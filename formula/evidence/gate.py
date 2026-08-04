"""근거 충족 게이트 (Evidence Readiness Gate) — "실행해도 될 만큼 알고 있는가".

룰 게이트(`formula/checkers/registry.py`)와 이 게이트는 **서로 다른 질문**을 던진다.

    룰 게이트          : 지금 아는 정보 안에 금기·규제 위반이 있는가?
    근거 충족 게이트    : 금기가 없더라도, 이 전략을 실행할 만큼 실제로 알고 있는가?

룰북을 통과했다는 것은 "안전이 확정됐다"가 아니라 "명시적 위반을 발견하지 못했다"이다.
신약 API는 애초에 정보 자체가 없어서 위반이 잡히지 않는 경우가 많다 — 수분·열 안정성이나
배합적합성 자료가 없는 상태로 수계 습식과립 프로토콜을 내보내면, 그 프로토콜은 검증된 것이
아니라 **모르는 것을 모른 채 지나간 것**이다. 그래서 판정 계층을 하나 더 둔다.

원칙은 앞 계층과 같다.

  1. **규칙은 데이터로 관리한다.** 요구 항목은 `database/reference/evidence_requirements.csv`
     한 행이고, 발동 조건(`applies_when`)·충족 조건(`satisfied_when`)은 룰북과 같은 제한 eval로
     평가한다. 항목을 늘리는 일은 CSV 한 줄이지 코드 수정이 아니다.
  2. **시험을 발명하지 않는다.** 각 요구는 `confirmation_test_master.csv`의 실제 시험
     `test_id`를 가리켜야 하고, 없는 id를 가리키는 행은 **로딩 단계에서 버린다.**
     그래서 모든 확인시험 요청에 ICH/USP 출처가 따라붙는다.
  3. **결정론이다.** LLM이 개입하지 않으므로 같은 입력이면 같은 판정이 나온다.

모든 확인시험을 무조건 선행시키지는 않는다. 요구는 세 시점으로 나뉜다(`EvidenceTiming`).

    before_protocol : 결과가 없으면 실행 가능한 공정 프로토콜을 낼 수 없다 (전략을 바꾼다)
    parallel        : 전략은 그대로 두고 병행한다 (세부 조건 최적화 · 중단/변경 기준을 함께 낸다)
    post_batch      : 첫 배치 결과를 본 뒤 조건부로 수행한다 (기존 lab-in-the-loop 영역)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from formula.checkers.applies_when import evaluate, spec_context
from formula.contracts import (
    ConfirmationResult,
    EvidenceAssessment,
    EvidenceGap,
    EvidenceStatus,
    EvidenceTiming,
    FormulationSpec,
    ProtocolReadiness,
    Recipe,
)

REQUIREMENTS_FILE = Path("database") / "reference" / "evidence_requirements.csv"
TEST_MASTER_FILE = Path("database") / "reference" / "confirmation_test_master.csv"


def evidence_context(
    spec: FormulationSpec,
    recipe: Optional[Recipe] = None,
    derived: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """근거 조건식이 참조할 수 있는 변수·헬퍼.

    룰북과 같은 `spec_context`를 바탕으로, 이 계층에만 필요한 것들을 얹는다:
    후보의 공정·전략·성분(처방이 정해진 뒤에야 알 수 있는 값)과, "그 값을 우리가
    실제로 알고 있는가"를 묻는 헬퍼들.
    """
    ctx = spec_context(spec, derived)
    derived = derived or {}
    profile = spec.api_profile

    ingredient_names = [i.name.lower() for i in (recipe.ingredients if recipe else [])]
    roles = [(i.role or "").lower() for i in (recipe.ingredients if recipe else [])]
    flag_names = set(profile.flag_names()) if profile else set()

    def flag(name: str) -> bool:
        """구조 플래그가 검출됐는가 (SMARTS 계층 산출물)."""
        return name in flag_names or bool(spec.properties.get(name))

    def prop(name: str) -> bool:
        return bool(spec.properties.get(name))

    def has_measured(key: str) -> bool:
        """실측값이 있는가. **추정·예측은 실측이 아니다** — 그게 이 게이트의 요지다."""
        return key in spec.measured_params or key in derived

    def ingredient(fragment: str) -> bool:
        return any(fragment.lower() in name for name in ingredient_names)

    def role(name: str) -> bool:
        return name.lower() in roles

    # BCS 등급의 출처를 구분한다. 룰북의 `bcs_classification`은 실측이 있을 때만 파생값을
    # 만들므로, derived에 등급이 있으면 실측 기반이다. 예측 계층이 낸 등급은 spec.properties에
    # 문자열로만 남고 spec.bcs_class 를 채우지 않는다(기준서 13 — 추정으로 등급을 확정하지 않는다).
    bcs_source = "unknown"
    if derived.get("bcs_class"):
        bcs_source = "measured"
    elif spec.properties.get("bcs_source"):
        bcs_source = str(spec.properties["bcs_source"])

    ctx.update({
        "process": (recipe.process if recipe else "") or "",
        "strategy": (recipe.strategy if recipe else "") or "",
        "packaging": (recipe.packaging if recipe else "") or "",
        "ingredients": ingredient_names,
        "is_salt": bool(profile.is_salt) if profile else False,
        "bcs_source": bcs_source,
        "logs_status": str(spec.properties.get("logs_status", "not_connected")),
        "flag": flag,
        "prop": prop,
        "has_measured": has_measured,
        "ingredient": ingredient,
        "role": role,
    })
    return ctx


class EvidenceGate:
    """근거 요구표를 로드해 후보별 충족 여부를 판정한다."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.tests: Dict[str, Dict[str, str]] = self._load_tests()
        self.requirements: List[Dict[str, str]] = []
        self.dropped: List[str] = []
        self._load_requirements()

    # ── 로딩 ────────────────────────────────────────────────────────
    def _load_tests(self) -> Dict[str, Dict[str, str]]:
        path = self.base_dir / TEST_MASTER_FILE
        if not path.exists():
            return {}
        df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
        return {row["test_id"]: row for row in df.to_dict(orient="records")}

    def _load_requirements(self) -> None:
        path = self.base_dir / REQUIREMENTS_FILE
        if not path.exists():
            return
        df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
        for row in df.to_dict(orient="records"):
            test_id = (row.get("confirmation_test_id") or "").strip()
            # 확인시험 마스터에 없는 시험을 요구하는 행은 실행하지 않는다.
            # 근거를 만들 방법이 없는 요구는 연구자에게 "무엇을 하라"를 못 주기 때문이다.
            if test_id not in self.tests:
                self.dropped.append(f"{row.get('requirement_id', '?')}: 미등록 시험 {test_id or '(공란)'}")
                continue
            self.requirements.append(row)

    def summary(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {t.value: 0 for t in EvidenceTiming}
        for row in self.requirements:
            timing = (row.get("timing") or "").strip()
            if timing in counts:
                counts[timing] += 1
        return {
            "requirements": len(self.requirements),
            "by_timing": counts,
            "test_master": len(self.tests),
            "dropped": self.dropped,
        }

    # ── 판정 ────────────────────────────────────────────────────────
    def assess(
        self,
        spec: FormulationSpec,
        recipe: Recipe,
        derived: Optional[Dict[str, Any]] = None,
        resolved: Optional[Dict[str, ConfirmationResult]] = None,
    ) -> EvidenceAssessment:
        """후보 1건의 근거 충족 상태를 판정한다 (LLM 없음 · 같은 입력이면 같은 판정)."""
        ctx = evidence_context(spec, recipe, derived)
        resolved = resolved or {}
        gaps: List[EvidenceGap] = []

        for row in self.requirements:
            if not evaluate(row.get("applies_when", "true"), dict(ctx)):
                continue

            requirement_id = row["requirement_id"]
            result = resolved.get(requirement_id)
            if result is not None:
                status = (EvidenceStatus.SATISFIED if result.outcome == "pass"
                          else EvidenceStatus.FAILED)
                note = " · ".join(part for part in (result.value, result.note) if part)
            elif evaluate(row.get("satisfied_when", "false"), dict(ctx)):
                status = EvidenceStatus.SATISFIED
                note = "이미 확보된 실측값으로 충족"
            else:
                status = EvidenceStatus.MISSING
                note = ""

            test = self.tests.get(row["confirmation_test_id"], {})
            gaps.append(EvidenceGap(
                requirement_id=requirement_id,
                evidence_key=row.get("evidence_key", ""),
                label=row.get("label_kr", ""),
                timing=EvidenceTiming(row.get("timing", "before_protocol")),
                status=status,
                why=row.get("why", ""),
                risk=row.get("risk_if_missing", ""),
                stop_criteria=row.get("stop_criteria", ""),
                result_key=row.get("result_key", ""),
                result_unit=row.get("result_unit", ""),
                test_id=row["confirmation_test_id"],
                test_name=test.get("test_name", ""),
                test_category=test.get("test_category", ""),
                test_design=test.get("test_design", ""),
                output_variable=test.get("output_variable", ""),
                acceptance_logic=test.get("acceptance_logic", ""),
                unit=test.get("unit", ""),
                source_reference=test.get("source_reference", "") or row.get("basis", ""),
                source_url=test.get("source_url", ""),
                result_note=note,
            ))

        assessment = EvidenceAssessment(
            candidate_id=recipe.candidate_id,
            strategy=recipe.strategy or "",
            process=recipe.process or "",
            gaps=gaps,
        )
        assessment.readiness = (ProtocolReadiness.BLOCKED if assessment.blocking
                                else ProtocolReadiness.READY_FOR_REVIEW)
        assessment.summary = self._summarize(assessment)
        return assessment

    def _summarize(self, assessment: EvidenceAssessment) -> str:
        failed = assessment.failed
        if failed:
            names = ", ".join(g.label for g in failed)
            return (f"확인시험 결과가 부적합입니다({names}) — 이 전략은 배제하고 재설계해야 합니다.")
        blocking = assessment.blocking
        if blocking:
            return (f"선행 확인시험 {len(blocking)}건의 결과가 없어 실행 가능한 공정 프로토콜을 낼 수 "
                    f"없습니다. 지금 출력은 근거가 붙은 초안(실행 불가)입니다.")
        parallel = [g for g in assessment.of_timing(EvidenceTiming.PARALLEL)
                    if g.status != EvidenceStatus.SATISFIED]
        return ("선행 근거가 충족되어 연구자 검토용 공정 프로토콜을 낼 수 있습니다"
                + (f" (병행 시험 {len(parallel)}건 함께 수행)." if parallel else "."))

    # ── 산출물 ──────────────────────────────────────────────────────
    def protocol(self, assessment: EvidenceAssessment) -> Dict[str, Any]:
        """확인시험 프로토콜 — 같은 시험을 두 요구가 가리키면 한 번만 싣는다."""
        buckets: Dict[str, List[Dict[str, Any]]] = {t.value: [] for t in EvidenceTiming}
        seen: Dict[str, set] = {t.value: set() for t in EvidenceTiming}
        for gap in assessment.gaps:
            if gap.status == EvidenceStatus.SATISFIED:
                continue
            bucket = gap.timing.value
            if gap.test_id in seen[bucket]:
                continue
            seen[bucket].add(gap.test_id)
            buckets[bucket].append(gap.model_dump(mode="json"))
        return {
            "candidate_id": assessment.candidate_id,
            "readiness": assessment.readiness.value,
            "summary": assessment.summary,
            **buckets,
        }

    def approve(self, assessment: EvidenceAssessment, approver: str = "researcher") -> EvidenceAssessment:
        """연구자 승인 — 근거가 충족된 경우에만 실행 가능 상태로 올린다.

        승인은 사람의 판단이므로 자동으로 일어나지 않는다. 근거가 비어 있는데 승인을
        허용하면 이 게이트 전체가 무의미해지므로, 막힌 상태에서는 승인 자체를 거부한다.
        """
        if assessment.blocking:
            raise ValueError("선행 근거가 충족되지 않아 승인할 수 없습니다.")
        assessment.readiness = ProtocolReadiness.APPROVED
        assessment.approved_by = approver
        assessment.approved_at = time.time()
        parallel = [g for g in assessment.of_timing(EvidenceTiming.PARALLEL)
                    if g.status != EvidenceStatus.SATISFIED]
        assessment.summary = (
            "연구자 승인 완료 — 실행 가능한 공정 프로토콜입니다."
            + (f" 병행 시험 {len(parallel)}건은 배치와 함께 수행하고 중단/변경 기준을 지켜 주세요."
               if parallel else "")
        )
        return assessment
