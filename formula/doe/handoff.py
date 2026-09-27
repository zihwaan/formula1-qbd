"""D0 불변 handoff(명세 §7.1) — 상류 후보 또는 CBD 문헌 픽스처에서 만든다. 성분값은 전부 REFERENCE_PROTOTYPE."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ROUTE_ALIASES = {"direct_compression": "direct_compression", "direct": "direct_compression", "dc": "direct_compression",
                 "직접타정": "direct_compression"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(h: Dict[str, Any]) -> str:
    core = {"candidate": f"{h['candidate_id']}@{h['candidate_version']}",
            "ingredients": sorted((i["material_id"], i.get("function"), i.get("percent_w_w"), i.get("material_grade")) for i in h["ingredients"]),
            "route": h.get("process_route_id"), "fixed": sorted((p["name"], str(p.get("value"))) for p in h.get("fixed_parameters", []))}
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, default=str, sort_keys=True).encode()).hexdigest()


def route_of(process: str) -> str:
    p = (process or "").strip().lower()
    for k, v in ROUTE_ALIASES.items():
        if k in p:
            return v
    return p or "unknown"


def _ing(material: str, function: str, mg: Optional[float], pct: Optional[float], grade: Optional[str], critical: bool,
         evidence_ref: Optional[str]) -> Dict[str, Any]:
    return {"material_id": material, "material_grade": grade, "function": function, "amount_mg": mg, "percent_w_w": pct,
            "unit": "mg" if mg is not None else None, "value_role": "REFERENCE_PROTOTYPE", "is_critical": critical,
            "evidence_ref": evidence_ref}


def from_fixture(fx: Dict[str, Any], actor: str) -> Dict[str, Any]:
    """CBD ODT 문헌 재현 — 값은 모두 논문 표(Table 1 · Methods 2.1·2.2.1)에서 온다."""
    pr = fx["process"]
    ings = [_ing(i["material"], i["function"], i["mg"], i["pct"], i.get("grade"), i["function"] == "API",
                 f"{fx['doi']} {fx['prototype_table']}") for i in fx["prototype"]]
    h = {"handoff_id": "HO-CBD-ODT-MONTON2026-v1", "project_id": "LITERATURE_REPLAY", "candidate_id": "CBD_ODT_PROTOTYPE",
         "candidate_version": 1, "dosage_form": "odt", "cqa_dosage_form": "tablet", "target_strength_mg": 10,
         "unit_weight_mg": 250, "batch_scale": pr["batch_scale"], "ingredients": ings,
         "process_route_id": route_of(pr["route"]), "process_steps": [{"order": k + 1, "text": s} for k, s in enumerate(pr["steps_as_reported"])],
         "equipment_id": pr["equipment"], "fixed_parameters": [dict(p) for p in pr["fixed_parameters"]],
         "unresolved_fields": [], "rule_verdicts": [], "qtpp_snapshot_id": f"QTPP-{fx['doi']}-Table3",
         "evidence_snapshot_id": f"EV-{fx['pmcid']}", "source": {"citation": fx["citation"], "doi": fx["doi"], "pmcid": fx["pmcid"]},
         "title": "CBD 구강붕해정 — Monton 2026 문헌 재현", "created_by": actor, "created_at": now()}
    h["formulation_fingerprint"] = fingerprint(h)
    return h


def from_candidate(recipe: Dict[str, Any], spec: Dict[str, Any], verdicts: List[Dict[str, Any]], *, run_id: str, actor: str) -> Dict[str, Any]:
    """① 후보 탐색의 통과 후보 → handoff. 모르는 값(등급·설비·배치 규모)은 비워 두고 RB01이 요청하게 한다."""
    total = sum(float(i.get("amount_mg") or 0) for i in recipe["ingredients"]) or None
    ings = []
    for i in recipe["ingredients"]:
        pct = i.get("percent")
        if pct is None and total and i.get("amount_mg") is not None:
            pct = round(100 * float(i["amount_mg"]) / total, 4)
        ings.append(_ing(i["name"], i.get("role") or "other", i.get("amount_mg"), pct, None, i.get("role") == "api",
                         f"candidate {recipe['candidate_id']}"))
    version = int(recipe.get("version") or 1)
    form = spec.get("dosage_form") or "tablet"
    h = {"handoff_id": f"HO-{recipe['candidate_id']}-v{version}", "project_id": run_id, "candidate_id": recipe["candidate_id"],
         "candidate_version": version, "dosage_form": form, "cqa_dosage_form": form if form in ("tablet", "dispersible_tablet") else "tablet",
         "target_strength_mg": next((i.get("amount_mg") for i in recipe["ingredients"] if i.get("role") == "api"), None),
         "unit_weight_mg": total, "batch_scale": None, "ingredients": ings, "process_route_id": route_of(recipe.get("process", "")),
         "process_steps": [{"order": k + 1, "text": s} for k, s in enumerate(recipe.get("process_steps") or [])],
         "equipment_id": None, "fixed_parameters": [], "unresolved_fields": ["equipment_id", "batch_scale", "material_grade(API)"],
         "rule_verdicts": [{"rule_id": v.get("rule_id"), "status": "hard_fail" if str(v.get("status", "")).lower() in ("hard_fail", "fail") else str(v.get("status", "")).lower(),
                            "resolved": False} for v in verdicts],
         "qtpp_snapshot_id": f"QTPP-{run_id}", "evidence_snapshot_id": f"EV-{run_id}-{recipe['candidate_id']}",
         "source": {"run_id": run_id, "api_name": recipe.get("api_name"), "strategy": recipe.get("strategy")},
         "title": f"{recipe.get('api_name') or 'API'} · {recipe.get('strategy') or ''} ({recipe['candidate_id']}@{version})",
         "created_by": actor, "created_at": now()}
    h["formulation_fingerprint"] = fingerprint(h)
    return h
