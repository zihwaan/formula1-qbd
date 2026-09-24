import csv, os
import pathlib
ROOT = str(pathlib.Path(__file__).resolve().parents[2] / "database" / "07_doe")
RULE_COLS = ["rule_id","rulebook_id","version","priority","scope","stage","when_expression",
 "required_inputs","missing_value_action","gate_effect","result_code","next_state","message_ko",
 "implementation_hint","human_override","override_approver_role","rationale","source_ids",
 "governance_class","validation_status","owner","effective_from"]
DEFAULTS = dict(version="1", validation_status="DRAFT_PENDING_REVIEW", owner="formula1-doe",
                effective_from="2026-09-23")

def R(rid, pri, scope, stage, when, inputs, missing, effect, code, nxt, msg, hint, override,
      approver, rationale, sources, gclass):
    return dict(rule_id=rid, priority=str(pri), scope=scope, stage=stage, when_expression=when,
        required_inputs=inputs, missing_value_action=missing, gate_effect=effect, result_code=code,
        next_state=nxt, message_ko=msg, implementation_hint=hint, human_override=override,
        override_approver_role=approver, rationale=rationale, source_ids=sources,
        governance_class=gclass)

def write_rules(folder, name, rulebook_id, rows):
    path = os.path.join(ROOT, folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RULE_COLS)
        w.writeheader()
        for r in rows:
            row = {**DEFAULTS, **r, "rulebook_id": rulebook_id}
            w.writerow(row)
    return path

PROV = ["source_ids","governance_class","validation_status","version","effective_from"]
def write_table(folder, name, cols, rows, gclass):
    path = os.path.join(ROOT, folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    allc = cols + [c for c in PROV if c not in cols]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=allc)
        w.writeheader()
        for r in rows:
            d = dict(zip(cols, r)) if isinstance(r, (list, tuple)) else dict(r)
            d.setdefault("governance_class", gclass)
            d.setdefault("validation_status", "DRAFT_PENDING_REVIEW")
            d.setdefault("version", "1")
            d.setdefault("effective_from", "2026-09-23")
            w.writerow(d)
    return path

# governance classes
SCI = "SCIENTIFIC"             # 과학적 근거 필요, 원문 대조 대상
COMP = "COMPENDIAL"            # 약전·가이드라인 수치
STAT = "STATISTICAL_METHOD"    # 통계 방법론
POL = "PROJECT_POLICY"         # 명세(v6)에서 파생된 운영 정책
