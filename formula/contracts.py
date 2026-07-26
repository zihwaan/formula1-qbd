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
    """SMARTS 구조 플래그 1건 (structural_flags_smarts.csv 1행에 대응)."""

    flag_id: str
    flag_name: str  # 예: has_primary_amine
    present: bool
    smarts: str
    match_count: int = 0
    fragment_count: Optional[int] = None  # rdkit fr_* 카운트 (교차검증용)
    cross_check_ok: bool = True  # SMARTS와 fragment 카운트가 일치하는가
    validation_status: str = "UNTESTED"  # 원본 CSV의 validation_status
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

    def flag_names(self) -> List[str]:
        """참으로 판정된 구조 플래그 이름 목록."""
        return [f.flag_name for f in self.flags if f.present]

    def functional_groups(self) -> List[str]:
        """배합금기 룰북의 `api_functional_group`과 조인할 작용기 이름.

        `has_primary_amine` → `primary_amine` 형태로 접두어만 벗긴다.
        """
        return [f.flag_name[4:] if f.flag_name.startswith("has_") else f.flag_name
                for f in self.flags if f.present]


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
    WETLAB = "wetlab"
    WARNING = "warning"
    ERROR = "error"


class TraceEvent(BaseModel):
    """실행 중 한 시점의 관측 1건."""

    run_id: str
    seq: int = 0
    ts: float = Field(default_factory=time.time)
    node: str  # "gate" | "judge:REV001" | "generator:B" ...
    kind: EventKind
    payload: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Closed-loop: Wet-lab 실험 결과 재입력 → 결과 해석 & 피드백
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
