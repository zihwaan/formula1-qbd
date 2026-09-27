"""DoE v7.0 결정론 core — INSTALLATION §11.4 golden 1–10 + 명세 §14 인수 테스트 일부 + CBD 문헌 재현(§14.6)."""
import numpy as np
import pytest

from formula.doe import design as D
from formula.doe import gates as G
from formula.doe import models as M
from formula.doe import region as RG
from formula.doe.contracts import FORBIDDEN_STATES, TRANSITIONS, FactorSpec, TransitionError, check_transition
from formula.doe.package import package
from formula.doe.replay import final_state, run_replay

P = package()
PROPOSAL = {"low": "UNVERIFIED_PROPOSAL", "center": "UNVERIFIED_PROPOSAL", "high": "UNVERIFIED_PROPOSAL"}
BATCH = {"low": "MEASURED_PRIOR_BATCH", "center": "MEASURED_PRIOR_BATCH", "high": "MEASURED_PRIOR_BATCH"}


def fac(fid, lo, c, hi, ev=PROPOSAL, **kw):
    return FactorSpec(fid, fid, kw.pop("unit", "%w/w"), lo, c, hi, quantity_kind=kw.pop("qk", "mass_fraction"), evidence_status=dict(ev), **kw)


F3 = [fac("X1", 1200, 1500, 1800, unit="psi", qk="pressure", kind="CPP"), fac("X2", 30, 40, 50, reference_value=42), fac("X3", 1, 3, 5, reference_value=2)]


# ── golden 1·2: 설계 선택과 run 수 ──
def test_g1_two_factors_fccd_13():
    d = G.select_design(P, F3[:2])
    assert d.result_code == "DESIGN_FCCD_13"
    plan = D.generate(G.DESIGN_OF_CODE[d.result_code], F3[:2], seed=7)
    assert len(plan["runs"]) == 13 and plan["center_points"] == 5 and plan["validation"]["ok"]


def test_g2_three_factors_bbd_17():
    d = G.select_design(P, F3)
    assert d.result_code == "DESIGN_BBD_17"
    plan = D.generate("BBD", F3, seed=7)
    assert len(plan["runs"]) == 17 and plan["validation"]["ok"]


# ── golden 3–7: 범위근거와 feasibility ──
def test_g3_new_api_proposals_need_feasibility():
    r = G.range_evidence(P, F3, "NEW_API")["route"]
    assert r["result_code"] == "RANGE_REQUIRES_FEASIBILITY" and r["next_state"] == "NEEDS_FEASIBILITY"
    assert r["enforced"] is False                        # DRAFT — 권고로만


def test_measured_batch_ranges_go_direct_to_rsm():
    fs = [fac(f.factor_id, f.low, f.center, f.high, BATCH, unit=f.unit, qk=f.quantity_kind) for f in F3]
    assert G.range_evidence(P, fs, "NEW_API")["route"]["next_state"] == "DOE_RANGE_READY"


def test_g4_g5_feasibility_condition_counts():
    assert G.feasibility_plan(P, F3[:2])["condition_count"] == 5
    plan = G.feasibility_plan(P, F3)
    assert plan["condition_count"] == 7 and plan["checks"] == []
    assert plan["fitting_eligibility"] == "EXCLUDED_BY_DEFAULT"
    # 한 번에 한 요인만 중심에서 벗어난다(2^k+1 요인배치가 아니다)
    for c in plan["conditions"]:
        assert sum(c["settings"][f.factor_id] != f.center for f in F3) <= 1


def _results(plan, **fail):
    r = {c["condition_id"]: {"manufacturable": True, "measurable": True} for c in plan["conditions"]}
    for cid in fail:
        r[cid]["manufacturable"] = False
    return r


def test_g6_center_failure_goes_to_prototype_revision():
    plan = G.feasibility_plan(P, F3)
    assert G.feasibility_evaluate(P, plan, _results(plan, C0=1))["route"]["next_state"] == "PROTOTYPE_REVISION_REQUIRED"


def test_g7_boundary_failure_goes_to_range_revision():
    plan = G.feasibility_plan(P, F3)
    out = G.feasibility_evaluate(P, plan, _results(plan, X1_HIGH=1))["route"]
    assert out["next_state"] == "RANGE_REVISION_REQUIRED" and out["failed_boundaries"] == ["X1_HIGH"]
    ok = G.feasibility_evaluate(P, plan, _results(plan))["route"]
    assert ok["next_state"] == "DOE_RANGE_READY"
    missing = dict(_results(plan))
    missing.pop("X2_LOW")
    assert G.feasibility_evaluate(P, plan, missing)["route"]["result_code"] == "FEASIBILITY_RESULT_INCOMPLETE"


def test_prototype_value_is_never_auto_center():
    f = fac("X2", 30, 40, 50, reference_value=40, center_source="HANDOFF_REFERENCE_PROTOTYPE")
    assert G.range_evidence(P, [f], "NEW_API")["route"]["result_code"] == "PROTOTYPE_AUTO_CENTER_FORBIDDEN"
    # reference_value ≠ center 는 정상(명세 §14.1)
    g = fac("X2", 30, 40, 50, BATCH, reference_value=42)
    assert G.range_evidence(P, [g], "NEW_API")["route"]["next_state"] == "DOE_RANGE_READY"


def test_advanced_design_routes():
    assert G.select_design(P, [fac("X1", 0, 1, 2, kind="MIXTURE_COMPONENT"), F3[1]]).next_state == "ADVANCED_DESIGN_REQUIRED"
    assert G.select_design(P, F3 + [fac("X4", 1, 2, 3)]).result_code == "OPTIONAL_SCREENING_REQUIRED"


# ── 설계 재현성 ──
def test_same_contract_and_seed_same_matrix():
    a, b, c = D.generate("BBD", F3, seed=11), D.generate("BBD", F3, seed=11), D.generate("BBD", F3, seed=12)
    assert a["matrix_hash"] == b["matrix_hash"] and [r["std_order"] for r in a["runs"]] == [r["std_order"] for r in b["runs"]]
    assert [r["std_order"] for r in a["runs"]] != [r["std_order"] for r in c["runs"]]


def test_asymmetric_range_round_trip():
    f = fac("X1", 10, 12, 20)
    for x in (10, 11, 12, 16, 20):
        assert D.to_actual(D.to_coded(x, f), f) == pytest.approx(x)
    assert D.to_coded(12, f) == 0


# ── golden 8: 모델 ──
def test_candidates_are_hierarchical_and_selection_is_deterministic():
    from formula.qbd.doe import is_hierarchical
    assert all(is_hierarchical(t) for t in M.enumerate_models(["X1", "X2", "X3"]))
    r = run_replay(accept_flags=True)
    r2 = run_replay(accept_flags=True)
    assert {k: v["formula"] for k, v in r["models"].items()} == {k: v["formula"] for k, v in r2["models"].items()}


def test_rank_deficient_candidates_are_rejected():
    coded = {"X1": np.array([-1.0, 1.0, 0.0])}
    out = M.fit_ols(["1", "X1", "X1^2"], coded, np.array([1.0, 2.0, 3.0]))
    assert out["rejected"] == "RESIDUAL_DF_LT_1"


def test_g8_inadequate_model_blocks_region():
    bad = {"df_resid": 7, "lack_of_fit": {"status": "ESTIMABLE", "p": 0.001, "df_pe": 4}, "adj_r2": 0.9, "pred_r2": 0.8,
           "cooks_d": [0.1], "leverage": [0.1], "p": 4, "n": 17}
    assert M.validate_model(bad, P.constants)["status"] == "MODEL_INADEQUATE"
    assert final_state(True, False, None, None, None)["state"] == "MODEL_INADEQUATE"


# ── golden 9·10: 확인과 금지 상태 ──
def test_g9_unlocked_verification_never_promotes():
    assert RG.evaluate_verification({"prediction_intervals": {}}, {}, {})["promote"] is False


def test_g10_forbidden_states_unreachable():
    reachable = set(TRANSITIONS) | {s for v in TRANSITIONS.values() for s in v}
    assert not reachable & set(FORBIDDEN_STATES)
    with pytest.raises(TransitionError):
        check_transition("VERIFIED_OPERATING_REGION", "CONTROL_STRATEGY")
    with pytest.raises(TransitionError):
        check_transition("MODEL_FIT", "VERIFIED_OPERATING_REGION")   # 확인 없이 검증 영역으로 건너뛸 수 없다


# ── CBD ODT 문헌 재현(Monton 2026, PMC13519653) — 실측 원자료로 고정 ──
def test_cbd_replay_links_table9_and_refits_without_published_equation():
    r = run_replay(accept_flags=True)
    assert r["design"]["runs"] == 17 and r["design"]["fixture_linked"] and r["design"]["validation"]["ok"]
    assert r["range_gate"]["route"]["result_code"] == "LITERATURE_REPLAY_RANGE_ONLY"
    assert r["models"]["hardness_kgf"]["formula"] == "1 + X1 + X2"            # 논문은 X3까지 3항 — 1-SE 규칙이 더 단순한 식
    assert r["models"]["dt_s"]["status"] == "VALID_WITH_FLAGS"                # 예측 R² 낮음(MV007) — 논문 ANOVA도 모형 p=0.2463
    kinds = {a["kind"] for a in r["audit"]}
    assert "PUBLISHED_REPORT_INCONSISTENCY" in kinds and "REFIT_DIFFERS_FROM_PUBLISHED" in kinds


def test_cbd_replay_waits_for_flag_approval_then_region_is_empty_under_locked_policy():
    assert run_replay()["final_state"]["state"] == "WAITING_MODEL_APPROVAL"
    r = run_replay(accept_flags=True)
    assert r["region"]["policy"]["p_min"] == 0.90 and r["region"]["status"] == "EMPTY"
    assert r["final_state"] == {"state": "MODEL_INADEQUATE", "reason_code": "REGION_EMPTY", "rule": "RB16 DR018"}
    # 확인 lot 3개는 규격·잠근 예측구간을 모두 통과하지만(9/9), 영역이 없어 승격하지 않는다
    assert r["verification"]["route"] == "VERIFICATION_PASSED" and len(r["verification"]["rows"]) == 9
    assert r["optimum_in_region"]["inside"] is False
