"""시연 쿼리 카드 3장을 실제 서버(API)로 끝까지 돌려 정답지와 나란히 기록한다.

    python3 scripts/report/demo_cards.py http://localhost:8106 dacon 2

출력: docs/report/demo_cards.json — 모든 값은 서버 응답·이벤트 스트림에서 읽는다(정답지는 카드에 적힌 출처의 값).
카드 1은 후보 → 연구자가 고른 후보로 개발 착수 → 2단계 study를 열고 프로토타입 실행 · QTPP 초안까지 간다.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devfix_check as dc  # noqa: E402 — 같은 호출 도구(call/events/run)를 쓴다

ROOT = dc.ROOT
LLM = dc.LLM
REPEAT = dc.REPEAT
sys.path.insert(0, str(ROOT))

CARD1 = dc.CASES["T1"]
CARD1_POOR = {**CARD1, "measured_params": {**CARD1["measured_params"], "angle_of_repose": 48}}
CARD2 = dc.CASES["T2"]
CARD2_FREE = dc.CASES["T3"]
CARD3 = dc.CASES["T4"]
LEAK = re.compile(r"ivacaftor|kalydeco|이바카프토|칼리데코", re.I)
MG_ST = re.compile(r"magnesium stearate|스테아르산\s*마그네슘", re.I)

ANSWER = {
    "card1": {"source": "Almotairi N et al. Pharmaceuticals 2022;15:1463 (doi:10.3390/ph15121463)",
              "optimum": {"F_filler_ratio": 3.0, "F_blend_time": 11.0, "F_disintegrant_pct": 6.23},
              "observed": {"dispersion_s": 4.4, "friability_pct": 0.19, "DE_pct": 80.64},
              "composition_mg": {"MCC": 166.06, "Mannitol": 55.35, "Crospovidone": 15.58, "Lornoxicam": 8, "SLS": 5}},
    "card2": {"source": "NORVASC US prescribing information (DailyMed) · Abdoh A et al. Pharm Dev Technol 2004;9(1):15-24",
              "label_excipients": ["Microcrystalline cellulose", "Dibasic calcium phosphate anhydrous",
                                   "Sodium starch glycolate", "Magnesium stearate"]},
    "card3": {"source": "Biomedicines 2023;11(5):1281 · PMC10608006",
              "product": "80 % 약물함량 HPMCAS 분무건조 분산체(SDD)"},
}


def act(sid, action, payload, version):
    return dc.call("POST", f"/api/stage2/studies/{sid}/actions/{action}", {"payload": payload},
                   {"Idempotency-Key": f"{sid}-{action}-{version}", "Expected-State-Version": str(version), "X-F1-LLM": LLM})


def stage2_walk(rid, cid):
    """연구자가 '이 후보로 개발 착수'를 누른 뒤의 2단계 — 프로토타입 실행 → QTPP·CQA LLM 초안까지(승인은 연구자 몫이라 초안에서 멈춘다)."""
    view = dc.call("POST", "/api/stage2/studies", {"source": "candidate", "run_id": rid, "candidate_id": cid},
                   {"Idempotency-Key": f"card1-{rid}-{cid}", "X-F1-LLM": LLM})
    sid = view["study"]["study_id"]
    rec = {"study_id": sid, "prototype_rows": len(view["study"]["steps"]["prototype"]["data"]["ingredients"]), "steps": []}
    try:
        view = act(sid, "run", {}, view["study"]["state_version"])
        rec["steps"].append({"action": "run", "status": view["current"]})
        view = act(sid, "draft", {}, view["study"]["state_version"])
        q = view["study"]["steps"]["qtpp"]
        rec["steps"].append({"action": "draft", "step": "qtpp", "rows": len((q["data"] or {}).get("items") or []), "source": q["source"],
                             "checks": [c["code"] for c in q["checks"]]})
    except Exception as exc:  # noqa: BLE001 — 멈춘 지점을 그대로 기록한다
        body = getattr(exc, "read", lambda: b"")().decode(errors="replace")[:400]
        rec["stopped_at"] = {"error": body or str(exc)}
    rec["final_status"] = view.get("current")
    return rec, view


def card1(rep, case, tag):
    rec = dc.check("T1", case, rep)
    rid = rec["run_id"]
    passed = [c for c in rec["candidates"] if c["passed"]]
    rec["card"] = tag
    rec["mg_stearate_candidates"] = sum(1 for c in rec["candidates"] if any(MG_ST.search(n) for n in c["ingredients"]))
    rec["inc014_fired"] = "INC014" in rec["fired_any"]
    rec["rte008_fired"] = "RTE008" in rec["fired_any"]
    rec["plan_signature"] = dc.call("GET", f"/api/runs/{rid}").get("plan_signature")
    if tag != "card1":
        return rec
    s = dc.call("GET", f"/api/runs/{rid}")
    before = {r["trigger_id"] for r in s.get("pending_requests") or []}
    turn = dc.call("POST", "/api/agent/turn", {"message": "DSC 측정 결과: Tm 225 도.", "tab": "discovery",
                                                "run_id": rid, "llm": LLM})
    card = next((p for p in turn.get("proposals", []) if p["kind"] == "submit_measurements"), None)
    rec["tm_submit"] = {"source": turn.get("source"), "measurements": card and card["measurements"]}
    if card:
        out = dc.call("POST", f"/api/runs/{rid}/measurements",
                      {"measurements": card["measurements"], "grade": "literature",
                       "source": "agent"})
        after = {r["trigger_id"] for r in out.get("pending_requests", [])}
        rec["tm_submit"]["closed"] = sorted(before - after)
        rec["tm_submit"]["regenerated"] = out.get("regenerated")
    s = dc.call("GET", f"/api/runs/{rid}")   # 제출로 재생성됐으면 후보가 바뀐다 — 지금의 1위를 고른다
    rec["plan_signature_after_tm"] = s.get("plan_signature")
    rec["status_after_tm"] = s.get("status")
    ranked = [r.get("candidate_id") for r in s.get("ranked") or []]
    pick = s.get("winner") or (ranked[0] if ranked else None)
    if pick:
        # 연구자가 카드에서 고른 후보 = 순위 1위 통과 후보(자동 진입이 아니라 이 스크립트가 버튼을 누른다)
        rec["picked"] = pick
        rec["stage2"], _ = stage2_walk(rid, pick)
    return rec


def card2(rep, case, name):
    rec = dc.check(name, case, rep)
    ev = dc.events(rec["run_id"])
    rec["card"] = "card2" if name == "T2" else "card2_free"
    inf = next((e["payload"] for e in ev if e.get("node") == "infeasible" and e.get("kind") == "warning"), None)
    rec["infeasible"] = inf and {"reason": inf.get("reason"),
                                 "blocking": sorted({b.get("rule_id") for b in inf.get("blocking") or []}),
                                 "suggestions": sorted({b.get("suggestion") for b in inf.get("blocking") or []
                                                        if b.get("suggestion")})[:3]}
    rec["api_amounts"] = [c["api"] for c in rec["candidates"] if c["passed"]]
    rec["lactose_in_passed"] = any("lactose" in n.lower() for c in rec["candidates"] if c["passed"]
                                   for n in c["ingredients"])
    return rec


def card3(rep):
    rec = dc.check("T4", CARD3, rep)
    rid = rec["run_id"]
    s = dc.call("GET", f"/api/runs/{rid}")
    ev = dc.events(rid)
    rec["card"] = "card3"
    rec["strategies_after"] = s.get("strategies")
    rec["plan_signature_after"] = s.get("plan_signature")
    rec["plan_signature_before"] = next((e["payload"].get("plan_signature") for e in ev
                                         if e.get("node") == "plan" and e["payload"].get("plan_signature")), None)
    rec["asd_process_signal"] = [p for p in (rec.get("phase_signals_after") or [])
                                 if str(p.get("rule_id", "")).startswith("G4B")]
    text = json.dumps(ev, ensure_ascii=False) + json.dumps(s, ensure_ascii=False)
    rec["name_leaks"] = sorted({m.group(0).lower() for m in LEAK.finditer(text)})
    rec["leak_sources"] = sorted({e.get("kind") for e in ev if LEAK.search(json.dumps(e, ensure_ascii=False))})
    rec["solubility_submitted"] = (rec.get("agent") or {}).get("measurements")
    return rec


def main():
    """네 번째 인자로 다시 돌릴 카드를 고르면(예: card3) 나머지는 기존 결과를 유지한다."""
    only = set(sys.argv[4].split(",")) if len(sys.argv) > 4 else None
    path = ROOT / "docs" / "report" / "demo_cards.json"
    prev = json.loads(path.read_text(encoding="utf-8")) if only and path.exists() else {"results": [], "llm_calls": {}}
    want = lambda tag: only is None or tag in only
    meta = dc.call("GET", "/api/meta")
    results = [r for r in prev["results"] if only and r["card"] not in only]
    for r in range(1, REPEAT + 1):
        if want("card1"):
            results.append(card1(r, CARD1, "card1"))
        if want("card2"):
            results.append(card2(r, CARD2, "T2"))
        if want("card2_free"):
            results.append(card2(r, CARD2_FREE, "T3"))
        if want("card3"):
            results.append(card3(r))
    if want("card1_flow48"):
        results.append(card1(1, CARD1_POOR, "card1_flow48"))
    order = ["card1", "card1_flow48", "card2", "card2_free", "card3"]
    results.sort(key=lambda r: (order.index(r["card"]), r["repeat"]))
    calls = dict(prev.get("llm_calls") or {})
    for k, v in (dc.call("GET", "/api/meta").get("llm_calls") or {}).items():   # 새로 띄운 서버 기준 누적
        calls[k] = calls.get(k, 0) + v
    out = {"llm": LLM, "llm_label": next((o["label"] for o in meta.get("llm_options", []) if o["id"] == LLM), LLM),
           "llm_calls": calls, "answer_key": ANSWER, "results": results}
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                              encoding="utf-8")
    print("llm_calls", out["llm_calls"])


if __name__ == "__main__":
    main()
