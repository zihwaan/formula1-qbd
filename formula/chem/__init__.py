"""RDKit 기반 API 물리화학 계층.

SMILES 하나로부터 descriptor · 구조 플래그 · 물성 추정을 **결정론적으로** 계산해
`FormulationSpec`의 입력을 만든다. 여기에 LLM은 개입하지 않는다.

원칙 3가지:
  1. 계산은 결정론 — 같은 SMILES면 같은 값. RDKit 버전을 결과에 기록해 재현성을 보장한다.
  2. 추정은 판정 근거가 아니다 — 용해도/투과도는 confidence=low라 BCS class를 확정하지 못한다.
  3. SMARTS는 parent 구조에 적용 — 염 형태는 먼저 제거한다.
"""

from formula.chem.descriptors import compute_descriptors
from formula.chem.estimator import estimate_properties
from formula.chem.profile import build_profile
from formula.chem.structural_flags import detect_flags, strip_salt

__all__ = [
    "build_profile",
    "compute_descriptors",
    "detect_flags",
    "estimate_properties",
    "strip_salt",
]
