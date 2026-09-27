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


# ── 단위(M04) · 근거 권한(M05) ────────────────────────────────────────────────
def _norm_unit(u: Optional[str]) -> str:
    return (u or "").replace(" ", "").lower()


def unit_compatible(pkg: DoePackage, unit: Optional[str], quantity_kind: Optional[str]) -> Optional[bool]:
    """M04 — 같은 quantity_kind 안의 단위만 허용. 모르는 kind면 None(REQUEST_DATA), 퍼지 변환 없음."""
    reg = (pkg.masters.get("M04") or {}).get("quantity_kinds", {})
    kind = reg.get(quantity_kind or "")
    if kind is None:
        return None
    units = set(map(_norm_unit, list((kind.get("conversions") or {}).keys()) + [kind.get("canonical_unit", "")]))
    return _norm_unit(unit) in units


def to_canonical(pkg: DoePackage, value: float, unit: str, quantity_kind: str) -> Optional[float]:
    kind = (pkg.masters.get("M04") or {}).get("quantity_kinds", {}).get(quantity_kind) or {}
    for u, k in (kind.get("conversions") or {}).items():
        if _norm_unit(u) == _norm_unit(unit):
            return value * float(k)
    return None


# study 안 새 batch 결과용 등급 — M05에 행이 없다(IMPLEMENTATION_DESIGN §8 #8·#9)
EVIDENCE_ALIAS = {"MEASURED_IN_STUDY": "MEASURED_PRIOR_BATCH"}
VERIFICATION_BATCH = "VERIFICATION_BATCH"


def evidence_permits(pkg: DoePackage, status: Optional[str], use: str, *, study_type: str = "NEW_API",
                     plan_locked: bool = True) -> bool:
    """M05 evidence_permission_matrix. use ∈ DIRECT_RSM_NEW_API · LITERATURE_REPLAY · MODEL_FIT · PURE_ERROR · VERIFICATION · RANGE_BASIS."""
    if use == "VERIFICATION" and status == VERIFICATION_BATCH:
        return True          # 독립성 조건(RB17 VR002·VR003·VR013·VR019·RQ009)은 호출 쪽이 따로 검사한다
    rows = {r["evidence_status"]: r for r in pkg.masters.get("M05", [])}
    r = rows.get(EVIDENCE_ALIAS.get(status or "", status or ""))
    if not r:
        return False
    v = (r.get(use) or "").upper()
    if v.startswith("DENY") or v in ("", "DEMO_ONLY", "PROPOSAL_ONLY", "ALLOW_AS_PROPOSAL"):
        return False
    if v == "ALLOW_ONLY_LITERATURE_REPLAY":
        return study_type == "LITERATURE_REPLAY"
    if v == "ALLOW_IF_PLAN":
        return plan_locked
    return v.startswith("ALLOW")


# ── RB01 handoff 진입 ─────────────────────────────────────────────────────────
def handoff_readiness(pkg: DoePackage, h: Dict[str, Any]) -> List[Decision]:
    tol = float(pkg.constants.get("composition_sum_tolerance_pct", 0.5))
    out: List[Decision] = []
    ings = h.get("ingredients", [])
    total = sum(float(i.get("percent_w_w") or 0) for i in ings)
    if abs(total - 100) > tol:
        out.append(_decide(pkg, "RB01", "RD001", detail=f"조성 합 {total:.2f}%"))
    if any(not i.get("unit") for i in ings):
        out.append(_decide(pkg, "RB01", "RD002"))
    if any(i.get("is_critical") and not i.get("material_grade") for i in ings):
        out.append(_decide(pkg, "RB01", "RD003", detail="주성분 등급 없음"))
    if not h.get("process_steps"):
        out.append(_decide(pkg, "RB01", "RD004"))
    if not h.get("equipment_id"):
        out.append(_decide(pkg, "RB01", "RD005"))
    if not h.get("batch_scale"):
        out.append(_decide(pkg, "RB01", "RD006"))
    if any(p.get("value") is None and p.get("status") != "UNKNOWN" for p in h.get("fixed_parameters", [])):
        out.append(_decide(pkg, "RB01", "RD007"))
    if any(v.get("status") == "hard_fail" and not v.get("resolved") for v in h.get("rule_verdicts", [])):
        out.append(_decide(pkg, "RB01", "RD009"))
    if not h.get("qtpp_snapshot_id"):
        out.append(_decide(pkg, "RB01", "RD010"))
    if any(i.get("value_role") != "REFERENCE_PROTOTYPE" for i in ings):
        out.append(_decide(pkg, "RB01", "HR011"))
    if not h.get("formulation_fingerprint") or not h.get("candidate_version"):
        out.append(_decide(pkg, "RB01", "HR012"))
    return out


# ── RB03 CQA 계약 ─────────────────────────────────────────────────────────────
def cqa_eligibility(pkg: DoePackage, cqas: Dict[str, Dict[str, Any]]) -> List[Decision]:
    out: List[Decision] = []
    for cid, c in cqas.items():
        role, op, lo, hi = c.get("analysis_role"), c.get("acceptance_operator"), c.get("lower"), c.get("upper")
        if role in ("DOE_RESPONSE", "MONITOR_ONLY") and not op:
            out.append(_decide(pkg, "RB03", "CR001", cqa=cid))
        if (op == "LE" and hi is None) or (op == "GE" and lo is None) or (op == "BETWEEN" and (lo is None or hi is None)) \
                or (op == "TARGET_TOL" and (c.get("target") is None or c.get("target_tolerance") is None)):
            out.append(_decide(pkg, "RB03", "CR002", cqa=cid))
        if lo is not None and hi is not None and lo > hi:
            out.append(_decide(pkg, "RB03", "CR003", cqa=cid))
        if role == "DOE_RESPONSE" and c.get("criterion_type") == "RELATIVE_ONLY":
            out.append(_decide(pkg, "RB03", "CR004", cqa=cid))
        if role == "DOE_RESPONSE" and (not c.get("test_method_id") or not c.get("unit")):
            out.append(_decide(pkg, "RB03", "CR005", cqa=cid))
        if cid == "CQA_DISSOLUTION" and role == "DOE_RESPONSE" and c.get("summary_definition") in (None, "", "PER_TIMEPOINT"):
            out.append(_decide(pkg, "RB03", "CR006", cqa=cid))
        if role == "DOE_RESPONSE" and (not c.get("test_method_id") or not c.get("test_method_version") or not c.get("summary_definition")):
            out.append(_decide(pkg, "RB03", "CE012", cqa=cid))
        if role == "DOE_RESPONSE" and not c.get("replicate_policy"):
            out.append(_decide(pkg, "RB03", "CR008", cqa=cid))
        if role == "DOE_RESPONSE" and c.get("practical_effect_threshold") is None:
            out.append(_decide(pkg, "RB03", "CR007", cqa=cid))
        if c.get("criterion_source") == "PROJECT_TARGET" and not c.get("evidence_refs"):
            out.append(_decide(pkg, "RB03", "CR010", cqa=cid))
    if sum(c.get("analysis_role") == "DOE_RESPONSE" for c in cqas.values()) > int(pkg.policy["limits"]["max_selected_doe_responses"]):
        out.append(_decide(pkg, "RB03", "CE011"))
    return out


# ── RB06 요인 선택 ─────────────────────────────────────────────────────────────
def factor_selection(pkg: DoePackage, selected: List[Dict[str, Any]], unselected_high_risk: List[Dict[str, Any]]) -> List[Decision]:
    out: List[Decision] = []
    if len(selected) > int(pkg.policy["limits"]["max_rsm_factors"]):
        out.append(_decide(pkg, "RB06", "FS013"))
    for f in selected:
        if not f.get("linked_cqa_ids"):
            out.append(_decide(pkg, "RB06", "FS014", factor=f.get("factor_id")))
    for f in unselected_high_risk:
        if f.get("fixed_value") is None or not f.get("fixed_rationale"):
            out.append(_decide(pkg, "RB06", "FS015", factor=f.get("key")))
    return out


# ── RB12 결과 품질 ─────────────────────────────────────────────────────────────
def result_quality(pkg: DoePackage, rows: List[Dict[str, Any]], *, study_type: str, plan_locked: bool) -> List[Decision]:
    out: List[Decision] = []
    for r in rows:
        rid = r.get("run_id")
        if not r.get("batch_id"):
            out.append(_decide(pkg, "RB12", "RQ001", run=rid))
        if not r.get("test_method_version"):
            out.append(_decide(pkg, "RB12", "RQ003", run=rid))
        if r.get("human_verification_status") != "CONFIRMED":
            out.append(_decide(pkg, "RB12", "RQ006", run=rid))
        if r.get("replicate_independence") in (None, "UNKNOWN"):
            out.append(_decide(pkg, "RB12", "RQ008", run=rid))
        if not evidence_permits(pkg, r.get("evidence_status"), "MODEL_FIT", study_type=study_type, plan_locked=plan_locked):
            out.append(_decide(pkg, "RB12", "RQ010", run=rid, evidence=r.get("evidence_status")))
    versions = {r.get("test_method_version") for r in rows if r.get("test_method_version")}
    if len(versions) > 1:
        out.append(_decide(pkg, "RB12", "RQ013", versions=sorted(versions)))
    return out
