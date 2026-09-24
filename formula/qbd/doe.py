"""DoE 설계 생성·코딩·검증 context — 명세 v6.1 §6 D5, §7.3 backend capability, 룰북 #13·#15.

행렬과 run 수는 여기(코드)가 만든다. LLM은 이 모듈을 부르지도, 결과를 고치지도 않는다.

pyDOE3 대신 numpy로 직접 생성한다: MVP 백엔드가 지원하는 설계(부분요인·PB·BBD·CCD·FCCD)는
교과서 표 그대로라 몇 줄이면 되고, 그러면 "특정 패키지가 설계 타당성을 보장한다고 가정하지
않는다"(§12.2)를 코드 수준에서 지킬 수 있다 — 생성기 이름·버전·seed를 plan에 남기고,
타당성은 `validation_context()`가 만든 context를 DV 규칙이 판정한다.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

GENERATOR = {"name": "formula1.qbd.doe", "version": "1.0", "numpy": np.__version__}

# 설계 선택 결과 코드(DS 규칙 result_code) → 설계군
RECOMMENDATION = {
    "DESIGN_BBD": "BOX_BEHNKEN", "DESIGN_FCCD": "FACE_CENTERED_CCD", "DESIGN_CCD": "CCD",
    "DESIGN_RES_IV_FF": "FRACTIONAL_FACTORIAL", "DESIGN_FF_WITH_2LEVEL_CATEGORICAL": "FRACTIONAL_FACTORIAL",
}

# Plackett–Burman 12-run 생성 행 (Plackett & Burman 1946)
_PB12 = [1, 1, -1, 1, 1, 1, -1, -1, -1, 1, -1]


@dataclass
class Factor:
    """설계에 들어가는 연속 요인 하나 (승인된 FactorDefinition의 수치 부분)."""

    factor_id: str
    symbol: str
    low: float
    high: float

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2

    @property
    def half(self) -> float:
        return (self.high - self.low) / 2

    def to_actual(self, coded: float) -> float:
        return self.mid + coded * self.half

    def to_coded(self, actual: float) -> float:
        return (actual - self.mid) / self.half if self.half else 0.0


# ── 설계 행렬 (coded) ──────────────────────────────────────────────────────
def box_behnken(k: int, centers: int) -> np.ndarray:
    if k != 3:
        raise ValueError("MVP Box–Behnken은 연속요인 3개만 지원한다 (manifest backend_capabilities)")
    rows = []
    for i, j in itertools.combinations(range(k), 2):
        for a, b in itertools.product((-1, 1), repeat=2):
            r = [0] * k
            r[i], r[j] = a, b
            rows.append(r)
    rows += [[0] * k for _ in range(centers)]
    return np.array(rows, dtype=float)


def full_factorial(k: int) -> np.ndarray:
    # 표준 순서(Yates): 첫 요인이 가장 빨리 바뀐다
    return np.array([[1.0 if (i >> j) & 1 else -1.0 for j in range(k)] for i in range(2 ** k)])


def fractional_factorial(k: int, centers: int) -> Tuple[np.ndarray, Dict[str, Any]]:
    """3요인 = 2³ 완전요인, 4요인 = 2⁴⁻¹ (D = ABC, I = ABCD, Resolution IV)."""
    if k == 3:
        base = full_factorial(3)
        info = {"defining_relation": None, "resolution": 99, "generators": []}
    elif k == 4:
        base = full_factorial(3)
        base = np.column_stack([base, base[:, 0] * base[:, 1] * base[:, 2]])
        info = {"defining_relation": "I = ABCD", "resolution": 4, "generators": ["D = ABC"]}
    else:
        raise ValueError("MVP 부분요인은 3–4요인")
    return np.vstack([base, np.zeros((centers, k))]), info


def plackett_burman(k: int, centers: int) -> np.ndarray:
    if not 3 <= k <= 4:
        raise ValueError("MVP Plackett–Burman은 3–4요인")
    rows = [np.roll(_PB12, s) for s in range(11)] + [[-1] * 11]
    m = np.array(rows, dtype=float)[:, :k]
    return np.vstack([m, np.zeros((centers, k))])


def ccd(k: int, centers: int, face_centered: bool) -> Tuple[np.ndarray, float]:
    if not 2 <= k <= 3:
        raise ValueError("MVP CCD는 연속요인 2–3개")
    alpha = 1.0 if face_centered else (2 ** k) ** 0.25   # rotatable
    fac = full_factorial(k)
    axial = []
    for i in range(k):
        for s in (-alpha, alpha):
            r = [0.0] * k
            r[i] = s
            axial.append(r)
    return np.vstack([fac, np.array(axial), np.zeros((centers, k))]), alpha


# ── 모형 항 ────────────────────────────────────────────────────────────────
def quadratic_terms(symbols: Sequence[str]) -> List[str]:
    main = list(symbols)
    inter = [f"{a}:{b}" for a, b in itertools.combinations(symbols, 2)]
    sq = [f"{s}^2" for s in symbols]
    return ["1"] + main + inter + sq


def linear_terms(symbols: Sequence[str]) -> List[str]:
    return ["1"] + list(symbols)


def term_column(term: str, coded: Dict[str, np.ndarray], n: int) -> np.ndarray:
    if term == "1":
        return np.ones(n)
    if term.endswith("^2"):
        return coded[term[:-2]] ** 2
    col = np.ones(n)
    for part in term.split(":"):
        col = col * coded[part]
    return col


def model_matrix(terms: Sequence[str], coded: Dict[str, np.ndarray]) -> np.ndarray:
    n = len(next(iter(coded.values())))
    return np.column_stack([term_column(t, coded, n) for t in terms])


def matrix_rank(X: np.ndarray, rel_tol: float) -> int:
    s = np.linalg.svd(X, compute_uv=False)
    if s.size == 0:
        return 0
    return int((s > rel_tol * s[0]).sum())


def parents(term: str) -> List[str]:
    if term == "1":
        return []
    if term.endswith("^2"):
        return [term[:-2]]
    parts = term.split(":")
    return parts if len(parts) > 1 else []


def is_hierarchical(terms: Sequence[str]) -> bool:
    have = set(terms)
    return all(p in have for t in terms for p in parents(t))


def alias_structure(matrix: np.ndarray, symbols: Sequence[str]) -> Dict[str, Any]:
    """2수준 부분(중심점 제외)에서 주효과·2인자 상호작용의 완전 alias 쌍."""
    fac = matrix[np.all(np.abs(matrix) == 1, axis=1)]
    if len(fac) == 0:
        return {"pairs": [], "partial": []}
    coded = {s: fac[:, i] for i, s in enumerate(symbols)}
    terms = list(symbols) + [f"{a}:{b}" for a, b in itertools.combinations(symbols, 2)]
    cols = {t: term_column(t, coded, len(fac)) for t in terms}
    pairs, partial = [], []
    for a, b in itertools.combinations(terms, 2):
        r = float(np.dot(cols[a], cols[b]) / len(fac))
        if abs(abs(r) - 1) < 1e-9:
            pairs.append([a, b])
        elif abs(r) > 1e-9:
            partial.append([a, b, round(r, 3)])
    return {"pairs": pairs, "partial": partial}


# ── plan 생성 ──────────────────────────────────────────────────────────────
def generate(design_type: str, factors: List[Factor], *, seed: int, centers: int = 3) -> Dict[str, Any]:
    """설계 행렬 + run order + 의도 모형 항. 값은 전부 결정론(같은 seed → 같은 순서)."""
    k = len(factors)
    symbols = [f.symbol for f in factors]
    info: Dict[str, Any] = {}
    stage = "RSM"
    if design_type == "BOX_BEHNKEN":
        matrix = box_behnken(k, centers)
        terms = quadratic_terms(symbols)
    elif design_type in ("CCD", "FACE_CENTERED_CCD"):
        matrix, alpha = ccd(k, centers, face_centered=design_type == "FACE_CENTERED_CCD")
        terms = quadratic_terms(symbols)
        info["alpha"] = round(alpha, 4)
    elif design_type == "FRACTIONAL_FACTORIAL":
        matrix, info = fractional_factorial(k, centers)
        terms = linear_terms(symbols)
        stage = "SCREENING"
    elif design_type == "PLACKETT_BURMAN":
        matrix = plackett_burman(k, centers)
        terms = linear_terms(symbols)
        info = {"resolution": 3}
        stage = "SCREENING"
    else:
        raise ValueError(f"MVP 백엔드가 생성하지 않는 설계: {design_type}")
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(matrix))
    runs = []
    for std_idx, row in enumerate(matrix):
        runs.append({
            "std_order": std_idx + 1,
            "run_order": int(np.where(order == std_idx)[0][0]) + 1,
            "coded": {s: float(row[i]) for i, s in enumerate(symbols)},
            "actual": {f.factor_id: round(f.to_actual(float(row[i])), 6) for i, f in enumerate(factors)},
            "center": bool(np.all(row == 0)),
        })
    runs.sort(key=lambda r: r["run_order"])
    for r in runs:
        r["doe_run_id"] = f"R{r['run_order']:02d}"
    return {"design_type": design_type, "stage": stage, "matrix": matrix, "runs": runs,
            "terms": terms, "symbols": symbols, "info": info, "seed": seed}


def matrix_hash(matrix: np.ndarray) -> str:
    return hashlib.sha256(json.dumps(np.round(matrix, 9).tolist()).encode()).hexdigest()[:16]


def validation_context(design: Dict[str, Any], factors: List[Factor], *, rel_tol: float,
                       balance_fn=None, prior_evidence_approved: bool = False,
                       extreme_corner_risk: bool = False, source: str = "SYSTEM_GENERATED",
                       material_lots: Optional[int] = None, expected_days: Optional[int] = None,
                       equipment_count: int = 1) -> Dict[str, Any]:
    """DV·RB·FR006·AA008 규칙이 읽는 `plan` context. 판정은 하지 않고 사실만 만든다."""
    matrix = design["matrix"]
    symbols = design["symbols"]
    coded = {s: matrix[:, i] for i, s in enumerate(symbols)}
    X = model_matrix(design["terms"], coded)
    unique = {tuple(np.round(r, 9)) for r in matrix}
    n_center = int(np.all(matrix == 0, axis=1).sum())
    points = []
    for run in design["runs"]:
        in_bounds = all(f.low - 1e-9 <= run["actual"][f.factor_id] <= f.high + 1e-9 for f in factors)
        bal = balance_fn(run["actual"]) if balance_fn else None
        points.append({"in_bounds": in_bounds, "in_forbidden_combination": False,
                       "balance_component_value": bal, "in_domain": True})
    resolution = design["info"].get("resolution")
    return {
        "design_type": design["design_type"], "stage": design["stage"], "source": source,
        "n_runs": len(matrix), "n_center_points": n_center,
        "n_unique_runs": len(unique) - (1 if n_center else 0),
        "n_terms": len(design["terms"]), "resolution": resolution,
        "random_seed": design["seed"], "generator": f"{GENERATOR['name']} {GENERATOR['version']}",
        "block_definition": None, "has_mixture": False, "mixture_sum_ok": True,
        "expected_days": expected_days, "material_lots": material_lots,
        "equipment_count": equipment_count, "randomization": "COMPLETE", "randomization_reason": None,
        "augments_previous_stage": False, "new_block_center_points": 0,
        "locked_at": None, "locked_hash": None, "point_roles": [],
        "n_factors": len(factors), "n_continuous": len(factors), "n_categorical": 0,
        "has_hard_to_change": False, "has_forbidden_combinations": False,
        "design_points": points, "interactions_plausible": True,
        "prior_evidence_approved": prior_evidence_approved,
        "extreme_corner_risk": extreme_corner_risk,
        "axial_must_stay_in_range": True, "axial_points_safe": False,
        "screening_core_reusable": False,
        "_matrix_rank": matrix_rank(X, rel_tol),
    }
