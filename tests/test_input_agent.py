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


def test_rule_parser_reads_only_what_was_written():
    ctx = ia.snapshot("discovery", None, None, CATALOG)
    out = ia.rule_parse("소아용 이부프로펜 100mg 현탁액 설계해 줘", ctx, CATALOG)
    assert out.intent == "start_run" and out.run.dose_mg == 100 and out.run.target_population == "pediatric"
    out = ia.rule_parse("녹는점 76", _run_ctx(), CATALOG)
    assert out.intent == "submit_measurements" and out.measurements == {"tm_c": 76.0}
    res = ia.build_response(out, "rules", "녹는점 76", [], _run_ctx(), CATALOG, INPUTS)
    assert res["proposals"][0]["measurements"] == {"tm_c": 76.0}


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


IVACAFTOR = "CC(C)(C)C1=CC(=C(C=C1NC(=O)C2=CNC3=CC=CC=C3C2=O)O)C(C)(C)C"


def _pubchem_by_code(name):
    """PubChem은 개발코드 동의어로도 구조를 찾는다(VX-770 → CID 16220172, 표제명 Ivacaftor)."""
    return {"found": True, "cid": 16220172, "url": "https://pubchem.ncbi.nlm.nih.gov/compound/16220172",
            "properties": {"Title": "Ivacaftor", "SMILES": IVACAFTOR}}


def test_development_code_stays_the_name_and_real_names_are_masked():
    """시연 쿼리 카드 수정판 실행 보고서(2026-09-29) §5-1 — 모델이 기억으로 'Ivacaftor'를 채워 카드 제목·요청문에 실명이 들어가
    블라인드가 깨졌다. 코드가 이름이고, 모델 문장의 실명(표제명·같은 구조의 라벨 제품명)도 코드로 가린다."""
    msg = "신규 후보물질 VX-770의 성인용 경구 정제 제형 전략을 세워 줘. 1회 150 mg이고, 구조식만 있고 실측 자료는 거의 없어."
    out = ia.AgentOutput(reply="VX-770은 ivacaftor(Kalydeco)입니다.", intent="start_run",
                         run=ia.RunDraft(api_name="Ivacaftor", dose_mg=150, target_population="adult", dosage_form="tablet"))
    res = _respond(out, msg, lookup=_pubchem_by_code)
    p = res["proposals"][0]
    assert p["ready"] and p["smiles_source"]["kind"] == "pubchem" and p["title"] == "설계 실행: 성인용 VX-770 정제"
    text = str(res).lower()
    assert "ivacaftor" not in text and "kalydeco" not in text
    assert "VX-770" in p["request"]


def test_real_name_typed_by_user_is_not_replaced():
    out = ia.AgentOutput(reply="", intent="start_run", run=ia.RunDraft(api_name="Ivacaftor", dose_mg=150, target_population="adult"))
    res = _respond(out, "성인용 ivacaftor 150 mg 정제", lookup=_pubchem_by_code)
    assert "Ivacaftor" in res["proposals"][0]["title"]


def test_running_blind_map_masks_later_turns():
    out = ia.AgentOutput(reply="이 물질은 ivacaftor라서 분무건조가 맞습니다.", intent="explain")
    res = ia.build_response(out, "llm", "왜 분무건조야?", [], ia.snapshot("discovery", None, None, CATALOG), CATALOG, INPUTS,
                            None, {"ivacaftor": "VX-770"})
    assert "ivacaftor" not in res["reply"].lower() and "VX-770" in res["reply"]


# ── 근거 결손 게이트 값을 말로 받기 (사용자 2026-09-30: 용해도는 pH마다, 투과도는 단위가 제각각이라 자연어가 편하다) ──
def _evidence_ctx(dose=100.0):
    run = {"run_id": "r1", "status": "passed", "winner": "cand-0-WG", "candidates": ["cand-0-WG"],
           "ranked": [{"candidate_id": "cand-0-WG"}], "request_groups": []}
    items = [
        {"requirement_id": "EVR004", "label": "실험 용해도 (pH 1.2 / 4.5 / 6.8)",
         "inputs": [{"key": "solubility_mg_per_ml", "type": "number", "label": "최저 평형용해도 (pH 1.2–6.8)", "unit": "mg/mL"}]},
        {"requirement_id": "EVR005", "label": "BCS 등급 근거 자료",
         "inputs": [{"key": "dose_solubility_volume", "type": "number", "label": "용량/용해도 부피", "unit": "mL"},
                    {"key": "fraction_absorbed", "type": "number", "label": "흡수율", "unit": "%"}]},
        {"requirement_id": "EVR002", "label": "강제분해 프로파일 (가수분해·산화·열)",
         "inputs": [{"key": "forced_degradation_done", "type": "bool", "label": "강제분해 수행", "unit": ""}]},
    ]
    return ia.snapshot("discovery", run, None, CATALOG, evidence={"items": items, "dose_mg": dose, "mw": 206.3})


def test_evidence_values_in_words_become_an_evidence_card():
    msg = "pH 1.2에서 2.1 mg/mL, 4.5에서 0.35 mg/mL, pH 6.8에서 40 µg/mL였고 흡수율 92%야"
    ctx = _evidence_ctx()
    out = ia.rule_parse(msg, ctx, CATALOG)
    assert out.intent == "submit_measurements" and out.observations
    res = ia.build_response(out, "rules", msg, [], ctx, CATALOG, INPUTS)
    p = res["proposals"][0]
    assert p["measurements"] == {"solubility_mg_per_ml": 0.04, "dose_solubility_volume": 2500.0, "fraction_absorbed": 92.0}
    assert p["source"] == "agent_evidence" and {e["requirement_id"] for e in p["evidence"]} == {"EVR004", "EVR005"}
    assert any("2500 mL" in line for line in p["lines"]) and "근거 결손 게이트" in res["reply"]
    assert "용량/용해도 부피 (mL)" in p["labels"]["dose_solubility_volume"]


def test_llm_bcs_numbers_go_through_the_code():
    """LLM이 '절대 생체이용률 70%'를 흡수율 70으로 곧바로 넣어도 쓰지 않는다 — 85% 미만 BA는 저흡수의 근거가 아니다."""
    out = ia.AgentOutput(reply="흡수율 70%로 제출합니다.", intent="submit_measurements", measurements={"fraction_absorbed": 70})
    res = _respond(out, "절대 생체이용률 70%", ctx=_evidence_ctx())
    assert all("fraction_absorbed" not in p["measurements"] for p in res["proposals"])
    assert any("85" in n for n in res["notes"])


def test_ph_tagged_solubility_is_not_read_as_the_minimum_by_rules_first():
    """'용해도 2.1 mg/mL (pH 1.2)'를 이름+숫자 규칙이 최저 용해도 2.1로 잡으면 안 된다 — 관측으로 읽고 pH별 최저값을 쓴다."""
    msg = "용해도 2.1 mg/mL (pH 1.2), 0.02 mg/mL (pH 6.8)"
    out, source = ia.run_turn(msg, [], _evidence_ctx(), CATALOG)
    res = ia.build_response(out, source, msg, [], _evidence_ctx(), CATALOG, INPUTS)
    m = res["proposals"][0]["measurements"]
    assert m == {"dose_solubility_volume": 5000.0}                          # pH 6.8에서 250 mL 초과 → 저용해도 확정, 4.5 미측정


def test_done_items_are_read_from_words_but_not_from_negations():
    ctx = _evidence_ctx()
    assert ia.rule_parse("강제분해 시험 끝냈어", ctx, CATALOG).measurements == {"forced_degradation_done": True}
    assert ia.rule_parse("강제분해는 아직 안 했어", ctx, CATALOG).measurements == {}
    nudge = ia.nudge(ctx)
    assert "근거 결손 3건" in nudge["reply"] and "pH" in nudge["reply"]
