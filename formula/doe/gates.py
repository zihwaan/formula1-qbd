"""범위근거 gate(RB07) · feasibility 계획·판정(RB08) · 설계 선택(RB09) — 판정 로직은 코드, 결과 코드·다음 상태·문구는 룰북 행.

모든 규칙이 DRAFT·enforcement_enabled=false인 동안 Decision.enforced=False — 화면은 '권고'로 표시하고 상태를 옮기지 않는다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from formula.doe.contracts import (EVIDENCE_DIRECT_RSM, EVIDENCE_NEEDS_FEASIBILITY, Decision, FactorSpec)
from formula.doe.package import DoePackage


def _decide(pkg: DoePackage, rb: str, rule_id: str, **detail) -> Decision:
    r = pkg.rule(rb, rule_id)
    pkg.reason(r["result_code"])            # 미등록 코드면 예외
    return Decision(rule_id=rule_id, gate_effect=r["gate_effect"], result_code=r["result_code"],
                    next_state=r.get("next_state") or None, message_ko=r.get("message_ko", ""),
                    enforced=pkg.can_enforce(r), detail=detail)


# ── RB07 범위근거 ──────────────────────────────────────────────────────────
def range_evidence(pkg: DoePackage, factors: Sequence[FactorSpec], mode: str) -> Dict[str, Any]:
    """요인별 검사 → study 단위 라우팅(DOE_RANGE_READY | NEEDS_FEASIBILITY | 요청·차단)."""
    per: Dict[str, List[Decision]] = {}
    for f in factors:
        ds: List[Decision] = []
        if f.low is None or f.center is None or f.high is None:
            ds.append(_decide(pkg, "RB07", "RE001", factor=f.factor_id))
        elif not (f.low < f.center < f.high):
            ds.append(_decide(pkg, "RB07", "RE002", factor=f.factor_id))
        if f.center_source == "HANDOFF_REFERENCE_PROTOTYPE":
            ds.append(_decide(pkg, "RB07", "RE003", factor=f.factor_id))
        if any(b is None for b in f.boundaries):
            ds.append(_decide(pkg, "RB07", "RE004", factor=f.factor_id))
        if not f.unit or not f.quantity_kind:
            ds.append(_decide(pkg, "RB07", "RE008", factor=f.factor_id))
        if any(b == "VERIFIED_EXTERNAL_DATA" for b in f.boundaries) and not f.applicability_confirmed:
            ds.append(_decide(pkg, "RB07", "RE007", factor=f.factor_id))
        per[f.factor_id] = ds
    blocking = [d for ds in per.values() for d in ds if d.gate_effect in ("BLOCK_STAGE", "REQUEST_DATA")]
    if blocking:
        route = blocking[0]
    elif mode == "NEW_API" and any(all(b in EVIDENCE_NEEDS_FEASIBILITY for b in f.boundaries) for f in factors):
        route = _decide(pkg, "RB07", "RE005", factors=[f.factor_id for f in factors if all(b in EVIDENCE_NEEDS_FEASIBILITY for b in f.boundaries)])
    elif mode == "NEW_API" and any(any(b not in EVIDENCE_DIRECT_RSM for b in f.boundaries) for f in factors):
        # 경계 일부만 근거가 약해도 신규 API는 RSM 직행 불가(FD001: 요인 하나라도 feasibility 필요)
        route = _decide(pkg, "RB08", "FD001")
    elif mode == "LITERATURE_REPLAY" and any("REPORTED_NO_RAW_DATA" in f.boundaries for f in factors):
        route = _decide(pkg, "RB07", "RE006", scope="LITERATURE_REPLAY_ONLY")
    else:
        route = _decide(pkg, "RB07", "RE012")
    return {"route": route.as_dict(), "factors": {k: [d.as_dict() for d in v] for k, v in per.items()}}


# ── RB08 feasibility micro-study ───────────────────────────────────────────
def feasibility_plan(pkg: DoePackage, factors: Sequence[FactorSpec]) -> Dict[str, Any]:
    """2k+1 축점 계획(2^k+1 아님): 중심 1 + 요인마다 low·high(다른 요인은 중심)."""
    k = len(factors)
    center = {f.factor_id: f.center for f in factors}
    conds = [{"condition_id": "C0", "role": "CENTER", "settings": dict(center)}]
    for f in factors:
        for lvl in ("low", "high"):
            s = dict(center)
            s[f.factor_id] = getattr(f, lvl)
            conds.append({"condition_id": f"{f.factor_id}_{lvl.upper()}", "role": f"BOUNDARY_{lvl.upper()}",
                          "factor": f.factor_id, "settings": s})
    checks = []
    if k == 2 and len(conds) != 5:
        checks.append(_decide(pkg, "RB08", "FD002").as_dict())
    if k == 3 and len(conds) != 7:
        checks.append(_decide(pkg, "RB08", "FD003").as_dict())
    ofat = all(sum(c["settings"][f.factor_id] != f.center for f in factors) <= 1 for c in conds)
    if not ofat:
        checks.append(_decide(pkg, "RB08", "FD004").as_dict())
    return {"design_type": "AXIAL_2K_PLUS_1", "factor_count": k, "condition_count": len(conds), "conditions": conds,
            "fitting_eligibility": "EXCLUDED_BY_DEFAULT", "objective": "경계가 제조·측정 가능한지 확인(최적화 아님)",
            "checks": checks}


def feasibility_evaluate(pkg: DoePackage, plan: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """results[condition_id] = {manufacturable: bool, measurable: bool, critical_incompatibility: bool} (None = 누락)."""
    missing = [c["condition_id"] for c in plan["conditions"]
               if c["condition_id"] not in results or any(results[c["condition_id"]].get(k) is None for k in ("manufacturable", "measurable"))]
    if missing:
        return {"route": _decide(pkg, "RB08", "FD007", missing=missing).as_dict()}
    ok = lambda cid: results[cid]["manufacturable"] and results[cid]["measurable"] and not results[cid].get("critical_incompatibility")  # noqa: E731
    if not ok("C0"):
        return {"route": _decide(pkg, "RB08", "FD005").as_dict()}
    failed = [c["condition_id"] for c in plan["conditions"] if c["condition_id"] != "C0" and not ok(c["condition_id"])]
    if failed:
        return {"route": _decide(pkg, "RB08", "FD006", failed_boundaries=failed).as_dict()}
    return {"route": _decide(pkg, "RB08", "FD008").as_dict()}


# ── RB09 설계 선택 ─────────────────────────────────────────────────────────
def select_design(pkg: DoePackage, factors: Sequence[FactorSpec], *, has_mixture_constraint: bool = False) -> Decision:
    k = len(factors)
    if has_mixture_constraint or any(f.kind == "MIXTURE_COMPONENT" for f in factors):
        return _decide(pkg, "RB09", "DS005")
    if any(f.data_type == "CATEGORICAL" or f.kind == "CATEGORICAL" for f in factors):
        return _decide(pkg, "RB09", "DS006")
    if any(f.kind == "HARD_TO_CHANGE" for f in factors):
        return _decide(pkg, "RB09", "DS007")
    if k > 3:
        return _decide(pkg, "RB09", "DS004")
    return _decide(pkg, "RB09", {1: "DS001", 2: "DS002", 3: "DS003"}[k])


DESIGN_OF_CODE = {"DESIGN_ONE_FACTOR_QUADRATIC": "ONE_FACTOR_QUADRATIC", "DESIGN_FCCD_13": "FCCD", "DESIGN_BBD_17": "BBD"}
