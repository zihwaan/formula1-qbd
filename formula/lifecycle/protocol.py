"""검증된 템플릿 기반 프로토콜 컴파일러와 결정론 validator."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

import yaml


class ProtocolCompiler:
    def __init__(self, base_dir: Path):
        self.templates = Path(base_dir) / "formula" / "protocol" / "templates"

    def compile(self, candidate: Dict[str, Any], specs: List[Dict[str, Any]],
                batch_size: int = 100) -> Dict[str, Any]:
        recipe = candidate.get("recipe") or candidate
        process = str(recipe.get("process") or "direct_compression").lower()
        template_name = "wet_granulation_aqueous" if "wet" in process else "direct_compression"
        with (self.templates / f"{template_name}.yaml").open(encoding="utf-8") as handle:
            template = yaml.safe_load(handle)
        ingredients = []
        unresolved = []
        known_unit_amounts: List[float] = []
        for ing in recipe.get("ingredients", []):
            amount = ing.get("amount_mg")
            if amount is None and ing.get("percent") is not None:
                amount = float(ing["percent"]) * float(template["target_unit_weight_mg"]) / 100
            if amount is None:
                unresolved.append(f"ingredient_amount:{ing.get('name', 'unknown')}")
            else:
                known_unit_amounts.append(float(amount))
            ingredients.append({**ing, "batch_amount_mg": None if amount is None else amount * batch_size})
        target_weight = (sum(known_unit_amounts) if not unresolved and known_unit_amounts
                         else float(template["target_unit_weight_mg"]))
        return {
            "protocol_id": f"prot-{uuid.uuid4().hex[:12]}",
            "version": 1,
            "candidate_id": candidate.get("candidate_id") or recipe.get("candidate_id"),
            "candidate_version": int(candidate.get("version", 1)),
            "template_id": template["template_id"],
            "template_version": template["version"],
            "batch_size_units": batch_size,
            "target_unit_weight_mg": target_weight,
            "ingredients": ingredients,
            "steps": template["steps"],
            "equipment": template["equipment"],
            "cqa_specs": specs,
            "unresolved_slots": unresolved,
            "validation": {},
            "status": "DRAFT",
            "created_at": time.time(),
        }


class ProtocolValidator:
    def validate(self, protocol: Dict[str, Any]) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        target = float(protocol.get("target_unit_weight_mg") or 0)
        known = [i.get("amount_mg") for i in protocol.get("ingredients", [])
                 if i.get("amount_mg") is not None]
        if protocol.get("unresolved_slots"):
            errors.append("성분별 양이 모두 확정되지 않았습니다.")
        if known and target and abs(sum(float(v) for v in known) - target) > max(0.5, target * .01):
            errors.append(f"정제당 질량수지가 맞지 않습니다: {sum(known):g} mg / 목표 {target:g} mg")
        if not protocol.get("steps"):
            errors.append("필수 공정 단계가 없습니다.")
        if not protocol.get("cqa_specs"):
            errors.append("후보별 CQA 규격이 없습니다.")
        for step in protocol.get("steps", []):
            if step.get("critical") and not step.get("source_ref"):
                errors.append(f"중요 공정 단계 '{step.get('name')}'에 출처가 없습니다.")
        status = "BLOCKED" if errors else "READY_FOR_REVIEW"
        return {"status": status, "errors": errors, "warnings": warnings,
                "checked": ["mass_balance", "units", "required_steps", "provenance", "cqa_specs"]}
