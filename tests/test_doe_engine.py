"""07_doe 통계 엔진 · 룰 평가기 인수 테스트 — 명세 v6.1 §15, 인계 문서 §8.

골든 값은 `tests/golden/compute_lornoxicam_golden.py`(statsmodels 참조 구현)가 낸 값이다.
이 엔진은 statsmodels 없이 numpy/scipy로 같은 값을 내야 한다(허용오차는 명세 §15 표).
"""

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from formula.development.rules import DoeRulebook, Missing, evaluate
from formula.qbd import doe
from formula.qbd.analysis import Fit, screening_effects
from formula.qbd.design_space import Domain, compute_region, predict_point, propose_verification_points

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="module")
def rb():
    return DoeRulebook(ROOT / "database" / "07_doe")


# ── 룰 평가기 (Sprint 0) ───────────────────────────────────────────────────
def test_rulebook_loads_all_171_rules(rb):
    assert len(rb.rules) == 171
    assert len({r.rule_id for r in rb.rules}) == 171


def test_rule_fixtures_pass_through_production_evaluator(rb):
    """fixture 48건을 **production 평가기**로 통과 (인계 문서 §6 Sprint 0 완료 기준)."""
    fixtures = json.loads((FIX / "rule_fixtures.json").read_text(encoding="utf-8"))
    assert len(fixtures) == 48
    failures = []
    for fx in fixtures:
        mode = fx.get("mode", "demo")
        rule = rb.by_id[fx["rule_id"]]
        if fx["expect"] in ("ENFORCED", "NOT_ENFORCED"):
            got = "ENFORCED" if rb.enforcement_allowed(rule, mode) else "NOT_ENFORCED"
        else:
            try:
                got = "FIRES" if evaluate(rule.tree, fx["context"], rb.functions(mode), rb.consts) else "NOT_FIRES"
            except Missing:
                got = "MISSING"
        if got != fx["expect"]:
            failures.append((fx["id"], fx["rule_id"], fx["expect"], got))
    assert failures == []


def test_production_mode_enforces_nothing_while_all_rules_are_draft(rb):
    assert not any(rb.enforcement_allowed(r, "production") for r in rb.rules)
    assert all(rb.enforcement_allowed(r, "demo") for r in rb.rules)


def test_evaluator_rejects_python_eval_escape(rb, tmp_path):
    """허용되지 않은 AST(속성 메서드 호출, 람다 등)가 CSV에 들어오면 로드가 실패한다."""
    import shutil
    from formula.development.rules import RulebookLoadError
    copy = tmp_path / "07_doe"
    shutil.copytree(ROOT / "database" / "07_doe", copy)
    p = copy / "analysis" / "design_space_rules.csv"
    text = p.read_text(encoding="utf-8").replace("region.domain_policy is None",
                                                 "(lambda: 1)() == 1", 1)
    p.write_text(text, encoding="utf-8")
    with pytest.raises(RulebookLoadError):
        DoeRulebook(copy)


def test_every_reason_code_routes_or_triage(rb):
    for rule in rb.rules:
        if rule.next_state:
            code, nxt, _ = rb.route(rule.result_code, rule.stages[0])
            assert code != "UNKNOWN", rule.rule_id
            assert nxt == rule.next_state, rule.rule_id
    assert rb.route("NOT_A_CODE", "MODEL_VALIDATION")[1] == "WAITING_HUMAN_TRIAGE"


def test_strongest_effect_wins_and_priority_breaks_ties(rb):
    # 마손도 전체 이차: MV006(ROUTE) + MV005(WARNING) 동시 발화 → ROUTE가 전이를 정한다
    ctx = {"model": {"validation_status": "PENDING", "df_resid": 5, "hierarchical": True,
                     "all_terms_estimable": True, "lof_computable": True, "lof_p": 0.5,
                     "pure_error_df": 2, "adj_r2": 0.86, "pred_r2": 0.25, "n": 15, "p": 10,
                     "fit_method": "PREPLANNED", "scope_hash": "s", "inputs": [], "input_batch_ids": [],
                     "residual_pattern": False, "heteroscedastic": False, "runs": [],
                     "local_prediction_se_high": None, "invalid_cause": None},
           "study": {"scope_hash": "s"}}
    ev = rb.evaluate("MODEL_VALIDATION", [("Y2", ctx)], mode="demo", rulebooks=["model_validation_rules"])
    assert ev.decisive.rule_id == "MV006"
    assert ev.next_state == "WAITING_MODEL_APPROVAL"
    assert "MODEL_LOW_PURE_ERROR_DF" in ev.codes("WARNING")


# ── 설계 생성 (Sprint 1) ──────────────────────────────────────────────────
def test_bbd_three_factors_is_15_runs_and_same_seed_same_order():
    f = [doe.Factor("x1", "a", 1, 3), doe.Factor("x2", "b", 5, 15), doe.Factor("x3", "c", 2, 10)]
    d1 = doe.generate("BOX_BEHNKEN", f, seed=7)
    d2 = doe.generate("BOX_BEHNKEN", f, seed=7)
    assert len(d1["runs"]) == 15
    assert [r["std_order"] for r in d1["runs"]] == [r["std_order"] for r in d2["runs"]]
    assert sum(r["center"] for r in d1["runs"]) == 3


def test_res_iv_half_fraction_alias_structure():
    f = [doe.Factor(f"x{i}", s, -1, 1) for i, s in enumerate("abcd")]
    d = doe.generate("FRACTIONAL_FACTORIAL", f, seed=1, centers=0)
    al = doe.alias_structure(d["matrix"], d["symbols"])
    pairs = {tuple(sorted(p)) for p in al["pairs"]}
    # I = ABCD → AB=CD, AC=BD, AD=BC, 주효과는 2인자와 alias 없음 (Resolution IV)
    assert pairs == {("a:b", "c:d"), ("a:c", "b:d"), ("a:d", "b:c")}
    assert d["info"]["resolution"] == 4


def test_ccd_alpha_and_coded_actual_round_trip():
    f = [doe.Factor("x1", "a", 10, 20), doe.Factor("x2", "b", 0, 4)]
    d = doe.generate("CCD", f, seed=3)
    assert d["info"]["alpha"] == pytest.approx(2 ** 0.5, abs=1e-4)
    for r in d["runs"]:
        for fac in f:
            assert fac.to_coded(r["actual"][fac.factor_id]) == pytest.approx(r["coded"][fac.symbol])


# ── Lornoxicam 골든 (명세 §15) ─────────────────────────────────────────────
@pytest.fixture(scope="module")
def lornox():
    d = pd.read_csv(FIX / "lornoxicam_table3.csv")
    coded = {"a": (d.x1_mcc_mannitol_ratio - 2).values, "b": ((d.x2_mixing_time_min - 10) / 5).values,
             "c": ((d.x3_crospovidone_pct - 6) / 4).values}
    ys = {"Y1": d.y1_dispersibility_s.values, "Y2": d.y2_friability_pct.values,
          "Y3": d.y3_de30_pct.values, "Y4": d.y4_cu_av.values}
    Q = doe.quadratic_terms(["a", "b", "c"])
    full = {k: Fit(Q, coded, v) for k, v in ys.items()}
    models = dict(full)
    models["Y2"] = Fit(doe.linear_terms(["a", "b", "c"]), coded, ys["Y2"])
    return coded, full, models


def test_golden_fit_statistics(lornox):
    _, full, models = lornox
    assert full["Y1"].r2 == pytest.approx(0.990, abs=0.01)
    assert full["Y1"].pred_r2 == pytest.approx(0.865, abs=0.01)
    assert full["Y2"].pred_r2 == pytest.approx(0.251, abs=0.01)
    assert models["Y2"].r2 == pytest.approx(0.912, abs=0.01)
    assert models["Y2"].pred_r2 == pytest.approx(0.824, abs=0.01)
    assert full["Y3"].r2 == pytest.approx(0.970, abs=0.01)
    assert full["Y3"].pred_r2 == pytest.approx(0.765, abs=0.01)
    assert full["Y4"].r2 == pytest.approx(0.959, abs=0.01)
    assert full["Y4"].pred_r2 == pytest.approx(0.481, abs=0.01)
    cook = full["Y1"].cooks_distance()
    # 명세 §15는 "run 12, 1.07"이라 쓰지만 run 3과 run 12가 정확히 동률(1.0658)이다 — 참조 구현
    # (statsmodels)의 argmax가 부동소수점 끝자리로 12를 골랐을 뿐. 둘 다 flag되어야 한다.
    top = {i + 1 for i in np.where(np.isclose(cook, cook.max(), rtol=1e-9))[0]}
    assert 12 in top and top == {3, 12}
    assert cook.max() == pytest.approx(1.07, abs=0.02)
    assert full["Y1"].pure_error()["df"] == 2


SPEC = {"Y1": {"acceptance_operator": "LE", "upper": 180}, "Y2": {"acceptance_operator": "LE", "upper": 1.0},
        "Y3": {"acceptance_operator": "GE", "lower": 75}, "Y4": {"acceptance_operator": "LE", "upper": 15}}
FACTORS = [doe.Factor("x1", "a", 1, 3), doe.Factor("x2", "b", 5, 15), doe.Factor("x3", "c", 2, 10)]


@pytest.fixture(scope="module")
def region(lornox):
    _, _, models = lornox
    domain = Domain(doe.box_behnken(3, 3))
    reg = compute_region(models=models, cqas=SPEC, factors=FACTORS, domain=domain, grid_per_axis=21,
                         joint_threshold=0.90, min_edge=0.1)
    return domain, reg


def test_golden_region(region):
    _, reg = region
    s = reg["summary"]
    assert s["grid_points_total"] == 9261
    assert s["grid_points_in_domain"] == 7501
    assert s["mean_ok_fraction"] == pytest.approx(0.772, abs=0.01)
    assert s["feasible_fraction"] == pytest.approx(0.476, abs=0.01)
    assert next(iter(s["binding_cqa_counts"])) == "Y3"        # 경계는 DE30이 주도
    sp = s["setpoint"]
    assert sp["actual"] == {"x1": pytest.approx(2.7), "x2": pytest.approx(12.5), "x3": pytest.approx(6.8)}
    assert sp["joint_probability"] == pytest.approx(0.991, abs=0.002)
    assert s["all_points_in_domain"]


def test_golden_setpoint_family_pi(lornox, region):
    _, _, models = lornox
    level = 1 - 0.05 / 12
    pred = predict_point(models, {"a": 0.7, "b": 0.5, "c": 0.2}, level)
    assert level == pytest.approx(0.99583, abs=1e-5)
    assert pred["Y3"]["mean"] == pytest.approx(82.3, abs=0.1)
    assert pred["Y3"]["pi_lower"] == pytest.approx(71.9, abs=0.1)
    assert pred["Y3"]["pi_upper"] == pytest.approx(92.8, abs=0.1)


def test_verification_points_are_inside_domain_and_off_edge(lornox, region):
    _, _, models = lornox
    domain, reg = region
    plan = propose_verification_points(reg, models=models, cqas=SPEC, factors=FACTORS, domain=domain,
                                       joint_threshold=0.9, min_edge=0.1, family_alpha=0.05,
                                       robustness_delta=0.2, reference={"x1": 3.0, "x2": 11, "x3": 6.23})
    roles = [p["role"] for p in plan["points"]]
    assert roles[:3] == ["SETPOINT", "BOUNDARY", "ROBUSTNESS"]
    assert roles[-1] == "REFERENCE_EXISTING"
    assert plan["pi_policy"]["comparisons"] == 12
    for p in plan["points"][:3]:
        arr = np.array([[p["coded"][s] for s in "abc"]])
        assert domain.contains(arr)[0]
        assert domain.edge_distance(arr)[0] >= 0.1 - 1e-9
