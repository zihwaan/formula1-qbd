"""`rdkit_descriptor_definitions.csv`(9행)를 구동해 분자 descriptor를 계산한다.

CSV의 `rdkit_function` 컬럼에는 `Descriptors.MolWt(mol)` 같은 **호출식 문자열**이 들어 있다.
이걸 eval하지 않는다 — descriptor_id → 파이썬 함수의 화이트리스트 dispatch 표로 옮긴다.
CSV는 "무엇을 계산하는지"의 문서이고, 실제 호출 대상은 코드가 고정한다.

산출 키는 룰북이 실제로 쓰는 이름을 따른다(`clogp`, `molecular_weight`, `tpsa` …).
reference/api_physchem_thresholds.csv 의 `property_name`과 일치해야 임계값 판정이 걸린다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List

import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors

# descriptor_id → (룰북에서 쓰는 이름, 계산 함수)
# CSV가 늘어나면 여기에 한 줄 추가한다. CSV에만 있고 여기 없으면 경고로 보고된다.
_DISPATCH: Dict[str, tuple[str, Callable[[Chem.Mol], Any]]] = {
    "DSC001": ("molecular_weight", Descriptors.MolWt),
    "DSC002": ("clogp", Descriptors.MolLogP),
    "DSC003": ("tpsa", Descriptors.TPSA),
    "DSC004": ("hbond_donors", Descriptors.NumHDonors),
    "DSC005": ("hbond_acceptors", Descriptors.NumHAcceptors),
    "DSC006": ("rotatable_bonds", Descriptors.NumRotatableBonds),
    "DSC007": ("aromatic_rings", Descriptors.NumAromaticRings),
    # CalcCrippenDescriptors는 (logP, MR) 2-tuple을 돌려준다 — MR은 두 번째 원소
    "DSC008": ("molar_refractivity", lambda m: rdMolDescriptors.CalcCrippenDescriptors(m)[1]),
    "DSC009": ("primary_amine_fragments", Descriptors.fr_NH2),
}

DEFAULT_CSV = "database/00_master/rdkit_descriptor_definitions.csv"


@lru_cache(maxsize=8)
def _read_csv(path: Path) -> tuple[Dict[str, Any], ...]:
    """CSV는 실행 중 바뀌지 않으므로 한 번만 읽는다(웹 요청마다 재파싱 방지)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
    return tuple(df.to_dict(orient="records"))


def load_definitions(base_dir: Path, csv_path: str = DEFAULT_CSV) -> List[Dict[str, Any]]:
    return list(_read_csv(base_dir / csv_path))


def compute_descriptors(
    mol: Chem.Mol,
    base_dir: Path,
    csv_path: str = DEFAULT_CSV,
) -> tuple[Dict[str, float], List[str]]:
    """CSV에 정의된 descriptor를 전부 계산한다.

    반환: (이름 → 값, 경고 목록)
    """
    values: Dict[str, float] = {}
    warnings: List[str] = []

    for row in load_definitions(base_dir, csv_path):
        descriptor_id = row.get("descriptor_id", "")
        entry = _DISPATCH.get(descriptor_id)
        if entry is None:
            warnings.append(
                f"{descriptor_id}({row.get('descriptor_name')}): 계산 함수 미등록 — "
                f"formula/chem/descriptors.py 의 _DISPATCH에 추가 필요"
            )
            continue
        name, fn = entry
        try:
            values[name] = float(fn(mol))
        except Exception as exc:  # RDKit 계산 실패는 값 누락으로 처리(판정은 그 규칙만 건너뜀)
            warnings.append(f"{descriptor_id}({name}): 계산 실패 — {exc}")

    return values, warnings


def lipinski_veber(values: Dict[str, float]) -> Dict[str, bool]:
    """Lipinski Rule of 5 / Veber 규칙 — 추정이 아니라 정의상 계산이라 confidence=high.

    (physchem_estimation_rules.csv 의 EST004 / EST005 에 해당)
    """
    out: Dict[str, bool] = {}
    if all(k in values for k in ("molecular_weight", "clogp", "hbond_donors", "hbond_acceptors")):
        out["lipinski_pass"] = (
            values["molecular_weight"] <= 500
            and values["clogp"] <= 5
            and values["hbond_donors"] <= 5
            and values["hbond_acceptors"] <= 10
        )
    if all(k in values for k in ("rotatable_bonds", "tpsa")):
        out["veber_pass"] = values["rotatable_bonds"] <= 10 and values["tpsa"] <= 140
    return out
