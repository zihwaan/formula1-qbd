"""그래프 실행 진입점 — CLI 데모와 웹 서버가 공유한다.

`run()`은 비동기 제너레이터로 `TraceEvent`를 흘리면서 마지막에 최종 상태를 남긴다.
웹 계층은 이걸 그대로 SSE로 중계하고, CLI 데모는 콘솔에 출력한다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from formula.agents import generator
from formula.biopharm.triggers import group_requests
from formula.checkers.registry import RulebookRegistry
from formula.contracts import (
    ConfirmationResult,
    EventKind,
    EvidenceAssessment,
    TraceEvent,
)
from formula.evidence.gate import EvidenceGate
from formula.agents.client import use_llm
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
                 run_id: Optional[str] = None, required_excipients: Optional[List[str]] = None,
                 measured_params: Optional[Dict[str, float]] = None,
                 property_flags: Optional[Dict[str, bool]] = None,
                 llm: str = "groq"):
        self.base_dir = Path(base_dir)
        self.llm = llm            # 화면에서 고른 모델("groq" | "dacon") — 권한 검사는 서버가 끝냈다
        self.state = new_state(request, smiles=smiles, run_id=run_id,
                               required_excipients=required_excipients,
                               measured_params=measured_params, property_flags=property_flags)
        self.run_id: str = self.state["run_id"]
        self.bus = EventBus(self.run_id)
        self.declined: set = set()   # 연구자가 건너뛴 데이터 요청 trigger_id
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
        # candidate_id → 확인시험 결과가 실측값 자리에 꽂힌 내역 (화면에 그대로 보여준다)
        self.applied_results: Dict[str, Dict[str, float]] = {}

    async def stream(self) -> AsyncIterator[TraceEvent]:
        """그래프를 돌리며 TraceEvent를 흘린다."""
        graph = build_graph(self.base_dir, self.registry, self.evidence_gate, self.evidence_store)
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        # 노드는 동기 함수라 별도 스레드에서 emit된다 → 스레드 안전하게 큐로 넘긴다
        self.bus.subscribe(lambda event: loop.call_soon_threadsafe(queue.put_nowait, event))

        async def drive() -> None:
            with self.bus, use_llm(self.llm):
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
            # RUN_END 배달도 다른 이벤트와 같은 call_soon_threadsafe 큐를 타야 한다.
            # `await queue.put(None)`은 큐가 안 찼으면 즉시(스케줄 지연 없이) put_nowait로
            # 끝나는데, 바로 위 publish()가 건 call_soon_threadsafe(RUN_END)는 다음 루프
            # 틱에야 실행된다 — 그래서 종료 신호(None)가 RUN_END를 추월해 먼저 큐에 들어갈
            # 수 있었다. 소비자가 None을 먼저 받아 while 루프를 끝내면 RUN_END는 아예
            # yield되지 않는다 — 후속 이벤트가 적어 "다음 틱"까지 갈 일이 없는 빠른 실행
            # (예: 심사관이 적은 요청)일수록 이 창이 실제로 열렸다. 같은 스케줄링 경로로
            # 보내야 발행 순서가 곧 큐 순서가 된다.
            loop.call_soon_threadsafe(queue.put_nowait, None)

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
        winner_result = next((r for r in final.get("results", [])
                              if r.get("candidate_id") == winner), None)
        winner_recipe = winner_result["recipe"] if winner_result else None
        return {
            "run_id": self.run_id,
            "status": final.get("status", "unknown"),
            "winner": winner,
            "reflection_count": final.get("reflection_count", 0),
            "candidates": [c.candidate_id for c in final.get("candidates", [])],
            "ranked": consensus.get("ranked", []),
            "rulebook_feedback": consensus.get("rulebook_feedback", []),
            # 출력 경계는 후보 처방 목록 — 권고 후보의 신뢰도 태그와 남은 요청을 낸다.
            "confidence": winner_recipe.confidence if winner_recipe else "",
            "pending_refinements": winner_recipe.pending_refinements if winner_recipe else [],
            "pending_requests": [r for r in final.get("pending_narrow", [])
                                 if r.get("trigger_id") not in self.declined],
            "request_groups": group_requests(final.get("pending_narrow", []), self.base_dir, list(self.declined)),
            "declined": sorted(self.declined),
            "plan_signature": final.get("plan_signature", ""),
            "strategies": final.get("strategies", []),
            "constraints": final.get("constraints", {}),
            "backtrack": final.get("backtrack", {}),
        }

    def decline(self, trigger_ids: List[str]) -> Dict[str, Any]:
        """연구자가 요청을 건너뛴다 — 멈추지 않고 예측값으로 계속한다(후보는 provisional 유지)."""
        known = {r.get("trigger_id") for r in (self.final or {}).get("pending_narrow", [])}
        for t in trigger_ids:
            if t in known:
                self.declined.add(t)
        return self.summary()

    # ── v3 데이터 요청 재계산 (§4.1) ──────────────────────────────────
    def reassess_with_measurements(self, measurements: Dict[str, float]) -> Dict[str, Any]:
        """같은 run의 모델 선택으로 재계산한다(재설계가 필요하면 그 모델로 다시 생성)."""
        with use_llm(self.llm):
            return self._reassess_with_measurements(measurements)

    def _reassess_with_measurements(self, measurements: Dict[str, float]) -> Dict[str, Any]:
        """narrows_strategy 요청에 대한 실측값을 반영해 다시 계산한다.

        그래프를 다시 돌리지 않는다 — phase_gates·gate·drq_refine은 전부 결정론이라
        같은 입력이면 같은 결과이기 때문이다. `plan_signature`가 이전과 같으면(전략
        *집합*이 안 바뀌었으면) 신뢰도 태그만 다시 매긴다. 바뀌었으면 GEN부터 다시
        돌린다 — LLM 호출이 실제로 필요한 경우에만 재생성한다(가이드 §4.1).
        """
        from formula.biopharm import evaluate_triggers, run_biopharm_gates, seed_known_keys
        from formula.biopharm.derived import compute_derived_quantities
        from formula.checkers.applies_when import spec_context
        from formula.planner import strategy_planner

        from formula.biopharm.triggers import load_measurement_catalog
        from formula.planner import backtrack as backtrack_mod

        spec = self.final.get("spec")
        if spec is None:
            raise KeyError("spec")
        for key, value in measurements.items():
            if isinstance(value, bool):
                spec.properties[str(key)] = value
            elif isinstance(value, (int, float)):
                spec.measured_params[str(key)] = float(value)
            else:
                spec.properties[str(key)] = str(value)   # 결정형 ID 같은 문자열 결과

        ctx: Dict[str, Any] = spec_context(spec, {})
        seed_known_keys(ctx, self.base_dir)
        compute_derived_quantities(ctx, self.base_dir)
        from formula.contracts import Recipe as _Recipe
        route_probe = _Recipe(api_name=spec.api_name, candidate_id="__reassess_probe__")
        route_result = self.registry.run(spec, route_probe, short_circuit=False,
                                         derived=dict(ctx), max_priority=11)
        ctx.update({k: v for k, v in route_result.derived.items()
                   if k != "candidate_id" and not str(k).startswith("_")})
        ctx.setdefault("recommended_routes", [])
        ctx.setdefault("excluded_routes", [])
        # 유동성 자료가 없어 경로 결정트리가 아무것도 권하지 못하면 좁히지 않고 넓힌다 —
        # 세 경로를 모두 잠정 후보로 열고(routes_provisional), 유동성 측정 요청(DRQ_PFLOW)이 좁힌다.
        if not ctx["recommended_routes"] and not ctx.get("flow_character"):
            ctx["recommended_routes"] = [r for r in ("DC", "DG", "WG") if r not in ctx["excluded_routes"]]
            ctx["routes_provisional"] = True
        run_biopharm_gates(ctx, self.base_dir)

        profile = self.final.get("api_profile")
        flag_names = profile.flag_names() if profile else []
        pending_narrow = evaluate_triggers(ctx, "narrows_strategy", self.base_dir, flags=flag_names)
        # 측정 결과가 전략의 전제를 부정하면(ASD 비혼화 등) 되돌림 표대로 그 전략을 빼거나 감점한다
        decisions = backtrack_mod.match_measurements(dict(measurements), self.final.get("strategies", []),
                                                     self.base_dir, load_measurement_catalog(self.base_dir))
        constraints = dict(self.final.get("constraints") or {})
        for d in decisions:
            constraints = backtrack_mod.apply(constraints, d.patch)
        self.final["constraints"] = constraints
        if decisions:
            self.final["backtrack"] = {"from_measurement": True, "decisions": [d.as_dict() for d in decisions]}
        planned = strategy_planner.plan(ctx, self.base_dir, constraints=constraints)
        new_signature = strategy_planner.signature(planned)
        old_signature = self.final.get("plan_signature", "")

        public_derived = {k: v for k, v in ctx.items() if not str(k).startswith("_")}
        self.final["phase_derived"] = public_derived
        self.final["pending_narrow"] = [p.model_dump(mode="json") for p in pending_narrow]
        self.final["plan_signature"] = new_signature

        if not planned:
            self.final["status"] = "qtpp_review"
            self.final["strategies"] = []
            return {"regenerated": False, "qtpp_review": True, "plan_signature": new_signature,
                    "backtrack": [d.as_dict() for d in decisions],
                    "pending_requests": self.final["pending_narrow"], "summary": self.summary()}
        self.final["strategies"] = [p.strategy_code for p in planned]
        if new_signature == old_signature:
            # 전략 집합 불변 — 기존 후보들의 confidence만 다시 매긴다(LLM 호출 없음).
            for result in self.final.get("results", []):
                if not result.get("passed"):
                    continue
                recipe: Recipe = result["recipe"]
                rctx = {**public_derived, **(result.get("derived") or {})}
                pending = evaluate_triggers(rctx, "refines_confidence", self.base_dir,
                                            strategy=recipe.strategy, flags=flag_names)
                recipe.pending_refinements = [p.trigger_id for p in pending]
                recipe.confidence = "grounded" if not pending else "provisional"
            regenerated = False
        else:
            # 전략 집합이 바뀌었다 — 새 전략들로 후보를 다시 생성하고 두 게이트를 다시 돈다.
            new_candidates = []
            new_results = []
            for planned_strategy in planned:
                candidate_id = f"cand-reassess-{planned_strategy.strategy_code}"
                recipe = generator.generate(spec, planned_strategy.strategy_code, self.base_dir,
                                            candidate_id)
                if recipe is None:
                    continue   # LLM 무응답 — 이 전략 후보는 만들지 않는다(대신 채우지 않음)
                gate = self.registry.run(spec, recipe, short_circuit=False, derived=dict(public_derived))
                result = {
                    "candidate_id": recipe.candidate_id, "recipe": recipe,
                    "verdicts": gate.verdicts,
                    "derived": {k: v for k, v in gate.derived.items()
                               if k != "candidate_id" and not str(k).startswith("_")},
                    "passed": gate.passed,
                    "blockers": [f"{v.rulebook_id}/{v.rule_id}: {v.reason}" for v in gate.blockers],
                }
                if gate.passed:
                    rctx = {**public_derived, **result["derived"]}
                    pending = evaluate_triggers(rctx, "refines_confidence", self.base_dir,
                                                strategy=recipe.strategy, flags=flag_names)
                    recipe.pending_refinements = [p.trigger_id for p in pending]
                    recipe.confidence = "grounded" if not pending else "provisional"
                new_candidates.append(recipe)
                new_results.append(result)
            self.final["candidates"] = new_candidates
            self.final["results"] = new_results
            from formula.agents import consensus as consensus_mod
            summary = consensus_mod.build_consensus(new_results, [], self.base_dir)
            winner_result = next((r for r in new_results if r["candidate_id"] == summary.get("winner")), None)
            if winner_result is not None:
                summary["confidence"] = winner_result["recipe"].confidence
                summary["pending_refinements"] = winner_result["recipe"].pending_refinements
            self.final["consensus"] = summary
            self.final["final_candidate"] = summary["winner"]
            passed_any = any(r["passed"] for r in new_results)
            self.final["status"] = ("passed" if summary["winner"] else
                                    "passed_unranked" if passed_any else
                                    "no_design" if not new_results else "rejected")
            regenerated = True

        return {"regenerated": regenerated, "plan_signature": new_signature,
                "backtrack": [d.as_dict() for d in decisions],
                "pending_requests": self.final["pending_narrow"], "summary": self.summary()}

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
        resolved = self.confirmations.get(candidate_id, {})
        self.applied_results[candidate_id] = self._apply_results(inputs["spec"], resolved)
        assessment = self.evidence_gate.assess(
            inputs["spec"], inputs["recipe"], inputs.get("derived"), resolved=resolved,
        )
        self.evidence_store[candidate_id] = {**inputs, "assessment": assessment}
        (self.final.setdefault("evidence", {}))[candidate_id] = assessment
        return assessment

    def _apply_results(self, spec: Any,
                       resolved: Dict[str, ConfirmationResult]) -> Dict[str, float]:
        """확인시험 결과를 **스펙의 실측값 자리**에 꽂는다.

        "확인시험 결과는 입력·근거 계층으로 돌아간다"를 문장이 아니라 데이터 이동으로
        구현하는 지점이다. 값이 실측값으로 들어가면 요구의 충족 조건(`satisfied_when`)이
        표시가 아니라 실제로 참이 되고, 다음 실행의 룰 판정에도 같은 값이 쓰인다.
        부적합(fail) 결과는 넣지 않는다 — 그건 근거 확보가 아니라 전제의 부정이다.
        """
        applied: Dict[str, float] = {}
        by_id = {row["requirement_id"]: row for row in self.evidence_gate.requirements}
        for requirement_id, result in resolved.items():
            row = by_id.get(requirement_id)
            key = (row or {}).get("result_key", "")
            if not key or result.outcome != "pass":
                continue
            # 수치가 오면 그대로, 안 오면 "수행함"을 1로 기록한다(불리언형 요구).
            value = result.value_num if result.value_num is not None else 1.0
            spec.measured_params[key] = float(value)
            applied[key] = float(value)
        return applied

    def approve(self, candidate_id: str, approver: str = "researcher") -> EvidenceAssessment:
        """연구자 승인 — 근거가 충족된 후보만 실행 가능 프로토콜로 올린다."""
        assessment = self.assessment(candidate_id)
        if assessment is None:
            raise KeyError(candidate_id)
        return self.evidence_gate.approve(assessment, approver)

    def regenerate_child(self, parent_candidate_id: str, child_candidate_id: str,
                         directive: Dict[str, Any]):
        """확인된 실험 원인으로 자식 후보 1건을 만들고 두 게이트를 전부 다시 실행한다.

        첫 실패를 곧바로 여기로 보내면 안 된다. API는 Lifecycle이 ROOT_CAUSE_CONFIRMED로
        전이한 뒤에만 이 메서드를 호출한다.
        """
        spec = self.final.get("spec")
        parent = next((c for c in self.final.get("candidates", [])
                       if c.candidate_id == parent_candidate_id), None)
        if spec is None or parent is None:
            raise KeyError(parent_candidate_id)
        instruction = str(directive.get("instruction") or "확인된 원인을 반영해 재설계")
        recipe = generator.generate(
            spec, parent.strategy or parent.process or "DC", self.base_dir,
            child_candidate_id, instruction,
        )
        gate = self.registry.run(spec, recipe, short_circuit=False)
        gate_result = {
            "candidate_id": recipe.candidate_id,
            "recipe": recipe,
            "verdicts": gate.verdicts,
            "derived": {k: v for k, v in gate.derived.items()
                        if k != "candidate_id" and not str(k).startswith("_")},
            "passed": gate.passed,
            "blockers": [f"{v.rulebook_id}/{v.rule_id}: {v.reason}" for v in gate.blockers],
        }
        assessment = None
        if gate.passed:
            assessment = self.evidence_gate.assess(spec, recipe, gate_result["derived"])
            self.evidence_store[recipe.candidate_id] = {
                "assessment": assessment, "spec": spec, "recipe": recipe,
                "derived": gate_result["derived"],
            }
        self.final.setdefault("candidates", []).append(recipe)
        self.final.setdefault("results", []).append(gate_result)
        self.final["final_candidate"] = recipe.candidate_id
        return recipe, gate_result, assessment


async def run(base_dir: Path, request: str, smiles: Optional[str] = None) -> Run:
    """편의 함수 — 이벤트를 소비하지 않고 끝까지 돌린다."""
    execution = Run(base_dir, request, smiles=smiles)
    async for _ in execution.stream():
        pass
    return execution
