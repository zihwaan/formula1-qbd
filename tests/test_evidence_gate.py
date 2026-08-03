"""근거 충족 게이트 회귀 테스트 — 두 번째 게이트가 무엇을 보장하는지 고정한다.

여기서 지키려는 성질은 네 가지다.

  1. 요구는 **실제 확인시험**만 가리킨다 (없는 시험을 요구하는 행은 로딩에서 빠진다).
  2. 룰을 통과한 후보라도 근거가 없으면 **실행 가능 프로토콜이 되지 않는다**.
  3. 이 판정은 **결정론**이다 — 같은 입력이면 같은 판정.
  4. 근거가 비어 있는 동안에는 **승인 자체가 거부**된다.

LLM 없이 돌아야 한다(이 계층은 애초에 LLM을 쓰지 않는다).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formula.chem.profile import build_profile
from formula.contracts import (
    ConfirmationResult,
    EvidenceStatus,
    EvidenceTiming,
    FormulationSpec,
    Ingredient,
    ProtocolReadiness,
    Recipe,
)
from formula.evidence.gate import EvidenceGate

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def gate() -> EvidenceGate:
    return EvidenceGate(ROOT)


def _spec(api: str = "Ibuprofen") -> FormulationSpec:
    profile = build_profile(api, base_dir=ROOT, render=False)
    return FormulationSpec(api_name=api, dosage_form="tablet").with_profile(profile)


def _recipe(strategy: str, process: str) -> Recipe:
    return Recipe(
        api_name="Ibuprofen", candidate_id=f"cand-0-{strategy}", strategy=strategy, process=process,
        ingredients=[
            Ingredient(name="Ibuprofen", role="api", amount_mg=200, percent=50),
            Ingredient(name="Microcrystalline cellulose", role="diluent", amount_mg=150, percent=38),
            Ingredient(name="Magnesium stearate", role="lubricant", amount_mg=4, percent=1),
        ],
        packaging="Alu-Alu blister")


# ---------------------------------------------------------------------------
# 1. 요구는 실제 확인시험만 가리킨다
# ---------------------------------------------------------------------------
def test_every_requirement_points_at_a_real_confirmation_test(gate):
    """요구표의 모든 행이 마스터 66종 안의 test_id를 가리켜야 한다.

    이게 깨지면 "확인시험을 하라"는 요청에 방법과 출처가 붙지 않는다 — 지시가 아니라
    구호가 된다. 로딩 단계에서 버리므로 남아 있는 행은 전부 유효해야 한다.
    """
    assert gate.requirements, "근거 요구표가 비어 있다"
    assert not gate.dropped, f"미등록 시험을 가리키는 행: {gate.dropped}"
    for row in gate.requirements:
        assert row["confirmation_test_id"] in gate.tests
        assert row["timing"] in {t.value for t in EvidenceTiming}


# ---------------------------------------------------------------------------
# 2. 룰 통과 ≠ 실행 가능
# ---------------------------------------------------------------------------
def test_wet_granulation_without_water_data_is_blocked(gate):
    """수분 안정성 자료가 없는 API에 수계 습식과립을 걸면 실행이 보류된다."""
    assessment = gate.assess(_spec(), _recipe("WG", "wet_granulation"))
    keys = {gap.evidence_key for gap in assessment.blocking}
    assert "aqueous_process_stability" in keys
    assert assessment.readiness is ProtocolReadiness.BLOCKED
    # 요청은 방법과 출처를 달고 나가야 한다.
    gap = next(g for g in assessment.gaps if g.evidence_key == "aqueous_process_stability")
    assert gap.test_id and gap.test_name and gap.source_reference


def test_direct_compression_still_needs_solubility_evidence(gate):
    """공정이 순한 직접타정이라도 BCS·용해도 근거가 없으면 실행 가능이 되지 않는다.

    룰북은 여기서 아무것도 잡지 않는다 — 금기가 없기 때문이다. 그게 바로 두 번째 게이트가
    필요한 이유다: 위반이 없다는 것과 알고 있다는 것은 다르다.
    """
    assessment = gate.assess(_spec(), _recipe("DC", "direct_compression"))
    keys = {gap.evidence_key for gap in assessment.blocking}
    assert {"experimental_solubility", "bcs_evidence"} <= keys
    assert assessment.readiness is ProtocolReadiness.BLOCKED


def test_timing_split_is_present(gate):
    """모든 시험을 선행시키지 않는다 — 병행·배치 후로 나뉜다."""
    assessment = gate.assess(_spec(), _recipe("DC", "direct_compression"))
    assert assessment.of_timing(EvidenceTiming.PARALLEL)
    assert assessment.of_timing(EvidenceTiming.POST_BATCH)
    # 배치 후 조건부 시험은 실행을 막지 않는다.
    assert all(not gap.blocking for gap in assessment.of_timing(EvidenceTiming.POST_BATCH))


# ---------------------------------------------------------------------------
# 3. 결정론
# ---------------------------------------------------------------------------
def test_same_input_same_verdict(gate):
    spec, recipe = _spec(), _recipe("WG", "wet_granulation")
    first = gate.assess(spec, recipe).model_dump(mode="json")
    second = gate.assess(spec, recipe).model_dump(mode="json")
    assert first == second


# ---------------------------------------------------------------------------
# 4. 확인시험 결과 → 재평가 → 승인
# ---------------------------------------------------------------------------
def test_confirmation_results_unblock_the_protocol(gate):
    """선행 시험 결과가 들어오면 상태가 '실행 불가 초안 → 검토용'으로 올라간다."""
    spec, recipe = _spec(), _recipe("WG", "wet_granulation")
    before = gate.assess(spec, recipe)
    resolved = {gap.requirement_id: ConfirmationResult(requirement_id=gap.requirement_id,
                                                       outcome="pass", value="분해물 0.3%")
                for gap in before.blocking}

    after = gate.assess(spec, recipe, resolved=resolved)
    assert not after.blocking
    assert after.readiness is ProtocolReadiness.READY_FOR_REVIEW
    assert all(g.status is EvidenceStatus.SATISFIED for g in after.gaps if g.requirement_id in resolved)


def test_failed_confirmation_keeps_it_blocked(gate):
    """확인시험이 부적합이면 근거가 '있다'가 아니라 전제가 부정된 것이다 — 계속 막는다."""
    spec, recipe = _spec(), _recipe("WG", "wet_granulation")
    before = gate.assess(spec, recipe)
    resolved = {gap.requirement_id: ConfirmationResult(requirement_id=gap.requirement_id,
                                                       outcome="pass")
                for gap in before.blocking}
    first = next(iter(resolved))
    resolved[first] = ConfirmationResult(requirement_id=first, outcome="fail",
                                         value="7일 후 분해물 4.1%")

    after = gate.assess(spec, recipe, resolved=resolved)
    assert after.failed
    assert after.readiness is ProtocolReadiness.BLOCKED
    with pytest.raises(ValueError):
        gate.approve(after)


def test_approval_is_refused_while_evidence_is_missing(gate):
    assessment = gate.assess(_spec(), _recipe("WG", "wet_granulation"))
    with pytest.raises(ValueError):
        gate.approve(assessment)


def test_approval_records_who_and_when(gate):
    spec, recipe = _spec(), _recipe("DC", "direct_compression")
    before = gate.assess(spec, recipe)
    resolved = {gap.requirement_id: ConfirmationResult(requirement_id=gap.requirement_id,
                                                       outcome="pass")
                for gap in before.blocking}
    approved = gate.approve(gate.assess(spec, recipe, resolved=resolved), approver="변지환")
    assert approved.readiness is ProtocolReadiness.APPROVED
    assert approved.approved_by == "변지환"
    assert approved.approved_at


# ---------------------------------------------------------------------------
# 5. 실행 중에도 실험 전 루프가 열려 있어야 한다
# ---------------------------------------------------------------------------
def test_confirmation_loop_works_before_the_run_finishes(gate):
    """근거 판정이 나온 순간부터 확인시험 결과를 받을 수 있어야 한다.

    화면은 evidence 이벤트를 받자마자 확인시험 요청을 띄우는데, 심사·합의가 도는 동안에는
    그래프의 최종 state가 아직 없다. 최종 state만 보고 있으면 "요청은 떠 있는데 서버는
    판정이 없다고 답하는" 구간이 생긴다 — 라이브에서 실제로 밟았다.
    """
    from formula.orchestrator.runner import Run

    spec, recipe = _spec(), _recipe("WG", "wet_granulation")
    run = Run(ROOT, "성인용 이부프로펜 정제를 설계해줘")
    # 근거 노드가 판정 직후에 채우는 것과 같은 모양으로 store를 채운다.
    assessment = gate.assess(spec, recipe)
    run.evidence_store[recipe.candidate_id] = {
        "assessment": assessment, "spec": spec, "recipe": recipe, "derived": {},
    }
    assert run.final == {}  # 아직 실행 중

    assert run.assessment(recipe.candidate_id) is assessment
    run.confirmations[recipe.candidate_id] = {
        gap.requirement_id: ConfirmationResult(requirement_id=gap.requirement_id, outcome="pass")
        for gap in assessment.blocking
    }
    updated = run.reassess(recipe.candidate_id)
    assert updated.readiness is ProtocolReadiness.READY_FOR_REVIEW
    assert run.approve(recipe.candidate_id, "변지환").readiness is ProtocolReadiness.APPROVED


# ---------------------------------------------------------------------------
# 6. 프로토콜 출력
# ---------------------------------------------------------------------------
def test_protocol_groups_by_timing_and_dedupes_tests(gate):
    assessment = gate.assess(_spec(), _recipe("WG", "wet_granulation"))
    protocol = gate.protocol(assessment)
    assert protocol["readiness"] == "blocked"
    ids = [item["test_id"] for item in protocol["before_protocol"]]
    assert ids and len(ids) == len(set(ids)), "같은 시험이 두 번 실려 있다"
    assert all(item["status"] != "satisfied" for item in protocol["before_protocol"])
