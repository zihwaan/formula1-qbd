"""데이터 요청 — Formula1_v3/IMPLEMENTATION_GUIDE.md §2.3·§3.3·§5.

`data_request_triggers.csv`에서 "지금 유효한 요청"만 골라내는 순수 조회 함수다.
**그래프를 절대 막지 않는다**(불변식 I-9) — plan()·candidate 출력은 이 함수의 결과와
무관하게 항상 진행한다. urgency=narrows_strategy는 phase_gates 직후 스펙 수준에서
한 번, refines_confidence는 GATE를 통과한 후보마다 따로 평가한다.
"""

from __future__ import annotations

import csv as csv_mod
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from formula.checkers.applies_when import evaluate
from formula.contracts import PendingRequest

CSV_PATH = "database/reference/data_request_triggers.csv"


@lru_cache(maxsize=4)
def _rows(base_dir: Path) -> List[Dict[str, str]]:
    path = Path(base_dir) / CSV_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv_mod.DictReader(handle))


def _split(value: Any) -> List[str]:
    return [p.strip() for p in str(value or "").split(";") if p.strip()]


def evaluate_triggers(
    ctx: Dict[str, Any],
    urgency: str,
    base_dir: Path,
    strategy: str = "",
    process_steps: Optional[List[str]] = None,
    flags: Optional[List[str]] = None,
) -> List[PendingRequest]:
    """satisfied_when이 아직 거짓이고 condition_expression이 참인 행만 요청으로 낸다.

    이미 풀린 요청(satisfied_when이 참)은 다음 턴에 목록에서 저절로 빠진다(불변식
    I-12) — 별도 "지웠다"는 기록을 남기지 않아도 재계산 자체가 사라짐을 보장한다.
    """
    flags_l = {f.strip().lower() for f in (flags or [])}
    steps_l = {s.strip().lower() for s in (process_steps or [])}

    def has_flag(name: str) -> bool:
        name = str(name).strip().lower()
        return name in flags_l or f"has_{name}" in flags_l or bool(ctx.get(f"has_{name}"))

    def has_step(name: str) -> bool:
        return str(name).strip().lower() in steps_l

    scope: Dict[str, Any] = {**ctx, "strategy": strategy, "has_flag": has_flag, "has_step": has_step}

    out: List[PendingRequest] = []
    for row in _rows(Path(base_dir)):
        if (row.get("urgency") or "").strip() != urgency:
            continue
        condition = str(row.get("condition_expression") or "").strip()
        if not evaluate(condition, scope):
            continue
        satisfied = str(row.get("satisfied_when") or "").strip()
        if satisfied and evaluate(satisfied, scope):
            continue
        out.append(PendingRequest(
            trigger_id=str(row.get("trigger_id") or ""),
            urgency=urgency,
            measurement_ids=_split(row.get("measurement_id")),
            result_keys=_split(row.get("result_keys")),
            label=str(row.get("rationale") or "")[:120],
            why=str(row.get("rationale") or ""),
            fallback=str(row.get("fallback_if_declined") or ""),
            strategy=strategy,
        ))
    return out


CATALOG_PATH = "database/reference/measurement_catalog.csv"


@lru_cache(maxsize=4)
def load_measurement_catalog(base_dir: Path) -> Dict[str, Dict[str, str]]:
    """measurement_id → 카탈로그 행. Tier 오름차순 정렬에 쓴다(가이드 §2.3 원칙 1)."""
    path = Path(base_dir) / CATALOG_PATH
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["measurement_id"]: row for row in csv_mod.DictReader(handle)
                if row.get("measurement_id")}
