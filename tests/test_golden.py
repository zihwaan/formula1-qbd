"""골든 시나리오 회귀 테스트 — 전체 파이프라인이 기대대로 움직이는지 고정한다.

LLM 없이(결정론 폴백) 돌아야 한다. 시연 환경에 API 키가 없어도 통과해야 하기 때문이다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from formula.checkers.registry import RulebookRegistry
from formula.chem.profile import build_profile
from formula.contracts import FormulationSpec, Ingredient, Recipe
from formula.orchestrator.runner import Run

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def registry() -> RulebookRegistry:
    return RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)


def _lactose_recipe(api: str) -> Recipe:
    return Recipe(
        api_name=api, candidate_id="draft",
        ingredients=[
            Ingredient(name=api, role="api", amount_mg=160, percent=53),
            Ingredient(name="Lactose monohydrate", role="diluent", amount_mg=95, percent=32),
            Ingredient(name="Croscarmellose sodium", role="superdisintegrant", amount_mg=9, percent=3),
            Ingredient(name="Magnesium stearate", role="lubricant", amount_mg=3, percent=1),
        ],
        process="direct_compression", packaging="Alu-Alu blister")


def _spec(api: str) -> FormulationSpec:
    profile = build_profile(api, base_dir=ROOT, render=False)
    return FormulationSpec(api_name=api, target_patient="pediatric_under_12",
                           dosage_form="tablet").with_profile(profile)


# ---------------------------------------------------------------------------
# 1장 — RDKit이 데모의 전제를 바꾼 지점
# ---------------------------------------------------------------------------
def test_acetaminophen_does_not_trigger_maillard(registry):
    """아세트아미노펜은 아미드라 유당-Maillard 반려가 성립하지 않는다.

    이 테스트가 깨진다면 SMARTS나 배합금기 조인이 바뀐 것이다 — 데모 서사도 함께 봐야 한다.
    """
    spec = _spec("Acetaminophen")
    assert "is_amide_not_amine" in spec.api_functional_groups
    assert "primary_amine" not in spec.api_functional_groups

    result = registry.run(spec, _lactose_recipe("Acetaminophen"), short_circuit=False)
    maillard = [v for v in result.blockers if v.rule_id in ("INC001", "INC002", "INC003")]
    assert not maillard, f"성립하지 않아야 할 Maillard 반려가 발생: {maillard}"


def test_fluoxetine_triggers_maillard_hard_fail(registry):
    """플루옥세틴은 2차 아민 — INC002(Wirth 1998 원문 사례)가 HARD_FAIL을 낸다."""
    spec = _spec("Fluoxetine HCl")
    assert "secondary_amine" in spec.api_functional_groups

    result = registry.run(spec, _lactose_recipe("Fluoxetine HCl"), short_circuit=False)
    assert not result.passed
    assert any(v.rule_id == "INC002" for v in result.blockers)


def test_replacing_lactose_clears_the_block(registry):
    """유당을 만니톨로 바꾸면 반려가 해소된다 — 룰북이 제시한 대안 그대로."""
    recipe = _lactose_recipe("Fluoxetine HCl")
    recipe.ingredients[1] = Ingredient(name="Mannitol", role="diluent", amount_mg=95, percent=32)
    result = registry.run(_spec("Fluoxetine HCl"), recipe, short_circuit=False)
    assert result.passed, [v.reason for v in result.blockers]


def test_sls_row_is_excluded_by_evidence_policy(registry):
    """PED044(SLS)는 근거가 없어(NO_SOURCE_FOUND) 어떤 판정도 만들지 못한다."""
    recipe = _lactose_recipe("Fluoxetine HCl")
    recipe.ingredients.append(
        Ingredient(name="Sodium lauryl sulfate", role="surfactant_wetting", amount_mg=15))
    result = registry.run(_spec("Fluoxetine HCl"), recipe, short_circuit=False)
    assert not [v for v in result.verdicts if v.rule_id == "PED044"]


# ---------------------------------------------------------------------------
# 2장 — 전체 그래프: 반려 → 반성 → 통과
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def golden_run():
    async def go() -> Run:
        run = Run(ROOT, "소아용 플루옥세틴 정제를 설계해줘")
        async for _ in run.stream():
            pass
        return run

    return asyncio.run(go())


def test_graph_completes_without_llm(golden_run):
    """API 키 없이도 그래프가 끝까지 완주해야 한다(시연 안전장치)."""
    assert golden_run.summary()["status"] == "passed"


def test_graph_rejects_then_recovers(golden_run):
    """1라운드는 반려되고, 반성 후 2라운드가 통과한다."""
    summary = golden_run.summary()
    assert summary["reflection_count"] == 1
    assert summary["winner"].startswith("cand-1-")


def test_previous_round_candidates_are_cleared(golden_run):
    """반성 후에는 이전 라운드 후보가 남아 있으면 안 된다(reducer 초기화)."""
    assert all(c.startswith("cand-1-") for c in golden_run.summary()["candidates"])


def test_judges_are_summoned_by_condition(golden_run):
    """소아 대상이므로 REV001(소아 안전)이 소집되고, REV002(가용화)는 소집되지 않는다."""
    summoned = {e.payload.get("reviewer_id")
                for e in golden_run.bus.history if e.kind.value == "judge.summoned"}
    assert "REV001" in summoned      # target_population=='pediatric'
    assert "REV003" in summoned      # always
    assert "REV002" not in summoned  # bcs_class in ['II','IV'] — 해당 없음


def test_consensus_renormalizes_weights(golden_run):
    """소집된 심사관 가중치는 세션 안에서 합=1로 재정규화된다(0.30/0.25 → 0.545/0.455)."""
    consensus = next(e.payload for e in golden_run.bus.history if e.kind.value == "consensus")
    top = consensus["contenders"][0]
    assert abs(sum(top["weights"].values()) - 1.0) < 1e-6
    assert top["weights"]["REV001"] == pytest.approx(0.545, abs=0.001)


def test_scores_cannot_block(golden_run):
    """B모델 — 심사관 점수는 후보를 반려시키지 못한다."""
    consensus = next(e.payload for e in golden_run.bus.history if e.kind.value == "consensus")
    assert consensus["score_affects_pass_fail"] is False


def test_every_event_is_serializable(golden_run):
    """모든 TraceEvent는 SSE로 나갈 수 있어야 한다(웹 UI 계약)."""
    for event in golden_run.bus.history:
        assert event.model_dump_json()
