"""2단계 LLM 초안 — 판정이 아니라 연구자가 고칠 초안이다. 응답이 없으면 아무것도 채우지 않는다(가짜 표 금지).

위험평가 근거(4·6단계)는 두 번에 나눠 받는다: ① 변수 × CQA 등급 격자 ② 코드가 만든 '변수 × 같은 등급 CQA' 묶음마다 기전 문장.
그래서 모든 칸이 정확히 한 번, 격자와 같은 등급으로 덮인다(LLM이 칸을 빠뜨리거나 등급을 어긋나게 쓸 수 없다).
"""
from __future__ import annotations

import re

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from formula.agents.client import LLMUnavailable, parse_structured, providers
from formula.stage2.model import BASIS, MAX_DOE, CQAOut, Level, QTPPOut, RecOut, risk_cqas

WAIT = 90.0
COMMON = f"""너는 제형 개발 QbD(ICH Q8(R2)·Q9) 초기 위험평가 초안을 쓰는 제제학자다. 연구자가 검토·수정·승인한다.
- 한국어로 쓴다. 약전·가이드라인(USP <905> 등)과 원료·부형제 이름은 원문 표기를 쓴다.
- 입력에 없는 실측값·제품 고유 수치를 지어내지 않는다. 공개 약전 규격처럼 확립된 기준만 수치로 쓰고, 모르면 '미정 — 연구자 입력'.
  문헌 번호·DOI를 만들어 인용하지 않는다. 약전 조항은 실제로 다루는 내용일 때만 인용한다(<905> 제제균일성, <701> 붕해, <711> 용출,
  <1216> 마손도, <1217> 경도 — 외관·냄새의 근거가 아니다).
- basis는 다음 중 하나: {' | '.join(BASIS)}. 확신이 없으면 '추정 — 확인 필요'."""


class _Var(BaseModel):
    name: str
    kind: Literal["material", "formulation", "process"]


class _Row(BaseModel):
    cqa: str
    levels: List[Level] = Field(description="variables 순서대로의 위험 등급")


class _Grid(BaseModel):
    variables: List[_Var]
    rows: List[_Row]


class _Text(BaseModel):
    group: int
    text: str = Field(description="그 변수가 그 CQA들에 왜 그 수준의 위험인지 기전 설명(등급을 되풀이하는 문장 금지). 끝에 '위험은 높다/중간이다/낮다.'")
    basis: Literal["처방 자료", "약전·가이드라인", "일반 제제학 지식", "문헌(출처 기재)", "추정 — 확인 필요"]


class _Texts(BaseModel):
    items: List[_Text]


def _proto(p: Dict[str, Any]) -> str:
    ing = "\n".join(f"- {i['name']}: {i.get('mg')} mg ({i.get('pct')}%) — {i.get('function') or i.get('role')}" for i in p.get("ingredients", []))
    return (f"주성분: {p.get('api')} {p.get('strength_mg') or ''} mg · 제형: {p.get('dosage_form')} · 투여: {p.get('route')} · "
            f"공정: {p.get('process')} · 정제 중량: {p.get('unit_weight_mg')} mg\n성분:\n{ing}"
            + (f"\n공정 단계: {' → '.join(p['process_steps'])}" if p.get("process_steps") else ""))


def _ctx(ctx: Dict[str, Any]) -> str:
    """프로토타입 + 1단계에서 넘어온 요청 맥락(불변 Handoff) — 대상 환자·용량·제형 요청·1단계 신호."""
    out = "## 프로토타입\n" + _proto(ctx["prototype"])
    h = ctx.get("handoff") or {}
    if h:
        ctx_lines = [f"- 요청: {h['request']}" if h.get("request") else "",
                     f"- 대상 환자: {h['target_population']}" if h.get("target_population") else "",
                     f"- 1회 용량: {h['dose_mg']} mg" if h.get("dose_mg") is not None else "",
                     f"- 요청 제형: {h['dosage_form']}" if h.get("dosage_form") else "",
                     f"- 약물 함량: {h['drug_loading_pct']:.1f} %" if h.get("drug_loading_pct") is not None else ""]
        ctx_lines += [f"- 1단계 신호 {g['rule_id']}: {g['message']}" for g in h.get("signals") or []]
        # 근거 결손이 남은 채 넘어왔으면(연구자 사유) 그 근거는 아직 모른다 — 위험평가가 그 불확실성을 봐야 한다
        ctx_lines += [f"- 근거 결손(확인 전): {g['label']} ({g['test_id']})" for g in ((h.get("evidence") or {}).get("open") or [])[:8]]
        ctx_lines = [x for x in ctx_lines if x]
        if ctx_lines:
            out += "\n\n## 1단계에서 넘어온 맥락\n" + "\n".join(ctx_lines)
    return out


def _call(schema, system: str, user: str, max_tokens: int):
    """무료 모델은 긴 JSON에서 가끔 400(json_validate_failed)을 낸다 — 한 번만 다시 묻는다."""
    try:
        out = parse_structured(schema, system, user, effort="low", max_tokens=max_tokens, wait_budget=WAIT)
    except LLMUnavailable:
        out = parse_structured(schema, system, user + "\n\n(형식: 스키마에 맞는 JSON 하나만)", effort="low", max_tokens=max_tokens, wait_budget=WAIT)
    return out


def groups(variables: List[Dict[str, Any]], cqas: List[str], levels: List[List[Any]]) -> List[Dict[str, Any]]:
    """격자 → 근거 묶음(변수마다 같은 등급 CQA끼리)."""
    out = []
    for j, v in enumerate(variables):
        by: Dict[str, List[str]] = {}
        for i, c in enumerate(cqas):
            by.setdefault(levels[i][j] if levels[i][j] in ("High", "Medium", "Low") else "?", []).append(c)
        for lv in ("High", "Medium", "Low", "?"):
            if by.get(lv):
                out.append({"variable": v["name"], "cqas": by[lv], "level": lv if lv != "?" else None})
    return out


def draft(step: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """반환 {data, provider}. 응답이 없으면 LLMUnavailable."""
    p = ctx["prototype"]
    prov = (providers() or ("none",))[0]
    if step == "qtpp":
        sys = COMMON + """
## 과제: QTPP(목표 제품 품질 프로파일) 표
요소: 제형/설계 · 투여 경로 · 함량 · 약동학 · 안정성 · 제품 품질특성(하위: 물리적 특성, 확인시험, 함량, 제제균일성, 붕해, 용출, 분해산물,
미생물 한도, 중금속, 잔류용매 — 제형에 맞게) · 용기·마개. 제품 품질특성의 하위 항목은 element='제품 품질특성', sub_element로 쓴다.
각 요소의 target과 justification(환자·임상·제형 목적과 연결한 이유)을 쓴다."""
        return {"data": _call(QTPPOut, sys, _ctx(ctx), 3500).model_dump(mode="json"), "provider": prov}
    if step == "cqa":
        q = "\n".join(f"- {i['element']}{(' / ' + i['sub_element']) if i.get('sub_element') else ''}: {i['target']}" for i in ctx["qtpp"]["items"])
        sys = COMMON + """
## 과제: 제품 품질특성 정리와 CQA 판별
QTPP의 제품 품질특성을 하나씩(외관·냄새·크기·분할선·마손도·경도 같은 물리적 특성 포함) 나열하고, 각각 CQA인지 논리적 근거와 함께 판별한다.
판별 기준(ICH Q8(R2)): 그 특성이 허용 범위를 벗어나면 환자의 안전성·유효성에 영향을 주는가. 외관·냄새·크기·분할선은 보통 안전성·유효성과 무관해
CQA가 아니다(이 제품에서 영향이 있다면 그 이유를 쓴다). 다른 CQA를 통해서만 영향을 주는 특성은 이유와 함께 판단한다.
short는 표준 영문 짧은 이름: Assay, Content uniformity, Hardness, Friability, Disintegration, Dissolution, Degradation products, Identification,
Microbial limits, Heavy metals, Residual solvents, Appearance, Odor, Size, Score configuration 등(축약어 금지).
in_risk_assessment: 제형·공정 변수가 영향을 주어 이번 초기 위험평가에서 볼 CQA만 true. CQA이지만 이번에 보지 않는 것(원료 입고 시 평가하는 확인시험,
R&D 단계에서 평가하지 않는 미생물·중금속·잔류용매 등)은 false와 exclusion_reason."""
        return {"data": _call(CQAOut, sys, _ctx(ctx) + "\n\n## 승인된 QTPP\n" + q, 4000).model_dump(mode="json"), "provider": prov}
    if step in ("rm_just", "fp_just"):
        cqas = risk_cqas(ctx["cqa"])
        cq = "\n".join(f"- {c['short']}: {c['target']}" for c in ctx["cqa"]["items"] if c.get("in_risk_assessment"))
        if step == "rm_just":
            what = "원료(주성분) 물성"
            task = """열(variables)은 주성분의 물질 특성(kind='material') — 입자크기분포, 유동성, 흡습성, 수분, 용해도, 잔류용매, 화학적 안정성 중
이 약·제형에 의미 있는 것(표준 영문: Particle size distribution, Flow properties, Hygroscopicity, Moisture content, Solubility, Residual solvents,
Chemical stability). 주성분 함량이 낮으면 혼합 균일성 관련 물성의 위험이 커진다."""
        else:
            what = "제형 변수(부형제)·공정 변수"
            exc = [i["name"] for i in p.get("ingredients", []) if i.get("role") != "api"]
            task = f"""열(variables): 처방의 모든 부형제를 빠짐없이 이 이름 그대로 kind='formulation'로({', '.join(exc)}), 그리고 핵심 공정변수를 kind='process'로.
공정변수는 공정 이름(direct_compression 등)이 아니라 조절 가능한 공정 파라미터다 — 직접타정이면 Compression force, Blending time,
Lubrication time; 습식과립이면 과립액 양·과립 시간·건조 온도 등. 사용량이 적고 기능이 해당 CQA와 무관하면 Low.
약물 함량이 5 % 미만(저함량)이면 혼합 공정(Blending time 등)이 혼합 균일성을 통해 함량균일성을 좌우한다 — 이 칸을 빠뜨리지 말고 기전으로 판단한다."""
        sys = COMMON + f"""
## 과제: {what} 초기 위험평가 — 등급 격자
{task}
행(rows)은 아래 CQA를 이 순서 그대로 전부: {', '.join(cqas)}. 각 칸은 그 변수가 그 CQA에 줄 수 있는 위험(High/Medium/Low)."""
        grid = _call(_Grid, sys, _ctx(ctx) + "\n\n## 확정 CQA\n" + cq, 2500)
        vars_ = [{"name": v.name, "kind": v.kind} for v in grid.variables]
        rows = {r.cqa: list(r.levels) for r in grid.rows}
        if step == "fp_just":            # LLM이 빠뜨린 부형제는 빈 열로 — 연구자가 채우게 한다(숨기지 않는다)
            have = {v["name"] for v in vars_}
            for e in [i["name"] for i in p.get("ingredients", []) if i.get("role") != "api" and i["name"] not in have]:
                vars_.append({"name": e, "kind": "formulation"})
                for r in rows.values():
                    r.append(None)
        levels = [rows.get(c) if rows.get(c) and len(rows[c]) == len(vars_) else [None] * len(vars_) for c in cqas]
        gs = groups(vars_, cqas, levels)
        tsys = COMMON + f"""
## 과제: {what} 초기 위험평가의 근거
아래 묶음마다(번호 그대로) 그 변수가 그 CQA들에 왜 그 수준의 위험인지 기전으로 설명한다. 예: 주성분 함량이 낮으면 입자크기·유동성이
혼합 균일성을 통해 함량·제제균일성에 직접 영향 / 사용량이 적고 기능이 무관하면 영향이 작다 / 결합제는 경도를 올려 붕해·용출에도 영향.
'High로 평가되어 위험이 높다'처럼 등급을 되풀이하는 문장은 근거가 아니다. 주어진 묶음 모두에 하나씩 쓴다."""
        texts: Dict[int, Any] = {}
        todo = [n for n, g in enumerate(gs) if g["level"]]
        for _ in range(2):                 # 8묶음씩, 빠진 묶음은 한 번 더(긴 출력에서 끝 묶음을 빠뜨린다)
            for k in range(0, len(todo), 8):
                chunk = todo[k:k + 8]
                lines = "\n".join(f"[{n}] {gs[n]['variable']} → {', '.join(gs[n]['cqas'])} : {gs[n]['level']}" for n in chunk)
                out = _call(_Texts, tsys, _ctx(ctx) + f"\n\n## 근거를 쓸 묶음\n{lines}", 2600)
                texts.update({t.group: t for t in out.items if t.group in chunk and t.text.strip()})
            todo = [n for n in todo if n not in texts]
            if not todo:
                break
        items = [{**g, "text": texts[n].text if n in texts else "", "basis": texts[n].basis if n in texts else None} for n, g in enumerate(gs)]
        return {"data": {"variables": vars_, "items": items}, "provider": prov}
    if step == "recommend":
        cands = ctx["candidates"]
        lines = "\n".join(f"- {c['variable']} ({c['kind']}): High → {', '.join(c['high']) or '없음'} / Medium → {', '.join(c['medium']) or '없음'}" for c in cands)
        sys = COMMON + f"""
## 과제: DoE로 조절해 볼 변수 추천(최대 {MAX_DOE}개)
아래는 연구자가 승인한 제형·공정 변수 위험평가에서 하나 이상의 CQA에 High인 변수다. 이 중에서만 고른다(목록 밖 이름 금지).
기준: 여러 핵심 CQA에 High인가, 실험에서 수준을 바꿀 수 있는가(연속 변수로 범위를 정할 수 있는가), 다른 변수와 역할이 겹치지 않는가
(예: 두 충전제 중 하나가 나머지를 채우는 균형 성분이면 하나만). 추천하지 않은 High 변수가 있으면 note에 이유."""
        out = _call(RecOut, sys, _ctx(ctx) + f"\n\n## 후보 변수\n{lines}", 1500)
        # 목록에 적어 준 "이름 (종류)" 형식을 그대로 돌려주는 경우가 있다 — 꼬리 괄호·대소문자만 걷어 후보 이름과 맞춘다(목록 밖은 버림)
        canon = {_key(c["variable"]): c["variable"] for c in cands}
        rec, seen, dropped = [], set(), []
        for r in out.recommended:
            name = canon.get(_key(r.variable)) or canon.get(_key(re.sub(r"\s*\([^()]*\)\s*$", "", r.variable)))
            if name is None:
                dropped.append(r.variable)
            elif name not in seen:
                seen.add(name)
                rec.append({"variable": name, "reason": r.reason})
        note = out.note + (f" (후보 목록 밖이라 뺀 이름: {', '.join(dropped)})" if dropped else "")
        return {"data": {"recommended": rec[:MAX_DOE], "note": note.strip()}, "provider": prov}
    raise KeyError(step)


def _key(name: str) -> str:
    return " ".join(str(name or "").lower().split())


__all__ = ["draft", "groups", "LLMUnavailable"]
