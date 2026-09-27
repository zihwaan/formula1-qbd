"""D1 CQA 표 — RB02(제형 → 템플릿·요구·기본 역할) + v6.1 cqa_templates(미이관) + M01 시험법.

규격값은 만들지 않는다(명세 §3.2) — 템플릿 기본값이 비어 있으면 비워 두고 연구자가 출처와 함께 입력한다.
is_cqa(제품에서 중요한가)와 analysis_role(이번 DoE에서 모델링하나)은 별개 축이다.
"""
from __future__ import annotations

import csv
from typing import Any, Dict, List

from formula.doe.package import DoePackage

ANALYSIS_ROLES = ("DOE_RESPONSE", "MONITOR_ONLY", "NOT_APPLICABLE")
OPERATORS = ("LE", "GE", "BETWEEN", "TARGET_TOL", "PASS_FAIL")


def templates(pkg: DoePackage) -> Dict[str, Dict[str, str]]:
    path = pkg.config.rulebook_root.parent / "masters" / "cqa_templates.csv"      # v6.1 (NOT_MIGRATED — 이관 대조표)
    with path.open(encoding="utf-8-sig", newline="") as h:
        return {r["cqa_template_id"]: r for r in csv.DictReader(h)}


def _num(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except ValueError:
        return None


def _applies(expr: str, ctx: Dict[str, Any]) -> bool:
    """RB02 condition_expression — 알려진 몇 형태만 결정론으로 읽는다. 모르는 식은 참으로 두고 연구자가 역할을 정한다."""
    e = (expr or "").strip()
    if e in ("", "True"):
        return True
    api = ctx.get("api", {})
    try:
        if e == "api.dose_mg < 25 or api.pct_w_w < 25":
            return (api.get("dose_mg") or 1e9) < 25 or (api.get("pct_w_w") or 1e9) < 25
        if e == "coating == 'none'":
            return ctx.get("coating", "none") == "none"
        if e.startswith("'hygroscopic' in api.flags"):
            return "hygroscopic" in (api.get("flags") or [])
        if e.startswith("api.bcs_class in"):
            return api.get("bcs_class") in ("II", "IV")
    except TypeError:
        return False
    return True


def draft(pkg: DoePackage, handoff: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    form = handoff.get("cqa_dosage_form") or "tablet"
    api = next((i for i in handoff["ingredients"] if i.get("is_critical")), {})
    ctx = {"api": {"dose_mg": api.get("amount_mg"), "pct_w_w": api.get("percent_w_w"), "flags": [], "bcs_class": None}, "coating": "none"}
    rows = pkg.rows("RB02")
    forms = {form}
    for r in rows:                                   # 분산정은 정제를 상속
        if r["dosage_form"] == form and r.get("inherits_from"):
            forms.add(r["inherits_from"])
    tpl = templates(pkg)
    methods = {}
    for m in pkg.masters.get("M01", []):
        for t in (m.get("measures_cqa_template_ids") or "").split(";"):
            if t.strip():
                methods.setdefault(t.strip(), m)
    out: Dict[str, Dict[str, Any]] = {}
    for r in sorted(rows, key=lambda r: int(r.get("merge_priority") or 0)):
        if r["dosage_form"] not in forms and r["dosage_form"] != "*":
            continue
        if not _applies(r.get("condition_expression", ""), ctx):
            continue
        tid = r["cqa_template_id"]
        t = tpl.get(tid, {})
        m = methods.get(tid, {})
        prev = out.get(tid)
        role = r.get("default_role") or "MONITOR_ONLY"
        if prev and prev["analysis_role"] == "DOE_RESPONSE":
            role = "DOE_RESPONSE"
        out[tid] = {"cqa_id": tid, "name": t.get("name_ko") or tid, "is_cqa": r.get("requirement") == "MANDATORY",
                    "analysis_role": role, "requirement": r.get("requirement"), "mapping_ids": (prev or {}).get("mapping_ids", []) + [r["mapping_id"]],
                    "acceptance_operator": t.get("default_acceptance_operator") if t.get("default_acceptance_operator") not in ("", "None") else None,
                    "lower": _num(t.get("default_lower")), "upper": _num(t.get("default_upper")), "target": None, "target_tolerance": None,
                    "unit": t.get("unit") or None, "quantity_kind": t.get("quantity_kind") or None,
                    "test_method_id": m.get("test_method_id") or (t.get("default_test_method_id") if t.get("default_test_method_id") not in ("", "None") else None),
                    "test_method_version": None, "summary_definition": m.get("summary_function") or None, "replicate_policy": None,
                    "practical_effect_threshold": None, "criterion_source": None, "rationale": "", "evidence_refs": [],
                    "version": 1, "approval_status": "DRAFT"}
    return out


EDITABLE = ("name", "is_cqa", "analysis_role", "acceptance_operator", "lower", "upper", "target", "target_tolerance", "unit",
            "test_method_id", "test_method_version", "summary_definition", "replicate_policy", "practical_effect_threshold",
            "criterion_source", "rationale", "evidence_refs", "response_key")


def apply_edits(cqas: Dict[str, Dict[str, Any]], edits: List[Dict[str, Any]]) -> List[str]:
    changed = []
    for e in edits:
        cid = e.get("cqa_id")
        if not cid:
            continue
        c = cqas.setdefault(cid, {"cqa_id": cid, "name": e.get("name") or cid, "is_cqa": False, "analysis_role": "MONITOR_ONLY",
                                  "version": 0, "approval_status": "DRAFT", "evidence_refs": [], "mapping_ids": []})
        before = {k: c.get(k) for k in EDITABLE}
        for k in EDITABLE:
            if k in e:
                v = e[k]
                if k in ("lower", "upper", "target", "target_tolerance", "practical_effect_threshold"):
                    v = _num(v)
                if k == "analysis_role" and v not in ANALYSIS_ROLES:
                    continue
                if k == "acceptance_operator" and v not in OPERATORS + (None,):
                    continue
                c[k] = v
        if {k: c.get(k) for k in EDITABLE} != before:
            c["version"] = int(c.get("version") or 0) + 1          # 덮지 않고 버전을 올린다
            c["approval_status"] = "DRAFT"
            changed.append(cid)
    return changed
