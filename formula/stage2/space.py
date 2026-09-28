"""2단계 13–15 — Design Space(overlay) · 확인계획 잠금 · 확인배치 2×2. numpy·scipy만(그림은 matplotlib), LLM 없음.

13단계는 overlay 파이프라인(논문 Figure 2 형식)을 따른다. 규칙 숫자는 config/stage2_design_space.yaml.
- 영역 = 10단계 검증 게이트를 통과한 반응의 **평균 예측**이 모든 목표를 동시에 만족하는 곳(노랑, 논문과 같은 기준).
  게이트 불합격 반응("요인으로 설명되지 않음")은 영역 계산에서 빼고, 관측 범위와 목표를 문구로 보인다
  (평균 모형 95 % 예측구간이 목표에 걸치거나 목표 밖 run이 있으면 경고 — 승인은 막지 않는다).
- 실험 범위 = 설계점의 convex hull(coded). 밖은 외삽(해칭)이라 영역에 넣지 않는다.
- 요인이 3개면 효과(게이트 통과 모형의 |주효과 계수| 합)가 가장 작은 요인을 −1 · 0 · +1에 고정한 세 단면, 축마다 41점 격자.
- control space = 단면마다 노랑 ∩ 실험 범위 격자에 들어가는 가장 넓은 축 정렬 직사각형(가로·세로 3칸 이상), 가장 넓은 단면을 쓴다.
- 최적점 = control space 안(실험 범위 경계에서 0.1 coded 이상)에서 새 배치가 모든 목표를 만족할 확률이 가장 큰 점.
  이 확률(반응별 t 예측분포 통과확률의 곱, 독립 가정)은 **보조 표시**다 — 등고선으로만 보이고 승인 조건이 아니다.
- 승인 불가는 두 경우뿐: 평균 기준 영역 없음 · control space를 만들 수 없음.
- 14단계 확인점 = 최적점(SETPOINT) · control space 꼭짓점 중 확률 최저(BOUNDARY) · 최적점 ± 허용 변동 꼭짓점 중 최저(ROBUSTNESS).
  예측구간은 (확인점 3 × 게이트 통과 반응 수) Bonferroni 동시구간, 결과 전에 잠근다. 게이트 불합격 반응은 목표만 본다.
- 15단계 판정은 규격 통과 × 예측구간 포함의 2×2(게이트 불합격 반응은 규격 통과만).
"""
from __future__ import annotations

import io
import itertools
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from scipy import stats
from scipy.spatial import ConvexHull, QhullError

from formula.stage2 import doe as T

FAMILY_ALPHA = 0.05
ROBUST_DELTA = 0.2
OPS = ("LE", "GE", "BETWEEN")
HULL_TOL = 1e-9
FONTS = Path(__file__).resolve().parent / "fonts"


def _R() -> Dict[str, Any]:
    return T.rules()


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
def spec_text(s: Optional[Dict[str, Any]]) -> str:
    op, lo, hi = (s or {}).get("op"), (s or {}).get("lower"), (s or {}).get("upper")
    if op == "LE":
        return f"≤ {hi:g}"
    if op == "GE":
        return f"≥ {lo:g}"
    if op == "BETWEEN":
        return f"{lo:g}–{hi:g}"
    return "목표 없음"


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
    """게이트 통과 반응 중 목표가 있는 것만(영역 · 확인점 계산에 쓴다)."""
    by = {r["response"]: r for r in reg["responses"]}
    out = {}
    for s in specs:
        if s.get("op") not in OPS:
            continue
        r = by.get(s["response"])
        if not r or r.get("aliased") or r.get("status", "SELECTED") != "SELECTED":
            continue
        out[s["response"]] = {"terms": [tuple(t) for t in r["terms"]], "coef": np.array(r["coef"]), "cov": np.array(r["cov"]),
                              "mse": float(r["mse"]), "df": int(r["df_resid"]), "spec": s, "unit": r.get("unit"), "family": r.get("family")}
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


def _joint(models: Dict[str, Dict[str, Any]], X: np.ndarray):
    P = np.ones(len(X))
    ok = np.ones(len(X), bool)
    marg, means = {}, {}
    for name, m in models.items():
        pr = predict(m, X)
        pp = pass_prob(m["spec"], pr["mean"], pr["sd"], m["df"])
        marg[name], means[name] = pp, pr["mean"]
        P *= pp
        ok &= mean_pass(m["spec"], pr["mean"])
    return P, ok, marg, means


def _actual(fn, cod, xrow) -> Dict[str, float]:
    return {n: round(float(T.to_actual(np.array(xrow[i]), cod[i])), 4) for i, n in enumerate(fn)}


def unexplained_note(r: Dict[str, Any], spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """게이트 불합격 반응 — 평균 모형 95 % 예측구간과 목표 비교. 목표에 걸치거나 목표 밖 run이 있으면 경고(승인은 막지 않음)."""
    o = r.get("observed") or {}
    y = np.array(o.get("values") or [], float)
    unit = f" {r['unit']}" if r.get("unit") else ""
    txt = f"{r['response']}: 요인으로 설명되지 않음 — 관측 {o.get('min', float('nan')):g}–{o.get('max', float('nan')):g}{unit}, 목표 {spec_text(spec)}"
    out = {"response": r["response"], "level": "note", "text": txt, "pi95": None, "runs_out_of_target": 0, "gate_why": (r.get("gate") or {}).get("why")}
    if len(y) > 1 and spec and spec.get("op") in OPS:
        n, m, s = len(y), y.mean(), y.std(ddof=1)
        half = stats.t.ppf(1 - (1 - _R()["unexplained_check"]["level"]) / 2, n - 1) * s * math.sqrt(1 + 1 / n)
        lo, hi = m - half, m + half
        inside = bool(np.all(mean_pass(spec, np.array([lo, hi]))))
        runs_out = int((~mean_pass(spec, y)).sum())
        out.update({"pi95": [float(lo), float(hi)], "runs_out_of_target": runs_out})
        if not inside or runs_out:
            out["level"] = "warn"
            out["text"] = txt + f" · 주의: 예측구간 {lo:.3g}–{hi:.3g}이 목표에 걸침" + (f", {runs_out} run 목표 밖" if runs_out else "") + " — 영역 안에서도 불합격 가능"
    return out


def _max_rect(mask: np.ndarray, min_side: int):
    """0/1 격자에서 가로·세로 모두 min_side칸 이상인 가장 넓은 직사각형(histogram 방식). 반환 (area, (r0, r1, c0, c1)) — 없으면 (0, None)."""
    R, C = mask.shape
    h = np.zeros(C, int)
    best = (0, None)
    for r in range(R):
        h = np.where(mask[r], h + 1, 0)
        stack: List[tuple] = []
        for c in range(C + 1):
            cur = h[c] if c < C else 0
            start = c
            while stack and stack[-1][1] >= cur:
                s, hh = stack.pop()
                w = c - s
                if hh >= min_side and w >= min_side and hh * w > best[0]:
                    best = (int(hh * w), (r - hh + 1, r, s, c - 1))
                start = s
            stack.append((start, cur))
    return best


# ── 13 Design Space(overlay) ─────────────────────────────────────────────
def _compute(design: Dict[str, Any], reg: Dict[str, Any], specs: Sequence[Dict[str, Any]], fixed: Optional[int] = None) -> Dict[str, Any]:
    R = _R()
    fn, cod, x = _setup(design)
    k = len(fn)
    spec_by = {s["response"]: s for s in specs if s.get("op") in OPS}
    models = _models(reg, specs)
    passed = [r["response"] for r in reg["responses"] if r.get("status", "SELECTED") == "SELECTED" and not r.get("aliased")]
    notes = [unexplained_note(r, spec_by.get(r["response"])) for r in reg["responses"]
             if r.get("status") == "UNEXPLAINED" or r.get("aliased")]
    base = {"basis": "mean_prediction", "grid": R["design_space"]["grid_points_per_axis"],
            "factors": [{"name": n, "unit": design["factors"][i].get("unit"), "low": cod[i]["low"], "high": cod[i]["high"]} for i, n in enumerate(fn)],
            "responses": [{"response": n, "unit": m["unit"], "spec": spec_text(m["spec"]), "family": m["family"]} for n, m in models.items()],
            "gate_passed": passed, "unexplained": notes, "excluded": [n for n in passed if n not in models]}
    if not passed:
        return {**base, "status": "NO_GATE", "slices": [], "_slices": []}
    if not models:
        return {**base, "status": "NO_SPEC", "slices": [], "_slices": []}
    dom = Domain(x)
    n = R["design_space"]["grid_points_per_axis"]
    g = np.linspace(-1, 1, n)
    min_side = R["control_space"]["min_cells_per_side"]
    if k >= 3:
        tot = [sum(abs(float(m["coef"][m["terms"].index((i,))])) if (i,) in m["terms"] else 0.0 for m in models.values()) for i in range(k)]
        auto = int(np.argmin(tot))
        fx = fixed if fixed is not None and 0 <= int(fixed) < k else auto
        fx = int(fx)
        xy = [i for i in range(k) if i != fx][:2]
        levels = list(R["design_space"]["slice_levels_coded"])
    elif k == 2:
        fx, auto, xy, levels = None, None, [0, 1], [None]
    else:
        fx, auto, xy, levels = None, None, [0], [None]
    slices = []
    for lv in levels:
        if k >= 2:
            Xg, Yg = np.meshgrid(g, g)
            pts = np.zeros((Xg.size, k))
            pts[:, xy[0]], pts[:, xy[1]] = Xg.ravel(), Yg.ravel()
            if fx is not None:
                pts[:, fx] = lv
            shape = Xg.shape
        else:
            Xg, Yg = g[None, :], None
            pts = g[:, None]
            shape = (1, n)
        inD = dom.contains(pts).reshape(shape)
        edge = dom.edge_distance(pts).reshape(shape)
        P, ok, marg, means = _joint(models, pts)
        P, ok = P.reshape(shape), ok.reshape(shape)
        means = {m: v.reshape(shape) for m, v in means.items()}
        ds = ok & inD
        area, rect = _max_rect(ds, min_side if k >= 2 else 1)
        if k == 1 and rect is not None and (rect[3] - rect[2] + 1) < min_side:
            area, rect = 0, None
        fail = {}
        if inD.any():
            for m, mu in means.items():
                fail[m] = float((~mean_pass(models[m]["spec"], mu))[inD].mean())
        slices.append({"level": lv, "X": Xg, "Y": Yg, "in": inD, "edge": edge, "ds": ds, "P": P, "means": means, "rect": rect, "rect_area": int(area),
                       "ds_fraction": float(ds[inD].mean()) if inD.any() else 0.0,
                       "p_max": float(np.nanmax(np.where(inD, P, np.nan))) if inD.any() else 0.0, "fail": fail})
    best = max(slices, key=lambda s: (s["rect_area"], s["level"] == 0))
    control = optimum = None
    if best["rect"] is not None:
        r0, r1, c0, c1 = best["rect"]
        margin = R["optimum"]["edge_margin_coded"]
        Ps, Es = best["P"][r0:r1 + 1, c0:c1 + 1], best["edge"][r0:r1 + 1, c0:c1 + 1]
        sub = np.where(Es >= margin - 1e-9, Ps, -1.0)
        if not (sub >= 0).any():
            sub = Ps
        i, j = np.unravel_index(int(np.argmax(sub)), sub.shape)
        oi, oj = r0 + i, c0 + j
        oc = np.zeros(k)
        oc[xy[0]] = g[oj]
        if k >= 2:
            oc[xy[1]] = g[oi]
        if fx is not None:
            oc[fx] = best["level"]
        act = lambda v, i_: round(float(T.to_actual(np.array(v), cod[i_])), 4)   # noqa: E731
        control = {fn[xy[0]]: [act(g[c0], xy[0]), act(g[c1], xy[0])]}
        if k >= 2:
            control[fn[xy[1]]] = [act(g[r0], xy[1]), act(g[r1], xy[1])]
        if fx is not None:
            control[fn[fx]] = act(best["level"], fx)
        corners = []
        for rr, cc in ((r0, c0), (r0, c1), (r1, c0), (r1, c1)):
            cx = np.zeros(k)
            cx[xy[0]] = g[cc]
            if k >= 2:
                cx[xy[1]] = g[rr]
            if fx is not None:
                cx[fx] = best["level"]
            corners.append([round(float(v), 6) for v in cx])
        optimum = {"coded": [round(float(v), 6) for v in oc], "actual": _actual(fn, cod, oc), "joint": float(best["P"][oi, oj]),
                   "control_corners": corners, "edge": float(best["edge"][oi, oj])}
    any_region = any(s["ds"].any() for s in slices)
    status = "OK" if control else ("NO_CONTROL_SPACE" if any_region else "NO_MEAN_REGION")
    inall = np.concatenate([s["in"].ravel() for s in slices])
    Pall = np.concatenate([s["P"].ravel() for s in slices])
    okall = np.concatenate([s["ds"].ravel() for s in slices])
    fail_tot = {}
    for m in models:
        vals = np.concatenate([(~mean_pass(models[m]["spec"], s["means"][m]))[s["in"]] for s in slices]) if inall.any() else np.array([])
        fail_tot[m] = float(vals.mean()) if len(vals) else 0.0
    return {**base, "status": status, "domain_kind": dom.kind,
            "slice": None if fx is None else {"index": fx, "name": fn[fx], "unit": design["factors"][fx].get("unit"), "auto": fx == auto,
                                               "auto_index": auto, "levels_actual": [round(float(T.to_actual(np.array(l), cod[fx])), 4) for l in levels]},
            "axes": {"x": xy[0], "y": xy[1] if k >= 2 else None},
            "slices": [{"level_coded": s["level"], "level_actual": None if s["level"] is None else round(float(T.to_actual(np.array(s["level"]), cod[fx])), 4),
                        "ds_fraction": s["ds_fraction"], "p_max": s["p_max"], "rect_area": s["rect_area"], "fail": s["fail"],
                        "control": s is best and control is not None} for s in slices],
            "control_space": control, "optimum": optimum, "setpoint": optimum,
            "mean_ok_fraction": float(okall[inall].mean()) if inall.any() else 0.0,
            "fail_fraction": dict(sorted(fail_tot.items(), key=lambda kv: -kv[1])),
            "aux": {"max_joint": float(Pall[inall].max()) if inall.any() else 0.0,
                    "joint_ge_09_fraction": float((Pall[inall] >= 0.9).mean()) if inall.any() else 0.0,
                    "contour_levels": list(R["robustness_aux"]["contour_levels"]), "note": "보조 — 판정에 쓰지 않는다(반응 간 독립 가정)"},
            "_slices": slices, "_best": best, "_xy": xy, "_fx": fx, "_g": g, "_cod": cod, "_fn": fn, "_x": x, "_models": models}


def approval(reg_space: Dict[str, Any]) -> Dict[str, Any]:
    st = reg_space.get("status")
    if st == "NO_GATE":
        return {"approvable": False, "code": "SPACE_NO_GATE", "reason": "게이트 통과 반응 없음 — 영역을 그릴 회귀식이 없습니다"}
    if st == "NO_SPEC":
        return {"approvable": False, "code": "SPACE_NO_SPEC", "reason": "게이트 통과 반응의 목표를 하나 이상 적어야 영역을 계산합니다"}
    if st == "NO_MEAN_REGION":
        worst = ", ".join(f"{k} 미달 {100 * v:.0f}%" for k, v in list((reg_space.get("fail_fraction") or {}).items())[:3])
        return {"approvable": False, "code": "SPACE_NO_MEAN_REGION",
                "reason": f"평균 기준 영역 없음 — 게이트 통과 반응의 평균 예측이 목표를 동시에 만족하는 점이 실험 범위 안에 하나도 없습니다(막는 반응: {worst})"}
    if st == "NO_CONTROL_SPACE":
        return {"approvable": False, "code": "SPACE_NO_CONTROL",
                "reason": "control space를 만들 수 없음 — 영역은 있지만 3×3 격자 이상의 직사각형이 들어가지 않습니다. 영역이 좁아 운전 범위를 정할 수 없습니다"}
    return {"approvable": True, "code": None, "reason": "평균 기준 영역과 control space 확인"}


def region(design: Dict[str, Any], reg: Dict[str, Any], specs: Sequence[Dict[str, Any]], fixed: Optional[int] = None) -> Dict[str, Any]:
    c = _compute(design, reg, specs, fixed)
    out = {k: v for k, v in c.items() if not k.startswith("_")}
    out["approval"] = approval(out)
    return out


# ── Overlay plot(논문 Figure 2 형식) ───────────────────────────────────────
_FONT_READY = False
YELLOW, GRAY, EDGE, RED = "#f2e30c", "#dedede", "#6d6d6d", "#e0121b"


def _fonts():
    global _FONT_READY
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    if not _FONT_READY:
        for f in ("NanumGothic-Regular.ttf", "NanumGothic-Bold.ttf"):
            try:
                font_manager.fontManager.addfont(str(FONTS / f))
            except (OSError, RuntimeError):
                pass
        _FONT_READY = True


def _slack(means, models, shape):
    """반응별 (목표 여유 / 반응 범위)의 최솟값 — ≥ 0이면 모든 목표 만족(연속장이라 경계가 매끈하다)."""
    if not means:
        return np.full(shape, -1.0)
    out = np.full(shape, np.inf)
    for y, m in means.items():
        s = models[y]["spec"]
        span = float(np.nanmax(m) - np.nanmin(m)) or 1.0
        if s["op"] in ("GE", "BETWEEN"):
            out = np.minimum(out, (m - s["lower"]) / span)
        if s["op"] in ("LE", "BETWEEN"):
            out = np.minimum(out, (s["upper"] - m) / span)
    return out


def render(design: Dict[str, Any], reg: Dict[str, Any], specs: Sequence[Dict[str, Any]], fixed: Optional[int] = None,
           fmt: str = "svg", caption: bool = True, aux: bool = True, dpi: int = 200) -> bytes:
    """Overlay plot — 노랑(평균 예측이 모든 목표 만족) · 회색(미달) · 해칭(설계점 밖, 외삽) · 목표 한계선과 깃발 · 설계점 ·
    control space(빨간 점선) · 최적점(큰 빨간 점) · 보조 확률 등고선(회색 점선). caption=True면 그림 아래 문구(게이트 불합격 반응 · 승인 판정)."""
    _fonts()
    import textwrap

    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    c = _compute(design, reg, specs, fixed)
    appr = approval(c)
    style = {"font.family": ["DejaVu Serif", "NanumGothic"], "mathtext.fontset": "dejavuserif", "axes.unicode_minus": False, "font.size": 9,
             "axes.linewidth": 0.8, "xtick.direction": "out", "ytick.direction": "out", "xtick.major.size": 3, "ytick.major.size": 3,
             "savefig.facecolor": "white", "savefig.bbox": "tight", "hatch.color": "#b9b9b9", "hatch.linewidth": 0.6}
    slices = c.get("_slices") or []
    units = [f.get("unit") for f in design["factors"]]
    with plt.rc_context(style):
        if not slices:
            fig = plt.figure(figsize=(6.4, 1.0))
            fig.text(0.02, 0.5, textwrap.fill("승인 불가 — " + appr["reason"], 70), fontsize=9, color="#b3261e", va="center", family="NanumGothic")
            buf = io.BytesIO()
            fig.savefig(buf, format=fmt, dpi=dpi)
            plt.close(fig)
            return buf.getvalue()
        fn, cod, x = c["_fn"], c["_cod"], c["_x"]
        xy, fx, g, models, best = c["_xy"], c["_fx"], c["_g"], c["_models"], c["_best"]
        lab = lambda i: f"{'ABCDEFG'[i]}: {fn[i]}" + (f" ({units[i]})" if units[i] else "")   # noqa: E731
        n, k = len(slices), len(fn)
        cap_lines = []
        if caption:
            crit = ", ".join(f"{nm} {spec_text(m['spec'])}{(' ' + m['unit']) if m.get('unit') else ''}" for nm, m in models.items()) or "없음"
            at = "" if fx is None else f" at {'ABCDEFG'[fx]}: {fn[fx]}{(' (' + units[fx] + ')') if units[fx] else ''} = " + \
                ", ".join(f"({'abcdefgh'[i]}) {T.to_actual(np.array(s['level']), cod[fx]):g}" for i, s in enumerate(slices))
            cap = (f"Design space where {crit}{at}. Yellow = all criteria met (mean prediction); gray = not met; hatched = outside design points "
                   "(extrapolation). Red dashed square = control space; red circle = optimum. Dotted = probability a new batch meets all criteria.")
            width = int(40 * max(n, 2))
            cap_lines = [(textwrap.fill("Figure. " + cap, int(width * 1.35)), "#222", 7)]
            cap_lines += [(textwrap.fill(("주의 · " if nt["level"] == "warn" else "· ") + nt["text"], int(width * 0.95)),
                           "#9a5b00" if nt["level"] == "warn" else "#444", 7) for nt in c["unexplained"]]
            cap_lines += [(textwrap.fill(("승인 가능 — " if appr["approvable"] else "승인 불가 — ") + appr["reason"], int(width * 0.95)),
                           "#1f6f2c" if appr["approvable"] else "#b3261e", 7.5)]
        cap_in = sum(0.16 * (t.count("\n") + 1) + 0.08 for t, _, _ in cap_lines) + (0.35 if caption else 0.2)
        plot_h = 3.9
        fig, axs = plt.subplots(1, n, figsize=(3.55 * n if n > 1 else 4.4, plot_h + cap_in))
        fig.subplots_adjust(left=0.08 if n > 1 else 0.17, right=0.98, top=1 - 0.25 / (plot_h + cap_in),
                            bottom=(cap_in + 0.55) / (plot_h + cap_in), wspace=0.34)
        axs = np.atleast_1d(axs)
        cs_on = c["control_space"] is not None
        for i, (ax, s) in enumerate(zip(axs, slices)):
            if k == 1:
                xa = T.to_actual(g, cod[0])
                ok = s["ds"][0]
                ax.fill_between(xa, 0, 1, where=ok, color=YELLOW, step="mid")
                ax.fill_between(xa, 0, 1, where=~ok, color=GRAY, step="mid")
                ax.set_yticks([])
                ax.set_xlabel(lab(0), fontsize=8)
                if cs_on:
                    lo, hi = c["control_space"][fn[0]]
                    ax.add_patch(mpatches.Rectangle((lo, 0.05), hi - lo, 0.9, fill=False, ec=RED, ls=(0, (4, 2.5)), lw=1.3))
                    ax.scatter([c["optimum"]["actual"][fn[0]]], [0.5], s=46, c=RED, edgecolors="black", linewidths=0.8, zorder=12)
                ax.set_title("Overlay plot", fontsize=9, pad=4)
                continue
            Xa, Ya = T.to_actual(s["X"], cod[xy[0]]), T.to_actual(s["Y"], cod[xy[1]])
            inD = s["in"]
            ax.contourf(Xa, Ya, _slack(s["means"], models, Xa.shape), levels=[-1e9, 0, 1e9], colors=[GRAY, YELLOW])
            edge = s["edge"]
            if (edge < -1e-6).any():                                   # 면(±1) 위 단면은 안쪽이 0이라 음수만 밖
                ax.contourf(Xa, Ya, edge, levels=[-1e9, -1e-6], colors=["white"])
                ax.contourf(Xa, Ya, edge, levels=[-1e9, -1e-6], colors="none", hatches=["/////"])
                ax.contour(Xa, Ya, edge, levels=[-1e-6], colors="#9a9a9a", linewidths=0.6)
            for y, m in s["means"].items():
                sp = models[y]["spec"]
                M = np.where(inD, m, np.nan)
                lims = [sp["lower"] if sp["op"] in ("GE", "BETWEEN") else None, sp["upper"] if sp["op"] in ("LE", "BETWEEN") else None]
                for lim in lims:
                    if lim is not None and np.isfinite(M).any() and np.nanmin(M) < lim < np.nanmax(M):
                        cs = ax.contour(Xa, Ya, M, levels=[lim], colors=EDGE, linewidths=0.8)
                        segs = [q for q in cs.allsegs[0] if len(q) > 2] if cs.allsegs else []
                        if segs:
                            seg = max(segs, key=len)
                            px, py = seg[int(len(seg) * 0.45)]
                            ax.annotate(f"{y}: {lim:g}", (px, py), fontsize=6.5, ha="center", va="center", zorder=12,
                                        bbox=dict(boxstyle="square,pad=0.18", fc="white", ec="#555", lw=0.5))
            if aux and s["means"]:
                Pm = np.where(inD, s["P"], np.nan)
                if np.isfinite(Pm).any():
                    for lv in [v for v in c["aux"]["contour_levels"] if np.nanmin(Pm) < v < np.nanmax(Pm)]:
                        cc = ax.contour(Xa, Ya, Pm, levels=[lv], colors="#7a7a7a", linewidths=0.6, linestyles=[(0, (1.5, 1.5))])
                        ax.clabel(cc, fmt={lv: f"P {lv:g}"}, fontsize=5.5, inline_spacing=2)
            on = np.ones(len(x), bool) if fx is None else np.isclose(x[:, fx], s["level"])
            ax.scatter(T.to_actual(x[on, xy[0]], cod[xy[0]]), T.to_actual(x[on, xy[1]], cod[xy[1]]), s=9, c=RED, zorder=10, clip_on=False, linewidths=0)
            if cs_on and s is best:
                (xl, xh), (yl, yh) = c["control_space"][fn[xy[0]]], c["control_space"][fn[xy[1]]]
                ax.add_patch(mpatches.Rectangle((xl, yl), xh - xl, yh - yl, fill=False, ec=RED, ls=(0, (4, 2.5)), lw=1.3, zorder=11))
                o = c["optimum"]["actual"]
                ax.scatter([o[fn[xy[0]]]], [o[fn[xy[1]]]], s=46, c=RED, edgecolors="black", linewidths=0.8, zorder=12)
            ax.set_xlim(Xa.min(), Xa.max())
            ax.set_ylim(Ya.min(), Ya.max())
            ax.set_xlabel(lab(xy[0]), fontsize=8)
            ax.set_ylabel(lab(xy[1]), fontsize=8)
            ax.tick_params(labelsize=7)
            ax.set_title("Overlay plot", fontsize=9, pad=4)
            ax.set_box_aspect(1)
            if fx is not None:
                ax.text(0.5, -0.25, f"({'abcdefgh'[i]}) {fn[fx]} = {T.to_actual(np.array(s['level']), cod[fx]):g}{(' ' + units[fx]) if units[fx] else ''}",
                        transform=ax.transAxes, ha="center", va="top", fontsize=8.5)
        y0 = (cap_in - 0.05) / (plot_h + cap_in)
        for txt, col, fs in cap_lines:
            fig.text(0.07 if n > 1 else 0.04, y0, txt, fontsize=fs, ha="left", va="top", color=col, linespacing=1.35,
                     family=["DejaVu Serif", "NanumGothic"])
            y0 -= (0.16 * (txt.count("\n") + 1) + 0.08) / (plot_h + cap_in)
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=dpi)
        plt.close(fig)
        return buf.getvalue()


# ── 14 확인계획 ───────────────────────────────────────────────────────────
def plan(design: Dict[str, Any], reg: Dict[str, Any], specs: Sequence[Dict[str, Any]], reg_space: Dict[str, Any],
         delta: float = ROBUST_DELTA, reference: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fn, cod, x = _setup(design)
    k = len(fn)
    models = _models(reg, specs)
    sp = (reg_space or {}).get("optimum") or (reg_space or {}).get("setpoint")
    if not sp or not models:
        return {"points": [], "reason": "최적점이 없다(control space 없음)"}
    spec_by = {s["response"]: s for s in specs if s.get("op") in OPS}
    unexpl = [r for r in reg["responses"] if (r.get("status") == "UNEXPLAINED" or r.get("aliased")) and r["response"] in spec_by]
    m = 3 * len(models)
    level = 1 - FAMILY_ALPHA / m
    dom = Domain(x)

    def pack(role, xc, why, **extra):
        xc = np.asarray(xc, float)[None, :]
        Pj, _, mg, _ = _joint(models, xc)
        pred = {}
        for nm, md in models.items():
            pr = predict(md, xc)
            t = stats.t.ppf(1 - (1 - level) / 2, md["df"])
            lo, hi = float(pr["mean"][0] - t * pr["sd"][0]), float(pr["mean"][0] + t * pr["sd"][0])
            pred[nm] = {"mean": float(pr["mean"][0]), "pi_lower": max(0.0, lo), "pi_upper": hi, "pi_lower_raw": lo,
                        "pi_truncated": lo < 0, "pass_prob": float(mg[nm][0]), "spec": spec_text(md["spec"]),
                        "spec_obj": {kk: md["spec"].get(kk) for kk in ("op", "lower", "upper")}, "basis": "예측구간 + 목표"}
        for r in unexpl:
            o = r.get("observed") or {}
            nn, mu, sd = o.get("n", 0), o.get("mean"), o.get("sd", 0.0)
            half = float(stats.t.ppf(0.975, nn - 1) * sd * math.sqrt(1 + 1 / nn)) if nn > 1 else 0.0
            s_ = spec_by[r["response"]]
            pred[r["response"]] = {"mean": mu, "pi_lower": None if mu is None else mu - half, "pi_upper": None if mu is None else mu + half,
                                   "pi_lower_raw": None if mu is None else mu - half, "pass_prob": None, "spec": spec_text(s_),
                                   "spec_obj": {kk: s_.get(kk) for kk in ("op", "lower", "upper")}, "unexplained": True,
                                   "basis": "목표만(요인으로 설명되지 않음) — 구간은 관측 평균의 95 % 예측구간"}
        return {"role": role, "coded": [round(float(v), 4) for v in xc[0]], "settings": _actual(fn, cod, xc[0]),
                "joint": float(Pj[0]), "predicted": pred, "why": why, **extra}

    pts = [pack("SETPOINT", sp["coded"], "control space 안(실험 범위 경계에서 0.1 coded 이상)에서 새 배치 통과확률이 가장 큰 점 — 13단계 최적점")]
    corners = [np.array(cn, float) for cn in (sp.get("control_corners") or [])]
    if corners:
        Pc = [float(_joint(models, cn[None, :])[0][0]) for cn in corners]
        b = int(np.argmin(Pc))
        mg = _joint(models, corners[b][None, :])[2]
        worst = min(mg, key=lambda q: mg[q][0])
        pts.append(pack("BOUNDARY", corners[b], f"control space 꼭짓점 중 새 배치 통과확률이 가장 낮은 점 — 가장 빠듯한 반응은 {worst}", binding=worst))
    rob = []
    for signs in itertools.product((-1, 1), repeat=k):
        pt = np.array([sp["coded"][i] + s * delta for i, s in enumerate(signs)])
        if dom.contains(pt[None, :])[0]:
            rob.append((float(_joint(models, pt[None, :])[0][0]), pt))
    if rob:
        pts.append(pack("ROBUSTNESS", min(rob, key=lambda q: q[0])[1], f"최적점 ± {delta} coded(허용 변동) 꼭짓점 중 새 배치 통과확률이 가장 낮은 점", delta=delta))
    if reference and all(reference.get("settings", {}).get(nm) not in (None, "") for nm in fn):
        xc = [float((float(reference["settings"][nm]) - cod[i]["center"]) / cod[i]["half"]) for i, nm in enumerate(fn)]
        inside = bool(dom.contains(np.array(xc)[None, :])[0])
        pts.append(pack("REFERENCE", xc, "계획 전부터 있던 배치(예: 논문 최적 처방) — 참고로만 비교하고 승격·무효화 근거로 쓰지 않는다",
                        label=str(reference.get("label") or "참고 배치"), inside=inside))
    return {"points": pts, "pi_policy": {"method": "BONFERRONI", "family": "필수 확인점 3 × 게이트 통과 반응", "comparisons": m,
                                         "family_alpha": FAMILY_ALPHA, "per_comparison_level": level}, "delta": delta}


# ── 15 확인배치 2×2 ──────────────────────────────────────────────────────
def judge(vplan: Dict[str, Any], observations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """observations = [{role, values{response: 값}}]. 필수 3점의 (규격 통과 × 예측구간 안)을 모두 만족해야 VERIFIED.
    게이트 불합격 반응(요인으로 설명되지 않음)은 규격 통과만 본다."""
    obs = {o.get("role"): o.get("values") or {} for o in observations}
    rows, required_ok, complete = [], True, True
    for p in vplan.get("points", []):
        req = p["role"] != "REFERENCE"
        for nm, pr in p["predicted"].items():
            v = obs.get(p["role"], {}).get(nm)
            try:
                v = None if v in (None, "") else float(v)
            except (TypeError, ValueError):
                v = None
            if v is None:
                if req:
                    complete = False
                rows.append({"role": p["role"], "response": nm, "observed": None, "required": req})
                continue
            spec = pr.get("spec_obj") or _spec_from_text(pr["spec"])
            sp_ok = bool(mean_pass(spec, v)) if spec else None
            if pr.get("unexplained"):
                in_pi, cell = None, ("PASS_NA" if sp_ok else "FAIL_NA")
            else:
                in_pi = pr["pi_lower_raw"] <= v <= pr["pi_upper"]
                cell = ("PASS" if sp_ok else "FAIL") + ("_IN" if in_pi else "_OUT")
            if req and cell not in ("PASS_IN", "PASS_NA"):
                required_ok = False
            rows.append({"role": p["role"], "response": nm, "observed": v, "spec_pass": sp_ok, "in_pi": in_pi, "cell": cell, "required": req,
                         "pi": [pr["pi_lower"], pr["pi_upper"]], "mean": pr["mean"], "unexplained": bool(pr.get("unexplained"))})
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
