"""되돌림 — 반려·측정 결과를 **사유별 복귀 지점**으로 보낸다 (database/06_config/backtrack_transitions.csv).

반려되면 무조건 처음부터 다시 설계하지 않는다. 사유가 첨가제면 같은 전략으로 성분만 바꾸고(GATE),
공정 규칙이면 공정 경로부터(G6R), 가용화 요소가 없으면 전략 선택부터(G4) 다시 한다. 어느 쪽인지는
코드가 아니라 표의 한 행이 정한다 — `match_expression`이 반려 판정(또는 측정 결과)에 맞으면 그 행의
`return_phase`로 돌아가고 `constraint_patch`(성분 제외·전략 제외·경로 제외·가족 요구/감점)를 제약에 쌓는다.

한도: 같은 복귀 지점으로 3번 돌아가도 풀리지 않으면 한 단계 위로 올리고(PHASE_LIMIT), 전체 5회를
넘으면 사람에게 넘긴다(그래프의 MAX_REFLECTION_LOOPS).
"""

from __future__ import annotations

import csv as csv_mod
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from formula.checkers.applies_when import evaluate

CSV_PATH = "database/06_config/backtrack_transitions.csv"
PHASE_LIMIT = 3
# 복귀 지점의 깊이 — 같은 지점에서 한도를 넘기면 한 단계 위로 올린다
PHASE_ORDER = ["GATE", "G6R", "G4", "G3B"]


@dataclass
class Decision:
    transition_id: str
    return_phase: str
    directive_hint: str
    patch: Dict[str, List[str]] = field(default_factory=dict)
    matched: List[Dict[str, Any]] = field(default_factory=list)
    escalated_from: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"transition_id": self.transition_id, "return_phase": self.return_phase,
                "directive_hint": self.directive_hint, "patch": self.patch, "matched": self.matched,
                "escalated_from": self.escalated_from}


@lru_cache(maxsize=4)
def _rows(base_dir: Path) -> List[Dict[str, str]]:
    path = Path(base_dir) / CSV_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv_mod.DictReader(handle))


def _resolve(template: str, scope: Dict[str, Any]) -> List[str]:
    """`{evidence.excipient}`·`{recipe.strategy}` 같은 자리표시자를 실제 값으로 바꾼다."""
    template = template.strip()
    if not (template.startswith("{") and template.endswith("}")):
        return [template] if template else []
    root, _, key = template[1:-1].partition(".")
    value = (scope.get(root) or {}).get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v]
    return [str(value)]


def _patch(expr: str, scope: Dict[str, Any]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for part in [p.strip() for p in str(expr or "").split(";") if p.strip()]:
        key, _, value = part.partition("=")
        vals = _resolve(value, scope)
        if vals:
            out.setdefault(key.strip(), []).extend(vals)
    return out


def match_rejection(results: List[Dict[str, Any]], base_dir: Path) -> List[Decision]:
    """반려된 후보들의 판정마다 맞는 전이 행을 찾는다. 가장 깊은(priority 큰) 전이가 앞에 온다."""
    decisions: List[Decision] = []
    rows = [r for r in _rows(Path(base_dir)) if r.get("trigger_type") == "rule_verdict"]
    for result in results:
        if result.get("passed"):
            continue
        recipe = result.get("recipe")
        for v in result.get("verdicts", []):
            status = getattr(getattr(v, "status", None), "value", getattr(v, "status", ""))
            if status not in ("hard_fail", "exclude_route"):
                continue
            ctx = {"rulebook_id": getattr(v, "rulebook_id", ""), "status": status,
                   "rule_id": getattr(v, "rule_id", "")}
            scope = {"evidence": dict(getattr(v, "evidence", None) or {}),
                     "recipe": {"strategy": getattr(recipe, "strategy", ""),
                                "candidate_id": getattr(recipe, "candidate_id", "")}}
            for row in rows:
                if evaluate(row.get("match_expression") or "false", ctx):
                    decisions.append(Decision(
                        transition_id=row["transition_id"], return_phase=row["return_phase"],
                        directive_hint=row.get("directive_hint") or "",
                        patch=_patch(row.get("constraint_patch") or "", scope),
                        matched=[{"rule_id": ctx["rule_id"], "rulebook_id": ctx["rulebook_id"],
                                  "candidate_id": scope["recipe"]["candidate_id"],
                                  "priority": int(float(row.get("priority") or 0))}]))
                    break
    decisions.sort(key=lambda d: -d.matched[0]["priority"])
    return decisions


def combine(decisions: List[Decision], attempts: Dict[str, int]) -> Optional[Decision]:
    """여러 반려를 하나의 복귀로 합친다 — 가장 깊은 지점으로 가되, 제약은 모두 쌓는다.

    같은 지점에 PHASE_LIMIT번 돌아갔는데 또 그 지점이면 한 단계 위로 올린다(같은 자리 맴돌기 방지).
    """
    if not decisions:
        return None
    head = decisions[0]
    merged: Dict[str, List[str]] = {}
    for d in decisions:
        for k, vs in d.patch.items():
            for v in vs:
                if v not in merged.setdefault(k, []):
                    merged[k].append(v)
    phase = head.return_phase
    escalated = None
    while attempts.get(phase, 0) >= PHASE_LIMIT and phase in PHASE_ORDER and PHASE_ORDER.index(phase) + 1 < len(PHASE_ORDER):
        escalated = escalated or phase
        phase = PHASE_ORDER[PHASE_ORDER.index(phase) + 1]
    if escalated:
        # 같은 전략으로는 더 풀리지 않았다 — 위 단계로 올리며 반려된 전략을 뺀다
        for d in decisions:
            for m in d.matched:
                strat = m["candidate_id"].split("-", 2)[-1] if m.get("candidate_id") else ""
                if strat and strat not in merged.setdefault("exclude_strategy", []):
                    merged["exclude_strategy"].append(strat)
    return Decision(transition_id="+".join(dict.fromkeys(d.transition_id for d in decisions)),
                    return_phase=phase, directive_hint=" / ".join(dict.fromkeys(d.directive_hint for d in decisions if d.directive_hint)),
                    patch=merged, matched=[m for d in decisions for m in d.matched], escalated_from=escalated)


@lru_cache(maxsize=4)
def _strategies_by_measurement(base_dir: Path) -> Dict[str, List[str]]:
    """측정 ID → 그 측정을 요구하는 전략들 (strategy_families.required_measurements → 트리거 → 측정)."""
    root = Path(base_dir)
    trig: Dict[str, str] = {}
    tpath = root / "database/reference/data_request_triggers.csv"
    if tpath.exists():
        with tpath.open(encoding="utf-8-sig", newline="") as h:
            trig = {r["trigger_id"]: r.get("measurement_id") or "" for r in csv_mod.DictReader(h)}
    out: Dict[str, List[str]] = {}
    spath = root / "database/06_config/strategy_families.csv"
    if spath.exists():
        with spath.open(encoding="utf-8-sig", newline="") as h:
            for r in csv_mod.DictReader(h):
                for t in [x.strip() for x in (r.get("required_measurements") or "").split(";") if x.strip()]:
                    for mid in [m.strip() for m in trig.get(t, "").split(";") if m.strip()]:
                        out.setdefault(mid, []).append(r["strategy_code"])
    return out


def match_measurements(measurements: Dict[str, Any], strategies: List[str], base_dir: Path,
                       catalog: Dict[str, Dict[str, str]]) -> List[Decision]:
    """측정 결과가 전략의 전제를 부정하면(예: ASD 비혼화) 그 전략을 빼고 전략 선택으로 돌아간다.

    `{recipe.strategy}`는 **그 측정을 요구하는 전략**에만 대입한다 — ASD 혼화성 부적합이
    미분화(MICRO)까지 빼면 안 된다. 어느 전략이 어느 측정을 요구하는지는 strategy_families.csv의
    required_measurements가 정한다.
    """
    rows = [r for r in _rows(Path(base_dir)) if r.get("trigger_type") == "measurement_result"]
    needs = _strategies_by_measurement(Path(base_dir))
    out: List[Decision] = []
    for mid, meta in catalog.items():
        outputs = [f.strip() for f in str(meta.get("output_fields") or "").split(";") if f.strip()]
        if not any(k in measurements for k in outputs):
            continue
        ctx = {"measurement_id": mid, "result": SimpleNamespace(**{k: measurements.get(k) for k in outputs})}
        relevant = [st for st in (strategies or []) if st in needs.get(mid, [])]
        for strategy in (relevant or [""]):
            scope = {"recipe": {"strategy": strategy}}
            for row in rows:
                if evaluate(row.get("match_expression") or "false", ctx):
                    d = Decision(transition_id=row["transition_id"], return_phase=row["return_phase"],
                                 directive_hint=row.get("directive_hint") or "",
                                 patch=_patch(row.get("constraint_patch") or "", scope),
                                 matched=[{"measurement_id": mid, "strategy": strategy,
                                           "priority": int(float(row.get("priority") or 0))}])
                    if not any(x.transition_id == d.transition_id and x.patch == d.patch for x in out):
                        out.append(d)
    return out


def apply(constraints: Dict[str, List[str]], patch: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out = {k: list(v) for k, v in (constraints or {}).items()}
    for k, vs in patch.items():
        for v in vs:
            if v not in out.setdefault(k, []):
                out[k].append(v)
    return out
