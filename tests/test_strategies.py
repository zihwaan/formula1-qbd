"""8개 결정론 전략의 단위 테스트.

여기서 지키려는 불변식 3가지:
  1. polarity — 03_process 룰북은 '통과 조건'이다. fail_when으로 읽으면 판정이 뒤집힌다.
  2. 근거 게이트 — 근거가 없는 행(NO_SOURCE_FOUND 등)은 HARD_FAIL을 만들 수 없다.
  3. 실행 순서 — 파생값(flow_character → selected_route)을 만드는 규칙이 먼저 돌아야 한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formula.checkers.registry import RulebookRegistry
from formula.checkers.strategies import STRATEGIES, threshold
from formula.contracts import (
    EvidencePolicy,
    FormulationSpec,
    Ingredient,
    Polarity,
    Recipe,
    RuleAction,
    RulebookEntry,
    VerdictStatus,
    evidence_policy,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def registry() -> RulebookRegistry:
    return RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)


def _entry(**kwargs) -> RulebookEntry:
    base = dict(id="t", file="x.csv", layer="process", owner_agent="predictor",
                eval_type="quantitative", strategy="threshold")
    base.update(kwargs)
    return RulebookEntry(**base)


def _spec(**kwargs) -> FormulationSpec:
    base = dict(api_name="TestAPI", dosage_form="tablet")
    base.update(kwargs)
    return FormulationSpec(**base)


def _recipe(**kwargs) -> Recipe:
    base = dict(api_name="TestAPI", ingredients=[])
    base.update(kwargs)
    return Recipe(**base)


# ---------------------------------------------------------------------------
# 1. polarity — 같은 행을 반대 방향으로 읽으면 판정이 정확히 뒤집혀야 한다
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "carr, polarity, expect_violation",
    [
        # 통과 조건 "carr_index <= 20": 28이면 미달 → 위반
        (28.0, Polarity.PASS_WHEN, True),
        (15.0, Polarity.PASS_WHEN, False),
        # 실패 조건 "carr_index <= 20": 15면 조건 성립 → 위반 (반대로 읽은 경우)
        (28.0, Polarity.FAIL_WHEN, False),
        (15.0, Polarity.FAIL_WHEN, True),
    ],
)
def test_threshold_polarity_inverts_verdict(carr, polarity, expect_violation):
    row = {"rule_id": "DC001", "parameter": "carr_index", "operator": "<=",
           "threshold_value": "20", "action": "REVIEWER_FLAG",
           "verification_status": "VERIFIED", "fail_mode": "유동 불량"}
    entry = _entry(polarity=polarity, schema={"param_col": "parameter",
                                              "operator_col": "operator",
                                              "threshold_col": "threshold_value"})
    verdicts = threshold(entry, [row], _recipe(), _spec(measured_params={"carr_index": carr}), {})
    fired = [v for v in verdicts if v.failed]
    assert bool(fired) is expect_violation


def test_threshold_word_operator_aliases():
    """소아 안전 룰북은 기호형이 아니라 워드형 연산자(gt/gte)를 쓴다."""
    row = {"rule_id": "PED001", "excipient_name_en": "Aspartame", "comparator": "gt",
           "threshold_value": "0", "action": "HARD_FAIL", "verification_status": "VERIFIED",
           "rationale": "PKU 위험"}
    entry = _entry(schema={"param_col": "excipient_name_en", "operator_col": "comparator",
                           "threshold_col": "threshold_value", "source": "ingredient_mg",
                           "reason_col": "rationale"})
    recipe = _recipe(ingredients=[Ingredient(name="Aspartame", amount_mg=5)])
    verdicts = threshold(entry, [row], recipe, _spec(), {})
    assert verdicts[0].status is VerdictStatus.HARD_FAIL
    assert verdicts[0].rule_id == "PED001"


def test_threshold_scale_converts_units():
    """상한이 g 단위인 행은 mg 처방과 비교하려면 1000배 환산이 필요하다."""
    row = {"rule_id": "PEDX", "excipient_name_en": "Lactose", "comparator": "gt",
           "threshold_value": "5", "action": "LABEL_REQUIRED", "verification_status": "VERIFIED"}
    schema = {"param_col": "excipient_name_en", "operator_col": "comparator",
              "threshold_col": "threshold_value", "source": "ingredient_mg"}
    recipe = _recipe(ingredients=[Ingredient(name="Lactose", amount_mg=900)])
    # 발동 여부는 rule_id 로 본다 — 합성 통과 verdict 은 rule_id 가 비어 있다.
    # (LABEL_REQUIRED는 ADVISORY = '통과하되 라벨 의무'라 .failed 로는 구분되지 않는다)
    def fired(entry):
        return threshold(entry, [row], recipe, _spec(), {})[0].rule_id == "PEDX"

    # 환산 없이 비교하면 900 > 5 → 오탐
    assert fired(_entry(schema=schema))
    # 환산하면 900 > 5000 이 거짓 → 발동하지 않음
    assert not fired(_entry(schema={**schema, "threshold_scale": "1000"}))


def test_threshold_between_operator():
    """operator='between' 은 threshold_value 에 하한;상한을 함께 담는다."""
    row = {"rule_id": "DC005", "parameter": "compaction_pressure", "operator": "between",
           "threshold_value": "80;120", "action": "REVIEWER_FLAG", "verification_status": "VERIFIED"}
    entry = _entry(polarity=Polarity.PASS_WHEN,
                   schema={"param_col": "parameter", "operator_col": "operator",
                           "threshold_col": "threshold_value"})
    inside = threshold(entry, [row], _recipe(), _spec(measured_params={"compaction_pressure": 100}), {})
    outside = threshold(entry, [row], _recipe(), _spec(measured_params={"compaction_pressure": 140}), {})
    assert not inside[0].failed
    assert outside[0].failed


# ---------------------------------------------------------------------------
# 2. 근거 게이트 — 개발자 가이드 7장의 엔진 규약
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "status, expected",
    [
        ("VERIFIED", EvidencePolicy.USE),
        ("VERIFIED_PRIMARY", EvidencePolicy.USE),
        ("PROVISIONAL", EvidencePolicy.PROVISIONAL),
        ("STRUCTURAL_VERIFIED", EvidencePolicy.PROVISIONAL),
        ("SCHEMA_ONLY", EvidencePolicy.NO_HARD_FAIL),
        ("UNVERIFIED", EvidencePolicy.NO_HARD_FAIL),
        ("UNVERIFIED_CRITICAL", EvidencePolicy.NO_HARD_FAIL),
        ("ESCALATION_REQUIRED", EvidencePolicy.ESCALATE),
        ("NO_SOURCE_FOUND", EvidencePolicy.SKIP),
        ("NOT_A_RULE", EvidencePolicy.SKIP),
        ("LEGACY", EvidencePolicy.SKIP),
        ("", EvidencePolicy.NO_HARD_FAIL),          # 빈 값은 보수적으로
        ("무엇인지모를값", EvidencePolicy.NO_HARD_FAIL),  # 모르는 어휘도 보수적으로
    ],
)
def test_evidence_policy_mapping(status, expected):
    assert evidence_policy(status) is expected


def test_unverified_row_cannot_hard_fail():
    """근거가 미검증인 행은 HARD_FAIL로 승격되지 못하고 심사관 이관으로 강등된다."""
    row = {"rule_id": "X1", "parameter": "p", "operator": ">", "threshold_value": "1",
           "action": "HARD_FAIL", "verification_status": "UNVERIFIED"}
    entry = _entry(schema={"param_col": "parameter", "operator_col": "operator",
                           "threshold_col": "threshold_value"})
    verdict = threshold(entry, [row], _recipe(), _spec(measured_params={"p": 5}), {})[0]
    assert verdict.status is VerdictStatus.SOFT_FLAG
    assert verdict.action is RuleAction.REVIEWER_FLAG
    assert verdict.provisional is True


def test_escalation_required_row_goes_to_human():
    row = {"rule_id": "X2", "parameter": "p", "operator": ">", "threshold_value": "1",
           "action": "HARD_FAIL", "verification_status": "ESCALATION_REQUIRED"}
    entry = _entry(schema={"param_col": "parameter", "operator_col": "operator",
                           "threshold_col": "threshold_value"})
    verdict = threshold(entry, [row], _recipe(), _spec(measured_params={"p": 5}), {})[0]
    assert verdict.status is VerdictStatus.ESCALATE


def test_no_source_found_rows_are_dropped_at_load(registry):
    """PED044(SLS)는 NO_SOURCE_FOUND/NOT_A_RULE — 로딩 단계에서 아예 제외돼야 한다."""
    entry = next(e for e in registry.entries if e.id == "pediatric_safety_mg")
    unfiltered = RulebookEntry(**{**entry.model_dump(by_alias=True), "row_filter": None})
    rows, skipped = registry._load_rows(unfiltered)
    assert skipped >= 1
    assert "PED044" not in {r["rule_id"] for r in rows}


# ---------------------------------------------------------------------------
# 3. 실행 순서 & 파생값
# ---------------------------------------------------------------------------
def test_stage_order_produces_derived_values_before_use(registry):
    """powder_flow → flow_character → route_decision_tree → selected_route 사슬."""
    spec = _spec(measured_params={"angle_of_repose": 48.0})
    result = registry.run(spec, _recipe(process=None), short_circuit=False)
    assert result.derived["flow_character"] == "Poor"          # USP<1174> 46-55° = Poor
    assert "DC" in result.derived["excluded_routes"]           # 유동 불량 → 직접타정 배제
    assert result.derived["selected_route"] in ("DG", "WG")


def test_priorities_are_monotonic(registry):
    """매니페스트는 우선순위 오름차순으로 정렬되어 로드된다."""
    priorities = [e.trigger_priority for e in registry.entries]
    assert priorities == sorted(priorities)


def test_all_strategies_registered(registry):
    """매니페스트가 참조하는 전략은 전부 구현돼 있어야 한다."""
    used = {e.strategy for e in registry.entries if e.strategy}
    assert used <= set(STRATEGIES), f"미구현 전략: {used - set(STRATEGIES)}"


def test_every_manifest_file_exists(registry):
    for entry in registry.entries:
        assert (ROOT / entry.file).exists(), f"{entry.id}: {entry.file} 없음"


# ---------------------------------------------------------------------------
# 4. 포장 범주 사전 — 식별자와 룰북 서술어를 잇는다
# ---------------------------------------------------------------------------
def test_packaging_traits_translation(registry):
    assert "고투습 포장" in registry.packaging_traits("PVC blister")
    assert "저투습 포장" in registry.packaging_traits("Alu-Alu blister")
    assert registry.packaging_traits("") == []


def test_hygroscopic_api_in_high_mvtr_packaging_is_flagged(registry):
    """흡습성 약물 + 고투습 포장 → 포장 적합성 규칙이 걸려야 한다."""
    spec = _spec(properties={"hygroscopic": True})
    recipe = _recipe(packaging="PVC blister")
    result = registry.run(spec, recipe, short_circuit=False)
    hits = [v for v in result.verdicts
            if v.rulebook_id == "packaging_compatibility" and v.failed]
    assert hits, "흡습성+PVC 조합이 감지되지 않음"
    assert hits[0].rule_id == "PK001"

    safe = registry.run(spec, _recipe(packaging="Alu-Alu blister"), short_circuit=False)
    assert not [v for v in safe.verdicts
                if v.rulebook_id == "packaging_compatibility" and v.failed]
