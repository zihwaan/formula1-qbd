"""후보 탐색 — 되돌림·계획·실험 요청 불변식.

- 반려는 사유별 복귀 지점으로 간다(backtrack_transitions.csv) — 첨가제면 같은 전략으로 성분만(GATE).
- 계획은 되돌림 제약(전략·경로 제외, 가족 요구/감점)을 반영하고, 남은 전략이 없으면 QTPP 재검토.
- 측정 결과가 전제를 부정하면 그 전략을 뺀다(예: ASD 비혼화).
- 같은 시험을 가리키는 요청은 하나로 합치고, 시료가 적은 시험부터 묻는다.
"""

from pathlib import Path
from types import SimpleNamespace

from formula.biopharm.triggers import group_requests, load_measurement_catalog
from formula.contracts import Verdict, VerdictStatus
from formula.planner import backtrack, strategy_planner

ROOT = Path(__file__).resolve().parents[1]


def _verdict(rulebook_id, status=VerdictStatus.HARD_FAIL, **evidence):
    return Verdict(rulebook_id=rulebook_id, strategy="pairwise_membership", rule_id="X001",
                   status=status, reason="test", evidence=evidence)


def test_incompatibility_backtracks_to_gate_and_excludes_the_excipient():
    results = [{"passed": False, "recipe": SimpleNamespace(strategy="CONV_DC", candidate_id="cand-0-CONV_DC"),
                "verdicts": [_verdict("incompatibility_1to1", excipient="Lactose monohydrate")]}]
    d = backtrack.combine(backtrack.match_rejection(results, ROOT), {})
    assert d.transition_id == "BT001" and d.return_phase == "GATE"
    assert d.patch == {"exclude_ingredient": ["Lactose monohydrate"]}


def test_process_rule_goes_deeper_and_excludes_the_strategy():
    results = [{"passed": False, "recipe": SimpleNamespace(strategy="CONV_DC", candidate_id="cand-0-CONV_DC"),
                "verdicts": [_verdict("incompatibility_1to1", excipient="Lactose monohydrate"),
                             _verdict("direct_compression")]}]
    d = backtrack.combine(backtrack.match_rejection(results, ROOT), {})
    assert d.return_phase == "G6R"                     # 가장 깊은 복귀가 이긴다
    assert d.patch["exclude_strategy"] == ["CONV_DC"] and "exclude_ingredient" in d.patch   # 제약은 모두 쌓인다


def test_same_phase_three_times_escalates_one_level():
    results = [{"passed": False, "recipe": SimpleNamespace(strategy="CONV_DC", candidate_id="cand-3-CONV_DC"),
                "verdicts": [_verdict("incompatibility_1to1", excipient="Lactose monohydrate")]}]
    d = backtrack.combine(backtrack.match_rejection(results, ROOT), {"GATE": 3})
    assert d.return_phase == "G6R" and d.escalated_from == "GATE"
    assert "CONV_DC" in d.patch["exclude_strategy"]


def _ctx():
    return {"recommended_routes": ["DC", "DG", "WG"], "excluded_routes": [], "dcs_solubility": "adequate",
            "bcs_class": None, "sig_particle_size_suitable": None, "sig_enabling_required": None}


def test_plan_respects_constraints_and_empties_into_qtpp_review():
    full = [p.strategy_code for p in strategy_planner.plan(_ctx(), ROOT)]
    assert full == ["CONV_DC", "CONV_DG", "CONV_WG"]
    cut = [p.strategy_code for p in strategy_planner.plan(_ctx(), ROOT, constraints={"exclude_strategy": ["CONV_DC"]})]
    assert cut == ["CONV_DG", "CONV_WG"]
    no_route = strategy_planner.plan(_ctx(), ROOT, constraints={"exclude_route": ["DC", "DG", "WG"]})
    assert no_route == []                               # 그래프는 여기서 qtpp_review로 간다


def test_measurement_that_negates_asd_removes_it():
    catalog = load_measurement_catalog(ROOT)
    ds = backtrack.match_measurements({"asd_miscible": False, "asd_feasibility_done": True},
                                      ["ASD_SDD", "MICRO"], ROOT, catalog)
    patches = [d.patch for d in ds if d.transition_id == "BT021"]
    assert patches == [{"exclude_strategy": ["ASD_SDD"]}]          # 미분화(MICRO)는 건드리지 않는다


def test_glass_forming_class_i_penalizes_asd_family_only():
    catalog = load_measurement_catalog(ROOT)
    ds = backtrack.match_measurements({"gfa_class": "I"}, ["ASD_SDD", "MICRO"], ROOT, catalog)
    patch = backtrack.apply({}, next(d.patch for d in ds if d.transition_id == "BT026"))
    assert patch["exclude_strategy"] == ["ASD_SDD"] and patch["penalize_family"] == ["ENABLING_ASD"]


def test_same_test_is_asked_once_and_cheapest_first():
    pending = [
        {"trigger_id": "DRQ_SOLIDFORM", "measurement_ids": ["M_XRPD", "M_DSC", "M_TGA", "M_KF"],
         "result_keys": ["tm_c", "crystalline_form_id", "water_content_percent"], "label": "a"},
        {"trigger_id": "DRQ_TM", "measurement_ids": ["M_DSC"], "result_keys": ["tm_c"], "label": "b"},
        {"trigger_id": "DRQ_SOL", "measurement_ids": ["M_EQSOL"],
         "result_keys": ["solubility_mg_per_ml"], "label": "c"},
    ]
    groups = group_requests(pending, ROOT)
    ids = [g["measurement_id"] for g in groups]
    assert ids.count("M_DSC") == 1                      # DSC 한 번으로 두 요청을 푼다
    dsc = next(g for g in groups if g["measurement_id"] == "M_DSC")
    assert dsc["triggers"] == ["DRQ_SOLIDFORM", "DRQ_TM"] and dsc["result_keys"] == ["tm_c"]
    assert ids.index("M_EQSOL") > ids.index("M_DSC")    # Tier 1(10 mg)이 Tier 2(30 mg)보다 먼저
    assert [g["measurement_id"] for g in group_requests(pending, ROOT, declined=["DRQ_SOL"])].count("M_EQSOL") == 0


def test_solubility_request_says_why_it_fired():
    from formula.biopharm.triggers import _reason
    kind, text = _reason("DRQ_SOL", {"logs_esol": -3.1, "logs_gse": -4.3}, "")
    assert kind == "disagreement" and "어긋나" in text
    kind, _ = _reason("DRQ_SOL", {"logs_esol": -5.0, "logs_gse": None}, "")
    assert kind == "low_or_unknown"
