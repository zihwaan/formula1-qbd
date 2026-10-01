"""근거 결손 게이트(발표 자료 ⑤)가 1단계 후보 → 2단계 진입 사이에 실제로 걸려 있는지 — API 수준.

  - 통과 후보마다 결손·요청 시험이 나온다(같은 입력 → 같은 판정, LLM 없음).
  - 결손이 남은 후보는 사유 없이 개발 착수가 409(EVIDENCE_GAPS), 사유를 적으면 Handoff에 사유와 결손이 남는다.
  - 확인시험 결과(적합)가 들어오면 재판정으로 결손이 닫히고 사유 없이 착수된다.
  - 부적합 결과는 전제의 부정 — 사유가 있어도 착수를 막는다(EVIDENCE_FAILED).
또한 무료 모델(Groq) 선택은 비밀번호 접속이면 대회 API를 뒤에 두는 체인이 된다(시연이 빈 결과로 끝나지 않게).
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("FORMULA1_LLM_PROVIDER", "none")

from formula.chem.profile import build_profile                     # noqa: E402
from formula.contracts import FormulationSpec, Ingredient, Recipe   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app_with_final(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMULA1_STAGE2_DB", str(tmp_path / "stage2.db"))
    import importlib
    import web.server as server
    server = importlib.reload(server)
    from formula.orchestrator.runner import Run
    run = Run(ROOT, "이부프로펜 200 mg 습식과립 정제")
    spec = FormulationSpec(api_name="Ibuprofen", dosage_form="tablet").with_profile(
        build_profile("Ibuprofen", base_dir=ROOT, render=False))
    recipe = Recipe(api_name="Ibuprofen", candidate_id="cand-0-WG", strategy="WG", process="wet_granulation",
                    ingredients=[Ingredient(name="Ibuprofen", role="api", amount_mg=200, percent=50),
                                 Ingredient(name="Microcrystalline cellulose", role="diluent", amount_mg=150, percent=38),
                                 Ingredient(name="Magnesium stearate", role="lubricant", amount_mg=4, percent=1)])
    run.final = {"spec": spec, "results": [{"candidate_id": "cand-0-WG", "recipe": recipe, "derived": {},
                                            "passed": True, "verdicts": []}]}
    server.RUNS[run.run_id] = run
    return server, TestClient(server.app), run


def _create(client, run, **extra):
    return client.post("/api/stage2/studies", json={"source": "candidate", "run_id": run.run_id,
                                                    "candidate_id": "cand-0-WG", **extra})


def test_evidence_is_listed_per_passed_candidate(app_with_final):
    server, client, run = app_with_final
    a = client.get(f"/api/runs/{run.run_id}/evidence").json()
    b = client.get(f"/api/runs/{run.run_id}/evidence").json()
    ev = a["candidates"]["cand-0-WG"]
    assert ev["blocking"] and ev["readiness"] == "blocked"
    assert all(g["test_id"] for g in ev["gaps"])                   # 요청은 실제 확인시험을 가리킨다
    assert a["candidates"] == b["candidates"]                      # 결정론


def test_gaps_hold_development_until_waiver_or_results(app_with_final):
    server, client, run = app_with_final
    held = _create(client, run)
    assert held.status_code == 409 and held.json()["detail"]["code"] == "EVIDENCE_GAPS"
    assert held.json()["detail"]["gaps"]

    ok = _create(client, run, evidence_waiver="선행 시험은 개발 1차 배치와 병행 — 발표 시연")
    assert ok.status_code == 200, ok.text
    ev = ok.json()["study"]["source"]["handoff"]["evidence"]
    assert ev["waiver"].startswith("선행 시험") and ev["open"]


def test_passing_results_close_the_gaps(app_with_final):
    server, client, run = app_with_final
    gaps = client.get(f"/api/runs/{run.run_id}/evidence").json()["candidates"]["cand-0-WG"]["blocking"]
    r = client.post(f"/api/runs/{run.run_id}/confirmation", json={
        "candidate_id": "cand-0-WG",
        "entries": [{"requirement_id": g, "outcome": "pass", "value": "적합"} for g in gaps]})
    assert r.status_code == 200, r.text
    assert not r.json()["candidate"]["blocking"]
    assert _create(client, run).status_code == 200


def test_failed_result_blocks_even_with_waiver(app_with_final):
    server, client, run = app_with_final
    gid = client.get(f"/api/runs/{run.run_id}/evidence").json()["candidates"]["cand-0-WG"]["blocking"][0]
    client.post(f"/api/runs/{run.run_id}/confirmation", json={
        "candidate_id": "cand-0-WG", "entries": [{"requirement_id": gid, "outcome": "fail", "value": "분해물 증가"}]})
    r = _create(client, run, evidence_waiver="그래도 진행")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "EVIDENCE_FAILED"


def test_unknown_requirement_is_rejected(app_with_final):
    server, client, run = app_with_final
    r = client.post(f"/api/runs/{run.run_id}/confirmation", json={
        "candidate_id": "cand-0-WG", "entries": [{"requirement_id": "NOPE", "outcome": "pass"}]})
    assert r.status_code == 422


def test_groq_choice_falls_back_to_contest_api_for_full_sessions(monkeypatch):
    from formula.agents import client as c
    monkeypatch.setattr(c, "_base_providers", lambda: ("dacon", "groq"))
    with c.use_llm(c.GROQ_THEN_DACON):
        assert c.providers() == ("groq", "dacon")
    with c.use_llm("groq"):
        assert c.providers() == ("groq",)                          # 게스트 — 무료 모델만
    with c.use_llm("dacon"):
        assert c.providers() == ("dacon", "groq")


def test_evidence_values_recompute_from_phase_gates(app_with_final, monkeypatch):
    """근거 결손 게이트의 입력은 적합/부적합이 아니라 측정값이다(사용자 2026-09-30). 값은 측정값 재계산 경로로 가서
    phase_gates부터 다시 계산하고(트레이스에 남는다), 통과 후보를 규칙 게이트로 다시 판정한 뒤 근거를 다시 판정한다.
    BCS 근거(EVR005)는 용해도 부피 · 흡수율이 들어와 규칙표가 실측 BCS 등급을 만들 때 닫힌다."""
    server, client, run = app_with_final
    run.final["spec"].measured_params["dose_mg"] = 200
    from formula.planner import strategy_planner
    monkeypatch.setattr(strategy_planner, "signature", lambda planned: "SAME")      # 전략 집합 불변 — LLM 재생성 없이 같은 후보를 다시 판정
    run.final["plan_signature"] = "SAME"
    ev = client.get(f"/api/runs/{run.run_id}/evidence").json()["candidates"]["cand-0-WG"]
    items = {i["requirement_id"]: i for i in ev["protocol"]["before_protocol"]}
    assert set(ev["blocking"]) == {"EVR001", "EVR004", "EVR005"}
    assert [f["key"] for f in items["EVR005"]["inputs"]] == ["dose_solubility_volume", "fraction_absorbed"]
    assert all(f["type"] in ("number", "bool") for i in items.values() for f in i["inputs"])

    r = client.post(f"/api/runs/{run.run_id}/measurements", json={
        "measurements": {"aqueous_stability_percent": 98.5, "solubility_mg_per_ml": 0.021}, "grade": "self_measured", "source": "evidence"})
    assert r.status_code == 200, r.text
    out = r.json()
    steps = [(e["node"], e["kind"]) for e in out["trace"]]
    assert steps[0] == ("phase_gates", "node.enter") and ("phase_gates", "phase.gate") in steps
    assert ("plan", "node.exit") in steps and ("gate", "verdict") in steps
    assert out["rejudged"][0]["candidate_id"] == "cand-0-WG" and out["results"][0]["passed"]
    assert any(e["node"] == "phase_gates" and e["kind"] == "node.enter" for e in (x.model_dump(mode="json") for x in run.bus.history))
    assert client.get(f"/api/runs/{run.run_id}/evidence").json()["candidates"]["cand-0-WG"]["blocking"] == ["EVR005"]

    r = client.post(f"/api/runs/{run.run_id}/measurements", json={
        "measurements": {"dose_solubility_volume": 9500, "fraction_absorbed": 90}, "grade": "literature", "source": "evidence"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/runs/{run.run_id}/evidence").json()["candidates"]["cand-0-WG"]["blocking"] == []
    assert _create(client, run).status_code == 200                                    # 결손이 닫혀 사유 없이 착수


def test_evidence_done_flag_counts_as_measured(app_with_final, monkeypatch):
    """'수행' 항목(예: forced_degradation_done)은 체크박스(bool)로 들어와도 실측 기록으로 남아 has_measured()를 채운다."""
    server, client, run = app_with_final
    from formula.planner import strategy_planner
    monkeypatch.setattr(strategy_planner, "signature", lambda planned: "SAME")
    run.final["plan_signature"] = "SAME"
    r = client.post(f"/api/runs/{run.run_id}/measurements", json={"measurements": {"forced_degradation_done": True}, "source": "evidence"})
    assert r.status_code == 200, r.text
    assert run.final["spec"].measured_params.get("forced_degradation_done") == 1.0


def test_agent_takes_evidence_values_in_words(app_with_final, monkeypatch):
    """근거 결손 게이트 값은 입력 에이전트에 말로 넣어도 된다 — 서버가 열린 항목·용량·분자량을 맥락으로 주고, 카드의 값은
    같은 재계산 경로(source agent_evidence)로 가서 phase_gates부터 다시 계산한다."""
    server, client, run = app_with_final
    run.final["spec"].measured_params["dose_mg"] = 200
    from formula.planner import strategy_planner
    monkeypatch.setattr(strategy_planner, "signature", lambda planned: "SAME")
    run.final["plan_signature"] = "SAME"
    msg = "용해도는 pH 1.2, 4.5, 6.8에서 각각 5, 3, 2 mg/mL이고 요중 회수율은 90%야"
    r = client.post("/api/agent/turn", json={"message": msg, "history": [], "run_id": run.run_id})
    assert r.status_code == 200, r.text
    p = r.json()["proposals"][0]
    assert p["source"] == "agent_evidence" and {"EVR004", "EVR005"} <= {e["requirement_id"] for e in p["evidence"]}
    assert p["measurements"]["dose_solubility_volume"] == 100.0 and p["measurements"]["fraction_absorbed"] == 90.0
    r = client.post(f"/api/runs/{run.run_id}/measurements", json={"measurements": p["measurements"], "grade": p["grade"],
                                                                  "source": p["source"]})
    assert r.status_code == 200, r.text
    assert r.json()["trace"][0]["payload"]["source"] == "agent_evidence"
    blocking = client.get(f"/api/runs/{run.run_id}/evidence").json()["candidates"]["cand-0-WG"]["blocking"]
    assert "EVR004" not in blocking and "EVR005" not in blocking


def test_regenerated_candidates_are_judged(app_with_final, monkeypatch):
    """측정값으로 전략 집합이 바뀌어 후보를 다시 설계하면, 새 후보도 그래프와 같은 규칙으로 심사관을 소집해 심사하고 합의한다
    (사용자 2026-10-01: 재설계 후보가 순위 없이 남으면 후보 카드에 심사관·점수·근거가 없다). 심사 이벤트는 재계산 트레이스에 실린다."""
    server, client, run = app_with_final
    run.final["spec"].measured_params["dose_mg"] = 200
    run.final["plan_signature"] = "OLD"
    from formula.agents import generator, judge
    from formula.contracts import EventKind, JudgeVerdict
    from formula.orchestrator.events import emit
    from formula.planner import strategy_planner
    recipe = run.final["results"][0]["recipe"]
    monkeypatch.setattr(strategy_planner, "signature", lambda planned: "NEW")
    monkeypatch.setattr(generator, "generate", lambda spec, code, base, cid, *a, **k: recipe.model_copy(update={"candidate_id": cid, "strategy": code}))

    def fake_evaluate(j, spec, rec, verdicts, base_dir):
        v = JudgeVerdict(rulebook_id=rec.candidate_id, reviewer_id=j.reviewer_id, persona=j.persona, score=0.7, passed=True,
                         weight=j.weight, rationale="근거 문장", citations=["10.1021/js9702067"])
        emit(f"judge:{j.reviewer_id}", EventKind.JUDGE_VERDICT, source="llm", **v.model_dump())
        return v
    monkeypatch.setattr(judge, "evaluate", fake_evaluate)
    r = client.post(f"/api/runs/{run.run_id}/measurements", json={"measurements": {"tm_c": 150}, "source": "evidence"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["regenerated"] and out["summoned"], out.get("summoned")
    steps = [(e["node"].split(":")[0], e["kind"]) for e in out["trace"]]
    assert ("summon", "node.exit") in steps and ("judge", "judge.verdict") in steps and ("consensus", "consensus") in steps
    assert steps.index(("gate", "node.exit")) < steps.index(("summon", "node.exit")) < steps.index(("consensus", "consensus"))
    assert run.final["status"] == "passed" and run.final["consensus"]["winner"]
    assert "judge_events" not in out
