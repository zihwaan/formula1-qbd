"""근거 결손 게이트 값을 말로 받는다 — 관측값을 시스템 측정 키로 옮기는 결정론 계층.

용해도는 pH마다 다르고, 투과도는 흡수율(%)·분율·절대 생체이용률·요중 회수율·Caco-2 Papp(cm/s, ×10⁻⁶ cm/s, nm/s)처럼
여러 형태로 말해진다. 입력 에이전트(LLM 또는 규칙)는 글에서 관측을 **쓰인 그대로**(값·단위·pH·온도·매질·방법) 뽑기만
하고, 단위 환산·pH 1.2–6.8 최저값·용량/용해도 부피·투과도 근거 해석은 이 모듈이 한다(ICH M9 5.1·5.2).

지키는 선
  - 값·pH·온도는 사용자 글에 있는 숫자여야 하고, 단위는 글에 그 단위가 실제로 있어야 옮긴다
    (µg/mL를 mg/mL로 읽는 1000배 오류를 막는다).
  - 고용해도는 pH 1.2·4.5·6.8을 모두 쟀을 때만 확정한다. 잰 pH 중 하나라도 250 mL를 넘으면 저용해도는 그것만으로
    확정된다 — 빠진 pH는 최저값을 더 낮출 수만 있기 때문이다.
  - 절대 생체이용률·요중 회수율은 85% 이상일 때만 흡수율로 옮긴다. 그보다 낮으면 초회통과 대사·담즙 배설 때문일 수
    있어 흡수가 낮다는 근거가 되지 못한다(물질수지 흡수율이 필요하다).
  - Caco-2·PAMPA Papp은 흡수율로 환산하지 않는다(환산식은 실험실마다 다른 상관식이다). 투과도 근거 자료로만 기록한다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

NUM = r"-?\d+(?:\.\d+)?"
BCS_PH = (1.2, 4.5, 6.8)
PH_TOL = 0.1                 # pH 1.2·4.5·6.8 지점으로 인정하는 폭
PH_RANGE = (1.15, 6.85)      # ICH M9 5.1 — pH 1.2–6.8
BCS_VOLUME_ML = 250.0        # ICH M9 5.1 고용해도 기준 (database/04_biopharmaceutics/bcs_classification_criteria.csv BCS001)
HIGH_FA = 85.0               # ICH M9 5.2 고투과도 기준 (BCS003·BCS004)

# 이 모듈만 채우는 키 — 에이전트가 이 키를 LLM 값으로 직접 넣지 않게 한다(단위·pH 해석을 건너뛰므로)
OWNED_KEYS = ("solubility_mg_per_ml", "dose_solubility_volume", "fraction_absorbed",
              "solubility_fassif_mg_per_ml", "peff_human_cm_s")

Kind = Literal["solubility", "fraction_absorbed", "absolute_bioavailability", "urinary_recovery", "papp", "peff"]
METHOD_KR = {"caco-2": "Caco-2", "caco2": "Caco-2", "pampa": "PAMPA", "mdck": "MDCK"}
KIND_KR = {"solubility": "용해도", "fraction_absorbed": "흡수율", "absolute_bioavailability": "절대 생체이용률",
           "urinary_recovery": "요중 회수율", "papp": "투과계수(Papp)", "peff": "인체 유효투과도(Peff)"}


class Observation(BaseModel):
    """글에 쓰인 관측 하나 — 환산하지 않은 값 그대로."""
    kind: Kind
    value: float
    unit: str = Field("", description="글에 쓴 단위 그대로(예: mg/mL, µg/mL, %, ×10^-6 cm/s). 없으면 빈칸")
    ph: Optional[float] = Field(None, description="글에 쓴 pH. 없으면 비움")
    temp_c: Optional[float] = Field(None, description="글에 쓴 온도(°C). 없으면 비움")
    medium: str = Field("", description="매질(완충액, 물, FaSSIF, FeSSIF …) — 글에 있을 때만")
    method: str = Field("", description="방법(Caco-2, PAMPA, 물질수지, 정맥 대조 …) — 글에 있을 때만")


@dataclass
class Normalized:
    measurements: Dict[str, Any] = field(default_factory=dict)
    lines: List[str] = field(default_factory=list)     # 카드에 보일 환산 과정
    notes: List[str] = field(default_factory=list)     # 옮기지 않은 것과 이유
    asks: List[str] = field(default_factory=list)


# ── 숫자·단위 표기 ─────────────────────────────────────────────────────────
_SUP = str.maketrans({"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8",
                      "⁹": "9", "⁻": "-", "⁺": "+", "−": "-", "–": "-", "μ": "µ", "×": "x", "㎍": "µg", "㎎": "mg",
                      "㎖": "ml", "ℓ": "l", "℃": "°c", "㎛": "µm", "㎚": "nm"})
_SCI = re.compile(r"(\d+(?:\.\d+)?)\s*(?:e\s*([+-]?\d+)|[x\*·]\s*10\s*\^?\s*([+-]?\s*\d+))", re.I)


def prep(text: str) -> str:
    return (text or "").translate(_SUP)


def number_pool(text: str) -> List[float]:
    """글에 있는 숫자 — 과학 표기(2.1e-6, 2.1 × 10⁻⁶)는 곱한 값도 넣는다."""
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", prep(text))     # 천 단위 쉼표만 — '2.1,0.35' 같은 목록은 두 숫자로
    pool = [float(x) for x in re.findall(NUM, t)]
    for m in _SCI.finditer(t):
        exp = (m.group(2) or m.group(3) or "0").replace(" ", "")
        pool.append(float(m.group(1)) * 10 ** int(exp))
    return pool


def _grounded(value: Optional[float], pool: Iterable[float]) -> bool:
    return value is not None and any(abs(value - p) <= 1e-9 * max(1.0, abs(p)) for p in pool)


def _unit_key(u: str) -> str:
    s = prep(u).lower().replace("mcg", "µg").replace(" per ", "/").replace("밀리리터", "ml").replace("리터", "l")
    s = re.sub(r"(?<![a-zµ])u(?=g|m|mol)", "µ", s)
    s = re.sub(r"cm\s*[·\*]?\s*s\s*\^?\s*-1", "cm/s", s)
    s = s.replace("cm/sec", "cm/s")
    return re.sub(r"[\s·]+", "", s)


_EXP = re.compile(r"^(?:x|\*)?\s*(?:10\s*\^?\s*([+-]?\s*\d+)|e\s*([+-]?\d+))\s*", re.I)


def split_exp(unit: str) -> Tuple[str, Optional[int]]:
    """'×10^-6 cm/s' → ('cm/s', -6). 지수가 없으면 None."""
    u = prep(unit).strip()
    m = _EXP.match(u)
    if not m:
        return u, None
    return u[m.end():].strip(), int((m.group(1) or m.group(2)).replace(" ", ""))


def _unit_in_text(base: str, text: str) -> bool:
    key = _unit_key(base)
    if not key:
        return True
    return re.search(r"(?<![a-zµ])" + re.escape(key) + r"(?![a-z])", _unit_key(text)) is not None


def _unit_after(value: float, text: str, family: str) -> Optional[List[str]]:
    """글에서 이 값 바로 뒤(목록이면 목록 끝)에 처음 나오는 같은 계열 단위들. 값이 글에 그대로 없으면 None(판단 보류).
    반환은 정규화한 단위 키 목록 — 주장한 단위가 이 안에 있어야 한다."""
    t = prep(text).lower()
    found: List[str] = []
    for m in re.finditer(NUM, t):
        if abs(float(m.group(0)) - value) > 1e-9 * max(1.0, abs(value)):
            continue
        u = re.search(family, t[m.end(): m.end() + 60])
        if u:
            found.append(_unit_key(u.group(0)))
    return found or None


SOL_MASS = {"mg/ml": 1.0, "g/l": 1.0, "mg/cm3": 1.0, "µg/ml": 1e-3, "mg/l": 1e-3, "ng/ml": 1e-6, "g/ml": 1e3,
            "mg/100ml": 1e-2, "µg/l": 1e-6, "%w/v": 10.0, "w/v%": 10.0}
SOL_MOLAR = {"m": 1.0, "mol/l": 1.0, "mm": 1e-3, "mmol/l": 1e-3, "µm": 1e-6, "µmol/l": 1e-6, "nmol/l": 1e-9}
PERM = {"cm/s": 1.0, "nm/s": 1e-7, "µm/s": 1e-4, "m/s": 100.0}


def _fmt(x: float) -> str:
    if x == 0:
        return "0"
    if abs(x) < 1e-3 or abs(x) >= 1e5:
        mant, exp = f"{x:.3e}".split("e")
        return f"{float(mant):g}×10^{int(exp)}"
    return f"{x:.4g}"


# ── 규칙 기반 추출 (LLM이 없을 때의 바닥) ─────────────────────────────────
_SOL_U = r"(mg\s*/\s*ml|µg\s*/\s*ml|ug\s*/\s*ml|mcg\s*/\s*ml|ng\s*/\s*ml|mg\s*/\s*l|g\s*/\s*l|mmol\s*/\s*l|µmol\s*/\s*l|mol\s*/\s*l|mm|µm)(?![a-z/])"
_PERM_U = r"((?:[x\*]\s*10\s*\^?\s*-?\s*\d+|e-?\d+)?\s*(?:cm\s*/\s*s(?:ec)?|nm\s*/\s*s|µm\s*/\s*s))"
_PERM_BASE = r"(cm\s*/\s*s(?:ec)?|nm\s*/\s*s|µm\s*/\s*s|um\s*/\s*s)"
_TEMP = re.compile(r"(" + NUM + r")\s*(?:°\s*c|도)")


def looks_like_evidence(text: str) -> bool:
    """pH가 붙은 용해도나 투과도 계열 표현 — 단위·pH를 따져 옮겨야 하는 글."""
    t = prep(text).lower()
    return bool(re.search(r"(?<![a-z])ph\s*" + NUM, t) and re.search(_SOL_U, t)) or bool(re.search(
        r"(papp|caco-?2|pampa|mdck|peff|투과|흡수율|흡수\s*분율|fraction\s*absorbed|생체\s*이용|bioavailability|요중|urinary|fassif)", t))


def rule_observations(text: str) -> List[Observation]:
    t = prep(text).lower()
    temps = [float(x) for x in _TEMP.findall(t)]
    temp = temps[0] if len(set(temps)) == 1 else None
    out: List[Observation] = []
    seen: set = set()

    def sol(ph: Optional[float], v: str, u: str, medium: str = "") -> None:
        k = ("sol", ph, float(v), u)
        if k not in seen:
            seen.add(k)
            out.append(Observation(kind="solubility", value=float(v), unit=u, ph=ph, temp_c=temp, medium=medium))

    if "ph" in t:
        lst = r"(" + NUM + r"(?:\s*(?:,|/|·|및|와|과)\s*" + NUM + r")+)"
        for m in re.finditer(r"ph\s*" + lst + r"\s*(?:에서(?:의)?|의)?\s*(?:용해도)?\s*(?:는|은|가|이)?\s*(?:각각)?\s*"
                             + lst + r"\s*" + _SOL_U, t):
            phs, vals = re.findall(NUM, m.group(1)), re.findall(NUM, m.group(2))
            if len(phs) == len(vals):
                for p, v in zip(phs, vals):
                    sol(float(p), v, m.group(3))
        # "pH 1.2에서 2.1 mg/mL, 4.5에서 0.35 mg/mL" — 두 번째부터 'pH'를 생략해도 앞에 pH가 나왔으면 pH로 읽는다
        for m in re.finditer(r"(?<![0-9.])(?:ph\s*)?(" + NUM + r")\s*(?:에서(?:의|는)?|:|=|조건(?:에서)?)\s*(?:용해도)?\s*"
                             r"(?:는|은|가|이)?\s*(?:약\s*)?(" + NUM + r")\s*" + _SOL_U, t):
            p = float(m.group(1))
            if 0 <= p <= 14 and (m.group(0).startswith("ph") or "ph" in t[max(0, m.start() - 60): m.start()]):
                sol(p, m.group(2), m.group(3))
        for m in re.finditer(r"(" + NUM + r")\s*" + _SOL_U + r"\s*(?:\(\s*|@\s*|at\s+)ph\s*(" + NUM + r")", t):
            sol(float(m.group(3)), m.group(1), m.group(2))
    for m in re.finditer(r"(fassif|fessif)[^0-9]{0,15}(" + NUM + r")\s*" + _SOL_U, t):
        sol(None, m.group(2), m.group(3), medium="FaSSIF" if m.group(1) == "fassif" else "FeSSIF")

    def pct(pattern: str, kind: str) -> None:
        for m in re.finditer(pattern + r"[^0-9%]{0,15}?(?P<v>" + NUM + r")\s*(?P<u>%|퍼센트)?", t):
            out.append(Observation(kind=kind, value=float(m.group("v")), unit="%" if m.group("u") else ""))

    pct(r"(절대\s*(?:생체\s*이용률|생체\s*이용율|ba\b|bioavailability)|absolute\s*(?:oral\s*)?bioavailability)", "absolute_bioavailability")
    pct(r"(요중\s*(?:미변화체\s*)?(?:회수율|배설률|회수|배설)|urinary\s*(?:recovery|excretion))", "urinary_recovery")
    pct(r"(흡수율|흡수\s*분율|fraction\s*absorbed|\bfa\b|흡수\s*정도|extent\s*of\s*absorption)", "fraction_absorbed")
    for m in re.finditer(r"(papp|caco-?2|pampa|mdck|peff)[^0-9]{0,25}?(" + NUM + r")\s*" + _PERM_U, t):
        kind = "peff" if m.group(1) == "peff" else "papp"
        method = next((w for w in ("caco-2", "caco2", "pampa", "mdck") if w in t), "") if kind == "papp" else ""
        out.append(Observation(kind=kind, value=float(m.group(2)), unit=m.group(3).strip(), method=method))
    return out


# ── 정규화 ─────────────────────────────────────────────────────────────────
def normalize(observations: List[Observation], text: str, *, dose_mg: Optional[float] = None,
              mw: Optional[float] = None, open_keys: Iterable[str] = ()) -> Normalized:
    """관측 → 시스템 측정 키. 숫자·단위 검사, 단위 환산, pH 최저값, 용량/용해도 부피, 투과도 해석."""
    res = Normalized()
    pool = number_pool(text)
    open_keys = set(open_keys)
    points: List[Tuple[Optional[float], float, str, Optional[float]]] = []   # (pH, mg/mL, 원래 표기, 온도)
    fassif: List[Tuple[float, str]] = []
    fa: List[Tuple[float, str]] = []
    permeability_seen = False

    for o in observations:
        kr = KIND_KR.get(o.kind, o.kind)
        if not _grounded(o.value, pool):
            res.notes.append(f"{kr} 값 {o.value:g}은 글에 없는 숫자라 옮기지 않았습니다.")
            continue
        if o.ph is not None and not _grounded(o.ph, pool):
            res.notes.append(f"{kr}의 pH {o.ph:g}는 글에 없는 숫자라 이 값을 옮기지 않았습니다.")
            continue
        temp = o.temp_c if _grounded(o.temp_c, pool) else None
        base, exp = split_exp(o.unit)
        if o.unit and not _unit_in_text(base, text):
            res.notes.append(f"{kr} {o.value:g}의 단위 '{o.unit}'가 글에 없어 옮기지 않았습니다 — 단위를 함께 적어 주세요.")
            continue
        if exp is not None and not _grounded(float(exp), pool):
            res.notes.append(f"{kr} {o.value:g}의 지수(10^{exp})가 글에 없어 옮기지 않았습니다.")
            continue
        family = {"solubility": _SOL_U, "papp": _PERM_BASE, "peff": _PERM_BASE}.get(o.kind)
        near = _unit_after(o.value, text, family) if family and o.unit else None
        if near is not None and _unit_key(base) not in near:
            res.notes.append(f"{kr} {o.value:g} 뒤에 적힌 단위는 '{near[0]}'인데 '{o.unit}'로 읽혀 옮기지 않았습니다 — 다시 확인해 주세요.")
            continue
        scale = 10.0 ** exp if exp is not None else 1.0
        said = f"{o.value:g}{(' ' + o.unit) if o.unit else ''}"

        if o.kind == "solubility":
            key = _unit_key(base)
            if key in SOL_MASS:
                mg = o.value * scale * SOL_MASS[key]
            elif key in SOL_MOLAR or key.startswith("log"):
                if not mw:
                    res.notes.append(f"용해도 {said}는 몰 농도라 분자량이 있어야 mg/mL로 바꿀 수 있습니다 — 구조가 확인된 설계에서 다시 입력해 주세요.")
                    continue
                mol_l = 10.0 ** o.value if key.startswith("log") else o.value * scale * SOL_MOLAR[key]
                mg = mol_l * mw
                said += f" (× MW {mw:.1f} g/mol)"
            elif not key:
                res.notes.append(f"용해도 {o.value:g}에 단위가 없어 옮기지 않았습니다 — mg/mL, µg/mL처럼 단위를 적어 주세요.")
                continue
            else:
                res.notes.append(f"용해도 단위 '{o.unit}'는 환산표에 없습니다(질량/부피 또는 몰 농도로 적어 주세요).")
                continue
            if mg <= 0 or not math.isfinite(mg):
                res.notes.append(f"용해도 {said}는 0보다 커야 합니다.")
                continue
            medium = o.medium.lower()
            if "fassif" in medium:
                fassif.append((mg, said))
            elif "fessif" in medium:
                res.notes.append(f"FeSSIF 용해도 {said}는 받을 키가 없어 기록만 합니다(BCS·DCS 계산에 쓰지 않음).")
            else:
                points.append((o.ph, mg, said if _unit_key(base) == "mg/ml" and scale == 1 else f"{said} = {_fmt(mg)} mg/mL", temp))
        elif o.kind in ("fraction_absorbed", "absolute_bioavailability", "urinary_recovery"):
            u = _unit_key(base)
            if u in ("%", "퍼센트"):
                v = o.value
            elif u in ("", "fraction", "분율") and o.value <= 1:
                v = o.value * 100
                said += " (분율 → ×100 %)"
            elif u == "":
                v = o.value
                said += " (%로 읽음)"
            else:
                res.notes.append(f"{kr} 단위 '{o.unit}'는 %나 분율이 아니라 옮기지 않았습니다.")
                continue
            if not 0 <= v <= 100:
                res.notes.append(f"{kr} {said}는 0–100 % 범위를 벗어납니다.")
                continue
            if o.kind != "fraction_absorbed" and v < HIGH_FA:
                res.notes.append(f"{kr} {_fmt(v)} %는 85 % 미만이라 흡수율로 옮기지 않았습니다 — 초회통과 대사나 담즙 배설로 "
                                 "낮아질 수 있어 흡수가 낮다는 근거가 되지 못합니다(ICH M9 5.2). 물질수지 흡수율이 있으면 알려 주세요.")
                permeability_seen = True
                continue
            fa.append((v, f"{kr} {said}"))
            permeability_seen = True
        elif o.kind == "papp":
            key = _unit_key(base)
            if key.startswith("log"):
                cm_s = 10.0 ** o.value
            elif key in PERM:
                cm_s = o.value * scale * PERM[key]
            else:
                res.notes.append(f"Papp 단위 '{o.unit or '없음'}'를 cm/s로 바꿀 수 없어 옮기지 않았습니다.")
                continue
            if not 1e-9 <= cm_s <= 1e-2:
                res.notes.append(f"Papp {said} = {_fmt(cm_s)} cm/s는 투과계수로 보기 어려운 크기입니다 — 지수(×10⁻⁶ 등)를 확인해 주세요.")
                continue
            res.lines.append(f"{METHOD_KR.get(o.method.lower().replace(' ', ''), o.method) or 'Papp'} Papp {said} = {_fmt(cm_s)} cm/s — 흡수율로 환산하지 않습니다(ICH M9 5.2: "
                             "BCS 투과도는 인체 흡수 자료로 판정, in vitro는 보조 근거)")
            permeability_seen = True
        elif o.kind == "peff":
            key = _unit_key(base)
            if key not in PERM:
                res.notes.append(f"Peff 단위 '{o.unit or '없음'}'를 cm/s로 바꿀 수 없어 옮기지 않았습니다.")
                continue
            cm_s = o.value * scale * PERM[key]
            if not 1e-9 <= cm_s <= 1e-2:
                res.notes.append(f"Peff {said} = {_fmt(cm_s)} cm/s는 투과계수로 보기 어려운 크기입니다 — 지수(×10⁻⁴ 등)를 확인해 주세요.")
                continue
            res.measurements["peff_human_cm_s"] = float(f"{cm_s:.6g}")
            res.lines.append(f"인체 Peff {said} = {_fmt(cm_s)} cm/s")
            permeability_seen = True

    _solubility(points, dose_mg, res)
    if fassif:
        mg, said = min(fassif)
        res.measurements["solubility_fassif_mg_per_ml"] = float(f"{mg:.6g}")
        res.lines.append(f"FaSSIF 용해도 {said}" + ("" if said.endswith(f"{_fmt(mg)} mg/mL") or said.lower().endswith("mg/ml") else f" = {_fmt(mg)} mg/mL"))
    if fa:
        v, said = max(fa) if len({round(x, 6) for x, _ in fa}) > 1 else fa[0]
        res.measurements["fraction_absorbed"] = round(v, 3)
        res.lines.append(f"흡수율 = {_fmt(v)} % ← {said}" + (" (여러 값 중 인체 흡수 정도의 최댓값 — 각 근거는 흡수의 하한)"
                                                           if len(fa) > 1 else "")
                         + f" · ICH M9 기준 {HIGH_FA:g} % {'이상 → 고투과' if v >= HIGH_FA else '미만 → 저투과'}")
    if permeability_seen and "permeability_evidence_done" in open_keys:
        res.measurements["permeability_evidence_done"] = True
        res.lines.append("투과도 근거 자료가 제출되어 '투과도 근거 검토'를 수행으로 기록합니다.")
    return res


def _solubility(points: List[Tuple[Optional[float], float, str, Optional[float]]], dose_mg: Optional[float],
                res: Normalized) -> None:
    if not points:
        return
    used: List[Tuple[float, float, str]] = []
    for ph, mg, said, temp in points:
        if ph is None:
            res.notes.append(f"용해도 {said}는 pH가 없어 BCS 최저값 계산에 쓰지 않았습니다 — 잰 pH를 함께 알려 주세요.")
        elif not PH_RANGE[0] <= ph <= PH_RANGE[1]:
            res.notes.append(f"pH {ph:g} 용해도 {said}는 ICH M9 범위(pH 1.2–6.8) 밖이라 최저값 계산에서 뺐습니다.")
        elif temp is not None and not 36 <= temp <= 38:
            res.notes.append(f"pH {ph:g} 용해도 {said}는 {temp:g} °C 값이라 BCS 조건(37 ± 1 °C)이 아니어서 뺐습니다.")
        else:
            used.append((ph, mg, said))
    if not used:
        return
    res.lines.append("pH별 용해도: " + " · ".join(f"pH {ph:g} {said}" for ph, _, said in sorted(used)))
    ph_min, mg_min, _ = min(used, key=lambda x: x[1])
    missing = [p for p in BCS_PH if not any(abs(ph - p) <= PH_TOL for ph, _, _ in used)]
    vol = dose_mg / mg_min if dose_mg else None
    res.lines.append(f"최저값: pH {ph_min:g}에서 {_fmt(mg_min)} mg/mL")
    if vol is not None:
        res.lines.append(f"용량/용해도 부피 = {dose_mg:g} mg ÷ {_fmt(mg_min)} mg/mL = {_fmt(vol)} mL "
                         f"(ICH M9 고용해도 기준 {BCS_VOLUME_ML:g} mL {'이하' if vol <= BCS_VOLUME_ML else '초과'})")
    if not missing:
        res.measurements["solubility_mg_per_ml"] = float(f"{mg_min:.6g}")
        if vol is not None:
            res.measurements["dose_solubility_volume"] = round(vol, 2)
        else:
            res.notes.append("1회 투여 용량이 없어 용량/용해도 부피를 계산하지 못했습니다 — 용량(mg)을 알려 주세요.")
        return
    miss = ", ".join(f"{p:g}" for p in missing)
    if vol is not None and vol > BCS_VOLUME_ML:
        # 빠진 pH는 최저값을 더 낮출 수만 있다 → 부피는 더 커질 뿐 저용해도 결론은 바뀌지 않는다
        res.measurements["dose_solubility_volume"] = round(vol, 2)
        res.lines.append(f"pH {miss}는 재지 않았지만 pH {ph_min:g}에서 이미 {BCS_VOLUME_ML:g} mL를 넘어 저용해도로 확정됩니다"
                         " (빠진 pH는 최저값을 더 낮출 수만 있다). 이 부피는 하한값입니다.")
        res.notes.append(f"실험 용해도 근거(pH 1.2 / 4.5 / 6.8)는 pH {miss} 값이 들어와야 채워집니다.")
        return
    if vol is None:
        res.asks.append(f"pH {miss} 용해도와 1회 투여 용량(mg)이 더 있어야 BCS 용해도를 판정할 수 있습니다.")
    else:
        res.asks.append(f"잰 pH에서는 {BCS_VOLUME_ML:g} mL 이하지만 고용해도로 확정하려면 pH {miss} 용해도(37 °C)도 필요합니다.")
    res.notes.append(f"pH {miss} 값이 없어 용해도는 아직 옮기지 않았습니다 — 나머지 pH 값과 함께 다시 말씀해 주시면 한 번에 계산합니다.")


def guess_grade(text: str) -> str:
    """근거 등급 기본값 — 카드에서 바꿀 수 있다."""
    if re.search(r"(문헌|논문|보고된|허가\s*사항|라벨|label|dailymed|pmid|doi)", text, re.I):
        return "literature"
    if re.search(r"(측정|실측|쟀|자체|사내|우리\s*(?:랩|실험실)|실험\s*결과|분석\s*결과)", text):
        return "self_measured"
    return "user_statement"
