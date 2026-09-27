"""§6.D6 설계 생성·검증 — 1요인 7 · FCCD(α=1) 13 · BBD 17. 외부 pyDOE에 기대지 않는다(생성 후 자체 Validator 필수).

coded↔actual은 조각 선형(−1→low, 0→center, +1→high): 비대칭 범위에서도 center가 정확히 0이 되고 왕복 오차가 0이다.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from typing import Any, Dict, List, Sequence, Optional

import numpy as np

from formula.doe.contracts import FactorSpec
from formula.qbd.doe import box_behnken, ccd, matrix_rank, model_matrix, quadratic_terms

CENTER_POINTS = 5
EXPECTED_RUNS = {"ONE_FACTOR_QUADRATIC": 7, "FCCD": 13, "BBD": 17}


def coded_matrix(design_type: str, k: int) -> np.ndarray:
    if design_type == "ONE_FACTOR_QUADRATIC":
        if k != 1:
            raise ValueError("1요인 설계")
        return np.array([[-1.0], [-1.0], [0.0], [0.0], [0.0], [1.0], [1.0]])   # low 2 · center 3 · high 2
    if design_type == "FCCD":
        if k != 2:
            raise ValueError("FCCD 기본값은 2요인")
        return ccd(2, CENTER_POINTS, face_centered=True)[0]                     # 4 factorial + 4 axial + 5 center
    if design_type == "BBD":
        if k != 3:
            raise ValueError("BBD 기본값은 3요인")
        return box_behnken(3, CENTER_POINTS)                                    # 12 edge-midpoint + 5 center
    raise ValueError(f"지원하지 않는 설계 {design_type}")


def to_actual(c: float, f: FactorSpec) -> float:
    return f.center + c * ((f.high - f.center) if c >= 0 else (f.center - f.low))


def to_coded(x: float, f: FactorSpec) -> float:
    return (x - f.center) / ((f.high - f.center) if x >= f.center else (f.center - f.low))


def generate(design_type: str, factors: Sequence[FactorSpec], *, seed: int) -> Dict[str, Any]:
    C = coded_matrix(design_type, len(factors))
    order = np.random.default_rng(seed).permutation(len(C))    # 같은 계약·seed → 같은 순서(§14.3)
    runs = []
    for run_no, idx in enumerate(order, 1):
        coded = {f.factor_id: float(C[idx, j]) for j, f in enumerate(factors)}
        runs.append({"run_id": f"R{run_no:02d}", "std_order": int(idx) + 1, "run_order": run_no,
                     "coded": coded, "actual": {f.factor_id: round(to_actual(coded[f.factor_id], f), 10) for f in factors},
                     "is_center": all(v == 0 for v in coded.values())})
    plan = {"design_type": design_type, "factors": [f.factor_id for f in factors], "random_seed": seed,
            "center_points": int(sum(r["is_center"] for r in runs)), "runs": runs,
            "intended_model_family": "HIERARCHICAL_QUADRATIC"}
    plan["matrix_hash"] = hashlib.sha256(json.dumps([[r["std_order"], r["coded"]] for r in runs], sort_keys=True).encode()).hexdigest()
    plan["validation"] = validate(plan, factors)
    return plan


def validate(plan: Dict[str, Any], factors: Sequence[FactorSpec]) -> Dict[str, Any]:
    """§6.D6 Validator — 하나라도 실패하면 ok=False(계획 승인 불가)."""
    ids = [f.factor_id for f in factors]
    runs = plan["runs"]
    coded = {i: np.array([r["coded"][i] for r in runs]) for i in ids}
    checks: List[Dict[str, Any]] = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    exp = EXPECTED_RUNS.get(plan["design_type"])
    add("run_count", exp is None or len(runs) == exp, f"{len(runs)} runs (기대 {exp})")
    rt = max(abs(to_coded(r["actual"][f.factor_id], f) - r["coded"][f.factor_id]) for r in runs for f in factors)
    add("coded_actual_round_trip", rt < 1e-9, f"최대 오차 {rt:.1e}")
    terms = quadratic_terms(ids) if len(ids) > 1 else ["1", ids[0], f"{ids[0]}^2"]
    X = model_matrix(terms, coded)
    rank = matrix_rank(X, 1e-10)
    add("full_quadratic_estimable", rank == len(terms), f"rank {rank}/{len(terms)}")
    pts = [tuple(r["coded"][i] for i in ids) for r in runs if not r["is_center"]]
    add("no_duplicate_noncenter_runs", len(pts) == len(set(pts)), f"{len(pts) - len(set(pts))}개 중복")
    n_c = plan["center_points"]
    add("center_replicates", n_c >= 3, f"중심점 {n_c}개 → pure error df {max(n_c - 1, 0)}")
    inb = all(min(f.low, f.high) - 1e-9 <= r["actual"][f.factor_id] <= max(f.low, f.high) + 1e-9 for r in runs for f in factors)
    add("within_low_high", inb)
    add("randomized", sorted(r["run_order"] for r in runs) == list(range(1, len(runs) + 1)) and plan.get("random_seed") is not None,
        f"seed {plan.get('random_seed')}")
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "pure_error_df": max(n_c - 1, 0)}


def classify(runs: Sequence[Dict[str, Any]], ids: Sequence[str]) -> Optional[str]:
    """실행된 행렬의 설계점 집합이 표준 설계(1요인 3수준 · FCCD · BBD)와 같으면 그 이름 — 지지 영역(domain) 정책에 쓴다.
    중심점 반복 수는 보지 않는다(run 수 검사는 Validator 몫)."""
    pts = {tuple(round(float(r["coded"][i]), 6) for i in ids) for r in runs}
    for dt in ("ONE_FACTOR_QUADRATIC", "FCCD", "BBD"):
        try:
            C = coded_matrix(dt, len(ids))
        except (ValueError, KeyError, IndexError):
            continue
        if {tuple(round(float(v), 6) for v in row) for row in C} == pts:
            return dt
    return None
