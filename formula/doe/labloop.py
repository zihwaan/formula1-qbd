"""D12 Lab-in-the-loop — M06 adapter(INSTALLATION §9.3)와 RB18 실패 패턴 → 판별시험 후보.

기존 formula/feedback/labloop.py는 database/reference/confirmation_test_master.csv(66)를 그대로 쓴다. 여기 adapter는 v7 M06(90)을
같은 canonical 계약으로 돌려준다 — 표시명은 test_name_ko가 없으면 test_name_en. LLM은 PROPOSE_ONLY 시험을 '제안'만 할 수 있다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from formula.doe.package import DoePackage


@dataclass(frozen=True)
class ConfirmationTestRecord:
    test_id: str
    display_name: str
    test_category: str
    test_design: str
    output_variable: str
    acceptance_logic: str
    unit: str
    allowed_for_agent: str
    source_reference: str
    source_url: str


def confirmation_tests(pkg: DoePackage) -> Dict[str, ConfirmationTestRecord]:
    out = {}
    for tid, r in pkg.confirmation_tests.items():
        out[tid] = ConfirmationTestRecord(tid, (r.get("test_name_ko") or "").strip() or r.get("test_name_en", tid), r.get("test_category", ""),
                                          r.get("test_design", ""), r.get("output_variable", ""), r.get("acceptance_logic", ""),
                                          r.get("unit", ""), r.get("allowed_for_agent", ""), r.get("source_reference", ""),
                                          r.get("source_url", ""))
    return out


def suggest(pkg: DoePackage, trigger: str) -> Optional[Dict[str, Any]]:
    """실패 trigger(= RB18 reason_code, 예: FEASIBILITY_BOUNDARY_FAILED) → 패턴 한 행과 그 판별시험(M06에 있는 것만)."""
    row = next((r for r in pkg.rows("RB18") if r["reason_code"] == trigger), None)
    if not row:
        return None
    tests = confirmation_tests(pkg)
    ids = [t.strip() for t in row.get("confirmation_test_ids", "").replace(",", ";").split(";") if t.strip()]
    return {"pattern_id": row["pattern_id"], "observed_pattern": row["observed_pattern"], "candidate_causes": row["candidate_causes"].split("|"),
            "backtrack_state": row["backtrack_state"], "reason_code": row["reason_code"], "notes": row.get("decision_notes_ko", ""),
            "tests": [asdict(tests[t]) for t in ids if t in tests]}
