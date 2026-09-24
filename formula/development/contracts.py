"""ExperimentalDevelopmentGraph 데이터 계약 — 명세 v6.1 §10.

후보 탐색(`formula/contracts.py`)의 계약과 **분리**한다(명세 §17-2). 두 그래프는 내부 state를
공유하지 않고, 불변 `CandidateDevelopmentHandoff` 하나로만 연결된다(§1.1).

필드는 명세 §10과 1:1이다. 명세에 없는 필드를 더한 곳은 주석으로 표시했다(화면·추적용).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

EvidenceStatus = Literal[
    "MEASURED_CONFIRMED", "MEASURED_UNCONFIRMED", "LITERATURE_DIRECT", "LITERATURE_DIGITIZED",
    "MODEL_PREDICTED", "EXPERT_ASSUMPTION", "LLM_HYPOTHESIS", "SYNTHETIC_DEMO", "UNKNOWN",
]
AnalysisRole = Literal["DOE_RESPONSE", "MONITOR_ONLY", "NOT_APPLICABLE"]
AcceptanceOperator = Literal["LE", "GE", "BETWEEN", "TARGET_TOL", "PASS_FAIL"]


# ── §10.1 Handoff ──────────────────────────────────────────────────────────
class IngredientAmount(BaseModel):
    name: str
    role: str
    amount_mg: Optional[float] = None
    pct_w_w: Optional[float] = None
    unit: Optional[str] = "mg"
    grade: Optional[str] = None
    is_critical: bool = False


class ProcessStepRef(BaseModel):
    unit_op_code: str
    name: str
    order: int


class FixedParameter(BaseModel):
    name: str
    value: Optional[Union[float, str]] = None
    unit: Optional[str] = None
    status: Literal["SET", "UNKNOWN", "MISSING"] = "MISSING"   # MISSING: 명세 외 — 아직 아무 기록도 없음
    evidence_ref: Optional[str] = None


class CandidateDevelopmentHandoff(BaseModel):
    handoff_id: str
    project_id: str
    candidate_id: str
    candidate_version: int
    formulation_fingerprint: str
    qtpp_snapshot_id: Optional[str]
    ingredients: List[IngredientAmount]
    process_route_id: str
    process_steps: List[ProcessStepRef]
    fixed_parameters: List[FixedParameter]
    batch_scale: Optional[str]
    evidence_snapshot_id: str
    rule_verdict_ids: List[str]
    rulebook_version: str
    created_by: str
    created_at: str
    # 명세 외(추적·화면용): 제형·방출·API 요약과 상류 판정 요약
    dosage_form: str = "tablet"
    release_type: str = "immediate_release"
    coating: str = "none"
    api: Dict[str, Any] = Field(default_factory=dict)
    equipment_id: Optional[str] = None
    upstream_verdicts: List[Dict[str, Any]] = Field(default_factory=list)
    unit_weight_mg: Optional[float] = None


# ── §10.2 CQA ──────────────────────────────────────────────────────────────
class CQASpec(BaseModel):
    cqa_id: str
    version: int = 1
    name: str
    criticality: Literal["HIGH", "MEDIUM", "LOW"]
    analysis_role: AnalysisRole
    summary_definition: Optional[str] = None
    quantity_kind: str
    acceptance_operator: Optional[AcceptanceOperator] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    target: Optional[float] = None
    target_tolerance: Optional[float] = None
    compendial_procedure_ref: Optional[str] = None
    unit: Optional[str] = None
    test_method_id: Optional[str] = None
    test_method_version: Optional[str] = None
    criterion_source: Literal["PHARMACOPEIA", "PROJECT_TARGET", "REGULATORY", "OTHER"] = "OTHER"
    binding_status: Literal["BINDING", "NON_BINDING", "NOT_YET_KNOWN"] = "NOT_YET_KNOWN"
    approval_status: str = "DRAFT"
    override_decision_ids: List[str] = Field(default_factory=list)
    # 명세 외: 룰 context(#7)가 읽는 필드
    template_id: str = ""
    category: str = ""
    requirement: str = "CONDITIONAL"
    criterion_type: str = "ABSOLUTE"
    practical_effect_threshold: Optional[float] = None
    replicate_policy: Optional[str] = None
    rationale_refs: Optional[str] = None
    criterion_note: str = ""
    assumption: bool = False          # 연구자 입력 가정 (UI에 표시)


# ── §10.3 Factor ───────────────────────────────────────────────────────────
class RangeBound(BaseModel):
    value: Optional[Union[float, str]] = None
    source_ref: Optional[str] = None
    evidence_status: EvidenceStatus = "UNKNOWN"


class FactorDefinition(BaseModel):
    factor_id: str
    version: int = 1
    name: str
    kind: Literal["CMA", "CPP", "CATEGORICAL", "MIXTURE_COMPONENT", "HARD_TO_CHANGE", "NOISE_FACTOR"]
    unit: Optional[str] = None
    low: RangeBound = Field(default_factory=RangeBound)
    center: RangeBound = Field(default_factory=RangeBound)
    high: RangeBound = Field(default_factory=RangeBound)
    width_check: Literal["OK", "TOO_NARROW", "NOT_CHECKED"] = "NOT_CHECKED"
    composition_group_id: Optional[str] = None
    balance_component: Optional[str] = None
    range_finding_run_ids: List[str] = Field(default_factory=list)
    fmea_refs: List[str] = Field(default_factory=list)
    supersedes: Optional[str] = None
    status: Literal["READY", "REQUEST_DATA", "FIXED", "EXCLUDED"] = "REQUEST_DATA"
    # 명세 외
    ingredient: Optional[str] = None
    symbol: str = ""
    manufacturability_evidence: Optional[str] = None
    expected_range_contrast: Optional[float] = None
    levels: List[str] = Field(default_factory=list)
    proposal_notes: List[str] = Field(default_factory=list)


# ── §10.4 Plan · screening decision ────────────────────────────────────────
class DoEPlan(BaseModel):
    doe_plan_id: str
    version: int = 1
    study_id: str
    handoff_id: str
    stage: Literal["RANGE_FINDING", "SCREENING", "RSM", "VERIFICATION"]
    source: Literal["SYSTEM_GENERATED", "RESEARCHER_PROVIDED"] = "SYSTEM_GENERATED"
    design_type: str
    factor_ids: List[str]
    response_ids: List[str]
    intended_model_terms: List[str]
    standard_matrix_ref: str
    actual_matrix_ref: str
    alias_structure: Dict[str, Any] = Field(default_factory=dict)
    block_definition: Optional[Dict[str, Any]] = None
    random_seed: int
    generator: Dict[str, Any]
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    override_decision_ids: List[str] = Field(default_factory=list)
    status: str = "DRAFT"
    approved_by: Optional[str] = None
    # 명세 외: 행렬 본문 (ref가 가리키는 내용을 study state에 함께 보존)
    runs: List[Dict[str, Any]] = Field(default_factory=list)


class FactorScreeningDecision(BaseModel):
    factor_id: str
    classification: Literal["ACTIVE", "FIXED", "ALIASED", "CURVATURE", "RETAIN_FOR_SAFETY",
                            "INCONCLUSIVE", "INVALID"]
    responses_evaluated: List[str]
    not_evaluated: List[str]
    range_tested: Dict[str, Any]
    rationale_codes: List[str]
    spec_checked: List[str] = Field(default_factory=list)   # 명세 §6 D7 예시의 별도 필드


# ── §10.5 결과 · 모델 · 영역 ────────────────────────────────────────────────
class TestResult(BaseModel):
    __test__ = False   # pytest가 수집하지 않게
    test_result_id: str
    study_id: str
    doe_run_id: str
    batch_id: Optional[str]
    test_method_id: Optional[str]
    test_method_version: Optional[str]
    response_id: str
    individual_values: List[float] = Field(default_factory=list)
    summary_statistic: Dict[str, Any]
    unit: Optional[str]
    raw_data_refs: List[str] = Field(default_factory=list)
    evidence_status: EvidenceStatus
    replicate_independence: Literal["INDEPENDENT_BATCH", "WITHIN_BATCH", "UNKNOWN"]
    deviation: Optional[str] = None
    human_verification_status: Literal["PENDING", "CONFIRMED", "REJECTED"] = "PENDING"
    # 명세 외
    parent_blend_id: Optional[str] = None
    settings: Dict[str, float] = Field(default_factory=dict)
    submitted_at: str = ""
    quality: Dict[str, Any] = Field(default_factory=dict)


class ResponseModel(BaseModel):
    response_model_id: str
    version: int
    cqa_id: str
    formula: str
    intended_terms: List[str]
    reduced_from: Optional[str] = None
    coefficients: Dict[str, float]
    covariance_ref: str
    fit_stats: Dict[str, Any]
    pure_error: Optional[Dict[str, Any]] = None
    lack_of_fit: Optional[Dict[str, Any]] = None
    influence_flags: List[Dict[str, Any]] = Field(default_factory=list)
    domain_bounds: Dict[str, Any]
    input_result_ids: List[str]
    tool_versions: Dict[str, str]
    validation_status: Literal["VALID", "FLAGGED", "ACCEPTED_WITH_FLAGS", "HOLD", "REJECTED"]
    selection_history: List[Dict[str, Any]] = Field(default_factory=list)
    override_decision_ids: List[str] = Field(default_factory=list)


class RegionScope(BaseModel):
    fixed_conditions: List[FixedParameter]
    unmanaged: List[str]
    not_evaluated: List[str]
    material_lots: List[Dict[str, Any]]
    equipment: Optional[str]
    batch_scale: Optional[str]
    extrapolation_zones: List[Dict[str, Any]]
    limitations: Optional[str] = None   # 명세 외: DR013이 요구하는 "검증 주장의 한계" 기록


class DesignSpaceVersion(BaseModel):
    design_space_id: str
    version: int
    source_model_ids: List[str]
    domain_bounds: Dict[str, Any]
    constraints: List[Dict[str, Any]]
    uncertainty_method: str
    joint_probability_policy: Dict[str, Any]
    feasible_region_ref: str
    recommended_setpoint: Optional[Dict[str, Any]]
    recommended_operating_range: Optional[Dict[str, Any]] = None
    scope: RegionScope
    verification_plan_id: Optional[str] = None
    status: Literal["PROVISIONAL", "VERIFIED", "INVALIDATED"] = "PROVISIONAL"
    invalidation_reason: Optional[str] = None


# ── §10.6 확인계획 · override ──────────────────────────────────────────────
class VerificationPoint(BaseModel):
    point_id: str
    role: Literal["SETPOINT", "BOUNDARY", "ROBUSTNESS", "CHALLENGE", "REFERENCE_EXISTING"]
    settings: Dict[str, float]
    predicted: Dict[str, Any]
    expected_outcome: Literal["PASS", "FAIL"] = "PASS"
    expected_fail_cqa: Optional[str] = None
    expected_fail_probability: Optional[float] = None
    batch_id: Optional[str] = None
    parent_blend_id: Optional[str] = None
    # 명세 외
    coded: Dict[str, float] = Field(default_factory=dict)
    rationale: str = ""


class VerificationPlan(BaseModel):
    verification_plan_id: str
    design_space_id: str
    design_space_version: int
    points: List[VerificationPoint]
    locked_at: Optional[str] = None
    approved_by: Optional[str] = None
    pi_policy: Optional[Dict[str, Any]] = None
    locked_hash: Optional[str] = None
    batches_per_point: int = 1


class OverrideDecision(BaseModel):
    decision_id: str
    rule_id: str
    rule_version: str
    original_effect: str
    researcher_decision: str
    reason: str
    approver: Optional[str] = None
    actor_id: str
    affected_artifacts: List[str] = Field(default_factory=list)
    created_at: str
