"""FMEA engine — 명세 v6.1 §3.3·§6 D3, 룰북 #8(fmea_failure_mode_rules)·#9(fmea_scoring_scale).

seed 행(공정경로별 원인–실패모드–CQA)을 승인된 CQA에 연결하고 S/O/D를 매긴다.

- **S**는 연결된 CQA의 criticality에서만 온다(척도표 #9: 5 = 환자 안전·유효성 직결 CQA,
  4 = critical CQA 이탈 가능, 3 = 비critical).
- **O**는 기본 `UNKNOWN`. 관찰자료 없이 숫자를 만들지 않는다. O가 UNKNOWN인 행은
  RPN을 계산하지 않는다(척도표 RULE RPN_WHEN_O_UNKNOWN).
- **D**는 실제 시험·관리 수단과 연결될 때만 매긴다. 고정 공정변수가 기록조차 안 되면(압축력
  UNKNOWN) 검출 불가 = 5.
- 처리 방향은 seed의 기본값을 쓰고, 고심각도 행의 제외 가능 여부는 FE012가 판정한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from formula.development.rules import DoeRulebook

_DISPOSITION = {"DOE_CANDIDATE": "DOE_CANDIDATE", "CONTROL_SOP": "FIXED", "MATERIAL_SPEC": "FIXED",
                "REQUEST_DATA": "REQUEST_DATA", "MONITOR": "FIXED"}
_S_BY_CRITICALITY = {"HIGH": 4, "MEDIUM": 3, "LOW": 2}
# S=5: 환자 안전·유효성 직결 (척도표 #9 SEVERITY 5 정의의 예시 그대로)
_PATIENT_CRITICAL = {"CQA_ASSAY", "CQA_CU_AV"}

# FMEA 요인 어휘 → (사람이 읽는 이름, 단위, 종류)
FACTOR_VOCAB: Dict[str, Dict[str, str]] = {
    "blend_time": {"name": "주혼합 시간", "unit": "min", "kind": "CPP"},
    "filler_ratio": {"name": "충진제 비 (가소성:취성)", "unit": "ratio", "kind": "CMA"},
    "disintegrant_pct": {"name": "붕해제 함량", "unit": "pct_w_w", "kind": "CMA"},
    "lubricant_pct": {"name": "활택제 함량", "unit": "pct_w_w", "kind": "CMA"},
    "lubrication_time": {"name": "활택 혼합 시간", "unit": "min", "kind": "CPP"},
    "compression_force": {"name": "압축력", "unit": "kN", "kind": "CPP"},
    "sieve_mesh": {"name": "체 눈 크기", "unit": "mesh", "kind": "CPP"},
    "glidant_pct": {"name": "활주제 함량", "unit": "pct_w_w", "kind": "CMA"},
    "api_psd": {"name": "API 입도", "unit": "µm", "kind": "CMA"},
    "transfer_control": {"name": "이송 관리", "unit": None, "kind": "CPP"},
}


def severity_for(cqa_ids: List[str], cqas: Dict[str, Dict[str, Any]], api: Dict[str, Any]) -> Optional[int]:
    scores = []
    for cid in cqa_ids:
        c = cqas.get(cid)
        if not c or c["analysis_role"] == "NOT_APPLICABLE":
            continue
        s = _S_BY_CRITICALITY.get(c["criticality"], 3)
        if c["criticality"] == "HIGH" and (cid in _PATIENT_CRITICAL or (
                c["category"] == "performance" and api.get("bcs_class") in ("II", "IV"))):
            s = 5
        scores.append(s)
    return max(scores) if scores else None


def draft_fmea(rb: DoeRulebook, handoff: Dict[str, Any], cqas: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    route = handoff.get("process_route_id")
    fixed = {p["name"]: p for p in handoff.get("fixed_parameters", [])}
    methods = {r["test_method_id"] for r in rb.master("test_method_registry")}
    rows = []
    for seed in rb.master("fmea_failure_mode_rules"):
        if seed["process_route"] != route:
            continue
        linked = [c for c in seed["cqa_effect"].split(";") if c in cqas and cqas[c]["analysis_role"] != "NOT_APPLICABLE"]
        if not linked:
            continue
        factors = [f for f in seed["candidate_factor"].split(";") if f and f != "—"]
        kinds = [k for k in seed["factor_kind"].split(";") if k and k != "—"]
        det_methods = [m for m in seed["detection_method_ids"].split(";") if m in methods]
        unrecorded = [f for f in factors if fixed.get(f, {}).get("status") == "UNKNOWN"]
        detect = 5 if unrecorded else (3 if det_methods else 5)
        sev = severity_for(linked, cqas, handoff.get("api") or {})
        rows.append({
            "row_id": seed["seed_id"], "seed_id": seed["seed_id"], "unit_op_code": seed["unit_op_code"] or None,
            "risk_category": seed["risk_category"], "cause": seed["cause"],
            "failure_mode": seed["failure_mode"], "local_effect": seed["local_effect"],
            "cqa_effect": linked, "candidate_factors": factors,
            "kind": kinds[0] if kinds else None,
            "severity": sev, "occurrence": None, "occurrence_evidence": None,
            "detectability": detect, "detection_method_ids": det_methods,
            "detect_note": ("고정값 미기록 — 검출 불가" if unrecorded else
                            "배치별 시험(간접) — 부분 검출" if det_methods else "시험·모니터링 없음"),
            "rpn": None, "disposition": _DISPOSITION.get(seed["default_disposition"], "REQUEST_DATA"),
            "evidence_status": "LITERATURE_DIRECT" if seed["evidence_type"] in ("textbook", "compendial", "guideline")
            else "EXPERT_ASSUMPTION",
            "evidence_type": seed["evidence_type"], "source_ids": seed["source_ids"],
            "alternative_control": None, "approval_ref": None, "deleted": False,
            "unrecorded_parameters": unrecorded, "origin": "SEED",
        })
    return rows


def rpn(row: Dict[str, Any]) -> Optional[int]:
    if row.get("occurrence") is None or row.get("severity") is None or row.get("detectability") is None:
        return None
    return int(row["severity"]) * int(row["occurrence"]) * int(row["detectability"])


def row_context(row: Dict[str, Any], fixed_status: Optional[str] = None,
                low=None, high=None, function_locked: bool = False) -> Dict[str, Any]:
    """룰 context `item`/`row` (manifest entities.fmea_row)."""
    kind = row.get("kind")
    factor = (row.get("candidate_factors") or [None])[0]
    vocab = FACTOR_VOCAB.get(factor or "", {})
    return {
        "severity": row.get("severity"), "occurrence": row.get("occurrence"),
        "occurrence_evidence": row.get("occurrence_evidence"),
        "evidence_status": row.get("evidence_status"),
        "alternative_control": row.get("alternative_control"), "approval_ref": row.get("approval_ref"),
        "disposition": row.get("disposition"),
        "controllable": bool(factor) and factor != "transfer_control",
        "measurable": bool(row.get("detection_method_ids")),
        "range_definable": bool(factor) and vocab.get("unit") is not None,
        "prohibited": False, "function_locked": function_locked, "kind": kind,
        "unit": vocab.get("unit"), "fixed_value_status": fixed_status, "low": low, "high": high,
    }
