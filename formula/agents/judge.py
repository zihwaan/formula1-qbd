"""심사 에이전트 (Agent 3) — 동적으로 소집되는 정성 판단자.

`reviewer_registry.csv`의 `summon_condition`이 참인 심사관만 그 자리에서 생성된다.
고정 명단이 없다는 점이 이 시스템의 '자기조직형' 성격을 만든다.

**심사관은 반려 권한이 없다**(`can_block = no`, `score_affects_pass_fail = false`).
점수는 통과 후보들 사이의 순위 결정에만 쓰인다. 안전 판정은 전적으로 룰북이 담당한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from formula.agents.client import LLMUnavailable, load_prompt, stream_text
from formula.contracts import (
    EventKind,
    FormulationSpec,
    JudgeSpec,
    JudgeVerdict,
    Recipe,
    Verdict,
)
from formula.orchestrator.events import emit
from formula.rag.store import get_store

SYSTEM_BASE = """당신은 제형 설계 심사위원단의 한 명이다.

중요 — 당신의 권한 범위:
- 당신은 후보를 **반려시킬 수 없다.** 안전·규제 판정은 이미 결정론적 룰북이 끝냈다.
- 당신이 하는 일은 룰북을 통과한 후보들 사이의 **상대적 우수도 평가**뿐이다.
- 점수는 0.0~1.0. 0.5가 '평범', 0.8 이상은 '이 도메인에서 확실히 우수'를 뜻한다.
- rationale에는 근거를 2~4문장으로 쓴다. 제공된 근거 문서를 인용하면 citations에 doc_id를 넣는다.
- 룰북이 못 잡았다고 판단되는 위험이 보이면 suggestion에 적는다 — 그것이 룰북 보강의 단서가 된다."""


class JudgeOutput(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    rationale: str
    suggestion: str = ""
    citations: List[str] = Field(default_factory=list)


def evaluate(
    judge: JudgeSpec,
    spec: FormulationSpec,
    recipe: Recipe,
    verdicts: List[Verdict],
    base_dir: Path,
) -> JudgeVerdict:
    """심사관 1명이 후보 1건을 평가한다. 토큰은 실시간으로 UI에 흘린다."""
    node = f"judge:{judge.reviewer_id or judge.persona}"
    emit(node, EventKind.JUDGE_SUMMONED,
         reviewer_id=judge.reviewer_id, persona=judge.persona,
         weight=judge.weight, summon_condition=judge.summon_condition,
         candidate_id=recipe.candidate_id)

    rubric = load_prompt(base_dir, judge.rubric_prompt or "", fallback="")
    store = get_store(base_dir)
    evidence = store.context_for(
        f"{judge.retrieval_namespace} {spec.api_name} {recipe.strategy} "
        + " ".join(i.name for i in recipe.ingredients), k=4)

    flagged = [v for v in verdicts if v.failed]
    flagged_text = "\n".join(
        f"- [{v.status.value}] {v.rulebook_id}/{v.rule_id}: {v.reason}" for v in flagged
    ) or "(룰북 지적 사항 없음)"

    system_suffix = f"\n\n## 당신의 역할\n{judge.persona}\n\n{rubric}".rstrip()
    user = f"""## 평가 대상 후보
전략: {recipe.strategy}
공정: {recipe.process} · 포장: {recipe.packaging}
성분:
""" + "\n".join(
        f"  - {i.name} ({i.role}) {i.amount_mg}mg / {i.percent}%" for i in recipe.ingredients
    ) + f"""

설계 근거: {recipe.rationale}

## 스펙
API {spec.api_name} · 대상 {spec.target_patient} · 제형 {spec.dosage_form}
구조 플래그: {', '.join(spec.api_functional_groups) or '(없음)'}

## 룰북이 남긴 지적(반려는 아님)
{flagged_text}

## 참고 근거
{evidence}

당신의 도메인 관점에서 이 후보의 상대적 우수도를 평가하라."""

    try:
        def on_delta(text: str) -> None:
            emit(node, EventKind.JUDGE_TOKEN, reviewer_id=judge.reviewer_id,
                 candidate_id=recipe.candidate_id, delta=text)

        # 구조화 출력과 스트리밍을 함께 쓰기 위해, 근거는 스트리밍으로 보여주고
        # 최종 점수만 스키마로 다시 받는다(UI 체감 + 파싱 안정성 양립).
        narration = stream_text(SYSTEM_BASE, user, on_delta=on_delta,
                                system_suffix=system_suffix, effort="medium")
        from formula.agents.client import parse_structured

        output = parse_structured(
            JudgeOutput, SYSTEM_BASE,
            f"{user}\n\n## 당신이 방금 작성한 심사 소견\n{narration}\n\n이 소견을 점수로 정리하라.",
            system_suffix=system_suffix, effort="low",
        )
        source = "llm"
    except LLMUnavailable as exc:
        output = _fallback(flagged)
        source = "deterministic-fallback"
        emit(node, EventKind.WARNING, reason=str(exc), fallback=True)

    verdict = JudgeVerdict(
        rulebook_id=recipe.candidate_id,   # 후보 기준으로 집계하므로 candidate_id를 키로 쓴다
        reviewer_id=judge.reviewer_id,
        persona=judge.persona,
        score=output.score,
        passed=output.score >= judge.pass_threshold,
        weight=judge.weight,
        rationale=output.rationale,
        suggestion=output.suggestion,
        citations=output.citations,
    )
    emit(node, EventKind.JUDGE_VERDICT, source=source, **verdict.model_dump())
    return verdict


def _fallback(flagged: List[Verdict]) -> JudgeOutput:
    """LLM 없이 만드는 점수 — 룰북 지적 건수에 반비례하는 단순 규칙.

    시연 안전장치이지 실제 심사가 아니므로 rationale에 그 사실을 명시한다.
    """
    penalty = min(0.1 * len(flagged), 0.5)
    return JudgeOutput(
        score=round(0.75 - penalty, 3),
        rationale=f"[결정론 폴백] LLM 미사용. 룰북 지적 {len(flagged)}건을 감점 요인으로 반영한 기본 점수.",
        suggestion="실제 심사 소견을 얻으려면 ANTHROPIC_API_KEY를 설정하고 재실행할 것.",
    )
