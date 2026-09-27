"""2단계 LLM 초안을 논문과 나란히 — CBD 논문 프로토타입으로 study를 열고 2~8단계를 LLM 초안 그대로 승인해 가며 논문 표와 대조한다.

    python3 scripts/report/stage2_llm.py http://localhost:8104 dacon     → docs/report/stage2_llm.json (보고서 7.2절)

초안은 고치지 않는다(연구자 편집 없음). 승인이 막히면 그 단계에서 멈추고 막은 검사 코드를 기록한다.
대조는 이름이 같은 변수 · CQA 칸끼리만 한다(LLM이 다른 이름을 쓰면 그 칸은 비교 밖으로 센다).
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8104"
LLM = sys.argv[2] if len(sys.argv) > 2 else "groq"


def call(path, body=None, ver=None):
    h = {"Content-Type": "application/json", "X-F1-LLM": LLM, "Actor-ID": "report"}
    if ver is not None:
        h["Expected-State-Version"] = str(ver)
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=h,
                                 method="POST" if body is not None else "GET")
    try:
        return json.load(urllib.request.urlopen(req, timeout=900))
    except urllib.error.HTTPError as e:
        return {"_err": e.code, "detail": e.read().decode()[:400]}


def cells(m):
    return {(c, v["name"]): m["levels"][i][j] for i, c in enumerate(m["cqas"]) for j, v in enumerate(m["variables"])}


def main():
    v = call("/api/stage2/studies", {"source": "cbd_paper"})
    sid = v["study"]["study_id"]
    ref = v["reference"]
    v = call(f"/api/stage2/studies/{sid}/actions/run", {"payload": {}}, v["study"]["state_version"])
    steps, stopped = [], None
    for step in ["qtpp", "cqa", "rm_just", "rm_matrix", "fp_just", "fp_matrix", "recommend"]:
        t = time.time()
        if step not in ("rm_matrix", "fp_matrix"):
            d = call(f"/api/stage2/studies/{sid}/actions/draft", {"payload": {}}, v["study"]["state_version"])
            if "_err" in d:
                stopped = {"step": step, "error": d}
                break
            v = d
        s = v["study"]["steps"][step]
        rec = {"step": step, "seconds": round(time.time() - t, 1), "provider": (s.get("llm") or {}).get("provider"),
               "checks": [{"level": c["level"], "code": c["code"]} for c in s["checks"]]}
        if step == "qtpp":
            rec.update(items=len(s["data"]["items"]), paper_items=len(ref["qtpp"]["items"]))
        if step == "cqa":
            mine = [c["short"] for c in s["data"]["items"] if c["in_risk_assessment"]]
            paper = [c["short"] for c in ref["cqa"]["items"] if c["in_risk_assessment"]]
            rec.update(items=len(s["data"]["items"]), in_risk=mine, paper_in_risk=paper,
                       only_llm=[c for c in mine if c not in paper], only_paper=[c for c in paper if c not in mine])
        if step in ("rm_just", "fp_just"):
            rec.update(variables=[x["name"] for x in s["data"]["variables"]], rows=len(s["data"]["items"]),
                       paper_variables=[x["name"] for x in ref[step]["variables"]], paper_rows=len(ref[step]["items"]))
        if step in ("rm_matrix", "fp_matrix"):
            a, b = cells(s["data"]), cells(ref[step])
            common = [k for k in a if k in b]
            same = [k for k in common if a[k] == b[k]]
            rec.update(cells=len(a), common=len(common), same=len(same),
                       differ=[{"cqa": k[0], "variable": k[1], "llm": a[k], "paper": b[k]} for k in common if a[k] != b[k]])
        if step == "recommend":
            rec.update(recommended=[r["variable"] for r in s["data"]["recommended"]], reasons={r["variable"]: r["reason"] for r in s["data"]["recommended"]},
                       note=s["data"].get("note"), rule_rank=s["data"]["rule_rank"], paper=ref["recommend"]["selected"])
        a = call(f"/api/stage2/studies/{sid}/actions/approve", {"payload": {}}, v["study"]["state_version"])
        rec["blocked"] = (a.get("action_result") or {}).get("blocked") or []
        steps.append(rec)
        v = a
        if rec["blocked"]:
            stopped = {"step": step, "blocked": rec["blocked"]}
            break
        print(step, rec["seconds"], "s", rec.get("provider"), rec["blocked"] or "승인", flush=True)
    meta = call("/api/meta")
    out = {"llm": LLM, "llm_calls": meta.get("llm_calls"), "study_id": sid, "steps": steps, "stopped": stopped,
           "at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    (ROOT / "docs" / "report" / "stage2_llm.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("llm", "llm_calls", "stopped")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
