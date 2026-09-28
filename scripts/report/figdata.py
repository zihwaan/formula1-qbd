"""보고서 그림용 수치 — 엔진을 실제로 돌려서 얻는다(손으로 적은 값 없음).

2단계는 Monton 2026(CBD 구강붕해정)의 표를 옮긴 fixture로 formula.stage2를 호출한다 — 위험 행렬(Table 5·7)은 근거 표(Table 6·8)에서
코드가 다시 만들고, 회귀식·ANOVA(Table 10·11)는 Table 9 원자료에서 다시 적합한다. study 하나를 논문 값으로 13단계(Design Space)까지 실제로 진행해
승인·이벤트·검사 건수와 보고서 PDF 크기를 기록한다. Design Space(공동확률)는 Almotairi 2022 로르녹시캄 분산정 실측 15 run(Table 3)으로
계산한다(발표 자료 10쪽). 출력: docs/report/figdata.json
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _audited() -> int:
    """조건식 이름 전수검사가 대조한 식 수(죽은 이름이 있으면 보고서를 만들지 않는다)."""
    from scripts.audit_conditions import audit
    n, bad = audit()
    if bad:
        raise SystemExit(f"조건식 전수검사 실패: {bad}")
    return n


def rows(path):
    with open(ROOT / path, encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


counts = {
    "structural_flags": len(rows("database/00_master/structural_flags_registry.csv")),
    "measurement_catalog": len(rows("database/reference/measurement_catalog.csv")),
    "data_request_triggers": len(rows("database/reference/data_request_triggers.csv")),
    "measurement_output_fields": len(rows("database/reference/measurement_output_fields.csv")),
    "conditions_audited": _audited(),
    "derived_quantities": len(rows("database/00_master/derived_quantities.csv")),
    "backtrack_transitions": len(rows("database/06_config/backtrack_transitions.csv")),
    "reviewers": len(rows("database/06_config/reviewer_registry.csv")),
    "strategies": len(rows("database/06_config/strategy_families.csv")),
    "confirmation_tests": len(rows("database/reference/confirmation_test_master.csv")),
    "evidence_requirements": len(rows("database/reference/evidence_requirements.csv")),
    "evidence_before": sum(1 for r in rows("database/reference/evidence_requirements.csv") if r.get("timing") == "before_protocol"),
}
bt = [{k: r[k] for k in ("transition_id", "trigger_type", "return_phase", "constraint_patch", "directive_hint")}
      for r in rows("database/06_config/backtrack_transitions.csv")]
strategies = [{k: r[k] for k in ("strategy_code", "family", "label_kr", "process_steps", "required_measurements")}
              for r in rows("database/06_config/strategy_families.csv")]
reviewers = [{k: r[k] for k in ("reviewer_id", "persona_name")} if "persona_name" in r else
             {"reviewer_id": r["reviewer_id"], "persona_name": list(r.values())[1]}
             for r in rows("database/06_config/reviewer_registry.csv")]

import yaml
manifest = [{"id": e["id"], "priority": e.get("trigger_priority"), "eval_type": e.get("eval_type"),
             "strategy": e.get("strategy"), "provides": e.get("provides"), "polarity": e.get("polarity") or "fail_when"}
            for e in yaml.safe_load((ROOT / "config" / "rulebook_manifest.yaml").read_text(encoding="utf-8"))]
jury = [{"reviewer_id": r["reviewer_id"], "name": r["reviewer_name_kr"], "condition": r["summon_condition"],
         "weight": r["base_weight"]} for r in rows("database/06_config/reviewer_registry.csv")]

def _fit_rows(r) -> list:
    return [{k: x.get(k) for k in ("model", "n_terms", "model_p", "lof_p", "adj_r2", "pred_r2", "aicc", "rank", "term_names")}
            | {"gate": bool((x.get("gate") or {}).get("passed")), "why": (x.get("gate") or {}).get("why") or []} for x in r["summary"]["rows"]]


def _region_brief(R) -> dict:
    return {k: R.get(k) for k in ("status", "approval", "slice", "control_space", "optimum", "mean_ok_fraction", "fail_fraction", "aux", "gate_passed")} | \
        {"slices": [{k: x[k] for k in ("level_actual", "ds_fraction", "p_max", "rect_area", "control")} for x in R.get("slices") or []],
         "unexplained": [{k: n[k] for k in ("response", "level", "text")} for n in R.get("unexplained") or []]}


def lornoxicam_block() -> dict:
    """발표 자료 10쪽 — Almotairi 2022 Table 3(실측 15 run) → 모형 선택·검증 게이트 · overlay Design Space · 확인계획. DE30 ≥ 75 %는 프로젝트 목표(가정).
    그림 9 = 13단계 화면과 같은 Overlay plot(docs/report/lornoxicam_overlay.png)."""
    from formula.stage2 import doe as T
    from formula.stage2 import space as SP
    rows = list(csv.DictReader(open(ROOT / "tests" / "fixtures" / "lornoxicam_table3.csv", encoding="utf-8")))
    d = {"factors": [{"name": "MCC:Mannitol", "unit": ""}, {"name": "Mixing time", "unit": "min"}, {"name": "Crospovidone", "unit": "%"}],
         "responses": [{"name": "Dispersion time", "unit": "s"}, {"name": "Friability", "unit": "%"}, {"name": "DE30", "unit": "%"}, {"name": "AV", "unit": ""}],
         "rows": [{"std": int(r["run"]), "run": int(r["run"]), "x": [float(r["x1_mcc_mannitol_ratio"]), float(r["x2_mixing_time_min"]), float(r["x3_crospovidone_pct"])],
                   "y": [float(r["y1_dispersibility_s"]), float(r["y2_friability_pct"]), float(r["y3_de30_pct"]), float(r["y4_cu_av"])]} for r in rows]}
    reg = T.regression(d)
    specs = [{"response": "Dispersion time", "op": "LE", "upper": 180, "basis": "분산정 3분 이내"}, {"response": "Friability", "op": "LE", "upper": 1.0, "basis": "USP <1216>"},
             {"response": "DE30", "op": "GE", "lower": 75, "basis": "프로젝트 목표(가정)"}, {"response": "AV", "op": "LE", "upper": 15, "basis": "USP <905> L1"}]
    R = SP.region(d, reg, specs)
    V = SP.plan(d, reg, specs, R, reference={"label": "논문 최적 처방", "settings": {"MCC:Mannitol": 3, "Mixing time": 11, "Crospovidone": 6.23}})
    (ROOT / "docs" / "report" / "lornoxicam_overlay.png").write_bytes(SP.render(d, reg, specs, fmt="png", caption=False, dpi=220))
    fit = [{"response": r["response"], "suggested": r["suggested"], "status": r["status"], "adj_r2": r.get("adj_r2"), "pred_r2": r.get("pred_r2"),
            "terms": next((x["term_names"] for x in r["summary"]["rows"] if x["model"] == r["family"]), []), "log": r["summary"]["log"],
            "rows": _fit_rows(r)} for r in reg["responses"]]
    return {"n": len(rows), "specs": specs, "fit": fit, "region": _region_brief(R),
            "plan": {"pi_policy": V["pi_policy"], "points": [{"role": p["role"], "settings": p["settings"], "joint": p["joint"],
                                                                "predicted": {n: {k: v[k] for k in ("mean", "pi_lower", "pi_upper", "spec")} for n, v in p["predicted"].items()}}
                                                               for p in V["points"]]},
            "reference_optimum": {"MCC:Mannitol": 3, "Mixing time": 11, "Crospovidone": 6.23}}


def stage2_block() -> dict:
    """2단계 — 논문 표 재현(행렬·회귀·ANOVA)과 study 한 건을 13단계까지 진행한 기록."""
    import tempfile
    from formula.stage2 import doe as T
    from formula.stage2 import reference as REF
    from formula.stage2 import report as RP
    from formula.stage2.model import STEPS, TITLE, candidates, matrix_of
    from formula.stage2.service import Stage2Service
    from formula.stage2.store import StudyStore
    r = REF.risk()
    cq = r["cqa"]["risk_order"]
    mats = {}
    for key, tbl in (("rm", "Table 5"), ("fp", "Table 7")):
        got = matrix_of(REF.step(f"{key}_just"), cq)
        pub = r[f"{key}_matrix"]
        cells = same = 0
        for i, c in enumerate(cq):
            for j, v in enumerate(got["variables"]):
                cells += 1
                pi, pj = pub["cqas"].index(c), pub["variables"].index(v["name"])
                same += got["levels"][i][j] == pub["levels"][pi][pj]
        mats[key] = {"table": tbl, "variables": len(got["variables"]), "cqas": len(cq), "cells": cells, "same": same,
                     "rows": len(r[f"{key}_just"]["items"]), "high": sum(x == "High" for row in got["levels"] for x in row)}
    fpm = matrix_of(REF.step("fp_just"), cq)
    cands = candidates(fpm)
    design = REF.design()
    auto = T.regression(design)
    paper = T.regression(design, REF.PAPER_FAMILIES)
    fn, X, rn, Y = T.table_arrays(design)
    x = T.to_coded(X, T.coding(X))
    pub = REF.doe()["published_models"]
    pkey = {"Hardness": "hardness_kgf", "DT": "dt_s", "Friability": "friability_pct"}
    resp = []
    for j, (a, p) in enumerate(zip(auto["responses"], paper["responses"])):
        an = T.anova(p["family"], x, Y[:, j], fn)
        model = next(row for row in an["rows"] if row["source"] == "Model")
        lof = next((row for row in an["rows"] if row["source"] == "Lack of fit"), None)
        pp = pub[pkey[a["response"]]]
        resp.append({"response": a["response"], "unit": a["unit"], "n": a["n"],
                     "summary": _fit_rows(a), "log": a["summary"]["log"], "status": a["status"],
                     "suggested": a["suggested"], "reason": a["reason"], "paper_family": p["family"], "paper_gate": p["status"],
                     "paper_gate_why": (p.get("gate") or {}).get("why") or [],
                     "coded_eq": p["coded_eq"], "actual_eq": p["actual_eq"], "paper_coded": pp.get("coded"),
                     "model_ss": model["ss"], "model_df": model["df"], "model_p": model["p"], "lof_p": lof["p"] if lof else None,
                     "paper_model_p": pp.get("model_p"), "paper_lof_p": pp.get("lof_p"), "residual_df": next(row["df"] for row in an["rows"] if row["source"] == "Residual"),
                     "paper_residual_df": pp.get("residual_df"), "r2": an["r2"], "adj_r2": an["adj_r2"], "pred_r2": an["pred_r2"],
                     "terms": [{"source": row["source"], "ss": row["ss"], "f": row["f"], "p": row["p"]} for row in an["rows"] if row.get("level") == 1 and "term" in row]})
    # study 한 건 — 논문 값으로 끝까지(10단계 논문 모형 → 게이트 통과한 경도만, 13단계 논문 규격 → overlay 영역 · control space, 14단계 잠금, 15단계는 실측 필요)
    svc = Stage2Service(StudyStore(Path(tempfile.mkdtemp()) / "s2.db"))
    sid = svc.create(REF.prototype(), title="CBD ODT (report)", source={"locator": "Table 1"}, reference=True, actor="report")["study"]["study_id"]
    svc.act(sid, "run", {}, actor="report")
    blocked = []
    for st in STEPS[1:]:
        if st in ("qtpp", "cqa", "rm_just", "fp_just", "design", "regression", "space", "vplan"):
            svc.act(sid, "use_reference", {}, actor="report")
        out = svc.act(sid, "approve", {"note": "논문이 보고한 모형 차수를 그대로 비교"}, actor="report")
        if out["action_result"].get("blocked"):
            blocked.append({"step": st, "codes": out["action_result"]["blocked"]})
            break
    raw = svc.raw(sid)
    cbd_space = raw["steps"]["space"]["data"]["region"] if raw["steps"]["space"]["data"] else None
    if cbd_space:
        from formula.stage2 import space as SP
        sd = raw["steps"]["space"]["data"]
        (ROOT / "docs" / "report" / "cbd_overlay.png").write_bytes(SP.render(raw["steps"]["design"]["data"], raw["steps"]["regression"]["data"],
                                                                                [x for x in sd["specs"] if x.get("op")], fmt="png", caption=False, dpi=220))
    tr = svc.trace(sid)
    risk_pdf = RP.risk_report(raw)
    final_pdf = RP.final_report(raw, {})
    src = (ROOT / "formula" / "stage2" / "model.py").read_text(encoding="utf-8")
    codes = sorted(set(re.findall(r'_c\("blocking", "([A-Z_]+)"', src)))
    warns = sorted(set(re.findall(r'_c\("warning", "([A-Z_]+)"', src)))
    return {"steps": [{"key": k, "title": TITLE[k]} for k in STEPS], "matrices": mats,
            "counts": {"qtpp": len(r["qtpp"]["items"]), "cqa": len(r["cqa"]["items"]), "cqa_in_risk": len(cq),
                       "cqa_is_cqa": sum(1 for c in r["cqa"]["items"] if c.get("is_cqa"))},
            "candidates": [{"variable": c["variable"], "high": c["high"], "medium": c["medium"]} for c in cands],
            "paper_doe": REF.PAPER_DOE_VARIABLES, "design": {"runs": len(design["rows"]), "factors": [f"{f['name']} ({f['unit']})" for f in design["factors"]],
                                                            "ranges": [[f["low"], f["high"]] for f in auto["factors"]]},
            "responses": resp,
            "cbd_space": _region_brief(cbd_space) if cbd_space else None,
            "cbd_vplan": [{"role": p["role"], "settings": p["settings"]} for p in ((raw["steps"]["vplan"]["data"] or {}).get("plan") or {}).get("points") or []],
            "cbd_vplan_locked": bool((raw["steps"]["vplan"]["data"] or {}).get("locked_at")),
            "lornoxicam": lornoxicam_block(),
            "walk": {"status": raw["status"], "blocked": blocked, "approvals": len(raw["approvals"]), "events": len(tr["events"]),
                     "decisions": len(tr["decisions"]), "risk_pdf_kb": round(len(risk_pdf) / 1024), "final_pdf_kb": round(len(final_pdf) / 1024)},
            "check_codes": {"blocking": codes, "warning": warns}}


out = {"manifest": manifest, "jury": jury, "counts": counts, "backtrack": bt,
       "strategies": strategies, "reviewers": reviewers, "stage2": stage2_block()}


(ROOT / "docs" / "report").mkdir(parents=True, exist_ok=True)
(ROOT / "docs" / "report" / "figdata.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("counts", "stage2")}, ensure_ascii=False, indent=1, default=str)[:6000])
