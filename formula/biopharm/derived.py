"""파생값 계산 — database/00_master/derived_quantities.csv.

각 행은 `provides` 하나에 `expression`(산술식) 하나를 댄다. 같은 provides를 여러 행이
가리킬 수 있고(예: logs_pred_min은 GSE·ESOL 둘 다 있을 때/한쪽만 있을 때로 세 갈래),
precedence가 낮은 행부터 시도해 requires가 채워진 첫 번째 행을 쓴다. **ctx에 이미 값이
있으면(실측·사용자 입력) 절대 덮어쓰지 않는다** — 실측이 예측보다 우선한다는 원칙을
대입 순서로 강제한다.

식이 다른 파생값을 참조할 수 있으므로(dose_solubility_volume → d0), 한 번에 못 끝나면
더 못 늘어날 때까지 여러 차례 돈다(고정점 계산). v3 가이드 §8.1 함정이 정확히 이
순서 버그였다 — "파생값은 코드가 아니라 데이터"라는 원칙을 어겨도, 대입 순서를
코드가 미리 정해 버리면 같은 사고가 재발한다. 여기서는 순서를 CSV가 아니라
고정점 반복이 알아서 찾게 한다.
"""

from __future__ import annotations

import csv as csv_mod
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from formula.checkers.applies_when import evaluate_expression

CSV_PATH = "database/00_master/derived_quantities.csv"


@lru_cache(maxsize=4)
def _rows(base_dir: Path) -> List[Dict[str, str]]:
    path = Path(base_dir) / CSV_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv_mod.DictReader(handle))


def _split(value: Any) -> List[str]:
    return [p.strip() for p in str(value or "").split(";") if p.strip()]


def compute_derived_quantities(ctx: Dict[str, Any], base_dir: Path) -> Dict[str, str]:
    """ctx를 제자리에서 채운다. 반환값은 {provides: quantity_id} — 추적·감사용."""
    rows = _rows(Path(base_dir))
    by_provides: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        provides = (row.get("provides") or "").strip()
        if provides:
            by_provides.setdefault(provides, []).append(row)
    for candidates in by_provides.values():
        candidates.sort(key=lambda r: float(r.get("precedence") or 99))

    used: Dict[str, str] = {}
    for _ in range(len(rows) + 2):  # 고정점. 최악의 경우도 행 수만큼이면 수렴한다
        progressed = False
        for provides, candidates in by_provides.items():
            if ctx.get(provides) is not None:
                continue  # 이미 값이 있다 — 실측/사용자 입력/앞선 라운드가 우선
            for row in candidates:
                requires = _split(row.get("requires"))
                if any(ctx.get(r) is None for r in requires):
                    continue  # 재료가 아직 안 모였다 — 다음 라운드에 재시도
                expression = (row.get("expression") or "").strip()
                try:
                    value = evaluate_expression(expression, ctx)
                except Exception:
                    continue  # 이 행은 지금 계산 불가 — 다음 후보 행으로 넘어간다
                if value is None:
                    continue
                ctx[provides] = value
                used[provides] = row.get("quantity_id", "")
                progressed = True
                break
        if not progressed:
            break
    return used
