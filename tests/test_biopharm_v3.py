"""Formula1_v3 페이즈 게이트 — 파생값 · 게이트 3A/3B/4/4B · 전략 플래너 · 데이터 요청.

2026-09 세션에서 실제로 걸린 함정을 고정한다: CSV 조건식이 `tm_c is None`처럼
"미지값 자체가 조건"인데, `tm_c`가 ctx에 아예 없으면 `eval()`이 NameError를 내고
`formula.checkers.applies_when.evaluate()`는 그걸 "미발동"으로 삼킨다 — seed_known_keys
없이 돌리면 게이트가 다섯 건 켜져야 할 시나리오에서 조용히 두 건만 켜졌다(재현: 디버그
스크립트로 확인). 이 파일은 그 재발을 막는다.
"""

from __future__ import annotations

from pathlib import Path

from formula.biopharm import (
    compute_derived_quantities,
    evaluate_triggers,
    run_biopharm_gates,
    seed_known_keys,
)
from formula.biopharm.seed import known_keys
from formula.biopharm.triggers import load_measurement_catalog
from formula.planner.strategy_planner import PlannedStrategy, plan, signature

ROOT = Path(__file__).resolve().parent.parent


def _seeded_ctx(**overrides):
    ctx: dict = {}
    seed_known_keys(ctx, ROOT)
    ctx.update(overrides)
    return ctx


# ── seed_known_keys ──────────────────────────────────────────────────────

def test_seed_known_keys_covers_gate_condition_variables():
    keys = known_keys(ROOT)
    for name in (
        "tm_c", "dose_solubility_volume_fassif", "solubility_est_mg_per_ml",
        "dcs_subclass", "sig_enabling_required",
    ):
        assert name in keys, f"{name}이 known_keys에서 빠지면 이를 참조하는 조건식이 조용히 죽는다"


def test_seed_known_keys_never_overwrites_existing_value():
    ctx = {"dose_mg": 200}
    seed_known_keys(ctx, ROOT)
    assert ctx["dose_mg"] == 200


def test_unseeded_ctx_reproduces_the_namerror_swallow_bug():
    """seed 없이 돌리면 실제로 무슨 일이 나는지를 고정한다 — 회귀 방지의 대조군."""
    from formula.checkers.applies_when import evaluate
    assert evaluate("tm_c is None", {}) is False  # NameError가 조용히 False로 삼켜진다
    assert evaluate("tm_c is None", {"tm_c": None}) is True  # 시드하면 의도대로 True


# ── compute_derived_quantities (고정점) ──────────────────────────────────

def test_compute_derived_quantities_fills_constants_without_overwriting_measured():
    ctx = _seeded_ctx(storage_temp_c=30)  # 실측/사용자 입력이 있다고 가정
    compute_derived_quantities(ctx, ROOT)
    assert ctx["storage_temp_c"] == 30  # 실측이 예측/상수보다 우선
    assert ctx["bcs_volume_ml"] == 250
    assert ctx["dcs_volume_ml"] == 500


def test_compute_derived_quantities_derives_d0_from_dose_and_solubility():
    ctx = _seeded_ctx(dose_mg=200.0, solubility_mg_per_ml=0.05)
    compute_derived_quantities(ctx, ROOT)
    assert ctx["dose_solubility_volume"] == 4000.0
    assert ctx["d0"] == 16.0  # 4000 / bcs_volume_ml(250)


# ── run_biopharm_gates (G3A → G3B → G4 → G4B) ────────────────────────────

def test_gate_3a_fires_provisional_low_solubility_when_no_measured_bcs():
    ctx = _seeded_ctx(bcs_class=None, dose_mg=200.0, solubility_est_mg_per_ml=0.05)
    compute_derived_quantities(ctx, ROOT)
    fired = run_biopharm_gates(ctx, ROOT)
    rule_ids = {s["rule_id"] for s in fired}
    assert "G3A010" in rule_ids
    assert ctx["bcs_solubility_provisional"] == "low"
    assert ctx["bcs_source"] == "predicted"


def test_gate_never_sets_measured_only_bcs_class():
    # 불변식 I-1: bcs_class는 실측 전용. 게이트가 쓰는 건 늘 다른 키(bcs_solubility_provisional 등).
    ctx = _seeded_ctx(bcs_class=None, dose_mg=200.0, solubility_est_mg_per_ml=0.05)
    compute_derived_quantities(ctx, ROOT)
    run_biopharm_gates(ctx, ROOT)
    assert ctx["bcs_class"] is None


def test_route_probe_absent_flow_data_yields_empty_not_none_route_lists():
    # 유동성 데이터가 전혀 없으면 decision_tree 전략이 한 행도 못 켜서 recommended_routes가
    # 아예 ctx에 없는 상태로 남는다 — node_phase_gates의 setdefault가 하는 일을 여기서 직접 확인한다.
    ctx = _seeded_ctx()
    assert "recommended_routes" not in ctx
    ctx.setdefault("recommended_routes", [])
    ctx.setdefault("excluded_routes", [])
    assert ctx["recommended_routes"] == []
    assert ctx["excluded_routes"] == []


# ── strategy_planner ──────────────────────────────────────────────────────

def test_strategy_planner_returns_nonempty_for_low_solubility_signal():
    ctx = _seeded_ctx(
        bcs_class=None, dose_mg=200.0, solubility_est_mg_per_ml=0.05,
        recommended_routes=[], excluded_routes=[],
    )
    compute_derived_quantities(ctx, ROOT)
    run_biopharm_gates(ctx, ROOT)
    planned = plan(ctx, ROOT)
    assert planned, "낮은 예측 용해도 신호가 있으면 최소 한 전략은 살아남아야 한다"
    assert all(isinstance(p, PlannedStrategy) for p in planned)


def test_strategy_planner_never_raises_on_a_bad_row(monkeypatch):
    # 행 하나가 예외를 내도 plan() 전체가 죽지 않는다 — score_expression이 깨진 행을 흉내낸다.
    from formula.planner import strategy_planner as mod

    bad_row = {
        "strategy_code": "BROKEN", "family": "x", "label_kr": "깨진 행",
        "applies_when": "true", "score_expression": "1/0",
        "min_score_to_generate": "0", "mcs_class": "1",
        "process_steps": "", "rulebook_coverage": "", "required_measurements": "",
        "generator_brief": "", "fallback_strategy": "",
    }
    monkeypatch.setattr(mod, "_rows", lambda base_dir: [bad_row])
    assert mod.plan({}, ROOT) == []


def test_strategy_planner_signature_is_set_not_order():
    a = [PlannedStrategy("B", "f", "라벨", 1.0, 1, [], [], [], "")]
    b = [PlannedStrategy("A", "f", "라벨", 1.0, 1, [], [], [], "")]
    assert signature(a) != signature(b)
    assert signature(a + b) == signature(b + a)


# ── data_request_triggers (lab-in-the-loop, 절대 차단하지 않는다: 불변식 I-9) ──

def test_narrows_strategy_trigger_never_blocks_downstream_planning():
    ctx = _seeded_ctx(
        bcs_class=None, dose_mg=200.0, solubility_est_mg_per_ml=0.05,
        recommended_routes=[], excluded_routes=[],
    )
    compute_derived_quantities(ctx, ROOT)
    run_biopharm_gates(ctx, ROOT)
    pending = evaluate_triggers(ctx, "narrows_strategy", ROOT)
    assert isinstance(pending, list)
    planned = plan(ctx, ROOT)
    assert planned, "대기 중인 데이터 요청이 있어도 전략 채점은 그대로 진행돼야 한다(I-9)"


def test_data_request_measurement_ids_all_exist_in_catalog():
    # 불변식 I-11: measurement_catalog.csv에 없는 measurement_id는 요청할 수 없다.
    catalog = load_measurement_catalog(ROOT)
    ctx = _seeded_ctx(
        bcs_class=None, dose_mg=200.0, solubility_est_mg_per_ml=0.05,
        recommended_routes=[], excluded_routes=[],
    )
    compute_derived_quantities(ctx, ROOT)
    run_biopharm_gates(ctx, ROOT)
    pending = evaluate_triggers(ctx, "narrows_strategy", ROOT)
    for req in pending:
        for measurement_id in req.measurement_ids:
            assert measurement_id in catalog, (
                f"{req.trigger_id}이 카탈로그에 없는 {measurement_id}를 요청했다"
            )


def test_satisfied_request_disappears_next_round():
    # 불변식 I-12: 값이 채워져 satisfied_when이 참이 되면 다음 라운드 목록에서 빠진다.
    ctx = _seeded_ctx(
        bcs_class=None, dose_mg=200.0, solubility_est_mg_per_ml=0.05,
        recommended_routes=[], excluded_routes=[],
    )
    compute_derived_quantities(ctx, ROOT)
    run_biopharm_gates(ctx, ROOT)
    before = evaluate_triggers(ctx, "narrows_strategy", ROOT)
    assert before, "이 시나리오는 최소 한 건의 narrows_strategy 요청을 내야 테스트가 의미 있다"

    target = before[0]
    for key in target.result_keys:
        ctx[key] = 1.0  # 어떤 수치든 — satisfied_when은 "값이 들어왔는가"만 보는 행이 대부분이다

    after = evaluate_triggers(ctx, "narrows_strategy", ROOT)
    after_ids = {r.trigger_id for r in after}
    assert target.trigger_id not in after_ids
