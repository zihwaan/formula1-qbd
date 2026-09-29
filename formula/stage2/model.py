"""2단계 단계 정의 · 데이터 모양 · 결정론 검사 · 파생(행렬·병합).

단계 데이터(JSON)
 1 prototype : {api, dosage_form, route, process, strength_mg, unit_weight_mg, ingredients[{name, mg, pct, function, role}], process_steps[]}   (Table 1)
 2 qtpp      : {items[{element, sub_element?, target, justification, basis?}]}                                                             (Table 3)
 3 cqa       : {items[{category, attribute, short, target, is_cqa, justification, in_risk_assessment, exclusion_reason?, basis?}]}          (Table 4)
 4 rm_just   : {variables[{name, kind:"material"}], items[{variable, cqas[], level, text, basis?}]}                                         (Table 6)
 5 rm_matrix : {cqas[], variables[], levels[[..]]}  ← 4에서 코드가 만든다                                                                    (Table 5)
 6 fp_just   : {variables[{name, kind:"formulation"|"process"}], items[...]}                                                                (Table 8)
 7 fp_matrix : ← 6에서                                                                                                                       (Table 7)
 8 recommend : {candidates[{variable, kind, high[], medium[]}](High만), watch[](Medium만), material_controls[]}  ← 5·7에서 코드가 만든다(선택 없음)
 9 design    : {factors[{name, unit}], responses[{name, unit}], rows[{std, run, x[], y[]}]}                                               (Table 9)
10 regression: doe.regression(...) + chosen{response: family}                                                                               (Table 10)
11 surface   : {images?}  곡면은 10의 선택 모형으로 그때그때 계산
12 anova     : doe.anova(...)                                                                                                                (Table 11)
13 space     : {specs[{response, unit, op, lower, upper, basis}], slice?}  ← space.region (평균 기준 Overlay 영역 · control space · 최적 처방)
14 vplan     : {delta, reference?, plan}  ← space.plan (SETPOINT · BOUNDARY · ROBUSTNESS, Bonferroni 예측구간 — 승인 = 잠금)
15 verify    : {independent, observations[{role, values}], judgement}  ← space.judge (규격 통과 × 예측구간 2×2)
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

STEPS = ["prototype", "qtpp", "cqa", "rm_just", "rm_matrix", "fp_just", "fp_matrix", "recommend", "design", "regression", "surface", "anova",
         "space", "vplan", "verify"]
TITLE = {"prototype": "프로토타입", "qtpp": "QTPP", "cqa": "CQA 판별", "rm_just": "원료 물성 위험평가", "rm_matrix": "원료 위험평가 정리",
         "fp_just": "제형·공정 변수 위험평가", "fp_matrix": "제형·공정 위험평가 정리", "recommend": "종합 정리 · 위험평가 보고서",
         "design": "실험 설계 입력", "regression": "회귀식 · 모형 진단", "surface": "반응 곡면", "anova": "ANOVA",
         "space": "Design Space (Overlay plot)", "vplan": "확인계획 잠금", "verify": "확인배치 · 2×2 판정"}
TABLE = {"prototype": "Table 1", "qtpp": "Table 3", "cqa": "Table 4", "rm_just": "Table 6", "rm_matrix": "Table 5", "fp_just": "Table 8",
         "fp_matrix": "Table 7", "design": "Table 9", "regression": "Table 10", "surface": "Figure 1", "anova": "Table 11",
         "space": "Peterson 2008", "vplan": "확인점 3", "verify": "2×2"}
# 연구자가 편집하는 단계 / 코드가 만드는 단계(확인만)
EDITABLE = {"prototype", "qtpp", "cqa", "rm_just", "fp_just", "design", "regression", "space", "vplan", "verify"}
DERIVED = {"rm_matrix", "fp_matrix", "recommend", "surface", "anova"}
LLM_STEPS = {"qtpp", "cqa", "rm_just", "fp_just"}
LEVELS = ("High", "Medium", "Low")
BASIS = ("처방 자료", "약전·가이드라인", "일반 제제학 지식", "문헌(출처 기재)", "추정 — 확인 필요")
MAX_FACTORS, MAX_RESPONSES = 3, 4

Level = Literal["High", "Medium", "Low"]
Basis = Literal["처방 자료", "약전·가이드라인", "일반 제제학 지식", "문헌(출처 기재)", "추정 — 확인 필요"]


# ── LLM 출력 스키마 ───────────────────────────────────────────────────────────
class QTPPItemOut(BaseModel):
    element: str = Field(description="QTPP 요소(제형/설계, 투여 경로, 함량, 약동학, 안정성, 제품 품질특성, 용기·마개)")
    sub_element: Optional[str] = Field(None, description="제품 품질특성의 하위 항목(물리적 특성·확인·함량 등), 아니면 null")
    target: str = Field(description="목표. 근거 없는 제품 고유 수치를 만들지 말고, 모르면 '미정 — 연구자 입력'")
    justification: str
    basis: Basis


class QTPPOut(BaseModel):
    items: List[QTPPItemOut]


class CQAItemOut(BaseModel):
    category: str = Field(description="분류(예: Physical attributes), 없으면 빈 문자열")
    attribute: str
    short: str = Field(description="위험평가 표의 표준 영문 짧은 이름(Assay, Content uniformity, Hardness, …)")
    target: str
    is_cqa: bool
    justification: str = Field(description="CQA 여부의 논리적 근거(허용 범위를 벗어나면 안전성·유효성에 영향을 주는가)")
    in_risk_assessment: bool
    exclusion_reason: Optional[str] = None
    basis: Basis


class CQAOut(BaseModel):
    items: List[CQAItemOut]


class JustItemOut(BaseModel):
    variable: str
    cqas: List[str] = Field(description="같은 판단을 공유하는 CQA 묶음")
    level: Level
    text: str = Field(description="그 변수가 그 CQA들에 왜 그 수준의 위험인지 기전 설명. 끝에 '위험은 높다/중간이다/낮다.'")
    basis: Basis


class JustVarOut(BaseModel):
    name: str
    kind: Literal["material", "formulation", "process"]


class JustOut(BaseModel):
    variables: List[JustVarOut]
    items: List[JustItemOut]


# ── 검사 ────────────────────────────────────────────────────────────────────
def _c(level: str, code: str, msg: str, **kw) -> Dict[str, Any]:
    return {"level": level, "code": code, "message": msg, **kw}


def risk_cqas(cqa: Optional[Dict[str, Any]]) -> List[str]:
    return [c["short"] for c in (cqa or {}).get("items", []) if c.get("in_risk_assessment")]


def matrix_of(just: Dict[str, Any], cqas: List[str]) -> Dict[str, Any]:
    """근거 표 → 위험 행렬(행 = CQA, 열 = 변수). 칸마다 그 칸을 덮은 근거의 등급."""
    vars_ = just.get("variables") or []
    cell = {}
    for it in just.get("items") or []:
        for c in it.get("cqas") or []:
            cell[(it.get("variable"), c)] = it.get("level")
    return {"cqas": list(cqas), "variables": [dict(v) for v in vars_],
            "levels": [[cell.get((v["name"], c)) for v in vars_] for c in cqas]}


def check(step: str, data: Dict[str, Any], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if data is None:
        return [_c("blocking", "EMPTY", "내용이 없습니다.")]
    if step == "prototype":
        ings = data.get("ingredients") or []
        if not any(i.get("role") == "api" for i in ings):
            out.append(_c("blocking", "PROTO_NO_API", "주성분(role = api) 행이 없습니다."))
        if not ings or any(not str(i.get("name") or "").strip() for i in ings):
            out.append(_c("blocking", "PROTO_NAME", "성분 이름이 비어 있습니다."))
        tot = sum(float(i.get("pct") or 0) for i in ings)
        if ings and all(i.get("pct") is not None for i in ings) and abs(tot - 100) > 0.5:
            out.append(_c("warning", "PROTO_SUM", f"조성 합이 {tot:.2f}%입니다."))
    elif step == "qtpp":
        items = data.get("items") or []
        if not items:
            out.append(_c("blocking", "QTPP_EMPTY", "QTPP 요소가 없습니다."))
        for n, it in enumerate(items):
            if not str(it.get("element") or "").strip() or not str(it.get("target") or "").strip():
                out.append(_c("blocking", "QTPP_FIELD", f"{n + 1}행: 요소와 목표가 필요합니다.", row=n))
    elif step == "cqa":
        items = data.get("items") or []
        if not items:
            out.append(_c("blocking", "CQA_EMPTY", "품질특성이 없습니다."))
        for n, c in enumerate(items):
            name = c.get("attribute") or f"{n + 1}행"
            if not str(c.get("attribute") or "").strip():
                out.append(_c("blocking", "CQA_FIELD", f"{n + 1}행: 품질특성 이름이 없습니다.", row=n))
            if not str(c.get("justification") or "").strip():
                out.append(_c("blocking", "CQA_NO_JUST", f"{name}: CQA 여부의 근거가 없습니다.", row=n))
            if c.get("in_risk_assessment") and not c.get("is_cqa"):
                out.append(_c("blocking", "CQA_RISK_NOT_CQA", f"{name}: CQA가 아닌 항목은 위험평가에 넣지 않습니다.", row=n))
            if c.get("is_cqa") and not c.get("in_risk_assessment") and not str(c.get("exclusion_reason") or "").strip():
                out.append(_c("blocking", "CQA_EXCLUDE_REASON", f"{name}: CQA를 위험평가에서 빼는 이유가 필요합니다.", row=n))
        shorts = risk_cqas(data)
        if not shorts:
            out.append(_c("blocking", "CQA_NONE_IN_RISK", "위험평가에 넣을 CQA가 하나도 없습니다."))
        if len(set(shorts)) != len(shorts) or any(not s for s in shorts):
            out.append(_c("blocking", "CQA_SHORT", "위험평가 CQA의 짧은 이름은 비어 있지 않고 서로 달라야 합니다."))
    elif step in ("rm_just", "fp_just"):
        cqas = risk_cqas(ctx.get("cqa"))
        vars_ = data.get("variables") or []
        names = [str(v.get("name") or "").strip() for v in vars_]
        if not names:
            out.append(_c("blocking", "RISK_NO_VARS", "평가할 변수가 없습니다."))
        if len(set(names)) != len(names) or any(not x for x in names):
            out.append(_c("blocking", "RISK_VAR_NAMES", "변수 이름은 비어 있지 않고 서로 달라야 합니다."))
        seen: Dict[tuple, int] = {}
        for n, it in enumerate(data.get("items") or []):
            if not str(it.get("text") or "").strip():
                out.append(_c("blocking", "JUST_EMPTY", f"{it.get('variable') or n + 1}: 근거 문장이 없습니다.", row=n))
            if it.get("level") not in LEVELS:
                out.append(_c("blocking", "JUST_LEVEL", f"{it.get('variable') or n + 1}: 위험 등급(High·Medium·Low)이 없습니다.", row=n))
            if it.get("variable") not in names:
                out.append(_c("blocking", "JUST_UNKNOWN_VAR", f"{n + 1}행: 변수 목록에 없는 변수({it.get('variable')}).", row=n))
            for c in it.get("cqas") or []:
                if c not in cqas:
                    out.append(_c("blocking", "JUST_UNKNOWN_CQA", f"{n + 1}행: 확정 CQA가 아닌 항목({c}).", row=n))
                    continue
                seen[(it.get("variable"), c)] = seen.get((it.get("variable"), c), 0) + 1
        miss = [(v, c) for v in names for c in cqas if (v, c) not in seen]
        dup = [k for k, v in seen.items() if v > 1]
        if miss:
            out.append(_c("blocking", "JUST_MISSING", "근거가 없는 칸: " + ", ".join(f"{a} × {b}" for a, b in miss[:12])
                          + (f" 외 {len(miss) - 12}칸" if len(miss) > 12 else "")))
        if dup:
            out.append(_c("blocking", "JUST_DUPLICATE", "근거가 두 번 이상인 칸: " + ", ".join(f"{a} × {b}" for a, b in dup[:12])))
        if step == "fp_just":
            proto = ctx.get("prototype") or {}
            exc = [i["name"] for i in proto.get("ingredients", []) if i.get("role") != "api"]
            missing = [e for e in exc if e not in names]
            if missing:
                out.append(_c("blocking", "RISK_EXCIPIENT_MISSING", f"처방의 모든 부형제를 평가해야 합니다 — 빠짐: {', '.join(missing)}."))
            route = {str(proto.get("process") or "").lower(), "direct_compression", "direct compression", "wet_granulation", "wet granulation",
                     "dry_granulation", "dry granulation", "직접타정", "습식과립", "건식과립"} - {""}
            bad = [v["name"] for v in vars_ if v.get("kind") == "process" and str(v.get("name") or "").strip().lower() in route]
            if bad:
                out.append(_c("blocking", "RISK_PROCESS_IS_ROUTE", f"공정 변수 자리에 공정 이름이 있습니다({', '.join(bad)}) — 압축력·혼합 시간처럼 조절 가능한 공정 파라미터로 바꾸세요."))
            if not any(v.get("kind") == "process" for v in vars_):
                out.append(_c("warning", "RISK_NO_PROCESS", "공정 변수가 없습니다 — 압축력 같은 공정 파라미터도 평가하는지 확인하세요."))
            pct = low_dose(ctx)
            if pct is not None:
                blend_hi = any(BLEND_RE.search(str(it.get("variable") or "")) and it.get("level") == "High"
                               and any(CU_RE.search(c) for c in it.get("cqas") or []) for it in data.get("items") or [])
                if not blend_hi:
                    out.append(_c("warning", "RISK_LOW_DOSE", f"약물 함량 {pct:.1f} %(< 5 %, RTE008) — 혼합 공정(혼합 시간 등) × 함량균일성 위험을 "
                                  "High로 평가했는지 확인하세요. 저함량 API는 혼합 균일성이 함량균일성을 좌우합니다."))
    elif step == "recommend":
        if not data.get("candidates"):
            out.append(_c("warning", "RISK_NO_HIGH", "High인 제형·공정 변수가 없습니다 — 실험 설계(9단계)의 요인은 위험평가 근거를 보고 정하세요."))
    elif step == "design":
        f, r, rows = data.get("factors") or [], data.get("responses") or [], data.get("rows") or []
        if not 1 <= len(f) <= MAX_FACTORS:
            out.append(_c("blocking", "DESIGN_FACTORS", f"요인은 1–{MAX_FACTORS}개입니다."))
        if not 1 <= len(r) <= MAX_RESPONSES:
            out.append(_c("blocking", "DESIGN_RESPONSES", f"반응은 1–{MAX_RESPONSES}개입니다."))
        if any(not str(x.get("name") or "").strip() for x in f + r):
            out.append(_c("blocking", "DESIGN_NAMES", "요인·반응 이름을 모두 적어 주세요."))
        bad = [n + 1 for n, row in enumerate(rows) if any(not _isnum(v) for v in (row.get("x") or [])) or len(row.get("x") or []) != len(f)]
        if bad:
            out.append(_c("blocking", "DESIGN_X", f"요인 값이 비었거나 숫자가 아닌 행: {', '.join(map(str, bad[:15]))}."))
        bady = [n + 1 for n, row in enumerate(rows) if len(row.get("y") or []) != len(r) or any(v not in (None, "") and not _isnum(v) for v in row.get("y") or [])]
        if bady:
            out.append(_c("blocking", "DESIGN_Y", f"반응 값이 숫자가 아닌 행: {', '.join(map(str, bady[:15]))}."))
        k = len(f)
        need = k + 2
        for j, resp in enumerate(r):
            n = sum(1 for row in rows if j < len(row.get("y") or []) and _isnum(row["y"][j]))
            if n < need:
                out.append(_c("blocking", "DESIGN_TOO_FEW", f"{resp.get('name') or f'반응 {j + 1}'}: 값이 있는 run이 {n}개 — 최소 {need}개(선형 모형 + 잔차 자유도 1)가 필요합니다."))
        for i, fac in enumerate(f):
            vals = {float(row["x"][i]) for row in rows if i < len(row.get("x") or []) and _isnum(row["x"][i])}
            if len(vals) < 2:
                out.append(_c("blocking", "DESIGN_ONE_LEVEL", f"{fac.get('name') or f'요인 {i + 1}'}: 서로 다른 수준이 2개 이상이어야 합니다."))
        runs = [row.get("run") for row in rows]
        if any(not _isnum(x) for x in runs) or len({float(x) for x in runs if _isnum(x)}) != len(runs):
            out.append(_c("warning", "DESIGN_RUN_ORDER", "Run order가 비었거나 겹칩니다 — 실제 실행 순서를 적어 두면 추적이 쉽습니다."))
    elif step == "regression":
        g = rules_gate_text()
        passed = 0
        for r in data.get("responses") or []:
            if r.get("aliased"):
                out.append(_c("blocking", "REG_ALIASED", f"{r['response']}: {r['family']} 모형은 이 설계로 추정할 수 없습니다(항 수 ≥ run 수 또는 별칭) — 다른 모형을 고르세요."))
                continue
            if r["summary"]["suggested"] != r["family"]:
                out.append(_c("warning", "REG_NOT_SUGGESTED", f"{r['response']}: 제안 모형은 {r['summary']['suggested']}, 선택은 {r['family']} — 연구자 선택으로 기록합니다."))
            if r.get("status", "SELECTED") == "SELECTED":
                passed += 1
            else:
                why = "; ".join((r.get("gate") or {}).get("why") or []) or "평균 모형"
                out.append(_c("warning", "REG_GATE_FAIL", f"{r['response']}: 검증 게이트 불합격({why}) — 요인으로 설명되지 않음: 회귀식·곡면·영역에 쓰지 않고 "
                              "관측 범위와 목표만 표시합니다.", response=r["response"]))
        if data.get("responses") and not passed:
            out.append(_c("blocking", "REG_GATE_NONE", f"모든 반응의 회귀식이 검증 게이트({g})를 통과하지 못했습니다 — 영역을 그릴 회귀식이 없어 승인할 수 없습니다."))
    elif step == "space":
        specs = data.get("specs") or []
        for s in specs:
            op = s.get("op")
            if op in (None, "", "NONE"):
                continue
            need = {"LE": ("upper",), "GE": ("lower",), "BETWEEN": ("lower", "upper")}.get(op)
            if not need or any(not _isnum(s.get(k)) for k in need):
                out.append(_c("blocking", "SPACE_SPEC", f"{s.get('response')}: 목표 값이 비었거나 숫자가 아닙니다."))
            elif op == "BETWEEN" and float(s["lower"]) >= float(s["upper"]):
                out.append(_c("blocking", "SPACE_SPEC", f"{s.get('response')}: 하한이 상한보다 작아야 합니다."))
        reg = data.get("region") or {}
        if not reg or reg.get("status") == "NO_SPEC":
            out.append(_c("blocking", "SPACE_NO_SPEC", "게이트 통과 반응의 목표를 하나 이상 적어야 영역을 계산합니다(반응마다 ≤ · ≥ · 범위)."))
        else:
            ap = reg.get("approval") or {}
            # 13단계 승인 불가는 두 경우뿐 — 평균 기준 영역 없음 · control space를 만들 수 없음(공동확률은 보조 표시)
            if ap.get("code") in ("SPACE_NO_MEAN_REGION", "SPACE_NO_CONTROL", "SPACE_NO_GATE"):
                out.append(_c("blocking", ap["code"], ap["reason"]))
            aux = reg.get("aux") or {}
            if ap.get("approvable") and aux.get("max_joint") is not None and aux["max_joint"] < 0.9:
                out.append(_c("warning", "SPACE_AUX_LOW", f"보조 지표: 새 배치가 모든 목표를 만족할 확률이 영역 안에서 최대 {aux['max_joint']:.3f}(< 0.9) — "
                              "여유가 적습니다. 승인은 막지 않습니다."))
            for nt in reg.get("unexplained") or []:
                if nt.get("level") == "warn":
                    out.append(_c("warning", "SPACE_UNEXPLAINED", nt["text"], response=nt["response"]))
    elif step == "vplan":
        roles = [p["role"] for p in (data.get("plan") or {}).get("points") or []]
        if "SETPOINT" not in roles:
            out.append(_c("blocking", "VPLAN_NONE", "확인점을 만들 수 없습니다 — 13단계에서 영역이 있어야 합니다."))
        elif len([r for r in roles if r != "REFERENCE"]) < 3:
            out.append(_c("warning", "VPLAN_FEW", "필수 확인점 3개 중 일부를 만들 수 없었습니다(경계·강건성 점이 지지 영역 밖)."))
    elif step == "verify":
        if not data.get("independent"):
            out.append(_c("blocking", "VERIFY_INDEPENDENT", "확인배치가 모형 적합에 쓰지 않은 새 독립 배치인지 확인해 주세요."))
        j = data.get("judgement") or {}
        if j.get("verdict") in (None, "INCOMPLETE"):
            out.append(_c("blocking", "VERIFY_MISSING", "필수 확인점 3개의 모든 반응 실측값이 필요합니다."))
        elif j.get("verdict") == "INVALIDATED":
            out.append(_c("warning", "VERIFY_INVALIDATED", "확인 실패 — 승인하면 '영역 무효화'로 기록됩니다. " + " ".join(j.get("advice") or [])))
    return out


def rules_gate_text() -> str:
    from formula.stage2.doe import rules
    g = rules()["gate"]
    return (f"모형 p < {g['model_p_max']:g} · 적합결여 p ≥ {g['lack_of_fit_p_min']:g} · 조정 R² − 예측 R² ≤ {g['adj_minus_pred_r2_max']:g} · "
            f"예측 R² > {g['pred_r2_min']:g}")


def numbers_not_in(text: str, source: str) -> List[str]:
    """LLM 문장 속 수치 중 입력(프로토타입·승인본)에 없는 것 — 경고용(출처 확인 필요). 한 자리 수는 문장 속 서수가 많아 뺀다."""
    import re
    src = set(re.findall(r"\d+(?:\.\d+)?", source))
    return sorted({x for x in re.findall(r"\d+(?:\.\d+)?", text or "") if x not in src and not re.fullmatch(r"[0-9]", x)})


def _isnum(v: Any) -> bool:
    try:
        return v not in (None, "") and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _rated(matrix: Dict[str, Any], min_level: str) -> List[Dict[str, Any]]:
    out = []
    for j, v in enumerate(matrix.get("variables") or []):
        hi = [c for i, c in enumerate(matrix["cqas"]) if matrix["levels"][i][j] == "High"]
        md = [c for i, c in enumerate(matrix["cqas"]) if matrix["levels"][i][j] == "Medium"]
        if hi or (md and min_level == "Medium"):
            out.append({"variable": v["name"], "kind": v.get("kind"), "high": hi, "medium": md})
    return sorted(out, key=lambda x: (-len(x["high"]), -len(x["medium"])))


def candidates(fp_matrix: Dict[str, Any]) -> List[Dict[str, Any]]:
    """DoE 후보 = 제형·공정 변수 중 하나 이상의 CQA에 High인 것(발표 자료: 'High만 DoE 요인으로'). High 개수 → Medium 개수 순."""
    return _rated(fp_matrix, "High")


def watch_list(fp_matrix: Dict[str, Any]) -> List[Dict[str, Any]]:
    """High는 없고 Medium만 있는 변수 — DoE 요인은 아니지만 관리·모니터링 대상으로 보여 준다."""
    return [c for c in _rated(fp_matrix, "Medium") if not c["high"]]


def material_controls(rm_matrix: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _rated(rm_matrix, "Medium")


LOW_DOSE_PCT = 5.0          # RTE008(route_decision_tree.csv) — 약물 함량 < 5 %면 함량균일성이 관건
BLEND_RE = re.compile(r"blend|mix|혼합", re.I)
CU_RE = re.compile(r"uniform|균일", re.I)


def low_dose(ctx: Dict[str, Any]) -> Optional[float]:
    """프로토타입에서 계산한 약물 함량(%). 5 % 미만이면 값, 아니면 None."""
    p = ctx.get("prototype") or {}
    api = next((i for i in p.get("ingredients") or [] if i.get("role") == "api"), None)
    tot = sum(float(i.get("mg") or 0) for i in p.get("ingredients") or []) or float(p.get("unit_weight_mg") or 0)
    if not api or not api.get("mg") or not tot:
        return None
    pct = 100 * float(api["mg"]) / tot
    return pct if pct < LOW_DOSE_PCT else None
