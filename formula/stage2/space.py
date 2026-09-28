"""2단계 13–15 — Design Space(공동확률) · 확인계획 잠금 · 확인배치 2×2. numpy·scipy만, LLM 없음.

영역은 평균 반응면이 아니라 **미래 배치의 예측분포**로 만든다(Peterson 2008):
- 반응별 예측분포 = t(df = 잔차 자유도), 척도 = √(SE²평균 + 잔차분산) — 10단계에서 고른 회귀식 그대로.
- 공동확률 = 반응별 규격 통과확률의 곱(반응 간 독립 가정 — 보고서에 적는다).
- 지지 영역 = 설계점의 convex hull(coded). 분모는 hull 안의 격자점(축마다 21점). hull 밖은 외삽이라 세지 않는다.
- 권장 설정점 = hull 경계에서 0.1 coded 이상 떨어진 격자점 중 공동확률 최대.
- 확인점 = SETPOINT · BOUNDARY(영역 안 공동확률 최저) · ROBUSTNESS(설정점 ± 허용 변동 꼭짓점 중 최저).
  예측구간은 (확인점 3 × 규격 반응 수) 비교를 한 family로 묶은 Bonferroni 동시구간이고, 결과 전에 잠근다.
- 판정은 규격 통과 × 예측구간 포함의 2×2. 영역이 비면 규격을 완화하지 않는다.
"""
from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from scipy import stats
from scipy.spatial import ConvexHull, QhullError

from formula.stage2 import doe as T

P_MIN = 0.90
GRID = 21
MIN_EDGE = 0.1
FAMILY_ALPHA = 0.05
ROBUST_DELTA = 0.2
OPS = ("LE", "GE", "BETWEEN")
HULL_TOL = 1e-9


class Domain:
    """설계점 convex hull. 소속과 경계까지의 거리(coded)를 같은 면 방정식으로 계산한다."""

    def __init__(self, x_coded: np.ndarray):
        pts = np.unique(np.round(x_coded, 9), axis=0)
        self.dim = pts.shape[1]
        self.lo, self.hi = pts.min(axis=0), pts.max(axis=0)
        self.kind = "hull"
        if self.dim == 1:
            self.equations = np.array([[1.0, -self.hi[0]], [-1.0, self.lo[0]]])
            return
        try:
            self.equations = ConvexHull(pts).equations      # n·x + d ≤ 0, |n| = 1
        except (QhullError, ValueError):
            # 설계점이 한 평면에 몰려 hull을 만들 수 없으면 요인 범위 상자로 둔다(보고서에 표시)
            self.kind = "box"
            eq = []
            for i in range(self.dim):
                e = np.zeros(self.dim + 1)
                e[i], e[-1] = 1.0, -self.hi[i]
                eq.append(e.copy())
                e[i], e[-1] = -1.0, self.lo[i]
                eq.append(e.copy())
            self.equations = np.array(eq)

    def contains(self, X: np.ndarray) -> np.ndarray:
        return np.all(X @ self.equations[:, :-1].T + self.equations[:, -1] <= HULL_TOL, axis=1)

    def edge_distance(self, X: np.ndarray) -> np.ndarray:
        return np.min(-(X @ self.equations[:, :-1].T + self.equations[:, -1]), axis=1)


# ── 규격 ──────────────────────────────────────────────────────────────────
def spec_text(s: Dict[str, Any]) -> str:
    op, lo, hi = s.get("op"), s.get("lower"), s.get("upper")
    if op == "LE":
        return f"≤ {hi:g}"
    if op == "GE":
        return f"≥ {lo:g}"
    if op == "BETWEEN":
        return f"{lo:g}–{hi:g}"
    return "규격 없음(영역 계산 제외)"


def pass_prob(s: Dict[str, Any], mean: np.ndarray, sd: np.ndarray, df: int) -> np.ndarray:
    cdf = lambda v: stats.t.cdf((v - mean) / sd, df)   # noqa: E731
    if s["op"] == "LE":
        return cdf(s["upper"])
    if s["op"] == "GE":
        return 1 - cdf(s["lower"])
    return cdf(s["upper"]) - cdf(s["lower"])


def mean_pass(s: Dict[str, Any], v):
    if s["op"] == "LE":
        return v <= s["upper"]
    if s["op"] == "GE":
        return v >= s["lower"]
    return (v >= s["lower"]) & (v <= s["upper"])


# ── 모형 ──────────────────────────────────────────────────────────────────
def _models(reg: Dict[str, Any], specs: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by = {r["response"]: r for r in reg["responses"]}
    out = {}
    for s in specs:
        if s.get("op") not in OPS:
            continue
        r = by.get(s["response"])
        if not r or r.get("aliased"):
            continue
        out[s["response"]] = {"terms": [tuple(t) for t in r["terms"]], "coef": np.array(r["coef"]), "cov": np.array(r["cov"]),
                              "mse": float(r["mse"]), "df": int(r["df_resid"]), "spec": s, "unit": r.get("unit")}
    return out


def predict(m: Dict[str, Any], x: np.ndarray) -> Dict[str, np.ndarray]:
    A = T.model_matrix(m["terms"], x)
    mean = A @ m["coef"]
    se = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", A, m["cov"], A), 0))
    return {"mean": mean, "se": se, "sd": np.sqrt(se ** 2 + m["mse"])}


def _setup(design: Dict[str, Any]):
    fn, X, rn, Y = T.table_arrays(design)
    cod = T.coding(X)
    x = T.to_coded(X, cod)
    return fn, cod, x


def _grid(dom: Domain, k: int, n: int = GRID) -> tuple:
    axes = [np.linspace(dom.lo[i], dom.hi[i], n) for i in range(k)]
    mesh = np.meshgrid(*axes, indexing="ij")
    return axes, np.column_stack([m.ravel() for m in mesh])


def _joint(models: Dict[str, Dict[str, Any]], X: np.ndarray):
    P = np.ones(len(X))
    ok = np.ones(len(X), bool)
    marg = {}
    for name, m in models.items():
        pr = predict(m, X)
        pp = pass_prob(m["spec"], pr["mean"], pr["sd"], m["df"])
        marg[name] = pp
        P *= pp
        ok &= mean_pass(m["spec"], pr["mean"])
    return P, ok, marg


def _actual(fn, cod, xrow) -> Dict[str, float]:
    return {n: round(float(T.to_actual(np.array(xrow[i]), cod[i])), 4) for i, n in enumerate(fn)}


# ── 13 Design Space ──────────────────────────────────────────────────────
def region(design: Dict[str, Any], reg: Dict[str, Any], specs: Sequence[Dict[str, Any]], p_min: float = P_MIN,
           n_grid: int = GRID, min_edge: float = MIN_EDGE) -> Dict[str, Any]:
    fn, cod, x = _setup(design)
    k = len(fn)
    models = _models(reg, specs)
    if not models:
        return {"status": "NO_SPEC", "responses": []}
    dom = Domain(x)
    axes, X = _grid(dom, k, n_grid)
    D = dom.contains(X)
    P, ok, marg = _joint(models, X)
    feas = D & (P >= p_min)
    edge = dom.edge_distance(X)
    cand = np.where(D & (edge >= min_edge - 1e-12))[0]
    setpoint = None
    if len(cand) and feas[cand].any():
        i = int(cand[np.argmax(P[cand])])
        setpoint = {"coded": [round(float(v), 6) for v in X[i]], "actual": _actual(fn, cod, X[i]), "joint": float(P[i]),
                    "marginals": {n: float(v[i]) for n, v in marg.items()}, "edge": float(edge[i])}
    failing = np.where(D & (P < p_min))[0]
    binding: Dict[str, int] = {}
    if len(failing):
        names = list(marg)
        worst = np.argmin(np.column_stack([marg[c][failing] for c in names]), axis=1)
        for w in worst:
            binding[names[w]] = binding.get(names[w], 0) + 1
    n_dom = int(D.sum())
    return {"status": "OK" if setpoint else "EMPTY", "p_min": p_min, "grid": n_grid, "min_edge": min_edge, "domain_kind": dom.kind,
            "grid_points_total": int(len(X)), "grid_points_in_domain": n_dom,
            "mean_ok_fraction": float(ok[D].mean()) if n_dom else 0.0, "feasible_fraction": float(feas[D].mean()) if n_dom else 0.0,
            "feasible_points": int(feas.sum()), "max_joint": float(P[D].max()) if n_dom else 0.0,
            "binding": dict(sorted(binding.items(), key=lambda kv: -kv[1])), "setpoint": setpoint,
            "responses": [{"response": n, "unit": m["unit"], "spec": spec_text(m["spec"]), "family_terms": len(m["terms"]), "df": m["df"]}
                          for n, m in models.items()],
            "excluded": [s["response"] for s in specs if s.get("op") not in OPS],
            "factors": [{"name": n, "unit": design["factors"][i].get("unit"), "low": cod[i]["low"], "high": cod[i]["high"]} for i, n in enumerate(fn)],
            "independence_note": "반응 간 상관은 무시하고 통과확률을 곱했다(독립 가정)."}


def slice_map(design: Dict[str, Any], reg: Dict[str, Any], specs: Sequence[Dict[str, Any]], *, fixed: Optional[int] = None,
              level: Optional[float] = None, p_min: float = P_MIN, n_grid: int = GRID) -> Dict[str, Any]:
    """화면용 단면 — 요인 3개면 하나를 고정한 2D(행 = 첫 요인, 열 = 둘째 요인), 2개면 전체, 1개면 선."""
    fn, cod, x = _setup(design)
    k = len(fn)
    models = _models(reg, specs)
    dom = Domain(x)
    axes = [np.linspace(dom.lo[i], dom.hi[i], n_grid) for i in range(k)]
    if k == 1:
        X = axes[0][:, None]
        P, ok, _ = _joint(models, X)
        D = dom.contains(X)
        return {"kind": "LINE", "x": [float(T.to_actual(np.array(v), cod[0])) for v in axes[0]], "P": np.round(P, 4).tolist(),
                "mean_ok": ok.tolist(), "in": D.tolist(), "factor": fn[0], "p_min": p_min}
    if k == 2:
        a, b, c = 0, 1, None
    else:
        c = 2 if fixed is None or not 0 <= fixed < 3 else fixed
        a, b = [i for i in range(3) if i != c]
    lv = 0.0
    if c is not None:
        lv = float(level) if level is not None else 0.0
        lv = float(axes[c][int(np.argmin(np.abs(axes[c] - lv)))])
    A, B = np.meshgrid(axes[a], axes[b], indexing="ij")
    X = np.zeros((A.size, k))
    X[:, a], X[:, b] = A.ravel(), B.ravel()
    if c is not None:
        X[:, c] = lv
    P, ok, _ = _joint(models, X)
    D = dom.contains(X)
    shape = (len(axes[a]), len(axes[b]))
    act = lambda i: [round(float(T.to_actual(np.array(v), cod[i])), 4) for v in axes[i]]  # noqa: E731
    return {"kind": "MAP", "rows": {"name": fn[a], "unit": design["factors"][a].get("unit"), "values": act(a)},
            "cols": {"name": fn[b], "unit": design["factors"][b].get("unit"), "values": act(b)},
            "fixed": None if c is None else {"index": c, "name": fn[c], "unit": design["factors"][c].get("unit"), "coded": lv,
                                             "actual": round(float(T.to_actual(np.array(lv), cod[c])), 4),
                                             "levels": [{"coded": round(float(v), 4), "actual": round(float(T.to_actual(np.array(v), cod[c])), 4)} for v in axes[c]]},
            "P": np.round(P.reshape(shape), 4).tolist(), "mean_ok": ok.reshape(shape).tolist(), "in": D.reshape(shape).tolist(), "p_min": p_min}


# ── 14 확인계획 ───────────────────────────────────────────────────────────
def plan(design: Dict[str, Any], reg: Dict[str, Any], specs: Sequence[Dict[str, Any]], reg_space: Dict[str, Any],
         delta: float = ROBUST_DELTA, reference: Optional[Dict[str, Any]] = None, p_min: float = P_MIN,
         min_edge: float = MIN_EDGE) -> Dict[str, Any]:
    fn, cod, x = _setup(design)
    k = len(fn)
    models = _models(reg, specs)
    sp = (reg_space or {}).get("setpoint")
    if not sp or not models:
        return {"points": [], "reason": "권장 설정점이 없다(영역 없음)"}
    m = 3 * len(models)
    level = 1 - FAMILY_ALPHA / m
    dom = Domain(x)
    axes, X = _grid(dom, k, reg_space.get("grid", GRID))
    D = dom.contains(X)
    P, _, marg = _joint(models, X)
    edge = dom.edge_distance(X)
    feas = D & (P >= p_min)

    def pack(role, xc, why, **extra):
        xc = np.asarray(xc, float)[None, :]
        Pj, _, mg = _joint(models, xc)
        pred = {}
        for n, md in models.items():
            pr = predict(md, xc)
            t = stats.t.ppf(1 - (1 - level) / 2, md["df"])
            lo, hi = float(pr["mean"][0] - t * pr["sd"][0]), float(pr["mean"][0] + t * pr["sd"][0])
            pred[n] = {"mean": float(pr["mean"][0]), "pi_lower": max(0.0, lo), "pi_upper": hi, "pi_lower_raw": lo,
                       "pi_truncated": lo < 0, "pass_prob": float(mg[n][0]), "spec": spec_text(md["spec"]),
                       "spec_obj": {k: md["spec"].get(k) for k in ("op", "lower", "upper")}}
        return {"role": role, "coded": [round(float(v), 4) for v in xc[0]], "settings": _actual(fn, cod, xc[0]),
                "joint": float(Pj[0]), "predicted": pred, "why": why, **extra}

    pts = [pack("SETPOINT", sp["coded"], f"공동확률 최대 · 지지 영역 경계에서 {min_edge} coded 이상 떨어진 격자점")]
    idx = np.where(feas & (edge >= min_edge - 1e-12))[0]
    if len(idx):
        b = int(idx[np.argmin(P[idx])])
        worst = min(marg, key=lambda c: marg[c][b])
        pts.append(pack("BOUNDARY", X[b], f"영역 안에서 공동확률이 가장 낮은 점 — 경계를 정하는 반응은 {worst}", binding=worst))
    corners = []
    for signs in itertools.product((-1, 1), repeat=k):
        pt = np.array([sp["coded"][i] + s * delta for i, s in enumerate(signs)])
        if dom.contains(pt[None, :])[0]:
            corners.append((float(_joint(models, pt[None, :])[0][0]), pt))
    if corners:
        pts.append(pack("ROBUSTNESS", min(corners, key=lambda c: c[0])[1],
                        f"설정점 ± {delta} coded(허용 변동) 꼭짓점 중 공동확률이 가장 낮은 점", delta=delta))
    if reference and all(reference.get("settings", {}).get(n) not in (None, "") for n in fn):
        xc = [float((float(reference["settings"][n]) - cod[i]["center"]) / cod[i]["half"]) for i, n in enumerate(fn)]
        inside = bool(dom.contains(np.array(xc)[None, :])[0])
        pts.append(pack("REFERENCE", xc, "계획 전부터 있던 배치(예: 논문 최적 처방) — 참고로만 비교하고 승격·무효화 근거로 쓰지 않는다",
                        label=str(reference.get("label") or "참고 배치"), inside=inside))
    return {"points": pts, "pi_policy": {"method": "BONFERRONI", "family": "필수 확인점 3 × 규격 반응", "comparisons": m,
                                         "family_alpha": FAMILY_ALPHA, "per_comparison_level": level}, "delta": delta}


# ── 15 확인배치 2×2 ──────────────────────────────────────────────────────
def judge(vplan: Dict[str, Any], observations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """observations = [{role, values{response: 값}}]. 필수 3점의 (규격 통과 × 예측구간 안)을 모두 만족해야 VERIFIED."""
    obs = {o.get("role"): o.get("values") or {} for o in observations}
    rows, required_ok, complete = [], True, True
    for p in vplan.get("points", []):
        req = p["role"] != "REFERENCE"
        for n, pr in p["predicted"].items():
            v = obs.get(p["role"], {}).get(n)
            try:
                v = None if v in (None, "") else float(v)
            except (TypeError, ValueError):
                v = None
            if v is None:
                if req:
                    complete = False
                rows.append({"role": p["role"], "response": n, "observed": None, "required": req})
                continue
            spec = pr.get("spec_obj") or _spec_from_text(pr["spec"])
            sp_ok = bool(mean_pass(spec, v)) if spec else None
            in_pi = pr["pi_lower_raw"] <= v <= pr["pi_upper"]
            cell = ("PASS" if sp_ok else "FAIL") + ("_IN" if in_pi else "_OUT")
            if req and cell != "PASS_IN":
                required_ok = False
            rows.append({"role": p["role"], "response": n, "observed": v, "spec_pass": sp_ok, "in_pi": in_pi, "cell": cell, "required": req,
                         "pi": [pr["pi_lower"], pr["pi_upper"]], "mean": pr["mean"]})
    if not complete:
        verdict = "INCOMPLETE"
    elif required_ok:
        verdict = "VERIFIED"
    else:
        verdict = "INVALIDATED"
    cells = [r["cell"] for r in rows if r.get("required") and r.get("cell")]
    advice = []
    if "PASS_OUT" in cells:
        advice.append("규격은 통과했지만 예측구간 밖 — 모형이 실제와 다르다: 10단계(회귀식)나 9단계(실험 설계)를 다시 열어 모형을 보강한다.")
    if any(c.startswith("FAIL") for c in cells):
        advice.append("규격 실패 — 영역을 무효화하고 원인을 진단한다: 위험평가(4·6단계)를 다시 열어 빠진 변수·기전을 검토한다.")
    return {"verdict": verdict, "rows": rows, "advice": advice}


def _spec_from_text(t: str) -> Optional[Dict[str, Any]]:
    t = (t or "").strip()
    try:
        if t.startswith("≤"):
            return {"op": "LE", "upper": float(t[1:])}
        if t.startswith("≥"):
            return {"op": "GE", "lower": float(t[1:])}
        if "–" in t:
            lo, hi = t.split("–")
            return {"op": "BETWEEN", "lower": float(lo), "upper": float(hi)}
    except ValueError:
        return None
    return None
