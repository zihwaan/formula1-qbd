"""§6.D9 자동 계층적 모델 선택 — 사용자가 회귀항을 고르지 않는다. 정책(RB13·RB15)은 결과를 보기 전에 고정돼 있다.

1) 강한 계층성을 지키는 후보 모형 전부(절편 고정)   2) rank·잔차 df·조건수 탈락
3) OLS · PRESS/LOOCV RMSE · 예측 R² · 수정 R² · AICc   4) 중심점 반복이 있으면 순수오차·적합결여(없으면 NOT_ESTIMABLE)
5) LOOCV RMSE 최소 모형의 1-SE 범위 안에서 항 수 최소 → AICc → 수정 R² → 정규화 식 문자열
6) 선택된 모형도 검증 gate(RB14)를 못 넘으면 MODEL_INADEQUATE — 영역을 만들지 않는다.
"""
from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from scipy import stats

from formula.qbd.doe import is_hierarchical, model_matrix

COND_MAX = 1e8


def candidate_terms(ids: Sequence[str]) -> List[str]:
    return list(ids) + [f"{a}:{b}" for a, b in itertools.combinations(ids, 2)] + [f"{i}^2" for i in ids]


def enumerate_models(ids: Sequence[str]) -> List[List[str]]:
    pool = candidate_terms(ids)
    out = []
    for r in range(0, len(pool) + 1):
        for combo in itertools.combinations(pool, r):
            terms = ["1"] + list(combo)
            if is_hierarchical(terms):
                out.append(terms)
    return out


def formula(terms: Sequence[str]) -> str:
    return " + ".join(t for t in terms)


def fit_ols(terms: Sequence[str], coded: Dict[str, np.ndarray], y: np.ndarray, center_mask: Optional[np.ndarray] = None) -> Dict[str, Any]:
    X = model_matrix(terms, coded)
    n, p = X.shape
    s = np.linalg.svd(X, compute_uv=False)
    rank = int((s > 1e-10 * s[0]).sum())
    cond = float(s[0] / s[-1]) if s[-1] > 0 else float("inf")
    res: Dict[str, Any] = {"terms": list(terms), "formula": formula(terms), "p": p, "n": n, "rank": rank, "cond": cond}
    if rank < p:
        return {**res, "rejected": "RANK_DEFICIENT"}
    if n - p < 1:
        return {**res, "rejected": "RESIDUAL_DF_LT_1"}
    if cond > COND_MAX:
        return {**res, "rejected": "ILL_CONDITIONED"}
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    fitted = X @ beta
    e = y - fitted
    sse = float(e @ e)
    sst = float(((y - y.mean()) ** 2).sum())
    H = X @ np.linalg.pinv(X.T @ X) @ X.T
    h = np.clip(np.diag(H), 0, 1 - 1e-12)
    loo = e / (1 - h)
    press = float(loo @ loo)
    df_res = n - p
    mse = sse / df_res
    r2 = 1 - sse / sst if sst > 0 else float("nan")
    adj = 1 - (1 - r2) * (n - 1) / df_res if sst > 0 else float("nan")
    pred = 1 - press / sst if sst > 0 else float("nan")
    aic = n * np.log(sse / n) + 2 * p
    aicc = aic + (2 * p * (p + 1)) / (n - p - 1) if n - p - 1 > 0 else float("inf")
    cooks = (e ** 2 / (p * mse)) * (h / (1 - h) ** 2)
    lof: Dict[str, Any] = {"status": "NOT_ESTIMABLE", "p": None}
    if center_mask is not None and center_mask.sum() >= 2:
        yc = y[center_mask]
        ss_pe = float(((yc - yc.mean()) ** 2).sum())
        df_pe = int(center_mask.sum() - 1)
        df_lof = df_res - df_pe
        if df_lof >= 1 and ss_pe > 0:
            ss_lof = sse - ss_pe
            F = (ss_lof / df_lof) / (ss_pe / df_pe)
            lof = {"status": "ESTIMABLE", "F": float(F), "p": float(stats.f.sf(F, df_lof, df_pe)), "df_lof": df_lof, "df_pe": df_pe}
        else:
            lof = {"status": "NOT_ESTIMABLE", "p": None, "df_pe": df_pe, "df_lof": df_lof}
    cov = mse * np.linalg.pinv(X.T @ X)
    return {**res, "coef": {t: float(b) for t, b in zip(terms, beta)}, "cov": cov.tolist(), "mse": mse, "df_resid": df_res,
            "sse": sse, "r2": r2, "adj_r2": adj, "pred_r2": pred, "press": press,
            "cv_rmse": float(np.sqrt(press / n)), "cv_rmse_se": float(np.std(loo ** 2, ddof=1) / np.sqrt(n) / (2 * np.sqrt(press / n)))
            if press > 0 else 0.0, "aicc": float(aicc), "leverage": h.tolist(), "cooks_d": cooks.tolist(),
            "lack_of_fit": lof, "fitted": fitted.tolist(), "residuals": e.tolist()}


def select_model(coded: Dict[str, np.ndarray], y: np.ndarray, *, center_mask: Optional[np.ndarray],
                 constants: Dict[str, float], nonphysical=None) -> Dict[str, Any]:
    ids = list(coded)
    fits = [fit_ols(t, coded, y, center_mask) for t in enumerate_models(ids)]
    ok = [f for f in fits if "rejected" not in f]
    history = [{"formula": f["formula"], "terms": len(f["terms"]) - 1, "rejected": f.get("rejected"),
                "cv_rmse": f.get("cv_rmse"), "aicc": f.get("aicc"), "adj_r2": f.get("adj_r2"), "pred_r2": f.get("pred_r2")} for f in fits]
    if not ok:
        return {"status": "MODEL_INADEQUATE", "reason": "NO_ESTIMABLE_CANDIDATE", "selected": None, "history": history}
    best = min(ok, key=lambda f: f["cv_rmse"])
    thr = best["cv_rmse"] + best["cv_rmse_se"]
    one_se = [f for f in ok if f["cv_rmse"] <= thr + 1e-12]
    one_se.sort(key=lambda f: (f["p"], f["aicc"], -f["adj_r2"], f["formula"]))
    sel = one_se[0]
    for hrow in history:
        if hrow["formula"] == sel["formula"]:
            hrow["selected"] = True
        elif hrow["rejected"] is None:
            hrow["in_one_se_set"] = any(f["formula"] == hrow["formula"] for f in one_se)
    gate = validate_model(sel, constants, nonphysical)
    return {"status": gate["status"], "selected": sel, "best_cv": best["formula"], "one_se_threshold": thr,
            "one_se_set": [f["formula"] for f in one_se], "gate": gate, "history": history,
            "candidates": len(fits), "estimable": len(ok), "policy": "LOOCV_RMSE · ONE_STANDARD_ERROR_THEN_FEWEST_TERMS"}


def validate_model(m: Dict[str, Any], c: Dict[str, float], nonphysical=None) -> Dict[str, Any]:
    """RB14(모형 검증) — 상수는 v6.1 statistical_policy_constants.csv(const.*)."""
    alpha = c.get("alpha", 0.05)
    flags, blocks = [], []
    if m["df_resid"] < c.get("residual_df_min", 1):
        blocks.append(("MV002", "잔차 자유도 부족"))
    lof = m["lack_of_fit"]
    if lof["status"] == "ESTIMABLE" and lof["p"] < alpha:
        blocks.append(("MV004", f"적합결여 유의(p={lof['p']:.3f})"))
    if lof["status"] != "ESTIMABLE":
        flags.append(("MV014", "적합결여 계산 불가 — '비유의'로 읽지 않는다"))
    if lof.get("df_pe") is not None and lof["df_pe"] <= c.get("pure_error_df_warning", 2):
        flags.append(("MV005", f"순수오차 자유도 {lof['df_pe']}"))
    if m["adj_r2"] - m["pred_r2"] > c.get("pred_r2_gap_flag", 0.2):
        flags.append(("MV006", f"수정 R² − 예측 R² = {m['adj_r2'] - m['pred_r2']:.2f}"))
    if m["pred_r2"] < c.get("pred_r2_min_flag", 0.5):
        flags.append(("MV007", f"예측 R² {m['pred_r2']:.2f}"))
    if any(d > c.get("cooks_d_flag", 1.0) for d in m["cooks_d"]):
        flags.append(("MV008", "Cook's D 영향점"))
    if any(hh > c.get("leverage_flag_multiplier", 2.0) * m["p"] / m["n"] for hh in m["leverage"]):
        flags.append(("MV009", "높은 leverage"))
    if nonphysical:
        blocks.append(("MV016", nonphysical))
    status = "MODEL_INADEQUATE" if blocks else ("VALID_WITH_FLAGS" if flags else "VALID")
    return {"status": status, "blocks": [{"rule_id": r, "detail": d} for r, d in blocks],
            "flags": [{"rule_id": r, "detail": d} for r, d in flags]}


def predict(m: Dict[str, Any], coded_points: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    X = model_matrix(m["terms"], coded_points)
    beta = np.array([m["coef"][t] for t in m["terms"]])
    cov = np.array(m["cov"])
    mean = X @ beta
    se_mean = np.sqrt(np.einsum("ij,jk,ik->i", X, cov, X))
    se_pred = np.sqrt(se_mean ** 2 + m["mse"])
    return {"mean": mean, "se_mean": se_mean, "se_pred": se_pred}
