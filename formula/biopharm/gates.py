"""BCS/DCS·고체상·가용화 전략·ASD 공정 게이트 — Gate 3A/3B/4/4B.

네 CSV 모두 같은 모양이다: `condition_expression`이 참이면 `assign`(세미콜론으로 묶은
key=value 여러 개)을 ctx에 쓴다. 판정(Verdict)을 내는 게 아니라 **파생값 산출과 신호
표시**가 목적이라 배합금기 룰북의 8대 전략과는 다른 스키마다 — action(ALLOW/
REVIEWER_FLAG)에는 반려 권한이 없다. 다음 단계(전략 채점·심사관 소집·데이터 요청)가
참조하는 신호일 뿐이다.

실행 순서가 과학적 의미를 갖는다 — derived_quantities로 tm_c·logs_* 등을 먼저 채운
뒤, G3A(BCS/DCS) → G3B(고체상, advisory) → G4(가용화 신호) → G4B(ASD 공정) 순서로
돈다. G4는 G3A의 dcs_subclass를 읽고, G4B는 G4의 sig_enabling_required를 읽는다.
"""

from __future__ import annotations

import csv as csv_mod
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from formula.checkers.applies_when import evaluate

GATE_FILES = [
    "database/04_biopharmaceutics/gate_3a_biopharm_class.csv",
    "database/04_biopharmaceutics/gate_3b_solid_form.csv",
    "database/04_biopharmaceutics/gate_4_enabling_strategy.csv",
    "database/04_biopharmaceutics/gate_4b_asd_process.csv",
]


class GateSignal(TypedDict):
    gate: str
    rule_id: str
    condition: str
    assigned: Dict[str, Any]
    action: str
    rationale: str
    citation: str


@lru_cache(maxsize=16)
def _rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv_mod.DictReader(handle))


def _coerce(raw: str) -> Any:
    text = raw.strip()
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def evaluate_gate(csv_path: Path, ctx: Dict[str, Any]) -> List[GateSignal]:
    """한 게이트 CSV의 행을 순서대로 평가하고 ctx를 제자리에서 채운다."""
    fired: List[GateSignal] = []
    gate_name = Path(csv_path).stem
    for row in _rows(Path(csv_path)):
        expression = (row.get("condition_expression") or "").strip()
        if not evaluate(expression, ctx):
            continue
        assigned: Dict[str, Any] = {}
        for pair in str(row.get("assign") or "").split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            key, _, value = pair.partition("=")
            key = key.strip()
            if key:
                # "$이름"은 ctx의 다른 값을 그대로 옮긴다(예: 문헌 표의 용해도 분류 → 잠정 판정)
                v = value.strip()
                ctx[key] = assigned[key] = ctx.get(v[1:]) if v.startswith("$") else _coerce(value)
        fired.append(GateSignal(
            gate=gate_name, rule_id=str(row.get("rule_id") or ""), condition=expression,
            assigned=assigned, action=str(row.get("action") or "ALLOW"),
            rationale=str(row.get("rationale") or ""),
            citation=str(row.get("source_citation") or ""),
        ))
    return fired


def run_biopharm_gates(ctx: Dict[str, Any], base_dir: Path) -> List[GateSignal]:
    """G3A → G3B → G4 → G4B를 정해진 순서로 돌린다. ctx를 제자리에서 갱신한다."""
    fired: List[GateSignal] = []
    for relative in GATE_FILES:
        fired.extend(evaluate_gate(Path(base_dir) / relative, ctx))
    return fired
