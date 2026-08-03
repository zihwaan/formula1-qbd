"""LangGraph StateGraph — 설계 → 규칙 검증 → 근거 검증 → 심사 → 합의 → 반성 루프.

    intake ─→ route ─→ generate ──(Send ×N)──→ gate ─┬─(통과)→ evidence ─→ summon ──(Send ×M)──→ consensus ─→ END
                          ↑                          │
                          └──────── reflect ←────────┘ (HARD_FAIL, 최대 5회)

**게이트가 둘인 이유.** `gate`는 "지금 아는 정보 안에 금기·규제 위반이 있는가"를 묻고,
`evidence`는 "금기가 없더라도 이 전략을 실행할 만큼 실제로 알고 있는가"를 묻는다. 룰북 통과는
안전 확정이 아니라 *명시적 위반을 발견하지 못했다*는 뜻이고, 신약 API는 정보 자체가 없어서
위반이 안 잡히는 경우가 많다. 그래서 근거 게이트는 후보를 반려하지 않고 **실행을 보류**한다 —
반려 권한은 룰북에, 보류 권한은 근거 게이트에 둔다.

병렬 팬아웃은 LangGraph의 `Send`로 한다. 설계 후보 N개와 심사관 M명이 동시에 돌고,
결과는 state의 reducer(operator.add)로 합쳐진다.

**결정론 경계**: route/gate/evidence/consensus 노드는 순수 파이썬이다.
LLM은 generate/judge/reflect에만 있다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from formula.agents import consensus as consensus_mod
from formula.agents import generator, intake, judge, reflect
from formula.checkers.registry import RulebookRegistry
from formula.contracts import EventKind, ProtocolReadiness, Recipe
from formula.evidence.gate import EvidenceGate
from formula.orchestrator.events import emit
from formula.orchestrator.state import MAX_REFLECTION_LOOPS, FormulationState


def _summon_signals(registry: RulebookRegistry, passed: List[Dict[str, Any]]) -> Dict[str, Any]:
    """심사관 소집 조건에 쓰이는 두 신호를 게이트 결과에서 계산한다.

    - `regulatory_narrative_needed` — 규제 계층에서 서술형 판단이 필요한 지적이 남았는가.
      ESCALATE(사람 이관)나 regulatory 계층의 SOFT_FLAG가 그 신호다. 숫자로 못 끊은 규제
      판단이 남았다는 뜻이므로 규제 취지 심사관(REV004)이 볼 몫이다.
    - `novel_combination_not_in_rulebook` — 처방에 부형제 마스터가 모르는 성분이 있는가.
      룰북이 판정 근거를 갖지 못한 조합이라, 문헌 조사 심사관(REV005)에게 넘긴다.
    """
    signals = {"regulatory_narrative_needed": False,
               "novel_combination_not_in_rulebook": False}
    if not passed:
        return signals

    for result in passed:
        for verdict in result.get("verdicts", []):
            status = getattr(verdict, "status", None)
            layer = (getattr(verdict, "layer", "") or "").lower()
            value = getattr(status, "value", status)
            if value == "escalate" or (value == "soft_flag" and layer == "regulatory"):
                signals["regulatory_narrative_needed"] = True

    known = registry.known_excipients()
    if known:
        for result in passed:
            recipe = result.get("recipe")
            names = getattr(recipe, "ingredient_names", None)
            if not callable(names):
                continue
            for name in names():
                normalized = name.strip().lower()
                if normalized and normalized not in known:
                    signals["novel_combination_not_in_rulebook"] = True
                    break
    return signals


def _required_conflict(state: Dict[str, Any], failures: List[Any]) -> bool:
    """반려 사유가 사용자가 못 박은 성분을 직접 지목하는가.

    재설계 지시가 "그 성분을 빼라"로 수렴하는데 제약이 "반드시 넣어라"이면 루프는 영원히
    돌기만 한다. 첫 반려에서 바로 이 충돌을 알아채고 결론을 내야 한다.
    """
    spec = state.get("spec")
    pinned = [p.strip() for p in (getattr(spec, "required_excipients", []) or []) if p.strip()]
    if not pinned or not failures:
        return False
    haystack = " ".join(
        f"{v.reason or ''} {v.suggestion or ''} {(v.evidence or {})}" for v in failures
    ).lower()
    # 첫 단어로 비교한다 — "Lactose monohydrate" 제약과 규칙 사유의 "lactose"가 맞물리게.
    return any(p.split()[0].lower() in haystack for p in pinned)


def build_graph(base_dir: Path, registry: RulebookRegistry,
                evidence_gate: Optional[EvidenceGate] = None,
                evidence_store: Optional[Dict[str, Any]] = None):
    """그래프를 조립해 컴파일한다. base_dir/registry는 클로저로 노드에 주입한다.

    `evidence_store`를 주면 근거 판정이 나오는 **즉시** 그 딕셔너리에 후보별 판정과 재평가에
    필요한 입력(spec·recipe·derived)이 쌓인다. 실행 전 루프(확인시험 결과 입력)는 그래프가
    끝나기 전에도 열려 있으므로, 최종 state만 보고 있으면 화면에는 요청이 떠 있는데 서버는
    "판정 없음"이라고 답하는 구간이 생긴다.
    """

    evidence_gate = evidence_gate or EvidenceGate(base_dir)

    # ── P0 · 입력 번역 + RDKit 물성 ────────────────────────────────────
    def node_intake(state: FormulationState) -> Dict[str, Any]:
        spec = intake.translate(state["request"], base_dir, smiles=state.get("smiles"),
                                required_excipients=state.get("required_excipients"))
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

    # ── P4 · 근거 충족 게이트 (순수 파이썬) ────────────────────────────
    def node_evidence(state: FormulationState) -> Dict[str, Any]:
        """룰을 통과한 후보마다 "실행할 만큼 아는가"를 판정한다.

        여기서는 **반려하지 않는다.** 근거가 없다는 것은 처방이 틀렸다는 뜻이 아니라
        아직 실행 가능한 공정 프로토콜을 낼 수 없다는 뜻이므로, 후보는 그대로 심사·합의로
        보내고 상태만 '실행 불가 초안'으로 묶는다. 연구자가 받는 것은 초안 + 선행
        확인시험 요청이고, 그 결과가 들어오면 이 판정을 다시 계산한다.
        """
        emit("evidence", EventKind.NODE_ENTER)
        spec = state["spec"]
        assessments: Dict[str, Any] = {}

        for result in state.get("results", []):
            if not result.get("passed"):
                continue
            assessment = evidence_gate.assess(spec, result["recipe"], result.get("derived"))
            assessments[assessment.candidate_id] = assessment
            if evidence_store is not None:
                evidence_store[assessment.candidate_id] = {
                    "assessment": assessment, "spec": spec,
                    "recipe": result["recipe"], "derived": result.get("derived"),
                }
            payload = assessment.model_dump(mode="json")
            payload["protocol"] = evidence_gate.protocol(assessment)
            emit("evidence", EventKind.EVIDENCE, **payload)

        blocked = [a for a in assessments.values()
                   if a.readiness == ProtocolReadiness.BLOCKED]
        readiness = (ProtocolReadiness.BLOCKED.value if blocked and len(blocked) == len(assessments)
                     else ProtocolReadiness.READY_FOR_REVIEW.value) if assessments else ""
        emit("evidence", EventKind.NODE_EXIT,
             assessed=len(assessments), blocked=len(blocked), readiness=readiness)
        return {"evidence": assessments, "readiness": readiness}

    # ── 분기: 통과 후보가 있으면 근거 게이트로, 없으면 반성으로 ──────────
    def route_after_gate(state: FormulationState) -> str:
        results = state.get("results", [])
        if any(r["passed"] for r in results):
            return "evidence"
        failures = [v for r in results for v in r["verdicts"] if v.failed]

        # 사용자가 못 박은 성분 자체가 반려 사유라면 재설계로 풀릴 문제가 아니다.
        # 반성 루프를 5회 돌려 소진시키는 대신, 제약이 불가능하다는 결론을 바로 낸다 —
        # 연구원이 알아야 할 답은 "다시 설계했다"가 아니라 "이 제약으로는 통과가 없다"다.
        if _required_conflict(state, failures):
            return "infeasible"

        if reflect.should_escalate(failures):
            return "escalate"
        if state.get("reflection_count", 0) >= MAX_REFLECTION_LOOPS:
            return "exhausted"
        return "reflect"

    # ── P5 · 심사관 동적 소집 ──────────────────────────────────────────
    def node_summon(state: FormulationState) -> Dict[str, Any]:
        emit("summon", EventKind.NODE_ENTER)
        passed = [r for r in state.get("results", []) if r["passed"]]
        derived = dict(passed[0]["derived"]) if passed else {}

        # 명단의 소집 조건 중 두 개(`regulatory_narrative_needed`,
        # `novel_combination_not_in_rulebook`)는 어느 계층도 산출하지 않아서
        # REV004·REV005가 **구조적으로 소집될 수 없었다.** 게이트 결과와 부형제 마스터에서
        # 실제로 계산해 넣는다 — 조건을 없애는 게 아니라 근거를 만들어 주는 방향.
        derived.update(_summon_signals(registry, passed))

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

    # ── P6 · 합의 도출 (결정론) ────────────────────────────────────────
    def node_consensus(state: FormulationState) -> Dict[str, Any]:
        emit("consensus", EventKind.NODE_ENTER)
        summary = consensus_mod.build_consensus(
            state.get("results", []), state.get("judge_verdicts", []), base_dir)

        # 합의가 고르는 것은 **권고 후보**다. 실행 가능한 프로토콜인지는 근거 게이트가
        # 따로 정하므로, 선정 결과에 그 상태를 함께 실어 보낸다.
        assessment = (state.get("evidence") or {}).get(summary.get("winner"))
        if assessment is not None:
            summary["readiness"] = assessment.readiness.value
            summary["evidence_summary"] = assessment.summary
            summary["protocol"] = evidence_gate.protocol(assessment)

        emit("consensus", EventKind.CONSENSUS, **summary)
        emit("consensus", EventKind.NODE_EXIT, winner=summary["winner"])
        return {"consensus": summary,
                "final_candidate": summary["winner"],
                "status": "passed" if summary["winner"] else "rejected"}

    # ── P7 · 반성 → 재설계 ────────────────────────────────────────────
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

    def node_infeasible(state: FormulationState) -> Dict[str, Any]:
        """못 박은 제약이 검증된 규칙과 충돌 — 재설계로 해결되지 않는다는 결론.

        이건 실패 보고가 아니라 **판정**이다: 어떤 제약이 어떤 규칙과 왜 충돌하는지와
        규칙표가 제시하는 대체 부형제를 함께 내보낸다. 연구원은 제약을 풀지, 대체를
        승인할지 결정하면 된다.
        """
        results = state.get("results", [])
        failures = [v for r in results for v in r["verdicts"] if v.failed]
        pinned = list(getattr(state.get("spec"), "required_excipients", []) or [])
        blocking = [
            {
                "rule_id": v.rule_id,
                "rulebook_id": v.rulebook_id,
                "reason": v.reason,
                "suggestion": v.suggestion,
                "citation": v.citation,
            }
            for v in failures
            if any(p.split()[0].lower() in (v.reason or "").lower() for p in pinned if p.strip())
        ]
        emit("infeasible", EventKind.WARNING,
             reason=f"고정 제약({', '.join(pinned)})이 검증된 규칙과 충돌 — "
                    "이 제약을 유지하는 한 통과하는 처방이 없다",
             required_excipients=pinned,
             blocking=blocking or [
                 {"rule_id": v.rule_id, "reason": v.reason, "suggestion": v.suggestion}
                 for v in failures
             ])
        return {"status": "infeasible"}

    # ── 그래프 조립 ────────────────────────────────────────────────────
    graph = StateGraph(FormulationState)
    for name, fn in [
        ("intake", node_intake), ("route", node_route), ("generate", node_generate),
        ("gate", node_gate), ("evidence", node_evidence),
        ("summon", node_summon), ("judge", node_judge),
        ("consensus", node_consensus), ("reflect", node_reflect),
        ("escalate", node_escalate), ("exhausted", node_exhausted),
        ("infeasible", node_infeasible),
    ]:
        graph.add_node(name, fn)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "route")
    graph.add_conditional_edges("route", fan_out_generators, ["generate"])
    graph.add_edge("generate", "gate")
    graph.add_conditional_edges("gate", route_after_gate,
                                ["evidence", "reflect", "escalate", "exhausted", "infeasible"])
    graph.add_edge("evidence", "summon")
    graph.add_conditional_edges("summon", fan_out_judges, ["judge", "consensus"])
    graph.add_edge("judge", "consensus")
    graph.add_conditional_edges("reflect", fan_out_generators, ["generate"])
    graph.add_edge("consensus", END)
    graph.add_edge("escalate", END)
    graph.add_edge("exhausted", END)
    graph.add_edge("infeasible", END)

    return graph.compile()
