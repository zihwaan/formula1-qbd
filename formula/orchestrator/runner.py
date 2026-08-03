"""그래프 실행 진입점 — CLI 데모와 웹 서버가 공유한다.

`run()`은 비동기 제너레이터로 `TraceEvent`를 흘리면서 마지막에 최종 상태를 남긴다.
웹 계층은 이걸 그대로 SSE로 중계하고, CLI 데모는 콘솔에 출력한다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from formula.checkers.registry import RulebookRegistry
from formula.contracts import (
    ConfirmationResult,
    EventKind,
    EvidenceAssessment,
    TraceEvent,
)
from formula.evidence.gate import EvidenceGate
from formula.orchestrator.events import EventBus
from formula.orchestrator.graph import build_graph
from formula.orchestrator.state import new_state


class Run:
    """한 번의 설계 실행. 이벤트 이력을 보관해 재생(replay)에 쓴다.

    실행이 끝난 뒤에도 살아 있는 상태가 둘 있다 — 후보별 **근거 판정**과 연구자가 되돌려
    넣은 **확인시험 결과**다. 실험 전 루프(확인시험 → 근거 재평가 → 승인)는 그래프를 다시
    돌리지 않고 이 두 값 위에서 결정론적으로 계산된다.
    """

    def __init__(self, base_dir: Path, request: str, smiles: Optional[str] = None,
                 run_id: Optional[str] = None, required_excipients: Optional[List[str]] = None):
        self.base_dir = Path(base_dir)
        self.state = new_state(request, smiles=smiles, run_id=run_id,
                               required_excipients=required_excipients)
        self.run_id: str = self.state["run_id"]
        self.bus = EventBus(self.run_id)
        self.final: Dict[str, Any] = {}
        self.registry = RulebookRegistry(self.base_dir / "config" / "rulebook_manifest.yaml",
                                         base_dir=self.base_dir)
        self.evidence_gate = EvidenceGate(self.base_dir)
        # candidate_id → {assessment, spec, recipe, derived} — 근거 노드가 판정하는 즉시 채운다.
        # 최종 state를 기다리면, 화면엔 확인시험 요청이 떠 있는데 서버는 "판정 없음"이라고
        # 답하는 구간이 생긴다(심사·합의가 도는 동안). 실제 라이브에서 그 구간을 밟았다.
        self.evidence_store: Dict[str, Dict[str, Any]] = {}
        # candidate_id → {requirement_id → ConfirmationResult}
        self.confirmations: Dict[str, Dict[str, ConfirmationResult]] = {}

    async def stream(self) -> AsyncIterator[TraceEvent]:
        """그래프를 돌리며 TraceEvent를 흘린다."""
        graph = build_graph(self.base_dir, self.registry, self.evidence_gate, self.evidence_store)
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        # 노드는 동기 함수라 별도 스레드에서 emit된다 → 스레드 안전하게 큐로 넘긴다
        self.bus.subscribe(lambda event: loop.call_soon_threadsafe(queue.put_nowait, event))

        async def drive() -> None:
            with self.bus:
                self.bus.publish(TraceEvent(run_id=self.run_id, node="run",
                                            kind=EventKind.RUN_START,
                                            payload={"request": self.state["request"]}))
                try:
                    self.final = await graph.ainvoke(self.state, {"recursion_limit": 60})
                except Exception as exc:
                    self.bus.publish(TraceEvent(run_id=self.run_id, node="run",
                                                kind=EventKind.ERROR,
                                                payload={"error": str(exc)}))
                    self.final = {**self.state, "status": "error"}
                self.bus.publish(TraceEvent(run_id=self.run_id, node="run",
                                            kind=EventKind.RUN_END,
                                            payload=self.summary()))
            await queue.put(None)

        task = asyncio.create_task(drive())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            await task

    def summary(self) -> Dict[str, Any]:
        final = self.final or {}
        consensus = final.get("consensus") or {}
        winner = final.get("final_candidate")
        assessment = self.assessment(winner) if winner else None
        return {
            "run_id": self.run_id,
            "status": final.get("status", "unknown"),
            "winner": winner,
            "reflection_count": final.get("reflection_count", 0),
            "candidates": [c.candidate_id for c in final.get("candidates", [])],
            "ranked": consensus.get("ranked", []),
            "rulebook_feedback": consensus.get("rulebook_feedback", []),
            # 실행 가능 여부는 합의가 아니라 근거 게이트가 정한다.
            "readiness": assessment.readiness.value if assessment else final.get("readiness", ""),
            "evidence_summary": assessment.summary if assessment else "",
        }

    # ── 실험 전 루프 (확인시험 → 근거 재평가 → 연구자 승인) ──────────────
    def assessment(self, candidate_id: str) -> Optional[EvidenceAssessment]:
        """근거 판정. 실행 중에도 조회되므로 store가 우선이고 최종 state는 폴백이다."""
        entry = self.evidence_store.get(candidate_id)
        if entry:
            return entry["assessment"]
        return (self.final.get("evidence") or {}).get(candidate_id)

    def _inputs_for(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        """재평가에 필요한 입력(spec·recipe·derived)을 store 또는 최종 state에서 찾는다."""
        entry = self.evidence_store.get(candidate_id)
        if entry:
            return entry
        for result in (self.final.get("results") or []):
            if result.get("candidate_id") == candidate_id:
                return {"spec": self.final.get("spec"), "recipe": result["recipe"],
                        "derived": result.get("derived")}
        return None

    def reassess(self, candidate_id: str) -> EvidenceAssessment:
        """확인시험 결과를 반영해 근거 판정을 다시 계산한다.

        그래프를 다시 돌리지 않는다 — 이 계층은 결정론이라 같은 입력이면 같은 판정이고,
        새로 들어온 것은 확인시험 결과뿐이기 때문이다. 판정이 바뀌면 그 자리에서 상태가
        '실행 불가 초안 → 검토용 프로토콜'로 올라간다.
        """
        inputs = self._inputs_for(candidate_id)
        if inputs is None or inputs.get("spec") is None:
            raise KeyError(candidate_id)
        assessment = self.evidence_gate.assess(
            inputs["spec"], inputs["recipe"], inputs.get("derived"),
            resolved=self.confirmations.get(candidate_id, {}),
        )
        self.evidence_store[candidate_id] = {**inputs, "assessment": assessment}
        (self.final.setdefault("evidence", {}))[candidate_id] = assessment
        return assessment

    def approve(self, candidate_id: str, approver: str = "researcher") -> EvidenceAssessment:
        """연구자 승인 — 근거가 충족된 후보만 실행 가능 프로토콜로 올린다."""
        assessment = self.assessment(candidate_id)
        if assessment is None:
            raise KeyError(candidate_id)
        return self.evidence_gate.approve(assessment, approver)


async def run(base_dir: Path, request: str, smiles: Optional[str] = None) -> Run:
    """편의 함수 — 이벤트를 소비하지 않고 끝까지 돌린다."""
    execution = Run(base_dir, request, smiles=smiles)
    async for _ in execution.stream():
        pass
    return execution
