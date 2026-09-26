"""LangGraph StateGraph — v3: 페이즈 게이트 → 설계 → 규칙 검증 → 데이터 요청 → 심사 → 합의.

    intake ─→ phase_gates ─→ generate ──(Send ×N)──→ gate ─┬─(통과)→ drq_refine ─→ summon ──(Send ×M)──→ consensus ─→ END
                                ↑                          │
                                └──────── reflect ←────────┘ (HARD_FAIL, 최대 5회)

Formula1_v3/IMPLEMENTATION_GUIDE.md를 그대로 배선한 것이다. **출력 경계가 후보 처방
목록에서 끝난다** — `evidence`(근거 충족 게이트)·실행 가능 프로토콜·연구자 승인·배치
피드백 루프는 이 그래프에서 더 이상 호출하지 않는다(§1 "여기서 끝난다"). 그 계층의
코드(`formula/evidence/gate.py`, `formula/lifecycle/`)는 지우지 않고 그대로 남아 있다 —
와이어링만 빠졌다. 되돌릴 필요가 생기면 `node_evidence`를 다시 그래프에 연결하면 된다.

**`phase_gates`가 하는 일** (P0~P1~G3A~G3B~G4~G4B~G6R~DRQ_NARROW를 한 노드로 묶었다):
RDKit이 계산 가능한 파생값(`derived_quantities.csv`)을 전부 채우고, BCS/DCS·고체상·
가용화 전략·ASD 공정 신호(Gate 3A/3B/4/4B)를 순서대로 평가한 뒤, 판정이 실제로 갈리는
지점에서만 구체적 실측을 요청한다(`data_request_triggers.csv`, urgency=narrows_strategy).
**이 요청은 그래프를 절대 막지 않는다**(불변식 I-9) — `strategy_planner.plan()`은 요청
결과와 무관하게 항상 진행한다.

**`drq_refine`가 하는 일**(구 `evidence` 자리): 룰 게이트를 통과한 후보마다
`data_request_triggers.csv`(urgency=refines_confidence)를 평가해 `pending_refinements`를
채운다. 비어 있으면 `confidence="grounded"`, 하나라도 있으면 `"provisional"`이다
(불변식 I-10 — LLM이 이 값을 직접 정하지 않는다).

병렬 팬아웃은 LangGraph의 `Send`로 한다. 설계 후보 N개와 심사관 M명이 동시에 돌고,
결과는 state의 reducer(operator.add)로 합쳐진다.

**결정론 경계**: phase_gates/gate/drq_refine/consensus 노드는 순수 파이썬이다.
LLM은 generate/judge/reflect에만 있다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from formula.agents import consensus as consensus_mod
from formula.agents import generator, intake, judge, reflect
from formula.planner import backtrack as backtrack_mod
from formula.biopharm import (
    compute_derived_quantities,
    evaluate_triggers,
    run_biopharm_gates,
    seed_known_keys,
)
from formula.checkers.applies_when import spec_context
from formula.checkers.registry import RulebookRegistry
from formula.contracts import EventKind, ProtocolReadiness, Recipe  # noqa: F401 — evidence 노드가 여전히 참조(주석처리 보류)
from formula.evidence.gate import EvidenceGate
from formula.biopharm.structure import apply_structure_signals
from formula.orchestrator.events import emit
from formula.orchestrator.state import MAX_REFLECTION_LOOPS, FormulationState
from formula.planner import strategy_planner


def _public_derived(derived: Dict[str, Any]) -> Dict[str, Any]:
    """화면·이벤트로 내보낼 파생 state.

    `candidate_id`는 파생값이 아니라 실행 식별자고, `_`로 시작하는 키는 엔진 내부 배선
    (성분명 사전 등)이다. 둘 다 "룰이 산출한 값"이 아니므로 밖으로 내보내지 않는다.
    """
    return {k: v for k, v in (derived or {}).items()
            if k != "candidate_id" and not str(k).startswith("_")}


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

    for result in passed:
        recipe = result.get("recipe")
        for ingredient in (getattr(recipe, "ingredients", None) or []):
            name = str(getattr(ingredient, "name", "") or "").strip()
            # 주성분은 부형제 마스터에 있을 리가 없다 — 빼지 않으면 이 신호가 모든
            # 실행에서 참이 되어 REV005가 상시 소집된다(신호로서 무의미해진다).
            if not name or getattr(ingredient, "role", "") == "api":
                continue
            if name.lower() == str(getattr(recipe, "api_name", "") or "").strip().lower():
                continue
            # 표준명 사전으로 판별한다 — 소문자 문자열 비교로는 "유당"도 "Lactose, NF"도
            # 모르는 성분이 되어 역시 REV005가 헛소집된다(같은 결함의 반대 방향).
            if not registry.is_known_excipient(name):
                signals["novel_combination_not_in_rulebook"] = True
                break
    return signals


CONTRACT_RULEBOOKS = ("request_contract", "max_daily_dose")


def _dose_over_label(state: Dict[str, Any], failures: List[Any]) -> bool:
    """요청 용량 자체가 라벨 1일 최대 용량을 넘는가 — 그러면 다시 설계해도 통과가 없다."""
    from formula.checkers.contract import requested_dose
    spec = state.get("spec")
    if spec is None:
        return False
    req_fb, _, _ = requested_dose(spec)
    for v in failures:
        if v.rulebook_id == "max_daily_dose" and v.blocking and req_fb is not None:
            limit = (v.evidence or {}).get("max_daily_free_base_mg")
            if limit is not None and req_fb > float(limit):
                return True
    return False


def _required_conflict(state: Dict[str, Any], failures: List[Any]) -> bool:
    """반려 사유가 사용자가 못 박은 성분을 직접 지목하는가.

    재설계 지시가 "그 성분을 빼라"로 수렴하는데 제약이 "반드시 넣어라"이면 루프는 영원히
    돌기만 한다. 첫 반려에서 바로 이 충돌을 알아채고 결론을 내야 한다.
    """
    spec = state.get("spec")
    if _dose_over_label(state, failures):
        return True
    pinned = [p.strip() for p in (getattr(spec, "required_excipients", []) or []) if p.strip()]
    # 입력 계약 판정(고정 부형제 누락 등)은 "제약을 지켜 다시 설계하라"는 뜻이지 제약이 불가능하다는
    # 뜻이 아니다 — 그 사유 문구에 고정 성분 이름이 들어 있어도 충돌로 세지 않는다.
    failures = [v for v in failures if v.blocking and v.rulebook_id not in CONTRACT_RULEBOOKS]
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
                                required_excipients=state.get("required_excipients"),
                                measured_params=state.get("measured_params"),
                                property_flags=state.get("property_flags"),
                                dose_basis=state.get("dose_basis") or "free_base")
        return {"spec": spec, "api_profile": spec.api_profile}

    # ── P0/P1/G3A/G3B/G4/G4B/G6R/DRQ_NARROW · 페이즈 게이트 (결정론) ───
    def node_phase_gates(state: FormulationState) -> Dict[str, Any]:
        """후보를 만들기 전에 파생값·BCS/DCS·고체상·가용화 신호·공정 경로를 확정한다.

        v3 IMPLEMENTATION_GUIDE.md §3~§5. 여기서 만든 ctx(phase_derived)는 이후
        node_gate가 룰북을 돌릴 때도 시드로 넘어가므로, dose_solubility_volume 같은
        파생값이 있으면 기존 bcs_classification 같은 규칙도 (실측 조건을 만족하는 한)
        같은 세션에서 그대로 참조할 수 있다.
        """
        emit("phase_gates", EventKind.NODE_ENTER)
        spec = state["spec"]
        ctx: Dict[str, Any] = spec_context(spec, {})
        # "tm_c is None" 같은 조건이 NameError로 조용히 죽지 않도록, 알려진 모든 변수
        # 이름을 먼저 None으로 깔아 둔다 — formula/biopharm/seed.py의 함정 기록 참고.
        seed_known_keys(ctx, base_dir)
        # 구조 신호 — 이온화 가능 여부·문헌 BCS 표(biopharm/structure.py)
        apply_structure_signals(ctx, spec, base_dir)

        # P1 — RDKit이 계산 가능한 파생값(D0·SLAD·Tg 여유·logS 등)을 전부 채운다.
        compute_derived_quantities(ctx, base_dir)

        # G6R — 기존 공정 경로 결정트리(유동성 등급 → DC/DG/WG)를 그대로 재사용한다.
        # 아직 처방이 없으므로 빈 처방으로 경로 규칙만 돌린다.
        probe = Recipe(api_name=spec.api_name, candidate_id="__route_probe__")
        route_result = registry.run(spec, probe, short_circuit=False, derived=dict(ctx), max_priority=11)
        ctx.update(_public_derived(route_result.derived))
        # 유동성 입력(안식각·Carr·Hausner)이 경로 결정에 쓰였다는 사실을 트레이스에 남긴다 — 예전엔 계산은
        # 됐는데 화면에 흔적이 없어 "입력이 무시됐다"로 읽혔다(데모 결과 보고서 ①).
        flow_inputs = {k: spec.measured_params.get(k) for k in ("angle_of_repose", "compressibility_index",
                                                                 "hausner_ratio") if spec.measured_params.get(k) is not None}
        for v in (route_result.verdicts if flow_inputs else []):
            if v.rulebook_id in ("powder_flow_scale", "route_decision_tree"):
                emit("phase_gates", EventKind.PHASE_GATE, gate=v.rulebook_id, rule_id=v.rule_id or "—",
                     assigned={k: route_result.derived.get(k) for k in
                               (("flow_character",) if v.rulebook_id == "powder_flow_scale"
                                else ("selected_route", "recommended_routes", "excluded_routes"))},
                     action=v.action.value, rationale=v.reason, citation=v.citation,
                     inputs={k: spec.measured_params.get(k) for k in
                             ("angle_of_repose", "compressibility_index", "hausner_ratio")
                             if spec.measured_params.get(k) is not None})
        # 유동성 데이터가 전혀 없으면 decision_tree 전략이 아무 행도 발동시키지 못해
        # recommended_routes를 아예 안 남긴다 — strategy_families.csv의
        # `'DC' in recommended_routes` 같은 멤버십 조건은 None에 대해선 예외가 난다.
        # 빈 리스트로 두면 "권장 경로 없음"으로 정직하게 읽히고, 조건은 조용히 거짓이 된다.
        ctx.setdefault("recommended_routes", [])
        ctx.setdefault("excluded_routes", [])
        # 유동성 자료가 없어 경로 결정트리가 아무것도 권하지 못하면 좁히지 않고 넓힌다 —
        # 세 경로를 모두 잠정 후보로 열고(routes_provisional), 유동성 측정 요청(DRQ_PFLOW)이 좁힌다.
        if not ctx["recommended_routes"] and not ctx.get("flow_character"):
            ctx["recommended_routes"] = [r for r in ("DC", "DG", "WG") if r not in ctx["excluded_routes"]]
            ctx["routes_provisional"] = True

        # G3A → G3B → G4 → G4B — BCS/DCS·고체상·가용화 전략·ASD 공정 신호.
        # bcs_class(실측 전용, 불변식 I-1)는 여기서 절대 쓰지 않는다 — bcs_solubility_provisional 등
        # 전혀 다른 키에만 쓴다.
        fired = run_biopharm_gates(ctx, base_dir)
        for signal in fired:
            emit("phase_gates", EventKind.PHASE_GATE, gate=signal["gate"], rule_id=signal["rule_id"],
                 assigned=signal["assigned"], action=signal["action"], rationale=signal["rationale"],
                 citation=signal["citation"])

        public_derived = _public_derived(ctx)
        emit("phase_gates", EventKind.NODE_EXIT, derived=public_derived)
        return {"phase_derived": public_derived}

    # ── DRQ_NARROW — 전략을 좁히는 실측 요청 (비차단) ──────────────────
    def node_drq_narrow(state: FormulationState) -> Dict[str, Any]:
        """판정이 갈리는 지점의 실측만 요청한다. **그래프를 멈추지 않는다** — 다음은 항상 계획이다."""
        emit("drq_narrow", EventKind.NODE_ENTER)
        ctx = dict(state.get("phase_derived") or {})
        profile = state.get("api_profile")
        pending = evaluate_triggers(ctx, "narrows_strategy", base_dir,
                                    flags=profile.flag_names() if profile else [])
        payload = [p.model_dump(mode="json") for p in pending]
        emit("drq_narrow", EventKind.DATA_REQUEST, urgency="narrows_strategy", pending=payload)
        emit("drq_narrow", EventKind.NODE_EXIT, pending_narrow_count=len(pending))
        return {"pending_narrow": payload}

    # ── PLAN — 전략 채점 → 상위 3개 (같은 입력 = 같은 계획) ──────────────
    def node_plan(state: FormulationState) -> Dict[str, Any]:
        """strategy_families.csv로 전략을 채점한다. 되돌림이 쌓은 제약(전략·경로 제외, 가족 요구/감점)을
        그대로 반영한다. 살아남는 전략이 없으면 임의의 기본 전략을 지어내지 않고 QTPP 재검토로 보낸다."""
        emit("plan", EventKind.NODE_ENTER)
        constraints = state.get("constraints") or {}
        planned = strategy_planner.plan(dict(state.get("phase_derived") or {}), base_dir,
                                        constraints=constraints)
        strategies = [p.strategy_code for p in planned]
        sig = strategy_planner.signature(planned)
        emit("plan", EventKind.NODE_EXIT, strategies=strategies, plan_signature=sig,
             scores=[{"strategy": p.strategy_code, "family": p.family, "label": p.label_kr,
                      "score": p.score, "process_steps": p.process_steps,
                      "coverage": p.rulebook_coverage} for p in planned],
             constraints=constraints)
        return {"strategies": strategies, "plan_signature": sig,
                "planned": [{"strategy": p.strategy_code, "family": p.family,
                             "process_steps": p.process_steps, "coverage": p.rulebook_coverage}
                            for p in planned]}

    def route_after_plan(state: FormulationState):
        if not state.get("strategies"):
            return "qtpp_review"
        return fan_out_generators(state)

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
            for strategy in state.get("strategies") or []
            if strategy not in set((state.get("constraints") or {}).get("exclude_strategy", []))
        ]

    def node_generate(payload: Dict[str, Any]) -> Dict[str, Any]:
        recipe = generator.generate(
            payload["spec"], payload["strategy"], base_dir,
            payload["candidate_id"], payload.get("directive", ""),
        )
        return {"candidates": [recipe] if recipe is not None else []}

    # ── P3 · 결정론 게이트 (순수 파이썬, 오차 0%) ──────────────────────
    def node_gate(state: FormulationState) -> Dict[str, Any]:
        emit("gate", EventKind.NODE_ENTER, candidates=len(state.get("candidates", [])))
        spec = state["spec"]
        results: List[Dict[str, Any]] = []
        # phase_gates가 채운 D0·SLAD·bcs_solubility_provisional·dcs_* 등을 룰북 실행에도
        # 시드로 넘긴다 — 실측 전용 규칙(bcs_classification 등)은 그대로 실측 조건에 묶여
        # 있으므로 안전하게 섞일 수 있다(§8.1의 교훈: 파생값은 코드 순서가 아니라
        # 데이터/상태로 전달해야 한다).
        phase_derived = state.get("phase_derived") or {}

        for recipe in state.get("candidates", []):
            def on_verdict(verdict, candidate_id=recipe.candidate_id):
                if verdict.rule_id:  # 합성 통과 판정은 UI에 흘리지 않는다
                    emit("gate", EventKind.RULE_FIRED, candidate_id=candidate_id,
                         **verdict.model_dump(mode="json"))

            gate = registry.run(spec, recipe, short_circuit=False, derived=dict(phase_derived),
                                on_verdict=on_verdict)
            results.append({
                "candidate_id": recipe.candidate_id,
                "recipe": recipe,
                "verdicts": gate.verdicts,
                "derived": _public_derived(gate.derived),
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

    # ── DRQ_REFINE · 후보별 신뢰도 요청 (결정론) — v3에서 node_evidence를 대신한다 ──
    def node_drq_refine(state: FormulationState) -> Dict[str, Any]:
        """룰 게이트를 통과한 후보마다 "이 후보를 grounded로 부를 만큼 아는가"를 묻는다.

        v3 IMPLEMENTATION_GUIDE.md §3.3·§4.2. 여기서도 **반려하지 않는다** — 근거가
        없다는 것은 처방이 틀렸다는 뜻이 아니라 아직 확정적으로 말할 수 없다는 뜻이므로,
        후보는 그대로 심사·합의로 보내고 confidence만 provisional로 표시한다.
        """
        emit("drq_refine", EventKind.NODE_ENTER)
        phase_derived = dict(state.get("phase_derived") or {})
        planned_by_code = {p.strategy_code: p for p in
                           strategy_planner.plan(phase_derived, base_dir, max_strategies=99)}
        profile = state.get("api_profile")
        flag_names = profile.flag_names() if profile else []

        for result in state.get("results", []):
            if not result.get("passed"):
                continue
            recipe: Recipe = result["recipe"]
            ctx = {**phase_derived, **(result.get("derived") or {})}
            family = planned_by_code.get(recipe.strategy)
            process_steps = family.process_steps if family else ([recipe.process] if recipe.process else [])
            pending = evaluate_triggers(ctx, "refines_confidence", base_dir,
                                        strategy=recipe.strategy, process_steps=process_steps,
                                        flags=flag_names)
            recipe.pending_refinements = [p.trigger_id for p in pending]
            recipe.confidence = "grounded" if not pending else "provisional"
            emit("drq_refine", EventKind.DATA_REQUEST, candidate_id=recipe.candidate_id,
                 urgency="refines_confidence", confidence=recipe.confidence,
                 pending=[p.model_dump(mode="json") for p in pending])

        emit("drq_refine", EventKind.NODE_EXIT)
        return {}

    # ── 분기: 통과 후보가 있으면 신뢰도 요청으로, 없으면 반성으로 ────────
    def route_after_gate(state: FormulationState) -> str:
        results = state.get("results", [])
        if not results:
            return "no_design"   # 설계 LLM이 이번 라운드 후보를 하나도 내지 못했다
        if any(r["passed"] for r in results):
            return "drq_refine"
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
        return "backtrack"

    # ── BACKTRACK — 반려 사유별 복귀 지점 (backtrack_transitions.csv) ────────
    def node_backtrack(state: FormulationState) -> Dict[str, Any]:
        emit("backtrack", EventKind.NODE_ENTER)
        attempts = dict(state.get("phase_attempts") or {})
        decision = backtrack_mod.combine(
            backtrack_mod.match_rejection(state.get("results", []), base_dir), attempts)
        if decision is None:
            # 표에 없는 반려 — 같은 전략으로 성분만 다시 설계한다(가장 얕은 복귀)
            decision = backtrack_mod.Decision(transition_id="UNMAPPED", return_phase="GATE",
                                              directive_hint="반려 사유를 해소하도록 성분을 조정")
        attempts[decision.return_phase] = attempts.get(decision.return_phase, 0) + 1
        constraints = backtrack_mod.apply(state.get("constraints") or {}, decision.patch)
        emit("backtrack", EventKind.BACKTRACK, **decision.as_dict(), attempts=attempts,
             constraints=constraints)
        emit("backtrack", EventKind.NODE_EXIT, return_phase=decision.return_phase)
        return {"constraints": constraints, "phase_attempts": attempts, "backtrack": decision.as_dict()}

    def route_after_reflect(state: FormulationState):
        if (state.get("backtrack") or {}).get("return_phase", "GATE") == "GATE":
            sends = fan_out_generators(state)
            return sends or "plan"
        return "plan"

    def node_qtpp_review(state: FormulationState) -> Dict[str, Any]:
        emit("qtpp_review", EventKind.WARNING,
             reason="남은 전략이 없습니다 — 목표(QTPP) 재검토가 필요합니다. 용량·대상 환자·제형이나 "
                    "고정한 제약을 조정하거나, 전략을 가르는 실측값을 넣어 주세요.",
             constraints=state.get("constraints") or {})
        return {"status": "qtpp_review"}

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
        # 전략·페이즈 게이트에서 오는 소집 신호 — 가용화/미분화/ASD 후보, 룰북 커버리지 공백,
        # 고체상 구간(염·공결정 경계), 염 안정성 주의. 이게 없으면 REV002·REV005·REV007이
        # 조건식에서 참조하는 이름이 비어 영영 소집되지 않는다.
        phase = state.get("phase_derived") or {}
        families = {p["strategy"]: p for p in (state.get("planned") or [])}
        strategies = {getattr(r["recipe"], "strategy", "") for r in passed}
        fam = {s_: (families.get(s_) or {}).get("family", "") for s_ in strategies}
        derived.setdefault("solid_form_zone", phase.get("solid_form_zone"))
        derived.setdefault("salt_stability_watch", phase.get("salt_stability_watch"))
        derived["enabling_candidates_present"] = any(f == "ENABLING" for f in fam.values())
        derived["particle_size_candidates_present"] = any(f == "PARTICLE_SIZE" for f in fam.values())
        derived["asd_candidates_present"] = any(s_.startswith("ASD_") for s_ in strategies)
        # 전략이 요구하는 공정 규칙표가 룰북에 없으면(ASD·HME·CD 등) 커버리지 공백
        known = {e.id for e in registry.entries}
        derived["coverage_gap_present"] = any(
            c and c not in known for s_ in strategies for c in (families.get(s_) or {}).get("coverage", []))

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
        return {"judge_verdicts": [verdict] if verdict is not None else []}

    # ── P6 · 합의 도출 (결정론) ────────────────────────────────────────
    def node_consensus(state: FormulationState) -> Dict[str, Any]:
        emit("consensus", EventKind.NODE_ENTER)
        summary = consensus_mod.build_consensus(
            state.get("results", []), state.get("judge_verdicts", []), base_dir)

        # 후보 탐색의 출력 경계 — 권고 후보의 confidence 태그(grounded/provisional)와
        # 남은 데이터 요청을 함께 낸다. 개발은 연구자가 후보를 골라 ② 개발 스튜디오에서 한다.
        winner_result = next((r for r in state.get("results", [])
                              if r.get("candidate_id") == summary.get("winner")), None)
        if winner_result is not None:
            winner_recipe: Recipe = winner_result["recipe"]
            summary["confidence"] = winner_recipe.confidence
            summary["pending_refinements"] = winner_recipe.pending_refinements

        emit("consensus", EventKind.CONSENSUS, **summary)
        emit("consensus", EventKind.NODE_EXIT, winner=summary["winner"])
        return {"consensus": summary,
                "final_candidate": summary["winner"],
                # 통과 후보는 있는데 심사 점수가 하나도 없으면 "통과 · 순위 없음" — 반려가 아니다
                "status": "passed" if summary["winner"] else (
                    "passed_unranked" if any(r.get("unscored") for r in summary["ranked"]) else "rejected"),
                "pending_requests": state.get("pending_narrow", [])}

    # ── P7 · 반성 → 재설계 ────────────────────────────────────────────
    def node_reflect(state: FormulationState) -> Dict[str, Any]:
        failures = [v for r in state.get("results", []) for v in r["verdicts"] if v.failed]
        attempt = state.get("reflection_count", 0) + 1
        outcome = reflect.reflect(failures, base_dir, attempt)
        bt = state.get("backtrack") or {}
        constraints = state.get("constraints") or {}
        parts = [outcome["directive"]]
        if bt.get("directive_hint"):
            parts.append(f"되돌림 규칙({bt.get('transition_id')}): {bt['directive_hint']}")
        if constraints.get("exclude_ingredient"):
            parts.append("다음 성분은 쓰지 않는다: " + ", ".join(constraints["exclude_ingredient"]))
        for combo in constraints.get("exclude_ingredient_set", []):
            parts.append(f"금지 조합에서 하나를 뺀다: {combo}")
        return {
            "reflection_count": attempt,
            "reflection_directive": " / ".join(p for p in parts if p),
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

    def node_no_design(state: FormulationState) -> Dict[str, Any]:
        emit("no_design", EventKind.WARNING,
             reason="설계 LLM이 응답하지 않아 검사할 후보 처방이 없습니다 — 잠시 후 다시 실행하세요.")
        return {"status": "no_design"}

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
        if _dose_over_label(state, failures):
            dose = [v for v in failures if v.rulebook_id == "max_daily_dose" and v.blocking]
            emit("infeasible", EventKind.WARNING,
                 reason="요청한 1회 용량 자체가 허가 라벨의 1일 최대 용량을 넘는다 — 이 요청으로는 통과하는 처방이 없다",
                 required_excipients=[],
                 blocking=[{"rule_id": v.rule_id, "rulebook_id": v.rulebook_id, "reason": v.reason,
                            "suggestion": v.suggestion, "citation": v.citation} for v in dose[:1]])
            return {"status": "infeasible"}
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
    # v3: node_evidence/evidence 엣지는 뺐다(§1 출력 경계) — 함수 자체는 위에 그대로
    # 남겨 뒀다. 되돌리려면 아래 add_node/add_edge 두 줄만 evidence로 복구하면 된다.
    graph = StateGraph(FormulationState)
    for name, fn in [
        ("intake", node_intake), ("phase_gates", node_phase_gates), ("generate", node_generate),
        ("gate", node_gate), ("drq_refine", node_drq_refine),
        ("summon", node_summon), ("judge", node_judge),
        ("consensus", node_consensus), ("reflect", node_reflect),
        ("escalate", node_escalate), ("exhausted", node_exhausted),
        ("infeasible", node_infeasible), ("no_design", node_no_design),
        ("drq_narrow", node_drq_narrow), ("plan", node_plan), ("backtrack", node_backtrack),
        ("qtpp_review", node_qtpp_review),
    ]:
        graph.add_node(name, fn)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "phase_gates")
    graph.add_edge("phase_gates", "drq_narrow")
    graph.add_edge("drq_narrow", "plan")
    graph.add_conditional_edges("plan", route_after_plan, ["generate", "qtpp_review"])
    graph.add_edge("generate", "gate")
    graph.add_conditional_edges("gate", route_after_gate,
                                ["drq_refine", "backtrack", "escalate", "exhausted", "infeasible", "no_design"])
    graph.add_edge("backtrack", "reflect")
    graph.add_edge("drq_refine", "summon")
    graph.add_conditional_edges("summon", fan_out_judges, ["judge", "consensus"])
    graph.add_edge("judge", "consensus")
    graph.add_conditional_edges("reflect", route_after_reflect, ["generate", "plan"])
    graph.add_edge("consensus", END)
    graph.add_edge("escalate", END)
    graph.add_edge("exhausted", END)
    graph.add_edge("no_design", END)
    graph.add_edge("qtpp_review", END)
    graph.add_edge("infeasible", END)

    return graph.compile()
