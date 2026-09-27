#!/usr/bin/env python3
from __future__ import annotations
import csv, sys, re
from pathlib import Path
import yaml

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
errors = []
warnings = []

def fail(msg): errors.append(msg)
def warn(msg): warnings.append(msg)

manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))
rulebooks = manifest.get("rulebooks", [])
masters = manifest.get("reference_masters", [])
if len(rulebooks) != 18: fail(f"expected 18 rulebooks, found {len(rulebooks)}")
if len(masters) != 7: fail(f"expected 7 masters, found {len(masters)}")
if manifest.get("global_config", {}).get("counted_as_rulebook") is not False: fail("RB00 must not count as a rulebook")

listed = [root / x["file"] for x in rulebooks + masters]
for p in listed:
    if not p.exists(): fail(f"missing manifest file: {p.relative_to(root)}")

for p in root.rglob("*.csv"):
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not reader.fieldnames: fail(f"empty header: {p.relative_to(root)}"); continue
        id_candidates = [c for c in ("rule_id", "mapping_id", "failure_mode_id", "pattern_id", "test_id", "reason_code", "material_id", "equipment_id", "test_method_id", "evidence_status", "source_id") if c in reader.fieldnames]
        if id_candidates:
            key = id_candidates[0]
            vals = [r.get(key, "").strip() for r in rows]
            if any(not v for v in vals): fail(f"blank {key}: {p.relative_to(root)}")
            if key not in ("equipment_id",) and len(vals) != len(set(vals)): fail(f"duplicate {key}: {p.relative_to(root)}")
        if "validation_status" in reader.fieldnames:
            bad = [r for r in rows if r.get("validation_status") != "DRAFT_EXPERT_REVIEW_REQUIRED"]
            if bad: fail(f"non-draft validation status in {p.relative_to(root)}")
        if "enforcement_enabled" in reader.fieldnames:
            bad = [r for r in rows if r.get("enforcement_enabled", "").lower() != "false"]
            if bad: fail(f"enforcement enabled in draft file {p.relative_to(root)}")

policy = yaml.safe_load((root / "config/development_policy.yaml").read_text(encoding="utf-8"))
if policy["limits"]["max_selected_doe_responses"] != 4: fail("max DOE responses must be 4")
if policy["limits"]["max_rsm_factors"] != 3: fail("max RSM factors must be 3")
if policy.get("enforcement_enabled") is not False: fail("draft config enforcement must be false")

test_path = root / "masters/06_confirmation_test_master.csv"
with test_path.open("r", encoding="utf-8-sig", newline="") as f:
    test_rows = list(csv.DictReader(f))
test_ids = {r["test_id"] for r in test_rows}
ntests = len(test_rows)
expected_tests = next(int(m["records"]) for m in masters if m["id"] == "M06")
if ntests != expected_tests: fail(f"expected {expected_tests} confirmation tests from manifest, found {ntests}")
if ntests < 66: fail(f"confirmation-test registry regressed below inherited 66 records: {ntests}")

with (root / "rulebooks/18_labloop_backtrack_rules.csv").open("r", encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        for tid in filter(None, row["confirmation_test_ids"].split(";")):
            if tid not in test_ids: fail(f"RB18 references missing confirmation test: {tid}")

with (root / "sources/source_registry.csv").open("r", encoding="utf-8-sig", newline="") as f:
    source_ids = {r["source_id"] for r in csv.DictReader(f)}
for p in root.rglob("*.csv"):
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            for sid in filter(None, (row.get("source_ids") or "").split(";")):
                sid = sid.strip()
                if sid.startswith("SRC_") and sid not in source_ids:
                    fail(f"unregistered source ID {sid} in {p.relative_to(root)}")

with (root / "masters/07_reason_code_catalog.csv").open("r", encoding="utf-8-sig", newline="") as f:
    reason_codes = {r["reason_code"] for r in csv.DictReader(f)}
for p in (root / "rulebooks").glob("*.csv"):
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("result_code") or row.get("reason_code") or "").strip()
            if code and code not in reason_codes:
                fail(f"unregistered reason code {code} in {p.relative_to(root)}")

forbidden = {"CONTROL_STRATEGY", "PPQ_READY", "COMMERCIAL_RELEASE"}
for p in listed + [root / "config/development_policy.yaml"]:
    text = p.read_text(encoding="utf-8-sig")
    # The config intentionally declares forbidden states; ignore those declarations.
    if p.name != "development_policy.yaml":
        hit = forbidden.intersection(set(re.findall(r"[A-Z][A-Z0-9_]+", text)))
        if hit: fail(f"forbidden workflow states {sorted(hit)} in {p.relative_to(root)}")

print(f"Rulebooks: {len(rulebooks)}/18")
print(f"Reference masters: {len(masters)}/7")
print(f"Confirmation tests: {ntests}/{expected_tests}")
print(f"Registered sources: {len(source_ids)}")
print(f"Registered reason codes: {len(reason_codes)}")
print(f"Warnings: {len(warnings)}")
for w in warnings: print(f"WARNING: {w}")
print(f"Errors: {len(errors)}")
for e in errors: print(f"ERROR: {e}")
print("RESULT: PASS" if not errors else "RESULT: FAIL")
sys.exit(1 if errors else 0)
