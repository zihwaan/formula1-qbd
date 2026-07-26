"""LangGraph StateGraph — 설계 → 검증 → 심사 → 합의 → 반성 루프.

    intake ─→ route ─→ generate ──(Send ×N)──→ gate ─┬─(통과)→ summon ──(Send ×M)──→ consensus ─→ END
                          ↑                          │
                          └──────── reflect ←────────┘ (HARD_FAIL, 최대 5회)

병렬 팬아웃은 LangGraph의 `Send`로 한다. 설계 후보 N개와 심사관 M명이 동시에 돌고,
결과는 state의 reducer(operator.add)로 합쳐진다.

**결정론 경계**: route/gate/consensus 노드는 순수 파이썬이다. LLM은 generate/judge/reflect에만 있다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from formula.agents import consensus as consensus_mod
from formula.agents import generator, intake, judge, reflect
from formula.checkers.registry import RulebookRegistry
from formula.contracts import EventKind, Recipe
from formula.orchestrator.events import emit
from formula.orchestrator.state import MAX_REFLECTION_LOOPS, FormulationState


def build_graph(base_dir: Path, registry: RulebookRegistry):
    """그래프를 조립해 컴파일한다. base_dir/registry는 클로저로 노드에 주입한다."""

    # ── P0 · 입력 번역 + RDKit 물성 ────────────────────────────────────
    def node_intake(state: FormulationState) -> Dict[str, Any]:
        spec = intake.translate(state["request"], base_dir, smiles=state.get("smiles"))
        return {"spec": spec, "api_profile": spec.api_profile}

    # ── P1 · 공정 경로 분기 (결정론) ───────────────────────────────────
    def node_route(state: FormulationState) -> Dict[str, Any]:
        """후보를 만들기 전에 유동성 등급과 가능한 공정 경로를 먼저 확정한다.

        아직 처방이 없으므로 빈 처방으로 경로 규칙만 돌린다 — 이 단계 규칙들은
        API 물성만 보기 때문에 성분이 없어도 판정이 성립한다.
        """
        emit("route", EventKind.NODE_ENTER)
        spec = state["spec"]
        probe = Recipe(api_name=spec.api_name, candidate_id="__route_probe__")
        # 성분이 아직 없으므로 API 물성만 보는 앞단(우선순위 ≤ 11)만 돌린다 —
        # 배합금기·배합비 규칙을 빈 처방에 돌리는 낭비를 막는다.
        result = registry.run(spec, probe, short_circuit=False, max_priority=11)
        derived = {k: v for k, v in result.derived.items() if k != "candidate_id"}
        strategies = generator.plan_strategies(spec, derived)
        emit("route", EventKind.NODE_EXIT, derived=derived, strategies=strategies)
        return {"strategies": strategies}

    # ── P2 · 설계 후보 병렬 생성 (LLM) ─────────────────────────────────
    def fan_out_generators(state: FormulationState) -> List[Send]:
        attempt = state.get("reflection_count", 0)
        return [
            Send("generate", {
                "spec": state["spec"],
                "strategy": strategy,
                "candidate_id": f"cand-{attempt}-{strategy}",
                "directive": state.get("reflection_directive", ""),
            })
            for strategy in state.get("strategies") or ["DC"]
        ]

    def node_generate(payload: Dict[str, Any]) -> Dict[str, Any]:
        recipe = generator.generate(
            payload["spec"], payload["strategy"], base_dir,
            payload["candidate_id"], payload.get("directive", ""),
        )
        return {"candidates": [recipe]}

    # ── P3 · 결정론 게이트 (순수 파이썬, 오차 0%) ──────────────────────
    def node_gate(state: FormulationState) -> Dict[str, Any]:
        emit("gate", EventKind.NODE_ENTER, candidates=len(state.get("candidates", [])))
        spec = state["spec"]
        results: List[Dict[str, Any]] = []

        for recipe in state.get("candidates", []):
            def on_verdict(verdict, candidate_id=recipe.candidate_id):
                if verdict.rule_id:  # 합성 통과 판정은 UI에 흘리지 않는다
                    emit("gate", EventKind.RULE_FIRED, candidate_id=candidate_id,
                         **verdict.model_dump(mode="json"))

            gate = registry.run(spec, recipe, short_circuit=False, on_verdict=on_verdict)
            results.append({
                "candidate_id": recipe.candidate_id,
                "recipe": recipe,
                "verdicts": gate.verdicts,
                "derived": {k: v for k, v in gate.derived.items() if k != "candidate_id"},
                "passed": gate.passed,
                "blockers": [f"{v.rulebook_id}/{v.rule_id}: {v.reason}" for v in gate.blockers],
            })
            emit("gate", EventKind.VERDICT, candidate_id=recipe.candidate_id,
                 passed=gate.passed, total=len(gate.verdicts),
                 failures=len(gate.failures), blockers=len(gate.blockers),
                 skipped_rows=gate.skipped_rows)

        emit("gate", EventKind.NODE_EXIT, passed=sum(1 for r in results if r["passed"]))
        return {"results": results}

    # ── 분기: 통과 후보가 있으면 심사로, 없으면 반성으로 ────────────────
    def route_after_gate(state: FormulationState) -> str:
        results = state.get("results", [])
        if any(r["passed"] for r in results):
            return "summon"
        failures = [v for r in results for v in r["verdicts"] if v.failed]
        if reflect.should_escalate(failures):
            return "escalate"
        if state.get("reflection_count", 0) >= MAX_REFLECTION_LOOPS:
            return "exhausted"
        return "reflect"

    # ── P4 · 심사관 동적 소집 ──────────────────────────────────────────
    def node_summon(state: FormulationState) -> Dict[str, Any]:
        emit("summon", EventKind.NODE_ENTER)
        passed = [r for r in state.get("results", []) if r["passed"]]
        derived = passed[0]["derived"] if passed else {}
        judges = registry.active_judges(state["spec"], derived)
        emit("summon", EventKind.NODE_EXIT,
             summoned=[{"reviewer_id": j.reviewer_id, "persona": j.persona,
                        "weight": j.weight, "summon_condition": j.summon_condition}
                       for j in judges])
        return {"summoned": judges}

    def fan_out_judges(state: FormulationState) -> List[Send]:
        passed = [r for r in state.get("results", []) if r["passed"]]
        judges = state.get("summoned", [])
        if not judges or not passed:
            return [Send("consensus", state)]
        return [
            Send("judge", {"judge": j, "spec": state["spec"],
                           "recipe": r["recipe"], "verdicts": r["verdicts"]})
            for r in passed for j in judges
        ]

    def node_judge(payload: Dict[str, Any]) -> Dict[str, Any]:
        verdict = judge.evaluate(payload["judge"], payload["spec"],
                                 payload["recipe"], payload["verdicts"], base_dir)
        return {"judge_verdicts": [verdict]}

    # ── P5 · 합의 도출 (결정론) ────────────────────────────────────────
    def node_consensus(state: FormulationState) -> Dict[str, Any]:
        emit("consensus", EventKind.NODE_ENTER)
        summary = consensus_mod.build_consensus(
            state.get("results", []), state.get("judge_verdicts", []), base_dir)
        emit("consensus", EventKind.CONSENSUS, **summary)
        emit("consensus", EventKind.NODE_EXIT, winner=summary["winner"])
        return {"consensus": summary,
                "final_candidate": summary["winner"],
                "status": "passed" if summary["winner"] else "rejected"}

    # ── P6 · 반성 → 재설계 ────────────────────────────────────────────
    def node_reflect(state: FormulationState) -> Dict[str, Any]:
        failures = [v for r in state.get("results", []) for v in r["verdicts"] if v.failed]
        attempt = state.get("reflection_count", 0) + 1
        outcome = reflect.reflect(failures, base_dir, attempt)
        return {
            "reflection_count": attempt,
            "reflection_directive": outcome["directive"],
            "reject_reasons": [v.reason for v in failures if v.blocking],
            # 다음 라운드를 위해 후보/결과를 비운다.
            # reducer가 누적형이라 []로는 안 지워진다 — None이 초기화 센티널이다.
            "candidates": None,
            "results": None,
            "judge_verdicts": None,
        }

    def node_escalate(state: FormulationState) -> Dict[str, Any]:
        reasons = [v.reason for r in state.get("results", []) for v in r["verdicts"]
                   if v.status.value == "escalate"]
        emit("escalate", EventKind.WARNING, reason="사람 판단 필요", details=reasons)
        return {"status": "escalated"}

    def node_exhausted(state: FormulationState) -> Dict[str, Any]:
        emit("exhausted", EventKind.WARNING,
             reason=f"재설계 {MAX_REFLECTION_LOOPS}회 초과 — 사람에게 이관",
             reject_reasons=state.get("reject_reasons", []))
        return {"status": "exhausted"}

    # ── 그래프 조립 ────────────────────────────────────────────────────
    graph = StateGraph(FormulationState)
    for name, fn in [
        ("intake", node_intake), ("route", node_route), ("generate", node_generate),
        ("gate", node_gate), ("summon", node_summon), ("judge", node_judge),
        ("consensus", node_consensus), ("reflect", node_reflect),
        ("escalate", node_escalate), ("exhausted", node_exhausted),
    ]:
        graph.add_node(name, fn)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "route")
    graph.add_conditional_edges("route", fan_out_generators, ["generate"])
    graph.add_edge("generate", "gate")
    graph.add_conditional_edges("gate", route_after_gate,
                                ["summon", "reflect", "escalate", "exhausted"])
    graph.add_conditional_edges("summon", fan_out_judges, ["judge", "consensus"])
    graph.add_edge("judge", "consensus")
    graph.add_conditional_edges("reflect", fan_out_generators, ["generate"])
    graph.add_edge("consensus", END)
    graph.add_edge("escalate", END)
    graph.add_edge("exhausted", END)

    return graph.compile()
