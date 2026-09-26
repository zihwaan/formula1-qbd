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
    dose_basis: str   # 요청 용량의 기준: free_base | salt

    # P0 — 입력 번역 & 물성
    spec: Optional[FormulationSpec]
    api_profile: Optional[ApiProfile]

    # v3 P1/G3A/G3B/G4/G4B/G6R — phase_gates가 채우는 파생값과 계획 서명.
    # phase_derived는 node_gate가 룰북 registry.run()의 derived= 시드로도 재사용한다.
    phase_derived: Dict[str, Any]
    pending_narrow: List[Dict[str, Any]]  # DRQ_NARROW — 전략을 좁히는 데 쓰일 요청(비차단)
    plan_signature: str  # strategy_planner.signature() — reassess_with_measurements()가 비교

    # P2 — 후보 생성 (병렬 fan-out → 누적)
    strategies: List[str]
    candidates: Annotated[List[Recipe], accumulate]

    # P3 — 결정론 게이트 (병렬 → 누적)
    results: Annotated[List[CandidateResult], accumulate]

    # v3 최종 산출물에 함께 실리는 미해결 요청(§1 "미해결 요청" 컬럼)
    pending_requests: List[Dict[str, Any]]

    # P4 — 근거 충족 게이트 (v3에서는 와이어링만 뺐다 — 그래프가 채우지 않는다.
    # 되돌릴 경우를 위해 필드는 남겨 둔다). candidate_id → EvidenceAssessment
    evidence: Dict[str, Any]
    readiness: str  # 대표 후보의 프로토콜 상태 (blocked | ready_for_review | approved)

    # P5/P6 — 심사 & 합의
    summoned: List[JudgeSpec]
    judge_verdicts: Annotated[List[JudgeVerdict], accumulate]
    consensus: Optional[Dict[str, Any]]

    # P6 — 반성 루프
    reflection_count: int
    reflection_directive: str
    constraints: Dict[str, List[str]]   # 되돌림이 쌓은 제약: 성분·전략·경로 제외, 가족 요구/감점
    phase_attempts: Dict[str, int]      # 복귀 지점별 횟수 — 같은 지점 3회면 한 단계 위로
    backtrack: Dict[str, Any]           # 마지막 되돌림 결정
    planned: List[Dict[str, Any]]       # 계획이 고른 전략(공정 단계·규칙 커버리지 포함)
    reject_reasons: List[str]

    # P7 — lab-in-the-loop (배치 결과 → 원인 가설 → 다음 실험 지시)
    wetlab: Optional[FeedbackReport]

    # 종료 상태
    status: str  # running | passed | rejected | escalated | exhausted | infeasible
    final_candidate: Optional[str]


def new_state(request: str, smiles: Optional[str] = None, run_id: Optional[str] = None,
              required_excipients: Optional[List[str]] = None,
              measured_params: Optional[Dict[str, float]] = None,
              property_flags: Optional[Dict[str, bool]] = None,
              dose_basis: str = "free_base") -> FormulationState:
    return FormulationState(
        run_id=run_id or uuid.uuid4().hex[:12],
        request=request,
        smiles=smiles,
        required_excipients=list(required_excipients or []),
        measured_params=dict(measured_params or {}),
        property_flags=dict(property_flags or {}),
        dose_basis=dose_basis,
        spec=None,
        api_profile=None,
        phase_derived={},
        pending_narrow=[],
        plan_signature="",
        strategies=[],
        candidates=[],
        results=[],
        pending_requests=[],
        evidence={},
        readiness="",
        summoned=[],
        judge_verdicts=[],
        consensus=None,
        reflection_count=0,
        constraints={},
        phase_attempts={},
        backtrack={},
        planned=[],
        reflection_directive="",
        reject_reasons=[],
        wetlab=None,
        status="running",
        final_candidate=None,
    )
