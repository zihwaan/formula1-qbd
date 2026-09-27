"""전수검사(2026-09-26) — 조건식이 참조하는 값이 실제로 만들어지는지, 시연 카드의 확인 항목이 성립하는지.

- 다성분 금기표는 성분 '부류' 어휘로 쓰여 있는데, 그 부류를 처방에서 판별하는 다리가 없어 한 번도 발동할 수
  없었다(config/component_classes.yaml).
- 트리거가 결과 키로 요구하는 값(thermally_stable_near_tm·api_pka_base·psd_dissolution_done·
  solubility_residue_form_confirmed)이 측정 카탈로그 산출 필드에 없어 요청이 닫힐 수 없었다.
- 약물 함량(drug_loading_pct)을 아무도 계산하지 않아 저함량 → 함량균일성 규칙(RTE008)이 죽어 있었다.
- 약산성 페놀만 있는 약(ivacaftor)은 위장관 pH에서 이온화가 바뀌지 않는다 — BCS 잠정 판정에서 '이온화'로 세지 않는다.
- 코드명(VX-770)은 일반명으로 바꾸지 않는다(블라인드 시연), 철자 오류는 바로잡는다.
"""
import csv
from pathlib import Path

import pytest

from formula.checkers.registry import RulebookRegistry
from formula.chem.profile import build_profile
from formula.contracts import EventKind, FormulationSpec, Ingredient, Recipe, VerdictStatus

ROOT = Path(__file__).resolve().parents[1]
AML_BESYLATE_CARD = "CCOC(=O)C1=C(COCCN)NC(C)=C(C(=O)OC)C1c1ccccc1Cl.OS(=O)(=O)c1ccccc1"   # 시연 카드 2의 표기
AML_BESYLATE = "CCOC(=O)C1=C(COCCN)NC(C)=C(C1c1ccccc1Cl)C(=O)OC.OS(=O)(=O)c1ccccc1"
LORNOXICAM = "CN1C(=C(C2=C(S1(=O)=O)C=C(S2)Cl)O)C(=O)NC3=CC=CC=N3"
IVACAFTOR = "CC(C)(C)C1=CC(=C(C=C1NC(=O)C2=CNC3=CC=CC=C3C2=O)O)C(C)(C)C"


@pytest.fixture(scope="module")
def registry():
    return RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)


def _spec(name, smiles, dose, **measured):
    s = FormulationSpec(api_name=name, target_patient="adult", measured_params={"dose_mg": dose, **measured})
    return s.with_profile(build_profile(name, smiles=smiles, base_dir=ROOT, render=False))


def test_card2_smiles_variant_is_the_same_parent():
    a = build_profile("a", smiles=AML_BESYLATE_CARD, base_dir=ROOT, render=False)
    b = build_profile("b", smiles=AML_BESYLATE, base_dir=ROOT, render=False)
    assert a.inchikey == b.inchikey and abs(a.descriptors["molecular_weight"] - 408.9) < 0.1
    assert "has_primary_aliphatic_amine" in a.flag_names() and "has_cyclic_secondary_amine" not in a.flag_names()


def test_multicomponent_rules_can_fire(registry):
    """아민염 + 환원당 + 알칼리 활택제 + (수계 공정의) 물 → MC001. 건식이면 물이 없어 발동하지 않는다."""
    spec = _spec("Amlodipine", AML_BESYLATE, 2.5)
    ings = [Ingredient(name="Amlodipine besylate", role="api", amount_mg=3.47),
            Ingredient(name="Lactose monohydrate", role="diluent", amount_mg=150),
            Ingredient(name="Magnesium stearate", role="lubricant", amount_mg=2)]
    wet = registry.run(spec, Recipe(api_name="Amlodipine", candidate_id="c-WG", ingredients=ings,
                                    process="wet_granulation"), short_circuit=False)
    assert any(v.rule_id == "MC001" and v.failed for v in wet.verdicts)
    dry = registry.run(spec, Recipe(api_name="Amlodipine", candidate_id="c-DC", ingredients=ings,
                                    process="direct_compression"), short_circuit=False)
    assert not any(v.rule_id == "MC001" and v.failed for v in dry.verdicts)


def test_every_trigger_result_key_is_a_catalog_output():
    cat = {r["measurement_id"]: set(r["output_fields"].split(";"))
           for r in csv.DictReader(open(ROOT / "database/reference/measurement_catalog.csv", encoding="utf-8-sig"))}
    for r in csv.DictReader(open(ROOT / "database/reference/data_request_triggers.csv", encoding="utf-8-sig")):
        outs = set().union(*(cat.get(m.strip(), set()) for m in r["measurement_id"].split(";")))
        for k in [x.strip() for x in r["result_keys"].split(";") if x.strip()]:
            assert k in outs, f"{r['trigger_id']}의 결과 키 {k}를 {r['measurement_id']}가 산출하지 않는다 — 요청이 닫힐 수 없다"


def test_low_drug_loading_raises_content_uniformity_flag(registry):
    """시연 카드 1: 250 mg 정제 중 로르녹시캄 8 mg(3.2%) → RTE008(저함량 → 함량균일성)."""
    spec = _spec("Lornoxicam", LORNOXICAM, 8)
    recipe = Recipe(api_name="Lornoxicam", candidate_id="c", process="direct_compression", ingredients=[
        Ingredient(name="Lornoxicam", role="api", amount_mg=8), Ingredient(name="Microcrystalline cellulose", role="diluent", amount_mg=166),
        Ingredient(name="Mannitol", role="diluent", amount_mg=55), Ingredient(name="Crospovidone", role="superdisintegrant", amount_mg=16),
        Ingredient(name="Sodium lauryl sulfate", role="surfactant_wetting", amount_mg=5)])
    res = registry.run(spec, recipe, short_circuit=False)
    assert res.derived["drug_loading_pct"] == pytest.approx(3.2, abs=0.01)
    assert any(v.rule_id == "RTE008" and v.failed for v in res.verdicts)


@pytest.mark.parametrize("angle, dc_allowed", [(42, True), (48, False)])
def test_card1_flow_contrast(registry, angle, dc_allowed):
    """시연 카드 1 장면 1: 안식각 42° → DC 유지, 48° → DC 배제."""
    spec = _spec("Lornoxicam", LORNOXICAM, 8, angle_of_repose=angle, compressibility_index=22, hausner_ratio=1.28)
    res = registry.run(spec, Recipe(api_name="x", candidate_id="__probe__"), short_circuit=False, max_priority=11)
    assert ("DC" in (res.derived.get("recommended_routes") or [])) == dc_allowed
    assert ("DC" in (res.derived.get("excluded_routes") or [])) == (not dc_allowed)


def test_weak_phenol_only_is_not_gi_ionizable():
    from test_devfix_0926 import _phase_ctx
    ctx = _phase_ctx(_spec("VX-770", IVACAFTOR, 150))
    assert ctx["ionizable"] is True and ctx["ionizable_gi"] is False
    assert ctx["bcs_solubility_provisional"] == "low"       # 예측(ESOL)으로 잠정 저용해도 — 카드 3 장면 1


def test_code_names_are_not_replaced_but_typos_are():
    from formula.literature import is_spelling_variant
    assert is_spelling_variant("Lornoxcam", "Lornoxicam")
    assert not is_spelling_variant("VX-770", "Ivacaftor")


def test_dispersible_tablet_is_understood_by_intake():
    from formula.agents.intake import _fallback
    assert _fallback("성인용 로르녹시캄 8 mg 분산정을 설계해 줘").dosage_form == "dispersible_tablet"


def test_card2_abdoh_multicomponent_rule_separates_wet_from_dry(registry):
    """시연 카드 2 심화: 유당 + Mg stearate + 물 공존 시 불안정(Abdoh 2004) — 1:1(건식)은 MC002 미발동, 수계 습식과립은 발동."""
    spec = _spec("Amlodipine", AML_BESYLATE, 2.5)
    ings = [Ingredient(name="Amlodipine besylate", role="api", amount_mg=3.468),
            Ingredient(name="Lactose monohydrate", role="diluent", amount_mg=150),
            Ingredient(name="Magnesium stearate", role="lubricant", amount_mg=2)]
    fired = lambda proc: any(v.rule_id == "MC002" and v.failed for v in registry.run(
        spec, Recipe(api_name="Amlodipine", candidate_id="c", ingredients=ings, process=proc), short_circuit=False).verdicts)
    assert fired("wet_granulation") and not fired("direct_compression")


def test_component_class_vocabulary_names_exist_in_the_multicomponent_table():
    """번역표의 부류·조건 이름은 다성분 금기표에 실제로 있는 어휘여야 한다 — 오타난 이름은 아무 규칙도 켜지 못한다."""
    import csv
    import yaml
    cfg = yaml.safe_load((ROOT / "config/component_classes.yaml").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((ROOT / "database/02_incompatibility/incompatibility_multicomponent.csv")
                               .open(encoding="utf-8-sig")))
    comps = {c.strip() for r in rows for c in r["component_set"].split(";")}
    conds = " ".join(r["required_conditions"].lower() for r in rows)
    names = (set(cfg["excipient_master_columns"]) | set(cfg["excipient_names"]) | set(cfg["api_groups"])
             | {"alkaline_lubricant", "amine_salt_API"})
    assert names <= comps, names - comps
    for tok in cfg["aqueous_process_water"]["tokens"] + cfg["always_present"]["tokens"]:
        assert tok in comps or tok in conds, tok


def test_code_name_blind_masks_real_names_in_events_and_llm_text():
    """카드 3: 개발코드로 요청하면 LLM이 기억으로 채운 일반명·라벨 제품명이 이벤트와 LLM 입출력에서 가려진다."""
    from types import SimpleNamespace
    from formula.agents.client import _blind
    from formula.agents.intake import _development_code, _real_names
    from formula.orchestrator.events import EventBus, emit, set_blind
    assert _development_code("신규 후보물질 VX-770의 성인용 경구 정제") == "VX-770"
    assert _development_code("성인용 이부프로펜 정제, 이산화티타늄 E171") == ""
    lit = {"compound": {"properties": {"Title": "Ivacaftor"}}}
    names = _real_names(lit, SimpleNamespace(inchikey="PURKAOJPTOLRMP-UHFFFAOYSA-N"), ROOT, "VX-770")
    assert {"Ivacaftor", "ivacaftor", "KALYDECO"} <= set(names)
    with EventBus("t") as bus:
        set_blind(names)
        emit("judge", EventKind.JUDGE_VERDICT, rationale="Ivacaftor는 KALYDECO (ivacaftor) 라벨 …")
        assert "ivacaftor" not in bus.history[-1].payload["rationale"].lower()
        assert "kalydeco" not in bus.history[-1].payload["rationale"].lower()
        assert _blind("the ivacaftor SDD") == "the VX-770 SDD"
    assert _blind("the ivacaftor SDD") == "the ivacaftor SDD"   # 블라인드 밖에서는 그대로


def test_blind_stream_masks_names_split_across_deltas():
    from formula.agents.client import _blind_stream
    from formula.orchestrator.events import EventBus, set_blind
    got = []
    with EventBus("t"):
        set_blind({"Ivacaftor": "VX-770"})
        cb, flush = _blind_stream(got.append)
        for d in ["분무건조 ", "Iva", "caf", "tor", " 분산체는 안정하다"]:
            cb(d)
        flush()
    assert "".join(got) == "분무건조 VX-770 분산체는 안정하다"
