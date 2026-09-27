"""보고서 그림용 수치 — 엔진을 실제로 돌려서 얻는다(손으로 적은 값 없음).

Lornoxicam 사례는 tests/test_doe_engine.py 골든 테스트와 같은 입력(논문 Table 3 실측 15 run, 같은 규격)으로
formula.qbd를 호출한다. 출력: docs/report/figdata.json
"""
import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd

from formula.qbd import doe
from formula.qbd.analysis import Fit
from formula.qbd.design_space import Domain, compute_region

ROOT = Path(__file__).resolve().parents[2]


def _audited() -> int:
    """조건식 이름 전수검사가 대조한 식 수(죽은 이름이 있으면 보고서를 만들지 않는다)."""
    from scripts.audit_conditions import audit
    n, bad = audit()
    if bad:
        raise SystemExit(f"조건식 전수검사 실패: {bad}")
    return n
FIX = ROOT / "tests" / "fixtures"

d = pd.read_csv(FIX / "lornoxicam_table3.csv")
coded = {"a": (d.x1_mcc_mannitol_ratio - 2).values, "b": ((d.x2_mixing_time_min - 10) / 5).values,
         "c": ((d.x3_crospovidone_pct - 6) / 4).values}
ys = {"Y1": d.y1_dispersibility_s.values, "Y2": d.y2_friability_pct.values,
      "Y3": d.y3_de30_pct.values, "Y4": d.y4_cu_av.values}
Q = doe.quadratic_terms(["a", "b", "c"])
full = {k: Fit(Q, coded, v) for k, v in ys.items()}
models = dict(full)
models["Y2"] = Fit(doe.linear_terms(["a", "b", "c"]), coded, ys["Y2"])
SPEC = {"Y1": {"acceptance_operator": "LE", "upper": 180}, "Y2": {"acceptance_operator": "LE", "upper": 1.0},
        "Y3": {"acceptance_operator": "GE", "lower": 75}, "Y4": {"acceptance_operator": "LE", "upper": 15}}
FACTORS = [doe.Factor("x1", "a", 1, 3), doe.Factor("x2", "b", 5, 15), doe.Factor("x3", "c", 2, 10)]
domain = Domain(doe.box_behnken(3, 3))
reg = compute_region(models=models, cqas=SPEC, factors=FACTORS, domain=domain, grid_per_axis=21,
                     joint_threshold=0.90, min_edge=0.1)
s = reg["summary"]
sp = s["setpoint"]

# 단면: 혼합 시간(b)을 setpoint의 격자값에 고정한 a×c 평면 — 평균 기준과 공동확률 기준의 차이가 가장 큰 면
axes = [np.linspace(domain.lo[i], domain.hi[i], 21) for i in range(3)]
bi = int(np.argmin(np.abs(axes[1] - sp["coded"]["b"])))
X, P, D = reg["X"], reg["P"], reg["D"]
mask = np.isclose(X[:, 1], axes[1][bi])
from formula.qbd.design_space import mean_passes
mean_ok = np.ones(len(X), bool)
for cid, fit in models.items():
    pr = fit.predict({k: X[:, i] for i, k in enumerate(["a", "b", "c"])})
    mean_ok &= mean_passes(SPEC[cid]["acceptance_operator"], pr["mean"], SPEC[cid])
sl = {"rows": axes[0].tolist(), "cols": axes[2].tolist(), "row_factor": "a", "col_factor": "c",
      "fixed": "b", "fixed_coded": float(axes[1][bi]), "fixed_actual": FACTORS[1].to_actual(float(axes[1][bi])),
      "P": [], "in": [], "mean_ok": []}
for ia in range(21):
    rowP, rowD, rowM = [], [], []
    for ic in range(21):
        idx = np.where(mask & np.isclose(X[:, 0], axes[0][ia]) & np.isclose(X[:, 2], axes[2][ic]))[0][0]
        rowP.append(round(float(P[idx]), 4)); rowD.append(bool(D[idx])); rowM.append(bool(mean_ok[idx]))
    sl["P"].append(rowP); sl["in"].append(rowD); sl["mean_ok"].append(rowM)
m = mask & D
sl["mean_ok_fraction"] = float(mean_ok[m].mean())
sl["feasible_fraction"] = float((P[m] >= 0.90).mean())

fits = []
for k in ["Y1", "Y2", "Y3", "Y4"]:
    fits.append({"cqa": k, "full_r2": full[k].r2, "full_pred_r2": full[k].pred_r2,
                 "used_terms": "linear" if k == "Y2" else "quadratic",
                 "used_r2": models[k].r2, "used_pred_r2": models[k].pred_r2, "df_resid": models[k].df_resid})


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

def v7_block() -> dict:
    """DoE v7.0 — 패키지 건수, CBD 문헌 재현(자동 선택 모형 · 보고 항 구성 재적합), 저장형 study를 실제로 끝까지 돌린 승인 기록."""
    import tempfile
    from formula.development.store import StudyStore
    from formula.doe import dataset as DS
    from formula.doe.contracts import ACTIONS, APPROVAL_POINT, STATES
    from formula.doe.package import package
    from formula.doe.replay import run_replay, surfaces
    from formula.doe.service import DoeStudyService
    pkg = package()
    summ = pkg.summary()
    rp = run_replay(pkg, accept_flags=True)
    pub = {r["id"]: r["formula"] for r in surfaces(pkg, source="published")["responses"]}
    models = {k: {"formula": m["formula"], "status": m["status"], "r2": m["r2"], "adj_r2": m["adj_r2"], "pred_r2": m["pred_r2"],
                  "lof_p": m["lack_of_fit"].get("p"), "flags": [f["rule_id"] for f in m["gate"]["flags"]],
                  "published_terms": pub.get(k), "published_model_p": m["published"].get("model_p")} for k, m in rp["models"].items()}
    ver = rp["verification"] or {}
    svc = DoeStudyService(pkg, StudyStore(Path(tempfile.mkdtemp()) / "doe7.db"))
    ds = DS.validate(pkg, DS.cbd())
    sid = svc.create(DS.handoff(ds, "report"), study_type=ds["study_type"], dataset=ds)["study"]["study_id"]
    walk = []
    for a in ["handoff_confirm", "cqa_edit", "cqa_approve", "fmea_approve", "factor_select", "range_submit", "range_approve",
              "plan_approve", "results_submit", "results_confirm", "model_accept_flags"]:
        st = svc.view(sid)["study"]
        pl = {k: v for k, v in (DS.fill(st, a) or {}).items() if k not in ("note", "unmatched")}
        out = svc.act(sid, a, pl, actor="report")
        walk.append({"action": a, "status": out["study"]["status"], "blocked": (out.get("action_result") or {}).get("blocked")})
    st = svc.view(sid)["study"]
    return {"package": {k: summ[k] for k in ("rulebooks", "masters", "confirmation_tests", "reason_codes", "sources", "enforceable_rules")},
            "states": len(STATES), "actions": sum(len(v) for v in ACTIONS.values()), "approval_points": len(pkg.policy["human_approval_required"]),
            "approval_actions": len(APPROVAL_POINT), "fmea_factor_keys": len(DS.fmea_factor_keys(pkg)),
            "replay": {"models": models, "region": {k: rp["region"][k] for k in ("status", "setpoint_joint_p", "mean_ok_fraction", "joint_ok_fraction",
                                                                                 "grid_points_in_domain")} | {"p_min": rp["region"]["policy"]["p_min"]},
                       "verification_rows": len(ver.get("rows", [])), "verification_pass": sum(1 for r in ver.get("rows", []) if r["code"] == "VERIFICATION_PASSED"),
                       "optimum_joint_p": (rp.get("optimum_in_region") or {}).get("joint_p"), "final_state": rp["final_state"],
                       "design": rp["design"], "audit": [a["kind"] for a in rp["audit"]]},
            "study_walk": {"steps": walk, "final_status": st["status"], "approvals": [a["point"] for a in st["approvals"]],
                           "labloop": (st["labloop"].get("current") or {}).get("pattern_id"),
                           "labloop_tests": [t["test_id"] for t in (st["labloop"].get("current") or {}).get("tests", [])],
                           "events": len(svc.trace(sid)["events"])}}


out = {"manifest": manifest, "jury": jury, "region": {k: s[k] for k in ("grid_points_total", "grid_points_in_domain", "mean_ok_fraction",
                                    "feasible_fraction", "feasible_points", "binding_cqa_counts")},
       "setpoint": sp, "slice": sl, "fits": fits, "counts": counts, "backtrack": bt,
       "strategies": strategies, "reviewers": reviewers,
       "cook_max": float(full["Y1"].cooks_distance().max()), "v7": v7_block()}


(ROOT / "docs" / "report").mkdir(parents=True, exist_ok=True)
(ROOT / "docs" / "report" / "figdata.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("region", "setpoint", "fits", "counts", "v7")}, ensure_ascii=False, indent=1, default=str))
