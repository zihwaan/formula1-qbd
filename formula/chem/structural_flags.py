"""`structural_flags_smarts.csv`(5행)의 SMARTS로 API 구조 플래그를 검출한다.

이 플래그가 `incompatibility_1to1.csv`의 배합금기 판정(HARD_FAIL 가능)을 직접 트리거하므로
오탐 1건 = 잘못된 반려, 미탐 1건 = 놓친 금기다. 그래서 세 가지 안전장치를 둔다.

  1. **염 제거** — SMARTS는 parent 구조에 적용한다. 원본 CSV의 FLG001 note가 요구하는 사항으로,
     안 하면 besylate/HCl 같은 염 형태에서 플래그와 descriptor가 어긋난다.
  2. **fragment 교차검증** — SMARTS 매치 수와 RDKit `fr_*` 카운트를 대조해 불일치를 경고한다.
  3. **아미드 상호배제** — FLG005(is_amide_not_amine)가 참인데 아민 플래그도 참이면 경고한다.
     아세트아미노펜(아미드)을 1차 아민으로 오탐하는 것을 막기 위한 장치다.

CSV의 `validation_status`가 전 행 UNTESTED이므로, 판정에 쓰이는 값은 `PROVISIONAL`로 표기된다
(formula/contracts.py의 VERIFICATION_POLICY 참조). 검증은 tests/test_smarts.py가 담당한다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import Fragments
from rdkit.Chem.MolStandardize import rdMolStandardize

from formula.contracts import StructuralFlag

RDLogger.DisableLog("rdApp.*")  # SMILES 파싱 경고를 우리 warnings로 통일

DEFAULT_CSV = "database/00_master/structural_flags_smarts.csv"

_AMINE_FLAGS = {"has_primary_amine", "has_secondary_amine"}
_AMIDE_FLAG = "is_amide_not_amine"


def strip_salt(mol: Chem.Mol) -> Tuple[Chem.Mol, bool]:
    """염을 제거하고 parent(최대 유기 fragment)를 돌려준다.

    반환: (parent 분자, 염이었는가)
    """
    if mol is None:
        return mol, False
    fragments = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
    if len(fragments) <= 1:
        return mol, False
    try:
        parent = rdMolStandardize.LargestFragmentChooser().choose(mol)
        return (parent if parent is not None else mol), True
    except Exception:
        # 표준화 실패 시 원자 수가 가장 많은 fragment를 parent로 본다
        return max(fragments, key=lambda f: f.GetNumAtoms()), True


@lru_cache(maxsize=8)
def _read_flags(path: Path) -> Tuple[Dict[str, Any], ...]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
    return tuple(df.to_dict(orient="records"))


@lru_cache(maxsize=32)
def _compile_smarts(smarts: str):
    """SMARTS 컴파일은 비싸다 — 패턴 수가 적으므로 전량 캐시한다."""
    return Chem.MolFromSmarts(smarts) if smarts else None


def load_flag_definitions(base_dir: Path, csv_path: str = DEFAULT_CSV) -> List[Dict[str, Any]]:
    return list(_read_flags(base_dir / csv_path))


def detect_flags(
    parent: Chem.Mol,
    base_dir: Path,
    csv_path: str = DEFAULT_CSV,
) -> Tuple[List[StructuralFlag], List[str]]:
    """parent 구조에 SMARTS를 적용해 구조 플래그를 만든다.

    반환: (플래그 목록, 경고 목록)
    """
    flags: List[StructuralFlag] = []
    warnings: List[str] = []

    for row in load_flag_definitions(base_dir, csv_path):
        smarts = row.get("smarts_pattern", "").strip()
        flag_name = row.get("flag_name", "").strip()
        pattern = _compile_smarts(smarts)
        if pattern is None:
            warnings.append(f"{row.get('flag_id')}({flag_name}): SMARTS 파싱 실패 — {smarts!r}")
            continue

        matches = len(parent.GetSubstructMatches(pattern))

        # fr_* fragment 카운트와 교차검증 (CSV가 rdkit_fragment_fn을 지정한 행만)
        fragment_count = None
        cross_ok = True
        fn_name = row.get("rdkit_fragment_fn", "").strip()
        if fn_name:
            fn = getattr(Fragments, fn_name, None)
            if fn is None:
                warnings.append(f"{flag_name}: rdkit_fragment_fn '{fn_name}' 없음")
            else:
                try:
                    fragment_count = int(fn(parent))
                    cross_ok = fragment_count == matches
                    if not cross_ok:
                        warnings.append(
                            f"{flag_name}: SMARTS {matches}건 vs {fn_name} {fragment_count}건 불일치"
                        )
                except Exception as exc:
                    warnings.append(f"{flag_name}: {fn_name} 계산 실패 — {exc}")

        flags.append(
            StructuralFlag(
                flag_id=row.get("flag_id", ""),
                flag_name=flag_name,
                present=matches > 0,
                smarts=smarts,
                match_count=matches,
                fragment_count=fragment_count,
                cross_check_ok=cross_ok,
                validation_status=row.get("validation_status", "UNTESTED"),
                triggers_rule=row.get("triggers_rule", ""),
            )
        )

    warnings.extend(_check_amide_exclusivity(flags))
    return flags, warnings


def _check_amide_exclusivity(flags: List[StructuralFlag]) -> List[str]:
    """아미드이면서 동시에 아민으로 잡히면 Maillard 오탐 위험 — 경고를 남긴다.

    FLG005의 설계 의도가 바로 이 오탐 방지다(원본 CSV note: "아세트아미노펜은 아미드").
    """
    by_name = {f.flag_name: f for f in flags}
    amide = by_name.get(_AMIDE_FLAG)
    if amide is None or not amide.present:
        return []
    both = [name for name in _AMINE_FLAGS if by_name.get(name) and by_name[name].present]
    if not both:
        return []
    return [
        f"아미드({_AMIDE_FLAG})와 아민({', '.join(both)})이 동시에 검출됨 — "
        f"분자에 두 작용기가 모두 있거나 SMARTS 오탐일 수 있다. 배합금기 판정 전 확인 필요."
    ]
