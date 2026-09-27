"""DoE 데이터셋 공통 엔진 — CBD 전용이 아니라 run 단위 데이터를 가진 어떤 DoE든 같은 study 흐름으로.

두 번째 데이터셋은 **이 테스트 안에서만 쓰는 합성 값**(알려진 2차식 + 고정 seed 잡음)이다. 화면·데모에는 쓰지 않는다.
실행 행렬이 표준 FCCD 13 run과 다르다(중심점 3개 · 순서 다름) — 그래서 '실행 행렬 가져오기'(plan_import)를 거친다.
"""
from __future__ import annotations

import copy

import numpy as np
import pytest

from formula.development.store import StudyStore
from formula.doe import dataset as DS
from formula.doe.service import DoeStudyService


@pytest.fixture()
def svc(tmp_path):
    return DoeStudyService(store=StudyStore(tmp_path / "doe7.db"))


def synthetic():
    rng = np.random.default_rng(11)
    pts = [(-1, -1), (1, -1), (-1, 1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1), (0, 0), (0, 0), (0, 0)]
    runs = []
    for n, (a, b) in enumerate(pts[::-1], 1):
        bf = 70 + 9 * a - 4 * b - 3 * a * a + rng.normal(0, 0.7)
        dt = 5 + 1.2 * a + 0.9 * b + 0.5 * a * b + rng.normal(0, 0.12)
        runs.append({"label": f"B{n:02d}", "batch_id": f"B{n:02d}", "blend_id": f"BL{n:02d}",
                     "factors": {"F": 10 + 3 * a, "M": 30 + 8 * b}, "responses": {"bf": round(bf, 3), "dt": round(dt, 3)}})
    return {
        "title": "테스트 전용 합성 데이터셋", "source": {"citation": "test fixture (synthetic)"}, "study_type": "NEW_API",
        "result_evidence_status": "MEASURED_PRIOR_BATCH",
        "formulation": {"dosage_form": "tablet", "unit_weight_mg": 200, "route": "direct_compression", "steps": ["blend", "compress"],
                        "equipment": "EQ-T", "batch_scale": {"units": 300}, "fixed_parameters": [],
                        "ingredients": [{"material": "API-T", "function": "API", "mg": 10, "pct": 5, "grade": "lot1", "is_api": True},
                                        {"material": "Mannitol", "function": "filler", "mg": 124, "pct": 62},
                                        {"material": "MCC", "function": "binder", "mg": 60, "pct": 30},
                                        {"material": "MgSt", "function": "lubricant", "mg": 6, "pct": 3}]},
        "factors": [{"id": "F", "name": "압축력", "key": "compression_force", "unit": "N", "quantity_kind": "force",
                     "low": 7000, "center": 10000, "high": 13000, "kind": "CPP", "evidence_status": "MEASURED_PRIOR_BATCH"},
                    {"id": "M", "name": "MCC", "key": "filler_ratio", "unit": "%w/w", "quantity_kind": "fraction_mass", "material": "MCC",
                     "low": 22, "center": 30, "high": 38, "evidence_status": "MEASURED_PRIOR_BATCH"}],
        "responses": [{"id": "bf", "name": "경도", "cqa_id": "CQA_BREAKING_FORCE", "unit": "N", "operator": "GE", "lower": 55,
                       "test_method_id": "TM_BREAK_USP1217", "test_method_version": "v1", "summary": "MEAN", "replicate_policy": "n=10"},
                      {"id": "dt", "name": "붕해", "cqa_id": "CQA_DISINTEGRATION", "unit": "min", "operator": "LE", "upper": 8,
                       "test_method_id": "TM_DISINT_USP701", "test_method_version": "v1", "summary": "MAX", "replicate_policy": "n=6"}],
        "runs": runs,
        "reported_models": {"bf": {"terms": ["F", "M", "F^2"]}, "dt": {"terms": ["F", "M", "F:M"]}},
        "protocol": {"sampling_plan": "n=10/6", "stop_criteria": "외관 불량 시 중단"},
    }


def _scale(ds):
    for r in ds["runs"]:
        r["factors"]["F"] = 10000 + 1000 * (r["factors"]["F"] - 10)
    return ds


def walk_to_plan(svc, ds):
    ds = DS.validate(svc.pkg, ds)
    sid = svc.create(DS.handoff(ds, "t"), study_type=ds["study_type"], dataset=ds)["study"]["study_id"]
    go = lambda a, p=None: svc.act(sid, a, p if p is not None else {k: v for k, v in (DS.fill(svc.view(sid)["study"], a) or {}).items() if k != "note"})  # noqa: E731
    assert go("handoff_confirm", {})["study"]["status"] == "CQA_REVIEW"
    go("cqa_edit"); go("cqa_approve", {}); go("fmea_approve", {}); go("factor_select"); go("range_submit")
    return sid, go


def test_validate_reports_every_structural_error(svc):
    bad = copy.deepcopy(synthetic())
    bad["source"] = {}
    bad["factors"][0]["key"] = "not_a_factor"
    bad["runs"][0]["responses"].pop("bf")
    bad["runs"] = bad["runs"][:4]
    with pytest.raises(DS.DatasetError) as e:
        DS.validate(svc.pkg, bad)
    msg = " | ".join(e.value.errors)
    assert "출처" in msg and "FMEA 후보 요인" in msg and "run은" in msg and "반응 bf 값이 없습니다" in msg


def test_generic_dataset_imported_matrix_to_region(svc):
    sid, go = walk_to_plan(svc, _scale(synthetic()))
    s = go("range_approve", {})["study"]          # MEASURED_PRIOR_BATCH → feasibility 없이 RSM
    assert s["status"] == "DOE_PLAN_REVIEW" and s["plans"][-1]["design_type"] == "FCCD"
    miss = DS.fill(s, "results_submit")
    assert not miss["rows"] or miss["unmatched"]  # 표준 13 run(중심 5)과 실행 행렬(중심 3)이 달라 짝이 모자란다
    s = go("plan_import")["study"]
    plan = s["plans"][s["active_plan"]]
    assert s["status"] == "DOE_PLAN_REVIEW" and plan["design_type"] == "IMPORTED" and plan["design_family"] == "FCCD"
    assert len(plan["runs"]) == 11 and plan["center_points"] == 3 and len(s["plans"]) == 2 and s["plans"][0].get("replaced")
    assert not any(c["check"] == "run_count" and not c["ok"] for c in plan["validation"]["checks"])
    go("plan_approve")
    fill = DS.fill(svc.view(sid)["study"], "results_submit")
    assert len(fill["rows"]) == 11 and not fill["unmatched"]
    go("results_submit"); s = go("results_confirm", {})["study"]
    if s["status"] == "MODEL_FIT":
        s = go("model_accept_flags")["study"]
    assert s["status"] == "PROVISIONAL_DESIGN_SPACE", s["status"]
    surf = svc.surfaces(sid, "selected")
    assert surf["kind"] == "SURFACE" and len(surf["responses"]) == 2 and len(surf["responses"][0]["slices"]) == 1
    pub = svc.surfaces(sid, "published")
    f = {r["id"]: r["formula"] for r in pub["responses"]}
    assert f["CQA_BREAKING_FORCE"] == "1 + X1 + X2 + X1^2" and f["CQA_DISINTEGRATION"] == "1 + X1 + X2 + X1:X2"   # 보고 항 구성, 요인 ID는 study 것으로
    tr = svc.trace(sid)
    assert "DOE_PLAN_REPLACED" in [t["reason"] for t in tr["timeline"]]


def test_results_csv_matches_by_factor_values_or_run_id(svc):
    sid, go = walk_to_plan(svc, _scale(synthetic()))
    go("range_approve", {}); go("plan_import"); go("plan_approve")
    st = svc.view(sid)["study"]
    plan = st["plans"][st["active_plan"]]
    ds = st["dataset"]
    lines = ["압축력,MCC,CQA_BREAKING_FORCE,CQA_DISINTEGRATION,batch"]
    for r in ds["runs"]:
        lines.append(f"{r['factors']['F']},{r['factors']['M']},{r['responses']['bf']},{r['responses']['dt']},{r['batch_id']}")
    out = svc.parse_results_csv(sid, "\n".join(lines))
    assert len(out["rows"]) == 11 and not out["unmatched_csv_rows"] and not out["runs_without_data"]
    assert all(set(r["values"]) == {"bf", "dt"} for r in out["rows"])       # 열 이름이 CQA ID여도 study의 반응 키로 들어간다
    assert {r["batch_id"] for r in out["rows"]} == {r["batch_id"] for r in ds["runs"]}
    by_id = "run_id,CQA_BREAKING_FORCE,CQA_DISINTEGRATION\n" + "\n".join(f"{r['run_id']},60,5" for r in plan["runs"][:3])
    out = svc.parse_results_csv(sid, by_id)
    assert len(out["rows"]) == 3 and len(out["runs_without_data"]) == 8
    with pytest.raises(Exception):
        svc.parse_results_csv(sid, "압축력,MCC\n10000,30")        # 반응 열 없음 → 422


def test_cbd_is_one_dataset_instance(svc):
    ds = DS.validate(svc.pkg, DS.cbd())
    assert len(ds["runs"]) == 17 and {r["cqa_id"] for r in ds["responses"]} == {"CQA_BREAKING_FORCE", "CQA_DISINTEGRATION", "CQA_FRIABILITY"}
    assert ds["verification"]["points"][0]["role"] == "SETPOINT"     # 논문 확인점은 SETPOINT 하나뿐 — VR001이 막는다(그대로 둔다)


def test_one_factor_dataset_line_surfaces(svc):
    """요인 1개 DoE(1요인 2차 7 run) — 같은 흐름을 지나 곡면 대신 곡선 데이터가 나온다. 합성 값은 테스트 전용."""
    rng = np.random.default_rng(5)
    base = synthetic()
    base["factors"] = [base["factors"][0]]
    base["responses"] = [base["responses"][0]]
    base["reported_models"] = {"bf": {"terms": ["F", "F^2"]}}
    base["runs"] = []
    for n, a in enumerate([-1, -1, 0, 0, 0, 1, 1], 1):
        base["runs"].append({"label": f"S{n}", "batch_id": f"S{n}", "blend_id": f"SB{n}", "factors": {"F": 10000 + 3000 * a},
                             "responses": {"bf": round(70 + 9 * a - 3 * a * a + rng.normal(0, 0.5), 3)}})
    sid, go = walk_to_plan(svc, base)
    s = go("range_approve", {})["study"]
    assert s["status"] == "DOE_PLAN_REVIEW" and s["plans"][-1]["design_type"] == "ONE_FACTOR_QUADRATIC"
    r = go("plan_approve")
    assert r["study"]["status"] == "WAITING_FOR_RESULTS", r["action_result"]
    go("results_submit"); s = go("results_confirm", {})["study"]
    if s["status"] == "MODEL_FIT":
        s = go("model_accept_flags")["study"]
    assert s["status"] in ("PROVISIONAL_DESIGN_SPACE", "MODEL_INADEQUATE")
    d = svc.surfaces(sid)
    assert d["kind"] == "LINE" and len(d["responses"][0]["line"]["x"]) == 25 and len(d["responses"][0]["points"]) == 7
    assert svc.surfaces(sid, "published")["responses"][0]["formula"] == "1 + X1 + X1^2"
