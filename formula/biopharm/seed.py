"""알려진 변수 이름을 전부 `None`으로 미리 깔아 둔다.

CSV 조건식은 `tm_c is None`처럼 **미지값 자체를 조건**으로 쓴다. 그런데 `tm_c`가 ctx에
아예 없으면(아무도 아직 안 썼으면) `eval("tm_c is None", ...)`은 참이 아니라
`NameError`가 나고, `formula.checkers.applies_when.evaluate()`는 그 예외를 "미발동"으로
삼켜 버린다 — **"모른다"고 판정해야 할 조건이 조용히 거짓으로 죽는다.** derived_quantities·
gate_3a~4b·data_request_triggers를 실제로 이어 붙이면서 걸린 첫 번째 함정이 이것이었다.

해결은 코드가 값을 추측하는 게 아니라, **"이런 이름이 존재한다"는 사실만 미리 알려주는
것**이다 — `measurement_catalog.csv`(무엇이 측정 가능한가), `derived_quantities.csv`의
provides(무엇이 계산 가능한가), 게이트 4종의 assign 키(무엇이 파생 신호로 나오는가)를
합쳐 None으로 seed한다. 실제 값이 있으면 이 함수 호출 전에 이미 ctx에 들어 있으므로
덮어쓰지 않는다(`setdefault`).
"""

from __future__ import annotations

import csv as csv_mod
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet

_MEASUREMENT_CATALOG = "database/reference/measurement_catalog.csv"
_DERIVED_QUANTITIES = "database/00_master/derived_quantities.csv"
_GATE_FILES = [
    "database/04_biopharmaceutics/gate_3a_biopharm_class.csv",
    "database/04_biopharmaceutics/gate_3b_solid_form.csv",
    "database/04_biopharmaceutics/gate_4_enabling_strategy.csv",
    "database/04_biopharmaceutics/gate_4b_asd_process.csv",
]


def _read(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv_mod.DictReader(handle))


@lru_cache(maxsize=4)
def known_keys(base_dir: Path) -> FrozenSet[str]:
    """v3 CSV 전체를 훑어 조건식이 참조할 수 있는 변수 이름을 모은다."""
    base_dir = Path(base_dir)
    keys: set = set()

    for row in _read(base_dir / _MEASUREMENT_CATALOG):
        for field in str(row.get("output_fields") or "").split(";"):
            field = field.strip()
            if field:
                keys.add(field)

    for row in _read(base_dir / _DERIVED_QUANTITIES):
        provides = (row.get("provides") or "").strip()
        if provides:
            keys.add(provides)

    for relative in _GATE_FILES:
        for row in _read(base_dir / relative):
            for pair in str(row.get("assign") or "").split(";"):
                key = pair.split("=", 1)[0].strip()
                if key:
                    keys.add(key)

    return frozenset(keys)


def seed_known_keys(ctx: Dict[str, Any], base_dir: Path) -> None:
    """ctx를 제자리에서 채운다. 이미 값이 있는 키는 절대 건드리지 않는다."""
    for key in known_keys(Path(base_dir)):
        ctx.setdefault(key, None)
