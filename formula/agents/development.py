"""ExperimentalDevelopmentGraph의 LLM 제안 에이전트 — 명세 v6.1 §3.3(FMEA 가설)·§3.9(진단)·§3.10(Reflection).

권한은 명세 §2.1 표 그대로다. 이 에이전트들은
- 수치를 만들지 않는다 (S/O/D·수준값·계수·확률 필드가 스키마에 아예 없다),
- 근거 등급을 바꾸지 못한다 (출력은 무조건 `LLM_HYPOTHESIS`로 태그된다 — AA005),
- 존재하지 않는 CQA·요인·시험을 쓰면 서비스가 그 항목을 버린다.

LLM이 없거나 토큰 예산을 못 받으면 **가설을 만들지 않는다.** 틀에 박힌 문장을 가설처럼 채우지 않고,
`generated_by = "unavailable"`로 "LLM 응답 없음"을 그대로 알린다 — 판단은 연구자와 seed 행으로 이어진다.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from formula.agents.client import LLMUnavailable, parse_structured

WAIT = 25.0   # 사용자가 버튼을 누르고 기다리는 요청 — 길게 기다리지 않고 대체로 내려간다


class FmeaHypothesis(BaseModel):
    cause: str
    failure_mode: str
    local_effect: str
    cqa_effect: List[str] = Field(description="아래 목록에 있는 cqa_id만")
    candidate_factor: str = Field("", description="아래 요인 어휘 중 하나, 없으면 빈 문자열")
    rationale: str = Field(description="처방 조성·공정의 어떤 사실에서 나온 가설인지")
    missing_evidence: str = Field("", description="이 가설을 확인하려면 필요한 자료")


class FmeaHypotheses(BaseModel):
    hypotheses: List[FmeaHypothesis] = Field(default_factory=list, max_length=4)


FMEA_SYSTEM = """당신은 경구 고형제 QbD의 FMEA 검토자다. 이미 seed FMEA 행이 있다.
당신의 일은 seed에 **없는** 실패 원인 가설을 최대 4개 제안하는 것뿐이다.
- 숫자(S/O/D 점수, 범위, 확률)를 쓰지 않는다. 필드에도 없다.
- cqa_effect에는 주어진 cqa_id만 쓴다. candidate_factor는 주어진 요인 어휘만 쓴다.
- 처방 조성·공정의 구체적 사실에 근거하라. 근거가 없으면 제안하지 않는다(빈 배열 허용).
- seed 행을 다른 말로 반복하지 않는다."""


def fmea_hypotheses(handoff: Dict[str, Any], cqas: Dict[str, Dict[str, Any]], seed_rows: List[Dict[str, Any]],
                    vocab: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    applicable = {k: v["name"] for k, v in cqas.items() if v["analysis_role"] != "NOT_APPLICABLE"}
    comp = ", ".join(f"{i['name']}({i.get('role')}, {i.get('pct_w_w')}%)" for i in handoff["ingredients"])
    seeds = "\n".join(f"- {r['cause']} → {r['failure_mode']} → {', '.join(r['cqa_effect'])}" for r in seed_rows)
    user = (f"## 처방\n{comp}\n공정: {handoff.get('process_route_id')}\n\n## CQA\n"
            + "\n".join(f"- {k}: {v}" for k, v in applicable.items())
            + "\n\n## 요인 어휘\n" + ", ".join(vocab) + f"\n\n## 이미 있는 seed 행\n{seeds}")
    try:
        out = parse_structured(FmeaHypotheses, FMEA_SYSTEM, user, effort="low", max_tokens=1200,
                               wait_budget=WAIT)
        items, by = out.hypotheses, "llm"
    except LLMUnavailable:
        items, by = [], "unavailable"
    rows = []
    for n, h in enumerate(items):
        effect = [c for c in h.cqa_effect if c in applicable]
        if not effect:
            continue   # 존재하지 않는 CQA만 가리키는 가설은 버린다
        factor = h.candidate_factor if h.candidate_factor in vocab else ""
        rows.append({
            "row_id": f"H{n + 1:02d}", "seed_id": None, "unit_op_code": None, "risk_category": "HYPOTHESIS",
            "cause": h.cause, "failure_mode": h.failure_mode, "local_effect": h.local_effect,
            "cqa_effect": effect, "candidate_factors": [factor] if factor else [],
            "kind": vocab.get(factor, {}).get("kind"), "severity": None, "occurrence": None,
            "occurrence_evidence": None, "detectability": None, "detection_method_ids": [],
            "detect_note": h.missing_evidence or "판별 자료 필요", "rpn": None,
            "disposition": "REQUEST_DATA", "evidence_status": "LLM_HYPOTHESIS",
            "hypothesis_status": "PROPOSED", "rationale": h.rationale, "alternative_control": None,
            "approval_ref": None, "deleted": False, "origin": "LLM_HYPOTHESIS",
        })
    return {"rows": rows, "generated_by": by}


class Hypothesis(BaseModel):
    statement: str
    distinguishing_test: str = Field(description="이 가설을 다른 가설과 갈라낼 시험 (아래 목록의 test_id)")
    expected_pattern: str
    cannot_exclude_yet: bool = True


class Diagnosis(BaseModel):
    hypotheses: List[Hypothesis] = Field(default_factory=list, max_length=3)
    directive: str = Field(description="DOE_AUGMENT | FACTOR_RANGE_REVISION | METHOD_PROCESS_CONTROL | CANDIDATE_REVISION")
    directive_reason: str


DIAG_SYSTEM = """당신은 QbD 개발 진단 담당이다. 확인배치·결과 품질 게이트가 실패했다.
- 서로 **다른** 원인가설을 최대 3개 세운다. 같은 원인을 바꿔 말한 가설은 금지.
- 각 가설에는 갈라낼 시험을 주어진 test_id 목록에서만 고른다.
- override 이력과 EXPERT_ASSUMPTION 근거를 우선 점검 대상으로 포함한다.
- directive는 네 가지 중 하나만. 수치(계수, 범위, 확률)를 새로 만들지 않는다."""

DIRECTIVES = ("DOE_AUGMENT", "FACTOR_RANGE_REVISION", "METHOD_PROCESS_CONTROL", "CANDIDATE_REVISION")


def diagnose(trigger: Dict[str, Any], overrides: List[Dict[str, Any]], assumptions: List[str],
             tests: List[Dict[str, str]]) -> Dict[str, Any]:
    ids = {t["test_id"] for t in tests}
    listing = "\n".join(f"- {t['test_id']}: {t.get('name', '')}" for t in tests[:40])
    user = (f"## 실패 신호\n{trigger}\n\n## override 이력\n{overrides or '없음'}\n\n"
            f"## EXPERT_ASSUMPTION 근거\n{assumptions or '없음'}\n\n## 선택 가능한 시험\n{listing}")
    try:
        d = parse_structured(Diagnosis, DIAG_SYSTEM, user, effort="low", max_tokens=1200, wait_budget=WAIT)
        by = "llm"
    except LLMUnavailable:
        # 가설도 방향 제안도 만들지 않는다 — 연구자가 판별시험 목록과 실패 신호를 보고 직접 고른다
        return {"hypotheses": [], "directive": None, "directive_reason": "LLM 응답 없음 — 방향 제안 없음",
                "generated_by": "unavailable", "status": "PROPOSED", "evidence_status": "LLM_HYPOTHESIS"}
    hyps = [h.model_dump() for h in d.hypotheses if h.distinguishing_test in ids]
    directive = d.directive if d.directive in DIRECTIVES else None
    return {"hypotheses": hyps, "directive": directive, "directive_reason": d.directive_reason,
            "generated_by": by, "status": "PROPOSED", "evidence_status": "LLM_HYPOTHESIS"}
