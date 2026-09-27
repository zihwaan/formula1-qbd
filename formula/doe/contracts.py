"""v7.0 상태·전이·근거 등급 — 명세 §5 상태기계와 §6.D4 범위근거 표를 그대로 옮긴다.

상태 문자열은 여기 한 곳에만 있다. PROVISIONAL_DESIGN_SPACE·VERIFIED_OPERATING_REGION은 study 상태이고, 영역 artifact의
PROVISIONAL/VERIFIED/INVALIDATED와 문자열 비교로 섞지 않는다(§5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

STATES = [
    "HANDOFF_RECEIVED", "CQA_REVIEW", "FMEA_REVIEW", "FACTOR_SELECTION", "RANGE_EVIDENCE_CHECK",
    "NEEDS_FEASIBILITY", "WAITING_FEASIBILITY_RESULTS", "RANGE_REVISION_REQUIRED", "PROTOTYPE_REVISION_REQUIRED",
    "ADVANCED_DESIGN_REQUIRED", "DOE_RANGE_READY", "DOE_PLAN_REVIEW", "WAITING_FOR_RESULTS", "RESULT_QUALITY_REVIEW",
    "MODEL_FIT", "MODEL_INADEQUATE", "PROVISIONAL_DESIGN_SPACE", "WAITING_VERIFICATION_RESULTS",
    "REGION_REVISION_REQUIRED", "VERIFIED_OPERATING_REGION",
]
FORBIDDEN_STATES = ("CONTROL_STRATEGY", "PPQ_READY", "COMMERCIAL_RELEASE")

TRANSITIONS: Dict[str, Sequence[str]] = {
    "HANDOFF_RECEIVED": ["CQA_REVIEW"],
    "CQA_REVIEW": ["FMEA_REVIEW"],
    "FMEA_REVIEW": ["FACTOR_SELECTION"],
    "FACTOR_SELECTION": ["RANGE_EVIDENCE_CHECK"],
    "RANGE_EVIDENCE_CHECK": ["NEEDS_FEASIBILITY", "ADVANCED_DESIGN_REQUIRED", "DOE_RANGE_READY"],
    "ADVANCED_DESIGN_REQUIRED": ["DOE_PLAN_REVIEW"],
    "NEEDS_FEASIBILITY": ["WAITING_FEASIBILITY_RESULTS"],
    "WAITING_FEASIBILITY_RESULTS": ["DOE_RANGE_READY", "RANGE_REVISION_REQUIRED", "PROTOTYPE_REVISION_REQUIRED"],
    "RANGE_REVISION_REQUIRED": ["RANGE_EVIDENCE_CHECK"],
    "PROTOTYPE_REVISION_REQUIRED": ["FMEA_REVIEW"],
    "DOE_RANGE_READY": ["DOE_PLAN_REVIEW"],
    "DOE_PLAN_REVIEW": ["WAITING_FOR_RESULTS", "RANGE_EVIDENCE_CHECK"],
    "WAITING_FOR_RESULTS": ["RESULT_QUALITY_REVIEW"],
    "RESULT_QUALITY_REVIEW": ["WAITING_FOR_RESULTS", "MODEL_FIT"],
    "MODEL_FIT": ["MODEL_INADEQUATE", "PROVISIONAL_DESIGN_SPACE"],
    "MODEL_INADEQUATE": ["FMEA_REVIEW"],
    "PROVISIONAL_DESIGN_SPACE": ["WAITING_VERIFICATION_RESULTS"],
    "WAITING_VERIFICATION_RESULTS": ["REGION_REVISION_REQUIRED", "VERIFIED_OPERATING_REGION"],
    "REGION_REVISION_REQUIRED": ["FMEA_REVIEW"],
    "VERIFIED_OPERATING_REGION": [],
}


class TransitionError(ValueError):
    pass


def check_transition(src: str, dst: str) -> None:
    if dst in FORBIDDEN_STATES or src in FORBIDDEN_STATES:
        raise TransitionError(f"금지 상태 {dst if dst in FORBIDDEN_STATES else src} — 관리전략·PPQ·상업 출하는 범위 밖(§2.3)")
    if src not in TRANSITIONS or dst not in TRANSITIONS.get(src, ()):
        raise TransitionError(f"허용되지 않은 전이 {src} → {dst}")


# §6.D4 범위근거 등급 — 신규 API에서 RSM 직행 가능 여부
EVIDENCE_DIRECT_RSM = ("MEASURED_PRIOR_BATCH", "FEASIBILITY_CONFIRMED", "VERIFIED_EXTERNAL_DATA")
EVIDENCE_NEEDS_FEASIBILITY = ("REPORTED_NO_RAW_DATA", "EXPERT_PROPOSAL", "UNVERIFIED_PROPOSAL")
EVIDENCE_STATUSES = EVIDENCE_DIRECT_RSM + EVIDENCE_NEEDS_FEASIBILITY
STUDY_MODES = ("NEW_API", "LITERATURE_REPLAY")


@dataclass
class FactorSpec:
    """§7.3 factor — reference_value와 center는 다른 필드다(상류 처방값을 중심점으로 자동 승계 금지)."""
    factor_id: str
    name: str
    unit: Optional[str]
    low: Optional[float]
    center: Optional[float]
    high: Optional[float]
    kind: str = "CMA"                          # CMA|CPP|CATEGORICAL|MIXTURE_COMPONENT|HARD_TO_CHANGE
    data_type: str = "CONTINUOUS"
    quantity_kind: Optional[str] = None
    reference_value: Optional[float] = None
    reference_source: Optional[str] = None
    center_source: str = "RESEARCHER_INPUT"    # HANDOFF_REFERENCE_PROTOTYPE이면 RE003로 차단
    evidence_status: Dict[str, Optional[str]] = field(default_factory=dict)   # {"low":…, "center":…, "high":…}
    applicability_confirmed: bool = False
    range_evidence_refs: List[str] = field(default_factory=list)

    @property
    def boundaries(self) -> List[Optional[str]]:
        return [self.evidence_status.get(k) for k in ("low", "center", "high")]


@dataclass
class Decision:
    """규칙 판정 한 건 — 코드와 다음 상태·문구는 룰북 행과 M07에서 온다(코드에 문자열을 새로 만들지 않는다)."""
    rule_id: str
    gate_effect: str
    result_code: str
    next_state: Optional[str]
    message_ko: str
    enforced: bool
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"rule_id": self.rule_id, "gate_effect": self.gate_effect, "result_code": self.result_code,
                "next_state": self.next_state, "message_ko": self.message_ko, "enforced": self.enforced, **self.detail}
