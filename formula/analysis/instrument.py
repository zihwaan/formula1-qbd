"""기기 원자료(.xy·.csv·.txt 두 열 수치) → 측정 필드 **초안** (결정론·재현 가능).

측정값 입력 개선 요청서 과제 4: 첨부가 기기 원자료면 LLM이 아니라 코드로 계산한다. 결과는 입력 칸을 채우는
초안일 뿐이고, 연구자가 확인해 제출해야 반영된다. 계산할 수 없는 값(DSC 융해열처럼 승온속도·시료량이 필요한
값)은 만들지 않고 비워 둔다.

- M_XRPD (2θ, 강도): 날카로운 피크 목록과 비정질 halo 여부
- M_DSC (온도 °C, 열류): 흡열 피크 수와 가장 큰 흡열의 onset(접선 외삽) — 흡열 방향은 기본 '아래(−)'로 가정하고
  초안에 가정을 적는다(기기마다 exo up/down이 다르다)
- M_TGA (온도 °C, 무게 % 또는 mg): 100–150 °C 무게 감소, 5% 감소 온도(Td5%)를 분해 시작 초안으로
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

SUPPORTED = {"M_XRPD", "M_DSC", "M_TGA"}


def parse_two_columns(data: bytes) -> Tuple[np.ndarray, np.ndarray]:
    """숫자 두 열을 읽는다(구분자 공백·쉼표·탭·세미콜론, 머리글·주석 줄은 건너뜀)."""
    text = data.decode("utf-8", errors="ignore")
    xs, ys = [], []
    for line in text.splitlines():
        parts = [p for p in re.split(r"[,\t; ]+", line.strip()) if p]
        if len(parts) < 2:
            continue
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        xs.append(x)
        ys.append(y)
    if len(xs) < 20:
        raise ValueError("두 열 수치 데이터가 20점 미만입니다 — 기기 원자료(x, y)인지 확인하세요")
    x, y = np.asarray(xs), np.asarray(ys)
    order = np.argsort(x)
    return x[order], y[order]


def _smooth(y: np.ndarray, k: int = 5) -> np.ndarray:
    k = max(1, min(k, len(y) // 10 or 1))
    return np.convolve(y, np.ones(k) / k, mode="same")


def xrpd(x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    from scipy.signal import find_peaks, peak_widths
    ys = _smooth(y, 3)
    base = np.percentile(ys, 10)
    rng = float(ys.max() - base) or 1.0
    step = float(np.median(np.diff(x))) or 0.02
    peaks, props = find_peaks(ys, prominence=0.08 * rng)
    widths = peak_widths(ys, peaks, rel_height=0.5)[0] * step if len(peaks) else np.array([])
    sharp = [(float(x[p]), float(w)) for p, w in zip(peaks, widths) if w < 1.0]
    broad = [(float(x[p]), float(w)) for p, w in zip(peaks, widths) if w >= 3.0]
    fields = {"is_amorphous_halo": bool(broad and not sharp)}
    return {"fields": fields,
            "evidence": {"sharp_peaks_2theta": [round(p, 2) for p, _ in sorted(sharp, key=lambda t: t[0])][:20],
                         "broad_humps_2theta": [round(p, 2) for p, _ in broad][:5],
                         "rule": "FWHM < 1° 피크 = 결정성, FWHM ≥ 3° 봉우리만 있으면 비정질 halo"},
            "not_derived": {"crystalline_form_id": "결정형 ID는 기준 패턴과의 비교가 필요해 계산하지 않았다"}}


def dsc(x: np.ndarray, y: np.ndarray, endo_down: bool = True) -> Dict[str, Any]:
    from scipy.signal import find_peaks
    s = -_smooth(y, 5) if endo_down else _smooth(y, 5)   # 흡열을 위로 뒤집어 봉우리로 찾는다
    base = np.median(s)
    rng = float(s.max() - base) or 1.0
    peaks, props = find_peaks(s, prominence=0.15 * rng)
    if not len(peaks):
        return {"fields": {"multiple_endotherms": False}, "evidence": {"endotherm_peaks_c": []},
                "not_derived": {"tm_c": "흡열 피크를 찾지 못했다"}}
    main = int(peaks[np.argmax(s[peaks])])
    # onset: 피크 앞쪽 최대 기울기 점의 접선을 기준선(피크 앞 구간 중앙값)과 교차
    left = max(0, main - max(10, len(x) // 20))
    seg = slice(left, main + 1)
    grad = np.gradient(s[seg], x[seg])
    i = left + int(np.argmax(grad))
    slope = float(np.gradient(s, x)[i]) or 1e-9
    pre = s[max(0, left - len(x) // 20):left + 1]
    baseline = float(np.median(pre)) if len(pre) else float(base)
    onset = float(x[i] - (s[i] - baseline) / slope)
    return {"fields": {"tm_c": round(onset, 1), "multiple_endotherms": bool(len(peaks) > 1)},
            "evidence": {"endotherm_peaks_c": [round(float(x[p]), 1) for p in peaks],
                         "main_peak_c": round(float(x[main]), 1),
                         "assumption": "흡열 = 음의 방향(exo up)으로 가정 — 기기 설정이 반대면 결과가 달라진다"},
            "not_derived": {"delta_hf_j_g": "융해열은 승온속도·시료량이 필요해 계산하지 않았다",
                            "thermally_stable_near_tm": "열안정 판단은 TGA·외관 확인이 필요하다"}}


def tga(x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    w0 = float(np.median(y[: max(3, len(y) // 50)]))
    pct = y / w0 * 100 if w0 else y
    def at(t: float) -> float:
        return float(np.interp(t, x, pct))
    loss_100_150 = round(at(100.0) - at(150.0), 3) if x.min() <= 100 <= x.max() and x.min() <= 150 <= x.max() else None
    below = np.where(pct <= 95.0)[0]
    td5 = round(float(x[below[0]]), 1) if len(below) else None
    fields: Dict[str, Any] = {}
    if loss_100_150 is not None:
        fields["weight_loss_100_150c_percent"] = loss_100_150
    if td5 is not None:
        fields["decomposition_onset_c"] = td5
    return {"fields": fields,
            "evidence": {"initial_weight": round(w0, 4), "td5_c": td5,
                         "rule": "무게를 시작값 대비 %로 환산 · 분해 시작 초안 = 5% 감소 온도(Td5%)"},
            "not_derived": {} if fields else {"all": "온도 범위가 100–150 °C를 덮지 않거나 5% 감소가 없다"}}


def interpret(measurement_id: str, data: bytes) -> Dict[str, Any]:
    if measurement_id not in SUPPORTED:
        raise ValueError(f"{measurement_id}는 기기 원자료 자동 해석 대상이 아니다(지원: {', '.join(sorted(SUPPORTED))})")
    x, y = parse_two_columns(data)
    fn = {"M_XRPD": xrpd, "M_DSC": dsc, "M_TGA": tga}[measurement_id]
    out = fn(x, y)
    out.update({"method": "deterministic", "points": int(len(x)), "x_range": [float(x.min()), float(x.max())]})
    return out
