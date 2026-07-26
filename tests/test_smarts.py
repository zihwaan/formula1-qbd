"""SMARTS 구조 플래그 진리표 검증.

`structural_flags_smarts.csv`는 전 행 `validation_status = UNTESTED`인데,
이 플래그가 `incompatibility_1to1.csv`의 HARD_FAIL 판정을 직접 트리거한다.
오탐 1건 = 잘못된 반려, 미탐 1건 = 놓친 배합금기이므로 **이 테스트가 통과하기 전에는
SMARTS를 배합금기 트리거로 신뢰해서는 안 된다.**

아래 기대값은 RDKit 출력을 베낀 것이 아니라 **분자 구조로부터 독립적으로 정한 것**이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem

from formula.chem.profile import build_profile
from formula.chem.structural_flags import detect_flags, strip_salt

ROOT = Path(__file__).resolve().parent.parent

P_AMINE, S_AMINE = "has_primary_amine", "has_secondary_amine"
ESTER, ACID, AMIDE = "has_ester", "has_carboxylic_acid", "is_amide_not_amine"


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
        # 이 한 줄이 FLG005의 존재 이유이자, 기존 데모가 틀렸음을 증명하는 지점이다.
        ("아세트아미노펜", "CC(=O)Nc1ccc(O)cc1",
         {AMIDE: True, P_AMINE: False, S_AMINE: False, ESTER: False, ACID: False}),

        # 아세트아미노펜의 가수분해 산물. 여기서는 1차 방향족 아민이 실제로 드러난다.
        ("p-아미노페놀(APAP 분해산물)", "Nc1ccc(O)cc1",
         {P_AMINE: True, AMIDE: False}),

        # 플루옥세틴 = 2차 아민. incompatibility_1to1 INC002의 원문 사례.
        ("플루옥세틴", "CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1",
         {S_AMINE: True, P_AMINE: False, AMIDE: False}),

        # 아스피린 = 에스터 + 카복실산.
        ("아스피린", "CC(=O)Oc1ccccc1C(=O)O",
         {ESTER: True, ACID: True, P_AMINE: False, S_AMINE: False, AMIDE: False}),

        # 유당 = 환원당. 아민은 없다(반응 상대이지 아민 공여체가 아님).
        ("유당", "OC[C@H]1O[C@@H](O[C@H]2[C@H](O)[C@@H](O)C(O)O[C@@H]2CO)[C@H](O)[C@@H](O)[C@@H]1O",
         {P_AMINE: False, S_AMINE: False, AMIDE: False}),

        # 이부프로펜 = 카복실산만.
        ("이부프로펜", "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
         {ACID: True, ESTER: False, P_AMINE: False, S_AMINE: False}),
    ],
)
def test_smarts_truth_table(label, smiles, expected):
    actual = flags_for(smiles)
    for flag, want in expected.items():
        assert actual[flag] is want, f"{label}: {flag} 기대 {want}, 실제 {actual[flag]}"


# ---------------------------------------------------------------------------
# 염 처리 — parent에 SMARTS를 적용해야 한다
# ---------------------------------------------------------------------------
def test_salt_is_stripped_before_matching():
    mol = Chem.MolFromSmiles("CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1.Cl")  # 플루옥세틴 염산염
    parent, is_salt = strip_salt(mol)
    assert is_salt is True
    assert "Cl" not in Chem.MolToSmiles(parent)
    assert flags_for("CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1.Cl")[S_AMINE] is True


def test_salt_flagged_in_profile():
    profile = build_profile("Amlodipine besylate", base_dir=ROOT, render=False)
    assert profile.is_salt is True
    assert any("염 형태" in w for w in profile.warnings)
    # 벤젠술폰산(besylate)이 parent에서 빠졌는지 — 술폰기가 남아 있으면 안 된다
    assert "S(=O)(=O)" not in profile.parent_smiles


def test_non_salt_is_untouched():
    profile = build_profile("Acetaminophen", base_dir=ROOT, render=False)
    assert profile.is_salt is False


# ---------------------------------------------------------------------------
# 알려진 과검출(over-detection) — 고쳐야 할 대상이지 정답이 아니다.
# 동작이 바뀌면 이 테스트가 깨져서 알려준다.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "label, smiles, flag, note",
    [
        ("메트포르민", "CN(C)C(=N)NC(=N)N", S_AMINE,
         "구아니딘 NH를 2차 아민으로 검출 — 통상적 지방족 아민과 반응성이 다르다"),
        ("암로디핀", "CCOC(=O)C1=C(COCCN)NC(C)=C(C1c1ccccc1Cl)C(=O)OC", S_AMINE,
         "다이하이드로피리딘 고리 NH를 2차 아민으로 검출 — FLG002의 !$(N[a])는 "
         "방향족 인접 N만 배제하므로 비방향족 고리 NH가 남는다"),
    ],
)
def test_known_over_detection_is_documented(label, smiles, flag, note):
    """과검출은 '안전 측 오류'라 즉시 위험하진 않지만, 불필요한 반려를 만든다.

    현재 동작을 고정해두고, 약학 팀이 SMARTS를 개선하면 이 테스트를 함께 갱신한다.
    """
    assert flags_for(smiles)[flag] is True, f"{label}: {note}"


def test_amide_amine_conflict_emits_warning():
    """아미드와 아민이 동시에 잡히면 경고가 나와야 한다(Maillard 오탐 방지 장치)."""
    # 파라세타몰 아미드 + 유리 1차 아민을 함께 가진 가상의 구조
    mol = Chem.MolFromSmiles("CC(=O)Nc1ccc(N)cc1")
    parent, _ = strip_salt(mol)
    flags, warnings = detect_flags(parent, ROOT)
    by_name = {f.flag_name: f.present for f in flags}
    assert by_name[AMIDE] is True and by_name[P_AMINE] is True
    assert any("동시에 검출" in w for w in warnings)


# ---------------------------------------------------------------------------
# fragment 교차검증 — SMARTS와 rdkit fr_* 카운트가 어긋나면 기록된다
# ---------------------------------------------------------------------------
def test_fragment_cross_check_runs():
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")  # 아스피린
    flags, _ = detect_flags(mol, ROOT)
    checked = [f for f in flags if f.fragment_count is not None]
    assert checked, "fr_* 교차검증이 한 건도 수행되지 않았다"
    assert all(f.cross_check_ok for f in checked)


def test_flags_carry_untested_status():
    """원본 CSV가 UNTESTED이므로 판정은 '잠정'으로 표기돼야 한다."""
    mol = Chem.MolFromSmiles("CC(=O)Nc1ccc(O)cc1")
    flags, _ = detect_flags(mol, ROOT)
    assert all(f.validation_status == "UNTESTED" for f in flags)
