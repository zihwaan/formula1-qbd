"""2단계 DoE toolkit — 실험 설계 표(9) → 회귀식(10) → 반응 곡면(11) → ANOVA(12). numpy·scipy만, LLM 없음.

- 요인은 표에 적힌 최솟값·최댓값으로 coded(−1…+1)로 바꾼다: x = (X − 중앙) / 반폭.
- 10단계 = Automatic Hierarchical Model Selector → Model Validation Gate(overlay 파이프라인, 규칙 숫자는 config/stage2_design_space.yaml).
  후보 Mean · Linear · 2FI · Pure quadratic · Quadratic · Reduced quadratic(Quadratic에서 계층성을 지키며 p > 0.05 항을 하나씩 뺀 모형)을
  AICc로 줄 세우고(최소 + 2 이내면 항 수가 적은 쪽 먼저) 순서대로 게이트 4조건 — 모형 p < 0.05 · 적합결여 p ≥ 0.05 · 조정 R² − 예측 R² ≤ 0.2 ·
  예측 R² > 0 — 을 검사해 처음 통과한 모형을 제안한다. 평균 모형까지 내려가면 "요인으로 설명되지 않음"(영역·ANOVA에 쓰지 않는다 —
  곡면은 게이트 통과 반응이 하나라도 있으면 참고로 그린다).
  연구자가 모형을 바꿀 수 있고, 고른 모형이 게이트를 못 넘으면 그 반응도 "요인으로 설명되지 않음"이다.
- ANOVA는 각 항의 부분 제곱합(Type III: 그 항을 뺀 모형과의 잔차 제곱합 차이), 잔차 = 적합결여 + 순수오차(같은 설정의 반복 run).
- 실제 단위 식은 coded 식을 전개해서 만든다(반올림은 표시할 때만).
"""
from __future__ import annotations

import itertools
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import yaml
from scipy import stats

FAMILIES = ("Mean", "Linear", "2FI", "Pure quadratic", "Quadratic", "Reduced quadratic")
ALPHA = 0.05
RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "stage2_design_space.yaml"


@lru_cache(maxsize=1)
def rules() -> Dict[str, Any]:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


# ── 설계 표 ────────────────────────────────────────────────────────────────
def table_arrays(design: Dict[str, Any]) -> Tuple[List[str], np.ndarray, List[str], np.ndarray]:
    """design = {factors[{name, unit}], responses[{name, unit}], rows[{std, run, x[], y[]}]} → 요인 이름, X(n×k), 반응 이름, Y(n×m, 결측 NaN)."""
    fn = [f["name"] for f in design["factors"]]
    rn = [r["name"] for r in design["responses"]]
    X = np.array([[float(v) for v in row["x"]] for row in design["rows"]], dtype=float)
    Y = np.array([[np.nan if v in (None, "") else float(v) for v in row["y"]] for row in design["rows"]], dtype=float)
    return fn, X, rn, Y


def coding(X: np.ndarray) -> List[Dict[str, float]]:
    out = []
    for j in range(X.shape[1]):
        lo, hi = float(np.min(X[:, j])), float(np.max(X[:, j]))
        out.append({"low": lo, "high": hi, "center": (lo + hi) / 2, "half": (hi - lo) / 2 or 1.0})
    return out


def to_coded(X: np.ndarray, cod: List[Dict[str, float]]) -> np.ndarray:
    return np.column_stack([(X[:, j] - c["center"]) / c["half"] for j, c in enumerate(cod)])


def to_actual(x: np.ndarray, c: Dict[str, float]) -> np.ndarray:
    return c["center"] + x * c["half"]


# ── 항 ────────────────────────────────────────────────────────────────────
def terms_of(family: str, k: int) -> List[Tuple[int, ...]]:
    """항 = 요인 인덱스 튜플. () 절편, (0,) X1, (0,1) X1X2, (0,0) X1². Reduced quadratic은 반응마다 달라 select()가 정한다."""
    t: List[Tuple[int, ...]] = [()]
    if family in ("Linear", "2FI", "Pure quadratic", "Quadratic", "Reduced quadratic"):
        t += [(i,) for i in range(k)]
    if family in ("2FI", "Quadratic", "Reduced quadratic"):
        t += [(i, j) for i, j in itertools.combinations(range(k), 2)]
    if family in ("Pure quadratic", "Quadratic", "Reduced quadratic"):
        t += [(i, i) for i in range(k)]
    return t


def families(k: int) -> List[str]:
    return [f for f in FAMILIES if not (f == "2FI" and k < 2)]


def column(term: Tuple[int, ...], x: np.ndarray) -> np.ndarray:
    col = np.ones(x.shape[0])
    for i in term:
        col = col * x[:, i]
    return col


def model_matrix(terms: Sequence[Tuple[int, ...]], x: np.ndarray) -> np.ndarray:
    return np.column_stack([column(t, x) for t in terms])


def term_label(t: Tuple[int, ...], names: Optional[Sequence[str]] = None, style: str = "X") -> str:
    """style 'X' → X1, X1X2, X1² · style 'A' → A, AB, A² (ANOVA 표)."""
    if not t:
        return "Intercept"
    sym = (lambda i: f"X{i + 1}") if style == "X" else (lambda i: "ABCDEFG"[i])
    if len(t) == 2 and t[0] == t[1]:
        return f"{sym(t[0])}²"
    lab = "".join(sym(i) for i in t)
    if style == "A" and len(t) == 1 and names:
        return f"{lab}-{names[t[0]]}"
    return lab


# ── 적합 ──────────────────────────────────────────────────────────────────
def pure_error(x: np.ndarray, y: np.ndarray) -> Tuple[float, int]:
    groups: Dict[tuple, List[float]] = {}
    for row, v in zip(np.round(x, 9), y):
        groups.setdefault(tuple(row), []).append(v)
    ss = sum(float(np.sum((np.array(g) - np.mean(g)) ** 2)) for g in groups.values() if len(g) > 1)
    df = sum(len(g) - 1 for g in groups.values())
    return ss, df


def fit(terms: Sequence[Tuple[int, ...]], x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    A = model_matrix(terms, x)
    n, p = A.shape
    rank = int(np.linalg.matrix_rank(A))
    out: Dict[str, Any] = {"terms": [list(t) for t in terms], "n": n, "p": p, "rank": rank, "aliased": rank < p or n <= p}
    if out["aliased"]:
        return out
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    yhat = A @ beta
    resid = y - yhat
    sse = float(resid @ resid)
    sst = float(np.sum((y - y.mean()) ** 2))
    df_res = n - p
    H = A @ np.linalg.pinv(A.T @ A) @ A.T
    h = np.clip(np.diag(H), 0, 1 - 1e-12)
    press = float(np.sum((resid / (1 - h)) ** 2))
    mse = sse / df_res
    r2 = 1 - sse / sst if sst > 0 else 1.0
    adj = 1 - (sse / df_res) / (sst / (n - 1)) if sst > 0 else 1.0
    pred = 1 - press / sst if sst > 0 else 1.0
    out.update({"coef": [float(b) for b in beta], "sse": sse, "sst": sst, "df_resid": df_res, "mse": mse, "r2": r2,
                "adj_r2": adj, "pred_r2": pred, "press": press, "std_dev": float(np.sqrt(mse)), "mean": float(y.mean()),
                "cv_pct": float(100 * np.sqrt(mse) / abs(y.mean())) if y.mean() else None,
                "cov": (mse * np.linalg.pinv(A.T @ A)).tolist()})
    ss_pe, df_pe = pure_error(x, y)
    df_lof = df_res - df_pe
    if df_pe > 0 and df_lof > 0 and ss_pe > 0:
        ss_lof = sse - ss_pe
        f = (ss_lof / df_lof) / (ss_pe / df_pe)
        out["lof"] = {"ss": ss_lof, "df": df_lof, "ms": ss_lof / df_lof, "f": f, "p": float(1 - stats.f.cdf(f, df_lof, df_pe)),
                      "ss_pe": ss_pe, "df_pe": df_pe, "ms_pe": ss_pe / df_pe}
    else:
        out["lof"] = {"ss": None, "df": df_lof, "ss_pe": ss_pe, "df_pe": df_pe, "p": None, "note": "반복 run이 없거나 자유도가 없어 계산 불가"}
    return out


def fit_summary(x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    """적합 요약 — 모형 차수별 순차 F·적합결여·R² 표와 제안 모형."""
    k = x.shape[1]
    rows, prev = [], None
    fits = {}
    for fam in families(k):
        f = fit(terms_of(fam, k), x, y)
        fits[fam] = f
        row = {"model": fam, "p": f["p"], "aliased": f["aliased"]}
        if not f["aliased"]:
            row.update({k2: f[k2] for k2 in ("r2", "adj_r2", "pred_r2", "press", "std_dev")})
            row["lof_p"] = f["lof"].get("p")
            if prev is not None and not prev["aliased"] and fam != "Mean":
                dfn = f["p"] - prev["p"]
                ssr = prev["sse"] - f["sse"]
                F = (ssr / dfn) / f["mse"] if f["mse"] > 0 else float("inf")
                row.update({"seq_ss": ssr, "seq_df": dfn, "seq_f": F, "seq_p": float(1 - stats.f.cdf(F, dfn, f["df_resid"]))})
        rows.append(row)
        prev = f
    ok = [r for r in rows if r["model"] != "Mean" and not r["aliased"] and r.get("seq_p") is not None and r["seq_p"] < ALPHA]
    if ok:
        pick = ok[-1]
        why = f"순차 F 검정이 유의한(p = {pick['seq_p']:.4f} < {ALPHA}) 가장 높은 차수"
    else:
        cand = [r for r in rows if r["model"] != "Mean" and not r["aliased"]]
        pick = max(cand, key=lambda r: r["pred_r2"]) if cand else rows[0]
        why = "순차 F 검정에서 유의한 차수가 없음 — 예측 R²가 가장 큰 모형(해석 주의)" if cand else "적합 가능한 모형이 없음"
    for r in rows:
        r["suggested"] = r is pick
    return {"rows": rows, "suggested": pick["model"], "reason": why}


# ── 10단계: 모형 자동 선택 → 검증 게이트 ──────────────────────────────────
def _zname(t: Tuple[int, ...]) -> str:
    """항 이름(overlay 파이프라인 표기) — 같은 p값일 때 제거 순서를 똑같이 정하려고 쓴다."""
    s = "abcdefg"
    if len(t) == 2 and t[0] == t[1]:
        return s[t[0]] + "2"
    return ":".join(s[i] for i in t)


def _parents(t: Tuple[int, ...]) -> List[Tuple[int, ...]]:
    if len(t) == 2 and t[0] == t[1]:
        return [(t[0],)]
    return [(i,) for i in t] if len(t) == 2 else []


def _term_p(terms: Sequence[Tuple[int, ...]], x: np.ndarray, y: np.ndarray) -> Dict[Tuple[int, ...], float]:
    f = fit(terms, x, y)
    if f["aliased"] or f["df_resid"] <= 0:
        return {}
    se = np.sqrt(np.maximum(np.diag(np.array(f["cov"])), 0))
    out = {}
    for t, b, e in zip(terms, f["coef"], se):
        if t:
            out[t] = float(2 * stats.t.sf(abs(b / e), f["df_resid"])) if e > 0 else 0.0
    return out


def reduce_hierarchical(x: np.ndarray, y: np.ndarray) -> List[Tuple[int, ...]]:
    """Quadratic에서 시작해 '다른 남은 항의 부모가 아닌 항' 중 p > alpha인 항을 p가 큰 것부터 하나씩 뺀다(모두 p ≤ alpha가 될 때까지)."""
    alpha = rules()["selector"]["reduction"]["alpha_remove"]
    terms = [t for t in terms_of("Quadratic", x.shape[1]) if t]
    while terms:
        p = _term_p([()] + terms, x, y)
        if not p:
            break
        removable = [t for t in terms if not any(t in _parents(u) for u in terms if u != t)]
        cand = [(p[t], _zname(t), t) for t in removable if p[t] > alpha]
        if not cand:
            break
        drop = max(cand)[2]
        terms = [t for t in terms if t != drop]
    return [()] + terms


def _aicc(f: Dict[str, Any]) -> float:
    n, p = f["n"], f["p"]
    llf = -n / 2 * (math.log(2 * math.pi) + math.log(f["sse"] / n) + 1) if f["sse"] > 0 else math.inf
    aic = -2 * llf + 2 * p
    kk = p + 1
    return aic + 2 * kk * (kk + 1) / (n - kk - 1) if n - kk - 1 > 0 else math.inf


def gate(row: Dict[str, Any]) -> Dict[str, Any]:
    """검증 게이트 4조건. 적합결여는 계산할 수 없으면 건너뛰고 표시한다."""
    g = rules()["gate"]
    why, checks = [], []
    mp, lp, adj, pred = row.get("model_p"), row.get("lof_p"), row.get("adj_r2"), row.get("pred_r2")
    ok = mp is not None and mp < g["model_p_max"]
    checks.append({"check": "모형 p < 0.05", "value": mp, "pass": ok})
    if not ok:
        why.append(f"모형 p {mp:.3f} ≥ {g['model_p_max']}" if mp is not None else "모형 p 없음")
    if lp is None:
        checks.append({"check": "적합결여 p ≥ 0.05", "value": None, "pass": None})
    else:
        ok = lp >= g["lack_of_fit_p_min"]
        checks.append({"check": "적합결여 p ≥ 0.05", "value": lp, "pass": ok})
        if not ok:
            why.append(f"적합결여 p {lp:.3f} < {g['lack_of_fit_p_min']}")
    gap = None if adj is None or pred is None else adj - pred
    ok = gap is not None and gap <= g["adj_minus_pred_r2_max"]
    checks.append({"check": "조정 R² − 예측 R² ≤ 0.2", "value": gap, "pass": ok})
    if not ok:
        why.append(f"조정 R² − 예측 R² = {gap:.2f} > {g['adj_minus_pred_r2_max']}" if gap is not None else "예측 R² 없음")
    ok = pred is not None and pred > g["pred_r2_min"]
    checks.append({"check": "예측 R² > 0", "value": pred, "pass": ok})
    if not ok:
        why.append(f"예측 R² {pred:.2f} ≤ {g['pred_r2_min']}" if pred is not None else "예측 R² 없음")
    return {"passed": not why, "why": why, "checks": checks}


def select(x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    """Automatic Hierarchical Model Selector → Model Validation Gate. rows = 순위대로 후보(게이트 결과 포함)."""
    k = x.shape[1]
    cands: Dict[str, List[Tuple[int, ...]]] = {f: terms_of(f, k) for f in families(k) if f != "Reduced quadratic"}
    cands["Reduced quadratic"] = reduce_hierarchical(x, y)
    rows, seen = [], set()
    for fam, terms in cands.items():
        key = tuple(sorted(terms))
        if key in seen:                      # 같은 항 구성(예: 축소 결과 = Linear)은 앞의 것만
            continue
        seen.add(key)
        f = fit(terms, x, y)
        if f["aliased"]:
            continue
        nt = len(terms) - 1
        row = {"model": fam, "terms": [list(t) for t in terms], "term_names": [_zname(t) for t in terms if t], "n_terms": nt,
               "r2": f["r2"], "adj_r2": f["adj_r2"] if nt else 0.0, "pred_r2": f["pred_r2"] if nt else None, "press": f["press"] if nt else None,
               "model_p": None, "lof_p": f["lof"].get("p"), "aicc": _aicc(f), "std_dev": f["std_dev"]}
        if nt:
            F = ((f["sst"] - f["sse"]) / nt) / f["mse"] if f["mse"] > 0 else math.inf
            row["model_p"] = float(stats.f.sf(F, nt, f["df_resid"]))
        rows.append(row)
    best = min(r["aicc"] for r in rows)
    delta = rules()["selector"]["ranking"]["parsimony_delta"]
    for r in rows:
        r["within_delta"] = bool(r["aicc"] <= best + delta)
    rows.sort(key=lambda r: (not r["within_delta"], r["n_terms"], r["aicc"]))
    log, pick = [], None
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        r["gate"] = gate(r) if r["model"] != "Mean" else {"passed": False, "why": ["평균 모형(요인 없음)"], "checks": []}
    for r in rows:
        if r["model"] == "Mean":
            log.append("평균 모형 도달 → 요인으로 설명되지 않음")
            pick = r
            break
        if r["gate"]["passed"]:
            log.append(f"{r['model']} 통과 → 채택")
            pick = r
            break
        log.append(f"{r['model']} 불합격: " + "; ".join(r["gate"]["why"]))
    pick = pick or next(r for r in rows if r["model"] == "Mean")
    status = "UNEXPLAINED" if pick["model"] == "Mean" else "SELECTED"
    for r in rows:
        r["suggested"] = r is pick
    reason = ("AICc 순위대로 검증 게이트(모형 p < 0.05 · 적합결여 p ≥ 0.05 · 조정 R² − 예측 R² ≤ 0.2 · 예측 R² > 0)를 처음 통과한 모형"
              if status == "SELECTED" else "게이트를 통과한 모형 없이 평균 모형까지 내려감 — 요인으로 설명되지 않음")
    return {"rows": rows, "suggested": pick["model"], "status": status, "log": log, "reason": reason}


# ── ANOVA ─────────────────────────────────────────────────────────────────
def anova(family: str, x: np.ndarray, y: np.ndarray, names: Sequence[str], terms: Optional[Sequence[Sequence[int]]] = None) -> Dict[str, Any]:
    k = x.shape[1]
    terms = [tuple(t) for t in terms] if terms else terms_of(family, k)
    full = fit(terms, x, y)
    if full["aliased"]:
        return {"family": family, "aliased": True}
    msr = full["mse"]
    rows = []
    model_ss = full["sst"] - full["sse"]
    model_df = full["p"] - 1
    if model_df > 0:
        F = (model_ss / model_df) / msr
        rows.append({"source": "Model", "ss": model_ss, "df": model_df, "ms": model_ss / model_df, "f": F,
                     "p": float(1 - stats.f.cdf(F, model_df, full["df_resid"])), "level": 0})
    for t in terms[1:]:
        red = [u for u in terms if u != t]
        r = fit(red, x, y)
        ss = r["sse"] - full["sse"] if not r["aliased"] else float("nan")
        if ss < 0 and abs(ss) < 1e-9 * max(full["sst"], 1e-12):
            ss = 0.0                                   # 부동소수 잡음(−0) — 직교 설계에서 0인 항
        F = ss / msr
        rows.append({"source": term_label(t, names, "A"), "ss": ss, "df": 1, "ms": ss, "f": F,
                     "p": float(1 - stats.f.cdf(F, 1, full["df_resid"])), "level": 1, "term": list(t)})
    rows.append({"source": "Residual", "ss": full["sse"], "df": full["df_resid"], "ms": full["mse"], "level": 0})
    lof = full["lof"]
    if lof.get("p") is not None:
        rows.append({"source": "Lack of fit", "ss": lof["ss"], "df": lof["df"], "ms": lof["ms"], "f": lof["f"], "p": lof["p"], "level": 1})
        rows.append({"source": "Pure error", "ss": lof["ss_pe"], "df": lof["df_pe"], "ms": lof["ms_pe"], "level": 1})
    rows.append({"source": "Cor total", "ss": full["sst"], "df": full["n"] - 1, "level": 0})
    return {"family": family, "rows": rows, "r2": full["r2"], "adj_r2": full["adj_r2"], "pred_r2": full["pred_r2"],
            "std_dev": full["std_dev"], "mean": full["mean"], "cv_pct": full["cv_pct"], "press": full["press"]}


# ── 식 ────────────────────────────────────────────────────────────────────
def actual_poly(terms: Sequence[Tuple[int, ...]], coef: Sequence[float], cod: List[Dict[str, float]]) -> Dict[Tuple[int, ...], float]:
    """coded 식 → 실제 단위 다항식. x_i = (X_i − c_i)/h_i 를 전개한다. 키 = 정렬된 요인 인덱스 튜플(단항식)."""
    poly: Dict[Tuple[int, ...], float] = {}
    for t, b in zip(terms, coef):
        parts = [{(): 1.0}]
        for i in t:
            c, h = cod[i]["center"], cod[i]["half"]
            lin = {(i,): 1 / h, (): -c / h}
            nxt: Dict[Tuple[int, ...], float] = {}
            for m1, v1 in parts[-1].items():
                for m2, v2 in lin.items():
                    m = tuple(sorted(m1 + m2))
                    nxt[m] = nxt.get(m, 0.0) + v1 * v2
            parts.append(nxt)
        for m, v in parts[-1].items():
            poly[m] = poly.get(m, 0.0) + b * v
    return poly


def _num(v: float, digits: int = 4) -> str:
    if v == 0:
        return "0"
    if abs(v) < 10 ** (-digits) or abs(v) >= 1e6:
        return f"{v:.3g}".replace("e-0", "×10⁻").replace("e-", "×10⁻").replace("e+0", "×10^").replace("e+", "×10^")
    return f"{v:.{digits}g}" if abs(v) < 1 else f"{v:.{max(2, digits - len(str(int(abs(v)))))}f}"


def equation(y: str, terms: Sequence[Tuple[int, ...]], coef: Sequence[float], sym: str = "X", digits: int = 4) -> str:
    parts = []
    scale = max([abs(float(b)) for b in coef] + [1e-300])
    for t, b in zip(terms, coef):
        b = 0.0 if abs(float(b)) < 1e-10 * scale else float(b)      # 직교 설계에서 0인 계수의 부동소수 잡음(−1.7e−17)
        lab = "" if not t else ("".join(f"{sym}{i + 1}" for i in t) if not (len(t) == 2 and t[0] == t[1]) else f"{sym}{t[0] + 1}²")
        if not parts:
            parts.append(f"{_num(b, digits)}{lab}")
        else:
            parts.append(f"{'−' if b < 0 else '+'} {_num(abs(b), digits)}{lab}")
    return f"{y} = " + " ".join(parts)


def observed(y: np.ndarray) -> Dict[str, Any]:
    return {"n": int(len(y)), "min": float(np.min(y)), "max": float(np.max(y)), "mean": float(np.mean(y)),
            "sd": float(np.std(y, ddof=1)) if len(y) > 1 else 0.0, "values": [float(v) for v in y]}


def regression(design: Dict[str, Any], chosen: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """반응별 모형 선택·게이트(select) + 선택 모형의 coded·actual 식(Table 10). status = SELECTED(게이트 통과) | UNEXPLAINED."""
    fn, X, rn, Y = table_arrays(design)
    cod = coding(X)
    x = to_coded(X, cod)
    out = []
    for j, name in enumerate(rn):
        ok = ~np.isnan(Y[:, j])
        y = Y[ok, j]
        xs = x[ok]
        summ = select(xs, y)
        rows = {r["model"]: r for r in summ["rows"]}
        fam = (chosen or {}).get(name) or summ["suggested"]
        row = rows.get(fam)
        terms = [tuple(t) for t in row["terms"]] if row else terms_of(fam, len(fn))
        f = fit(terms, xs, y)
        g = (row or {}).get("gate") or ({"passed": False, "why": ["평균 모형(요인 없음)"], "checks": []} if fam == "Mean" else None)
        if g is None and not f["aliased"]:
            nt = len(terms) - 1
            mp = float(stats.f.sf(((f["sst"] - f["sse"]) / nt) / f["mse"], nt, f["df_resid"])) if nt and f["mse"] > 0 else None
            g = gate({"model_p": mp, "lof_p": f["lof"].get("p"), "adj_r2": f["adj_r2"], "pred_r2": f["pred_r2"]})
        passed = bool(g and g["passed"]) and not f["aliased"] and fam != "Mean"
        entry = {"response": name, "unit": design["responses"][j].get("unit"), "n": int(ok.sum()), "summary": summ, "family": fam,
                 "suggested": summ["suggested"], "reason": summ["reason"], "aliased": f["aliased"], "gate": g,
                 "status": "SELECTED" if passed else "UNEXPLAINED", "observed": observed(y)}
        if not f["aliased"]:
            ap = actual_poly(terms, f["coef"], cod)
            aterms = sorted(ap, key=lambda m: (len(m), m))
            entry.update({"terms": [list(t) for t in terms], "coef": f["coef"], "cov": f["cov"], "mse": f["mse"], "df_resid": f["df_resid"],
                          "r2": f["r2"], "adj_r2": f["adj_r2"], "pred_r2": f["pred_r2"], "lof_p": f["lof"].get("p"),
                          "coded_eq": equation(f"Y{j + 1}", terms, f["coef"]),
                          "actual_eq": equation(f"Y{j + 1}", aterms, [ap[m] for m in aterms]),
                          "actual_terms": [list(m) for m in aterms], "actual_coef": [ap[m] for m in aterms]})
        out.append(entry)
    return {"factors": [{"name": n, "unit": design["factors"][i].get("unit"), **cod[i]} for i, n in enumerate(fn)], "responses": out,
            "gate_passed": [e["response"] for e in out if e["status"] == "SELECTED"]}


def predict(terms: Sequence[Sequence[int]], coef: Sequence[float], x: np.ndarray) -> np.ndarray:
    return model_matrix([tuple(t) for t in terms], x) @ np.array(coef)


# ── 곡면 ─────────────────────────────────────────────────────────────────
def _hull(pts: np.ndarray) -> List[List[float]]:
    """2D 볼록 껍질(Andrew monotone chain) — 설계점이 받치는 영역. 점이 3개 미만이면 정사각형."""
    P = sorted(set(map(tuple, np.round(pts, 9))))
    if len(P) < 3:
        return [[1, 1], [-1, 1], [-1, -1], [1, -1], [1, 1]]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in P:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(P):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return [list(p) for p in hull] + [list(hull[0])]


def surfaces(design: Dict[str, Any], reg: Dict[str, Any], steps: int = 25, order: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """반응(행) × 세 번째 요인 수준(열) 곡면 격자. 수준은 표에 나온 그 요인의 서로 다른 값(최대 5개)."""
    fn, X, rn, Y = table_arrays(design)
    cod = coding(X)
    x = to_coded(X, cod)
    k = len(fn)
    idx = list(order) if order and sorted(order) == list(range(k)) else list(range(k))
    g = np.linspace(-1, 1, steps)
    fac = [{"id": f"X{i + 1}", "name": fn[i], "unit": design["factors"][i].get("unit"), "low": cod[i]["low"], "high": cod[i]["high"]} for i in range(k)]
    # 곡면: 검증 게이트를 통과한 반응이 하나라도 있으면 모든 반응을 그린다(불합격 반응은 참고로 표시 — 사용자 2026-09-29).
    # 영역(13단계)·ANOVA(12단계)는 여전히 통과 반응만 쓴다.
    any_pass = any(r.get("status") == "SELECTED" and not r.get("aliased") for r in reg["responses"])

    def drawn(r):
        return not r.get("aliased") and (r.get("status") == "SELECTED" or any_pass)

    def status_of(r):
        if r.get("status") == "SELECTED":
            return r["family"]
        return f"{r['family']} · " + ("평균 모형(요인 효과 없음) — 참고" if r["family"] == "Mean" else "검증 게이트 불합격 — 참고")

    if k == 1:
        out = []
        for j, r in enumerate(reg["responses"]):
            if not drawn(r):
                continue
            mean = predict(r["terms"], r["coef"], g[:, None])
            ok = ~np.isnan(Y[:, j])
            pred = predict(r["terms"], r["coef"], x[ok])
            pts = [{"a": float(X[i, 0]), "y": float(Y[i, j]), "pred": float(p), "above": bool(Y[i, j] >= p)} for i, p in zip(np.where(ok)[0], pred)]
            vals = list(mean) + [p["y"] for p in pts]
            lo, hi = min(vals), max(vals)
            out.append({"id": r["response"], "name": r["response"], "unit": r["unit"], "formula": r["coded_eq"], "status": status_of(r),
                        "gate_passed": r.get("status") == "SELECTED", "line": {"x": [float(to_actual(v, cod[0])) for v in g], "y": mean.tolist()}, "points": pts,
                        "zrange": [lo - 0.08 * (hi - lo or 1), hi + 0.08 * (hi - lo or 1)]})
        return {"kind": "LINE", "factors": fac, "responses": out}
    a, b = idx[0], idx[1]
    c = idx[2] if k == 3 else None
    levels = [None] if c is None else sorted(set(np.round(x[:, c], 9)))
    if len(levels) > 5:
        levels = [-1.0, 0.0, 1.0]
    A, B = np.meshgrid(g, g, indexing="xy")
    axis = {"a": {"id": fac[a]["id"], "actual": [float(to_actual(v, cod[a])) for v in g]},
            "b": {"id": fac[b]["id"], "actual": [float(to_actual(v, cod[b])) for v in g]}}
    out = []
    for j, r in enumerate(reg["responses"]):
        if not drawn(r):
            continue
        slices, lo, hi = [], np.inf, -np.inf
        for lv in levels:
            P = np.zeros((A.size, k))
            P[:, a], P[:, b] = A.ravel(), B.ravel()
            if c is not None:
                P[:, c] = lv
            mean = predict(r["terms"], r["coef"], P).reshape(A.shape)
            lo, hi = min(lo, float(mean.min())), max(hi, float(mean.max()))
            sel = np.where((~np.isnan(Y[:, j])) & (np.ones(len(x), bool) if c is None else np.isclose(x[:, c], lv)))[0]
            pts = []
            if len(sel):
                pred = predict(r["terms"], r["coef"], x[sel])
                for i, p in zip(sel, pred):
                    lo, hi = min(lo, float(Y[i, j])), max(hi, float(Y[i, j]))
                    pts.append({"a": float(X[i, a]), "b": float(X[i, b]), "y": float(Y[i, j]), "pred": float(p), "above": bool(Y[i, j] >= p)})
            hull = _hull(x[sel][:, [a, b]]) if len(sel) >= 3 else _hull(np.zeros((0, 2)))
            outline = [[float(to_actual(p[0], cod[a])), float(to_actual(p[1], cod[b]))] for p in hull]
            slices.append({"level_coded": None if lv is None else float(lv), "level_actual": None if lv is None else float(to_actual(lv, cod[c])),
                           "mean": mean.tolist(), "domain": [[True] * steps] * steps, "points": pts, "domain_outline": outline})
        span = (hi - lo) or 1.0
        out.append({"id": r["response"], "name": r["response"], "unit": r["unit"], "formula": r["coded_eq"], "status": status_of(r),
                    "gate_passed": r.get("status") == "SELECTED", "slices": slices, "zrange": [lo - 0.05 * span, hi + 0.05 * span]})
    return {"kind": "SURFACE", "factors": fac, "axis": axis, "responses": out,
            "slice_factor": ({"id": fac[c]["id"], "name": fac[c]["name"], "unit": fac[c]["unit"]} if c is not None else None),
            "note": "곡면은 요인 범위 전체에 그린다. 바닥 점선은 그 단면의 설계점이 받치는 영역(밖은 외삽)."}
