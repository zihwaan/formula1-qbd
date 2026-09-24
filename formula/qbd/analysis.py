"""회귀 적합·진단·축소·screening 효과 — 명세 v6.1 §6 D7·D8, 룰북 #19·#20.

사전 AnalysisPlan의 의도 항(기본: 전체 이차모형)으로만 적합한다. p값으로 항을 지우는
자동 stepwise는 없다 — 축소는 `fit()`을 연구자가 고른 항 목록으로 다시 부르는 것뿐이고,
그 호출은 서비스가 계층성 검사(AA010)와 승인 기록을 거친 뒤에만 한다.

numpy + scipy.stats만 쓴다. 이 모듈은 판정하지 않는다 — MV 규칙이 읽을 사실
(`model_context`)을 만들 뿐이고, VALID/FLAGGED는 룰 집행기가 정한다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from scipy import stats

from formula.qbd.doe import is_hierarchical, matrix_rank, model_matrix

TOOL_VERSIONS = {"engine": "formula1.qbd.analysis 1.0", "numpy": np.__version__,
                 "scipy": __import__("scipy").__version__}


def data_hash(coded: Dict[str, Sequence[float]], y: Sequence[float]) -> str:
    payload = {"x": {k: [round(float(v), 9) for v in vs] for k, vs in sorted(coded.items())},
               "y": [round(float(v), 9) for v in y]}
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:16]


class Fit:
    """OLS 한 번의 결과. statsmodels 없이 hat 행렬·PRESS·Cook's D까지 직접 계산한다."""

    def __init__(self, terms: Sequence[str], coded: Dict[str, np.ndarray], y: np.ndarray,
                 rel_tol: float = 1e-10):
        self.terms = list(terms)
        self.coded = {k: np.asarray(v, float) for k, v in coded.items()}
        self.y = np.asarray(y, float)
        X = model_matrix(self.terms, self.coded)
        self.X = X
        self.n, self.p = X.shape
        self.rank = matrix_rank(X, rel_tol)
        self.estimable = self.rank == self.p
        self.df_resid = self.n - self.p
        XtX_inv = np.linalg.pinv(X.T @ X)
        self.XtX_inv = XtX_inv
        self.beta = XtX_inv @ X.T @ self.y
        self.fitted = X @ self.beta
        self.resid = self.y - self.fitted
        self.sse = float(self.resid @ self.resid)
        self.sst = float(((self.y - self.y.mean()) ** 2).sum())
        self.scale = self.sse / self.df_resid if self.df_resid > 0 else float("nan")
        self.cov = XtX_inv * self.scale
        self.hat = np.einsum("ij,jk,ik->i", X, XtX_inv, X)

    # -- 적합 통계 -------------------------------------------------------------
    @property
    def r2(self) -> float:
        return 1 - self.sse / self.sst

    @property
    def adj_r2(self) -> float:
        if self.df_resid <= 0:
            return float("nan")
        return 1 - (self.sse / self.df_resid) / (self.sst / (self.n - 1))

    @property
    def press(self) -> float:
        with np.errstate(divide="ignore", invalid="ignore"):
            return float(((self.resid / (1 - self.hat)) ** 2).sum())

    @property
    def pred_r2(self) -> float:
        return 1 - self.press / self.sst

    def cooks_distance(self) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            return (self.resid ** 2 / (self.p * self.scale)) * self.hat / (1 - self.hat) ** 2

    # -- pure error / 적합결여 --------------------------------------------------
    def pure_error(self) -> Dict[str, Any]:
        keys = [tuple(round(float(self.coded[s][i]), 9) for s in sorted(self.coded)) for i in range(self.n)]
        groups: Dict[tuple, List[float]] = {}
        for k, v in zip(keys, self.y):
            groups.setdefault(k, []).append(float(v))
        ss_pe = sum(float(((np.array(g) - np.mean(g)) ** 2).sum()) for g in groups.values() if len(g) > 1)
        df_pe = sum(len(g) - 1 for g in groups.values() if len(g) > 1)
        return {"ss": ss_pe, "df": df_pe, "sd": (ss_pe / df_pe) ** 0.5 if df_pe else None,
                "replicated_points": sum(1 for g in groups.values() if len(g) > 1)}

    def lack_of_fit(self) -> Dict[str, Any]:
        pe = self.pure_error()
        df_lof = self.df_resid - pe["df"]
        if pe["df"] <= 0 or df_lof <= 0 or pe["ss"] <= 0:
            return {"computable": False, "df_lof": df_lof, "df_pe": pe["df"], "F": None, "p": None,
                    "reason": "반복점 없음" if pe["df"] <= 0 else "적합결여 자유도 없음"}
        ss_lof = self.sse - pe["ss"]
        F = (ss_lof / df_lof) / (pe["ss"] / pe["df"])
        return {"computable": True, "df_lof": df_lof, "df_pe": pe["df"], "F": F,
                "p": float(stats.f.sf(F, df_lof, pe["df"]))}

    # -- 잔차 구조 -------------------------------------------------------------
    def residual_checks(self, alpha: float) -> Dict[str, Any]:
        """잔차 ~ (적합값, 적합값²) 회귀로 곡선 패턴, 잔차² ~ 적합값으로 이분산을 본다."""
        out = {"residual_pattern": None, "heteroscedastic": None, "pattern_p": None, "hetero_p": None}
        if self.df_resid < 3 or np.ptp(self.fitted) == 0:
            return out
        f = (self.fitted - self.fitted.mean()) / (self.fitted.std() or 1)
        Z = np.column_stack([np.ones(self.n), f, f ** 2])
        g = np.linalg.lstsq(Z, self.resid, rcond=None)[0]
        e = self.resid - Z @ g
        ss_red = float(((Z @ g - self.resid.mean()) ** 2).sum())
        F = (ss_red / 2) / (float(e @ e) / (self.n - 3)) if float(e @ e) > 0 else 0.0
        out["pattern_p"] = float(stats.f.sf(F, 2, self.n - 3))
        r2 = self.resid ** 2
        slope, _, _, p_h, _ = stats.linregress(self.fitted, r2)
        out["hetero_p"] = float(p_h)
        out["residual_pattern"] = out["pattern_p"] < alpha
        out["heteroscedastic"] = out["hetero_p"] < alpha
        return out

    # -- 예측 ------------------------------------------------------------------
    def predict(self, coded_points: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        Xn = model_matrix(self.terms, {k: np.asarray(v, float) for k, v in coded_points.items()})
        mean = Xn @ self.beta
        se_mean = np.sqrt(np.einsum("ij,jk,ik->i", Xn, self.cov, Xn))
        return {"mean": mean, "se_mean": se_mean, "sd_pred": np.sqrt(se_mean ** 2 + self.scale)}

    def prediction_interval(self, coded_points: Dict[str, np.ndarray], level: float) -> Dict[str, np.ndarray]:
        pr = self.predict(coded_points)
        t = stats.t.ppf(1 - (1 - level) / 2, self.df_resid)
        return {"mean": pr["mean"], "lo": pr["mean"] - t * pr["sd_pred"], "hi": pr["mean"] + t * pr["sd_pred"]}

    def formula(self, response: str) -> str:
        return f"{response} ~ " + " + ".join(t for t in self.terms if t != "1")


def model_context(fit: Fit, *, alpha: float, fit_method: str, scope_hash: str,
                  inputs: List[Dict[str, Any]], batch_ids: List[str]) -> Dict[str, Any]:
    """MV 규칙이 읽는 `model` context (manifest context_schema.model)."""
    pe = fit.pure_error()
    lof = fit.lack_of_fit()
    res = fit.residual_checks(alpha)
    cook = fit.cooks_distance()
    runs = [{"cooks_d": float(cook[i]) if np.isfinite(cook[i]) else None,
             "leverage": float(fit.hat[i]), "batch_id": batch_ids[i] if i < len(batch_ids) else None,
             "influence_flag": False}
            for i in range(fit.n)]
    return {
        "validation_status": "PENDING", "df_resid": fit.df_resid,
        "hierarchical": is_hierarchical(fit.terms), "all_terms_estimable": fit.estimable,
        "lof_computable": lof["computable"], "lof_p": lof["p"], "pure_error_df": pe["df"],
        "adj_r2": _f(fit.adj_r2), "pred_r2": _f(fit.pred_r2), "n": fit.n, "p": fit.p,
        "fit_method": fit_method, "scope_hash": scope_hash, "inputs": inputs,
        "input_batch_ids": [b for b in batch_ids if b], "residual_pattern": res["residual_pattern"],
        "heteroscedastic": res["heteroscedastic"], "runs": runs,
        "local_prediction_se_high": None, "invalid_cause": None if fit.estimable else "RANK",
    }


def fit_summary(fit: Fit, response: str) -> Dict[str, Any]:
    pe = fit.pure_error()
    lof = fit.lack_of_fit()
    cook = fit.cooks_distance()
    se = np.sqrt(np.clip(np.diag(fit.cov), 0, None)) if fit.df_resid > 0 else np.full(fit.p, np.nan)
    tcrit = stats.t.ppf(0.975, fit.df_resid) if fit.df_resid > 0 else np.nan
    coefs = []
    for i, t in enumerate(fit.terms):
        coefs.append({"term": t, "estimate": _f(fit.beta[i]), "se": _f(se[i]),
                      "ci_lower": _f(fit.beta[i] - tcrit * se[i]), "ci_upper": _f(fit.beta[i] + tcrit * se[i])})
    worst = int(np.nanargmax(cook)) if np.isfinite(cook).any() else None
    return {
        "formula": fit.formula(response), "n": fit.n, "p": fit.p, "df_resid": fit.df_resid,
        "r2": _f(fit.r2), "adj_r2": _f(fit.adj_r2), "pred_r2": _f(fit.pred_r2), "press": _f(fit.press),
        "sigma": _f(fit.scale ** 0.5) if fit.df_resid > 0 else None,
        "coefficients": coefs, "pure_error": pe, "lack_of_fit": lof,
        "max_cooks": {"index": worst, "value": _f(cook[worst])} if worst is not None else None,
        "leverage_max": _f(fit.hat.max()), "rank": fit.rank,
    }


def screening_effects(fit: Fit, alpha: float) -> List[Dict[str, Any]]:
    """코딩 ±1 설계에서 요인 효과 = 2 × 계수, 효과구간 = 2 × 계수 CI (effect context)."""
    out = []
    if fit.df_resid <= 0:
        return out
    se = np.sqrt(np.clip(np.diag(fit.cov), 0, None))
    t = stats.t.ppf(1 - alpha / 2, fit.df_resid)
    for i, term in enumerate(fit.terms):
        if term == "1" or ":" in term or term.endswith("^2"):
            continue
        eff = 2 * fit.beta[i]
        out.append({"term": term, "actual": _f(eff), "ci_lower": _f(eff - 2 * t * se[i]),
                    "ci_upper": _f(eff + 2 * t * se[i])})
    return out


def curvature_test(y: np.ndarray, is_center: np.ndarray, alpha: float) -> Dict[str, Any]:
    """중심점 평균 vs 요인점 평균 (single-df curvature). 중심점 2개 미만이면 계산 불가."""
    yc, yf = y[is_center], y[~is_center]
    if len(yc) < 2 or len(yf) < 2:
        return {"significant": None, "p": None, "reason": "중심점 부족"}
    s2 = float(np.var(yc, ddof=1))
    if s2 == 0:
        return {"significant": None, "p": None, "reason": "중심점 분산 0"}
    diff = float(yf.mean() - yc.mean())
    se = (s2 * (1 / len(yf) + 1 / len(yc))) ** 0.5
    p = float(2 * stats.t.sf(abs(diff / se), len(yc) - 1))
    return {"significant": p < alpha, "p": p, "difference": diff}


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None
