"""DoE v7.0 study 서비스 — HITL 상태기계(IMPLEMENTATION_DESIGN §3·§9).

신규 API walk의 결과값은 **이 테스트 안에서만 쓰는 합성 데이터**다(알려진 2차식 + 고정 seed 잡음). 화면·데모에는 쓰지 않는다.
"""
from __future__ import annotations

import numpy as np
import pytest

from formula.development.service import StudyError
from formula.development.store import StudyStore, VersionConflict
from formula.doe import dataset as DS
from formula.doe import handoff as H
from formula.doe.contracts import TransitionError, check_transition
from formula.doe.service import DoeStudyService


@pytest.fixture()
def svc(tmp_path):
    return DoeStudyService(store=StudyStore(tmp_path / "doe7.db"))


def act(svc, sid, action, payload=None, **kw):
    return svc.act(sid, action, payload or {}, **kw)


def fill(svc, sid, action):
    p = DS.fill(svc.view(sid)["study"], action) or {}
    p.pop("note", None)
    return p


def cbd(svc):
    ds = DS.validate(svc.pkg, DS.cbd())
    return svc.create(DS.handoff(ds, "t"), study_type=ds["study_type"], dataset=ds)["study"]["study_id"]


# ── CBD 문헌 재현: 폼 채우기 값 = 논문 표 ─────────────────────────────────────────
def test_cbd_walk_ends_region_empty(svc):
    sid = cbd(svc)
    act(svc, sid, "handoff_confirm")
    act(svc, sid, "cqa_edit", fill(svc, sid, "cqa_edit"))
    act(svc, sid, "cqa_approve")
    act(svc, sid, "fmea_approve")
    act(svc, sid, "factor_select", fill(svc, sid, "factor_select"))
    act(svc, sid, "range_submit", fill(svc, sid, "range_submit"))
    v = act(svc, sid, "range_approve")
    s = v["study"]
    assert s["status"] == "DOE_PLAN_REVIEW"
    assert s["design_decision"]["rule_id"] == "DS003" and len(s["plans"][0]["runs"]) == 17
    assert s["run_sheet"]["balance_material"] == "Spray-dried mannitol" and not s["run_sheet"]["issues"]
    # 중단 기준·샘플링 없이 승인 불가(PC008)
    v = act(svc, sid, "plan_approve")
    assert v["study"]["status"] == "DOE_PLAN_REVIEW" and "PC008" in v["action_result"]["blocked"]
    act(svc, sid, "plan_approve", fill(svc, sid, "plan_approve"))
    act(svc, sid, "results_submit", fill(svc, sid, "results_submit"))
    v = act(svc, sid, "results_confirm")
    s = v["study"]
    assert s["status"] == "MODEL_FIT"                                     # 플래그 승인 대기(RB00)
    assert s["models"]["CQA_BREAKING_FORCE"]["selected"]["formula"] == "1 + X1 + X2"
    assert set(v["prompt"]["flagged"]) == {"CQA_DISINTEGRATION", "CQA_FRIABILITY"}
    v = act(svc, sid, "model_accept_flags", fill(svc, sid, "model_accept_flags"))
    s = v["study"]
    assert s["status"] == "MODEL_INADEQUATE" and s["region"]["status"] == "EMPTY"
    assert s["region"]["setpoint_joint_p"] == pytest.approx(0.889, abs=1e-3)
    assert v["prompt"]["labloop"]["pattern_id"] == "LB012"
    assert any(d["rule_id"] == "DR018" for d in s["evaluations"]["region"]["decisions"])
    v = act(svc, sid, "revise", fill(svc, sid, "revise"))
    assert v["study"]["status"] == "FMEA_REVIEW" and v["study"]["labloop"]["history"][0]["pattern_id"] == "LB012"
    tr = svc.trace(sid)
    assert [a["point"] for a in tr["lineage"]["approvals"]] == [
        "CQA_SELECTION", "FMEA_REVIEW", "FACTOR_AND_RANGE_SELECTION", "DOE_PLAN", "EXECUTION_PROTOCOL", "MODEL_ACCEPTANCE_WITH_FLAGS"]
    assert tr["lineage"]["plan_locked_hash"] is None                    # revise가 활성 계획을 내렸다 — 이력은 plans[]에
    assert len(tr["events"]) == 14                                  # 막힌 승인 시도도 이벤트로 남는다


def test_hitl_wrong_action_is_409(svc):
    sid = cbd(svc)
    with pytest.raises(StudyError) as e:
        act(svc, sid, "cqa_approve")
    assert e.value.status == 409
    act(svc, sid, "handoff_confirm")
    with pytest.raises(StudyError):
        act(svc, sid, "plan_approve")            # 승인 지점을 건너뛸 수 없다


def test_blocked_approval_is_not_recorded(svc):
    sid = cbd(svc)
    act(svc, sid, "handoff_confirm")
    v = act(svc, sid, "cqa_approve")             # 기본 초안은 기준·시험법 버전이 비어 막힌다
    assert v["study"]["status"] == "CQA_REVIEW" and v["action_result"]["blocked"]
    assert v["study"]["approvals"] == []


def test_doe_response_limit_and_factor_limit(svc):
    sid = cbd(svc)
    act(svc, sid, "handoff_confirm")
    p = fill(svc, sid, "cqa_edit")
    extra = [e for e in p["edits"] if e["analysis_role"] == "NOT_APPLICABLE"][:2]
    for e in extra:
        e.update(analysis_role="DOE_RESPONSE", acceptance_operator="LE", upper=1, unit="%", test_method_id="TM_X",
                 test_method_version="v1", summary_definition="MEAN", replicate_policy="n=3")
    act(svc, sid, "cqa_edit", p)
    v = act(svc, sid, "cqa_approve")
    assert "CE011" in v["action_result"]["blocked"] and v["study"]["status"] == "CQA_REVIEW"
    act(svc, sid, "cqa_edit", fill(svc, sid, "cqa_edit"))
    act(svc, sid, "cqa_approve")
    act(svc, sid, "fmea_approve")
    sel = fill(svc, sid, "factor_select")
    sel["selected"].append({"key": "blend_time", "name": "blend time", "kind": "CPP"})
    v = act(svc, sid, "factor_select", sel)
    assert "FS013" in v["action_result"]["blocked"] and v["study"]["status"] == "FACTOR_SELECTION"


def test_reference_value_never_becomes_center(svc):
    sid = cbd(svc)
    act(svc, sid, "handoff_confirm")
    act(svc, sid, "cqa_edit", fill(svc, sid, "cqa_edit"))
    act(svc, sid, "cqa_approve")
    act(svc, sid, "fmea_approve")
    s = act(svc, sid, "factor_select", fill(svc, sid, "factor_select"))["study"]
    assert s["factors"]["X2"]["reference_value"] == 40 and s["factors"]["X2"]["center"] is None
    with pytest.raises(StudyError):              # 먼저 범위를 제출해야 승인할 수 있다
        act(svc, sid, "range_approve")
    with pytest.raises(StudyError) as e:         # 근거 등급 수동 상향 금지
        act(svc, sid, "range_submit", {"factors": [{"factor_id": "X1", "low": 1, "center": 2, "high": 3, "unit": "psi",
                                                    "quantity_kind": "pressure",
                                                    "evidence_status": {"low": "FEASIBILITY_CONFIRMED"}}]})
    assert e.value.status == 422
    p = fill(svc, sid, "range_submit")
    p["factors"][0]["unit"] = "kN"               # 압력 요인에 힘 단위 — M04로 변환하지 않는다
    v = act(svc, sid, "range_submit", p)
    assert any(d["rule_id"] == "RE009" for d in v["study"]["range_gate"]["unit_checks"])
    assert act(svc, sid, "range_approve")["study"]["status"] == "RANGE_EVIDENCE_CHECK"


def test_idempotency_and_version_conflict(svc):
    sid = cbd(svc)
    a = act(svc, sid, "handoff_confirm", idempotency_key="k1")
    b = act(svc, sid, "handoff_confirm", idempotency_key="k1")
    assert b.get("replayed") and a["study"]["state_version"] == b["study"]["state_version"]
    assert len(svc.trace(sid)["events"]) == 2
    with pytest.raises(VersionConflict):
        act(svc, sid, "cqa_edit", {"edits": []}, expected_version=1)


def test_forbidden_states_unreachable():
    for dst in ("CONTROL_STRATEGY", "PPQ_READY", "COMMERCIAL_RELEASE"):
        with pytest.raises(TransitionError):
            check_transition("VERIFIED_OPERATING_REGION", dst)


def test_production_mode_refused(svc):
    with pytest.raises(StudyError):
        svc.create(DS.handoff(DS.cbd(), "t"), study_type="LITERATURE_REPLAY", execution_mode="PRODUCTION")


def test_new_api_study_has_no_demo_fill(svc):
    h = _candidate_handoff()
    sid = svc.create(h, study_type="NEW_API")["study"]["study_id"]
    assert DS.fill(svc.view(sid)["study"], "results_submit") is None


# ── 신규 API walk (합성 결과 — 테스트 전용) ────────────────────────────────────────
def _candidate_handoff():
    recipe = {"candidate_id": "cand-1", "version": 1, "api_name": "TESTAPI", "strategy": "DC", "process": "direct_compression",
              "process_steps": ["sieve", "blend", "lubricate", "compress"],
              "ingredients": [{"name": "TESTAPI", "role": "api", "amount_mg": 10}, {"name": "Mannitol", "role": "diluent", "amount_mg": 150},
                              {"name": "MCC", "role": "binder", "amount_mg": 80}, {"name": "Croscarmellose sodium", "role": "disintegrant", "amount_mg": 8},
                              {"name": "Magnesium stearate", "role": "lubricant", "amount_mg": 2}]}
    return H.from_candidate(recipe, {"dosage_form": "tablet"}, [], run_id="run-test", actor="t")


def _cqa_edits(st):
    edits = [{"cqa_id": "CQA_BREAKING_FORCE", "analysis_role": "DOE_RESPONSE", "unit": "N", "acceptance_operator": "GE", "lower": 40,
              "test_method_id": "TM_BREAK_USP1217", "test_method_version": "v1", "summary_definition": "MEAN", "replicate_policy": "n=10"},
             {"cqa_id": "CQA_DISINTEGRATION", "analysis_role": "DOE_RESPONSE", "unit": "min", "acceptance_operator": "LE", "upper": 12,
              "test_method_id": "TM_DISINT_USP701", "test_method_version": "v1", "summary_definition": "MAX", "replicate_policy": "n=6"}]
    keep = {e["cqa_id"] for e in edits}
    return edits + [{"cqa_id": c, "analysis_role": "NOT_APPLICABLE", "acceptance_operator": None} for c in st["cqas"] if c not in keep]


def _synthetic(coded):
    rng = np.random.default_rng(7)
    x1, x2 = coded["X1"], coded["X2"]
    bf = 60 + 8 * x1 - 5 * x2 - 3 * x1 ** 2 + rng.normal(0, 0.6)
    dt = 6 + 1.5 * x1 + 1.2 * x2 + 0.8 * x1 * x2 + rng.normal(0, 0.15)
    return bf, dt


def test_new_api_walk_feasibility_to_verified(svc):
    sid = svc.create(_candidate_handoff(), study_type="NEW_API")["study"]["study_id"]
    v = act(svc, sid, "handoff_confirm")
    assert {"RD003", "RD005", "RD006"} <= set(v["action_result"]["blocked"])
    act(svc, sid, "handoff_data", {"equipment_id": "EQ-TEST", "batch_scale": {"units": 500},
                                   "material_grades": {"TESTAPI": "lot A"}})
    assert act(svc, sid, "handoff_confirm")["study"]["status"] == "CQA_REVIEW"
    act(svc, sid, "cqa_edit", {"edits": _cqa_edits(svc.view(sid)["study"])})
    act(svc, sid, "cqa_approve")
    # RB05: 심각도 4 행은 대체관리·사유 없이 제외 불가
    row = svc.view(sid)["study"]["fmea"]["rows"][0]
    v = act(svc, sid, "fmea_edit", {"rows": [{"row_id": row["row_id"], "severity": 4, "disposition": "EXCLUDED"}]})
    assert act(svc, sid, "fmea_approve")["study"]["status"] == "FMEA_REVIEW"
    act(svc, sid, "fmea_edit", {"rows": [{"row_id": row["row_id"], "alternative_control": "SOP", "rationale": "관리 가능"}]})
    s = act(svc, sid, "fmea_approve")["study"]
    assert s["status"] == "FACTOR_SELECTION"
    high = [c["key"] for c in s["factor_candidates"] if c["high_risk"]]
    sel = {"selected": [{"key": "compression_force", "name": "압축력", "kind": "CPP"},
                        {"key": "filler_ratio", "name": "MCC", "kind": "CMA", "material_id": "MCC"}]}
    unsel = [k for k in high if k not in ("compression_force", "filler_ratio")]
    if unsel:
        v = act(svc, sid, "factor_select", sel)
        assert "FS015" in v["action_result"]["blocked"]
        sel["fixed"] = [{"key": k, "fixed_value": "현행", "fixed_rationale": "고정 관리"} for k in unsel]
    s = act(svc, sid, "factor_select", sel)["study"]
    assert s["status"] == "RANGE_EVIDENCE_CHECK"

    def rng_payload(hi1):
        ev = {b: "EXPERT_PROPOSAL" for b in ("low", "center", "high")}
        return {"factors": [{"factor_id": "X1", "unit": "N", "quantity_kind": "force", "low": 6000, "center": 9000, "high": hi1, "evidence_status": ev},
                            {"factor_id": "X2", "unit": "%w/w", "quantity_kind": "fraction_mass", "low": 25, "center": 32, "high": 39,
                             "evidence_status": ev}]}
    act(svc, sid, "range_submit", rng_payload(14000))
    s = act(svc, sid, "range_approve")["study"]
    assert s["status"] == "NEEDS_FEASIBILITY" and s["feasibility"]["plan"]["condition_count"] == 5
    act(svc, sid, "feasibility_plan_approve")
    ok = {"manufacturable": True, "measurable": True, "critical_incompatibility": False}
    conds = [c["condition_id"] for c in s["feasibility"]["plan"]["conditions"]]
    res = {c: dict(ok) for c in conds}
    res["X1_HIGH"] = {**ok, "manufacturable": False}
    v = act(svc, sid, "feasibility_results_submit", {"results": res})
    assert v["study"]["status"] == "RANGE_REVISION_REQUIRED" and v["prompt"]["labloop"]["pattern_id"] == "LB002"
    act(svc, sid, "range_submit", rng_payload(12000))
    assert act(svc, sid, "range_approve")["study"]["status"] == "NEEDS_FEASIBILITY"
    act(svc, sid, "feasibility_plan_approve")
    s = act(svc, sid, "feasibility_results_submit", {"results": {c: dict(ok) for c in conds}})["study"]
    assert s["status"] == "DOE_PLAN_REVIEW" and s["design_decision"]["rule_id"] == "DS002"
    assert s["factors"]["X1"]["evidence_status"]["high"] == "FEASIBILITY_CONFIRMED"
    rows = s["run_sheet"]["runs"]
    assert all(abs(sum(i["pct_w_w"] for i in r["ingredients"]) - 100) < 1e-6 for r in rows)   # balance로 100%
    with pytest.raises(StudyError):
        act(svc, sid, "verification_submit")      # 확인계획 잠금 전 확인 결과 불가
    act(svc, sid, "plan_approve", {"sampling_plan": "n=10", "stop_criteria": "외관 불량 시 중단"})
    plan = svc.view(sid)["study"]["plans"][-1]
    rows = []
    for r in plan["runs"]:
        bf, dt = _synthetic(r["coded"])
        rows.append({"run_id": r["run_id"], "batch_id": f"B-{r['run_id']}", "parent_blend_id": f"BL-{r['run_id']}",
                     "test_method_version": "v1", "replicate_independence": "INDEPENDENT_BATCH", "evidence_status": "MEASURED_IN_STUDY",
                     "values": {"CQA_BREAKING_FORCE": bf, "CQA_DISINTEGRATION": dt}})
    dup = [dict(r) for r in rows]
    dup[1]["parent_blend_id"] = dup[0]["parent_blend_id"]          # 같은 blend를 다른 run으로 — 가짜 반복
    act(svc, sid, "results_submit", {"rows": dup})
    v = act(svc, sid, "results_confirm")
    assert "RQ009" in v["action_result"]["blocked"] and v["study"]["status"] == "RESULT_QUALITY_REVIEW"
    act(svc, sid, "results_revise")
    act(svc, sid, "results_submit", {"rows": rows})
    s = act(svc, sid, "results_confirm")["study"]
    if s["status"] == "MODEL_FIT":
        s = act(svc, sid, "model_accept_flags", {"rationale": "테스트"})["study"]
    assert s["status"] == "PROVISIONAL_DESIGN_SPACE", s["status"]
    prop = s["region"]["proposal"]
    assert [p["role"] for p in prop] == ["SETPOINT", "BOUNDARY", "ROBUSTNESS"]
    v = act(svc, sid, "vplan_lock", {"points": prop[:1]})
    assert "VR001" in v["action_result"]["blocked"]
    s = act(svc, sid, "vplan_lock", {"points": prop})["study"]
    assert s["status"] == "WAITING_VERIFICATION_RESULTS" and s["verification"]["plan"]["locked_hash"]

    def vpoints(ev, batch=lambda i: f"V-{i}"):
        out = []
        for i, pt in enumerate(s["verification"]["plan"]["points"]):
            vals = {k: [pi["predicted"]] * 3 for k, pi in pt["prediction_intervals"].items()}
            out.append({"role": pt["role"], "batch_id": batch(i), "parent_blend_id": f"VB-{i}", "evidence_status": ev, "values": vals})
        return {"points": out}
    v = act(svc, sid, "verification_submit", vpoints("LITERATURE_DIRECT"))
    assert "VR015" in v["action_result"]["blocked"]                     # 문헌 lot은 확인 근거 불가(M05)
    v = act(svc, sid, "verification_submit", vpoints("VERIFICATION_BATCH", batch=lambda i: "B-R01"))
    assert {"VR003", "VR013"} <= set(v["action_result"]["blocked"])     # 적합 set batch 재사용 · 점 간 batch 중복
    with pytest.raises(StudyError):
        act(svc, sid, "final_approve", {"rationale": "x"})
    v = act(svc, sid, "verification_submit", vpoints("VERIFICATION_BATCH"))
    assert v["action_result"]["all_pass"] and v["prompt"]["awaiting_final_approval"]
    s = act(svc, sid, "final_approve", {"rationale": "3점 모두 규격·PI 안"})["study"]
    assert s["status"] == "VERIFIED_OPERATING_REGION" and s["region"]["status"] == "VERIFIED"
    with pytest.raises(StudyError):
        act(svc, sid, "revise", {"reason": "x"})
    surf = svc.surface(sid, "CQA_BREAKING_FORCE")
    assert len(surf["mean"]) == 31 and surf["joint"] is not None


def test_cbd_fill_matches_factors_by_key_not_position(svc):
    """화면이 후보를 다른 순서로 보여 줘도(요인 ID가 달라져도) 논문 값이 맞는 요인에 들어가야 한다."""
    sid = cbd(svc)
    act(svc, sid, "handoff_confirm")
    act(svc, sid, "cqa_edit", fill(svc, sid, "cqa_edit"))
    act(svc, sid, "cqa_approve")
    act(svc, sid, "fmea_approve")
    sel = fill(svc, sid, "factor_select")
    sel["selected"] = sel["selected"][::-1]               # X1 = CCS, X3 = 압축력
    act(svc, sid, "factor_select", sel)
    act(svc, sid, "range_submit", fill(svc, sid, "range_submit"))
    s = act(svc, sid, "range_approve")["study"]
    assert s["factors"]["X3"]["unit"] == "psi" and s["factors"]["X1"]["high"] == 5
    assert not s["run_sheet"]["issues"]
    act(svc, sid, "plan_approve", fill(svc, sid, "plan_approve"))
    act(svc, sid, "results_submit", fill(svc, sid, "results_submit"))
    s = act(svc, sid, "results_confirm")["study"]
    assert s["models"]["CQA_BREAKING_FORCE"]["selected"]["formula"] == "1 + X2 + X3"   # 같은 모형, 요인 이름만 바뀜
    surf = svc.surfaces(sid)                              # 곡면 축·단면은 데이터셋 순서(압축력 × MCC, CCS 단면) — 고른 순서와 무관
    assert surf["slice_factor"]["name"] == "CCS" and surf["axis"]["a"]["id"] == "X3"
    assert svc.surfaces(sid, slice_factor="X3")["slice_factor"]["name"] == "Compression force"
