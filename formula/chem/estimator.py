"""`physchem_estimation_rules.csv`(5행)로 descriptor → 물성을 추정한다.

**여기서 나온 값은 판정 근거가 아니다.** 원본 CSV가 명시한 대로:
  - EST001 용해도 추정: confidence=low, "logP는 용해도의 근사일 뿐. 단독 BCS 확정 금지"
  - EST002 투과도 추정: confidence=low, "투과도는 RDKit로 신뢰성 있게 안 나옴"
  → 둘 다 `action_if_low_confidence = ESCALATE_TO_HUMAN`

반면 EST004(Lipinski) / EST005(Veber)는 confidence=high — 추정이 아니라 정의상 계산이라
그대로 써도 된다.

그래서 이 모듈은 `override_by_experimental` 규약을 강제한다:
실측값이 이미 있으면 추정을 만들지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from formula.chem.descriptors import lipinski_veber
from formula.contracts import PhysChemEstimate

DEFAULT_CSV = "database/00_master/physchem_estimation_rules.csv"

# 실측이 들어오면 추정을 덮어쓰지 못하게 막을 때 참조하는 키
_EXPERIMENTAL_KEYS = {
    "EST001": ("equilibrium_solubility", "intrinsic_solubility", "solubility_mg_ml"),
    "EST002": ("fraction_absorbed", "caco2_papp", "permeability_class"),
    "EST003": ("dose_solubility_volume",),
}


def estimate_properties(
    descriptors: Dict[str, float],
    base_dir: Path,
    measured: Optional[Dict[str, Any]] = None,
    csv_path: str = DEFAULT_CSV,
) -> Tuple[List[PhysChemEstimate], List[str]]:
    """descriptor로부터 물성 힌트를 만든다.

    반환: (추정 목록, 경고 목록). 경고에는 '사람 판단 필요' 항목이 포함된다.
    """
    measured = measured or {}
    df = pd.read_csv(base_dir / csv_path, dtype=str, keep_default_na=False).fillna("")
    rules = df.to_dict(orient="records")
    flags = lipinski_veber(descriptors)

    estimates: List[PhysChemEstimate] = []
    warnings: List[str] = []

    for row in rules:
        estimate_id = row.get("estimate_id", "")
        confidence = row.get("confidence", "low").strip().lower()
        overridable = str(row.get("override_by_experimental", "")).lower().startswith("yes")

        # 실측이 있으면 추정하지 않는다 — 원본 CSV의 override_by_experimental 규약
        if overridable and any(k in measured for k in _EXPERIMENTAL_KEYS.get(estimate_id, ())):
            warnings.append(f"{estimate_id}: 실측값이 있어 추정을 건너뜀(실측 우선)")
            continue

        value = _evaluate(estimate_id, descriptors, flags)
        if value is None:
            continue

        estimates.append(
            PhysChemEstimate(
                estimate_id=estimate_id,
                property=row.get("estimated_property", ""),
                value=value,
                confidence=confidence,
                override_by_experimental=overridable,
                action_if_low_confidence=row.get("action_if_low_confidence", ""),
                basis=row.get("estimation_logic", ""),
            )
        )
        if confidence == "low":
            warnings.append(
                f"{estimate_id}({row.get('estimated_property')}): 저신뢰 추정 → "
                f"{row.get('action_if_low_confidence') or 'ESCALATE_TO_HUMAN'}. 판정 근거로 쓰지 말 것."
            )

    return estimates, warnings


def _evaluate(estimate_id: str, d: Dict[str, float], flags: Dict[str, bool]) -> Any:
    """추정 규칙 하나를 계산한다. 필요한 descriptor가 없으면 None."""
    if estimate_id == "EST001":  # 용해도 경향 (정성적, 저신뢰)
        if "clogp" not in d or "tpsa" not in d:
            return None
        return "low" if (d["clogp"] > 3 and d["tpsa"] < 75) else "high"

    if estimate_id == "EST002":  # 투과도 경향 (Veber/Egan 계열, 저신뢰)
        if "tpsa" not in d or "clogp" not in d:
            return None
        return "high" if (d["tpsa"] <= 140 and -1 <= d["clogp"] <= 5) else "low"

    if estimate_id == "EST003":  # dose/solubility 비율 — 용량·실측 용해도가 있어야 계산 가능
        return None  # 최고용량(mg)이 자연어 요구에서 파싱돼 들어와야 함 → intake 단계 책임

    if estimate_id == "EST004":
        return flags.get("lipinski_pass")

    if estimate_id == "EST005":
        return flags.get("veber_pass")

    return None
