"""예측 불확실성 · BCS 도출 · 확인시험 동적 승격 검증.

팀 리뷰에서 요구한 세 가지가 실제로 이어지는지 고정한다.
  ② 예측 편차 → 고불확실성 → ⑤ 확인시험 요청
  ③ LogS + Caco-2 → BCS 등급
  구조 경고 → 권장 등급 시험의 필수 승격
"""

from __future__ import annotations

from pathlib import Path

from formula.chem.predictions import (
    LOGS_DISAGREEMENT_THRESHOLD,
    PropertyPrediction,
    build_prediction_layer,
    classify_bcs,
    uncertainty_triggered_tests,
)
from formula.chem.profile import build_profile
from formula.feedback.test_planner import BASELINE_TESTS, plan_tests

ROOT = Path(__file__).resolve().parent.parent


def _pred(prop, values, spread=None, high=False):
    p = PropertyPrediction(property=prop, values=values)
    if values:
        p.consensus = sum(values.values()) / len(values)
        p.spread = spread
        p.high_uncertainty = high
        p.status = "high_uncertainty" if high else "ok"
    return p


def test_logs_disagreement_flags_high_uncertainty():
    """두 LogS 예측이 1 log 이상 벌어지면 점추정을 신뢰하지 않는다."""
    close = _pred("logs", {"A": -3.0, "B": -3.4}, spread=0.4, high=False)
    far = _pred("logs", {"A": -3.0, "B": -4.5}, spread=1.5, high=True)
    assert not close.high_uncertainty
    assert far.high_uncertainty
    assert far.spread >= LOGS_DISAGREEMENT_THRESHOLD


def test_high_uncertainty_triggers_confirmation_test():
    """②의 불확실성 출력이 ⑤의 확인시험 요청으로 이어져야 한다."""
    layer = {"logs": _pred("logs", {"A": -3.0, "B": -4.5}, spread=1.5, high=True).to_dict(),
             "bcs": {"status": "predicted", "bcs_class": "I", "confidence": "low"}}
    requests = uncertainty_triggered_tests(layer)
    assert any(r["trigger"] == "prediction_uncertainty" for r in requests)
    assert all(r["tier"] == "필수" for r in requests if r["trigger"] == "prediction_uncertainty")


def test_bcs_requires_both_inputs():
    """입력이 없으면 등급을 지어내지 않고 자료를 요청한다."""
    out = classify_bcs(_pred("logs", {}), _pred("caco2", {}))
    assert out["bcs_class"] is None
    assert out["status"] == "request_data"


def test_bcs_classification_from_predictions():
    """LogS와 Caco-2가 있으면 등급을 도출한다(예측 기반·규제 판정 아님)."""
    low_sol_high_perm = classify_bcs(_pred("logs", {"A": -6.0}), _pred("caco2", {"A": -4.5}))
    assert low_sol_high_perm["bcs_class"] == "II"
    assert "대체하지 않음" in low_sol_high_perm["limitation"]

    high_both = classify_bcs(_pred("logs", {"A": -2.0}), _pred("caco2", {"A": -4.5}))
    assert high_both["bcs_class"] == "I"


def test_predictor_layer_reports_not_connected_without_models():
    """모델이 없으면 숫자를 지어내지 않고 미연결을 보고해야 한다."""
    layer = build_prediction_layer("CC(=O)Nc1ccc(O)cc1")
    assert layer["logs"]["status"] == "not_connected"
    assert layer["logs"]["values"] == {}
    assert layer["bcs"]["bcs_class"] is None
    # 미연결도 확인시험 요청으로 이어져야 한다(자료 없음 = 안전 아님)
    assert uncertainty_triggered_tests(layer)


def test_hydrolysis_flag_promotes_stress_stability():
    """에스터가 검출되면 stress stability가 권장 → 필수로 올라가야 한다."""
    baseline = {t["test"]: t["tier"] for t in BASELINE_TESTS}
    assert baseline["소규모 stress stability"] == "권장"

    plan = plan_tests(["has_ester"])
    promoted = {p["test"]: p for p in plan["promotions"]}
    assert "소규모 stress stability" in promoted
    assert promoted["소규모 stress stability"]["to"] == "필수"
    assert "has_ester" in promoted["소규모 stress stability"]["trigger_flags"]


def test_photo_and_amine_flags_promote_their_tests():
    plan = plan_tests(["has_nitroaromatic", "has_primary_aliphatic_amine"])
    promoted = {p["test"] for p in plan["promotions"]}
    assert "광안정성 (ICH Q1B)" in promoted
    assert "부형제 배합적합성 시험" in promoted


def test_route_scope_downgrades_solid_only_tests():
    """고형 경구가 아니면 고체 특성화 비중을 낮춘다(팀 리뷰 제안 ④)."""
    plan = plan_tests([], route="injection")
    xrpd = next(t for t in plan["tests"] if t["test"] == "XRPD 결정형 확인")
    assert xrpd["tier"] == "권장"
    assert plan["scope_note"]


def test_real_molecule_promotes_from_structure():
    """실제 분자로 구조 → 시험 승격이 끝까지 이어지는지."""
    profile = build_profile("Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O",
                            base_dir=ROOT, render=False)
    names = [f.flag_name for f in profile.flags if f.present]
    plan = plan_tests(names)
    assert plan["required_count"] > plan["baseline_required"], "구조 경고가 시험을 승격하지 못했다"
    assert any(p["trigger"] == "structural_alert" for p in plan["promotions"])
