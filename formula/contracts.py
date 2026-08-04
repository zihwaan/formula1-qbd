"""시스템 전역에서 공유되는 데이터 계약(Pydantic 모델).

이 파일은 약대생 팀(데이터)과 개발 백엔드(로직)의 경계 인터페이스다.
CSV의 컬럼명이 바뀌어도 매니페스트 schema 매핑만 고치면 되고, 이 계약은 안정적으로 유지된다.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# API 물리화학 프로파일 (RDKit 계층 산출물)
#
# SMILES 하나로부터 descriptor·구조 플래그·물성 추정을 결정론적으로 계산한다.
# 추정(estimate)은 신뢰도가 낮으므로 판정 근거가 아니라 '힌트'로만 쓴다 — 실측 우선.
# ---------------------------------------------------------------------------
class StructuralFlag(BaseModel):
    """SMARTS 구조 플래그 1건.

    기준서 v1.1 §3 "SMARTS 구조 플래그 공통 데이터 계약"을 그대로 따른다.
    Boolean만 저장하면 중복 motif와 탐지 위치를 확인할 수 없으므로
    match_count와 atom_indices를 함께 싣고, **구조 사실(fact)과 구조 경고(alert)를
    alert_level로 분리한다** — 경고는 단독으로 공정을 배제하지 못한다(§L2).
    """

    flag_id: str
    flag_name: str  # 예: has_primary_aliphatic_amine
    present: bool
    smarts: str
    match_count: int = 0
    atom_indices: List[List[int]] = Field(default_factory=list)  # 시각화·검토용
    section: str = ""            # 기준서 절 번호 (4~12)
    rulebook_group: str = ""     # 룰북 api_functional_group 조인 어휘
    specificity: str = "medium"  # low | medium | high
    alert_level: str = "fact"    # fact | conditional_alert | hard_alert
    interpretation: str = ""
    required_cofactors: List[str] = Field(default_factory=list)  # 위험 발현 조건
    applicability: str = "parent"      # parent | input_form | impurity
    false_positive_notes: str = ""
    confirmation_test: str = ""        # 이 경고를 확인할 시험
    smarts_version: str = ""
    fragment_count: Optional[int] = None  # rdkit fr_* 카운트 (교차검증용)
    cross_check_ok: bool = True  # SMARTS와 fragment 카운트가 일치하는가
    validation_status: str = "draft"
    triggers_rule: str = ""


class PhysChemEstimate(BaseModel):
    """descriptor로부터 추정한 물성 1건 (physchem_estimation_rules.csv 1행)."""

    estimate_id: str
    property: str
    value: Any = None
    confidence: str = "low"  # low | medium | high
    override_by_experimental: bool = True
    action_if_low_confidence: str = ""
    basis: str = ""


class ApiProfile(BaseModel):
    """SMILES → RDKit 계산 결과 묶음. 재현성을 위해 도구 버전까지 기록한다."""

    api_name: str
    smiles: str
    parent_smiles: str = ""  # 염 제거 후 parent (SMARTS는 이걸로 매칭)
    is_salt: bool = False
    descriptors: Dict[str, float] = Field(default_factory=dict)
    flags: List[StructuralFlag] = Field(default_factory=list)
    estimates: List[PhysChemEstimate] = Field(default_factory=list)
    svg: str = ""  # 2D 구조 (UI 표시용)
    rdkit_version: str = ""
    warnings: List[str] = Field(default_factory=list)

    # ── 기준서 §1 구조 품질/정규화 ──────────────────────────────────
    # parent를 만들어도 실제 투입되는 등록 형태는 제제 특성에 영향을 주므로 함께 보존한다.
    structure_quality: Dict[str, Any] = Field(default_factory=dict)
    # ── 기준서 §2.1 파생 스크리닝 지표 (BCS·공정 확정값 아님) ────────
    derived_screens: Dict[str, Any] = Field(default_factory=dict)
    # ── 재현성: RDKit·정규화·SMARTS 레지스트리 버전 ─────────────────
    versions: Dict[str, str] = Field(default_factory=dict)

    def alerts(self, level: str = "hard_alert") -> List[StructuralFlag]:
        """해당 경고 등급의 플래그만. 확인시험 승격 판단에 쓴다."""
        return [f for f in self.flags if f.present and f.alert_level == level]

    def confirmation_tests(self) -> List[str]:
        """검출된 구조 경고가 요구하는 확인시험 목록(중복 제거)."""
        seen: List[str] = []
        for flag in self.flags:
            if not flag.present or not flag.confirmation_test:
                continue
            for test in flag.confirmation_test.split(";"):
                name = test.strip()
                if name and name not in seen:
                    seen.append(name)
        return seen

    def flag_names(self) -> List[str]:
        """참으로 판정된 구조 플래그 이름 목록."""
        return [f.flag_name for f in self.flags if f.present]

    def functional_groups(self) -> List[str]:
        """배합금기 룰북의 `api_functional_group`과 조인할 작용기 이름.

        기준서 v1.1은 아민을 지방족/방향족·1·2·3차로 세분하지만, 룰북은 여전히
        `primary_amine`·`secondary_amine` 어휘로 조인한다. 레지스트리의
        `rulebook_group`이 그 다리 역할을 하므로 **세분 이름과 룰북 어휘를 둘 다** 낸다.
        이름만 바꾸면 INC001~INC006이 조용히 발동하지 않게 된다.
        """
        names: List[str] = []
        for flag in self.flags:
            if not flag.present:
                continue
            for candidate in (
                flag.rulebook_group,
                flag.flag_name[4:] if flag.flag_name.startswith("has_") else flag.flag_name,
            ):
                if candidate and candidate not in names:
                    names.append(candidate)
        return names


# ---------------------------------------------------------------------------
# 입력 스펙 & 처방
# ---------------------------------------------------------------------------
class FormulationSpec(BaseModel):
    """자연어 요구가 intake 단계에서 번역된 정량 스펙."""

    api_name: str
    # API 물리화학 프로파일 (RDKit 산출 또는 수동 입력)
    api_functional_groups: List[str] = Field(default_factory=list)
    bcs_class: Optional[str] = None  # "I" | "II" | "III" | "IV"
    target_patient: str = "adult"  # 예: "pediatric_under_12"
    dosage_form: str = "tablet"
    # 공정/물성 측정치 (Carr Index, Hausner Ratio, 수분 함량 등)
    measured_params: Dict[str, float] = Field(default_factory=dict)
    # 그 외 플래그 (hygroscopic, low_melting_point 등)
    properties: Dict[str, Any] = Field(default_factory=dict)
    # 반드시 처방에 넣어야 하는 부형제 (기존 생산라인·단가·공급 계약 등 현장 제약).
    # 설계 에이전트는 이걸 회피할 수 없고, 위반 여부는 룰북이 판정한다 —
    # 검증 계층이 무엇을 잡아내는지가 여기서 드러난다.
    required_excipients: List[str] = Field(default_factory=list)
    # RDKit 계층이 채운 프로파일 (있으면 근거 추적에 쓴다)
    api_profile: Optional[ApiProfile] = None

    @property
    def is_pediatric(self) -> bool:
        return "pediatric" in self.target_patient.lower()

    def with_profile(self, profile: ApiProfile) -> "FormulationSpec":
        """RDKit 프로파일을 스펙에 병합한다.

        원칙: **실측값이 이미 있으면 덮어쓰지 않는다.** 추정은 빈칸만 채운다.
        """
        merged = self.model_copy(deep=True)
        merged.api_profile = profile
        if not merged.api_functional_groups:
            merged.api_functional_groups = profile.functional_groups()
        for name, value in profile.descriptors.items():
            merged.measured_params.setdefault(name, value)
        for flag in profile.flags:
            merged.properties.setdefault(flag.flag_name, flag.present)
        return merged


class Ingredient(BaseModel):
    name: str
    role: str = "excipient"  # api | excipient | lubricant | disintegrant | binder | solubilizer ...
    amount_mg: Optional[float] = None
    percent: Optional[float] = None  # 전체 정제 중량 대비 %


class Recipe(BaseModel):
    """Agent 1(Generator)이 만든 처방전 후보."""

    api_name: str
    ingredients: List[Ingredient] = Field(default_factory=list)
    process: Optional[str] = None  # "direct_compression" | "wet_granulation" ...
    packaging: Optional[str] = None  # "pvc_blister" | "alu_alu_blister" ...
    candidate_id: str = "cand-0"
    strategy: str = ""  # 이 후보를 만든 설계 전략 (DC / WG / 가용화 …)
    rationale: str = ""  # 설계 에이전트의 근거 서술

    # --- 체커가 사용하는 조회 헬퍼 ---
    def ingredient_names(self) -> set[str]:
        return {ing.name for ing in self.ingredients}

    def amount_of(self, name: str) -> Optional[float]:
        for ing in self.ingredients:
            if ing.name == name:
                return ing.amount_mg
        return None

    def percent_of_role(self, role: str) -> Optional[float]:
        total = sum(ing.percent for ing in self.ingredients if ing.role == role and ing.percent is not None)
        return total or None


# ---------------------------------------------------------------------------
# 판정 결과
#
# 룰북 CSV의 `action` 컬럼이 6종이라, 통과/반려 2분법으로는 표현이 안 된다.
# action(원본 어휘)은 그대로 보존하고, status(엔진 어휘)를 여기서 파생시킨다.
# ---------------------------------------------------------------------------
class RuleAction(str, Enum):
    """룰북 CSV의 `action` 컬럼 어휘 (이도영 가이드 6장)."""

    HARD_FAIL = "HARD_FAIL"  # 즉시 반려. 심사관 점수와 무관
    EXCLUDE_ROUTE = "EXCLUDE_ROUTE"  # 해당 공정 경로만 후보에서 제외
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"  # 판정 근거 없음 → 사람에게 이관
    REVIEWER_FLAG = "REVIEWER_FLAG"  # 통과하되 심사관 평가 대상으로 표시
    LABEL_REQUIRED = "LABEL_REQUIRED"  # 통과, 단 라벨 기재 의무
    ALLOW = "ALLOW"  # 무조건 통과
    NOT_A_RULE = "NOT_A_RULE"  # 규칙 아님(기록용) — 실행되지 않음

    @classmethod
    def parse(cls, raw: Any) -> "RuleAction":
        try:
            return cls(str(raw).strip().upper())
        except ValueError:
            return cls.REVIEWER_FLAG  # 모르는 어휘는 보수적으로 심사관 이관


class VerdictStatus(str, Enum):
    PASS = "pass"
    HARD_FAIL = "hard_fail"  # 결정론적 규칙 위반 → 즉시 반려
    EXCLUDE_ROUTE = "exclude_route"  # 이 공정 경로만 배제
    ESCALATE = "escalate"  # 사람 판단 필요
    SOFT_FLAG = "soft_flag"  # 심사관 평가 대상 → reflection 후보
    ADVISORY = "advisory"  # 통과 + 의무/참고 사항(라벨 기재 등)


# action → status 매핑. 엔진 전역에서 이 한 곳만 참조한다.
ACTION_TO_STATUS: Dict[RuleAction, VerdictStatus] = {
    RuleAction.HARD_FAIL: VerdictStatus.HARD_FAIL,
    RuleAction.EXCLUDE_ROUTE: VerdictStatus.EXCLUDE_ROUTE,
    RuleAction.ESCALATE_TO_HUMAN: VerdictStatus.ESCALATE,
    RuleAction.REVIEWER_FLAG: VerdictStatus.SOFT_FLAG,
    RuleAction.LABEL_REQUIRED: VerdictStatus.ADVISORY,
    RuleAction.ALLOW: VerdictStatus.PASS,
    RuleAction.NOT_A_RULE: VerdictStatus.PASS,
}


class Verdict(BaseModel):
    """결정론적 체커(정량)의 판정 1건."""

    rulebook_id: str
    strategy: str
    status: VerdictStatus
    action: RuleAction = RuleAction.ALLOW
    rule_id: str = ""  # 원본 CSV 행의 rule_id (근거 드릴다운 키)
    layer: str = ""  # chemical | process | biopharm | regulatory | master | route
    reason: str = ""
    suggestion: str = ""
    score: float = 1.0  # 1.0 = 통과, 0.0 = 실패 (정량은 이분적)
    provisional: bool = False  # 근거가 잠정(PROVISIONAL/미검증)인 규칙에서 나온 판정
    citation: str = ""  # source_citation / source_doc
    evidence: Dict[str, Any] = Field(default_factory=dict)  # 근거가 된 CSV 행

    @property
    def failed(self) -> bool:
        """무언가 걸린 판정인가 (통과·참고 제외)."""
        return self.status not in (VerdictStatus.PASS, VerdictStatus.ADVISORY)

    @property
    def blocking(self) -> bool:
        """후보를 즉시 반려시키는 판정인가. 반려 권한은 HARD_FAIL에만 있다."""
        return self.status == VerdictStatus.HARD_FAIL


class EvidenceTiming(str, Enum):
    """이 근거를 **언제** 확보해야 하는가.

    모든 확인시험을 무조건 먼저 시키는 것은 비효율이다. 선택된 전략을 바꿀 수 있는
    시험만 선행시키고, 나머지는 병행하거나 배치 뒤에 조건부로 돌린다.
    """

    BEFORE_PROTOCOL = "before_protocol"  # 없으면 실행 가능한 공정 프로토콜을 낼 수 없다
    PARALLEL = "parallel"  # 전략은 안 바꾸지만 세부 조건 최적화에 필요 → 병행
    POST_BATCH = "post_batch"  # 첫 배치 결과에 따라 조건부로 수행


class EvidenceStatus(str, Enum):
    SATISFIED = "satisfied"  # 근거 확보됨(실측·확인시험 결과)
    MISSING = "missing"  # 근거 없음
    FAILED = "failed"  # 확인시험을 했는데 부적합 — 이 전략은 배제된다


class ProtocolReadiness(str, Enum):
    """공정 프로토콜의 실행 가능 상태.

    룰 게이트 통과는 "금기를 발견하지 못했다"일 뿐 "실행해도 된다"가 아니다.
    근거가 충족되어야 검토용 프로토콜이 되고, 연구자가 승인해야 실행 가능해진다.
    """

    BLOCKED = "blocked"  # 근거 부족 — 실행 불가 초안(Grounded Draft, Not Executable)
    READY_FOR_REVIEW = "ready_for_review"  # 근거 충족 — 연구자 검토용 프로토콜
    APPROVED = "approved"  # 연구자 승인 완료 — 실행 가능 공정 프로토콜


class EvidenceGap(BaseModel):
    """후보 1건에 대한 근거 요구 1건과 그 충족 여부."""

    requirement_id: str
    evidence_key: str
    label: str = ""
    timing: EvidenceTiming = EvidenceTiming.BEFORE_PROTOCOL
    status: EvidenceStatus = EvidenceStatus.MISSING
    why: str = ""  # 왜 이 후보에 이 근거가 필요한가 (발동 조건의 뜻)
    risk: str = ""  # 근거 없이 실행하면 무엇이 잘못되는가
    stop_criteria: str = ""  # 병행 시험일 때 중단/변경 기준
    # 이 시험이 산출하는 canonical 측정값 이름. 결과가 이 자리에 꽂히면 충족 조건이
    # '표시'가 아니라 실제 실측값으로 참이 된다 — 확인시험 결과가 입력 계층으로 돌아가는 통로.
    result_key: str = ""
    result_unit: str = ""
    # 이 근거를 만드는 확인시험 (confirmation_test_master.csv 의 실제 행)
    test_id: str = ""
    test_name: str = ""
    test_category: str = ""
    test_design: str = ""
    output_variable: str = ""
    acceptance_logic: str = ""
    unit: str = ""
    source_reference: str = ""
    source_url: str = ""
    # 확인시험 결과가 들어왔을 때의 기록
    result_note: str = ""

    @property
    def blocking(self) -> bool:
        """이 결손이 실행 가능 프로토콜을 막는가.

        선행 시험이 비어 있으면 당연히 막고, **시점과 무관하게 '부적합' 결과도 막는다** —
        확인시험이 전제를 부정했는데 그대로 진행하는 것이 가장 위험하기 때문이다.
        """
        if self.status == EvidenceStatus.FAILED:
            return True
        return (self.timing == EvidenceTiming.BEFORE_PROTOCOL
                and self.status != EvidenceStatus.SATISFIED)


class EvidenceAssessment(BaseModel):
    """후보 1건에 대한 근거 충족 판정 (Evidence Readiness Gate의 산출물)."""

    candidate_id: str
    strategy: str = ""
    process: str = ""
    readiness: ProtocolReadiness = ProtocolReadiness.BLOCKED
    gaps: List[EvidenceGap] = Field(default_factory=list)  # 충족된 항목까지 전부
    summary: str = ""
    approved_by: str = ""  # 승인한 연구자 표기 (감사 흔적)
    approved_at: Optional[float] = None

    def of_timing(self, timing: EvidenceTiming) -> List[EvidenceGap]:
        return [g for g in self.gaps if g.timing == timing]

    @property
    def blocking(self) -> List[EvidenceGap]:
        return [g for g in self.gaps if g.blocking]

    @property
    def satisfied(self) -> List[EvidenceGap]:
        return [g for g in self.gaps if g.status == EvidenceStatus.SATISFIED]

    @property
    def failed(self) -> List[EvidenceGap]:
        return [g for g in self.gaps if g.status == EvidenceStatus.FAILED]


class ConfirmationResult(BaseModel):
    """연구자가 되돌려 넣는 **확인시험**(선행 시험) 결과 1건.

    배치 결과(`WetLabResult`)와 입력을 분리한다 — 돌아가는 곳이 다르기 때문이다.
    확인시험 결과는 입력·근거 계층으로 돌아가고, 배치 결과는 설계·프로토콜 개정으로 간다.
    """

    requirement_id: str
    outcome: str = "pass"  # pass(적합) | fail(부적합) — fail이면 그 전략은 배제된다
    value: str = ""  # 측정값·요약 (자유 텍스트)
    value_num: Optional[float] = None  # 요구표의 `result_key`에 대응하는 정량 결과
    note: str = ""


class JudgeVerdict(BaseModel):
    """정성 판단 에이전트(Judge)의 판정 1건."""

    rulebook_id: str
    reviewer_id: str = ""
    persona: str
    score: float  # 0.0 ~ 1.0
    passed: bool
    weight: float = 1.0
    rationale: str = ""
    suggestion: str = ""
    citations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 근거 신뢰도 정책
#
# 룰북 CSV마다 `verification_status` 어휘가 3계열로 갈려 있다(규제형/문헌형/계산형).
# 엔진은 이 값을 보고 "이 행을 판정에 써도 되는가"를 결정해야 한다.
# (이도영 개발자 가이드 7장의 '엔진 동작' 표를 코드로 옮긴 것)
# ---------------------------------------------------------------------------
class EvidencePolicy(str, Enum):
    USE = "use"  # 그대로 판정에 사용
    PROVISIONAL = "provisional"  # 사용하되 '잠정값'으로 표기
    NO_HARD_FAIL = "no_hard_fail"  # 실행하되 HARD_FAIL로는 못 씀 → 심사관 이관
    ESCALATE = "escalate"  # 사람에게 이관
    SKIP = "skip"  # 아예 실행하지 않음(기록용)


VERIFICATION_POLICY: Dict[str, EvidencePolicy] = {
    # 사용 가능
    "VERIFIED": EvidencePolicy.USE,
    "VERIFIED_PRIMARY": EvidencePolicy.USE,
    "VERIFIED_SECONDARY": EvidencePolicy.USE,
    # 잠정값 — 실행은 하되 출력에 표기
    "PROVISIONAL": EvidencePolicy.PROVISIONAL,
    "ESTIMATION_RULE": EvidencePolicy.PROVISIONAL,
    "STRUCTURAL_VERIFIED": EvidencePolicy.PROVISIONAL,  # SMARTS는 RDKit 미검증
    # Hard Fail 판정 금지
    "SCHEMA_ONLY": EvidencePolicy.NO_HARD_FAIL,
    "PARTIAL": EvidencePolicy.NO_HARD_FAIL,
    "INFERRED": EvidencePolicy.NO_HARD_FAIL,
    "UNVERIFIED": EvidencePolicy.NO_HARD_FAIL,
    "UNVERIFIED_CRITICAL": EvidencePolicy.NO_HARD_FAIL,
    # 사람 이관
    "ESCALATION_REQUIRED": EvidencePolicy.ESCALATE,
    # 실행 안 됨
    "NO_SOURCE_FOUND": EvidencePolicy.SKIP,
    "NOT_A_RULE": EvidencePolicy.SKIP,
    "LEGACY": EvidencePolicy.SKIP,  # 구기준 — 판정 사용 금지
}


def evidence_policy(verification_status: Any) -> EvidencePolicy:
    """근거 상태 문자열 → 엔진 동작. 모르는 어휘는 보수적으로 HARD_FAIL을 막는다."""
    key = str(verification_status or "").strip().upper()
    if not key:
        return EvidencePolicy.NO_HARD_FAIL
    return VERIFICATION_POLICY.get(key, EvidencePolicy.NO_HARD_FAIL)


# ---------------------------------------------------------------------------
# 매니페스트 엔트리 (전체 시스템의 린치핀)
# ---------------------------------------------------------------------------
class EvalType(str, Enum):
    QUANTITATIVE = "quantitative"  # → 결정론적 체커 툴
    QUALITATIVE = "qualitative"  # → Judge 에이전트 팩토리
    REFERENCE = "reference"  # → 조회 전용(판정 없음). RAG/파생값 산출에만 쓴다


class Severity(str, Enum):
    HARD_FAIL = "hard_fail"
    SOFT_SCORE = "soft_score"


class Polarity(str, Enum):
    """CSV 행이 서술하는 조건의 방향.

    fail_when : 조건이 참이면 위반   (예: carr_index > 25 → 유동 불량)
    pass_when : 조건이 거짓이면 위반 (예: carr_index <= 20 을 만족해야 통과)
    """

    FAIL_WHEN = "fail_when"
    PASS_WHEN = "pass_when"


class JudgeSpec(BaseModel):
    reviewer_id: str = ""
    persona: str
    rubric_prompt: Optional[str] = None
    retrieval_namespace: Optional[str] = None
    weight: float = 1.0
    pass_threshold: float = 0.7
    summon_condition: str = "true"


class RulebookEntry(BaseModel):
    """rulebook_manifest.yaml의 항목 1개.

    이 한 덩어리가 "이 CSV를 어떻게 검증에 배선할지"를 스스로 선언한다.
    """

    id: str
    file: str
    layer: str  # chemical | process | biopharm | regulatory | master | route | system
    owner_agent: str  # generator | predictor | auditor
    eval_type: EvalType
    severity: Severity = Severity.HARD_FAIL  # 행에 action이 없을 때의 기본값
    applies_when: str = "true"  # 스펙에 대한 발동 조건식 (매니페스트 저자가 작성 → 신뢰 입력)
    row_filter: Optional[str] = None  # 혼합 CSV에서 특정 행만 선택하는 컬럼 조건
    trigger_priority: int = 50  # 낮을수록 먼저. 파생값을 만드는 규칙이 앞에 온다
    polarity: Polarity = Polarity.FAIL_WHEN
    provides: List[str] = Field(default_factory=list)  # 이 규칙이 산출하는 파생 state 키

    # 정량일 때
    strategy: Optional[str] = None
    schema_map: Dict[str, str] = Field(default_factory=dict, alias="schema")

    # 정성일 때
    judge: Optional[JudgeSpec] = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# 실행 트레이스 이벤트 — 웹 UI가 소비하는 유일한 스트림
#
# 모든 노드는 결과를 반환하는 것과 별개로 여기에 이벤트를 흘린다.
# UI는 이 스트림만 보고 그래프를 점등하므로, 백엔드/프론트가 완전히 분리된다.
# ---------------------------------------------------------------------------
class EventKind(str, Enum):
    RUN_START = "run.start"
    RUN_END = "run.end"
    NODE_ENTER = "node.enter"
    NODE_EXIT = "node.exit"
    CHEM_PROFILE = "chem.profile"  # RDKit descriptor/flag/SVG
    SPEC_READY = "spec.ready"
    CANDIDATE = "candidate"  # 설계 에이전트가 낸 후보 처방
    RULE_FIRED = "rule.fired"  # 규칙 1건 발동 (원본 CSV 행 + 출처 포함)
    VERDICT = "verdict"  # 후보 1개에 대한 게이트 종합 판정
    JUDGE_SUMMONED = "judge.summoned"
    JUDGE_TOKEN = "judge.token"  # 심사관 스트리밍 델타
    JUDGE_VERDICT = "judge.verdict"
    CONSENSUS = "consensus"
    REFLECT = "reflect"
    EVIDENCE = "evidence"  # 후보별 근거 충족 판정 (Evidence Readiness Gate)
    CONFIRMATION = "confirmation"  # 확인시험 결과 입력 → 근거 재평가 (실험 전 루프)
    APPROVAL = "approval"  # 연구자 승인 → 실행 가능 프로토콜 전환
    WETLAB = "wetlab"
    WARNING = "warning"
    ERROR = "error"
    PREDICTIONS = "predictions"
    LITERATURE = "literature"


class TraceEvent(BaseModel):
    """실행 중 한 시점의 관측 1건."""

    run_id: str
    seq: int = 0
    ts: float = Field(default_factory=time.time)
    node: str  # "gate" | "judge:REV001" | "generator:B" ...
    kind: EventKind
    payload: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Lab-in-the-loop: 실험 결과 판독 → 규격 판정 → 다음 실험 지시
#
# 검증을 통과한 처방이 실제 wet-lab에서 실험되고, 그 측정 데이터(용출률·경도·불순물
# 등)가 다시 시스템으로 들어온다. 이 계층은 결정론적으로 목표 대비 gap을 해석하고,
# 재설계(reflection)에 넘길 피드백을 만든다. 여기에도 "숫자 판단은 계산기가" 원칙을
# 그대로 적용 → 같은 실험 데이터면 같은 해석(오차 0%).
# ---------------------------------------------------------------------------
class WetLabResult(BaseModel):
    """연구원이 재입력하는 실제 실험 측정치 (human-in-the-loop 진입점)."""

    candidate_id: str
    # metric 이름 → 측정값 (예: {"dissolution_30min_percent": 45.0, "tablet_hardness_N": 55})
    measurements: Dict[str, float] = Field(default_factory=dict)
    notes: str = ""


class FeedbackFinding(BaseModel):
    """한 QC 지표에 대한 목표 대비 해석 1건."""

    metric: str
    measured: float
    operator: str  # 목표 이탈로 판정하는 비교 연산자 (예: '<' → target 미만이면 이탈)
    target: float
    off_target: bool
    interpretation: str = ""  # 실패 원인 추론
    suggested_revision: str = ""  # 재설계 방향 제안
    suggested_tests: List[str] = Field(default_factory=list)  # 확인시험 제안(test_id)
    evidence: Dict[str, Any] = Field(default_factory=dict)  # 근거가 된 규칙 행


class FeedbackReport(BaseModel):
    """WetLabResult 1건에 대한 종합 해석 → reflection 루프 입력."""

    candidate_id: str
    findings: List[FeedbackFinding] = Field(default_factory=list)
    reflection_needed: bool = False  # 목표 이탈이 하나라도 있으면 재설계 필요
    summary: str = ""

    @property
    def off_target_findings(self) -> List[FeedbackFinding]:
        return [f for f in self.findings if f.off_target]
