"""SMARTS 직접 검사 — 룰북 판정의 출발점을 화면에서 확인할 수 있게 한다.

배합금기 판정은 "이 분자에 이 작용기가 있는가"에서 시작하고, 그 판별은 전부
`structural_flags_smarts.csv`의 SMARTS 패턴으로 한다. 판정을 신뢰하려면 그 패턴이
정말 이 분자에 맞는지를 사람이 직접 확인할 수 있어야 한다 — 이 모듈이 그 통로다.

판정 계층과 같은 규약을 지킨다:
  · 염 형태는 **parent를 추출한 뒤** 매칭한다(besylate·HCl을 벗겨낸다).
  · 원본과 parent 결과를 함께 돌려준다 — 염 때문에 결과가 달라지는 경우를 보이기 위해.
"""

from __future__ import annotations

from typing import Any, Dict, List

from rdkit import Chem, RDLogger

from formula.chem.render import highlight_svg

RDLogger.DisableLog("rdApp.*")   # 잘못된 입력은 우리가 메시지로 처리한다


def _parent(mol: Chem.Mol) -> Chem.Mol:
    """염을 벗겨 가장 큰 조각(parent)을 남긴다. 조각이 하나면 그대로."""
    fragments = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
    if len(fragments) <= 1:
        return mol
    return max(fragments, key=lambda frag: frag.GetNumHeavyAtoms())


def _matches(mol: Chem.Mol, pattern: Chem.Mol) -> List[List[int]]:
    return [list(hit) for hit in mol.GetSubstructMatches(pattern, uniquify=True)]


def match_smarts(smiles: str, smarts: str) -> Dict[str, Any]:
    """SMILES × SMARTS 매칭 결과 + 강조 구조 SVG."""
    result: Dict[str, Any] = {
        "smiles": smiles, "smarts": smarts,
        "smiles_valid": False, "smarts_valid": False,
        "match_count": 0, "matched_atoms": [], "is_salt": False,
        "parent_smiles": "", "parent_match_count": 0,
        "svg": "", "message": "",
    }

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        result["message"] = "SMILES를 해석할 수 없습니다. 표기를 확인해 주세요."
        return result
    result["smiles_valid"] = True

    pattern = Chem.MolFromSmarts(smarts)
    if pattern is None:
        result["message"] = "SMARTS 패턴을 해석할 수 없습니다. 대괄호·조건 표기를 확인해 주세요."
        return result
    result["smarts_valid"] = True

    parent = _parent(mol)
    result["is_salt"] = parent.GetNumAtoms() != mol.GetNumAtoms()
    if result["is_salt"]:
        result["parent_smiles"] = Chem.MolToSmiles(parent)

    whole = _matches(mol, pattern)
    on_parent = _matches(parent, pattern)
    result["match_count"] = len(whole)
    result["parent_match_count"] = len(on_parent)
    result["matched_atoms"] = whole

    # 판정 계층은 parent에서 매칭하므로, 강조도 parent 기준으로 그린다.
    result["svg"] = highlight_svg(parent, smarts)

    if not on_parent:
        result["message"] = "이 분자에는 해당 구조가 없습니다."
    elif result["is_salt"] and len(whole) != len(on_parent):
        result["message"] = (f"염을 벗겨낸 parent에서 {len(on_parent)}곳 일치 "
                             f"(원본 전체로는 {len(whole)}곳) — 판정은 parent 기준입니다.")
    else:
        result["message"] = f"{len(on_parent)}곳에서 일치합니다."
    return result
