"""심사관 인용 검증 — DOI·PMID·PMCID만 인정하고, 실재하는지 결정론으로 확인한다(개발자 수정 과제 P1-6).

"출처 없는 규칙은 실행되지 않는다"는 원칙을 심사관 점수에도 적용한다. 심사관이 "J. Pharm. Sci. 2019"처럼
식별자 없는 인용으로 점수를 매기면, 그 점수는 근거를 확인할 수 없다. 그래서:

1. 인용 풀 — 입력 단계 문헌 조사(Europe PMC가 돌려준 실제 레코드의 PMID·DOI)와 룰북 인용 등록부
   (`database/reference/citation_registry.csv`, Crossref·NCBI로 조회해 통과한 식별자)를 심사관에게 준다.
2. 검증 — 심사관 출력의 식별자가 풀에 있으면 통과. 풀 밖이면 Crossref(DOI)·NCBI(PMID/PMCID)로 조회해
   실재할 때만 통과(결과는 프로세스 안에서 캐시).
3. 검증된 인용이 하나도 없으면 그 점수는 **무효** — 합의에 쓰지 않고 화면에 사유를 표시한다.
"""

from __future__ import annotations

import csv as csv_mod
import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REGISTRY = "database/reference/citation_registry.csv"
_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}
TIMEOUT = 6.0


def normalize(raw: str) -> Optional[Tuple[str, str]]:
    """문자열 → (kind, id). DOI는 소문자, PMCID는 대문자, PMID는 숫자만."""
    text = str(raw or "").strip()
    m = re.search(r"10\.\d{4,9}/[^\s,;\"\)\]<>]+", text)
    if m:
        return "doi", m.group(0).rstrip(".").lower()
    m = re.search(r"PMC\d{5,9}", text, re.I)
    if m:
        return "pmc", m.group(0).upper()
    m = re.search(r"(?:PMID[:\s]*)?(\d{6,9})$", text, re.I)
    if m:
        return "pmid", m.group(1)
    return None


@lru_cache(maxsize=4)
def _registry(base_dir: Path) -> Dict[str, Dict[str, str]]:
    path = Path(base_dir) / REGISTRY
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as h:
        return {r["id"]: r for r in csv_mod.DictReader(h)}


def pool(spec, base_dir: Path, limit: int = 14) -> List[Dict[str, Any]]:
    """심사관에게 줄 인용 후보 — 이 약의 문헌(Europe PMC) + 룰북 등록부."""
    out: List[Dict[str, Any]] = []
    for hit in (getattr(spec, "literature", None) or []):
        ident = None
        if str(hit.get("id") or "").isdigit():
            ident = ("pmid", str(hit["id"]))
        elif hit.get("doi"):
            ident = ("doi", str(hit["doi"]).lower())
        if ident:
            out.append({"id": ident[1], "kind": ident[0], "title": hit.get("title", ""),
                        "year": hit.get("year", ""), "container": hit.get("journal", ""),
                        "abstract": (hit.get("abstract") or "")[:280], "via": "Europe PMC"})
    for r in _registry(Path(base_dir)).values():
        out.append({"id": r["id"], "kind": r["kind"], "title": r["title"], "year": r["year"],
                    "container": r["container"], "abstract": "", "via": r["verified_via"]})
    seen, uniq = set(), []
    for c in out:
        if c["id"] not in seen:
            seen.add(c["id"])
            uniq.append(c)
    return uniq[:limit]


def _lookup(kind: str, ident: str) -> Optional[Dict[str, Any]]:
    key = f"{kind}:{ident}"
    if key in _CACHE:
        return _CACHE[key]
    meta: Optional[Dict[str, Any]] = None
    try:
        if kind == "doi":
            with urllib.request.urlopen(f"https://api.crossref.org/works/{urllib.parse.quote(ident)}",
                                        timeout=TIMEOUT) as r:
                m = json.loads(r.read())["message"]
            meta = {"title": (m.get("title") or [""])[0], "via": "Crossref"}
        else:
            pmid = ident
            if kind == "pmc":
                url = f"https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?format=json&tool=formula1&ids={ident}"
                with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
                    rec = json.loads(r.read())["records"][0]
                pmid = str(rec.get("pmid") or "")
                if rec.get("status") == "error" or not pmid:
                    raise ValueError("pmc not found")
            url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id={pmid}"
            with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
                res = json.loads(r.read())["result"].get(pmid) or {}
            if res and not res.get("error"):
                meta = {"title": res.get("title", ""), "via": "NCBI"}
    except Exception:   # noqa: BLE001 — 조회되지 않으면 검증 실패다
        meta = None
    _CACHE[key] = meta
    return meta


def verify(cited: List[str], candidates: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(검증된 인용 목록, 거부된 원문). 풀에 있으면 통과, 없으면 외부 조회."""
    by_id = {c["id"]: c for c in candidates}
    ok: List[Dict[str, Any]] = []
    rejected: List[str] = []
    for raw in cited or []:
        norm = normalize(raw)
        if norm is None:
            rejected.append(str(raw))
            continue
        kind, ident = norm
        if ident in by_id:
            ok.append({"id": ident, "kind": kind, "title": by_id[ident]["title"], "via": by_id[ident]["via"]})
            continue
        meta = _lookup(kind, ident)
        if meta:
            ok.append({"id": ident, "kind": kind, "title": meta["title"], "via": meta["via"]})
        else:
            rejected.append(str(raw))
    uniq = list({c["id"]: c for c in ok}.values())
    return uniq, rejected
