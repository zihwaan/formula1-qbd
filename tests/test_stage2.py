"""2단계 Design Space 도출 — 15단계 HITL, 결정론 검사, toolkit(논문 Table 10·11 재현), 보고서."""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from formula.stage2 import agent as AG
from formula.stage2 import doe as T
from formula.stage2 import reference as REF
from formula.stage2 import report
from formula.stage2.model import STEPS, check, matrix_of
from formula.stage2.service import Stage2Service
from formula.stage2.store import StudyError, StudyStore


@pytest.fixture()
def svc(tmp_path):
    return Stage2Service(StudyStore(tmp_path / "s2.db"))


def cbd(svc):
    return svc.create(REF.prototype(), title="CBD", source={"locator": "Table 1"}, reference=True)["study"]["study_id"]


EDIT_REF = {"qtpp", "cqa", "rm_just", "fp_just", "design", "space"}
NOTE = "논문이 보고한 모형 차수를 그대로 비교하려고 수용"


def walk(svc, sid, upto="space", families=None):
    """CBD 논문 값으로 진행. 기본은 13단계(영역) 앞까지 — CBD는 공동확률 ≥ 0.90 영역이 비어 13단계에서 멈추는 것이 정답이다."""
    out = svc.act(sid, "run", {})
    for s in STEPS[1:]:
        if s == upto:
            return out
        if s in EDIT_REF:
            svc.act(sid, "use_reference", {})
        if s == "regression" and families:
            svc.act(sid, "save", {"data": {"chosen": families}})
        out = svc.act(sid, "approve", {"note": NOTE})
        assert not out["action_result"].get("blocked"), (s, out["action_result"], out["study"]["steps"][s]["checks"])
    return out


def test_paper_justifications_cover_every_cell():
    ctx = {"cqa": REF.step("cqa"), "prototype": REF.prototype()}
    for s in ("rm_just", "fp_just", "cqa", "qtpp", "prototype", "design"):
        assert not [c for c in check(s, REF.step(s), ctx) if c["level"] == "blocking"], s


def test_derived_matrices_equal_paper_tables_5_and_7():
    fx = REF.risk()
    order = fx["cqa"]["risk_order"]
    for just, table in (("rm_just", "rm_matrix"), ("fp_just", "fp_matrix")):
        m = matrix_of(REF.step(just), order)
        assert m["levels"] == fx[table]["levels"] and [v["name"] for v in m["variables"]] == fx[table]["variables"]


def test_full_walk_with_paper_values(svc):
    sid = cbd(svc)
    out = walk(svc, sid)
    assert out["current"] == "space" and len(out["study"]["approvals"]) == 12
    svc.act(sid, "use_reference", {})                                # 논문 규격: 경도 4–6 kgf · 붕해 ≤ 30 s · 마손도 ≤ 1 %
    out = svc.act(sid, "approve", {})
    reg13 = out["study"]["steps"]["space"]["data"]["region"]
    # 평균 예측으로는 영역이 있어 보이지만 미래 배치 공동확률 ≥ 0.90은 없다(경도 4–6 kgf 폭이 잔차에 비해 좁다) — 규격을 완화하지 않는다
    assert out["action_result"]["blocked"] == ["SPACE_EMPTY"] and reg13["status"] == "EMPTY"
    assert reg13["mean_ok_fraction"] > 0.4 and reg13["max_joint"] < 0.9 and next(iter(reg13["binding"])) == "Hardness"
    st = svc.raw(sid)
    rec = st["steps"]["recommend"]["data"]                            # 8단계는 코드가 만든 종합 정리 — 고르는 칸이 없다
    assert [c["variable"] for c in rec["candidates"]][:3] == ["MCC", "Compression force", "CCS"] and "selected" not in rec
    assert st["steps"]["recommend"]["source"] == "code"
    reg = {r["response"]: r for r in st["steps"]["regression"]["data"]["responses"]}
    assert reg["Hardness"]["family"] == reg["Hardness"]["suggested"] == "Linear"
    assert st["steps"]["surface"]["data"]["responses"] == ["Hardness", "DT", "Friability"]
    risk = report.risk_report(st)
    final = report.final_report(st, {})
    assert risk[:4] == final[:4] == b"%PDF" and len(final) > len(risk) > 20000


def test_toolkit_reproduces_paper_table_11_and_table_10():
    d = REF.design()
    fn, X, rn, Y = T.table_arrays(d)
    x = T.to_coded(X, T.coding(X))
    h = {r["source"]: r for r in T.anova("Linear", x, Y[:, 0], fn)["rows"]}
    assert round(h["Model"]["ss"], 2) == 10.73 and round(h["Model"]["p"], 4) == 0.0005 and round(h["A-Force"]["ss"], 2) == 8.04
    assert round(h["C-CCS"]["ss"], 4) == 0.1953 and h["Residual"]["df"] == 13 and round(h["Lack of fit"]["p"], 4) == 0.4043
    assert round(h["Pure error"]["ss"], 4) == 0.9687 and round(h["Cor total"]["ss"], 1) == 14.7
    dt = {r["source"]: r for r in T.anova("Quadratic", x, Y[:, 1], fn)["rows"]}
    assert round(dt["Model"]["p"], 4) == 0.2463 and round(dt["C²"]["ss"], 2) == 24.15 and round(dt["C²"]["p"], 4) == 0.0811
    fr = {r["source"]: r for r in T.anova("2FI", x, Y[:, 2], fn)["rows"]}
    assert round(fr["AC"]["p"], 4) == 0.0226 and round(fr["B-MCC"]["p"], 4) == 0.0015 and fr["AB"]["ss"] >= 0
    reg = {r["response"]: r for r in T.regression(d, REF.PAPER_FAMILIES)["responses"]}
    assert reg["Hardness"]["coded_eq"] == "Y1 = 6.040 + 1.002X1 + 0.5587X2 + 0.1562X3"
    assert reg["DT"]["coded_eq"].startswith("Y2 = 15.62 + 1.065X1 + 1.666X2 + 1.259X3 + 0.16X1X2 + 0.915X1X3")
    assert reg["DT"]["actual_eq"].startswith("Y2 = 89.26")                         # 논문 실제 단위 식과 같다


def test_only_current_step_and_derived_not_editable(svc):
    sid = cbd(svc)
    with pytest.raises(StudyError):
        svc.act(sid, "use_reference", {"step": "cqa"})
    walk(svc, sid, upto="qtpp")
    with pytest.raises(StudyError):
        svc.act(sid, "approve", {})                                   # 빈 QTPP
    svc.act(sid, "use_reference", {})
    svc.act(sid, "approve", {})
    for s in ("cqa", "rm_just"):
        svc.act(sid, "use_reference", {})
        svc.act(sid, "approve", {})
    assert svc.view(sid)["current"] == "rm_matrix"
    with pytest.raises(StudyError):
        svc.act(sid, "save", {"data": {"levels": []}})               # 5단계는 코드가 만든 정리
    with pytest.raises(StudyError):
        svc.act(sid, "draft", {})                                    # LLM 단계가 아니다


def test_justification_gaps_block(svc):
    sid = cbd(svc)
    walk(svc, sid, upto="fp_just")
    data = copy.deepcopy(REF.step("fp_just"))
    data["items"] = [i for i in data["items"] if i["variable"] != "Sucralose"]
    data["variables"] = [v for v in data["variables"] if v["name"] != "Sucralose"]
    data["variables"][-1]["name"] = "direct_compression"
    for i in data["items"]:
        if i["variable"] == "Compression force":
            i["variable"] = "direct_compression"
    data["items"][0]["cqas"] = data["items"][0]["cqas"][:1]
    svc.act(sid, "save", {"data": data})
    out = svc.act(sid, "approve", {})
    assert {"RISK_EXCIPIENT_MISSING", "RISK_PROCESS_IS_ROUTE", "JUST_MISSING"} <= set(out["action_result"]["blocked"])


def test_summary_step_needs_no_selection_and_design_factors_are_researchers(svc):
    sid = cbd(svc)
    walk(svc, sid, upto="recommend")
    v = svc.view(sid)
    assert v["current"] == "recommend" and not v["study"]["steps"]["recommend"]["checks"]
    with pytest.raises(StudyError):
        svc.act(sid, "save", {"data": {"selected": ["MCC"]}})       # 8단계는 코드가 만든 정리 — 저장할 것이 없다
    with pytest.raises(StudyError):
        svc.act(sid, "draft", {})                                    # LLM 추천도 없다
    out = svc.act(sid, "approve", {})                                # 확인만으로 다음 단계
    assert out["current"] == "design" and not out["action_result"].get("blocked")
    d = out["study"]["steps"]["design"]["data"]
    assert [f["name"] for f in d["factors"]] == [""] and [r["name"] for r in d["responses"]] == [""]   # 요인·반응 모두 연구자가 적는다
    assert "DESIGN_NAMES" in {c["code"] for c in out["study"]["steps"]["design"]["checks"]}
    bad = {"factors": [{"name": "MCC", "unit": "%"}], "responses": [{"name": "H", "unit": ""}],
           "rows": [{"std": 1, "run": 1, "x": [40], "y": [5]}, {"std": 2, "run": 2, "x": [40], "y": ["a"]}]}
    out = svc.act(sid, "save", {"data": bad})
    assert {"DESIGN_TOO_FEW", "DESIGN_ONE_LEVEL"} <= set(out["action_result"]["blocking"])


def test_regression_overfit_needs_reason(svc):
    sid = cbd(svc)
    walk(svc, sid, upto="regression")
    svc.act(sid, "use_reference", {})                                 # 논문 차수: DT 2차 · 마손도 2FI → 예측 R²가 수정 R²보다 한참 낮다
    out = svc.act(sid, "approve", {})
    assert "REG_OVERFIT_REASON" in out["action_result"]["blocked"]
    assert {c["response"] for c in out["study"]["steps"]["regression"]["checks"] if c["code"] == "REG_OVERFIT"} >= {"DT"}
    out = svc.act(sid, "approve", {"note": NOTE})
    assert out["current"] == "surface" and out["study"]["approvals"][-1]["note"] == NOTE


def test_regression_choice_aliased_blocks_and_reopen_marks_stale(svc):
    sid = cbd(svc)
    walk(svc, sid, upto="regression")
    out = svc.act(sid, "save", {"data": {"chosen": {"DT": "Quadratic"}}})
    reg = {r["response"]: r for r in out["study"]["steps"]["regression"]["data"]["responses"]}
    assert reg["DT"]["family"] == "Quadratic" and out["study"]["steps"]["regression"]["source"].endswith("user")
    out = svc.act(sid, "reopen", {"step": "cqa"})
    assert out["current"] == "cqa" and out["study"]["steps"]["design"]["status"] == "stale"


def test_llm_unavailable_fills_nothing(svc, monkeypatch):
    sid = cbd(svc)
    svc.act(sid, "run", {})

    def boom(step, ctx):
        raise AG.LLMUnavailable("no key")
    monkeypatch.setattr(AG, "draft", boom)
    with pytest.raises(StudyError) as e:
        svc.act(sid, "draft", {})
    assert e.value.status == 503 and svc.raw(sid)["steps"]["qtpp"]["data"] is None


def test_llm_grid_then_texts_always_cover_every_cell(monkeypatch):
    """근거 초안은 격자 → 묶음 → 문장. LLM이 문장을 일부 빠뜨려도 칸은 전부 덮이고 빈 문장은 검사가 잡는다."""
    ctx = {"prototype": REF.prototype(), "cqa": REF.step("cqa")}
    cq = REF.risk()["cqa"]["risk_order"]

    def fake(schema, system, user, max_tokens):
        if schema is AG._Grid:
            return AG._Grid(variables=[AG._Var(name="Particle size distribution", kind="material"), AG._Var(name="Flow properties", kind="material")],
                            rows=[AG._Row(cqa=c, levels=["High" if i < 2 else "Low", "Low"]) for i, c in enumerate(cq)])
        return AG._Texts(items=[AG._Text(group=0, text="입자크기 차이가 혼합 균일성에 영향. 위험은 높다.", basis="일반 제제학 지식")])
    monkeypatch.setattr(AG, "_call", fake)
    out = AG.draft("rm_just", ctx)["data"]
    chk = {c["code"] for c in check("rm_just", out, ctx)}
    assert "JUST_MISSING" not in chk and "JUST_DUPLICATE" not in chk and "JUST_EMPTY" in chk
    m = matrix_of(out, cq)
    assert m["levels"][0] == ["High", "Low"] and m["levels"][5] == ["Low", "Low"]


def test_surfaces_and_images(svc):
    sid = cbd(svc)
    walk(svc, sid, upto="surface")
    sf = svc.surfaces(sid)
    assert sf["kind"] == "SURFACE" and sf["slice_factor"]["name"] == "CCS" and len(sf["responses"][0]["slices"]) == 3
    assert svc.surfaces(sid, slice_factor=0)["slice_factor"]["name"] == "Force"
    png = "data:image/png;base64," + "iVBORw0KGgo="
    assert svc.act(sid, "attach_images", {"images": {"Hardness (a)": png, "x": "notimage"}})["action_result"]["images"] == 1


def test_one_factor_design_line():
    d = {"factors": [{"name": "F", "unit": "N"}], "responses": [{"name": "H", "unit": ""}],
         "rows": [{"std": i + 1, "run": i + 1, "x": [x], "y": [60 + 9 * a - 3 * a * a]} for i, (x, a) in
                  enumerate([(7, -1), (7, -1), (10, 0), (10, 0), (10, 0), (13, 1), (13, 1)])]}
    d["rows"][0]["y"][0] += 0.3
    reg = T.regression(d)
    sf = T.surfaces(d, reg)
    assert sf["kind"] == "LINE" and len(sf["responses"][0]["points"]) == 7
    assert np.isfinite(reg["responses"][0]["r2"])


# ── 13–15 Design Space · 확인계획 · 확인배치 — Almotairi 2022 로르녹시캄 분산정(실측 15 run) ─────────────────────────
def lornoxicam_design():
    import csv
    rows = list(csv.DictReader(open(Path(__file__).parent / "fixtures" / "lornoxicam_table3.csv", encoding="utf-8")))
    return {"factors": [{"name": "MCC:Mannitol", "unit": ""}, {"name": "Mixing time", "unit": "min"}, {"name": "Crospovidone", "unit": "%"}],
            "responses": [{"name": "DT", "unit": "s"}, {"name": "Friability", "unit": "%"}, {"name": "DE30", "unit": "%"}, {"name": "AV", "unit": ""}],
            "rows": [{"std": int(r["run"]), "run": int(r["run"]),
                      "x": [float(r["x1_mcc_mannitol_ratio"]), float(r["x2_mixing_time_min"]), float(r["x3_crospovidone_pct"])],
                      "y": [float(r["y1_dispersibility_s"]), float(r["y2_friability_pct"]), float(r["y3_de30_pct"]), float(r["y4_cu_av"])]} for r in rows]}


LX_SPECS = [{"response": "DT", "op": "LE", "upper": 180, "basis": "분산정 분산 3분 이내"}, {"response": "Friability", "op": "LE", "upper": 1.0, "basis": "USP <1216>"},
            {"response": "DE30", "op": "GE", "lower": 75, "basis": "프로젝트 목표(가정)"}, {"response": "AV", "op": "LE", "upper": 15, "basis": "USP <905> L1"}]


def test_lornoxicam_design_space_reproduces_golden_values():
    """발표 자료 10쪽: 평균 반응면 77.2 % → 공동확률 ≥ 0.90 47.6 %, 설정점 2.7 · 12.5분 · 6.8 %(P 0.991), DE30 예측구간 71.9–92.8."""
    from formula.stage2 import space as SP
    from formula.stage2.model import check as chk
    d = lornoxicam_design()
    auto = T.regression(d)
    assert {r["response"]: r["suggested"] for r in auto["responses"]} == {"DT": "Quadratic", "Friability": "Linear", "DE30": "Quadratic", "AV": "Quadratic"}
    flags = {c["response"] for c in chk("regression", auto, {}) if c["code"] == "REG_OVERFIT"}
    assert flags == {"AV"}                                             # AV 2차: 수정 R² 0.884 vs 예측 R² 0.481
    fr = next(r for r in auto["responses"] if r["response"] == "Friability")
    quad = next(x for x in fr["summary"]["rows"] if x["model"] == "Quadratic")
    assert round(quad["pred_r2"], 3) == 0.251 and round(fr["pred_r2"], 3) == 0.824   # 마손도는 2차 과적합 → 선형으로 제안
    R = SP.region(d, auto, LX_SPECS)
    assert (R["grid_points_total"], R["grid_points_in_domain"]) == (9261, 7501)
    assert round(R["mean_ok_fraction"], 3) == 0.772 and round(R["feasible_fraction"], 3) == 0.476 and next(iter(R["binding"])) == "DE30"
    sp = R["setpoint"]
    assert sp["actual"] == {"MCC:Mannitol": 2.7, "Mixing time": 12.5, "Crospovidone": 6.8} and round(sp["joint"], 3) == 0.991
    V = SP.plan(d, auto, LX_SPECS, R, reference={"label": "논문 최적", "settings": {"MCC:Mannitol": 3, "Mixing time": 11, "Crospovidone": 6.23}})
    assert [p["role"] for p in V["points"]] == ["SETPOINT", "BOUNDARY", "ROBUSTNESS", "REFERENCE"] and V["pi_policy"]["comparisons"] == 12
    de = V["points"][0]["predicted"]["DE30"]
    assert (round(de["mean"], 1), round(de["pi_lower"], 1), round(de["pi_upper"], 1)) == (82.3, 71.9, 92.8)
    sl = SP.slice_map(d, auto, LX_SPECS, fixed=1, level=0.5)
    assert sl["kind"] == "MAP" and sl["fixed"]["actual"] == 12.5 and len(sl["P"]) == 21 and len(sl["P"][0]) == 21


def test_space_vplan_verify_steps(svc):
    """13 규격 → 영역 · 14 확인계획(승인 = 잠금) · 15 확인배치 2×2. 확인 실측값은 테스트 전용 값이다(화면·보고서의 시연 데이터 아님)."""
    sid = cbd(svc)
    walk(svc, sid, upto="design")
    svc.act(sid, "save", {"data": lornoxicam_design()})
    svc.act(sid, "approve", {})
    out = svc.act(sid, "approve", {})                                  # 10 회귀 — AV 과적합이라 사유 없이는 막힌다
    assert "REG_OVERFIT_REASON" in out["action_result"]["blocked"]
    svc.act(sid, "approve", {"note": "AV는 예측 R² 0.48 — 사유를 기록하고 수용"})
    svc.act(sid, "approve", {})
    svc.act(sid, "approve", {})
    assert svc.view(sid)["current"] == "space"
    out = svc.act(sid, "approve", {})
    assert "SPACE_NO_SPEC" in out["action_result"]["blocked"]
    out = svc.act(sid, "save", {"data": {"specs": LX_SPECS}})
    assert round(out["study"]["steps"]["space"]["data"]["region"]["feasible_fraction"], 3) == 0.476
    out = svc.act(sid, "approve", {})
    assert out["current"] == "vplan"
    plan = out["study"]["steps"]["vplan"]["data"]["plan"]
    assert [p["role"] for p in plan["points"]] == ["SETPOINT", "BOUNDARY", "ROBUSTNESS"]
    out = svc.act(sid, "approve", {})
    vp = out["study"]["steps"]["vplan"]["data"]
    assert vp["locked_at"] and vp["plan_hash"] and out["current"] == "verify"
    out = svc.act(sid, "approve", {})
    assert {"VERIFY_INDEPENDENT", "VERIFY_MISSING"} <= set(out["action_result"]["blocked"])
    obs = [{"role": p["role"], "values": {n: round(v["mean"], 2) for n, v in p["predicted"].items()}} for p in plan["points"]]
    out = svc.act(sid, "save", {"data": {"independent": True, "observations": obs}})
    assert out["study"]["steps"]["verify"]["data"]["judgement"]["verdict"] == "VERIFIED"
    obs[0]["values"]["DE30"] = 60.0                                   # 설정점 DE30 규격 실패 → 무효화(경고와 함께 승인 가능)
    out = svc.act(sid, "save", {"data": {"independent": True, "observations": obs}})
    j = out["study"]["steps"]["verify"]["data"]["judgement"]
    assert j["verdict"] == "INVALIDATED" and any("진단" in a for a in j["advice"])
    out = svc.act(sid, "approve", {})
    assert out["done"]
    st = svc.raw(sid)
    pdf = report.final_report(st, {})
    assert pdf[:4] == b"%PDF" and len(pdf) > 60000
    out = svc.act(sid, "reopen", {"step": "vplan"})                   # 다시 열면 잠금이 풀리고 확인배치는 stale
    assert "locked_at" not in out["study"]["steps"]["vplan"]["data"] and out["study"]["steps"]["verify"]["status"] == "stale"


def test_candidates_are_high_only_and_low_dose_warning():
    from formula.stage2.model import candidates, watch_list
    m = {"cqas": ["Assay", "Content uniformity"], "variables": [{"name": "A", "kind": "formulation"}, {"name": "B", "kind": "process"}],
         "levels": [["High", "Medium"], ["Low", "Medium"]]}
    assert [c["variable"] for c in candidates(m)] == ["A"] and [c["variable"] for c in watch_list(m)] == ["B"]
    ctx = {"cqa": REF.step("cqa"), "prototype": REF.prototype()}          # CBD 10/250 mg = 4 % < 5 %
    codes = {c["code"] for c in check("fp_just", REF.step("fp_just"), ctx)}
    assert "RISK_LOW_DOSE" in codes                                      # 논문 Table 8에는 혼합 공정 변수가 없다 — 경고로 알린다


def test_step9_paper_fill_buttons_use_real_cited_tables(svc):
    """9단계 '논문 값 채우기' — 슬라이드 9(Monton 2026 Table 9)·발표 10쪽(Almotairi 2022 Table 3)의 실제 표만, 출처와 함께."""
    from formula.stage2 import paper_designs as PD
    sid = cbd(svc)
    opts = svc.view(sid)["paper_designs"]
    assert [o["key"] for o in opts][0] == "monton2026_t9" and opts[0]["match"]            # CBD study면 CBD 표가 앞
    with pytest.raises(StudyError):
        svc.act(sid, "use_paper", {"paper": "almotairi2022_t3"})                          # 9단계에서만
    walk(svc, sid, upto="design")
    with pytest.raises(StudyError):
        svc.act(sid, "use_paper", {"paper": "made_up"})
    out = svc.act(sid, "use_paper", {"paper": "monton2026_t9"})
    d = out["study"]["steps"]["design"]
    assert d["source"] == "paper" and d["data"]["rows"] == REF.design()["rows"] and d["data"]["paper"]["locator"] == "Table 9"
    out = svc.act(sid, "use_paper", {"paper": "almotairi2022_t3"})
    d = out["study"]["steps"]["design"]["data"]
    assert len(d["rows"]) == 15 and [f["name"] for f in d["factors"]] == ["MCC:Mannitol ratio", "Mixing time", "Crospovidone"]
    assert [r["name"] for r in d["responses"]] == ["Dispersion time", "Friability", "DE30", "AV"] and d["rows"][0]["y"] == [11, 0.7, 75.3, 14.82]
    assert "Almotairi" in d["paper"]["citation"] and not out["action_result"]["blocking"]
    out = svc.act(sid, "approve", {})
    fams = {r["response"]: r["suggested"] for r in out["study"]["steps"]["regression"]["data"]["responses"]}
    assert fams == {"Dispersion time": "Quadratic", "Friability": "Linear", "DE30": "Quadratic", "AV": "Quadratic"}   # 발표 10쪽과 같은 제안 모형
    assert PD.options("Lornoxicam")[0]["key"] == "almotairi2022_t3"
