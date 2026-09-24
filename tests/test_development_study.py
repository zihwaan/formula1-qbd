"""ExperimentalDevelopmentGraph 서비스 인수 테스트 — 명세 v6.1 §15 Orchestration, §18 trace, §19 데모.

Lornoxicam 분산정 시나리오를 결과 제출 API와 같은 경로(`act`)로 끝까지 걷는다. LLM 키가 없어도
돌아야 한다(FMEA 가설·진단은 결정론 대체로 내려가고 그 사실이 기록된다).
"""

from pathlib import Path

import pytest

from formula.development import handoff as ho
from formula.development import states as sm
from formula.development.service import DevelopmentService, StudyError
from formula.development.store import StudyStore, VersionConflict

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ho.LORNOXICAM_SCRIPT
CSV = (ROOT / "tests" / "fixtures" / "lornoxicam_table3.csv").read_text(encoding="utf-8")


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMULA1_LLM_PROVIDER", "none")
    return DevelopmentService(ROOT, StudyStore(tmp_path / "dev.db"))


def _new(svc):
    return svc.create(ho.lornoxicam_demo(svc.rb, "tester"), mode="demo", demo_script="lornoxicam")


def _to_region(svc):
    st = _new(svc)
    sid = st["study_id"]
    st = svc.act(sid, "required_data", SCRIPT["required_data"])
    st = svc.act(sid, "cqa_edit", {"edits": SCRIPT["cqa_edits"]})
    st = svc.act(sid, "cqa_approve", {"reason": "demo"})
    st = svc.act(sid, "fmea_edit", {"edits": SCRIPT["fmea_edits"]})
    st = svc.act(sid, "fmea_approve", {})
    st = svc.act(sid, "factor_data", {"factors": SCRIPT["factor_inputs"]})
    st = svc.act(sid, "factor_approve", SCRIPT["factor_approval"])
    st = svc.act(sid, "plan_approve", {})
    st = svc.act(sid, "results_submit", {"csv": CSV, "column_map": SCRIPT["column_map"], "source": "fixture"})
    st = svc.act(sid, "results_confirm", {"accept": True})
    return sid, st


def test_scene1_entry_readiness_requests_data(svc):
    st = _new(svc)
    assert st["status"] == "WAITING_REQUIRED_DATA"
    codes = {v["rule_id"] for v in st["readiness"]["requests"]}
    assert {"RD006", "RD007"} <= codes            # 배치규모 · 압축력
    st = svc.act(st["study_id"], "required_data", SCRIPT["required_data"])
    assert st["status"] == "WAITING_CQA_APPROVAL"
    assert st["handoff"]["handoff_id"].endswith("-r2")      # Handoff는 고치지 않고 새 revision


def test_scene2_cqa_contract_blocks_until_de30_limit(svc):
    st = _new(svc)
    sid = st["study_id"]
    st = svc.act(sid, "required_data", SCRIPT["required_data"])
    roles = {c: v["analysis_role"] for c, v in st["cqas"].items()}
    assert roles["CQA_DISPERSIBILITY"] == roles["CQA_FRIABILITY"] == roles["CQA_CU_AV"] == "DOE_RESPONSE"
    assert roles["CQA_BREAKING_FORCE"] == "MONITOR_ONLY"
    with pytest.raises(StudyError) as e:
        svc.act(sid, "cqa_approve", {})
    blocked = {v["rule_id"] for v in e.value.verdicts}
    assert "CR006" in blocked          # 용출 요약값 미정
    st = svc.act(sid, "cqa_edit", {"edits": SCRIPT["cqa_edits"]})
    st = svc.act(sid, "cqa_approve", {})
    assert st["status"] == "WAITING_FMEA_APPROVAL"


def test_fmea_high_severity_delete_needs_alternative_control(svc):
    st = _new(svc)
    sid = st["study_id"]
    svc.act(sid, "required_data", SCRIPT["required_data"])
    svc.act(sid, "cqa_edit", {"edits": SCRIPT["cqa_edits"]})
    st = svc.act(sid, "cqa_approve", {})
    high = next(r for r in st["fmea"]["rows"] if (r["severity"] or 0) >= 4 and r["origin"] == "SEED")
    with pytest.raises(StudyError):
        svc.act(sid, "fmea_edit", {"edits": [{"row_id": high["row_id"], "op": "DELETE", "reason": "x"}]})
    # 근거 등급은 연구자가 바꿀 수 없다
    with pytest.raises(StudyError):
        svc.act(sid, "fmea_edit", {"edits": [{"row_id": high["row_id"],
                                             "changes": {"evidence_status": "MEASURED_CONFIRMED"}}]})
    # O가 UNKNOWN인 행은 RPN이 없다
    assert all(r["rpn"] is None for r in st["fmea"]["rows"] if r["occurrence"] is None)


def _walk_to_verification(svc):
    sid, st = _to_region(svc)
    # 장면 6: 마손도 과적합 → 연구자 판단 대기
    assert st["status"] == "WAITING_MODEL_APPROVAL", st["timeline"][-3:]
    status = {c: ms[-1]["validation_status"] for c, ms in st["models"].items()}
    assert status["CQA_FRIABILITY"] == "FLAGGED"
    assert st["models"]["CQA_FRIABILITY"][-1]["fit_stats"]["pred_r2"] == pytest.approx(0.251, abs=0.01)
    assert st["cqas"]["CQA_DISPERSIBILITY"]["binding_status"] == "NON_BINDING"
    runs_flagged = {f["source_row"] for f in st["models"]["CQA_DISPERSIBILITY"][-1]["influence_flags"]}
    assert 12 in runs_flagged                  # 영향점 flag — 삭제 없음
    with pytest.raises(StudyError):
        svc.act(sid, "model_approve", {})      # FLAGGED를 판단하지 않고는 못 넘어간다
    with pytest.raises(StudyError):
        svc.act(sid, "model_reduce", {"cqa_id": "CQA_FRIABILITY", "terms": ["1", "a:b"]})   # 계층성 위반
    assert status["CQA_CU_AV"] == "FLAGGED"     # MV006: 0.885 − 0.481 > 0.20
    svc.act(sid, "model_reduce", SCRIPT["model_reduction"])
    with pytest.raises(StudyError):
        svc.act(sid, "model_accept", {"cqa_id": "CQA_CU_AV"})      # 사유 없이 수용 불가
    svc.act(sid, "model_accept", SCRIPT["model_accept"])
    st = svc.act(sid, "model_approve", {})
    assert st["models"]["CQA_CU_AV"][-1]["validation_status"] == "ACCEPTED_WITH_FLAGS"
    fr = st["models"]["CQA_FRIABILITY"][-1]
    assert fr["validation_status"] == "VALID" and fr["reduced_from"]
    assert fr["fit_stats"]["pred_r2"] == pytest.approx(0.824, abs=0.01)
    # 장면 7: 영역
    assert st["status"] == "WAITING_REGION_APPROVAL"
    s = st["region"]["summary"]
    assert s["grid_points_in_domain"] == 7501
    assert s["mean_ok_fraction"] == pytest.approx(0.772, abs=0.01)
    assert s["feasible_fraction"] == pytest.approx(0.476, abs=0.01)
    assert s["setpoint"]["actual"] == {"F_filler_ratio": pytest.approx(2.7), "F_blend_time": pytest.approx(12.5),
                                       "F_disintegrant_pct": pytest.approx(6.8)}
    scope = st["region"]["design_space"]["scope"]
    assert "compression_force" in scope["unmanaged"]
    assert any("파괴강도" in n for n in scope["not_evaluated"])
    # 장면 8: 확인계획
    st = svc.act(sid, "region_approve", {"reference": SCRIPT["reference_existing"]})
    assert st["status"] == "WAITING_VERIFICATION_PLAN_APPROVAL"
    pts = st["verification"]["plan"]["points"]
    assert [p["role"] for p in pts] == ["SETPOINT", "BOUNDARY", "ROBUSTNESS", "REFERENCE_EXISTING"]
    de30 = pts[0]["predicted"]["cqa"]["CQA_DISSOLUTION"]
    assert (de30["mean"], de30["pi_lower"], de30["pi_upper"]) == (pytest.approx(82.3, abs=0.1),
                                                                   pytest.approx(71.9, abs=0.1),
                                                                   pytest.approx(92.8, abs=0.1))
    st = svc.act(sid, "vplan_lock", {})
    assert st["verification"]["plan"]["locked_hash"]
    return sid, st


def test_full_lornoxicam_walk_to_verification(svc):
    _walk_to_verification(svc)


def _verification_values(st, override=None):
    out = {}
    for n, p in enumerate(st["verification"]["plan"]["points"][:3]):
        vals = {}
        for cid, c in st["cqas"].items():
            if c["analysis_role"] == "NOT_APPLICABLE":
                continue
            pred = p["predicted"]["cqa"].get(cid)
            if pred:
                vals[cid] = round(pred["mean"], 2)
            elif c["acceptance_operator"] == "PASS_FAIL":
                vals[cid] = "PASS"
            elif c["acceptance_operator"] == "BETWEEN":
                vals[cid] = (c["lower"] + c["upper"]) / 2
            else:
                vals[cid] = c["upper"] * 0.5
        if override and p["role"] in override:
            vals.update(override[p["role"]])
        out[p["point_id"]] = {"batch_id": f"VB-{n}", "parent_blend_id": f"BL-{n}",
                              "evidence_status": "MEASURED_UNCONFIRMED", "values": vals}
    return out


def test_verified_region_and_scope(svc):
    sid, st = _walk_to_verification(svc)
    svc.act(sid, "verification_submit", {"points": _verification_values(st)})
    st = svc.act(sid, "verification_confirm", {})
    assert st["status"] == "WAITING_FINAL_APPROVAL", st["evaluations"].get("verification_gate")
    with pytest.raises(StudyError):
        svc.act(sid, "finalize", {})           # DR013: 압축력 UNKNOWN → 한계 기록 필수
    st = svc.act(sid, "finalize", {"limitations": SCRIPT["limitations"]})
    assert st["status"] == "COMPLETED"
    assert st["region"]["design_space"]["status"] == "VERIFIED"
    tr = svc.trace(sid)
    assert tr["identifiers"]["design_space"].endswith("@1")
    assert tr["identifiers"]["verification_plan_id"]


def test_synthetic_verification_results_cannot_promote(svc):
    sid, st = _walk_to_verification(svc)
    pts = _verification_values(st)
    for v in pts.values():
        v["evidence_status"] = "SYNTHETIC_DEMO"
    svc.act(sid, "verification_submit", {"points": pts})
    st = svc.act(sid, "verification_confirm", {})
    assert st["status"] == "VERIFICATION_GATE"
    blocked = {v["rule_id"] for v in st["evaluations"]["verification_gate"]["verdicts"]
               if v["effect"] == "BLOCK_STAGE"}
    assert "VR015" in blocked
    assert st["region"]["design_space"]["status"] == "PROVISIONAL"   # 무효화도 승격도 아님


def test_spec_fail_invalidates_region_and_diagnoses(svc):
    sid, st = _walk_to_verification(svc)
    pts = _verification_values(st, override={"BOUNDARY": {"CQA_DISSOLUTION": 70.0}})
    svc.act(sid, "verification_submit", {"points": pts})
    st = svc.act(sid, "verification_confirm", {})
    assert st["region"]["design_space"]["status"] == "INVALIDATED"
    assert st["status"] == "WAITING_DIRECTIVE_APPROVAL"
    assert st["diagnosis"]["generated_by"].startswith("deterministic_stand_in")
    st = svc.act(sid, "directive_approve", {"directive": "DOE_AUGMENT"})
    assert st["status"] == "WAITING_RSM_APPROVAL"


def test_outside_pi_routes_to_augmentation(svc):
    sid, st = _walk_to_verification(svc)
    pts = _verification_values(st, override={"SETPOINT": {"CQA_DISSOLUTION": 99.0}})
    svc.act(sid, "verification_submit", {"points": pts})
    st = svc.act(sid, "verification_confirm", {})
    assert st["region"]["design_space"]["status"] == "INVALIDATED"
    assert any(t["reason"] == "VERIF_OUTSIDE_PI" for t in st["timeline"])
    assert st["status"] == "WAITING_RSM_APPROVAL"


def test_idempotency_and_optimistic_lock(svc):
    st = _new(svc)
    sid, v = st["study_id"], st["state_version"]
    a = svc.act(sid, "required_data", SCRIPT["required_data"], idempotency_key="k1", expected_version=v)
    b = svc.act(sid, "required_data", SCRIPT["required_data"], idempotency_key="k1", expected_version=v)
    assert b.get("replayed") and a["state_version"] == b["state_version"]
    with pytest.raises(VersionConflict):
        svc.act(sid, "cqa_approve", {}, idempotency_key="k2", expected_version=v)   # 오래된 버전


def test_every_approval_state_has_reject_edge_and_transitions_are_in_table():
    for state, (ok, back) in sm.APPROVAL_STATES.items():
        assert sm.allowed(state, back), state
        if ok != "<directive>":
            assert sm.allowed(state, ok), state


def test_override_of_blocking_rule_is_refused(svc):
    st = _new(svc)
    with pytest.raises(StudyError) as e:
        svc.act(st["study_id"], "override", {"rule_id": "CR002", "reason": "just because"})
    assert "AA017" in str(e.value) or "override" in str(e.value)


def test_production_mode_enforces_nothing(svc):
    st = svc.create(ho.lornoxicam_demo(svc.rb, "t"), mode="production")
    assert st["enforced_rule_count"] == 0
    assert st["status"] == "WAITING_CQA_APPROVAL"      # DRAFT 규칙은 집행되지 않는다 — 명세상 정상


def test_screening_path_classifies_by_effect_interval_and_routes_to_rsm(svc):
    """4요인·사전근거 없음 → Res IV 부분요인 screening → 효과구간 판정 → ACTIVE만 RSM으로 (명세 §6 D7)."""
    import random
    h = ho.lornoxicam_demo(svc.rb, "t")
    h["fixed_parameters"].append({"name": "lubrication_time", "value": 2.0, "unit": "min", "status": "SET",
                                  "evidence_ref": "t"})
    h["formulation_fingerprint"] = ho.fingerprint(h)   # 안 하면 PV001이 lineage 불일치로 잡는다(아래 테스트)
    st = svc.create(h, mode="demo")
    sid = st["study_id"]
    svc.act(sid, "required_data", SCRIPT["required_data"])
    edits = SCRIPT["cqa_edits"] + [
        {"cqa_id": "CQA_DISSOLUTION", "changes": {"practical_effect_threshold": 2}},
        {"cqa_id": "CQA_FRIABILITY", "changes": {"practical_effect_threshold": 0.1}},
        {"cqa_id": "CQA_DISPERSIBILITY", "changes": {"practical_effect_threshold": 2}},
        {"cqa_id": "CQA_CU_AV", "changes": {"practical_effect_threshold": 1}}]
    svc.act(sid, "cqa_edit", {"edits": edits})
    svc.act(sid, "cqa_approve", {})
    fm = [e for e in SCRIPT["fmea_edits"] if e["row_id"] != "FM008"]   # 활택 요인도 DoE 후보로 둔다
    svc.act(sid, "fmea_edit", {"edits": fm})
    st = svc.act(sid, "fmea_approve", {})
    inputs = dict(SCRIPT["factor_inputs"])
    inputs["lubricant_pct"] = {"low": 0.5, "high": 1.5, "source_ref": "t", "evidence_status": "EXPERT_ASSUMPTION",
                               "manufacturability_evidence": "t"}
    inputs["lubrication_time"] = {"disposition": "FIXED", "low": 1, "high": 3, "source_ref": "t",
                                  "evidence_status": "EXPERT_ASSUMPTION", "manufacturability_evidence": "t"}
    svc.act(sid, "factor_data", {"factors": inputs})
    st = svc.act(sid, "factor_approve", {"prior_evidence_approved": False})
    assert st["status"] == "WAITING_SCREENING_APPROVAL"
    plan = st["plans"][-1]
    assert plan["design_type"] == "FRACTIONAL_FACTORIAL" and plan["diagnostics"]["resolution"] == 4
    st = svc.act(sid, "plan_approve", {})
    random.seed(3)
    fids = plan["factor_ids"]
    sym = {v: k for k, v in plan["symbols"].items()}
    rows = [",".join(fids + ["y1", "y2", "y3", "y4", "batch_id", "replicate_independence", "evidence_status"])]
    for n, r in enumerate(plan["runs"]):
        c = r["coded"]
        de = 80 + 5 * c[sym["F_blend_time"]] - 4 * c[sym["F_disintegrant_pct"]] + random.gauss(0, 0.5)
        fr = 0.5 - 0.25 * c[sym["F_filler_ratio"]] + random.gauss(0, 0.02)
        rows.append(",".join([str(r["actual"][f]) for f in fids] + [f"{de:.2f}", f"{fr:.3f}", "10", "5",
                                                                    f"S{n}", "INDEPENDENT_BATCH", "SYNTHETIC_DEMO"]))
    svc.act(sid, "results_submit", {"csv": "\n".join(rows), "column_map": {
        **{f: f for f in fids}, "y1": "CQA_DISSOLUTION", "y2": "CQA_FRIABILITY", "y3": "CQA_DISPERSIBILITY",
        "y4": "CQA_CU_AV"}})
    st = svc.act(sid, "results_confirm", {"accept": True})
    cls = {d["factor_id"]: d["classification"] for d in st["screening"]["decisions"]}
    assert cls["F_blend_time"] == cls["F_disintegrant_pct"] == cls["F_filler_ratio"] == "ACTIVE"
    assert cls["F_lubricant_pct"] in ("FIXED", "RETAIN_FOR_SAFETY", "INCONCLUSIVE")
    if cls["F_lubricant_pct"] != "INCONCLUSIVE":
        assert st["status"] == "WAITING_RSM_APPROVAL"
        assert st["factors"]["F_lubricant_pct"]["disposition"] == "FIXED"
        assert len(st["plans"][-1]["factor_ids"]) == 3
    # MONITOR_ONLY CQA는 요인 판정의 not_evaluated에 자동 기록 (§15)
    assert any("파괴강도" in n for n in st["screening"]["decisions"][0]["not_evaluated"])


def test_tampered_handoff_goes_to_audit_review(svc):
    h = ho.lornoxicam_demo(svc.rb, "t")
    h["ingredients"][0]["pct_w_w"] = 5.0          # fingerprint를 다시 계산하지 않고 조성을 바꿈
    st = svc.create(h, mode="demo")
    assert st["status"] == "WAITING_AUDIT_REVIEW"
    assert any(t["reason"] == "LINEAGE_MISMATCH" for t in st["timeline"])
