"""기준서 v1.1 §1·§2·§2.1·§12 — 구조 품질, 확장 descriptor, 파생 스크리닝 지표.

기존 `descriptors.py`(9행 CSV 구동)는 룰북 임계값 판정용 이름을 그대로 유지하고,
이 모듈이 기준서가 요구하는 확장 필드를 얹는다. 두 산출은 키가 겹치지 않는다.

**이 모듈이 계산하는 값은 전부 구조에서 재현 가능한 값이다.** 물성의 실험적 확정값이
아니며, 기준서 §2가 못 박은 대로 cLogP·QED·TPSA를 공정 하드 게이트로 쓰지 않는다.
Lipinski·Veber는 사전 스크리닝 신호일 뿐 BCS 등급을 대체하지 못한다(§2.1, §13).

기준서가 "계산 옵션을 반드시 기록하라"고 한 항목(회전결합 정의, HBD/HBA 정의,
RDKit 버전, 정규화 버전, 레지스트리 버전)은 `versions`/`options`로 함께 낸다.
"""

from __future__ import annotations

from typing import Any, Dict, List

import rdkit
from rdkit import Chem, RDLogger
from rdkit.Chem import Crippen, Descriptors, QED, rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

RDLogger.DisableLog("rdApp.*")

NORMALIZATION_VERSION = "1.1.0"

# 회전결합·HBD/HBA 정의는 값이 달라지므로 무엇을 썼는지 고정 기록한다(기준서 §2 계산옵션).
CALC_OPTIONS = {
    "rotatable_bond_count": "Strict",
    "hbd_hba_definition": "RDKit Lipinski (CalcNumHBD/CalcNumHBA)",
    "aromaticity_model": "RDKit default",
    "salt_handling": "LargestFragmentChooser parent",
}


# ---------------------------------------------------------------------------
# §1 입력 구조 정규화 및 품질 플래그
# ---------------------------------------------------------------------------
_INORGANIC_COUNTERIONS = {
    "Cl", "Br", "I", "F", "Na", "K", "Ca", "Mg", "Zn", "Li", "NH4",
}


def structure_quality(smiles: str, input_form: str = "") -> Dict[str, Any]:
    """파싱·염·전하·입체 상태를 점검한다.

    기준서 §1: parent를 만들더라도 **염 형태 자체가 제제 특성에 영향을 준다.**
    그래서 parent_smiles와 실제 투입 형태(formulation_input_smiles)를 따로 보존한다.
    """
    out: Dict[str, Any] = {
        "structure_parse_success": False,
        "sanitization_success": False,
        "fragment_count": 0,
        "is_multicomponent": False,
        "has_counterion": False,
        "counterion_list": [],
        "input_form": input_form or "unspecified",
        "formulation_input_smiles": smiles,
        "formal_charge": 0,
        "absolute_atomic_charge_sum": 0,
        "is_zwitterion": False,
        "stereocenter_count": 0,
        "unspecified_stereocenter_count": 0,
        "double_bond_stereo_count": 0,
        "unspecified_double_bond_stereo_count": 0,
        "parent_smiles": "",
        "standardized_smiles": "",
        "structure_hash": "",
        "normalization_version": NORMALIZATION_VERSION,
    }
    if not smiles:
        return out

    mol = Chem.MolFromSmiles(smiles, sanitize=False)
    if mol is None:
        return out
    out["structure_parse_success"] = True
    try:
        Chem.SanitizeMol(mol)
        out["sanitization_success"] = True
    except Exception:
        return out   # sanitization 실패 → Invalid_Input, 이후 분석 중단

    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
    out["fragment_count"] = len(frags)
    out["is_multicomponent"] = len(frags) > 1

    parent = mol
    if len(frags) > 1:
        try:
            parent = rdMolStandardize.LargestFragmentChooser().choose(mol) or mol
        except Exception:
            parent = max(frags, key=lambda f: f.GetNumAtoms())
        parent_atoms = parent.GetNumAtoms()
        removed = [Chem.MolToSmiles(f) for f in frags if f.GetNumAtoms() != parent_atoms]
        out["counterion_list"] = removed
        out["has_counterion"] = bool(removed)

    charges = [a.GetFormalCharge() for a in mol.GetAtoms()]
    out["formal_charge"] = int(sum(charges))
    out["absolute_atomic_charge_sum"] = int(sum(abs(c) for c in charges))
    out["is_zwitterion"] = any(c > 0 for c in charges) and any(c < 0 for c in charges)

    try:
        out["stereocenter_count"] = int(rdMolDescriptors.CalcNumAtomStereoCenters(parent))
        out["unspecified_stereocenter_count"] = int(
            rdMolDescriptors.CalcNumUnspecifiedAtomStereoCenters(parent))
    except Exception:
        pass

    stereo_bonds = [b for b in parent.GetBonds()
                    if b.GetBondType() == Chem.BondType.DOUBLE and not b.IsInRing()
                    and b.GetBeginAtom().GetDegree() > 1 and b.GetEndAtom().GetDegree() > 1]
    out["double_bond_stereo_count"] = len(stereo_bonds)
    out["unspecified_double_bond_stereo_count"] = sum(
        1 for b in stereo_bonds if b.GetStereo() == Chem.BondStereo.STEREONONE)

    out["parent_smiles"] = Chem.MolToSmiles(parent)
    out["standardized_smiles"] = out["parent_smiles"]
    out["structure_hash"] = Chem.MolToInchiKey(parent) if _inchi_ok() else ""
    return out


def _inchi_ok() -> bool:
    try:
        from rdkit.Chem import inchi  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# §2 RDKit 직접 계산 descriptor (확장)
# ---------------------------------------------------------------------------
def extended_descriptors(mol: Chem.Mol) -> Dict[str, float]:
    """기준서 §2 표의 계산 가능 항목 + §12 고체상 보조 지표."""
    if mol is None:
        return {}
    heavy = max(mol.GetNumHeavyAtoms(), 1)
    d: Dict[str, float] = {}

    d["exact_molecular_weight"] = float(rdMolDescriptors.CalcExactMolWt(mol))
    d["heavy_atom_count"] = float(mol.GetNumHeavyAtoms())
    hetero = float(rdMolDescriptors.CalcNumHeteroatoms(mol))
    d["heteroatom_count"] = hetero
    d["heteroatom_fraction"] = hetero / heavy

    charges = [a.GetFormalCharge() for a in mol.GetAtoms()]
    d["absolute_atomic_charge_sum"] = float(sum(abs(c) for c in charges))
    d["formal_charge_density"] = d["absolute_atomic_charge_sum"] / heavy

    hbd = float(rdMolDescriptors.CalcNumHBD(mol))
    hba = float(rdMolDescriptors.CalcNumHBA(mol))
    d["hbd_count"] = hbd
    d["hba_count"] = hba
    d["hbond_site_density"] = (hbd + hba) / heavy

    d["molar_refractivity"] = float(Crippen.MolMR(mol))
    d["rotatable_bond_count_strict"] = float(rdMolDescriptors.CalcNumRotatableBonds(
        mol, rdMolDescriptors.NumRotatableBondsOptions.Strict))
    d["ring_count"] = float(rdMolDescriptors.CalcNumRings(mol))

    ring_info = mol.GetRingInfo()
    rings = ring_info.AtomRings()
    d["largest_ring_size"] = float(max((len(r) for r in rings), default=0))
    d["ring_system_count"] = float(_ring_system_count(rings))

    d["spiro_atom_count"] = float(rdMolDescriptors.CalcNumSpiroAtoms(mol))
    d["bridgehead_atom_count"] = float(rdMolDescriptors.CalcNumBridgeheadAtoms(mol))
    d["aliphatic_ring_count"] = float(rdMolDescriptors.CalcNumAliphaticRings(mol))
    d["heterocycle_count"] = float(rdMolDescriptors.CalcNumHeterocycles(mol))
    aromatic_atoms = float(sum(1 for a in mol.GetAtoms() if a.GetIsAromatic()))
    d["aromatic_atom_fraction"] = aromatic_atoms / heavy
    d["fraction_csp3"] = float(rdMolDescriptors.CalcFractionCSP3(mol))
    d["bertz_complexity"] = float(Descriptors.BertzCT(mol))
    d["labute_asa"] = float(rdMolDescriptors.CalcLabuteASA(mol))
    try:
        d["qed"] = float(QED.qed(mol))
    except Exception:
        pass
    d["longest_conjugated_path"] = float(longest_conjugated_path(mol))
    return {k: round(v, 4) for k, v in d.items()}


def _ring_system_count(rings) -> int:
    """융합/연결된 고리를 하나의 고리계로 묶어 센다(기준서 §2 ring_system_count)."""
    systems: List[set] = []
    for ring in rings:
        atoms = set(ring)
        merged = [s for s in systems if s & atoms]
        for s in merged:
            atoms |= s
            systems.remove(s)
        systems.append(atoms)
    return len(systems)


def longest_conjugated_path(mol: Chem.Mol) -> int:
    """공액 결합 그래프의 최장 연속 경로(결합 수).

    기준서 §2.1: 광안정성 **시험 우선순위**용이며 photolability 확정에 쓰지 않는다.
    """
    conj = [b for b in mol.GetBonds() if b.GetIsConjugated()]
    if not conj:
        return 0
    adjacency: Dict[int, List[int]] = {}
    for bond in conj:
        for other in conj:
            if bond.GetIdx() == other.GetIdx():
                continue
            shared = {bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()} & \
                     {other.GetBeginAtomIdx(), other.GetEndAtomIdx()}
            if shared:
                adjacency.setdefault(bond.GetIdx(), []).append(other.GetIdx())

    best = 1
    for start in [b.GetIdx() for b in conj]:
        stack = [(start, {start})]
        while stack:
            node, seen = stack.pop()
            best = max(best, len(seen))
            if len(seen) > 24:      # 큰 방향족계에서 폭발 방지
                continue
            for nxt in adjacency.get(node, []):
                if nxt not in seen:
                    stack.append((nxt, seen | {nxt}))
    return best


# ---------------------------------------------------------------------------
# §2.1 파생 스크리닝 지표
# ---------------------------------------------------------------------------
def derived_screens(mol: Chem.Mol, base: Dict[str, float],
                    extended: Dict[str, float],
                    flag_names: List[str]) -> Dict[str, Any]:
    """Lipinski·Veber 위반 사유, 이온화 site 요약, zwitterion 가능성.

    기준서 §2.1은 count만 저장하지 말고 **위반 항목과 실제값**을 배열로 남기라고 요구한다.
    설명 가능해야 모델 입력으로도, 리포트로도 쓸 수 있기 때문이다.
    """
    mw = base.get("molecular_weight", extended.get("exact_molecular_weight", 0.0))
    clogp = base.get("clogp", 0.0)
    hbd = extended.get("hbd_count", base.get("hbond_donors", 0.0))
    hba = extended.get("hba_count", base.get("hbond_acceptors", 0.0))
    rb = extended.get("rotatable_bond_count_strict", base.get("rotatable_bonds", 0.0))
    tpsa = base.get("tpsa", 0.0)

    lipinski = []
    if mw > 500: lipinski.append({"rule": "MW>500", "value": mw})
    if clogp > 5: lipinski.append({"rule": "cLogP>5", "value": clogp})
    if hbd > 5: lipinski.append({"rule": "HBD>5", "value": hbd})
    if hba > 10: lipinski.append({"rule": "HBA>10", "value": hba})

    veber = []
    if rb > 10: veber.append({"rule": "RB>10", "value": rb})
    if tpsa > 140: veber.append({"rule": "TPSA>140", "value": tpsa})

    acidic = [n for n in flag_names if n in {
        "has_carboxylic_acid", "has_sulfonic_acid", "has_phosphonic_acid",
        "has_phenol", "has_tetrazole", "has_imide"}]
    basic = [n for n in flag_names if n in {
        "has_primary_aliphatic_amine", "has_secondary_aliphatic_amine",
        "has_tertiary_aliphatic_amine", "has_aromatic_amine_aniline",
        "has_amidine", "has_guanidine", "has_basic_heteroaromatic_n"}]
    permanent = [n for n in flag_names if n == "has_quaternary_ammonium"]

    return {
        "lipinski_violation_count": len(lipinski),
        "lipinski_violation_reasons": lipinski,
        "veber_violation_count": len(veber),
        "veber_violation_reasons": veber,
        "veber_definition": "RB>10 or TPSA>140",
        "ionizable_group_summary": {
            "acidic": acidic, "basic": basic, "permanent_charge": permanent,
            "acidic_site_count": len(acidic), "basic_site_count": len(basic),
            "permanent_charge_count": len(permanent),
        },
        # 산성·염기성 site가 동시에 있거나 실제 ±전하가 있으면 zwitterion 가능
        "zwitterion_potential": bool(acidic and basic),
        "salt_forming_site_count": len(acidic) + len(basic),
        "longest_conjugated_path": extended.get("longest_conjugated_path", 0.0),
        # 확정 금지 표기 — 이 값들은 BCS·공정 판정을 대체하지 않는다
        "usage_limit": "사전 스크리닝 신호. BCS 등급·공정 적합성 확정에 사용 금지(기준서 §2.1·§13)",
    }


def versions() -> Dict[str, str]:
    from formula.chem.structural_flags import REGISTRY_VERSION
    return {
        "rdkit": rdkit.__version__,
        "normalization": NORMALIZATION_VERSION,
        "smarts_registry": REGISTRY_VERSION,
    }
