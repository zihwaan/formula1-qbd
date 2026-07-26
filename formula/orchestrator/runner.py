"""그래프 실행 진입점 — CLI 데모와 웹 서버가 공유한다.

`run()`은 비동기 제너레이터로 `TraceEvent`를 흘리면서 마지막에 최종 상태를 남긴다.
웹 계층은 이걸 그대로 SSE로 중계하고, CLI 데모는 콘솔에 출력한다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

from formula.checkers.registry import RulebookRegistry
from formula.contracts import EventKind, TraceEvent
from formula.orchestrator.events import EventBus
from formula.orchestrator.graph import build_graph
from formula.orchestrator.state import new_state


class Run:
    """한 번의 설계 실행. 이벤트 이력을 보관해 재생(replay)에 쓴다."""

    def __init__(self, base_dir: Path, request: str, smiles: Optional[str] = None,
                 run_id: Optional[str] = None):
        self.base_dir = Path(base_dir)
        self.state = new_state(request, smiles=smiles, run_id=run_id)
        self.run_id: str = self.state["run_id"]
        self.bus = EventBus(self.run_id)
        self.final: Dict[str, Any] = {}
        self.registry = RulebookRegistry(self.base_dir / "config" / "rulebook_manifest.yaml",
                                         base_dir=self.base_dir)

    async def stream(self) -> AsyncIterator[TraceEvent]:
        """그래프를 돌리며 TraceEvent를 흘린다."""
        graph = build_graph(self.base_dir, self.registry)
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
        return {
            "run_id": self.run_id,
            "status": final.get("status", "unknown"),
            "winner": final.get("final_candidate"),
            "reflection_count": final.get("reflection_count", 0),
            "candidates": [c.candidate_id for c in final.get("candidates", [])],
            "ranked": consensus.get("ranked", []),
            "rulebook_feedback": consensus.get("rulebook_feedback", []),
        }


async def run(base_dir: Path, request: str, smiles: Optional[str] = None) -> Run:
    """편의 함수 — 이벤트를 소비하지 않고 끝까지 돌린다."""
    execution = Run(base_dir, request, smiles=smiles)
    async for _ in execution.stream():
        pass
    return execution
