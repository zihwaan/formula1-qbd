"""반응 곡면 격자 — 반응(행) × 세 번째 요인 수준(열). 논문 Figure(Design-Expert 형식)와 같은 배치로 그리기 위한 데이터.

- 곡면은 두 요인 정사각형 전체(low–high)에 그린다. 설계 지지 영역(BBD: Σ|x| ≤ 2) 밖은 외삽이므로 `domain` 마스크와
  바닥 외곽선(domain_outline)으로 따로 표시한다 — 영역 판정은 여기서 하지 않는다(region.py).
- 실험점은 그 단면 수준의 run만(3요인 BBD: X3 = −1·0·+1). 관측값과 같은 점의 예측값을 함께 줘서 잔차 줄기를 그린다.
- 숫자는 전부 적합된 모형(models.predict)에서 온다. 화면은 계산하지 않는다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from formula.doe import design as D
from formula.doe import region as RG
from formula.doe.contracts import FactorSpec
from formula.doe.models import predict


def _domain_outline(design_type: str, c: Optional[float]) -> List[List[float]]:
    """coded (a, b) 다각형 — BBD 단면 |a|+|b| ≤ 2−|c| ∩ 정사각형, 그 밖(FCCD 등)은 정사각형."""
    if design_type == "BBD" and c is not None:
        r = 2 - abs(c)
        if r < 2 - 1e-9:
            if r <= 1 + 1e-9:
                return [[r, 0], [0, r], [-r, 0], [0, -r], [r, 0]]
            t = r - 1
            return [[1, t], [t, 1], [-t, 1], [-1, t], [-1, -t], [-t, -1], [t, -1], [1, -t], [1, t]]
    return [[1, 1], [-1, 1], [-1, -1], [1, -1], [1, 1]]


def build(factors: Sequence[FactorSpec], models: Dict[str, Dict[str, Any]], responses: Sequence[Dict[str, Any]],
          runs: Sequence[Dict[str, Any]], *, design_type: str, steps: int = 25, order: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """responses[i] = {id, name, unit, operator, lower, upper, key, status?, formula?}
    runs[j] = {coded: {fid: c}, y: {response_id: 관측값}}
    order = [가로축, 세로축, 단면(열) 요인] — 없으면 factors 순서."""
    ids = [f.factor_id for f in factors]
    if order and sorted(order) == sorted(ids):
        ids = list(order)
    fs = {f.factor_id: f for f in factors}
    g = np.linspace(-1, 1, steps)
    fac_out = [{"id": f.factor_id, "name": f.name, "unit": f.unit, "low": f.low, "high": f.high} for f in factors]
    if len(ids) == 1:
        a = ids[0]
        out = []
        for r in responses:
            m = models.get(r["id"])
            if not m:
                continue
            mean = predict(m, {a: g})["mean"]
            pts = [{"a": D.to_actual(run["coded"][a], fs[a]), "y": run["y"].get(r["id"])} for run in runs]
            out.append({**r, "line": {"x": [D.to_actual(float(c), fs[a]) for c in g], "y": mean.tolist()}, "points": pts})
        return {"kind": "LINE", "factors": fac_out, "responses": out}
    a, b = ids[0], ids[1]
    c_id = ids[2] if len(ids) == 3 else None
    levels = [-1.0, 0.0, 1.0] if c_id else [None]
    A, B = np.meshgrid(g, g, indexing="xy")        # 행 = b, 열 = a (Plotly surface z[row=y][col=x])
    axis = {"a": {"id": a, "coded": g.tolist(), "actual": [D.to_actual(float(x), fs[a]) for x in g]},
            "b": {"id": b, "coded": g.tolist(), "actual": [D.to_actual(float(x), fs[b]) for x in g]}}
    out = []
    for r in responses:
        m = models.get(r["id"])
        if not m:
            continue
        slices, lo, hi = [], np.inf, -np.inf
        for lv in levels:
            pts = {a: A.ravel(), b: B.ravel()}
            if c_id:
                pts[c_id] = np.full(A.size, lv)
            mean = predict(m, pts)["mean"].reshape(A.shape)
            P = np.column_stack([pts[i] for i in ids])
            dom = RG.in_domain(design_type, P).reshape(A.shape)
            lo, hi = min(lo, float(mean.min())), max(hi, float(mean.max()))
            sel = [run for run in runs if not c_id or abs(run["coded"][c_id] - lv) < 1e-9]
            obs = []
            if sel:
                pp = {i: np.array([run["coded"][i] for run in sel], dtype=float) for i in ids}
                pred = predict(m, pp)["mean"]
                for run, yh in zip(sel, pred):
                    y = run["y"].get(r["id"])
                    if y is None:
                        continue
                    lo, hi = min(lo, float(y)), max(hi, float(y))
                    obs.append({"a": D.to_actual(run["coded"][a], fs[a]), "b": D.to_actual(run["coded"][b], fs[b]),
                                "y": float(y), "pred": float(yh), "above": bool(y >= yh)})
            outline = [[D.to_actual(p[0], fs[a]), D.to_actual(p[1], fs[b])] for p in _domain_outline(design_type, lv)]
            slices.append({"level_coded": lv, "level_actual": D.to_actual(lv, fs[c_id]) if c_id else None,
                           "mean": mean.tolist(), "domain": dom.tolist(), "points": obs, "domain_outline": outline})
        span = (hi - lo) or 1.0
        out.append({**r, "slices": slices, "zrange": [lo - 0.05 * span, hi + 0.05 * span]})
    return {"kind": "SURFACE", "factors": fac_out, "axis": axis,
            "slice_factor": ({"id": c_id, "name": fs[c_id].name, "unit": fs[c_id].unit} if c_id else None),
            "design_type": design_type, "responses": out,
            "note": "곡면은 low–high 정사각형 전체에 그린다. 점선 밖은 설계 지지 영역 밖(외삽)이다."}
