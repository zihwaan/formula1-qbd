"""§12 CBD ODT 문헌 재현 — 논문 식을 입력하지 않고 Table 9 원자료에서 다시 적합해 보고식과 나란히 둔다.

주장하지 않는 것(§12.5): CBD가 신약이라는 것, 공개 안 된 선행 batch 재현, CBD 범위의 다른 API 적용, 논문 control space 구현.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import numpy as np

from formula.doe import design as D
from formula.doe import gates as G
from formula.doe import region as RG
from formula.doe.contracts import FactorSpec
from formula.doe.models import predict, select_model
from formula.doe.package import DoePackage, package

FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/cbd_odt_monton2026.json"
KEY = {"X1": "force_psi", "X2": "mcc_pct", "X3": "ccs_pct"}


def _y(run: Dict[str, Any], rid: str) -> float:
    v = run[rid]
    return float(v["mean"] if "mean" in v else v["value"])


def factors_from(fx: Dict[str, Any]):
    ev = fx["range_evidence"]["prior_study_status"]
    return [FactorSpec(f["id"], f["name"], f["unit"], f["low"], f["center"], f["high"], kind=f["kind"],
                       quantity_kind="pressure" if f["unit"] == "psi" else "mass_fraction",
                       reference_value=f.get("reference_value"), reference_source="Table 1 prototype" if f.get("reference_value") is not None else None,
                       evidence_status={"low": ev, "center": ev, "high": ev}) for f in fx["factors"]]


def published_audit(fx: Dict[str, Any], selected: Dict[str, Dict[str, Any]]) -> list:
    """출판 보고값끼리, 그리고 재적합과 보고식의 차이 — 식을 고치지 않고 나란히 기록한다."""
    out = []
    pm = fx["published_models"]["hardness_kgf"]
    if "X1X2" in pm["actual_as_printed"].replace(" ", "") and "X1:X2" not in pm["anova_terms"]:
        out.append({"response": "hardness_kgf", "kind": "PUBLISHED_REPORT_INCONSISTENCY",
                    "detail": "Table 10 실제 단위 식에 X1X2 항이 있으나 Table 11 ANOVA는 주효과 3개(선형) 모형 — 보고값끼리 맞지 않는다",
                    "reason_code_registered": False})
    for rid, m in selected.items():
        pub = set(fx["published_models"][rid]["anova_terms"])
        mine = set(t for t in m["terms"] if t != "1")
        if pub != mine:
            out.append({"response": rid, "kind": "REFIT_DIFFERS_FROM_PUBLISHED",
                        "detail": f"논문 항 {sorted(pub)} · 재적합 선택 항 {sorted(mine)}", "reason_code_registered": None})
    return out


def run_replay(pkg: DoePackage = None, fx: Dict[str, Any] = None, *, accept_flags: bool = False) -> Dict[str, Any]:
    """accept_flags = 연구자의 MODEL_ACCEPTANCE_WITH_FLAGS 승인(RB00 human_approval_required). 코드가 대신 승인하지 않는다 —
    False면 VALID_WITH_FLAGS 모형이 있는 한 영역을 만들지 않고 승인 대기로 멈춘다."""
    pkg = pkg or package()
    fx = fx or json.loads(FIXTURE.read_text(encoding="utf-8"))
    factors = factors_from(fx)
    ids = [f.factor_id for f in factors]
    gate = G.range_evidence(pkg, factors, "LITERATURE_REPLAY")
    design_decision = G.select_design(pkg, factors)
    plan = D.generate("BBD", factors, seed=int(pkg.rulebooks["RB15"].get("random_seed", 20260926)))
    # 논문 17 run을 설계 표준점에 연결(§14.6 — 17개 행과 Table 9가 정확히 연결)
    runs = fx["runs"]
    coded = {i: np.array([D.to_coded(r[KEY[i]], f) for r in runs]) for i, f in zip(ids, factors)}
    design_pts = {tuple(r["coded"][i] for i in ids) for r in plan["runs"]}
    fixture_pts = [tuple(float(coded[i][k]) for i in ids) for k in range(len(runs))]
    link_ok = set(fixture_pts) == design_pts and len(fixture_pts) == 17
    center = np.all(np.stack([coded[i] for i in ids]) == 0, axis=0)
    models, summaries = {}, {}
    for resp in fx["responses"]:
        y = np.array([_y(r, resp["id"]) for r in runs])
        res = select_model(coded, y, center_mask=center, constants=pkg.constants)
        models[resp["id"]] = res["selected"]
        s = res["selected"]
        summaries[resp["id"]] = {"status": res["status"], "formula": s["formula"], "coef": s["coef"], "r2": s["r2"],
                                 "adj_r2": s["adj_r2"], "pred_r2": s["pred_r2"], "cv_rmse": s["cv_rmse"], "aicc": s["aicc"],
                                 "lack_of_fit": s["lack_of_fit"], "gate": res["gate"], "best_cv": res["best_cv"],
                                 "one_se_set": res["one_se_set"], "candidates": res["candidates"], "estimable": res["estimable"],
                                 "published": fx["published_models"][resp["id"]]}
    statuses = {k: v["status"] for k, v in summaries.items()}
    region = None
    blocked = [k for k, s in statuses.items() if s == "MODEL_INADEQUATE"]
    flagged = [k for k, s in statuses.items() if s == "VALID_WITH_FLAGS"]
    waiting_flag_approval = bool(flagged) and not accept_flags and not blocked
    if not blocked and not waiting_flag_approval:
        # 영역 정책은 결과를 보기 전에 잠근 상수(RB16 · const.joint_pass_probability · region_grid_points_per_axis) — 사후 완화 금지(DR011)
        region = RG.compute_region("BBD", ids, models, fx["responses"],
                                   steps=int(pkg.constants.get("region_grid_points_per_axis", 21)),
                                   p_min=float(pkg.constants.get("joint_pass_probability", RG.P_MIN_DEMO)))
    opt = fx["optimum"]
    opt_coded = {i: D.to_coded(opt[KEY[i]], f) for i, f in zip(ids, factors)}
    vplan = RG.lock_verification_plan(opt_coded, [r["id"] for r in fx["responses"]], models)
    lots = {rid: v["lots"] for rid, v in fx["verification"].items() if isinstance(v, dict)}
    verdict = None
    opt_in_region = None
    if region:
        # 확인점(논문 최적점)이 잠근 영역 안인가 — 영역 밖 점의 통과는 승격 근거가 되지 않는다
        pts = {i: np.array([opt_coded[i]]) for i in ids}
        jp = 1.0
        for r in fx["responses"]:
            pr = predict(models[r["id"]], pts)
            jp *= float(RG.pass_prob(r, pr["mean"], pr["se_pred"], models[r["id"]]["df_resid"])[0])
        in_dom = bool(RG.in_domain("BBD", np.array([[opt_coded[i] for i in ids]]))[0])
        opt_in_region = {"joint_p": jp, "in_domain": in_dom, "inside": in_dom and jp >= region["policy"]["p_min"]}
        verdict = RG.evaluate_verification(vplan, lots, {r["id"]: r for r in fx["responses"]})
    return {"source": {k: fx[k] for k in ("citation", "doi", "pmcid")}, "mode": "LITERATURE_REPLAY",
            "banner": pkg.config.display_banner + " · 문헌 재현 전용, 독립 검증 아님",
            "range_gate": gate, "design_decision": design_decision.as_dict(),
            "design": {"type": plan["design_type"], "runs": len(plan["runs"]), "validation": plan["validation"], "seed": plan["random_seed"],
                       "matrix_hash": plan["matrix_hash"], "fixture_linked": link_ok},
            "models": summaries, "region": region, "verification_plan": vplan, "verification": verdict,
            "audit": published_audit(fx, models), "package_hash": pkg.package_hash,
            "flags_accepted": accept_flags, "waiting_flag_approval": waiting_flag_approval, "flagged_responses": flagged,
            "optimum_coded": opt_coded, "optimum_in_region": opt_in_region,
            "final_state": final_state(blocked, waiting_flag_approval, region, verdict, opt_in_region)}


def final_state(blocked, waiting, region, verdict, opt) -> Dict[str, Any]:
    """상태와 그 근거 규칙. 영역이 비면 DR018(REGION_EMPTY → MODEL_INADEQUATE) — 확인 lot이 통과해도 승격하지 않는다."""
    if blocked:
        return {"state": "MODEL_INADEQUATE", "reason_code": "MODEL_INVALID", "rule": "RB14"}
    if waiting:
        return {"state": "WAITING_MODEL_APPROVAL", "reason_code": "MODEL_FLAGGED", "rule": "RB00 human_approval_required"}
    if region["status"] != "PROVISIONAL":
        return {"state": "MODEL_INADEQUATE", "reason_code": "REGION_EMPTY", "rule": "RB16 DR018"}
    if not opt["inside"]:
        return {"state": "REGION_REVISION_REQUIRED", "reason_code": "REGION_EXTRAPOLATION", "rule": "RB17 — 확인점이 잠근 영역 밖"}
    if verdict["promote"]:
        return {"state": "VERIFIED_OPERATING_REGION", "reason_code": "VERIFICATION_PASSED", "rule": "RB17"}
    return {"state": "REGION_REVISION_REQUIRED", "reason_code": verdict["route"], "rule": "RB17"}


def _raw_models(pkg: DoePackage = None) -> Dict[str, Dict[str, Any]]:
    """화면 곡면용 — 재현에서 자동 선택된 모형 그대로(공분산 포함). 부적합 모형도 설명용으로 그릴 수 있지만 영역은 만들지 않는다(§4 화면 6)."""
    pkg = pkg or package()
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    factors = factors_from(fx)
    ids = [f.factor_id for f in factors]
    coded = {i: np.array([D.to_coded(r[KEY[i]], f) for r in fx["runs"]]) for i, f in zip(ids, factors)}
    center = np.all(np.stack([coded[i] for i in ids]) == 0, axis=0)
    return {resp["id"]: select_model(coded, np.array([_y(r, resp["id"]) for r in fx["runs"]]), center_mask=center,
                                     constants=pkg.constants)["selected"] for resp in fx["responses"]}
