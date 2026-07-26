"""Wet-lab 결과 해석기 (결정론적).

검증을 통과한 처방이 실제 실험된 뒤, 연구원이 측정 데이터(용출률·경도·불순물 등)를
재입력한다(human-in-the-loop). 이 해석기는 각 QC 지표를 목표 규격과 대조해 '이탈' 여부를
계산하고, 이탈한 지표마다 실패 원인 해석과 재설계 방향을 규칙표에서 뽑아 붙인다.

핵심: 검증 계층과 동일하게 순수 계산만 한다 → 같은 실험 데이터면 항상 같은 해석(오차 0%).
규칙표(wetlab_feedback_rules.csv)의 각 행은 '목표 이탈(=실패) 조건'을 서술한다.
예: dissolution_30min_percent < 80  → 30분 용출률이 80% 미만이면 이탈.
"""

from __future__ import annotations

import operator as _op
from pathlib import Path
from typing import Callable, Dict

import pandas as pd

from formula.contracts import FeedbackFinding, FeedbackReport, WetLabResult

# CSV의 비교 연산자 문자열 → 실제 파이썬 연산자 (strategies.py와 동일 규약)
_OPERATORS: Dict[str, Callable[[float, float], bool]] = {
    ">": _op.gt,
    ">=": _op.ge,
    "<": _op.lt,
    "<=": _op.le,
    "==": _op.eq,
    "!=": _op.ne,
}


class WetLabInterpreter:
    """실험 결과 → 목표 대비 gap 해석 → reflection 루프 입력을 만든다."""

    def __init__(self, rules_path: str | Path):
        self.rules_path = Path(rules_path)
        self._rules = pd.read_csv(self.rules_path).fillna("")

    def interpret(self, result: WetLabResult) -> FeedbackReport:
        findings = []
        for row in self._rules.to_dict(orient="records"):
            metric = str(row.get("metric", "")).strip()
            op = str(row.get("operator", "")).strip()
            if metric not in result.measurements or op not in _OPERATORS:
                continue  # 이번 실험에서 측정되지 않은 지표거나 판정 불가 → 스킵
            try:
                target = float(row.get("target"))
            except (TypeError, ValueError):
                continue
            value = result.measurements[metric]
            off = _OPERATORS[op](value, target)  # 이탈(실패) 조건 충족 여부
            findings.append(
                FeedbackFinding(
                    metric=metric,
                    measured=value,
                    operator=op,
                    target=target,
                    off_target=off,
                    interpretation=str(row.get("interpretation", "")) if off else "",
                    suggested_revision=str(row.get("suggested_revision", "")) if off else "",
                    evidence={"unit": row.get("unit", ""), "rule": f"{metric} {op} {target}"},
                )
            )

        off_targets = [f for f in findings if f.off_target]
        if off_targets:
            summary = (
                f"{result.candidate_id}: {len(off_targets)}개 지표가 목표를 이탈 → 재설계 필요. "
                + "; ".join(f"{f.metric}={f.measured}({f.operator}{f.target})" for f in off_targets)
            )
        else:
            summary = f"{result.candidate_id}: 측정된 모든 QC 지표가 목표 규격 충족 ✅"

        return FeedbackReport(
            candidate_id=result.candidate_id,
            findings=findings,
            reflection_needed=bool(off_targets),
            summary=summary,
        )
