"""SMARTS 구조 플래그 진리표 검증 — 기준서 v1.1 레지스트리 기준.

이 플래그가 `incompatibility_1to1.csv`의 HARD_FAIL 판정을 직접 트리거한다.
오탐 1건 = 잘못된 반려, 미탐 1건 = 놓친 배합금기이므로 **이 테스트가 통과하기 전에는
SMARTS를 배합금기 트리거로 신뢰해서는 안 된다.**

아래 기대값은 RDKit 출력을 베낀 것이 아니라 **분자 구조로부터 독립적으로 정한 것**이다.
기준서 §18(단위 테스트 전략)이 요구하는 양성·음성·경계·염 사례를 포함한다.

v1.1에서 이름이 바뀐 부분:
  has_primary_amine    → has_primary_aliphatic_amine / has_aromatic_amine_aniline 로 분리
  has_secondary_amine  → has_secondary_aliphatic_amine
  is_amide_not_amine   → 폐기. 한 분자에 amine과 amide가 동시에 있을 수 있으므로
                          단일 Boolean을 쓰지 않고 각각 독립적으로 검출한다(§4).
룰북 조인 어휘(primary_amine·secondary_amine)는 레지스트리의 rulebook_group이 유지한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem

from formula.chem.profile import build_profile
from formula.chem.structural_flags import detect_flags, load_flag_definitions, strip_salt

ROOT = Path(__file__).resolve().parent.parent

P_ALIPH = "has_primary_aliphatic_amine"
S_ALIPH = "has_secondary_aliphatic_amine"
ANILINE = "has_aromatic_amine_aniline"
ESTER, ACID, AMIDE = "has_ester", "has_carboxylic_acid", "has_amide"
PHENOL, LACTAM = "has_phenol", "has_lactam"


def flags_for(smiles: str) -> dict:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"SMILES 파싱 실패: {smiles}"
    parent, _ = strip_salt(mol)
    flags, _ = detect_flags(parent, ROOT)
    return {f.flag_name: f.present for f in flags}


# ---------------------------------------------------------------------------
# 화학적으로 반드시 성립해야 하는 진리표
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "label, smiles, expected",
    [
        # 아세트아미노펜 = N-(4-hydroxyphenyl)acetamide. 아미드이고 **유리 아민이 없다.**
        # 기존 데모가 이걸 1차 아민으로 잘못 적었고, 그 오류를 막는 것이 이 줄의 목적이다.
        ("아세트아미노펜", "CC(=O)Nc1ccc(O)cc1",
         {AMIDE: True, P_ALIPH: False, S_ALIPH: False, ANILINE: False,
          PHENOL: True, ESTER: False, ACID: False}),

        # 아세트아미노펜의 가수분해 산물. 여기서는 방향족 아민이 실제로 드러난다.
        ("p-아미노페놀(APAP 분해산물)", "Nc1ccc(O)cc1",
         {ANILINE: True, AMIDE: False, PHENOL: True}),

        # 플루옥세틴 = 2차 지방족 아민. incompatibility_1to1 INC002의 원문 사례.
        ("플루옥세틴", "CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1",
         {S_ALIPH: True, P_ALIPH: False, AMIDE: False}),

        # 아스피린 = 에스터 + 카복실산. 살리실산과 반드시 구분돼야 한다(§18).
        ("아스피린", "CC(=O)Oc1ccccc1C(=O)O",
         {ESTER: True, ACID: True, P_ALIPH: False, S_ALIPH: False, AMIDE: False}),
        ("살리실산", "OC(=O)c1ccccc1O",
         {ESTER: False, ACID: True, PHENOL: True}),

        # 유당 = 환원당. 아민은 없다(반응 상대이지 아민 공여체가 아님).
        ("유당", "OC[C@H]1O[C@@H](O[C@H]2[C@H](O)[C@@H](O)C(O)O[C@@H]2CO)[C@H](O)[C@@H](O)[C@@H]1O",
         {P_ALIPH: False, S_ALIPH: False, AMIDE: False}),

        # 이부프로펜 = 카복실산만.
        ("이부프로펜", "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
         {ACID: True, ESTER: False, P_ALIPH: False, S_ALIPH: False}),

        # §18 경계 사례 — amide 질소를 amine으로 세면 안 된다.
        ("메틸아민", "CN", {P_ALIPH: True, AMIDE: False}),
        ("아세트아미드", "CC(N)=O", {P_ALIPH: False, AMIDE: True}),
        ("요소", "NC(N)=O", {P_ALIPH: False, AMIDE: True, "has_urea": True}),
        ("디메틸아민", "CNC", {S_ALIPH: True, AMIDE: False}),
        ("N-메틸아세트아미드", "CNC(C)=O", {S_ALIPH: False, AMIDE: True}),
        ("아닐린", "Nc1ccccc1", {ANILINE: True, P_ALIPH: False}),
        ("아세트아닐리드", "CC(=O)Nc1ccccc1", {ANILINE: False, AMIDE: True}),
        ("아니솔", "COc1ccccc1", {PHENOL: False}),
        ("페놀", "Oc1ccccc1", {PHENOL: True}),
        ("THF", "C1CCOC1", {"has_lactone": False}),
        ("γ-부티로락톤", "O=C1CCCO1", {"has_lactone": True, "has_beta_lactone": False}),
    ],
)
def test_smarts_truth_table(label, smiles, expected):
    got = flags_for(smiles)
    for flag, want in expected.items():
        assert flag in got, f"{label}: 플래그 {flag} 가 레지스트리에 없다"
        assert got[flag] is want, f"{label}: {flag} 기대 {want}, 실제 {got[flag]}"


# ---------------------------------------------------------------------------
# 고리 크기 후처리 — β/γ-lactam은 위험도가 다르므로 반드시 갈려야 한다 (§7)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "label, smiles, beta, gamma",
    [
        ("2-azetidinone(β-lactam, 4원)", "O=C1CCN1", True, False),
        ("2-pyrrolidone(γ-lactam, 5원)", "O=C1CCCN1", False, True),
        ("아목시실린(β-lactam 보유)",
         "CC1(C)SC2C(NC(=O)C(N)c3ccc(O)cc3)C(=O)N2C1C(=O)O", True, False),
    ],
)
def test_ring_size_postprocessing(label, smiles, beta, gamma):
    got = flags_for(smiles)
    assert got[LACTAM] is True, f"{label}: lactam 자체가 검출돼야 한다"
    assert got["has_beta_lactam"] is beta, f"{label}: β-lactam 기대 {beta}"
    assert got["has_gamma_lactam"] is gamma, f"{label}: γ-lactam 기대 {gamma}"


def test_beta_lactam_is_hard_alert():
    """β-lactam은 ring strain 때문에 높은 구조 경고여야 한다 — 시험 승격의 근거."""
    profile = build_profile("Amoxicillin",
                            smiles="CC1(C)SC2C(NC(=O)C(N)c3ccc(O)cc3)C(=O)N2C1C(=O)O",
                            base_dir=ROOT, render=False)
    hard = [f.flag_name for f in profile.alerts("hard_alert")]
    assert "has_beta_lactam" in hard, f"β-lactam이 hard_alert가 아니다: {hard}"


# ---------------------------------------------------------------------------
# 알려진 과검출 — 고치기 전까지 사실로 고정해 둔다(기준서 §3 false_positive_notes)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "label, smiles, flag, note",
    [
        ("메트포르민", "CN(C)C(=N)NC(=N)N", "has_guanidine",
         "구아니딘은 강염기성 motif로 별도 분류된다 — 통상적 2차 아민과 반응성이 다르다"),
        ("암로디핀", "CCOC(=O)C1=C(COCCN)NC(C)=C(C1c1ccccc1Cl)C(=O)OC", "has_cyclic_secondary_amine",
         "다이하이드로피리딘 고리 NH는 환형 2차 아민으로 분리 검출된다 — 사슬형과 구분 필요"),
    ],
)
def test_known_over_detection_is_documented(label, smiles, flag, note):
    got = flags_for(smiles)
    assert got.get(flag) is True, f"{label}: {flag} 가 검출돼야 한다 ({note})"


# ---------------------------------------------------------------------------
# 염 처리 — SMARTS는 parent에 적용해야 한다
# ---------------------------------------------------------------------------
def test_salt_is_stripped_before_matching():
    profile = build_profile("Fluoxetine HCl",
                            smiles="CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1.Cl",
                            base_dir=ROOT, render=False)
    assert profile.is_salt is True
    assert "." not in profile.parent_smiles, "parent에 염 fragment가 남아 있다"
    assert S_ALIPH in profile.flag_names(), "염을 벗긴 뒤 2차 아민이 검출돼야 한다"
    assert profile.structure_quality["has_counterion"] is True
    assert profile.structure_quality["counterion_list"], "counterion 추적 기록이 비어 있다"


def test_rulebook_join_vocabulary_survives_rename():
    """플래그 이름이 세분화돼도 룰북 조인 어휘는 유지돼야 한다.

    이게 깨지면 INC001~INC006이 조용히 발동하지 않는다.
    """
    profile = build_profile("Fluoxetine",
                            smiles="CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1",
                            base_dir=ROOT, render=False)
    groups = profile.functional_groups()
    assert "secondary_amine" in groups, f"룰북 어휘가 사라졌다: {groups}"


# ---------------------------------------------------------------------------
# 데이터 계약 — 기준서 §3이 요구하는 필드가 실제로 채워지는가
# ---------------------------------------------------------------------------
def test_flag_data_contract_is_populated():
    profile = build_profile("Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O",
                            base_dir=ROOT, render=False)
    ester = next(f for f in profile.flags if f.flag_name == ESTER)
    assert ester.present and ester.match_count >= 1
    assert ester.atom_indices, "atom_indices가 비어 있다 — 시각화·검토 불가"
    assert ester.alert_level in {"fact", "conditional_alert", "hard_alert"}
    assert ester.confirmation_test, "구조 경고에 확인시험이 연결돼 있지 않다"
    assert ester.required_cofactors, "위험 발현 조건이 비어 있다"


def test_registry_smarts_all_compile():
    """레지스트리의 모든 SMARTS가 컴파일돼야 한다 — 하나라도 깨지면 그 플래그는 침묵한다."""
    broken = [row["flag_id"] for row in load_flag_definitions(ROOT)
              if Chem.MolFromSmarts(row.get("smarts", "")) is None]
    assert not broken, f"컴파일 실패 SMARTS: {broken}"


def test_registry_covers_reference_sections():
    """기준서 §4~§12가 모두 레지스트리에 반영돼 있어야 한다."""
    sections = {row.get("section") for row in load_flag_definitions(ROOT)}
    missing = {str(n) for n in range(4, 13)} - sections
    assert not missing, f"기준서 절이 누락됨: {sorted(missing)}"


# ---------------------------------------------------------------------------
# §1·§2.1 — 구조 품질과 파생 스크리닝
# ---------------------------------------------------------------------------
def test_structure_quality_and_derived_screens():
    profile = build_profile("Amoxicillin",
                            smiles="CC1(C)SC2C(NC(=O)C(N)c3ccc(O)cc3)C(=O)N2C1C(=O)O",
                            base_dir=ROOT, render=False)
    quality = profile.structure_quality
    assert quality["structure_parse_success"] and quality["sanitization_success"]
    assert quality["stereocenter_count"] > 0
    assert quality["parent_smiles"]

    screens = profile.derived_screens
    # 산성(카복실산)과 염기성(1차 아민) site가 함께 있으므로 zwitterion 가능성이 참이어야 한다
    assert screens["zwitterion_potential"] is True
    assert screens["ionizable_group_summary"]["acidic_site_count"] >= 1
    assert screens["ionizable_group_summary"]["basic_site_count"] >= 1
    assert "lipinski_violation_reasons" in screens
