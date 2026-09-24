"""RangeProposer — 명세 v6.1 §3.4·§6 D4, 룰북 #10(factor_eligibility)·#11(factor_range_constraint).

요인별 low/center/high를 **근거와 함께 제안**한다. 확정은 연구자가 WAITING_FACTOR_APPROVAL에서 한다.

1. center = 후보처방의 현재값 (Handoff). 없으면 center도 비워 둔다 — 추정하지 않는다.
2. low/high = 근거 교집합: 과학적 범위(부형제 사용범위 master, TYPICAL_USE) ∩ 물리 한계(0–100 %)
   ∩ 연구 목적(연구자 입력). 설비 능력은 master가 UNKNOWN이라 교집합에 넣지 못하고 그 사실을
   notes에 남긴다.
3. 연구 목적 범위가 없고 master 행도 없으면 경계를 만들지 않는다 → FR002 REQUEST_DATA.
4. 폭 적정성은 |예상 범위 효과|와 시험법 반복정밀도가 둘 다 있어야 판정한다. 없으면 NOT_CHECKED.
5. balance(나머지 충진제) 구조면 모든 설계점에서 balance ≥ 0인지는 설계 단계(FR006)가 본다.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from formula.development.rules import DoeRulebook
from formula.qbd.fmea import FACTOR_VOCAB

PCT_ROLES = {"disintegrant_pct": "disintegrant", "lubricant_pct": "lubricant", "glidant_pct": "glidant"}
DILUENT_ROLES = ("diluent", "filler")
SYMBOLS = "abcdefgh"


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def diluents(handoff: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [i for i in handoff["ingredients"] if i.get("role") in DILUENT_ROLES]


def current_value(handoff: Dict[str, Any], factor: str) -> Optional[float]:
    if factor in PCT_ROLES:
        hits = [i for i in handoff["ingredients"] if PCT_ROLES[factor] in (i.get("role") or "")]
        return hits[0].get("pct_w_w") if hits else None
    if factor == "filler_ratio":
        d = diluents(handoff)
        if len(d) >= 2 and d[0].get("pct_w_w") and d[1].get("pct_w_w"):
            return round(d[0]["pct_w_w"] / d[1]["pct_w_w"], 3)
        return None
    for p in handoff.get("fixed_parameters", []):
        if p["name"] == factor and p.get("status") == "SET":
            try:
                return float(p["value"])
            except (TypeError, ValueError):
                return None
    return None


def ingredient_for(handoff: Dict[str, Any], factor: str) -> Optional[str]:
    if factor in PCT_ROLES:
        hits = [i for i in handoff["ingredients"] if PCT_ROLES[factor] in (i.get("role") or "")]
        return hits[0]["name"] if hits else None
    if factor == "filler_ratio":
        d = diluents(handoff)
        return " : ".join(i["name"] for i in d[:2]) if len(d) >= 2 else None
    return None


def master_row(rb: DoeRulebook, ingredient: Optional[str]) -> Optional[Dict[str, str]]:
    if not ingredient:
        return None
    key = _norm(ingredient)
    for r in rb.master("excipient_use_range_master"):
        if _norm(r["name_en"]) in key or _norm(r["name_ko"]) in key or key in _norm(r["name_en"]):
            return r
    return None


def balance_fn(handoff: Dict[str, Any], factors: List[Dict[str, Any]]) -> Optional[Callable[[Dict[str, float]], float]]:
    """설계점 actual 설정 → balance 성분(충진제 합) % w/w. balance 구조가 없으면 None."""
    pct_factors = {f["factor_id"]: f["source_factor"] for f in factors if f.get("source_factor") in PCT_ROLES}
    if not pct_factors or not diluents(handoff):
        return None
    base = {i["name"]: i.get("pct_w_w") or 0.0 for i in handoff["ingredients"] if i.get("role") not in DILUENT_ROLES}

    def fn(actual: Dict[str, float]) -> float:
        other = dict(base)
        for fid, src in pct_factors.items():
            ing = ingredient_for(handoff, src)
            if ing in other and fid in actual:
                other[ing] = actual[fid]
        return 100.0 - sum(other.values())
    return fn


def propose(rb: DoeRulebook, handoff: Dict[str, Any], candidates: List[Dict[str, Any]],
            study_inputs: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """FMEA DOE_CANDIDATE 요인 → FactorDefinition dict. study_inputs = 연구자 입력(요인별)."""
    out: Dict[str, Dict[str, Any]] = {}
    for n, cand in enumerate(candidates):
        src = cand["factor"]
        vocab = FACTOR_VOCAB.get(src, {"name": src, "unit": None, "kind": "CPP"})
        inp = study_inputs.get(src, {})
        center = current_value(handoff, src)
        ing = ingredient_for(handoff, src)
        mrow = master_row(rb, ing) if src in PCT_ROLES else None
        notes: List[str] = []
        center_bound = {"value": center, "source_ref": "Handoff 현재값" if center is not None else None,
                        "evidence_status": "MEASURED_CONFIRMED" if center is not None else "UNKNOWN"}
        if center is None:
            notes.append("Handoff에 현재값이 없어 center를 비워 둠 (FR001)")
        low = {"value": None, "source_ref": None, "evidence_status": "UNKNOWN"}
        high = dict(low)
        if inp.get("low") is not None and inp.get("high") is not None:
            lo, hi = float(inp["low"]), float(inp["high"])
            ev = inp.get("evidence_status") or "EXPERT_ASSUMPTION"
            srcref = inp.get("source_ref")
            if vocab["unit"] == "pct_w_w":
                lo2, hi2 = max(lo, 0.0), min(hi, 100.0)
                if (lo2, hi2) != (lo, hi):
                    notes.append("물리 한계(0–100 %)로 잘림")
                lo, hi = lo2, hi2
            low = {"value": lo, "source_ref": srcref, "evidence_status": ev}
            high = {"value": hi, "source_ref": srcref, "evidence_status": ev}
            notes.append("연구 목적 범위(연구자 입력)를 사용")
        elif mrow and center is not None:
            tmin, tmax = float(mrow["min_pct"]), float(mrow["max_pct"])
            lo, hi = max(tmin, 0.0), min(tmax, 100.0)
            ref = f"{mrow['excipient_id']} ({mrow['citation_locator']})"
            low = {"value": lo, "source_ref": ref, "evidence_status": "LITERATURE_DIRECT"}
            high = {"value": hi, "source_ref": ref, "evidence_status": "LITERATURE_DIRECT"}
            notes.append(f"부형제 통상 사용범위 {tmin}–{tmax} % (TYPICAL_USE, 한계 아님)를 제안")
        else:
            notes.append("근거 있는 경계가 없음 — 연구 목적 범위를 입력하거나 자료를 제출해야 함 (FR002)")
        if mrow and low["value"] is not None:
            if low["value"] < float(mrow["min_pct"]) or high["value"] > float(mrow["max_pct"]):
                notes.append(f"통상 사용범위 {mrow['min_pct']}–{mrow['max_pct']} %를 벗어남 (FR003 경고 대상)")
        notes.append("설비 능력: equipment_capability_master 값 UNKNOWN — 교집합에 반영하지 못함")
        fid = f"F_{src}"
        out[fid] = {
            "factor_id": fid, "version": 1, "name": vocab["name"], "kind": vocab["kind"],
            "unit": vocab["unit"], "low": low, "center": center_bound, "high": high,
            "width_check": "NOT_CHECKED", "composition_group_id": "CG1" if src in PCT_ROLES or src == "filler_ratio" else None,
            "balance_component": (" + ".join(i["name"] for i in diluents(handoff))
                                  if src in PCT_ROLES and diluents(handoff) else None),
            "range_finding_run_ids": [], "fmea_refs": cand.get("fmea_refs", []), "supersedes": None,
            "status": "READY" if low["value"] is not None else "REQUEST_DATA",
            "ingredient": ing, "symbol": SYMBOLS[n] if n < len(SYMBOLS) else f"x{n}",
            "source_factor": src, "disposition": inp.get("disposition", "DOE_CANDIDATE"),
            "manufacturability_evidence": inp.get("manufacturability_evidence"),
            "expected_range_contrast": inp.get("expected_range_contrast"),
            "levels": [], "proposal_notes": notes,
            "at_extreme_of_master_range": bool(mrow and low["value"] is not None and (
                low["value"] <= float(mrow["min_pct"]) or high["value"] >= float(mrow["max_pct"]))),
            "master_range": ({"typical_min_pct": float(mrow["min_pct"]), "typical_max_pct": float(mrow["max_pct"]),
                              "excipient_id": mrow["excipient_id"]} if mrow else None),
        }
    return out


def factor_context(f: Dict[str, Any]) -> Dict[str, Any]:
    def bound(b):
        return {"value": b.get("value"), "source_ref": b.get("source_ref"),
                "evidence_status": b.get("evidence_status"), "amount_per_unit_mg": None}
    return {
        "id": f["factor_id"], "kind": f["kind"], "unit": f["unit"],
        "low": bound(f["low"]), "center": bound(f["center"]), "high": bound(f["high"]),
        "expected_range_contrast": f.get("expected_range_contrast"),
        "manufacturability_evidence": f.get("manufacturability_evidence"),
        "at_extreme_of_master_range": f.get("at_extreme_of_master_range", False),
        "levels": f.get("levels", []), "redefinition_requested": False,
        "disposition": f.get("disposition"),
    }
