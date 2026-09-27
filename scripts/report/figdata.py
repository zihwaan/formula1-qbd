"""보고서 그림용 수치 — 엔진을 실제로 돌려서 얻는다(손으로 적은 값 없음).

2단계는 Monton 2026(CBD 구강붕해정)의 표를 옮긴 fixture로 formula.stage2를 호출한다 — 위험 행렬(Table 5·7)은 근거 표(Table 6·8)에서
코드가 다시 만들고, 회귀식·ANOVA(Table 10·11)는 Table 9 원자료에서 다시 적합한다. study 하나를 논문 값으로 12단계 끝까지 실제로 진행해
승인·이벤트·검사 건수와 보고서 PDF 크기를 기록한다. 출력: docs/report/figdata.json
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

def stage2_block() -> dict:
    """2단계 — 논문 표 재현(행렬·회귀·ANOVA)과 study 한 건을 12단계 끝까지 진행한 기록."""
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
                     "summary": [{k: row.get(k) for k in ("model", "seq_p", "lof_p", "r2", "adj_r2", "pred_r2", "aliased", "suggested")} for row in a["summary"]["rows"]],
                     "suggested": a["suggested"], "reason": a["reason"], "paper_family": p["family"],
                     "coded_eq": p["coded_eq"], "actual_eq": p["actual_eq"], "paper_coded": pp.get("coded"),
                     "model_ss": model["ss"], "model_df": model["df"], "model_p": model["p"], "lof_p": lof["p"] if lof else None,
                     "paper_model_p": pp.get("model_p"), "paper_lof_p": pp.get("lof_p"), "residual_df": next(row["df"] for row in an["rows"] if row["source"] == "Residual"),
                     "paper_residual_df": pp.get("residual_df"), "r2": an["r2"], "adj_r2": an["adj_r2"], "pred_r2": an["pred_r2"],
                     "terms": [{"source": row["source"], "ss": row["ss"], "f": row["f"], "p": row["p"]} for row in an["rows"] if row.get("level") == 1 and "term" in row]})
    # study 한 건 — 논문 값으로 12단계
    svc = Stage2Service(StudyStore(Path(tempfile.mkdtemp()) / "s2.db"))
    sid = svc.create(REF.prototype(), title="CBD ODT (report)", source={"locator": "Table 1"}, reference=True, actor="report")["study"]["study_id"]
    svc.act(sid, "run", {}, actor="report")
    blocked = []
    for st in STEPS[1:]:
        if st in ("qtpp", "cqa", "rm_just", "fp_just", "recommend", "design", "regression"):
            svc.act(sid, "use_reference", {}, actor="report")
        out = svc.act(sid, "approve", {}, actor="report")
        if out["action_result"].get("blocked"):
            blocked.append(st)
    raw = svc.raw(sid)
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
            "walk": {"status": raw["status"], "blocked": blocked, "approvals": len(raw["approvals"]), "events": len(tr["events"]),
                     "decisions": len(tr["decisions"]), "risk_pdf_kb": round(len(risk_pdf) / 1024), "final_pdf_kb": round(len(final_pdf) / 1024)},
            "check_codes": {"blocking": codes, "warning": warns}}


out = {"manifest": manifest, "jury": jury, "counts": counts, "backtrack": bt,
       "strategies": strategies, "reviewers": reviewers, "stage2": stage2_block()}


(ROOT / "docs" / "report").mkdir(parents=True, exist_ok=True)
(ROOT / "docs" / "report" / "figdata.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("counts", "stage2")}, ensure_ascii=False, indent=1, default=str)[:6000])
