"""입력 에이전트 — 말을 제안으로 바꾸되, 숫자·SMILES는 지어내지 않는다.

- 제안의 숫자는 사용자가 쓴 글에 있어야 한다(LLM이 낸 값도 이 검사를 통과해야 한다).
- SMILES는 사용자 입력·내장 사전·PubChem에서만 — LLM 기억은 쓰지 않는다.
- SMILES·용량이 없으면 실행 제안은 준비되지 않은 상태(ready=False)로 묻는다.
- 측정 키·스튜디오 행동은 허용된 것만.
- LLM이 없으면 규칙 기반으로 글에서 값만 읽는다.
"""

from pathlib import Path

from formula.agents import input_agent as ia
from formula.experimental_inputs import ExperimentalInputs

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ExperimentalInputs(ROOT)
CATALOG = ia.measurement_catalog(ROOT, INPUTS)


def _respond(out, message, ctx=None, lookup=None, source="llm"):
    ctx = ctx or ia.snapshot("discovery", None, None, CATALOG)
    return ia.build_response(out, source, message, [], ctx, CATALOG, INPUTS, lookup)


def test_numbers_not_in_user_text_are_dropped():
    out = ia.AgentOutput(reply="준비했습니다.", intent="start_run",
                         run=ia.RunDraft(api_name="Ibuprofen", dose_mg=400, target_population="adult"))
    res = _respond(out, "성인용 이부프로펜 정제 설계해 줘")
    p = res["proposals"][0]
    assert "dose_mg" not in p["measured_params"] and not p["ready"] and "dose_mg" in p["missing"]
    assert any("mg" in a for a in res["asks"])


def test_grounded_run_is_ready_with_dictionary_smiles():
    out = ia.AgentOutput(reply="", intent="start_run",
                         run=ia.RunDraft(api_name="Ibuprofen", dose_mg=200, target_population="adult"))
    res = _respond(out, "성인용 이부프로펜 200mg 정제")
    p = res["proposals"][0]
    assert p["ready"] and p["measured_params"]["dose_mg"] == 200
    assert p["smiles_source"]["kind"] == "dictionary"


def test_llm_smiles_is_never_trusted():
    out = ia.AgentOutput(reply="", intent="start_run",
                         run=ia.RunDraft(api_name="Unknownazole", smiles="CCO", dose_mg=10))
    res = _respond(out, "Unknownazole 10mg 설계", lookup=lambda name: {"found": False})
    p = res["proposals"][0]
    assert p["smiles"] == "" and "smiles" in p["missing"] and not p["ready"]


def test_pubchem_smiles_carries_its_source():
    found = {"found": True, "cid": 3672, "url": "https://pubchem.ncbi.nlm.nih.gov/compound/3672",
             "properties": {"SMILES": "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O"}}
    out = ia.AgentOutput(reply="", intent="start_run", run=ia.RunDraft(api_name="Newdrug", dose_mg=50))
    p = _respond(out, "Newdrug 50 mg", lookup=lambda name: found)["proposals"][0]
    assert p["ready"] and p["smiles_source"]["kind"] == "pubchem" and p["smiles_source"]["cid"] == 3672


def _run_ctx():
    run = {"run_id": "r1", "status": "passed", "winner": "cand-0-CONV_DC", "candidates": ["cand-0-CONV_DC", "cand-0-CONV_WG"],
           "ranked": [{"candidate_id": "cand-0-CONV_DC"}],
           "request_groups": [{"measurement_id": "M_DSC", "name": "DSC", "tier": "1", "sample_mg": "10",
                               "result_keys": ["tm_c"], "triggers": ["DRQ_TM"], "reasons": []}]}
    return ia.snapshot("discovery", run, None, CATALOG)


def test_measurements_keep_only_allowed_and_grounded():
    out = ia.AgentOutput(reply="", intent="submit_measurements",
                         measurements={"tm_c": 76, "is_pediatric": 1, "water_content_percent": 0.3})
    res = _respond(out, "녹는점은 76도였어요", ctx=_run_ctx())
    assert res["proposals"][0]["measurements"] == {"tm_c": 76}
    assert any("is_pediatric" in n for n in res["notes"])


def test_only_passed_candidates_can_be_developed():
    out = ia.AgentOutput(reply="", intent="develop_candidate", candidate_id="cand-0-CONV_WG")
    assert _respond(out, "cand-0-CONV_WG로 개발", ctx=_run_ctx())["proposals"] == []
    nudge = ia.nudge(_run_ctx())
    assert nudge["proposals"][0]["candidate_id"] == "cand-0-CONV_DC"


def test_studio_action_must_be_allowed_now():
    study = {"study_id": "s1", "status": "WAITING_CQA_APPROVAL", "state_version": 3, "evaluations": {},
             "prompt": {"title": "CQA", "ask": "", "actions": ["cqa_edit", "cqa_approve"]}}
    ctx = ia.snapshot("studio", None, study, CATALOG)
    bad = ia.AgentOutput(reply="", intent="studio_action", studio_action="region_approve")
    assert _respond(bad, "영역 승인", ctx=ctx)["proposals"] == []
    ok = ia.AgentOutput(reply="", intent="studio_action", studio_action="cqa_approve")
    assert _respond(ok, "CQA 승인", ctx=ctx)["proposals"][0]["action"] == "cqa_approve"


def test_rule_parser_reads_only_what_was_written():
    ctx = ia.snapshot("discovery", None, None, CATALOG)
    out = ia.rule_parse("소아용 이부프로펜 100mg 현탁액 설계해 줘", ctx, CATALOG)
    assert out.intent == "start_run" and out.run.dose_mg == 100 and out.run.target_population == "pediatric"
    out = ia.rule_parse("녹는점 76", _run_ctx(), CATALOG)
    assert out.intent == "submit_measurements" and out.measurements == {"tm_c": 76.0}
    res = ia.build_response(out, "rules", "녹는점 76", [], _run_ctx(), CATALOG, INPUTS)
    assert res["proposals"][0]["measurements"] == {"tm_c": 76.0}


def test_studio_unknown_compression_force_in_rules_mode():
    study = {"study_id": "s1", "status": "WAITING_REQUIRED_DATA", "state_version": 1, "evaluations": {},
             "prompt": {"title": "진입 자료", "ask": "", "actions": ["required_data"]}}
    ctx = ia.snapshot("studio", None, study, CATALOG)
    out = ia.rule_parse("압축력은 몰라요", ctx, CATALOG)
    assert out.studio_action == "required_data"
    assert out.studio_payload["fixed_parameters"][0]["status"] == "UNKNOWN"


def test_daily_token_limit_is_named_and_fails_fast(monkeypatch):
    """하루 한도(TPD) 429는 '분당 한도'가 아니다 — 풀릴 때까지 기다리지 않고 바로 사유를 말한다."""
    import httpx
    import pytest
    from formula.agents import client as C

    body = ('{"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` ... on tokens per day (TPD): '
            'Limit 200000, Used 199000, Requested 4000. Please try again in 16m58.224s."}}')
    err = httpx.HTTPStatusError("429", request=httpx.Request("POST", "https://x"),
                                response=httpx.Response(429, text=body))
    assert abs(C._daily_retry_seconds(err) - (16 * 60 + 58.224)) < 1e-6
    assert C._friendly(err) == C.DAILY_LIMIT_MESSAGE
    monkeypatch.setattr(C, "_DAILY_BLOCK", {m: float("inf") for m in C.GROQ_MODELS})
    with pytest.raises(C.LLMUnavailable, match="일일"):
        C._groq_with_fallback(lambda m: 100, lambda m: None)


def test_contest_api_quota_exhaustion_falls_back_to_free_model(monkeypatch):
    """대회 API가 403(누적 한도 소진)이면 그 뒤로는 Groq로 간다 — 결과를 지어내지 않고 실제 모델로."""
    import httpx
    from pydantic import BaseModel
    from formula.agents import client as C

    class A(BaseModel):
        a: int

    def forbidden(*args, **kwargs):
        raise httpx.HTTPStatusError("403", request=httpx.Request("POST", "https://x"),
                                    response=httpx.Response(403, text="quota"))

    monkeypatch.setattr(C, "providers", lambda: ("dacon", "groq"))
    monkeypatch.setattr(C, "_DACON_EXHAUSTED", {"flag": False})
    monkeypatch.setattr(httpx, "post", forbidden)
    monkeypatch.setattr(C, "_groq_parse", lambda fmt, *a, **k: fmt(a=3))
    assert C.parse_structured(A, "s", "u").a == 3
    assert C._DACON_EXHAUSTED["flag"] and C.provider() == "groq"
