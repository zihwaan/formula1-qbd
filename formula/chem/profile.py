"""SMILES → `ApiProfile` 조립. RDKit 계층의 진입점.

파이프라인 (개발자 가이드 2장 Priority 0 단계):
    SMILES → 파싱 → 염 제거(parent) → descriptor 계산 → SMARTS 구조 플래그 → 물성 추정

descriptor는 **원본 분자**로, 구조 플래그는 **parent**로 계산한다.
(염 형태의 분자량은 염을 포함한 값이 실제 처방 중량과 맞고, 작용기 반응성은 parent가 기준)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import rdkit
from rdkit import Chem

from formula.chem.descriptors import compute_descriptors, lipinski_veber
from formula.chem.estimator import estimate_properties
from formula.chem.render import to_svg
from formula.chem.descriptors_v2 import (
    CALC_OPTIONS,
    derived_screens,
    extended_descriptors,
    structure_quality,
    versions,
)
from formula.chem.structural_flags import detect_flags, strip_salt
from formula.contracts import ApiProfile, FormulationSpec

# 데모/테스트에서 자주 쓰는 API의 SMILES. 실제 운영에서는 intake 단계가 조회해 넣는다.
KNOWN_SMILES = {
    "acetaminophen": "CC(=O)Nc1ccc(O)cc1",
    "paracetamol": "CC(=O)Nc1ccc(O)cc1",
    "p-aminophenol": "Nc1ccc(O)cc1",
    "metformin": "CN(C)C(=N)NC(=N)N",
    "fluoxetine": "CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1",
    "fluoxetine hcl": "CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1.Cl",
    "amlodipine besylate": (
        "CCOC(=O)C1=C(COCCN)NC(C)=C(C1c1ccccc1Cl)C(=O)OC.OS(=O)(=O)c1ccccc1"
    ),
    "aspirin": "CC(=O)Oc1ccccc1C(=O)O",
    "ibuprofen": "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
}


def resolve_smiles(api_name: str) -> Optional[str]:
    """API 이름으로 알려진 SMILES를 찾는다(내장 사전 한정)."""
    return KNOWN_SMILES.get(api_name.strip().lower())


def smiles_error(smiles: Optional[str]) -> Optional[str]:
    """사용자가 준 SMILES가 못 읽히면 사유 문자열, 읽히면 None.

    입력 경계에서 바로 되돌려 주려고 분리했다. 오타 하나('O'를 '0'으로)로 구조가
    비어 버리면 구조 기반 규칙이 하나도 발동하지 않는데, 그걸 60초짜리 실행을 다
    돌린 뒤에 알려 주면 사용자는 '규칙이 없나 보다'로 읽는다.
    """
    text = str(smiles or "").strip()
    if not text:
        return None
    if Chem.MolFromSmiles(text) is None:
        return (f"SMILES를 해석하지 못했습니다: {text!r} — 오타(예: 산소 O 대신 숫자 0)를 "
                "확인해 주세요. 구조를 못 읽으면 구조 기반 배합금기 판정이 성립하지 않습니다.")
    return None


def build_profile(
    api_name: str,
    smiles: Optional[str] = None,
    base_dir: Optional[Path] = None,
    measured: Optional[dict] = None,
    render: bool = True,
) -> ApiProfile:
    """SMILES(또는 알려진 API 이름)로부터 물리화학 프로파일을 만든다.

    SMILES를 못 얻거나 파싱에 실패해도 예외를 던지지 않는다 —
    warnings에 사유를 남긴 빈 프로파일을 돌려주고, 상위 계층이 사람에게 이관한다.
    """
    base_dir = Path(base_dir or Path(__file__).resolve().parent.parent.parent)
    smiles = smiles or resolve_smiles(api_name) or ""
    profile = ApiProfile(api_name=api_name, smiles=smiles, rdkit_version=rdkit.__version__)

    if not smiles:
        profile.structure_resolved = False
        profile.warnings.append(
            f"'{api_name}'의 SMILES를 알 수 없어 물성 계산을 건너뜀 → 구조 기반 배합금기 판정 불가"
        )
        return profile

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        # 여기서 이름 사전으로 되돌아가 다른 구조를 대신 쓰지 않는다 — 사용자가 친 구조를
        # 말없이 다른 분자로 바꾸는 것이야말로 이 시스템이 금지하는 추측이다.
        profile.structure_resolved = False
        profile.warnings.append(f"SMILES 파싱 실패: {smiles!r}")
        return profile

    profile.structure_resolved = True
    parent, is_salt = strip_salt(mol)
    profile.is_salt = is_salt
    profile.parent_smiles = Chem.MolToSmiles(parent)
    if is_salt:
        profile.warnings.append(
            f"염 형태로 판단 — 구조 플래그는 parent({profile.parent_smiles})에 적용했다"
        )

    descriptors, descriptor_warnings = compute_descriptors(mol, base_dir)
    profile.descriptors = descriptors
    profile.warnings.extend(descriptor_warnings)

    # Lipinski/Veber는 정의상 계산이라 descriptor와 같은 층위로 노출한다
    for name, value in lipinski_veber(descriptors).items():
        profile.descriptors[name] = float(value)

    flags, flag_warnings = detect_flags(parent, base_dir)
    profile.flags = flags
    profile.warnings.extend(flag_warnings)

    # ── 기준서 v1.1 확장분 ────────────────────────────────────────────
    # §1 구조 품질 · §2 확장 descriptor · §2.1 파생 스크리닝 · 계산옵션/버전 기록.
    # 원본 mol 기준으로 염·전하 상태를 보고, descriptor는 parent 기준으로 계산한다.
    profile.structure_quality = structure_quality(smiles)
    profile.descriptors.update(extended_descriptors(parent))
    profile.derived_screens = derived_screens(
        parent, descriptors, profile.descriptors,
        [f.flag_name for f in flags if f.present])
    profile.versions = versions()
    profile.versions["calc_options"] = "; ".join(f"{k}={v}" for k, v in CALC_OPTIONS.items())

    estimates, estimate_warnings = estimate_properties(descriptors, base_dir, measured=measured)
    profile.estimates = estimates
    profile.warnings.extend(estimate_warnings)

    if render:
        profile.svg = to_svg(mol)

    return profile


def apply_to_spec(spec: FormulationSpec, profile: Optional[ApiProfile] = None) -> FormulationSpec:
    """스펙에 물리화학 프로파일을 병합한다. 실측값은 덮어쓰지 않는다."""
    profile = profile or build_profile(spec.api_name, measured=spec.measured_params)
    return spec.with_profile(profile)
