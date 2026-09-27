"""§6.D10 provisional 영역 · §6.D11 독립 확인 판정.

- 지지 domain = 설계점의 볼록 껍질(BBD: |xᵢ|≤1 · Σ|xᵢ|≤2 입방팔면체, FCCD·1요인: 정사각형·선분). 밖은 EXTRAPOLATION으로 가린다.
- 반응별 예측분포(t, 잔차 df)로 통과확률 → 반응 간 독립을 가정해 곱한 공동 통과확률(INDEPENDENT_APPROXIMATION 표시 필수).
- 확인 판정은 사전 잠근 예측구간과 규격의 2×2(§6.D11 표). 확인 lot은 fitting set에 넣지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Sequence

import numpy as np
from scipy import stats

from formula.doe.models import predict

P_MIN_DEMO = 0.90


def in_domain(design_type: str, P: np.ndarray) -> np.ndarray:
    inside = np.all(np.abs(P) <= 1 + 1e-9, axis=1)
    if design_type == "BBD":
        inside &= np.abs(P).sum(axis=1) <= 2 + 1e-9
    return inside


def pass_prob(resp: Dict[str, Any], mean: np.ndarray, se: np.ndarray, df: int) -> np.ndarray:
    op, lo, hi = resp["operator"], resp.get("lower"), resp.get("upper")
    cdf = lambda v: stats.t.cdf((v - mean) / se, df)  # noqa: E731
    if op == "LE":
        return cdf(hi)
    if op == "GE":
        return 1 - cdf(lo)
    if op == "BETWEEN":
        return cdf(hi) - cdf(lo)
    raise ValueError(op)


def mean_pass(resp: Dict[str, Any], v):
    op, lo, hi = resp["operator"], resp.get("lower"), resp.get("upper")
    if op == "LE":
        return v <= hi
    if op == "GE":
        return v >= lo
    if op == "BETWEEN":
        return (v >= lo) & (v <= hi)
    raise ValueError(op)


def compute_region(design_type: str, ids: Sequence[str], models: Dict[str, Dict[str, Any]], responses: Sequence[Dict[str, Any]],
                   *, steps: int = 21, p_min: float = P_MIN_DEMO) -> Dict[str, Any]:
    g = np.linspace(-1, 1, steps)
    P = np.array(np.meshgrid(*[g] * len(ids), indexing="ij")).reshape(len(ids), -1).T
    dom = in_domain(design_type, P)
    Pd = P[dom]
    pts = {i: Pd[:, j] for j, i in enumerate(ids)}
    joint = np.ones(len(Pd))
    mean_ok = np.ones(len(Pd), dtype=bool)
    per = {}
    for r in responses:
        m = models[r["id"]]
        pr = predict(m, pts)
        p = pass_prob(r, pr["mean"], pr["se_pred"], m["df_resid"])
        joint *= p
        mean_ok &= mean_pass(r, pr["mean"])
        per[r["id"]] = {"mean_pass_fraction": float(mean_pass(r, pr["mean"]).mean()), "p_mean": float(p.mean())}
    feasible = joint >= p_min
    best = int(np.argmax(joint))
    policy = {"grid_steps": steps, "p_min": p_min, "dependence_assumption": "INDEPENDENT_APPROXIMATION",
              "uncertainty": "t 예측분포(잔차 df) · 반응별 통과확률의 곱", "domain": "설계점 볼록 껍질"}
    region = {"status": "PROVISIONAL" if feasible.any() else "EMPTY", "policy": policy,
              "grid_points_total": int(len(P)), "grid_points_in_domain": int(dom.sum()),
              "mean_ok_fraction": float(mean_ok.mean()), "joint_ok_fraction": float(feasible.mean()),
              "per_response": per, "setpoint_coded": {i: float(Pd[best, j]) for j, i in enumerate(ids)},
              "setpoint_joint_p": float(joint[best]), "reason_codes": ["REGION_INDEPENDENCE_ASSUMED"] + ([] if feasible.any() else ["REGION_EMPTY"])}
    region["hash"] = hashlib.sha256(json.dumps({k: region[k] for k in ("policy", "joint_ok_fraction", "setpoint_coded")}, sort_keys=True).encode()).hexdigest()
    return region


def lock_verification_plan(point_coded: Dict[str, float], responses: Sequence[str], models: Dict[str, Dict[str, Any]], *,
                           level: float = 0.95, role: str = "SETPOINT") -> Dict[str, Any]:
    """결과를 보기 전에 예측구간을 계산해 잠근다(§6.D11) — locked_hash가 있어야 판정한다."""
    pts = {k: np.array([v]) for k, v in point_coded.items()}
    pis = {}
    for rid in responses:
        m = models[rid]
        pr = predict(m, pts)
        t = stats.t.ppf(0.5 + level / 2, m["df_resid"])
        mu, se = float(pr["mean"][0]), float(pr["se_pred"][0])
        pis[rid] = {"predicted": mu, "pi": [mu - t * se, mu + t * se], "level": level}
    plan = {"role": role, "point_coded": point_coded, "prediction_intervals": pis}
    plan["locked_hash"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan


def evaluate_verification(plan: Dict[str, Any], lots: Dict[str, List[float]], responses: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if not plan.get("locked_hash"):
        return {"route": "VERIFICATION_NOT_LOCKED", "promote": False}
    rows, codes = [], set()
    for rid, vals in lots.items():
        lo, hi = plan["prediction_intervals"][rid]["pi"]
        for i, v in enumerate(vals, 1):
            spec = bool(mean_pass(responses[rid], np.array(v)))
            inside = lo <= v <= hi
            code = ("VERIFICATION_PASSED" if spec and inside else "VERIFICATION_MODEL_MISMATCH" if spec
                    else "VERIFICATION_SPEC_FAILURE" if inside else "VERIFICATION_MODEL_AND_SPEC_FAILURE")
            codes.add(code)
            rows.append({"response": rid, "lot": i, "value": v, "spec_pass": spec, "inside_pi": inside, "code": code})
    worst = next((c for c in ("VERIFICATION_MODEL_AND_SPEC_FAILURE", "VERIFICATION_SPEC_FAILURE", "VERIFICATION_MODEL_MISMATCH") if c in codes),
                 "VERIFICATION_PASSED")
    return {"rows": rows, "route": worst, "promote": worst == "VERIFICATION_PASSED",
            "next_state": "VERIFIED_OPERATING_REGION" if worst == "VERIFICATION_PASSED" else "REGION_REVISION_REQUIRED"}
