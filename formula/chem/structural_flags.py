"""SMARTS 구조 플래그 검출 — 기준서 v1.1 §3~§12 구현.

이 플래그가 `incompatibility_1to1.csv`의 배합금기 판정(HARD_FAIL 가능)을 직접 트리거하므로
오탐 1건 = 잘못된 반려, 미탐 1건 = 놓친 금기다. 그래서 안전장치를 둔다.

  1. **염 제거** — SMARTS는 parent 구조에 적용한다. 안 하면 besylate/HCl 같은 염 형태에서
     플래그와 descriptor가 어긋난다.
  2. **fragment 교차검증** — SMARTS 매치 수와 RDKit `fr_*` 카운트를 대조해 불일치를 경고한다.
  3. **아민/아미드 분리** — 기준서 §4가 요구하는 대로 `is_amide_not_amine` 같은 단일 Boolean을
     쓰지 않는다. amine 패턴 자체가 `!$(NC=O)` 등으로 amide·sulfonamide·urea를 배제하므로
     한 분자에 amine과 amide가 동시에 있어도 각각 정확히 검출된다.

기준서가 요구하는 **판정 계층 분리**를 alert_level로 구현한다.
  fact              구조 사실 — 해당 motif가 존재한다
  conditional_alert 구조 경고 — 조건(수분·pH·금속·빛…)이 함께 있어야 위험이 된다
  hard_alert        높은 구조 경고 — 그래도 단독 Exclude가 아니라 확인시험 요청이다

레지스트리(`structural_flags_registry.csv`)는 데이터다. 새 플래그를 추가하는 일은 코딩이
아니라 행 추가이며, 후처리가 필요한 것만 `postprocess` 칸으로 선언한다.
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

# v1.1 레지스트리. 구 5행 파일은 회귀 비교용으로 남는다.
DEFAULT_CSV = "database/00_master/structural_flags_registry.csv"
LEGACY_CSV = "database/00_master/structural_flags_smarts.csv"
REGISTRY_VERSION = "1.1.0"

# SMARTS 매치와 대조할 RDKit fragment 카운터 (있는 것만).
_FRAGMENT_FN = {
    "has_primary_aliphatic_amine": Fragments.fr_NH2,
    "has_aromatic_amine_aniline": Fragments.fr_Ar_NH,
    "has_ester": Fragments.fr_ester,
    "has_amide": Fragments.fr_amide,
    "has_carboxylic_acid": Fragments.fr_COO,
    "has_phenol": Fragments.fr_phenol,
    "has_aldehyde": Fragments.fr_aldehyde,
    "has_nitro_group": Fragments.fr_nitro,
    "has_urea": Fragments.fr_urea,
    "has_epoxide": Fragments.fr_epoxide,
}


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


@lru_cache(maxsize=256)
def _compile_smarts(smarts: str):
    """SMARTS 컴파일은 비싸다 — 패턴 수가 한정적이므로 전량 캐시한다."""
    return Chem.MolFromSmarts(smarts) if smarts else None


def load_flag_definitions(base_dir: Path, csv_path: str = DEFAULT_CSV) -> List[Dict[str, Any]]:
    path = base_dir / csv_path
    if not path.exists():          # 레지스트리가 없으면 구 파일로 내려간다
        path = base_dir / LEGACY_CSV
    return list(_read_flags(path))


def _split(value: str) -> List[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def _ring_filtered(mol: Chem.Mol, matches, size: int) -> List[List[int]]:
    """매치된 원자가 지정 크기 고리에 속하는 것만 남긴다.

    기준서 §7: β/γ/δ-lactam과 β-lactone은 같은 SMARTS를 쓰고 **ring-info 후처리**로
    가른다. 4원 고리(β)는 ring strain 때문에 위험도가 달라 반드시 분리해야 한다.
    """
    ring_info = mol.GetRingInfo()
    kept: List[List[int]] = []
    for match in matches:
        # 매치에는 고리 밖 원자(예: 카르보닐 산소)가 섞인다. 고리 소속 원자만 검사해야
        # 한다 — 전체를 요구하면 β-lactam이 영원히 검출되지 않는다(실제로 겪은 미탐).
        ring_atoms = [idx for idx in match if ring_info.NumAtomRings(idx) > 0]
        if not ring_atoms:
            continue
        for ring in ring_info.AtomRings():
            if len(ring) == size and all(idx in ring for idx in ring_atoms):
                kept.append(list(match))
                break
    return kept


def _apply_postprocess(mol: Chem.Mol, rule: str, matches) -> List[List[int]]:
    """레지스트리의 `postprocess` 선언을 적용한다.

    `ring_size:N` — 매치가 N원 고리에 속할 때만 인정
    `count_ge:N`  — 매치 수가 N 이상일 때만 플래그를 세운다(예: polyphenol = phenol 2개 이상)
    """
    if not rule:
        return [list(m) for m in matches]
    key, _, value = rule.partition(":")
    if key == "ring_size":
        return _ring_filtered(mol, matches, int(value))
    if key == "count_ge":
        return [list(m) for m in matches] if len(matches) >= int(value) else []
    return [list(m) for m in matches]


def detect_flags(
    parent: Chem.Mol,
    base_dir: Path,
    csv_path: str = DEFAULT_CSV,
) -> Tuple[List[StructuralFlag], List[str]]:
    """parent 구조에 레지스트리 전체를 적용한다.

    반환: (플래그 목록, 경고 목록). 경고는 fragment 카운트 교차검증 불일치다.
    """
    definitions = load_flag_definitions(base_dir, csv_path)
    flags: List[StructuralFlag] = []
    warnings: List[str] = []
    if parent is None:
        return flags, ["구조를 파싱하지 못해 구조 플래그를 계산할 수 없음"]

    for row in definitions:
        name = row.get("flag_name", "")
        smarts = (row.get("smarts", "") or row.get("smarts_pattern", "")).strip()
        pattern = _compile_smarts(smarts)
        if pattern is None:
            warnings.append(f"{row.get('flag_id', name)}: SMARTS 컴파일 실패 — 이 플래그는 건너뜀")
            continue

        raw = parent.GetSubstructMatches(pattern, uniquify=True)
        indices = _apply_postprocess(parent, row.get("postprocess", ""), raw)

        # fragment 카운터와 대조 (있는 항목만). 불일치는 오탐/미탐 신호다.
        fragment_count = None
        cross_ok = True
        counter = _FRAGMENT_FN.get(name)
        if counter is not None and not row.get("postprocess"):
            try:
                fragment_count = int(counter(parent))
                cross_ok = (fragment_count > 0) == bool(indices)
                if not cross_ok:
                    warnings.append(
                        f"{name}: SMARTS {len(indices)}건 vs fragment 카운트 {fragment_count} 불일치")
            except Exception:
                fragment_count = None

        flags.append(StructuralFlag(
            flag_id=row.get("flag_id", name),
            flag_name=name,
            present=bool(indices),
            smarts=smarts,
            match_count=len(indices),
            atom_indices=indices,
            section=row.get("section", ""),
            rulebook_group=row.get("rulebook_group", ""),
            specificity=row.get("specificity", "medium"),
            alert_level=row.get("alert_level", "fact"),
            interpretation=row.get("interpretation", ""),
            required_cofactors=_split(row.get("required_cofactors", "")),
            applicability=row.get("applicability", "parent"),
            false_positive_notes=row.get("false_positive_notes", ""),
            confirmation_test=row.get("confirmation_test", ""),
            smarts_version=row.get("smarts_version", REGISTRY_VERSION),
            fragment_count=fragment_count,
            cross_check_ok=cross_ok,
            validation_status=row.get("validation_status", "draft"),
            triggers_rule=row.get("triggers_rule", ""),
        ))

    warnings.extend(_check_amine_amide_separation(flags))
    return flags, warnings


def _check_amine_amide_separation(flags: List[StructuralFlag]) -> List[str]:
    """아민 패턴이 amide 질소를 잡지 않았는지 확인한다.

    기준서 §4는 `is_amide_not_amine` 같은 단일 Boolean을 금지한다 — 한 분자에 amine과
    amide가 동시에 있을 수 있기 때문이다. 대신 둘이 함께 잡히면 별개 부위인지 패턴 누수인지
    원자 인덱스로 확인하라는 안내만 남긴다(아세트아미노펜 오탐 방지 장치의 후속판).
    """
    by_name = {f.flag_name: f for f in flags}
    amide = by_name.get("has_amide")
    if amide is None or not amide.present:
        return []
    leaked = [
        name for name in ("has_primary_aliphatic_amine", "has_secondary_aliphatic_amine")
        if by_name.get(name) is not None and by_name[name].present
    ]
    if leaked:
        return [f"amide와 지방족 아민이 동시 검출({', '.join(leaked)}) — "
                "별개 부위인지 패턴 누수인지 원자 인덱스로 확인 권장"]
    return []
