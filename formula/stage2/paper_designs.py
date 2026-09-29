"""9단계(실험 설계 표) 시연용 논문 실측값 — 출처가 붙은 실제 표만 둔다(값을 만들지 않는다).

- monton2026_t9   : Monton 2026(Scientifica 2026:3553253) Table 9 — CBD 구강붕해정 Box–Behnken 17 run(2단계 발표 자료 슬라이드 9)
- almotairi2022_t3: Almotairi 2022(Pharmaceuticals 15:1463) Table 3 — 로르녹시캄 분산정 Box–Behnken 15 run(발표 자료 10쪽 시연 ①)

어느 study에서나 9단계에서 "논문 값 채우기"로 표 전체(요인 · 반응 · 행)를 바꾼다. 출처(citation · 표 번호)는 설계 데이터의
`paper`에 남아 화면과 보고서에 그대로 보인다. 연구자가 고치면 출처는 '논문 값+연구자'가 된다.
"""
from __future__ import annotations

import copy
import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from formula.stage2 import reference as REF

ALMOTAIRI_CSV = Path(__file__).resolve().parents[2] / "web" / "static" / "data" / "almotairi2022_table3.csv"


def _head(h: str):
    """'X: Mixing time (min)' → ('f', 'Mixing time', 'min')."""
    role = {"X": "f", "Y": "r"}.get(h[:1]) if re.match(r"^[XY]\s*:", h) else None
    name = re.sub(r"^[XY]\s*:\s*", "", h).strip()
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", name)
    return role, (m.group(1).strip() if m else name), (m.group(2).strip() if m else "")


@lru_cache(maxsize=1)
def _almotairi() -> Dict[str, Any]:
    lines = ALMOTAIRI_CSV.read_text(encoding="utf-8").splitlines()
    cite = next((l.lstrip("# ").replace("출처: ", "", 1) for l in lines if l.startswith("#")), "")
    rows = list(csv.reader(l for l in lines if l.strip() and not l.startswith("#")))
    head, body = rows[0], rows[1:]
    cols = [_head(h) for h in head]
    fi = [i for i, c in enumerate(cols) if c[0] == "f"]
    ri = [i for i, c in enumerate(cols) if c[0] == "r"]
    std, run = head.index("Std"), head.index("Run")
    num = lambda v: float(v) if re.search(r"[.eE]", v) else int(v)          # noqa: E731
    return {"citation": cite, "locator": "Table 3",
            "data": {"factors": [{"name": cols[i][1], "unit": cols[i][2]} for i in fi],
                     "responses": [{"name": cols[i][1], "unit": cols[i][2]} for i in ri],
                     "rows": [{"std": int(r[std]), "run": int(r[run]), "x": [num(r[i]) for i in fi], "y": [num(r[i]) for i in ri]} for r in body]}}


def catalog() -> Dict[str, Dict[str, Any]]:
    a = _almotairi()
    return {
        "monton2026_t9": {"label": "CBD 구강붕해정 · Monton 2026 Table 9", "runs": len(REF.design()["rows"]), "api": ("cannabidiol", "cbd"),
                          "citation": REF.citation(), "locator": "Table 9", "data": REF.design(),
                          # 논문이 반응별로 쓴 모형 차수(Table 10 식 · Table 11 ANOVA) — 10단계 '논문 식으로 설정'
                          "families": dict(REF.PAPER_FAMILIES), "families_locator": "Table 10", "short": "Monton 2026"},
        "almotairi2022_t3": {"label": "로르녹시캄 분산정 · Almotairi 2022 Table 3", "runs": len(a["data"]["rows"]), "api": ("lornoxicam", "로르녹시캄"),
                             "citation": a["citation"], "locator": a["locator"], "data": a["data"]},
    }


def options(api: Optional[str]) -> List[Dict[str, Any]]:
    """화면용 목록 — 이 study의 주성분과 같은 약물의 표를 앞에."""
    a = str(api or "").lower()
    out = [{"key": k, "label": v["label"], "runs": v["runs"], "match": any(t in a for t in v["api"])} for k, v in catalog().items()]
    return sorted(out, key=lambda o: not o["match"])


def families(key: Optional[str]) -> Optional[Dict[str, Any]]:
    """그 논문 표에 대해 논문이 보고한 반응별 모형 차수 — 없으면 None(Almotairi 표는 싣지 않았다)."""
    v = catalog().get(str(key or ""))
    if not v or not v.get("families"):
        return None
    return {"families": dict(v["families"]), "locator": v["families_locator"], "citation": v["citation"], "short": v["short"]}


def design(key: str) -> Optional[Dict[str, Any]]:
    v = catalog().get(key)
    if v is None:
        return None
    d = copy.deepcopy(v["data"])
    d["paper"] = {"key": key, "citation": v["citation"], "locator": v["locator"]}
    d["note"] = f"논문 실측값({v['locator']}, {v['runs']} run) — {v['citation']}"
    return d
