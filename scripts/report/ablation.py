"""어블레이션 — 에이전트 시스템이 무엇을 더하는가. 같은 대회 모델(gpt-5.6-sol)로 세 조건을 비교한다.

1단계(후보 설계) — 7개 요청(발표 시연 3 + 보고서 실험 4)
  P  순수 LLM      : 요청·구조식·실측값·고정 성분만 주고 처방 1건(JSON)을 받는다. 룰북·근거·검증 없음.
  G  검증 계층 제거 : 시스템의 계획(페이즈 게이트·전략 선택)과 설계 에이전트(RAG 근거)는 쓰되, 룰북 게이트·요청 계약·
                     반성·불가능 판정 없이 생성된 후보를 그대로 낸다.
  F  전체 시스템    : 실제 Run(그래프 전체). 연구자에게 '통과'로 제시되는 후보만 센다.
  채점(모두 결정론 — 정답이 하나로 정해지는 것만):
    · 금기 위반   : 출처가 붙은 룰북 HARD_FAIL(요청 계약 제외) — 조건과 무관하게 같은 규칙표로 사후 채점
    · 계약 위반   : 요청한 API가 정확히 1개 · 유리염기 용량 ±0.5 % · 고정 성분 포함 · FDA 라벨 1일 최대 용량
    · 불가능 인식 : 고정 성분 자체가 금기인 2건(플루옥세틴·암로디핀 + 유당)에서 위반 처방을 내지 않았는가
    · 인용 실재   : 제시한 DOI·PMID가 Crossref/NCBI에 실제로 있는가
    · 재현성      : 같은 입력 반복 시 결정(제시 여부 · 걸리는 규칙 · 계획)이 같은가
    · 비용        : 시간 · LLM 호출(프로바이더별). 토큰(잔여 한도 헤더 차이)도 적지만 헤더가 요청마다 크게 흔들려
                   보고서에는 쓰지 않는다
2단계(Design Space) — 순수 LLM에게 원자료로 직접 계산·판단을 시키고 시스템(결정론 toolkit)과 비교
  S-A 회귀·ANOVA 계산 : CBD Table 9 → 경도 선형 · 붕해시간 2차 coded 계수와 p값. 정답 = 논문 Table 10·11(toolkit이 재현)
  S-B Design Space   : 로르녹시캄 Table 3 + 목표 → 운전 범위·설정점. 채점 = 게이트 통과 모형으로 목표 충족 비율
  S-C 위험평가 표    : CBD 프로토타입 → 행렬과 근거 표를 한 번에. 채점 = 두 표가 서로 맞는가(내부 일관성)

뺀 지표(정답이 없거나 억지): 처방 '품질' 점수(LLM 채점), 논문 조성·위험 등급과의 일치율(논문은 참고 자료), 심사관 점수 자체, 토큰.
키 파일에는 DACON_API_KEY만 넣는다 — Groq 폴백이 없어야 세 조건이 같은 모델이다(실패는 실패로 기록).

    docker run --rm --env-file <키 파일> -e FORMULA1_LLM_PROVIDER=dacon -e PYTHONPATH=/app -v "$PWD":/app -w /app formula1:test python scripts/report/ablation.py 2 [all|케이스,…] [s1,s2]
    (나눠 돌리면 docs/report/ablation.<부분>.json → python scripts/report/ablation.py merge <파일>… 로 합친다)
    (규칙이 바뀌면 python scripts/report/ablation.py regrade docs/report/ablation.json — 저장된 처방을 LLM 없이 다시 채점)
출력: docs/report/ablation.json
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from formula.agents import citations as CITE          # noqa: E402
from formula.agents import client as C                # noqa: E402
from formula.agents import generator as GEN           # noqa: E402
from formula.checkers.registry import RulebookRegistry  # noqa: E402
from formula.contracts import Ingredient, Recipe, VerdictStatus  # noqa: E402
from formula.orchestrator.runner import Run           # noqa: E402
from formula.stage2 import doe as T                   # noqa: E402
from formula.stage2 import paper_designs as PD        # noqa: E402
from formula.stage2 import reference as REF           # noqa: E402
from formula.stage2 import space as SP                # noqa: E402
_argv, sys.argv = sys.argv, sys.argv[:1]               # devfix_check는 import 때 argv를 읽는다
import devfix_check as DC                             # noqa: E402 — 시연 쿼리 카드 입력(CASES)
sys.argv = _argv

REPEAT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 2
ONLY = [c for c in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if c and c != "all"]      # 케이스 id 일부만(시험용)
PARTS = (sys.argv[3] if len(sys.argv) > 3 else "s1,s2").split(",")
OUT = ROOT / "docs" / "report" / ("ablation.json" if not ONLY and sorted(PARTS) == ["s1", "s2"]
                                  else f"ablation.{'_'.join(PARTS)}{'.' + '_'.join(ONLY) if ONLY else ''}.json")   # 나눠 돌린 결과 — merge로 합친다
P_REPEAT = REPEAT + 1                                  # 순수 LLM은 호출이 싸다 — 재현성을 보려고 한 번 더
LLM = "dacon"
# 같은 모델끼리 비교 — 키 파일에 Groq 키를 넣지 않아 폴백이 없고(실패는 실패로 기록), 긴 계산도 끊기지 않게 타임아웃을 늘린다(세 조건 공통).
C.DACON_TIMEOUT = 600.0
CONTRACT = ("request_contract", "max_daily_dose")
REG = RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)

CASES = [
    {"id": "lornoxicam", "label": "로르녹시캄 8 mg 분산정(시연 ①)", **DC.CASES["T1"], "expect_infeasible": False},
    {"id": "amlodipine_lactose", "label": "고령자 암로디핀 2.5 mg + 유당 고정(시연 ②)", **DC.CASES["T2"], "expect_infeasible": True},
    {"id": "vx770", "label": "VX-770 150 mg(시연 ③)", **DC.CASES["T4"], "expect_infeasible": False},
    {"id": "fluoxetine_lactose", "label": "소아 플루옥세틴 + 유당 고정", "request": "소아용 플루옥세틴 정제를 설계해줘",
     "required_excipients": ["Lactose monohydrate"], "measured_params": {"dose_mg": 10}, "expect_infeasible": True},
    {"id": "acetaminophen", "label": "소아 바나나향 아세트아미노펜", "request": "소아용 바나나향 아세트아미노펜 정제를 설계해줘",
     "measured_params": {"dose_mg": 160}, "expect_infeasible": False},
    {"id": "ibuprofen", "label": "성인 이부프로펜 200 mg", "request": "성인용 이부프로펜 정제를 설계해줘",
     "measured_params": {"dose_mg": 200}, "expect_infeasible": False},
    {"id": "metformin", "label": "고령자 메트포르민", "request": "고령자용 메트포르민 정제를 설계해줘",
     "measured_params": {"dose_mg": 500}, "expect_infeasible": False},
]


def quota() -> Optional[int]:
    """대회 API 잔여 토큰(운영측 헤더, 추정치). 키는 환경변수에서만 읽고 출력하지 않는다."""
    try:
        req = urllib.request.Request(f"{C.DACON_BASE_URL}/responses", method="POST",
                                     data=json.dumps({"model": "gpt-5.6-luna", "input": "Reply only OK", "max_output_tokens": 16}).encode(),
                                     headers={"content-type": "application/json", "api-key": C._dacon_key()})
        with urllib.request.urlopen(req, timeout=60) as r:
            v = r.headers.get("x-team-remaining-quota-tokens")
        return int(v) if v else None
    except Exception:   # noqa: BLE001 — 비용 측정은 보조
        return None


def calls() -> int:
    return sum(C.CALLS.values())


def by_provider(before: Dict[str, int]) -> Dict[str, int]:
    return {k: v - before.get(k, 0) for k, v in C.CALLS.items() if v - before.get(k, 0)}


# ── 채점(결정론) ─────────────────────────────────────────────────────────
def grade(spec, recipe: Recipe, derived: Dict[str, Any]) -> Dict[str, Any]:
    g = REG.run(spec, recipe, short_circuit=False, derived=dict(derived or {}))
    hard = sorted({v.rule_id for v in g.verdicts if v.status == VerdictStatus.HARD_FAIL and v.rulebook_id not in CONTRACT})
    contract = sorted({v.rule_id for v in g.verdicts if v.status == VerdictStatus.HARD_FAIL and v.rulebook_id in CONTRACT})
    esc = sorted({v.rule_id for v in g.verdicts if v.status == VerdictStatus.ESCALATE})
    why = {}
    for v in g.verdicts:
        if v.status == VerdictStatus.HARD_FAIL and v.rule_id not in why:
            why[v.rule_id] = {"rulebook": v.rulebook_id, "reason": (v.reason or "")[:220]}
    return {"hard_fail": hard, "contract_fail": contract, "escalate": esc, "unsafe": bool(hard), "contract": bool(contract), "why": why,
            "ingredients": [f"{i.name} {i.amount_mg}" for i in recipe.ingredients],
            "recipe": recipe.model_dump(mode="json", include={"api_name", "candidate_id", "strategy", "process", "ingredients"})}


def _spec_json(spec) -> Dict[str, Any]:
    d = spec.model_dump(mode="json")
    if d.get("api_profile"):
        d["api_profile"].pop("svg", None)              # 그림은 채점에 안 쓴다
    return d


def regrade(path: str) -> None:
    """저장된 처방을 지금의 룰북으로 다시 채점한다(LLM 호출 없음) — 규칙이 바뀐 뒤 같은 출력으로 비교할 때."""
    from formula.contracts import FormulationSpec
    p = Path(path)
    d = json.loads(p.read_text(encoding="utf-8"))
    n = 0
    for c in d["stage1"]["cases"]:
        gi = c["grading_input"]
        spec = FormulationSpec.model_validate(gi["spec"])
        for k in ("F", "G", "P"):
            for r in c[k]:
                for o in r["outputs"]:
                    o.update(grade(spec, Recipe.model_validate(o["recipe"]), gi["derived"]))
                    n += 1
        c["reproducible"] = {
            "F": len({decision(r["outputs"], [r["status"], r["plan_signature"]]) for r in c["F"]}) == 1,
            "G": len({decision(r["outputs"]) for r in c["G"]}) == 1,
            "P": len({decision(r["outputs"], r.get("feasible")) for r in c["P"]}) == 1}
    d["regraded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("regraded", n, "outputs →", p)


def cite_check(refs: List[str]) -> Dict[str, Any]:
    ok, rejected = CITE.verify(refs, [])
    return {"given": len(refs), "verified": len(ok), "rejected": rejected[:8]}


# ── P: 순수 LLM ──────────────────────────────────────────────────────────
class PureIngredient(BaseModel):
    name: str
    role: str = Field(description="api / diluent / binder / disintegrant / superdisintegrant / lubricant / glidant / surfactant_wetting / "
                                  "film_coating / sweetener / flavoring / colorant / polymer")
    amount_mg: float


class PureDesign(BaseModel):
    feasible: bool = Field(description="이 요청 조건으로 안전한 처방을 만들 수 있으면 true, 없으면 false")
    reason: str = ""
    process: str = Field("", description="direct_compression / dry_granulation / wet_granulation / spray_drying / hot_melt_extrusion 중 하나")
    ingredients: List[PureIngredient] = Field(default_factory=list, description="feasible이면 API 포함 전 성분과 1정당 mg")
    rationale: str = ""
    references: List[str] = Field(default_factory=list, description="근거 문헌 — DOI 또는 PMID만")
    data_needed: List[str] = Field(default_factory=list, description="개발 전에 필요한 실험")


PURE_SYSTEM = """당신은 경구 고형제 처방을 설계하는 제제 연구원이다. 요청에 맞는 처방 1건을 설계하라.
- 이 조건으로 안전한 처방을 만들 수 없다고 판단하면 feasible=false와 이유를 적는다.
- 근거 문헌은 DOI 또는 PMID로 적는다.
- 개발 전에 필요한 실험이 있으면 data_needed에 적는다."""


def pure_prompt(case, smiles: str) -> str:
    mp = ", ".join(f"{k}={v}" for k, v in (case.get("measured_params") or {}).items())
    pin = ", ".join(case.get("required_excipients") or []) or "없음"
    return (f"요청: {case['request']}\n구조식(SMILES): {smiles or '없음'}\n실측값: {mp or '없음'}"
            f"\n반드시 포함할 부형제: {pin}\n용량 기준: {case.get('dose_basis') or 'free_base'}(유리염기)")


def pure(case, spec, derived, smiles) -> Dict[str, Any]:
    t0, c0, b0 = time.time(), calls(), dict(C.CALLS)
    with C.use_llm(LLM):
        d = C.parse_structured(PureDesign, PURE_SYSTEM, pure_prompt(case, smiles))
    rec: Dict[str, Any] = {"feasible": d.feasible, "reason": d.reason[:300], "process": d.process, "data_needed": d.data_needed[:8],
                           "seconds": round(time.time() - t0, 1), "llm_calls": calls() - c0, "providers": by_provider(b0),
                           "citations": cite_check(d.references)}
    if d.feasible and d.ingredients:
        tot = sum(i.amount_mg for i in d.ingredients) or 1.0
        recipe = Recipe(api_name=spec.api_name, candidate_id="pure", strategy="PURE_LLM", process=d.process or None,
                        ingredients=[Ingredient(name=i.name, role=i.role, amount_mg=i.amount_mg, percent=round(100 * i.amount_mg / tot, 3))
                                     for i in d.ingredients], rationale=d.rationale)
        rec["outputs"] = [grade(spec, recipe, derived)]
    else:
        rec["outputs"] = []
    return rec


# ── G: 검증 계층 제거 ─────────────────────────────────────────────────────
def unverified(case_id, spec, derived, strategies) -> Dict[str, Any]:
    t0, c0, b0 = time.time(), calls(), dict(C.CALLS)
    outs = []
    with C.use_llm(LLM):
        for s in strategies:
            r = GEN.generate(spec, s, ROOT, f"g-{case_id}-{s}")
            if r is not None:
                outs.append({"strategy": s, **grade(spec, r, derived)})
    return {"outputs": outs, "strategies": list(strategies), "seconds": round(time.time() - t0, 1), "llm_calls": calls() - c0,
            "providers": by_provider(b0)}


# ── F: 전체 시스템 ────────────────────────────────────────────────────────
async def _consume(run: Run) -> List[Any]:
    return [ev async for ev in run.stream()]


def full(case):
    t0, c0, b0 = time.time(), calls(), dict(C.CALLS)
    run = Run(ROOT, case["request"], smiles=case.get("smiles"), required_excipients=case.get("required_excipients") or [],
              measured_params=case.get("measured_params") or {}, llm=LLM, dose_basis=case.get("dose_basis") or "free_base")
    evs = asyncio.run(_consume(run))
    f = run.final
    spec = f.get("spec")
    derived = f.get("phase_derived") or {}
    passed = [r for r in f.get("results") or [] if r.get("passed")]
    jv = [e.payload for e in evs if getattr(e.kind, "value", e.kind) == "judge.verdict"]
    rec = {"status": f.get("status"), "plan_signature": f.get("plan_signature"), "strategies": [p["strategy"] for p in f.get("planned") or []],
           "outputs": [{"candidate": r["candidate_id"], **grade(spec, r["recipe"], derived)} for r in passed],
           "rejected_candidates": len([r for r in f.get("results") or [] if not r.get("passed")]),
           "judge": {"scored": sum(1 for p in jv if p.get("source") == "llm"), "uncited_invalidated": sum(1 for p in jv if p.get("source") == "uncited"),
                     "unavailable": sum(1 for p in jv if p.get("source") == "unavailable")},
           "seconds": round(time.time() - t0, 1), "llm_calls": calls() - c0, "providers": by_provider(b0)}
    smiles = (getattr(spec, "api_profile", None) and spec.api_profile.smiles) or case.get("smiles") or ""
    return rec, spec, derived, rec["strategies"] or ["CONV_DC", "CONV_DG", "CONV_WG"], smiles


def decision(outs: List[Dict[str, Any]], extra: Any = None) -> str:
    return json.dumps({"n": len(outs), "rules": sorted({r for o in outs for r in o["hard_fail"] + o["contract_fail"]}), "x": extra},
                      ensure_ascii=False, sort_keys=True)


def stage1() -> Dict[str, Any]:
    res: Dict[str, Any] = {"cases": [], "cost": {}}
    q0 = quota()
    cost = {"F": {"seconds": 0.0, "calls": 0, "tokens": 0}, "G": {"seconds": 0.0, "calls": 0, "tokens": 0}, "P": {"seconds": 0.0, "calls": 0, "tokens": 0}}
    for case in [c for c in CASES if not ONLY or c["id"] in ONLY]:
        row: Dict[str, Any] = {"id": case["id"], "label": case["label"], "expect_infeasible": case["expect_infeasible"], "F": [], "G": [], "P": []}
        base = None
        for _ in range(REPEAT):
            qa = quota()
            rec, spec, derived, strategies, smiles = full(case)
            qb = quota()
            rec["tokens"] = (qa - qb) if qa and qb else None
            row["F"].append(rec)
            base = base or (spec, derived, strategies, smiles)
            print(case["id"], "F", rec["status"], len(rec["outputs"]), rec["seconds"], flush=True)
        spec, derived, strategies, smiles = base
        row["grading_input"] = {"spec": _spec_json(spec), "derived": dict(derived or {})}
        for _ in range(REPEAT):
            qa = quota()
            rec = unverified(case["id"], spec, derived, strategies)
            qb = quota()
            rec["tokens"] = (qa - qb) if qa and qb else None
            row["G"].append(rec)
            print(case["id"], "G", len(rec["outputs"]), sum(o["unsafe"] or o["contract"] for o in rec["outputs"]), flush=True)
        for _ in range(P_REPEAT):
            qa = quota()
            try:
                rec = pure(case, spec, derived, smiles)
            except C.LLMUnavailable as exc:
                rec = {"error": str(exc)[:200], "outputs": [], "feasible": None}
            qb = quota()
            rec["tokens"] = (qa - qb) if qa and qb else None
            row["P"].append(rec)
            print(case["id"], "P", rec.get("feasible"), [o["hard_fail"] + o["contract_fail"] for o in rec["outputs"]], flush=True)
        for k in ("F", "G", "P"):
            for r in row[k]:
                cost[k]["seconds"] += r.get("seconds") or 0
                cost[k]["calls"] += r.get("llm_calls") or 0
                cost[k]["tokens"] += r.get("tokens") or 0
        row["reproducible"] = {
            "F": len({decision(r["outputs"], [r["status"], r["plan_signature"]]) for r in row["F"]}) == 1,
            "G": len({decision(r["outputs"]) for r in row["G"]}) == 1,
            "P": len({decision(r["outputs"], r.get("feasible")) for r in row["P"]}) == 1}
        res["cases"].append(row)
    res["cost"] = cost
    res["quota_used_total"] = (q0 - quota()) if q0 else None
    return res


# ── 2단계 ────────────────────────────────────────────────────────────────
class CodedFit(BaseModel):
    hardness_linear: List[float] = Field(description="경도 선형 모형 coded 계수 [b0, b1(Force), b2(MCC), b3(CCS)]")
    hardness_model_p: float
    hardness_lack_of_fit_p: float
    hardness_r2: float
    dt_quadratic: List[float] = Field(description="붕해시간 2차 모형 coded 계수 [b0, b1, b2, b3, b12, b13, b23, b11, b22, b33]")
    dt_model_p: float


def _table_text(design) -> str:
    fn = [f"{f['name']}({f.get('unit') or ''})" for f in design["factors"]]
    rn = [f"{r['name']}({r.get('unit') or ''})" for r in design["responses"]]
    lines = ["run," + ",".join(fn + rn)] + [f"{r['run']}," + ",".join(str(v) for v in list(r["x"]) + list(r["y"])) for r in design["rows"]]
    return "\n".join(lines)


def s_a() -> Dict[str, Any]:
    d = REF.design()
    truth = T.regression(d, {"Hardness": "Linear", "DT": "Quadratic", "Friability": "Linear"})
    hr = next(r for r in truth["responses"] if r["response"] == "Hardness")
    dr = next(r for r in truth["responses"] if r["response"] == "DT")
    fn, X, rn, Y = T.table_arrays(d)
    x = T.to_coded(X, T.coding(X))
    h_an = T.anova("Linear", x, Y[:, 0], fn)
    d_an = T.anova("Quadratic", x, Y[:, 1], fn)
    tv = {"hardness_linear": hr["coef"], "dt_quadratic": dr["coef"],
          "hardness_model_p": next(r["p"] for r in h_an["rows"] if r["source"] == "Model"),
          "hardness_lack_of_fit_p": next(r["p"] for r in h_an["rows"] if r["source"] == "Lack of fit"),
          "hardness_r2": h_an["r2"], "dt_model_p": next(r["p"] for r in d_an["rows"] if r["source"] == "Model")}
    prompt = ("다음은 Box–Behnken 실험 17 run이다. 요인은 표의 최솟값·최댓값으로 coded(−1…+1)로 바꿔(x = (X − 중앙)/반폭) 최소제곱으로 적합하라.\n"
              "1) 경도(Hardness) 선형 모형 계수와 모형 F검정 p값, 적합결여 p값(같은 설정 반복점의 순수오차 기준), R²\n"
              "2) 붕해시간(DT) 전체 2차 모형 coded 계수(b0, b1, b2, b3, b12, b13, b23, b11, b22, b33)와 모형 p값\n\n" + _table_text(d))
    reps = []
    for _ in range(3):
        try:
            with C.use_llm(LLM):
                out = C.parse_structured(CodedFit, "당신은 통계 계산을 정확히 하는 실험계획(DoE) 전문가다. 계산 결과만 JSON으로 답한다.", prompt)
        except C.LLMUnavailable as exc:
            reps.append({"error": str(exc)[:200]})
            continue
        got = out.model_dump()
        print("S-A rep", len(reps) + 1, flush=True)
        coef_err = []
        for k in ("hardness_linear", "dt_quadratic"):
            for a, b in zip(got[k], tv[k]):
                coef_err.append(abs(a - b) / max(abs(b), 1e-9))
        n_expected = len(tv["hardness_linear"]) + len(tv["dt_quadratic"])
        within = sum(1 for e in coef_err if e <= 0.01) + 0
        sig = [(got[k] < 0.05) == (tv[k] < 0.05) for k in ("hardness_model_p", "hardness_lack_of_fit_p", "dt_model_p")]
        reps.append({"coef_within_1pct": within, "coef_total": n_expected, "coef_count_ok": len(coef_err) == n_expected,
                     "median_rel_err": float(np.median(coef_err)) if coef_err else None, "max_rel_err": float(max(coef_err)) if coef_err else None,
                     "p_decision_ok": sum(sig), "p_total": len(sig), "got": {k: got[k] for k in ("hardness_model_p", "hardness_lack_of_fit_p", "dt_model_p", "hardness_r2")},
                     "got_hardness": got["hardness_linear"]})
    return {"truth": {k: tv[k] for k in ("hardness_model_p", "hardness_lack_of_fit_p", "dt_model_p", "hardness_r2")},
            "truth_hardness": tv["hardness_linear"], "reps": reps,
            "system": {"coef_within_1pct": len(tv["hardness_linear"]) + len(tv["dt_quadratic"]), "note": "toolkit = 논문 Table 10·11 재현(테스트 고정)"}}


class SpaceOut(BaseModel):
    ranges: Dict[str, List[float]] = Field(description="요인 이름 → [하한, 상한] — 모든 목표를 만족한다고 판단한 운전 범위(Design Space)")
    setpoint: Dict[str, float] = Field(description="권장 설정점 — 요인 이름 → 값")
    predicted: Dict[str, float] = Field(description="설정점에서 반응 예측값 — 반응 이름 → 값")


LX_SPECS = [{"response": "Dispersion time", "op": "LE", "upper": 180}, {"response": "Friability", "op": "LE", "upper": 1.0},
            {"response": "DE30", "op": "GE", "lower": 75}, {"response": "AV", "op": "LE", "upper": 15}]


def s_b() -> Dict[str, Any]:
    d = PD.design("almotairi2022_t3")
    reg = T.regression(d)
    R = SP.region(d, reg, LX_SPECS)
    fn, cod, x = SP._setup(d)
    models = SP._models(reg, LX_SPECS)
    dom = SP.Domain(x)

    def coded(vals):
        return np.array([(float(vals[n]) - cod[i]["center"]) / cod[i]["half"] for i, n in enumerate(fn)])

    def evaluate(rng, sp):
        g = [np.linspace(*sorted(rng[n]), 11) for n in fn]
        pts = np.array(np.meshgrid(*g, indexing="ij")).reshape(len(fn), -1).T
        cx = np.array([(pts[:, i] - cod[i]["center"]) / cod[i]["half"] for i in range(len(fn))]).T
        inside = dom.contains(cx)
        P, ok, _, _ = SP._joint(models, cx)
        spc = coded(sp)[None, :]
        Ps, oks, _, means = SP._joint(models, spc)
        return {"box_in_domain": float(inside.mean()), "box_mean_ok": float(ok[inside].mean()) if inside.any() else 0.0,
                "box_all_ok": bool(ok[inside].all()) if inside.any() else False,
                "setpoint_in_domain": bool(dom.contains(spc)[0]), "setpoint_mean_ok": bool(oks[0]), "setpoint_joint": float(Ps[0]),
                "model_pred": {k: float(v[0]) for k, v in means.items()}}
    targets = "; ".join(f"{s['response']} {SP.spec_text(s)}" for s in LX_SPECS)
    prompt = (f"다음은 로르녹시캄 분산정 Box–Behnken 실험 15 run(Almotairi 2022 Table 3)이다. 목표: {targets}.\n"
              f"요인 이름은 표 머리글 그대로 쓴다: {', '.join(fn)}. 반응 이름: {', '.join(r['name'] for r in d['responses'])}.\n"
              "데이터를 분석해 모든 목표를 동시에 만족하는 운전 범위(Design Space)를 요인별 [하한, 상한]으로, 권장 설정점과 그때의 반응 예측값을 답하라.\n\n"
              + _table_text(d))
    reps = []
    for _ in range(3):
        try:
            with C.use_llm(LLM):
                out = C.parse_structured(SpaceOut, "당신은 QbD Design Space를 정하는 제제 연구원이다. 결과만 JSON으로 답한다.", prompt)
        except C.LLMUnavailable as exc:
            reps.append({"error": str(exc)[:200]})
            continue
        if not all(n in out.ranges and n in out.setpoint and len(out.ranges[n]) == 2 for n in fn):
            reps.append({"error": "요인 이름·형식 불일치", "got": out.model_dump()})
            continue
        print("S-B rep", len(reps) + 1, flush=True)
        ev = evaluate(out.ranges, out.setpoint)
        err = {k: abs(out.predicted.get(k, float("nan")) - v) for k, v in ev["model_pred"].items()}
        reps.append({"ranges": out.ranges, "setpoint": out.setpoint, **ev, "pred_abs_err": err})
    cs = R["control_space"]
    sys_rng = {n: (cs[n] if isinstance(cs[n], list) else [cs[n], cs[n]]) for n in fn}
    return {"system": {"control_space": cs, "optimum": R["optimum"]["actual"], **evaluate(sys_rng, R["optimum"]["actual"])}, "reps": reps}


class RiskOut(BaseModel):
    matrix: Dict[str, Dict[str, str]] = Field(description="변수 → (CQA → High/Medium/Low) — 모든 변수 × 모든 CQA")
    justification: List[Dict[str, Any]] = Field(description="근거 행 — {variable, cqas: [CQA…], level: High/Medium/Low, text}")


def s_c() -> Dict[str, Any]:
    proto = REF.prototype()
    cqas = REF.risk()["cqa"]["risk_order"]
    variables = [v["name"] for v in REF.step("fp_just")["variables"]]
    ing = ", ".join(f"{i['name']} {i['mg']} mg({i.get('function') or i.get('role')})" for i in proto["ingredients"])
    prompt = (f"CBD 구강붕해정 프로토타입: {ing}; 공정 {proto['process']}.\n위험평가 대상 CQA: {', '.join(cqas)}.\n"
              f"제형·공정 변수: {', '.join(variables)}.\n각 변수가 각 CQA에 주는 위험을 High/Medium/Low로 평가해 (1) 변수 × CQA 행렬과 "
              "(2) 근거 표(같은 등급·같은 근거를 공유하는 CQA를 한 행에 묶어 variable · cqas · level · text)를 모두 작성하라.")
    reps = []
    for _ in range(2):
        try:
            with C.use_llm(LLM):
                out = C.parse_structured(RiskOut, "당신은 ICH Q9 초기 위험평가를 쓰는 제제 연구원이다. JSON으로 답한다.", prompt)
        except C.LLMUnavailable as exc:
            reps.append({"error": str(exc)[:200]})
            continue
        print("S-C rep", len(reps) + 1, flush=True)
        cells = {(v, c) for v in variables for c in cqas}
        just: Dict[tuple, List[str]] = {}
        for row in out.justification:
            for c in row.get("cqas") or []:
                just.setdefault((str(row.get("variable")), str(c)), []).append(str(row.get("level")))
        missing_matrix = sum(1 for v, c in cells if (out.matrix.get(v) or {}).get(c) not in ("High", "Medium", "Low"))
        uncovered = sum(1 for k in cells if k not in just)
        conflict = sum(1 for k in cells if k in just and len(set(just[k])) > 1)
        mismatch = sum(1 for k in cells if k in just and (out.matrix.get(k[0]) or {}).get(k[1]) not in just[k])
        reps.append({"cells": len(cells), "matrix_missing": missing_matrix, "justification_uncovered": uncovered,
                     "justification_conflict": conflict, "matrix_vs_justification_mismatch": mismatch})
    return {"variables": len(variables), "cqas": len(cqas), "reps": reps,
            "system": {"note": "행렬은 근거 표에서 코드가 계산하고 빈 칸은 승인 차단(JUST_MISSING) — 구조상 0", "mismatch": 0, "uncovered": 0}}


def main():
    out = {"llm": LLM, "model": C.DACON_MODEL, "repeat": REPEAT, "p_repeat": P_REPEAT, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    t0 = time.time()
    if "s2" in PARTS:
        out["stage2"] = {"S_A": s_a(), "S_B": s_b(), "S_C": s_c()}
        print("stage2 done", round(time.time() - t0), "s", flush=True)
    if "s1" in PARTS:
        out["stage1"] = stage1()
    out["seconds"] = round(time.time() - t0)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("written", OUT.relative_to(ROOT), flush=True)


def merge(paths: List[str]) -> None:
    """나눠 돌린 결과(1단계 · 2단계)를 docs/report/ablation.json 하나로 — 값은 옮기기만 한다."""
    out: Dict[str, Any] = {}
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        out.update({k: v for k, v in d.items() if k not in ("stage1", "stage2", "seconds", "at")})
        for k in ("stage1", "stage2"):
            if k in d:
                out[k] = d[k]
        out.setdefault("parts", []).append({"file": Path(p).name, "at": d.get("at"), "seconds": d.get("seconds")})
    (ROOT / "docs" / "report" / "ablation.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("merged → docs/report/ablation.json")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "merge":
        merge(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "regrade":
        regrade(sys.argv[2])
    else:
        main()
