"""2단계 Design Space 도출 — 12단계 HITL, 결정론 검사, toolkit(논문 Table 10·11 재현), 보고서."""
from __future__ import annotations

import copy

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


EDIT_REF = {"qtpp", "cqa", "rm_just", "fp_just", "recommend", "design"}


def walk(svc, sid, upto=None, families=None):
    out = svc.act(sid, "run", {})
    for s in STEPS[1:]:
        if s == upto:
            return out
        if s in EDIT_REF:
            svc.act(sid, "use_reference", {})
        if s == "regression" and families:
            svc.act(sid, "save", {"data": {"chosen": families}})
        out = svc.act(sid, "approve", {})
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
    assert out["done"] and len(out["study"]["approvals"]) == 12
    st = svc.raw(sid)
    rec = st["steps"]["recommend"]["data"]
    assert rec["selected"] == ["Compression force", "MCC", "CCS"] and rec["rule_rank"][:3] == ["MCC", "Compression force", "CCS"]
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


def test_recommend_limits_and_design_checks(svc):
    sid = cbd(svc)
    walk(svc, sid, upto="recommend")
    out = svc.act(sid, "save", {"data": {"selected": ["MCC", "CCS", "Compression force", "Spray-dried mannitol", "Sucralose"]}})
    assert {"REC_TOO_MANY", "REC_NOT_CANDIDATE"} <= set(out["action_result"]["blocking"])
    svc.act(sid, "save", {"data": {"selected": ["MCC", "CCS"]}})
    out = svc.act(sid, "approve", {})
    d = out["study"]["steps"]["design"]["data"]
    assert [f["name"] for f in d["factors"]] == ["MCC", "CCS"] and d["responses"][0]["name"] in ("Disintegration", "Dissolution")
    bad = {"factors": [{"name": "MCC", "unit": "%"}], "responses": [{"name": "H", "unit": ""}],
           "rows": [{"std": 1, "run": 1, "x": [40], "y": [5]}, {"std": 2, "run": 2, "x": [40], "y": ["a"]}]}
    out = svc.act(sid, "save", {"data": bad})
    assert {"DESIGN_TOO_FEW", "DESIGN_ONE_LEVEL"} <= set(out["action_result"]["blocking"])


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


def test_recommend_names_are_matched_to_candidates(monkeypatch):
    """LLM이 목록 형식('이름 (종류)')이나 대소문자를 바꿔 돌려줘도 후보 이름으로 맞추고, 목록 밖 이름은 버린 뒤 note에 남긴다."""
    from formula.stage2.model import RecItemOut, RecOut
    cands = [{"variable": "Compression force", "kind": "process", "high": ["Hardness"], "medium": []},
             {"variable": "MCC", "kind": "formulation", "high": ["Hardness"], "medium": []}]
    monkeypatch.setattr(AG, "_call", lambda *a, **k: RecOut(recommended=[
        RecItemOut(variable="Compression force (process)", reason="a"), RecItemOut(variable="mcc", reason="b"),
        RecItemOut(variable="Tablet shape", reason="c")], note=""))
    out = AG.draft("recommend", {"prototype": REF.prototype(), "candidates": cands})["data"]
    assert [r["variable"] for r in out["recommended"]] == ["Compression force", "MCC"]
    assert "Tablet shape" in out["note"]
