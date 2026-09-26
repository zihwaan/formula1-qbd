"""잠정 design space · 권장 setpoint · 확인점 · family 예측구간 — 명세 v6.1 §6 D9·D10, 룰북 #21·#22.

평균 예측이 아니라 **미래 배치의 예측분포**로 영역을 만든다:

- 반응별 예측분포 = t(df = 잔차 자유도), 척도 = √(평균 SE² + 잔차분산)
- 공동확률 = 반응별 통과확률의 곱 (반응 간 독립 가정 — MVP 근사, 정책에 기록)
- supported domain = 설계점 convex hull (BBD면 coded |xᵢ| ≤ 1 이고 Σ|xᵢ| ≤ 2),
  분모 = domain 안의 격자점. 격자 밖 연속 영역을 보장한다고 쓰지 않는다.
- 권장 setpoint = domain 경계에서 0.1 coded 이상 떨어진 격자점 중 공동확률 최대
- 확인 PI = family(필수 확인점 × DOE_RESPONSE) Bonferroni, 개별 수준 = 1 − α_family / m

영역이 비면 규격을 자동 완화하지 않는다 — 그 판정(DR006 → STRATEGY_REVIEW)은 룰북이 한다.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
from scipy import stats
from scipy.spatial import ConvexHull

from formula.qbd.analysis import Fit
from formula.qbd.doe import Factor

HULL_TOL = 1e-9


class Domain:
    """설계점 convex hull. membership과 경계까지의 거리(coded)를 같은 facet 방정식으로 계산한다."""

    def __init__(self, design_coded: np.ndarray):
        pts = np.unique(np.round(design_coded, 9), axis=0)
        self.dim = pts.shape[1]
        self.lo, self.hi = pts.min(axis=0), pts.max(axis=0)
        if self.dim == 1:
            self.equations = np.array([[1.0, -self.hi[0]], [-1.0, self.lo[0]]])
        else:
            self.equations = ConvexHull(pts).equations      # n·x + d ≤ 0, |n| = 1

    def contains(self, X: np.ndarray) -> np.ndarray:
        return np.all(X @ self.equations[:, :-1].T + self.equations[:, -1] <= HULL_TOL, axis=1)

    def edge_distance(self, X: np.ndarray) -> np.ndarray:
        return np.min(-(X @ self.equations[:, :-1].T + self.equations[:, -1]), axis=1)

    def describe(self, design_type: str) -> str:
        if design_type == "BOX_BEHNKEN" and self.dim == 3:
            return "coded |xᵢ| ≤ 1 이고 Σ|xᵢ| ≤ 2 (BBD 설계점 convex hull)"
        return "설계점 convex hull"


def pass_probability(op: str, mean: np.ndarray, sd: np.ndarray, df: int, cqa: Dict[str, Any]) -> np.ndarray:
    """acceptance_operator별 통과확률 — t 예측분포."""
    lo, hi = _limits(op, cqa)
    cdf = lambda v: stats.t.cdf((v - mean) / sd, df)   # noqa: E731
    if op == "LE":
        return cdf(hi)
    if op == "GE":
        return 1 - cdf(lo)
    if op in ("BETWEEN", "TARGET_TOL"):
        return cdf(hi) - cdf(lo)
    raise ValueError(f"{op}는 연속 예측으로 판정할 수 없다")


def mean_passes(op: str, value, cqa: Dict[str, Any]):
    lo, hi = _limits(op, cqa)
    if op == "LE":
        return value <= hi if cqa.get("upper_inclusive", True) else value < hi
    if op == "GE":
        return value >= lo if cqa.get("lower_inclusive", True) else value > lo
    if op in ("BETWEEN", "TARGET_TOL"):
        return (value >= lo) & (value <= hi)
    raise ValueError(op)


def spec_pass(cqa: Dict[str, Any], value: Any) -> Optional[bool]:
    """관측값 1개의 규격 판정. PASS_FAIL은 1/0·PASS/FAIL. 판정 불가면 None."""
    op = cqa.get("acceptance_operator")
    if value is None or op is None:
        return None
    if op == "PASS_FAIL":
        return str(value).strip().upper() in ("1", "1.0", "PASS", "TRUE", "적합")
    try:
        return bool(mean_passes(op, float(value), cqa))
    except (TypeError, ValueError):
        return None


def _limits(op: str, cqa: Dict[str, Any]):
    if op == "TARGET_TOL":
        t, tol = cqa.get("target"), cqa.get("target_tolerance")
        return t - tol, t + tol
    return cqa.get("lower"), cqa.get("upper")


def compute_region(*, models: Dict[str, Fit], cqas: Dict[str, Dict[str, Any]], factors: List[Factor],
                   domain: Domain, grid_per_axis: int, joint_threshold: float, min_edge: float,
                   balance_fn: Optional[Callable[[Dict[str, float]], Optional[float]]] = None) -> Dict[str, Any]:
    symbols = [f.symbol for f in factors]
    axes = [np.linspace(domain.lo[i], domain.hi[i], grid_per_axis) for i in range(len(factors))]
    mesh = np.meshgrid(*axes, indexing="ij")
    X = np.column_stack([m.ravel() for m in mesh])
    coded = {s: X[:, i] for i, s in enumerate(symbols)}
    in_domain = domain.contains(X)
    if balance_fn is not None:
        bal = np.array([balance_fn({f.factor_id: f.to_actual(x[i]) for i, f in enumerate(factors)}) or 0.0
                        for x in X])
        in_domain &= bal >= -1e-9
    P = np.ones(len(X))
    mean_ok = np.ones(len(X), bool)
    marginals: Dict[str, np.ndarray] = {}
    for cid, fit in models.items():
        cqa = cqas[cid]
        pr = fit.predict(coded)
        pp = pass_probability(cqa["acceptance_operator"], pr["mean"], pr["sd_pred"], fit.df_resid, cqa)
        marginals[cid] = pp
        P *= pp
        mean_ok &= mean_passes(cqa["acceptance_operator"], pr["mean"], cqa)
    D = in_domain
    feasible = D & (P >= joint_threshold)
    edge = domain.edge_distance(X)
    cand = np.where(D & (edge >= min_edge - 1e-12))[0]
    setpoint = None
    if len(cand) and feasible[cand].any():
        i = int(cand[np.argmax(P[cand])])
        setpoint = _point(i, X, factors, P, marginals, edge)
    failing = np.where(D & (P < joint_threshold))[0]
    binding: Dict[str, int] = {}
    if len(failing):
        names = list(marginals)
        worst = np.argmin(np.column_stack([marginals[c][failing] for c in names]), axis=1)
        for w in worst:
            binding[names[w]] = binding.get(names[w], 0) + 1
    n_dom = int(D.sum())
    summary = {
        "grid_points_total": int(len(X)), "grid_points_in_domain": n_dom,
        "mean_ok_fraction": float(mean_ok[D].mean()) if n_dom else 0.0,
        "feasible_fraction": float(feasible[D].mean()) if n_dom else 0.0,
        "feasible_points": int(feasible.sum()),
        "binding_cqa_counts": dict(sorted(binding.items(), key=lambda kv: -kv[1])),
        "setpoint": setpoint,
        "all_points_in_domain": bool(np.all(D[feasible])),
    }
    grid = {"axes": [a.tolist() for a in axes], "symbols": symbols,
            "P": np.round(P, 4).tolist(), "in_domain": "".join("1" if d else "0" for d in D),
            "marginals": {c: np.round(v, 4).tolist() for c, v in marginals.items()}}
    summary["grid_hash"] = hashlib.sha256(json.dumps(grid["P"]).encode()).hexdigest()[:16]
    return {"summary": summary, "grid": grid, "X": X, "P": P, "D": D, "edge": edge,
            "marginals": marginals, "feasible": feasible}


def _point(i: int, X, factors, P, marginals, edge) -> Dict[str, Any]:
    return {
        "coded": {f.symbol: round(float(X[i, j]), 6) for j, f in enumerate(factors)},
        "actual": {f.factor_id: round(f.to_actual(float(X[i, j])), 4) for j, f in enumerate(factors)},
        "joint_probability": float(P[i]),
        "marginals": {c: float(v[i]) for c, v in marginals.items()},
        "edge_distance": float(edge[i]),
    }


def joint_at(models: Dict[str, Fit], cqas: Dict[str, Dict[str, Any]], coded_point: Dict[str, float]):
    one = {k: np.array([v]) for k, v in coded_point.items()}
    P, marg = 1.0, {}
    for cid, fit in models.items():
        pr = fit.predict(one)
        pp = float(pass_probability(cqas[cid]["acceptance_operator"], pr["mean"], pr["sd_pred"],
                                    fit.df_resid, cqas[cid])[0])
        marg[cid] = pp
        P *= pp
    return P, marg


def predict_point(models: Dict[str, Fit], coded_point: Dict[str, float], level: float) -> Dict[str, Any]:
    one = {k: np.array([v]) for k, v in coded_point.items()}
    out = {}
    for cid, fit in models.items():
        pi = fit.prediction_interval(one, level)
        lo = float(pi["lo"][0])
        # 이 도메인의 반응(시간·%·AV 등)은 정의상 0 이상이다. 원척도 정규 가정의 예측구간이 음수로
        # 내려가면(예: AV −2.1) 물리적으로 불가능한 값이라 0에서 자르고, 자른 사실과 원래 값을 남긴다
        # (개발자 수정 과제 P1-7). 판정(구간 안/밖)은 실측이 0 이상이라 절단 전후가 같다.
        out[cid] = {"mean": float(pi["mean"][0]), "pi_lower": max(0.0, lo), "pi_upper": float(pi["hi"][0]),
                    "pi_lower_raw": lo, "pi_truncated": lo < 0,
                    "pi_note": "하한 0에서 절단 — 원척도 정규 가정" if lo < 0 else ""}
    return out


def propose_verification_points(region: Dict[str, Any], *, models: Dict[str, Fit],
                                cqas: Dict[str, Dict[str, Any]], factors: List[Factor], domain: Domain,
                                joint_threshold: float, min_edge: float, family_alpha: float,
                                robustness_delta: float, reference: Optional[Dict[str, float]] = None,
                                include_challenge: bool = False) -> Dict[str, Any]:
    """필수 확인점 3개(SETPOINT·BOUNDARY·ROBUSTNESS) + 선택 점. 수치는 전부 모델에서 계산한다."""
    X, P, D, edge, feas = region["X"], region["P"], region["D"], region["edge"], region["feasible"]
    sp = region["summary"]["setpoint"]
    if sp is None:
        return {"points": [], "pi_policy": None, "reason": "권장 setpoint 없음"}
    n_doe = len(models)
    m = 3 * n_doe
    level = 1 - family_alpha / m
    pi_policy = {"family": "필수 확인점 × DOE_RESPONSE", "n_required_points": 3, "n_doe_responses": n_doe,
                 "comparisons": m, "family_alpha": family_alpha, "method": "BONFERRONI",
                 "per_comparison_level": level}
    symbols = [f.symbol for f in factors]

    def pack(role, coded_pt, rationale, **extra):
        Pj, marg = joint_at(models, cqas, coded_pt)
        pred = predict_point(models, coded_pt, level)
        for cid in pred:
            pred[cid]["pass_probability"] = marg[cid]
        return {
            "point_id": f"VP-{role}", "role": role,
            "coded": {s: round(float(coded_pt[s]), 4) for s in symbols},
            "settings": {f.factor_id: round(f.to_actual(coded_pt[f.symbol]), 4) for f in factors},
            "predicted": {"cqa": pred, "joint_probability": Pj, "pi_level": level},
            "rationale": rationale, **extra,
        }

    points = [pack("SETPOINT", sp["coded"], "공동확률 최대 · domain 경계에서 "
                                            f"{min_edge} coded 이상 떨어진 격자점")]
    # BOUNDARY — feasible 격자점 중 공동확률이 가장 낮은(영역 경계에 가장 가까운) 내부점
    idx = np.where(feas & (edge >= min_edge - 1e-12))[0]
    if len(idx):
        b = int(idx[np.argmin(P[idx])])
        worst = min(region["marginals"], key=lambda c: region["marginals"][c][b])
        points.append(pack("BOUNDARY", {s: float(X[b, j]) for j, s in enumerate(symbols)},
                           f"영역 안에서 공동확률이 가장 낮은 점 — 경계를 주도하는 CQA는 {worst}",
                           binding_cqa=worst))
    # ROBUSTNESS — setpoint ± 허용 변동(coded)의 꼭짓점 중 공동확률 최저
    corners = []
    for signs in itertools.product((-1, 1), repeat=len(symbols)):
        pt = {s: sp["coded"][s] + sg * robustness_delta for s, sg in zip(symbols, signs)}
        arr = np.array([[pt[s] for s in symbols]])
        if domain.contains(arr)[0]:
            corners.append((joint_at(models, cqas, pt)[0], pt))
    if corners:
        Pr, pt = min(corners, key=lambda c: c[0])
        points.append(pack("ROBUSTNESS", pt, f"setpoint ± {robustness_delta} coded(허용 변동 가정) "
                                              "꼭짓점 중 공동확률이 가장 낮은 점",
                           robustness_delta=robustness_delta))
    if include_challenge:
        out = np.where(D & (P < 0.5))[0]
        if len(out):
            c = int(out[np.argmin(P[out])])
            worst = min(region["marginals"], key=lambda k: region["marginals"][k][c])
            fail_p = 1 - float(region["marginals"][worst][c])
            points.append(pack("CHALLENGE", {s: float(X[c, j]) for j, s in enumerate(symbols)},
                               "영역 밖 음성대조 (선택)", expected_outcome="FAIL",
                               expected_fail_cqa=worst, expected_fail_probability=fail_p))
    if reference:
        coded_ref = {f.symbol: f.to_coded(reference[f.factor_id]) for f in factors}
        points.append(pack("REFERENCE_EXISTING", coded_ref,
                           "계획 전부터 존재하던 배치 — 참고 평가만(승격·무효화 근거 아님)",
                           results_public=True))
    return {"points": points, "pi_policy": pi_policy}


def edge_of(domain: Domain, coded_pt: Dict[str, float], symbols: Sequence[str]) -> float:
    return float(domain.edge_distance(np.array([[coded_pt[s] for s in symbols]]))[0])
