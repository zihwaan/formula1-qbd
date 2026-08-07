"""성분명 해석 + 구조 미확정 이관 — 배합금기가 조용히 통과하던 두 경로를 못 박는다.

실제로 겪은 사고 두 건이 여기 고정돼 있다.

  1. fluoxetine(2차 아민) + "유당"을 넣었는데 INC002가 발동하지 않았다.
     룰북은 "Lactose monohydrate"라고 적고 처방은 "유당"이라고 적는데, 전략 함수가
     문자열 동등 비교를 했다. 규칙은 멀쩡했고 판정만 통과로 나왔다.
  2. 같은 입력에서 SMILES의 'O'를 숫자 '0'으로 친 오타가 파싱 실패로 끝났는데,
     구조 플래그가 하나도 안 선 상태를 게이트가 **통과**로 셌다.

둘 다 "아무것도 발동하지 않음"을 "문제 없음"으로 읽은 결과다. 그래서 이 파일의
음성 대조군(Mannitol·MCC·전분글리콜산나트륨)도 같은 무게로 지킨다 — 미탐을 막겠다고
오탐을 만들면 잘못된 반려가 되고, 그건 반대 방향의 같은 사고다.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from formula.checkers.excipients import IngredientMatcher, excipient_resolver
from formula.checkers.registry import RulebookRegistry
from formula.chem.profile import build_profile, smiles_error
from formula.contracts import FormulationSpec, Ingredient, Recipe, VerdictStatus
from formula.orchestrator.graph import _public_derived

ROOT = Path(__file__).resolve().parent.parent

# 2차 아민 — INC002의 근거 논문(Wirth 1998)이 바로 이 분자다.
FLUOXETINE = "CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1"
# 사용자가 실제로 붙여넣은 오타: 에테르 산소 O를 숫자 0으로 쳤다.
FLUOXETINE_TYPO = "CNCCC(C1=CC=CC=C1)0C2=CC=C(C=C2)C(F)(F)F"


@pytest.fixture(scope="module")
def registry() -> RulebookRegistry:
    return RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)


def _spec(smiles: str | None = FLUOXETINE) -> FormulationSpec:
    profile = build_profile("Fluoxetine", smiles=smiles, base_dir=ROOT, render=False)
    return FormulationSpec(api_name="Fluoxetine").with_profile(profile)


def _recipe(*excipients: str) -> Recipe:
    return Recipe(
        api_name="Fluoxetine",
        ingredients=[Ingredient(name="Fluoxetine", role="api", amount_mg=20)]
        + [Ingredient(name=name, role="diluent", amount_mg=100) for name in excipients],
        process="direct_compression",
        packaging="pvc_blister",
    )


def _rule_ids(result, status=VerdictStatus.HARD_FAIL) -> set:
    return {v.rule_id for v in result.verdicts if v.status == status}


# ---------------------------------------------------------------------------
# 1. 표기가 달라도 같은 부형제면 룰이 발동한다
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("written_as", [
    "Lactose monohydrate",        # 룰북 표기 그대로
    "lactose monohydrate",        # 대소문자
    "Lactose Monohydrate, NF",    # 공정서 등급 표기
    "Lactose monohydrate (유당)",  # 괄호 병기
    "유당수화물",                   # 마스터의 국문명
    "Lactose",                    # 계열명(등급 미지정)
    "유당",                        # 국문 계열명 — 사용자가 실제로 쓴 표기
])
def test_lactose_synonyms_fire_maillard_rule(registry, written_as):
    result = registry.run(_spec(), _recipe(written_as))
    assert "INC002" in _rule_ids(result), f"{written_as!r}에서 INC002가 발동하지 않았다"
    assert not result.passed


def test_generic_name_is_marked_as_such(registry):
    """계열명 매칭은 발동시키되 '등급 미지정'을 판정문에 남긴다 — 등급을 특정해 재실행할 수 있게."""
    verdict = next(v for v in registry.run(_spec(), _recipe("유당")).verdicts
                   if v.rule_id == "INC002")
    assert verdict.evidence["match_kind"] == "generic"
    assert verdict.evidence["matched_ingredient"] == "유당"
    assert "등급" in verdict.reason

    exact = next(v for v in registry.run(_spec(), _recipe("유당수화물")).verdicts
                 if v.rule_id == "INC002")
    assert exact.evidence["match_kind"] == "exact"


# ---------------------------------------------------------------------------
# 2. 음성 대조군 — 미탐을 막겠다고 오탐을 만들지 않았는가
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("excipient", [
    "Mannitol",                     # INC002가 권하는 대체품 — 여기서 걸리면 대안이 사라진다
    "Microcrystalline cellulose",
    "Magnesium stearate",
    "Sodium starch glycolate",      # 'starch'를 계열명으로 오인하면 걸린다
    "Croscarmellose sodium",
])
def test_unrelated_excipients_do_not_fire(registry, excipient):
    result = registry.run(_spec(), _recipe(excipient))
    assert not _rule_ids(result), f"{excipient!r}에서 잘못된 반려가 났다"
    assert result.passed


def test_family_match_requires_head_or_tail(registry):
    """계열명은 머리말·꼬리말로만 인정한다. 단순 부분집합이면 전혀 다른 부형제가 걸린다."""
    matcher = IngredientMatcher({"starch": ["starch"]})
    assert matcher.match("Sodium starch glycolate") is None
    assert matcher.match("Pregelatinized starch").kind == "generic"


# ---------------------------------------------------------------------------
# 3. 구조를 못 얻으면 통과가 아니라 이관이다
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("smiles", [FLUOXETINE_TYPO, None])
def test_unresolved_structure_escalates_instead_of_passing(registry, smiles):
    spec = _spec(smiles) if smiles else FormulationSpec(api_name="이름없는신약").with_profile(
        build_profile("이름없는신약", base_dir=ROOT, render=False))
    result = registry.run(spec, _recipe("유당"))
    assert spec.properties["structure_known"] is False
    assert "STRUCT000" in _rule_ids(result, VerdictStatus.ESCALATE)
    assert not result.passed, "구조 미확정을 통과로 세면 오타 한 글자가 게이트를 무력화한다"


def test_resolved_structure_does_not_escalate(registry):
    result = registry.run(_spec(), _recipe("Mannitol"))
    assert "STRUCT000" not in _rule_ids(result, VerdictStatus.ESCALATE)


def test_typo_smiles_is_rejected_at_the_input_boundary():
    """입력 경계에서 사유를 돌려준다 — 60초 실행 뒤 '규칙이 없나 보다'로 읽히면 안 된다."""
    assert smiles_error(FLUOXETINE_TYPO)
    assert smiles_error(FLUOXETINE) is None
    assert smiles_error(None) is None
    assert smiles_error("") is None


def test_parse_failure_never_substitutes_a_known_structure():
    """이름 사전에 있는 API라도, 사용자가 친 구조가 깨졌으면 말없이 바꿔치지 않는다."""
    profile = build_profile("fluoxetine", smiles=FLUOXETINE_TYPO, base_dir=ROOT, render=False)
    assert profile.structure_resolved is False
    assert profile.flags == []


# ---------------------------------------------------------------------------
# 4. 사전 자체가 살아 있는가 (조용히 빈 사전이 되는 회귀를 막는다)
# ---------------------------------------------------------------------------
def test_known_excipients_is_not_empty(registry):
    """컬럼명이 어긋나 항상 빈 집합이던 회귀 — REV005가 구조적으로 소집 불가였다."""
    assert len(registry.known_excipients()) > 500
    assert registry.is_known_excipient("유당")
    assert registry.is_known_excipient("Lactose, NF")
    assert not registry.is_known_excipient("존재하지않는가상부형제XYZ")


def test_alias_targets_exist_in_a_master():
    """별칭 오타는 조용한 무효화다 — 대상 표준명이 마스터에 실제로 있어야 한다."""
    config = yaml.safe_load((ROOT / "config" / "excipient_aliases.yaml").read_text("utf-8"))
    resolver = excipient_resolver(ROOT, ROOT / "config" / "excipient_aliases.yaml")
    for alias, targets in (config.get("aliases") or {}).items():
        for target in targets:
            assert resolver.is_known(target), f"{alias!r} → {target!r}: 마스터에 없는 표준명"


def test_rulebook_excipient_names_are_all_resolvable():
    """배합금기 룰북이 지목하는 부형제는 전부 사전이 알아야 한다 — 모르면 그 행은 죽은 규칙이다."""
    resolver = excipient_resolver(ROOT, ROOT / "config" / "excipient_aliases.yaml")
    path = ROOT / "database" / "02_incompatibility" / "incompatibility_1to1.csv"
    with path.open(encoding="utf-8") as handle:
        names = {row["excipient_name_en"].strip() for row in csv.DictReader(handle)}
    unknown = sorted(n for n in names if n and not resolver.is_known(n))
    assert not unknown, f"룰북이 지목하는데 마스터가 모르는 부형제: {unknown}"


def test_internal_wiring_never_reaches_the_ui():
    """성분명 사전은 파생 state가 아니다 — 이벤트로 새 나가면 안 된다."""
    public = _public_derived({"selected_route": "DC", "candidate_id": "cand-0",
                              "_excipient_identities": {"유당": ["Lactose"]}})
    assert public == {"selected_route": "DC"}
