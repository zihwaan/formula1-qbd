"""상황별 심사관 소집 — 요청 6건을 실제 그래프(대회 API)로 한 번씩 돌려, 누가 소집되었는지와 그 근거(조건식이 본 신호)를 기록한다.

보고서 표 5(그림 7의 명단 · 조건과 짝). 심사관은 조건식이 참일 때만 생성되고(REV003 공정 실현성은 `always`), 심사 전에
"제약 불가능"으로 끝나는 실행은 같은 조건식으로 계산한 소집 예정 명단(planned_judges)을 기록한다 — 통과 후보가 없으면
심사할 대상이 없을 뿐 소집 조건은 그대로다.

요청은 심사관 7명이 모두 한 번 이상 조건에 걸리도록 고른 상황이다(입력값은 시연 쿼리 카드와 보고서 실험의 값 그대로):
  성인 일반 · 소아 츄어블정(백당 고정 → 소아 규칙 PED028 검토 지적) · 고령자 염 형태 · 룰북 밖 부형제 고정(부형제 마스터에 없는 성분 → 문헌 조사) ·
  고융점 난용성 신약(실측 Tm · 용해도 → ASD 후보) · 금기 성분 고정(제약 불가능).

    docker run --rm --env-file <DACON_API_KEY만 든 파일> -e FORMULA1_LLM_PROVIDER=dacon -e PYTHONPATH=/app -v "$PWD":/app -w /app \
        formula1:test python scripts/report/jury_scenarios.py [상황 id,…]   (일부만 돌리면 기존 결과의 그 상황만 바꾼다)
출력: docs/report/jury_scenarios.json
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from formula.agents import client as C                 # noqa: E402
from formula.checkers.applies_when import spec_context  # noqa: E402
from formula.checkers.registry import RulebookRegistry  # noqa: E402
from formula.orchestrator.graph import summon_scope     # noqa: E402
from formula.orchestrator.runner import Run             # noqa: E402

_argv, sys.argv = sys.argv, sys.argv[:1]                # devfix_check는 import 때 argv를 읽는다
import devfix_check as DC                              # noqa: E402 — 시연 쿼리 카드 입력
sys.argv = _argv

LLM = "dacon"
C.DACON_TIMEOUT = 600.0
REG = RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)
OUT = ROOT / "docs" / "report" / "jury_scenarios.json"
SIGNALS = ("target_population", "bcs_class", "enabling_candidates_present", "particle_size_candidates_present",
           "asd_candidates_present", "coverage_gap_present", "novel_combination_not_in_rulebook",
           "regulatory_narrative_needed", "solid_form_zone", "salt_stability_watch")

SCENARIOS: List[Dict[str, Any]] = [
    {"id": "adult", "label": "성인 일반 정제", "request": "성인용 메트포르민 정제를 설계해줘", "measured_params": {"dose_mg": 500}},
    {"id": "pediatric", "label": "소아 츄어블정 · 백당 고정", "request": "소아용 아세트아미노펜 츄어블정을 설계해줘. 백당(수크로스)은 반드시 넣어줘",
     "required_excipients": ["Sucrose"], "measured_params": {"dose_mg": 160}},
    {"id": "geriatric", "label": "고령자 · 염 형태(베실산염)", **{k: DC.CASES["T3"][k] for k in ("request", "smiles", "measured_params", "dose_basis")}},
    {"id": "novel", "label": "룰북 밖 부형제 고정", "request": "성인용 이부프로펜 정제를 설계해줘. 마그네슘 알루미노메타실리케이트(Neusilin US2)는 반드시 넣어줘",
     "required_excipients": ["Magnesium aluminometasilicate"], "measured_params": {"dose_mg": 200}},
    {"id": "asd", "label": "고융점 난용성 신약(실측 Tm · 용해도)", "request": DC.CASES["T4"]["request"], "smiles": DC.CASES["T4"]["smiles"],
     "measured_params": {**DC.CASES["T4"]["measured_params"], "tm_c": 317, "solubility_mg_per_ml": 0.00005}},
    {"id": "infeasible", "label": "금기 성분 고정(제약 불가능)", "request": "소아용 플루옥세틴 정제를 설계해줘",
     "required_excipients": ["Lactose monohydrate"], "measured_params": {"dose_mg": 10}},
]


async def _consume(run: Run) -> List[Any]:
    return [ev async for ev in run.stream()]


def _kind(e) -> str:
    return getattr(e.kind, "value", e.kind)


def one(sc: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.time()
    run = Run(ROOT, sc["request"], smiles=sc.get("smiles"), required_excipients=sc.get("required_excipients") or [],
              measured_params=sc.get("measured_params") or {}, llm=LLM, dose_basis=sc.get("dose_basis") or "free_base")
    evs = asyncio.run(_consume(run))
    f = run.final
    spec = f.get("spec")
    summon = [e.payload for e in evs if e.node == "summon" and _kind(e) == "node.exit" and "summoned" in e.payload]
    infeasible = [e.payload for e in evs if e.node == "infeasible" and _kind(e) == "warning"]
    verdicts = [e.payload for e in evs if _kind(e) == "judge.verdict"]
    results = f.get("results") or []
    pool = [r for r in results if r.get("passed")] or results
    scope = spec_context(spec, summon_scope(REG, f, pool))
    summoned = (summon[-1]["summoned"] if summon else [])
    planned = (infeasible[-1].get("planned_judges") or []) if infeasible else []
    return {
        **{k: sc.get(k) for k in ("id", "label", "request", "required_excipients", "measured_params")},
        "status": f.get("status"), "strategies": [p["strategy"] for p in f.get("planned") or []],
        "summoned": [s["reviewer_id"] for s in summoned], "planned": [s["reviewer_id"] for s in planned],
        "signals": {k: scope.get(k) for k in SIGNALS},
        "soft_flags": sorted({f"{v.rulebook_id}/{v.rule_id}" for r in pool for v in r.get("verdicts") or []
                              if getattr(v.status, "value", v.status) == "soft_flag" and (getattr(v, "layer", "") or "").lower() == "regulatory"}),
        "scores": {s["reviewer_id"]: [p.get("score") for p in verdicts if p.get("reviewer_id") == s["reviewer_id"]] for s in summoned},
        "seconds": round(time.time() - t0, 1),
    }


def main() -> None:
    only = [x for x in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if x]
    prev = {r["id"]: r for r in (json.loads(OUT.read_text(encoding="utf-8"))["scenarios"] if only and OUT.exists() else [])}
    rows = []
    for sc in SCENARIOS:
        if only and sc["id"] not in only:
            if sc["id"] in prev:
                rows.append(prev[sc["id"]])
            continue
        r = one(sc)
        print(f"{r['id']:<11} {r['status']:<16} summoned={r['summoned']} planned={r['planned']} {r['seconds']}s", flush=True)
        rows.append(r)
    OUT.write_text(json.dumps({"llm": LLM, "model": C.DACON_MODEL, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "scenarios": rows},
                              ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
