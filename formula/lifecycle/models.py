"""장기 실행 제형 개발 워크플로의 외부 계약.

Phase는 별도 AI 에이전트 이름이 아니라 현재 진행 위치와 되돌아갈 주소다. 따라서 이
모델은 모델 호출 방식과 독립적이며, 사람이 며칠 뒤 결과를 넣어도 같은 상태에서 재개된다.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    DESIGNING = "DESIGNING"
    RULE_VALIDATING = "RULE_VALIDATING"
    EVIDENCE_CHECK = "EVIDENCE_CHECK"
    WAITING_FOR_EVIDENCE = "WAITING_FOR_EVIDENCE"
    REVIEWING = "REVIEWING"
    PROTOCOL_DRAFT = "PROTOCOL_DRAFT"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    READY_FOR_LAB = "READY_FOR_LAB"
    WAITING_FOR_RESULT = "WAITING_FOR_RESULT"
    RESULT_CONFIRMATION = "RESULT_CONFIRMATION"
    CQA_EVALUATION = "CQA_EVALUATION"
    DIAGNOSING = "DIAGNOSING"
    WAITING_FOR_CONFIRMATION_TEST = "WAITING_FOR_CONFIRMATION_TEST"
    REFLECTING = "REFLECTING"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    INFEASIBLE = "INFEASIBLE"


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt-{uuid.uuid4().hex}")
    event_type: str
    project_id: str
    run_id: str = ""
    candidate_id: str = ""
    protocol_version: Optional[int] = None
    batch_id: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_by: Dict[str, str] = Field(default_factory=lambda: {"type": "system", "id": "formula1"})
    created_at: float = Field(default_factory=time.time)
    idempotency_key: str = Field(default_factory=lambda: uuid.uuid4().hex)
    schema_version: str = "1.0"


class CandidateSpec(BaseModel):
    cqa_id: str
    test_method_id: str
    metric: str
    timepoint: str = "initial"
    operator: str
    target_value: float
    unit: str
    spec_type: str = "development"
    justification: str
    source_ref: str
    version: int = 1


class ProjectState(BaseModel):
    project_id: str
    run_id: str = ""
    state_version: int = 0
    status: WorkflowStatus = WorkflowStatus.DESIGNING
    request: str = ""
    qtpp: Dict[str, Any] = Field(default_factory=dict)
    active_candidate_id: Optional[str] = None
    candidates: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    protocols: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    batches: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    results: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    diagnoses: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    candidate_specs: Dict[str, List[CandidateSpec]] = Field(default_factory=dict)
    pending_actions: List[Dict[str, Any]] = Field(default_factory=list)
    decision_refs: List[str] = Field(default_factory=list)
    rule_revision_attempt: int = 0
    evidence_round: int = 0
    lab_iteration: int = 0
    diagnostic_round: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def public(self) -> Dict[str, Any]:
        data = self.model_dump(mode="json")
        data["next_allowed_events"] = next_allowed_events(self.status)
        return data


def next_allowed_events(status: WorkflowStatus) -> List[str]:
    return {
        WorkflowStatus.DESIGNING: ["DESIGN_RUN_COMPLETED"],
        WorkflowStatus.WAITING_FOR_EVIDENCE: ["EVIDENCE_RESULT_CONFIRMED"],
        WorkflowStatus.WAITING_FOR_APPROVAL: ["PROTOCOL_APPROVED", "PROTOCOL_CHANGES_REQUESTED"],
        WorkflowStatus.READY_FOR_LAB: ["BATCH_REGISTERED"],
        WorkflowStatus.WAITING_FOR_RESULT: ["LAB_RESULT_SUBMITTED"],
        WorkflowStatus.RESULT_CONFIRMATION: ["LAB_RESULT_CONFIRMED"],
        WorkflowStatus.DIAGNOSING: ["CONFIRMATION_TEST_APPROVED", "ROOT_CAUSE_CONFIRMED"],
        WorkflowStatus.WAITING_FOR_CONFIRMATION_TEST: ["LAB_RESULT_SUBMITTED"],
        WorkflowStatus.REFLECTING: ["CHILD_CANDIDATE_CREATED"],
    }.get(status, [])
