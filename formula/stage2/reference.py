"""논문 참조값 — Monton 2026(Scientifica 2026:3553253) Table 1·3·4·6·8·9와 Table 2의 DoE 요인·Table 10·11의 모형 차수.
CBD 논문 프로토타입으로 시작한 study에서만 '논문 값으로 채우기'와 '논문과 비교'에 쓴다. 다른 study에는 참조값이 없다(만들지 않는다)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


@lru_cache(maxsize=1)
def risk() -> Dict[str, Any]:
    return json.loads((FIX / "cbd_odt_risk_monton2026.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def doe() -> Dict[str, Any]:
    return json.loads((FIX / "cbd_odt_monton2026.json").read_text(encoding="utf-8"))


def citation() -> str:
    return risk()["citation"]


def prototype() -> Dict[str, Any]:
    p = risk()["prototype"]
    return {"api": p["api"], "dosage_form": p["dosage_form"], "route": p["route"], "process": p["process"], "strength_mg": p["strength_mg"],
            "unit_weight_mg": p["unit_weight_mg"], "process_steps": list(doe()["process"]["steps_as_reported"]),
            "ingredients": [dict(i) for i in p["ingredients"]], "source": {"citation": citation(), "doi": risk()["doi"], "locator": "Table 1"}}


def _just(key: str, kinds: Optional[list] = None) -> Dict[str, Any]:
    m = risk()["rm_matrix" if key == "rm_just" else "fp_matrix"]
    ks = kinds or m.get("kinds") or ["material"] * len(m["variables"])
    return {"variables": [{"name": v, "kind": k} for v, k in zip(m["variables"], ks)],
            "items": [{**i, "basis": "문헌(출처 기재)"} for i in risk()[key]["items"]]}


def design() -> Dict[str, Any]:
    fx = doe()
    runs = sorted(fx["runs"], key=lambda r: r["run_order"])
    return {"factors": [{"name": "Force", "unit": "psi"}, {"name": "MCC", "unit": "%"}, {"name": "CCS", "unit": "%"}],
            "responses": [{"name": "Hardness", "unit": "kgf"}, {"name": "DT", "unit": "s"}, {"name": "Friability", "unit": "%"}],
            "rows": [{"std": r["std_order"], "run": r["run_order"], "x": [r["force_psi"], r["mcc_pct"], r["ccs_pct"]],
                      "y": [r["hardness_kgf"]["mean"], r["dt_s"]["mean"], r["friability_pct"]["value"]]} for r in runs]}


# 논문이 DoE에 넣은 요인(Table 2 · Results 3.3 '고위험 → DoE') · 논문이 반응별로 쓴 모형 차수(Table 10·11)
PAPER_DOE_VARIABLES = ["Compression force", "MCC", "CCS"]
PAPER_FAMILIES = {"Hardness": "Linear", "DT": "Quadratic", "Friability": "2FI"}


_RESP = {"hardness_kgf": "Hardness", "dt_s": "DT", "friability_pct": "Friability"}


def specs() -> Dict[str, Dict[str, Any]]:
    """논문의 반응 규격(Table 2 · Methods — 경도 4–6 kgf, 붕해 ≤ 30 s, 마손도 ≤ 1 %) — 설계 표의 반응 이름으로."""
    out = {}
    for r in doe()["responses"]:
        name = _RESP.get(r["id"])
        if not name:
            continue
        out[name] = {"response": name, "unit": r.get("unit") or "", "op": r.get("operator"), "lower": r.get("lower"), "upper": r.get("upper"),
                     "basis": f"Monton 2026 ({r.get('name')} 규격)"}
    return out


def reference_point() -> Dict[str, Any]:
    """논문 최적 처방(1400 psi · MCC 35 % · CCS 1 %) — 확인계획의 참고점(결과가 이미 공개돼 승격 근거로 쓰지 않는다)."""
    o = doe()["optimum"]
    return {"label": "논문 최적 처방(Table 12 확인 lot)", "settings": {"Force": o["force_psi"], "MCC": o["mcc_pct"], "CCS": o["ccs_pct"]}}


def step(name: str) -> Optional[Dict[str, Any]]:
    r = risk()
    if name == "prototype":
        return prototype()
    if name == "qtpp":
        return {"items": [{**i, "basis": "문헌(출처 기재)"} for i in r["qtpp"]["items"]]}
    if name == "cqa":
        return {"items": [{**i, "basis": "문헌(출처 기재)"} for i in r["cqa"]["items"]]}
    if name == "rm_just":
        return _just("rm_just")
    if name == "fp_just":
        return _just("fp_just")
    if name == "design":
        return design()
    return None


LOCATOR = {"prototype": "Table 1", "qtpp": "Table 3", "cqa": "Table 4 · Results 3.3", "rm_just": "Table 6", "rm_matrix": "Table 5",
           "fp_just": "Table 8", "fp_matrix": "Table 7", "recommend": "Results 3.3 · Table 2", "design": "Table 9",
           "regression": "Table 10", "surface": "Figure 1", "anova": "Table 11", "space": "Table 2 규격", "vplan": "Table 12"}
