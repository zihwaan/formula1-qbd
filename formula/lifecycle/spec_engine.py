"""후보별 CQA 규격 생성·판정.

legacy 공통 표를 런타임 판정에 직접 재사용하지 않고, 설계가 끝나는 시점에 후보별 규격
스냅샷으로 복사한다. 이후 비교는 이 스냅샷만 사용하므로 다른 제품의 기준이 섞이지 않는다.
"""

from __future__ import annotations

import csv
import operator
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .models import CandidateSpec

OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt,
       ">=": operator.ge, "==": operator.eq, "!=": operator.ne}


class CandidateSpecEngine:
    def __init__(self, base_dir: Path):
        self.path = Path(base_dir) / "database" / "legacy" / "wetlab_feedback_rules.csv"

    def snapshot(self, candidate_id: str) -> List[CandidateSpec]:
        specs: List[CandidateSpec] = []
        if not self.path.exists():
            return specs
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            for i, row in enumerate(csv.DictReader(handle), 1):
                metric = str(row.get("metric", "")).strip()
                if not metric:
                    continue
                specs.append(CandidateSpec(
                    cqa_id=f"{candidate_id}:cqa:{i}",
                    test_method_id=f"DEV-{metric.upper()}",
                    metric=metric,
                    operator=str(row.get("operator", "")).strip(),
                    target_value=float(row.get("target") or 0),
                    unit=str(row.get("unit", "")),
                    justification=str(row.get("interpretation", "")),
                    source_ref="database/legacy/wetlab_feedback_rules.csv#candidate-snapshot",
                ))
        return specs

    def evaluate(self, specs: Iterable[CandidateSpec],
                 measurements: Dict[str, float]) -> List[Dict[str, Any]]:
        evaluations: List[Dict[str, Any]] = []
        for spec in specs:
            if spec.metric not in measurements or spec.operator not in OPS:
                continue
            value = float(measurements[spec.metric])
            failed = OPS[spec.operator](value, spec.target_value)
            evaluations.append({
                "cqa_id": spec.cqa_id,
                "metric": spec.metric,
                "measured": value,
                "unit": spec.unit,
                "failure_condition": f"{spec.operator} {spec.target_value:g}",
                "passed": not failed,
                "reason": spec.justification if failed else "후보별 개발 규격 충족",
                "spec_version": spec.version,
                "source_ref": spec.source_ref,
            })
        return evaluations
