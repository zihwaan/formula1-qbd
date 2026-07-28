"""자연어 요구 → `FormulationSpec` 번역 (Agent 0).

LLM이 하는 일은 **해석**뿐이다: "소아용 바나나향 해열제" 같은 문장에서 API명·대상 환자·
제형·요구 사항을 뽑아낸다. 숫자 물성은 여기서 지어내지 않는다 — RDKit 계층이 계산한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from formula.agents.client import LLMUnavailable, parse_structured
from formula.chem.profile import build_profile, resolve_smiles
from formula.contracts import EventKind, FormulationSpec
from formula.orchestrator.events import emit

SYSTEM = """당신은 제형 설계 요청을 정량 스펙으로 번역하는 intake 전문가다.

규칙:
- 사용자 문장에서 확인 가능한 것만 채운다. 물성 수치(logP, 용해도, 유동성 등)는 절대 지어내지 않는다.
  그 값들은 별도의 RDKit 계층이 SMILES로부터 계산한다.
- target_patient는 pediatric_under_12 / pediatric / adult / geriatric 중 하나로 정규화한다.
- dosage_form은 tablet / capsule / oral_liquid 중 하나로 정규화한다.
- properties에는 문장에서 명시적으로 확인되는 플래그만 넣는다
  (hygroscopic, light_sensitive, moisture_sensitive, heat_sensitive, coating_required,
   flavoring_used, colorant_used, solvent_used).
- 확신이 없으면 비워 둔다. 빈 값은 후속 계층이 사람에게 이관한다."""


class IntakeResult(BaseModel):
    """intake 에이전트의 구조화 출력."""

    api_name: str = Field(description="주성분(API)의 표준 영문명")
    target_patient: str = Field(default="adult")
    dosage_form: str = Field(default="tablet")
    properties: Dict[str, bool] = Field(default_factory=dict)
    requirements: List[str] = Field(default_factory=list, description="맛·크기 등 자연어 요구")
    notes: str = ""


def translate(
    request: str,
    base_dir: Path,
    smiles: Optional[str] = None,
    node: str = "intake",
    required_excipients: Optional[List[str]] = None,
) -> FormulationSpec:
    """자연어 요구를 스펙으로 옮기고 RDKit 프로파일을 붙인다."""
    emit(node, EventKind.NODE_ENTER, request=request)

    try:
        parsed = parse_structured(IntakeResult, SYSTEM, f"설계 요청:\n{request}")
        source = "llm"
    except LLMUnavailable as exc:
        parsed = _fallback(request)
        source = "deterministic-fallback"
        emit(node, EventKind.WARNING, reason=str(exc), fallback=True)

    spec = FormulationSpec(
        api_name=parsed.api_name,
        target_patient=parsed.target_patient,
        dosage_form=parsed.dosage_form,
        properties=dict(parsed.properties),
        # 사용자가 못 박은 현장 제약. LLM이 해석해 바꿀 수 없는 값이라 그대로 싣는다.
        required_excipients=[e.strip() for e in (required_excipients or []) if e.strip()],
    )

    profile = build_profile(spec.api_name, smiles=smiles, base_dir=base_dir, measured=spec.measured_params)
    spec = spec.with_profile(profile)

    emit(node, EventKind.CHEM_PROFILE,
         api_name=profile.api_name, smiles=profile.smiles, parent_smiles=profile.parent_smiles,
         is_salt=profile.is_salt, descriptors=profile.descriptors,
         flags=[f.model_dump() for f in profile.flags],
         estimates=[e.model_dump() for e in profile.estimates],
         svg=profile.svg, rdkit_version=profile.rdkit_version, warnings=profile.warnings)
    emit(node, EventKind.SPEC_READY, source=source, spec=spec.model_dump(exclude={"api_profile"}))
    emit(node, EventKind.NODE_EXIT, api_name=spec.api_name)
    return spec


def _fallback(request: str) -> IntakeResult:
    """LLM 없이 돌아가는 최소 해석기 — 시연 안전장치.

    알려진 API명 사전과 몇 개 키워드만 본다. 못 찾으면 원문을 그대로 api_name으로 둔다.
    """
    lowered = request.lower()
    # 요청은 한국어로 들어오는 경우가 많다 — 국문 표기도 같은 API로 인식해야 한다.
    aliases = {
        "acetaminophen": ("acetaminophen", "paracetamol", "아세트아미노펜", "파라세타몰", "타이레놀"),
        "fluoxetine": ("fluoxetine", "플루옥세틴"),
        "metformin": ("metformin", "메트포르민", "메트포민"),
        "amlodipine besylate": ("amlodipine", "암로디핀"),
        "aspirin": ("aspirin", "아스피린"),
        "ibuprofen": ("ibuprofen", "이부프로펜"),
    }
    api_name = next(
        (canonical.title() for canonical, names in aliases.items()
         if any(n in lowered for n in names)),
        request.strip()[:60],
    )
    if resolve_smiles(api_name) is None and " " in api_name:
        api_name = api_name.split()[0]

    patient = "adult"
    if any(k in lowered for k in ("소아", "어린이", "pediatric", "child")):
        patient = "pediatric_under_12"
    elif any(k in lowered for k in ("고령", "노인", "geriatric", "elderly")):
        patient = "geriatric"

    form = "tablet"
    if any(k in lowered for k in ("캡슐", "capsule")):
        form = "capsule"
    elif any(k in lowered for k in ("시럽", "현탁", "액상", "syrup", "suspension")):
        form = "oral_liquid"

    properties: Dict[str, Any] = {}
    if any(k in lowered for k in ("향", "flavor", "flavour")):
        properties["flavoring_used"] = True
    if any(k in lowered for k in ("색소", "colorant", "coloring")):
        properties["colorant_used"] = True
    if any(k in lowered for k in ("흡습", "hygroscopic")):
        properties["hygroscopic"] = True
    if any(k in lowered for k in ("광분해", "차광", "light_sensitive", "광안정")):
        properties["light_sensitive"] = True

    return IntakeResult(api_name=api_name, target_patient=patient,
                        dosage_form=form, properties=properties)
