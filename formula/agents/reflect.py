"""반성 에이전트 — 반려 사유를 근본 원인으로 묶어 재설계 지시를 만든다.

입력은 룰북이 남긴 `reject_reason`(규칙 ID + 메커니즘 + 대안)이다. 이미 구조화된 근거가
있으므로 LLM은 "무엇이 문제였나"를 다시 추론하지 않는다 — **어떻게 고칠지**만 정리한다.

무한 루프 방지: 재설계는 최대 5회(state.MAX_REFLECTION_LOOPS). 초과하면 사람에게 이관한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, Field

from formula.agents.client import LLMUnavailable, parse_structured
from formula.contracts import EventKind, Verdict, VerdictStatus
from formula.orchestrator.events import emit

SYSTEM = """당신은 제형 설계 실패를 분석해 다음 시도의 방향을 잡는 반성 에이전트다.

- 결정론적 룰북이 이미 '무엇이 왜 걸렸는지'를 규칙 ID와 메커니즘까지 특정해 두었다.
  당신은 그 사실을 다시 판단하지 않는다. 받아들이고 **고치는 방법**을 쓴다.
- directive는 설계 에이전트에게 그대로 전달된다. 구체적인 성분·비율·공정 변경으로 적는다.
  ("유당을 만니톨로 교체" 처럼. "안정성을 개선하라" 같은 추상적 지시는 쓸모없다.)
- 여러 반려가 같은 뿌리에서 나왔다면 root_cause 하나로 묶는다."""


class Reflection(BaseModel):
    root_cause: str = Field(description="여러 반려를 관통하는 근본 원인 한 문장")
    directive: str = Field(description="설계 에이전트에게 줄 구체적 변경 지시")
    avoid: List[str] = Field(default_factory=list, description="다음 후보에서 배제할 성분·공정")


def reflect(
    failures: List[Verdict],
    base_dir: Path,
    attempt: int,
    node: str = "reflect",
) -> Dict[str, object]:
    """반려 판정 묶음 → 재설계 지시."""
    emit(node, EventKind.NODE_ENTER, attempt=attempt, failure_count=len(failures))

    blocking = [v for v in failures if v.blocking]
    considered = blocking or failures
    detail = "\n".join(
        f"- [{v.layer}/{v.rulebook_id}/{v.rule_id}] {v.reason}"
        + (f"\n    권고 대안: {v.suggestion}" if v.suggestion else "")
        for v in considered
    )

    try:
        result = parse_structured(
            Reflection, SYSTEM,
            f"## {attempt}차 시도에서 걸린 규칙\n{detail}\n\n"
            f"다음 시도를 위한 근본 원인과 변경 지시를 작성하라.",
            effort="medium",
        )
        source = "llm"
    except LLMUnavailable as exc:
        result = _fallback(considered)
        source = "deterministic-fallback"
        emit(node, EventKind.WARNING, reason=str(exc), fallback=True)

    payload = {"root_cause": result.root_cause, "directive": result.directive,
               "avoid": result.avoid, "source": source, "attempt": attempt}
    emit(node, EventKind.REFLECT, **payload)
    emit(node, EventKind.NODE_EXIT, attempt=attempt)
    return payload


def _fallback(failures: List[Verdict]) -> Reflection:
    """LLM 없이 만드는 지시 — 룰북의 suggestion 컬럼을 그대로 이어 붙인다.

    룰북이 대안(alternative_excipient 등)을 이미 담고 있어서, 폴백만으로도
    '유당 → 만니톨' 같은 실질적 재설계가 가능하다.
    """
    layers = {v.layer for v in failures} or {"unknown"}
    suggestions = [v.suggestion for v in failures if v.suggestion]
    avoid: List[str] = []
    for verdict in failures:
        evidence = verdict.evidence or {}
        for key in ("excipient", "component_set", "param"):
            value = evidence.get(key)
            if isinstance(value, str):
                avoid.append(value)
            elif isinstance(value, list):
                avoid.extend(str(v) for v in value)

    directive = "; ".join(dict.fromkeys(suggestions)) or "반려된 성분을 다른 기능군 부형제로 교체하라."
    return Reflection(
        root_cause=f"[결정론 폴백] {', '.join(sorted(layers))} 계층에서 {len(failures)}건 반려 — "
                   f"성분 선택 재검토 필요",
        directive=directive,
        avoid=list(dict.fromkeys(avoid)),
    )


def should_escalate(failures: List[Verdict]) -> bool:
    """반성 루프로 풀 수 없는 반려인가 — 사람에게 바로 넘겨야 하는 경우.

    route_decision_tree의 RTE010(가능한 공정 경로 없음)처럼 재설계로 해결되지 않는 건
    루프를 돌리면 비용만 쓴다.
    """
    return any(v.status == VerdictStatus.ESCALATE for v in failures)
