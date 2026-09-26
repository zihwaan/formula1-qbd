"""개발자 수정 과제(2026-09-26) 회귀 — 데모 결과 보고서에서 재현된 결함이 다시 생기지 않게 고정한다.

P0-1 요청 용량·API 존재·최대 용량 · P0-2 염 제거 후 물성 · P0-3 측정값 제출 의도 · P1-1 고정 부형제 ·
P1-2 역할 재매핑 · P1-3 INC014 · P1-4 DHP N–H(test_smarts) · P1-5 이온화·문헌 BCS · P1-6 인용 검증 · P1-7 PI 하한.
"""

from pathlib import Path

import pytest

from formula.checkers.registry import RulebookRegistry
from formula.chem.profile import build_profile
from formula.contracts import FormulationSpec, Ingredient, Recipe, VerdictStatus

ROOT = Path(__file__).resolve().parents[1]
AMLODIPINE_BESYLATE = "CCOC(=O)C1=C(COCCN)NC(C)=C(C1c1ccccc1Cl)C(=O)OC.OS(=O)(=O)c1ccccc1"
LORNOXICAM = "CN1C(=C(C2=C(S1(=O)=O)C=C(S2)Cl)O)C(=O)NC3=CC=CC=N3"


@pytest.fixture(scope="module")
def registry():
    return RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)


def _spec(name, smiles, dose=None, pinned=(), population="geriatric", **measured):
    params = dict(measured)
    if dose is not None:
        params["dose_mg"] = dose
    spec = FormulationSpec(api_name=name, target_patient=population, measured_params=params,
                           required_excipients=list(pinned))
    return spec.with_profile(build_profile(name, smiles=smiles, base_dir=ROOT, render=False))


def _recipe(api_name, api_mg, others, cid="cand-0-CONV_DC"):
    ings = ([Ingredient(name=api_name, role="api", amount_mg=api_mg, percent=5)] if api_mg is not None else [])
    ings += [Ingredient(name=n, role=r, amount_mg=mg, percent=p) for n, r, mg, p in others]
    return Recipe(api_name=api_name, candidate_id=cid, ingredients=ings, process="direct_compression")


BASE = [("Mannitol", "diluent", 150, 75.0), ("Crospovidone", "superdisintegrant", 8, 4.0),
        ("Magnesium stearate", "lubricant", 2, 1.0)]


def _by(result, rule_id):
    return [v for v in result.verdicts if v.rule_id == rule_id]


# ── P0-2 염 제거 ─────────────────────────────────────────────────────────
def test_descriptors_use_parent_not_the_salt(registry):
    spec = _spec("Amlodipine", AMLODIPINE_BESYLATE, dose=2.5)
    p = spec.api_profile
    assert abs(p.descriptors["molecular_weight"] - 408.9) < 0.1 and abs(p.descriptors["tpsa"] - 99.88) < 0.05
    assert abs(p.salt_factor - 1.387) < 0.001 and abs(p.salt_molecular_weight - 567.06) < 0.1
    res = registry.run(spec, _recipe("Amlodipine", 2.5, BASE), short_circuit=False)
    fired = {v.rule_id for v in res.verdicts if v.failed}
    assert not ({"RO5_MW_02", "VEBER_TPSA_02"} & fired), fired


# ── P0-1 API·용량·최대 용량 ──────────────────────────────────────────────
def test_t5_candidate_without_api_is_rejected(registry):
    res = registry.run(_spec("Amlodipine", AMLODIPINE_BESYLATE, dose=2.5), _recipe("Amlodipine", None, BASE),
                       short_circuit=False)
    assert any(v.status == VerdictStatus.HARD_FAIL for v in _by(res, "RC001"))


def test_t6_unit_dose_above_label_max_is_rejected(registry):
    res = registry.run(_spec("Amlodipine", AMLODIPINE_BESYLATE, dose=50), _recipe("Amlodipine", 50, BASE),
                       short_circuit=False)
    mdd = [v for v in res.verdicts if v.rulebook_id == "max_daily_dose"]
    assert mdd and mdd[0].status == VerdictStatus.HARD_FAIL and "10" in mdd[0].reason


def test_dose_mismatch_is_rejected_and_salt_is_converted(registry):
    spec = _spec("Amlodipine", AMLODIPINE_BESYLATE, dose=2.5)
    wrong = registry.run(spec, _recipe("Amlodipine", 10, BASE), short_circuit=False)
    assert any(v.status == VerdictStatus.HARD_FAIL for v in _by(wrong, "RC002"))
    # 베실산염 3.468 mg = 유리염기 2.5 mg — 염 이름이면 염 기준으로 읽는다
    salt = registry.run(spec, _recipe("Amlodipine besylate", 3.468, BASE), short_circuit=False)
    assert all(v.status == VerdictStatus.PASS for v in _by(salt, "RC002"))


def test_missing_dose_is_flagged_not_silently_passed(registry):
    res = registry.run(_spec("Amlodipine", AMLODIPINE_BESYLATE), _recipe("Amlodipine", 5, BASE), short_circuit=False)
    assert _by(res, "RC002")[0].status == VerdictStatus.SOFT_FLAG


def test_requested_dose_above_label_ends_infeasible():
    from formula.orchestrator.graph import _dose_over_label
    from formula.contracts import Verdict, RuleAction
    spec = _spec("Amlodipine", AMLODIPINE_BESYLATE, dose=50)
    v = Verdict(rulebook_id="max_daily_dose", strategy="request_contract", status=VerdictStatus.HARD_FAIL,
                action=RuleAction.HARD_FAIL, evidence={"max_daily_free_base_mg": 10.0})
    assert _dose_over_label({"spec": spec}, [v])
    assert not _dose_over_label({"spec": _spec("Amlodipine", AMLODIPINE_BESYLATE, dose=2.5)}, [v])


# ── P1-1 고정 부형제 ─────────────────────────────────────────────────────
def test_pinned_excipients_must_all_be_present_and_additions_are_labelled(registry):
    spec = _spec("Lornoxicam", LORNOXICAM, dose=8, population="adult",
                 pinned=("Microcrystalline cellulose", "Mannitol", "Crospovidone"))
    missing = registry.run(spec, _recipe("Lornoxicam", 8, BASE), short_circuit=False)
    rc3 = _by(missing, "RC003")[0]
    assert rc3.status == VerdictStatus.HARD_FAIL and "Microcrystalline" in rc3.reason
    full = BASE + [("Microcrystalline cellulose", "diluent", 30, 15.0), ("Lactose monohydrate", "diluent", 20, 10.0)]
    ok = registry.run(spec, _recipe("Lornoxicam", 8, full), short_circuit=False)
    assert _by(ok, "RC003")[0].status == VerdictStatus.PASS
    added = _by(ok, "RC004")
    assert added and "Lactose" in added[0].reason and "Magnesium" in added[0].reason


# ── P1-2 역할 재매핑 ─────────────────────────────────────────────────────
def test_mcc_and_talc_are_judged_by_their_own_ranges(registry):
    spec = _spec("Lornoxicam", LORNOXICAM, dose=8, population="adult")
    others = [("Microcrystalline cellulose", "binder", 60, 30.0), ("Mannitol", "diluent", 120, 60.0),
              ("Talc", "glidant", 6, 3.0), ("Magnesium stearate", "lubricant", 2, 1.0)]
    res = registry.run(spec, _recipe("Lornoxicam", 8, others), short_circuit=False)
    fired = {v.rule_id for v in res.verdicts if v.failed}
    assert "FR002" not in fired and "FR006" not in fired, fired
    assert any(v.rulebook_id == "excipient_role_map" for v in res.verdicts)


# ── P1-3 INC014 ──────────────────────────────────────────────────────────
def test_inc014_becomes_a_doe_factor_candidate_not_a_soft_flag(registry):
    res = registry.run(_spec("Lornoxicam", LORNOXICAM, dose=8, population="adult"),
                       _recipe("Lornoxicam", 8, BASE), short_circuit=False)
    inc = _by(res, "INC014")
    assert inc and inc[0].status == VerdictStatus.ADVISORY and inc[0].evidence.get("doe_factor_candidate")


# ── P1-5 이온화·문헌 BCS ────────────────────────────────────────────────
def _phase_ctx(spec):
    from formula.biopharm import run_biopharm_gates, seed_known_keys
    from formula.biopharm.derived import compute_derived_quantities
    from formula.biopharm.structure import apply_structure_signals
    from formula.checkers.applies_when import spec_context
    ctx = spec_context(spec, {})
    seed_known_keys(ctx, ROOT)
    apply_structure_signals(ctx, spec, ROOT)
    compute_derived_quantities(ctx, ROOT)
    run_biopharm_gates(ctx, ROOT)
    return ctx


def test_lornoxicam_uses_literature_not_a_single_esol_prediction():
    ctx = _phase_ctx(_spec("Lornoxicam", LORNOXICAM, dose=8, population="adult"))
    assert ctx["ionizable"] is True
    assert ctx["bcs_solubility_provisional"] == "low" and ctx["bcs_source"] == "literature"


def test_ionizable_drug_without_literature_is_undetermined_and_asks_ph_solubility():
    from formula.biopharm.triggers import evaluate_triggers, _reason
    ctx = _phase_ctx(_spec("Amlodipine", AMLODIPINE_BESYLATE, dose=2.5))
    assert ctx["bcs_solubility_provisional"] == "undetermined"
    pending = {p.trigger_id for p in evaluate_triggers(ctx, "narrows_strategy", ROOT)}
    assert "DRQ_SOL" in pending
    assert _reason("DRQ_SOL", ctx, "")[0] == "ph_dependent"


# ── P1-6 인용 검증 ───────────────────────────────────────────────────────
def test_citations_are_verified_against_the_pool():
    from formula.agents import citations as cite
    spec = _spec("Lornoxicam", LORNOXICAM, dose=8, population="adult")
    pool = cite.pool(spec, ROOT)
    ok, rejected = cite.verify(["PMC3225520", "J. Pharm. Sci. 2019"], pool)
    assert [c["id"] for c in ok] == ["PMC3225520"] and rejected == ["J. Pharm. Sci. 2019"]
    assert cite.normalize("https://doi.org/10.3390/PH15121463") == ("doi", "10.3390/ph15121463")


def test_uncited_judge_score_is_void(monkeypatch):
    import formula.agents.judge as judge
    from formula.contracts import JudgeSpec
    monkeypatch.setattr(judge, "stream_text", lambda *a, **k: "소견")
    import formula.agents.client as client
    monkeypatch.setattr(client, "parse_structured",
                        lambda fmt, *a, **k: judge.JudgeOutput(score=0.9, rationale="근거 없음", citations=[]))
    spec = _spec("Lornoxicam", LORNOXICAM, dose=8, population="adult")
    out = judge.evaluate(JudgeSpec(reviewer_id="REV003", persona="공정", weight=0.25), spec,
                         _recipe("Lornoxicam", 8, BASE), [], ROOT)
    assert out is None


# ── P1-7 PI 하한 ─────────────────────────────────────────────────────────
def test_prediction_interval_is_truncated_at_zero():
    import numpy as np
    from formula.qbd import doe
    from formula.qbd.analysis import Fit
    from formula.qbd.design_space import predict_point
    coded = {"a": np.array([-1, 1, -1, 1, 0, 0, 0.0]), "b": np.array([-1, -1, 1, 1, 0, 0, 0.0])}
    y = np.array([0.5, 1.2, 0.3, 2.0, 0.4, 0.6, 0.2])
    fit = Fit(doe.linear_terms(["a", "b"]), coded, y)
    out = predict_point({"AV": fit}, {"a": -1.0, "b": 1.0}, 0.99)["AV"]
    assert out["pi_lower"] >= 0 and (out["pi_lower_raw"] < 0) == out["pi_truncated"]


# ── P0-3 측정값 제출 의도 ────────────────────────────────────────────────
def test_measurement_sentence_from_the_demo_becomes_a_submit_card():
    from formula.agents import input_agent as ia
    from formula.experimental_inputs import ExperimentalInputs
    inputs = ExperimentalInputs(ROOT)
    catalog = ia.measurement_catalog(ROOT, inputs)
    run = {"run_id": "r", "status": "passed", "candidates": [], "ranked": [],
           "request_groups": [{"measurement_id": "M_DSC", "name": "DSC", "tier": "1", "sample_mg": "10",
                               "result_keys": ["tm_c"], "triggers": ["DRQ_TM"], "reasons": []}]}
    ctx = ia.snapshot("discovery", run, None, catalog)
    text = "DSC 측정 결과: Tm 317 도. 실험 용해도는 0.00005 mg/mL."
    out, source = ia.run_turn(text, [], ctx, catalog)
    assert out.intent == "submit_measurements" and source == "rules-first"
    card = ia.build_response(out, source, text, [], ctx, catalog, inputs)["proposals"][0]
    assert card["measurements"] == {"tm_c": 317.0, "solubility_mg_per_ml": 5e-05}
