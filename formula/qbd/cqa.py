"""CQA Mapper — 명세 v6.1 §3.2, 룰북 #6(qtpp_cqa_mapping)·#7(cqa_response_definition).

`template + rule engine + researcher approval`. 이 모듈은 제형·방출·API 요약에서 CQA 후보를
**제안**만 한다. 역할·규격을 확정하는 것은 연구자고, 제안이 계약이 될 수 있는지는 CR 규칙이
WAITING_CQA_APPROVAL에서 판정한다. 규격 수치를 지어내지 않는다 — 템플릿에 기본값이 없는
규격(함량 BETWEEN, 용출 Q 등)은 비워 두고, 비어 있으면 CR002가 막는다.
"""

from __future__ import annotations

import ast
import json
from typing import Any, Dict, List, Optional, Tuple

from formula.development.rules import DoeRulebook, Missing, evaluate

# criterion_basis(템플릿) → CQASpec.criterion_source
_SOURCE = {"COMPENDIAL": "PHARMACOPEIA", "COMPENDIAL_SUMMARY": "PHARMACOPEIA", "GUIDELINE": "REGULATORY",
           "MONOGRAPH": "PHARMACOPEIA", "MONOGRAPH_OR_PROJECT_TARGET": "PROJECT_TARGET",
           "PROJECT_TARGET": "PROJECT_TARGET"}


def _num(v: str) -> Optional[float]:
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def _forms(dosage_form: str, mapping: List[Dict[str, str]]) -> List[str]:
    """dosage_form과 그 상속 체인 (dispersible_tablet → tablet)."""
    chain, cur = [dosage_form], dosage_form
    inherits = {r["dosage_form"]: r["inherits_from"] for r in mapping if r["inherits_from"]}
    while cur in inherits and inherits[cur] not in chain:
        cur = inherits[cur]
        chain.append(cur)
    return chain


def method_index(rb: DoeRulebook) -> Dict[str, Dict[str, str]]:
    return {r["test_method_id"]: r for r in rb.master("test_method_registry")}


def draft_cqas(rb: DoeRulebook, handoff: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """(cqa_id → CQASpec dict, mapping trace). trace는 어느 매핑 행이 왜 적용·미적용됐는지 남긴다."""
    mapping = rb.master("qtpp_cqa_mapping_rules")
    templates = {r["cqa_template_id"]: r for r in rb.master("cqa_templates")}
    methods = method_index(rb)
    forms = _forms(handoff.get("dosage_form", "tablet"), mapping)
    ctx = {"api": handoff.get("api") or {}, "coating": handoff.get("coating", "none")}
    chosen: Dict[str, Tuple[int, Dict[str, str]]] = {}
    trace = []
    for row in mapping:
        if row["dosage_form"] not in forms and row["dosage_form"] != "*":
            continue
        if row["release_type"] not in ("*", handoff.get("release_type", "immediate_release")):
            continue
        tree = ast.parse(row["condition_expression"], mode="eval")
        try:
            hit = bool(evaluate(tree, ctx, rb.functions("demo"), rb.consts))
            status = "APPLIED" if hit else "NOT_APPLIED"
        except Missing as exc:
            hit, status = False, f"NOT_CHECKED (값 없음: {exc})"
        trace.append({"mapping_id": row["mapping_id"], "cqa_template_id": row["cqa_template_id"],
                      "condition": row["condition_expression"], "status": status})
        if not hit:
            continue
        prio = int(row["merge_priority"] or 0)
        cur = chosen.get(row["cqa_template_id"])
        if cur is None or prio > cur[0]:
            chosen[row["cqa_template_id"]] = (prio, row)
    out: Dict[str, Dict[str, Any]] = {}
    for tid, (_, row) in chosen.items():
        t = templates[tid]
        m = methods.get(t["default_test_method_id"])
        policy = None
        if m:
            policy = json.dumps({"sampling": json.loads(m["sampling_rule"] or "{}"),
                                 "summary": m["summary_function"]}, ensure_ascii=False)
        op = t["default_acceptance_operator"] or None
        out[tid] = {
            "cqa_id": tid, "version": 1, "name": t["name_ko"], "template_id": tid,
            "category": t["category"], "criticality": t["default_criticality"],
            "analysis_role": row["default_role"], "requirement": row["requirement"],
            "summary_definition": None if tid == "CQA_DISSOLUTION" else (m["summary_function"] if m else None),
            "quantity_kind": t["quantity_kind"], "acceptance_operator": op,
            "lower": _num(t["default_lower"]), "upper": _num(t["default_upper"]),
            "lower_inclusive": True, "upper_inclusive": True, "target": None, "target_tolerance": None,
            "compendial_procedure_ref": None, "unit": t["unit"] or None,
            "test_method_id": t["default_test_method_id"] or None,
            "test_method_version": m["version"] if m else None,
            "criterion_source": _SOURCE.get(t["criterion_basis"], "OTHER"),
            "criterion_type": "ABSOLUTE", "binding_status": "NOT_YET_KNOWN", "approval_status": "DRAFT",
            "override_decision_ids": [], "practical_effect_threshold": None, "replicate_policy": policy,
            "rationale_refs": t["source_ids"] or None, "criterion_note": t["criterion_note_ko"],
            "mapping_id": row["mapping_id"], "assumption": False,
            "has_registered_method": bool(m),
        }
    return out, trace


def cqa_context(c: Dict[str, Any], max_observed: Optional[float] = None) -> Dict[str, Any]:
    """룰 context `cqa` (manifest context_schema.entities.cqa)."""
    return {
        "id": c["cqa_id"], "template_id": c["template_id"], "category": c["category"],
        "analysis_role": c["analysis_role"], "requirement": c["requirement"],
        "acceptance_operator": c["acceptance_operator"], "lower": c["lower"], "upper": c["upper"],
        "target": c["target"], "target_tolerance": c["target_tolerance"],
        "lower_inclusive": c["lower_inclusive"], "upper_inclusive": c["upper_inclusive"],
        "unit": c["unit"], "test_method_id": c["test_method_id"],
        "test_method_version": c["test_method_version"], "criterion_source": c["criterion_source"],
        "criterion_type": c["criterion_type"], "summary_definition": c["summary_definition"],
        "practical_effect_threshold": c["practical_effect_threshold"],
        "replicate_policy": c["replicate_policy"], "rationale_refs": c["rationale_refs"],
        "has_registered_method": c.get("has_registered_method", False), "max_observed": max_observed,
    }


def criterion_text(c: Dict[str, Any]) -> str:
    op, lo, hi, unit = c.get("acceptance_operator"), c.get("lower"), c.get("upper"), c.get("unit") or ""
    if op == "LE":
        return f"≤ {hi} {unit}" if hi is not None else "상한 미정"
    if op == "GE":
        return f"≥ {lo} {unit}" if lo is not None else "하한 미정"
    if op == "BETWEEN":
        return f"{lo}–{hi} {unit}" if lo is not None and hi is not None else "범위 미정"
    if op == "TARGET_TOL":
        return f"{c.get('target')} ± {c.get('target_tolerance')} {unit}"
    if op == "PASS_FAIL":
        return "적합/부적합"
    return "판정 방식 미정"
