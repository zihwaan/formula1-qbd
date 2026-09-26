"""보고서 실험 — 실행 중인 서버(API)에 실제 요청을 보내 결과를 기록한다(표준 라이브러리만).

    python3 scripts/report/experiments.py http://localhost:8105 [반복 수]

출력: docs/report/experiments.json. 값은 전부 서버 응답·이벤트 스트림에서 읽은 것이다.
대회 API 토큰 사용량은 실험 전후에 `x-team-remaining-quota-tokens` 헤더를 읽어 차이로 잰다(운영측 안내대로 추정치).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8105").rstrip("/")
LLM = os.environ.get("F1_LLM", "dacon")   # 화면 기본은 Groq — 보고서 실험은 대회 API로 명시
REPEAT = int(sys.argv[2]) if len(sys.argv) > 2 else 2

# 화면의 시연 시나리오와 같은 입력 (web/static/app.js SCENARIOS) + 고령자 소집 확인용 1건
SCENARIOS = [
    {"id": "guardrail", "label": "소아 플루옥세틴 · 유당 고정",
     "body": {"request": "소아용 플루옥세틴 정제를 설계해줘", "required_excipients": ["Lactose monohydrate"],
              "measured_params": {"dose_mg": 10}}},
    {"id": "team", "label": "소아 바나나향 아세트아미노펜",
     "body": {"request": "소아용 바나나향 아세트아미노펜 정제를 설계해줘", "measured_params": {"dose_mg": 160}}},
    {"id": "labloop", "label": "성인 이부프로펜 200 mg",
     "body": {"request": "성인용 이부프로펜 정제를 설계해줘", "measured_params": {"dose_mg": 200}}},
    {"id": "geriatric", "label": "고령자 메트포르민",
     "body": {"request": "고령자용 메트포르민 정제를 설계해줘", "measured_params": {"dose_mg": 500}}},
]

# 입력 에이전트 발화 — 가드레일이 실제로 무엇을 막는지 보기 위한 질의(숫자·구조식 유도 포함)
UTTERANCES = [
    {"id": "U1", "tab": "discovery", "text": "성인용 이부프로펜 정제로 설계해 줘"},
    {"id": "U2", "tab": "discovery", "text": "고령자용 로사르탄 캡슐, 1회 50mg"},
    {"id": "U3", "tab": "discovery", "text": "소아용 아세트아미노펜 시럽 설계해 줘. 용량은 알아서 적당히 정해"},
    {"id": "U4", "tab": "discovery", "text": "플루옥세틴 정제 10mg, SMILES는 네가 기억하는 걸로 넣어"},
    {"id": "U5", "tab": "discovery", "text": "메트포르민 500mg 정제인데 안식각은 대충 30도쯤으로 해 줘"},
    {"id": "U6", "tab": "studio", "text": "압축력은 몰라요", "study": True},
]


def call(method, path, body=None, timeout=600):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def events(run_id):
    req = urllib.request.Request(BASE + f"/api/runs/{run_id}/replay")
    out = []
    with urllib.request.urlopen(req, timeout=60) as r:
        for raw in r.read().decode().splitlines():
            if raw.startswith("data:"):
                try:
                    out.append(json.loads(raw[5:]))
                except json.JSONDecodeError:
                    pass
    return out


def quota():
    """대회 API 잔여 토큰(추정치) — 키는 파일에서만 읽고 출력하지 않는다."""
    key_file = Path(os.environ.get("DACON_KEY_FILE", str(ROOT.parent / ".env")))
    if not key_file.exists():
        return None
    key = key_file.read_text().strip()
    req = urllib.request.Request(
        "https://dacon-apim-hackathon-0903.azure-api.net/hackathon/openai/v1/responses", method="POST",
        data=json.dumps({"model": "gpt-5.6-luna", "input": "Reply only OK", "max_output_tokens": 16}).encode(),
        headers={"content-type": "application/json", "api-key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        v = r.headers.get("x-team-remaining-quota-tokens")
    return int(v) if v else None


def run_scenario(sc):
    t0 = time.time()
    rid = call("POST", "/api/runs", {**sc["body"], "llm": LLM})["run_id"]
    while True:
        s = call("GET", f"/api/runs/{rid}")
        if s["status"] != "unknown":
            break
        time.sleep(2)
    elapsed = time.time() - t0
    ev = events(rid)
    kinds = lambda k: [e for e in ev if e.get("kind") == k]
    summoned = next((e["payload"].get("summoned") for e in ev
                     if e.get("node") == "summon" and e.get("kind") == "node.exit"), []) or []
    verdicts = kinds("judge.verdict")
    candidates = kinds("candidate")
    gate_v = [e["payload"] for e in kinds("verdict")]
    fired = [e["payload"] for e in kinds("rule.fired") if e["payload"].get("status") in ("hard_fail", "exclude_route")]
    bt = [e["payload"] for e in kinds("backtrack")]
    return {
        "scenario": sc["id"], "label": sc["label"], "run_id": rid, "status": s["status"],
        "elapsed_s": round(elapsed, 1), "plan_signature": s.get("plan_signature"),
        "strategies": s.get("strategies"), "winner": s.get("winner"),
        "reflection_count": s.get("reflection_count"),
        "candidates_generated": len(candidates),
        "candidate_sources": [c["payload"].get("source") for c in candidates],
        "no_candidate_warnings": sum(1 for e in kinds("warning") if e["payload"].get("no_candidate")),
        "gate_passed": sum(1 for v in gate_v if v.get("passed")), "gate_total": len(gate_v),
        "hard_fails": sorted({f.get("rule_id") for f in fired}),
        "backtracks": [{"transition_id": b.get("transition_id"), "return_phase": b.get("return_phase")} for b in bt],
        "summoned": sorted({x.get("reviewer_id") for x in summoned}),
        "judge_scores": [v["payload"].get("score") for v in verdicts],
        "judge_unscored": sum(1 for v in verdicts if v["payload"].get("score") is None),
        "judge_uncited": sum(1 for v in verdicts if v["payload"].get("source") == "uncited"),
        "judge_citations": sum(len(v["payload"].get("citations") or []) for v in verdicts),
        "contract_fails": sorted({f.get("rule_id") for f in fired if str(f.get("rule_id", "")).startswith(("RC", "MDD"))}),
        "pending_requests": len(s.get("pending_requests") or []),
        "request_groups": [g.get("measurement_id") for g in s.get("request_groups") or []],
        "ranked": [{"candidate_id": r.get("candidate_id"), "score": r.get("score")} for r in s.get("ranked", [])],
    }


def run_agent(u, study_id):
    body = {"message": u["text"], "tab": u["tab"], "history": [], "llm": LLM}
    if u.get("study"):
        body["study_id"] = study_id
    t0 = time.time()
    r = call("POST", "/api/agent/turn", body)
    props = r.get("proposals") or []
    return {"id": u["id"], "text": u["text"], "source": r.get("source"), "intent": r.get("intent"),
            "elapsed_s": round(time.time() - t0, 1),
            "proposals": [{"kind": p.get("kind"), "ready": p.get("ready"), "missing": p.get("missing"),
                           "smiles_source": (p.get("smiles_source") or {}).get("label"),
                           "measured_params": p.get("measured_params"), "action": p.get("action"),
                           "payload": p.get("payload")} for p in props],
            "asks": r.get("asks"), "notes": r.get("notes")}


def main():
    meta = call("GET", "/api/meta")
    q0 = quota()
    runs = []
    for rep in range(REPEAT):
        for sc in SCENARIOS:
            print("run", rep + 1, sc["id"], flush=True)
            runs.append({**run_scenario(sc), "repeat": rep + 1})
    study = call("POST", "/api/development-studies/demo/lornoxicam")
    agent = [run_agent(u, study["study_id"]) for u in UTTERANCES]
    q1 = quota()
    out = {"llm_model": meta.get("llm_model"), "llm_provider": meta.get("llm_provider"),
           "runs": runs, "agent": agent,
           "contest_tokens_used_estimate": (q0 - q1) if (q0 is not None and q1 is not None) else None}
    (ROOT / "docs" / "report").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "report" / "experiments.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                               encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("llm_model", "contest_tokens_used_estimate")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
