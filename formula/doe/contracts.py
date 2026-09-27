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
    "DOE_RANGE_READY": ["DOE_PLAN_REVIEW", "ADVANCED_DESIGN_REQUIRED"],
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


# ── 연구자 행동 · 사람 승인(RB00 human_approval_required) ─────────────────────────
# 상태마다 받을 수 있는 행동. 표 밖 행동은 409 — 승인 없이 다음 단계로 가는 길이 없다.
REVISE_STATES = ("PROTOTYPE_REVISION_REQUIRED", "MODEL_INADEQUATE", "REGION_REVISION_REQUIRED")
ACTIONS: Dict[str, Sequence[str]] = {
    "HANDOFF_RECEIVED": ("handoff_data", "handoff_confirm"),
    "CQA_REVIEW": ("cqa_edit", "cqa_approve"),
    "FMEA_REVIEW": ("fmea_edit", "fmea_approve"),
    "FACTOR_SELECTION": ("factor_select",),
    "RANGE_EVIDENCE_CHECK": ("range_submit", "range_approve"),
    "NEEDS_FEASIBILITY": ("feasibility_plan_approve",),
    "WAITING_FEASIBILITY_RESULTS": ("feasibility_results_submit",),
    "RANGE_REVISION_REQUIRED": ("range_submit",),
    "PROTOTYPE_REVISION_REQUIRED": ("revise",),
    "ADVANCED_DESIGN_REQUIRED": ("design_import",),
    "DOE_PLAN_REVIEW": ("plan_approve", "plan_reject", "plan_import"),
    "WAITING_FOR_RESULTS": ("results_submit",),
    "RESULT_QUALITY_REVIEW": ("results_confirm", "results_revise"),
    "MODEL_FIT": ("model_accept_flags",),
    "MODEL_INADEQUATE": ("revise",),
    "PROVISIONAL_DESIGN_SPACE": ("vplan_lock",),
    "WAITING_VERIFICATION_RESULTS": ("verification_submit", "final_approve"),
    "REGION_REVISION_REQUIRED": ("revise",),
    "VERIFIED_OPERATING_REGION": (),
}
APPROVAL_POINT = {
    "cqa_approve": ("CQA_SELECTION",), "fmea_approve": ("FMEA_REVIEW",), "range_approve": ("FACTOR_AND_RANGE_SELECTION",),
    "feasibility_plan_approve": ("FEASIBILITY_PLAN",), "plan_approve": ("DOE_PLAN", "EXECUTION_PROTOCOL"),
    "model_accept_flags": ("MODEL_ACCEPTANCE_WITH_FLAGS",), "vplan_lock": ("VERIFICATION_PLAN",),
    "final_approve": ("VERIFIED_OPERATING_REGION",),
}
# 명세 §4 화면 1–6
STEP_OF = {
    "HANDOFF_RECEIVED": 1, "CQA_REVIEW": 1, "FMEA_REVIEW": 2, "FACTOR_SELECTION": 2,
    "RANGE_EVIDENCE_CHECK": 3, "NEEDS_FEASIBILITY": 3, "WAITING_FEASIBILITY_RESULTS": 3, "RANGE_REVISION_REQUIRED": 3,
    "PROTOTYPE_REVISION_REQUIRED": 3, "DOE_RANGE_READY": 4, "ADVANCED_DESIGN_REQUIRED": 4, "DOE_PLAN_REVIEW": 4,
    "WAITING_FOR_RESULTS": 5, "RESULT_QUALITY_REVIEW": 5, "MODEL_FIT": 5, "MODEL_INADEQUATE": 5,
    "PROVISIONAL_DESIGN_SPACE": 6, "WAITING_VERIFICATION_RESULTS": 6, "REGION_REVISION_REQUIRED": 6,
    "VERIFIED_OPERATING_REGION": 6,
}
STEPS = ("후보·CQA", "FMEA·요인", "범위·feasibility", "실험표", "결과·모델", "영역·확인")

# 룰북 next_state 중 v6.1 이름 → 명세 상태. STAY = 지금 단계에서 막힘(연구자 입력 대기).
# 표에 없는 값은 옮기지 않고 결정 원장에 UNMAPPED_NEXT_STATE로 남긴다(IMPLEMENTATION_DESIGN §3).
STAY = "STAY"
RULE_STATE_ALIAS: Dict[str, str] = {
    "WAITING_REQUIRED_DATA": STAY, "INELIGIBLE": STAY, "WAITING_CQA_APPROVAL": STAY, "WAITING_FACTOR_APPROVAL": STAY,
    "WAITING_FACTOR_DATA": STAY, "DESIGN_REPLAN": STAY, "WAITING_RUN_DATA": STAY, "WAITING_PROTOCOL_DATA": STAY,
    "WAITING_RESULT_CONFIRMATION": STAY, "WAITING_MODEL_APPROVAL": STAY, "WAITING_FINAL_APPROVAL": STAY,
    "WAITING_AUDIT_REVIEW": STAY, "DIAGNOSING": STAY,
    "DOE_PLAN_DRAFT": "DOE_PLAN_REVIEW", "WAITING_BATCH_RESULTS": "WAITING_FOR_RESULTS",
    "RSM_AUGMENTATION": "MODEL_INADEQUATE", "DOE_AUGMENTATION_REVIEW": "MODEL_INADEQUATE", "STRATEGY_REVIEW": "MODEL_INADEQUATE",
    "MODEL_REVIEW": "REGION_REVISION_REQUIRED", "REGION_REVIEW": "REGION_REVISION_REQUIRED",
}


def resolve_state(next_state: Optional[str]) -> Optional[str]:
    """룰 next_state → 명세 상태 | STAY | None(표에 없음)."""
    if not next_state:
        return STAY
    if next_state in STATES:
        return next_state
    return RULE_STATE_ALIAS.get(next_state)
