"""LangGraph 전역 상태(state) 정의.

필드 이름은 조하준 자료의 `rule_input_dictionary.csv`(155변수)가 정의한 canonical 어휘를
따른다 — 룰북 조건식(`selected_route`, `bcs_class`, `target_population` …)이 그대로
state를 참조할 수 있어야 하기 때문이다.

LangGraph의 병렬 fan-out(Send)에서 여러 노드가 같은 키에 쓰기 때문에,
누적되는 필드에는 reducer(operator.add)를 붙인다.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Dict, List, Optional

from typing_extensions import TypedDict

from formula.contracts import (
    ApiProfile,
    FeedbackReport,
    FormulationSpec,
    JudgeSpec,
    JudgeVerdict,
    Recipe,
    Verdict,
)

# 무한 재설계를 막는 상한 (README 8장의 '최대 5회' 규약)
MAX_REFLECTION_LOOPS = 5


def accumulate(left: Optional[List], right: Optional[List]) -> List:
    """병렬 fan-out 결과를 누적하는 reducer. `None`은 **초기화 신호**다.

    반성 루프가 돌 때 이전 라운드의 후보·판정을 비워야 하는데, 단순 `operator.add`로는
    빈 리스트를 반환해도 아무것도 지워지지 않는다(더하기니까). 그래서 초기화 전용
    센티널을 둔다 — 노드가 `{"candidates": None}`을 반환하면 그 키가 비워진다.
    """
    if right is None:
        return []
    return list(left or []) + list(right)


class CandidateResult(TypedDict, total=False):
    """후보 처방 1건에 대한 게이트 결과 묶음."""

    candidate_id: str
    recipe: Recipe
    verdicts: List[Verdict]
    derived: Dict[str, Any]
    passed: bool
    blockers: List[str]


class FormulationState(TypedDict, total=False):
    """그래프 전역에서 공유되는 상태."""

    run_id: str
    request: str  # 사용자의 자연어 요구
    smiles: Optional[str]
    required_excipients: List[str]  # 현장 제약으로 반드시 넣어야 하는 부형제
    # 사용자가 처음부터 넣은 실측값·플래그(선택). 추정보다 우선한다.
    measured_params: Dict[str, float]
    property_flags: Dict[str, bool]

    # P0 — 입력 번역 & 물성
    spec: Optional[FormulationSpec]
    api_profile: Optional[ApiProfile]

    # P2 — 후보 생성 (병렬 fan-out → 누적)
    strategies: List[str]
    candidates: Annotated[List[Recipe], accumulate]

    # P3 — 결정론 게이트 (병렬 → 누적)
    results: Annotated[List[CandidateResult], accumulate]

    # P4 — 근거 충족 게이트 (후보별 판정 · candidate_id → EvidenceAssessment)
    evidence: Dict[str, Any]
    readiness: str  # 대표 후보의 프로토콜 상태 (blocked | ready_for_review | approved)

    # P5/P6 — 심사 & 합의
    summoned: List[JudgeSpec]
    judge_verdicts: Annotated[List[JudgeVerdict], accumulate]
    consensus: Optional[Dict[str, Any]]

    # P6 — 반성 루프
    reflection_count: int
    reflection_directive: str
    reject_reasons: List[str]

    # P7 — lab-in-the-loop (배치 결과 → 원인 가설 → 다음 실험 지시)
    wetlab: Optional[FeedbackReport]

    # 종료 상태
    status: str  # running | passed | rejected | escalated | exhausted | infeasible
    final_candidate: Optional[str]


def new_state(request: str, smiles: Optional[str] = None, run_id: Optional[str] = None,
              required_excipients: Optional[List[str]] = None,
              measured_params: Optional[Dict[str, float]] = None,
              property_flags: Optional[Dict[str, bool]] = None) -> FormulationState:
    return FormulationState(
        run_id=run_id or uuid.uuid4().hex[:12],
        request=request,
        smiles=smiles,
        required_excipients=list(required_excipients or []),
        measured_params=dict(measured_params or {}),
        property_flags=dict(property_flags or {}),
        spec=None,
        api_profile=None,
        strategies=[],
        candidates=[],
        results=[],
        evidence={},
        readiness="",
        summoned=[],
        judge_verdicts=[],
        consensus=None,
        reflection_count=0,
        reflection_directive="",
        reject_reasons=[],
        wetlab=None,
        status="running",
        final_candidate=None,
    )
