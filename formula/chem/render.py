"""분자 2D 구조를 SVG로 그린다 (웹 UI 좌측 패널용).

RDKit이 SVG 문자열을 직접 내주므로 이미지 파일도, 외부 CDN도 필요 없다 —
SSE 이벤트에 그대로 실어 보낼 수 있다.
"""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D


def to_svg(mol: Chem.Mol, width: int = 380, height: int = 260, dark: bool = False) -> str:
    """분자를 SVG 문자열로 렌더링한다. 실패하면 빈 문자열."""
    if mol is None:
        return ""
    try:
        drawing_mol = Chem.Mol(mol)
        rdDepictor.Compute2DCoords(drawing_mol)
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        options = drawer.drawOptions()
        options.clearBackground = False  # 페이지 배경(라이트/다크)이 그대로 비치게
        if dark:
            options.setAtomPalette({-1: (0.85, 0.87, 0.91)})
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, drawing_mol)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:
        return ""


def highlight_svg(mol: Chem.Mol, smarts: str, width: int = 380, height: int = 260) -> str:
    """SMARTS가 매치된 부분을 강조해 그린다 — "왜 이 플래그가 켜졌는가"를 보여준다."""
    if mol is None or not smarts:
        return to_svg(mol, width, height)
    try:
        pattern = Chem.MolFromSmarts(smarts)
        if pattern is None:
            return to_svg(mol, width, height)
        atoms: set = set()
        bonds: set = set()
        for match in mol.GetSubstructMatches(pattern):
            atoms |= set(match)
            for bond in mol.GetBonds():
                if bond.GetBeginAtomIdx() in match and bond.GetEndAtomIdx() in match:
                    bonds.add(bond.GetIdx())
        drawing_mol = Chem.Mol(mol)
        rdDepictor.Compute2DCoords(drawing_mol)
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        drawer.drawOptions().clearBackground = False
        rdMolDraw2D.PrepareAndDrawMolecule(
            drawer, drawing_mol, highlightAtoms=sorted(atoms), highlightBonds=sorted(bonds)
        )
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:
        return to_svg(mol, width, height)
