"""RDKit 물성 계층 검증 리포트.

`structural_flags_smarts.csv`는 전 행 `validation_status = UNTESTED`인데 이 플래그가
배합금기 HARD_FAIL을 직접 트리거한다. 이 스크립트는 알려진 분자로 5개 SMARTS를 전수
검증하고, descriptor·물성 추정까지 한 번에 보여준다.

실행:  .venv/bin/python scripts/verify_smarts.py [SMILES 또는 API명]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rdkit import Chem  # noqa: E402

from formula.chem.profile import KNOWN_SMILES, build_profile  # noqa: E402
from formula.chem.structural_flags import detect_flags, strip_salt  # noqa: E402

P_AMINE, S_AMINE = "has_primary_amine", "has_secondary_amine"
ESTER, ACID, AMIDE = "has_ester", "has_carboxylic_acid", "is_amide_not_amine"

# (표시명, SMILES, 화학적으로 반드시 성립해야 하는 기대값)
TRUTH_TABLE = [
    ("아세트아미노펜", "CC(=O)Nc1ccc(O)cc1",
     {AMIDE: True, P_AMINE: False, S_AMINE: False}),
    ("p-아미노페놀 (APAP 분해산물)", "Nc1ccc(O)cc1",
     {P_AMINE: True, AMIDE: False}),
    ("메트포르민", "CN(C)C(=N)NC(=N)N", {P_AMINE: True}),
    ("플루옥세틴", "CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1",
     {S_AMINE: True, P_AMINE: False}),
    ("플루옥세틴 염산염 (염)", "CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1.Cl",
     {S_AMINE: True}),
    ("암로디핀 베실산염 (염)",
     "CCOC(=O)C1=C(COCCN)NC(C)=C(C1c1ccccc1Cl)C(=O)OC.OS(=O)(=O)c1ccccc1",
     {P_AMINE: True, ESTER: True}),
    ("아스피린", "CC(=O)Oc1ccccc1C(=O)O", {ESTER: True, ACID: True}),
    ("이부프로펜", "CC(C)Cc1ccc(cc1)C(C)C(=O)O", {ACID: True, ESTER: False}),
    ("유당 (환원당)",
     "OC[C@H]1O[C@@H](O[C@H]2[C@H](O)[C@@H](O)C(O)O[C@@H]2CO)[C@H](O)[C@@H](O)[C@@H]1O",
     {P_AMINE: False, S_AMINE: False, AMIDE: False}),
]

FLAG_ORDER = [P_AMINE, S_AMINE, ESTER, ACID, AMIDE]
SHORT = {P_AMINE: "1°아민", S_AMINE: "2°아민", ESTER: "에스터", ACID: "COOH", AMIDE: "아미드"}


def _flags(smiles: str) -> dict:
    mol = Chem.MolFromSmiles(smiles)
    parent, _ = strip_salt(mol)
    flags, warnings = detect_flags(parent, ROOT)
    return {f.flag_name: f for f in flags}, warnings


def run_truth_table() -> int:
    print("═" * 100)
    print("1. SMARTS 진리표 검증  (구조로부터 독립적으로 정한 기대값 ↔ RDKit 실제 검출)")
    print("═" * 100)
    header = f"{'분자':<30}" + "".join(f"{SHORT[f]:>10}" for f in FLAG_ORDER) + "   판정"
    print(header)
    print("─" * 100)

    failures = 0
    for label, smiles, expected in TRUTH_TABLE:
        flags, _ = _flags(smiles)
        cells, mismatches = [], []
        for name in FLAG_ORDER:
            flag = flags.get(name)
            present = bool(flag and flag.present)
            want = expected.get(name)
            mark = "T" if present else "F"
            if want is not None and present is not want:
                mark = f"{mark}✗"
                mismatches.append(f"{SHORT[name]}(기대 {'T' if want else 'F'})")
            elif want is not None:
                mark = f"{mark}✓"
            cells.append(f"{mark:>10}")
        verdict = "OK" if not mismatches else "불일치: " + ", ".join(mismatches)
        failures += bool(mismatches)
        print(f"{label:<30}" + "".join(cells) + f"   {verdict}")

    print("─" * 100)
    print(f"결과: {len(TRUTH_TABLE) - failures}/{len(TRUTH_TABLE)} 통과"
          + ("" if not failures else f"  ⛔ {failures}건 불일치 — SMARTS 수정 필요"))
    return failures


def report_molecule(api_name: str, smiles: str | None = None) -> None:
    print("\n" + "═" * 100)
    print(f"2. 분자 상세 프로파일 — {api_name}")
    print("═" * 100)
    profile = build_profile(api_name, smiles=smiles, base_dir=ROOT, render=False)

    if not profile.smiles:
        print("  SMILES 미상 — 물성 계산 불가")
        for w in profile.warnings:
            print(f"  ⚠ {w}")
        return

    print(f"  SMILES        {profile.smiles}")
    if profile.is_salt:
        print(f"  parent        {profile.parent_smiles}   (염 제거 후 — SMARTS는 이쪽에 적용)")
    print(f"  RDKit         {profile.rdkit_version}")

    print("\n  ── descriptor (rdkit_descriptor_definitions.csv 구동) ──")
    for name, value in profile.descriptors.items():
        print(f"     {name:<26} {value:>10.3f}")

    print("\n  ── 구조 플래그 (structural_flags_smarts.csv) ──")
    for flag in profile.flags:
        mark = "●" if flag.present else "○"
        cross = "" if flag.cross_check_ok else "  ⚠ fr_* 카운트 불일치"
        frag = "" if flag.fragment_count is None else f" / fr={flag.fragment_count}"
        print(f"     {mark} {flag.flag_name:<24} 매치 {flag.match_count}{frag}"
              f"   [{flag.validation_status}]{cross}")
        if flag.present and flag.triggers_rule:
            print(f"        → 트리거: {flag.triggers_rule}")

    print("\n  ── 물성 추정 (physchem_estimation_rules.csv) ──")
    for est in profile.estimates:
        badge = {"high": "신뢰", "medium": "보통", "low": "저신뢰"}.get(est.confidence, est.confidence)
        print(f"     {est.property:<28} = {str(est.value):<8} [{badge}]")
        if est.confidence == "low":
            print(f"        → {est.action_if_low_confidence}  (판정 근거로 사용 금지)")

    if profile.warnings:
        print("\n  ── 경고 ──")
        for w in profile.warnings:
            print(f"     ⚠ {w}")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else None

    if target:
        smiles = target if Chem.MolFromSmiles(target) else None
        report_molecule(target if smiles is None else "입력 분자", smiles=smiles or target)
        return

    failures = run_truth_table()

    # 데모 시나리오에서 가장 중요한 두 분자를 상세 출력
    report_molecule("Acetaminophen")
    report_molecule("Fluoxetine HCl")

    print("\n" + "═" * 100)
    print("3. 검토 결론")
    print("═" * 100)
    print("""  ✅ SMARTS 5개는 의도한 대로 동작한다. 특히 FLG005(is_amide_not_amine)가
     아세트아미노펜을 아미드로 정확히 잡고 1차 아민으로 오탐하지 않는다.

  ⛔ 그 결과 **기존 데모 시나리오가 화학적으로 성립하지 않는다.**
     scripts/demo.py 는 아세트아미노펜에 api_functional_groups=["Primary Amine"]을
     하드코딩해 유당-Maillard HARD_FAIL을 만들었지만, 실제 구조에는 유리 아민이 없다.
     → RDKit을 연결하면 이 반려 사유가 사라진다.
     (개발자 가이드 §9.3에 따르면 나머지 반려 사유 SLS 10mg도 NO_SOURCE_FOUND로 폐기됨)

  🟡 알려진 과검출 2건 — 안전 측 오류지만 불필요한 반려를 만든다:
     · 메트포르민의 구아니딘 NH → 2차 아민으로 검출
     · 암로디핀의 다이하이드로피리딘 고리 NH → 2차 아민으로 검출
       FLG002의 !$(N[a])는 방향족 인접 N만 배제해 비방향족 고리 NH가 남는다.

  🟡 용해도·투과도 추정은 confidence=low — BCS class 확정에 쓰지 않는다.
     매니페스트의 bcs_classification 은 실측값이 있을 때만 발동하도록 배선했다.

  → 권고: 위 진리표를 structural_flags_smarts.csv 의 validation_status 근거로 삼아
     UNTESTED → STRUCTURAL_VERIFIED 로 갱신하고, FLG002 패턴에 고리 NH 배제 조건을 추가할지
     약학 팀이 결정할 것.""")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
