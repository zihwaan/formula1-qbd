"""구조에서 오는 게이트 신호 — 이온화 가능 여부와 문헌 BCS 표.

- `ionizable`: RDKit 구조 플래그의 산·염기 site 수(descriptors_v2.derived_screens)로 정한다. 게이트·요청
  CSV(G3B001·DRQ_PKA·DRQ_SOLIDFORM 등)가 이 이름을 조건으로 쓰는데, 예전엔 아무도 채우지 않아
  조건이 늘 거짓으로 죽어 있었다. 이온화 가능한 약물은 단일 ESOL 예측이 pH 의존 용해도를 반영하지
  못하므로, BCS 잠정 용해도를 '미정'으로 두고 pH 1.2–6.8 평형용해도를 요청한다(개발자 수정 과제 P1-5).
- `bcs_lit_*`: 공식 문헌 값이 있는 약물은 `literature_bcs.csv`의 한 행으로 채운다(등급: 문헌 표 수치).
  대조는 이름이 아니라 parent InChIKey 골격으로 한다.
"""

from __future__ import annotations

import csv as csv_mod
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

LIT_CSV = "database/04_biopharmaceutics/literature_bcs.csv"


@lru_cache(maxsize=4)
def _lit_rows(path: Path) -> tuple:
    if not path.exists():
        return ()
    with path.open(encoding="utf-8-sig", newline="") as h:
        return tuple(csv_mod.DictReader(h))


def literature_row(profile, base_dir: Path) -> Optional[Dict[str, str]]:
    key = (getattr(profile, "inchikey", "") or "")[:14] if profile else ""
    if not key:
        return None
    return next((r for r in _lit_rows(Path(base_dir) / LIT_CSV) if r.get("parent_inchikey_skeleton") == key), None)


def apply_structure_signals(ctx: Dict[str, Any], spec, base_dir: Path) -> None:
    profile = getattr(spec, "api_profile", None)
    screens = getattr(profile, "derived_screens", None) or {}
    if profile is not None and profile.structure_resolved and "salt_forming_site_count" in screens:
        ctx["ionizable"] = bool(screens.get("salt_forming_site_count"))
        ctx["ionizable_sites"] = screens.get("ionizable_group_summary")
    else:
        ctx.setdefault("ionizable", None)
    row = literature_row(profile, base_dir)
    ctx["bcs_lit_solubility"] = row.get("solubility_class") if row else None
    ctx["bcs_lit_class"] = row.get("bcs_class_literature") if row else None
    ctx["bcs_lit_source"] = row.get("source_citation") if row else None
