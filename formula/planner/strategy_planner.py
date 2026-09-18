"""전략 선정 — database/06_config/strategy_families.csv (Formula1_v3 §3.5).

기존 `formula.agents.generator.plan_strategies()`가 "BCS class가 II/IV면 가용화 전략
하나 추가"하는 얕은 휴리스틱이었다면, 이 플래너는 Gate 3A~4B가 만든 파생 신호
(dcs_subclass·sig_*·asd_process 등)를 조건식·점수식으로 정식 채점한다. 여러 전략이
동시에 살아남을 수 있다 — 판정이 갈리는 지점(dcs_subclass=undetermined 등)에서는
가지치기 대신 탐색을 넓히는 것이 이 시스템의 원칙이다(가이드 §2.2, G4003).
"""

from __future__ import annotations

import csv as csv_mod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from formula.checkers.applies_when import evaluate, evaluate_expression

CSV_PATH = "database/06_config/strategy_families.csv"


@dataclass
class PlannedStrategy:
    strategy_code: str
    family: str
    label_kr: str
    score: float
    mcs_class: int
    process_steps: List[str]
    rulebook_coverage: List[str]
    required_measurements: List[str]
    generator_brief: str
    fallback_strategy: str = ""


@lru_cache(maxsize=4)
def _rows(base_dir: Path) -> List[Dict[str, str]]:
    path = Path(base_dir) / CSV_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv_mod.DictReader(handle))


def _split(value: Any) -> List[str]:
    return [p.strip() for p in str(value or "").split(";") if p.strip()]


def _route_index(ctx: Dict[str, Any]):
    routes = list(ctx.get("recommended_routes") or [])

    def route_index(route: str) -> int:
        try:
            return routes.index(route)
        except ValueError:
            return 9
    return route_index


def plan(ctx: Dict[str, Any], base_dir: Path, max_strategies: int = 3) -> List[PlannedStrategy]:
    """조건에 맞는 전략을 채점해 점수 내림차순으로 최대 max_strategies개 돌려준다.

    실패해도(행 하나가 예외를 내도) 그 행만 건너뛴다 — 전략 선정 전체가 죽지 않는다.
    아무 전략도 살아남지 않으면 빈 리스트를 돌려주고, 호출부(그래프)가 QTPP 재검토로
    보낸다 — 임의의 기본 전략을 지어내지 않는다.
    """
    scope = {**ctx, "route_index": _route_index(ctx)}
    scored: List[PlannedStrategy] = []
    for row in _rows(Path(base_dir)):
        applies = str(row.get("applies_when") or "true").strip()
        if not evaluate(applies, scope):
            continue
        try:
            raw_score = evaluate_expression(row.get("score_expression") or "0", scope)
            score = float(raw_score) if raw_score is not None else 0.0
        except Exception:
            continue
        min_score = float(row.get("min_score_to_generate") or 0)
        if score < min_score:
            continue
        scored.append(PlannedStrategy(
            strategy_code=str(row.get("strategy_code") or ""),
            family=str(row.get("family") or ""),
            label_kr=str(row.get("label_kr") or ""),
            score=score,
            mcs_class=int(float(row.get("mcs_class") or 9)),
            process_steps=_split(row.get("process_steps")),
            rulebook_coverage=_split(row.get("rulebook_coverage")),
            required_measurements=_split(row.get("required_measurements")),
            generator_brief=str(row.get("generator_brief") or ""),
            fallback_strategy=str(row.get("fallback_strategy") or ""),
        ))
    scored.sort(key=lambda s: (-s.score, s.mcs_class, s.strategy_code))
    return scored[:max_strategies]


def signature(planned: List[PlannedStrategy]) -> str:
    """"같은 입력 → 같은 계획"을 확인하는 서명(가이드 §4.1, §7.1 T-3).

    전략 *집합*이 바뀌었는지만 본다 — reassess_with_measurements()가 이 문자열을
    이전 라운드와 비교해 "신뢰도만 갱신하면 되는가, 처음부터 다시 생성해야 하는가"를
    가른다.
    """
    return "|".join(sorted(p.strategy_code for p in planned))
