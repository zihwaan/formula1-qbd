"""D2 FMEA — RB04 실패모드 → 초안, RB05 점수 정책(O 근거 없으면 UNKNOWN·RPN 없음, S≥4 제외 보호, RPN은 정렬 보조)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from formula.doe.package import DoePackage

EVIDENCE_CLASS = {"textbook": "RULE_SUPPORTED", "compendial": "RULE_SUPPORTED", "guideline": "RULE_SUPPORTED",
                  "general_gmp": "RULE_SUPPORTED", "scientific_risk": "RULE_SUPPORTED", "llm_hypothesis": "LLM_HYPOTHESIS"}
DISPOSITIONS = ("DOE_CANDIDATE", "FIXED", "EXCLUDED", "CONTROL_SOP", "MONITOR", "MATERIAL_SPEC", "REQUEST_DATA", "CONFIRMATION_REQUIRED")
HIGH_S = 4


def draft(pkg: DoePackage, route: str, cqa_ids: List[str]) -> List[Dict[str, Any]]:
    rows = []
    for r in pkg.rows("RB04"):
        if r["process_route"] not in (route, "all") or r.get("evidence_type") == "llm_hypothesis":
            continue                                    # LLM 가설 행(FM019)은 연구자가 추가할 때만
        effects = [c for c in (r.get("cqa_effect") or "").split(";") if c]
        factors = [f for f in (r.get("candidate_factor") or "").split(";") if f and f != "—"]
        kinds = [k for k in (r.get("factor_kind") or "").split(";") if k and k != "—"]
        rows.append({"row_id": r["failure_mode_id"], "unit_op": r.get("unit_op_code") or None, "cause": r["cause"],
                     "failure_mode": r["failure_mode"], "local_effect": r.get("local_effect", ""), "cqa_effect_ids": effects,
                     "affects_selected_cqa": bool(set(effects) & set(cqa_ids)), "candidate_factors": factors,
                     "factor_kinds": kinds, "disposition": r.get("default_disposition") or "MONITOR",
                     "severity": None, "occurrence": "UNKNOWN", "detectability": None, "risk_level": None,
                     "evidence_class": EVIDENCE_CLASS.get(r.get("evidence_type", ""), "RULE_SUPPORTED"),
                     "evidence_refs": [s for s in (r.get("source_ids") or "").split(";") if s], "rationale": "",
                     "alternative_control": None})
    return rows


def rpn(row: Dict[str, Any]) -> Optional[int]:
    s, o, d = row.get("severity"), row.get("occurrence"), row.get("detectability")
    if isinstance(s, int) and isinstance(o, int) and isinstance(d, int):
        return s * o * d
    return None                                          # O UNKNOWN이면 계산하지 않는다(RB05 FMEA_UNKNOWN_OCCURRENCE)


def check(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """RB05 정책 위반 목록 — 고심각도 행을 대체 관리·사유 없이 제외할 수 없다."""
    out = []
    for r in rows:
        if r.get("disposition") == "EXCLUDED" and isinstance(r.get("severity"), int) and r["severity"] >= HIGH_S \
                and not (r.get("alternative_control") and r.get("rationale")):
            out.append({"policy": "FMEA_HIGH_SEVERITY_PROTECTION", "row_id": r["row_id"],
                        "message_ko": "심각도 4 이상 행은 대체 관리수단과 연구자 사유 없이 제외할 수 없습니다."})
        if isinstance(r.get("detectability"), int) and not r.get("detection_method_id"):
            out.append({"policy": "FMEA_DETECTABILITY_EVIDENCE", "row_id": r["row_id"],
                        "message_ko": "검출도 점수에는 등록된 시험법과 검출 근거가 필요합니다."})
    return out


def factor_candidates(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        for k, fkey in enumerate(r["candidate_factors"]):
            c = by.setdefault(fkey, {"key": fkey, "kind": (r["factor_kinds"][k] if k < len(r["factor_kinds"]) else None),
                                     "fmea_refs": [], "linked_cqa_ids": set(), "high_risk": False, "doe_candidate": False})
            c["fmea_refs"].append(r["row_id"])
            c["linked_cqa_ids"] |= set(r["cqa_effect_ids"])
            c["doe_candidate"] |= r["disposition"] == "DOE_CANDIDATE"
            c["high_risk"] |= (isinstance(r.get("severity"), int) and r["severity"] >= HIGH_S) or (r.get("risk_level") == "High")
    return [{**c, "linked_cqa_ids": sorted(c["linked_cqa_ids"])} for c in by.values()]
