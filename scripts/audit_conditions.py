"""조건식 전수검사 — 데이터(CSV·manifest)의 모든 조건식이 참조하는 변수 이름이 **실제로 채워지는 이름인지** 확인한다.

    python scripts/audit_conditions.py            # 0 = 문제 없음, 1 = 죽은 이름 발견

CSV 조건식은 모르는 이름을 만나면 NameError → fail-closed(미발동)로 조용히 죽는다. `tm_c is None` 류(seed.py)와
`ionizable`(2026-09-26 발견 — G3B001·DRQ_PKA가 한 번도 켜지지 않았다)가 이 모양의 사고였다. 이 검사는 그 부류를
사람 눈이 아니라 대조로 잡는다.
"""
from __future__ import annotations

import ast
import csv
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formula.biopharm.seed import known_keys  # noqa: E402

# 코드가 조건식 문맥에 직접 넣는 이름(spec_context · 게이트 · 계획 · 되돌림 · 소집 신호 · 요청 평가)
CODE_KEYS = {
    "api_name", "bcs_class", "target_patient", "target_population", "dosage_form", "is_pediatric",
    "api_functional_groups", "measured_keys", "property_keys", "true", "false", "True", "False", "None", "always",
    "process", "packaging", "packaging_traits", "candidate_id", "selected_route", "recommended_routes",
    "excluded_routes", "routes_provisional", "flow_character", "flow_character_normalized",
    "strategy", "family", "rulebook_id", "status", "rule_id", "measurement_id", "result",
    "regulatory_narrative_needed", "novel_combination_not_in_rulebook", "coverage_gap_present",
    "enabling_candidates_present", "particle_size_candidates_present", "asd_candidates_present",
    "salt_stability_watch", "flag", "prop", "has_measured", "ingredient", "role", "abs", "min", "max", "len",
    "any", "all", "round", "is_salt", "bcs_source", "logs_status",
    # 헬퍼 함수 — triggers.evaluate_triggers(has_flag·has_step), strategy_planner(route_index)
    "has_flag", "has_step", "route_index",
    # pairwise required_conditions — 모르는 이름은 None으로 채워 평가한다(strategies._scope_with_unknowns)
    "lubricant_blend_time_min",
}


def names(expr: str) -> set:
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        return {"<SyntaxError>"}
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.add(n.id)
    attr_roots = {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    return out | attr_roots


def rows(rel):
    with (ROOT / rel).open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def audit():
    """(검사한 조건식 수, [(위치, 모르는 이름, 식)])."""
    known = set(known_keys(ROOT)) | CODE_KEYS
    # 실험 입력 허용목록·측정 필드·물성 플래그 키도 문맥에 들어간다
    known |= {r["field_key"] for r in rows("database/reference/measurement_output_fields.csv")}
    exp = yaml.safe_load((ROOT / "config/experimental_inputs.yaml").read_text(encoding="utf-8"))
    for g in exp.get("groups", []):
        known |= {f["key"] for f in g.get("fields", []) or []}
    # RDKit 기술자(with_profile이 measured_params에 합친다)
    from formula.chem.profile import build_profile
    known |= set(build_profile("Ibuprofen", base_dir=ROOT, render=False).descriptors)
    # intake가 쓰는 물성 플래그 — spec_context가 기본값 False를 깐다
    from formula.checkers.applies_when import PROPERTY_FLAG_DEFAULTS
    known |= set(PROPERTY_FLAG_DEFAULTS)
    # 구조 플래그 이름(flag() 헬퍼 인자나 has_* 로 참조)
    known |= {r["flag_name"] for r in rows("database/00_master/structural_flags_registry.csv")}

    sources = []
    for rel, cols in [
        ("database/04_biopharmaceutics/gate_3a_biopharm_class.csv", ["condition_expression"]),
        ("database/04_biopharmaceutics/gate_3b_solid_form.csv", ["condition_expression"]),
        ("database/04_biopharmaceutics/gate_4_enabling_strategy.csv", ["condition_expression"]),
        ("database/04_biopharmaceutics/gate_4b_asd_process.csv", ["condition_expression"]),
        ("database/reference/data_request_triggers.csv", ["condition_expression", "satisfied_when"]),
        ("database/06_config/strategy_families.csv", ["applies_when", "score_expression"]),
        ("database/06_config/backtrack_transitions.csv", ["match_expression"]),
        ("database/06_config/reviewer_registry.csv", ["summon_condition"]),
        ("database/02_incompatibility/incompatibility_1to1.csv", ["required_conditions"]),
    ]:
        for r in rows(rel):
            rid = next(iter(r.values()))
            for c in cols:
                expr = (r.get(c) or "").strip()
                if expr:
                    sources.append((f"{Path(rel).name}:{rid}:{c}", expr))
    for e in yaml.safe_load((ROOT / "config/rulebook_manifest.yaml").read_text(encoding="utf-8")):
        if e.get("applies_when"):
            sources.append((f"manifest:{e['id']}:applies_when", str(e["applies_when"])))

    bad = []
    for where, expr in sources:
        unknown = sorted(n for n in names(expr) if n not in known)
        if unknown:
            bad.append((where, unknown, expr[:110]))
    return len(sources), bad


def main() -> int:
    n, bad = audit()
    for where, unknown, expr in bad:
        print(f"DEAD? {where}: {unknown}  ← {expr}")
    print(f"{n} expressions checked, {len(bad)} with unknown names")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
