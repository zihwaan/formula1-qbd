"""룰북 CSV·SOURCES 문서에 적힌 DOI·PMID·PMCID를 모아 **실재 여부를 조회해** 등록부로 만든다.

    python scripts/build_citation_registry.py      # → database/reference/citation_registry.csv

심사관은 이 등록부의 식별자나 입력 단계 문헌 조사(Europe PMC)가 돌려준 식별자만 인용할 수 있고,
그 밖의 식별자는 실행 중에 같은 방식(Crossref / NCBI)으로 조회해 통과한 것만 인정한다
(formula/agents/citations.py). 조회에 실패한 식별자는 등록부에 넣지 않는다.
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "database" / "reference" / "citation_registry.csv"
DOI = re.compile(r"10\.\d{4,9}/[^\s,;\"\)\]<>]+")
PMC = re.compile(r"PMC\d{5,9}")
PMID = re.compile(r"(?:PMID[:\s]*|pubmed\.ncbi\.nlm\.nih\.gov/)(\d{6,9})")


def crossref(doi: str):
    try:
        with urllib.request.urlopen(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}", timeout=15) as r:
            m = json.loads(r.read())["message"]
        return {"title": (m.get("title") or [""])[0], "container": (m.get("container-title") or [""])[0],
                "year": ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0]}
    except Exception:   # noqa: BLE001
        return None


def ncbi(kind: str, ident: str):
    try:
        if kind == "pmc":
            url = ("https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?format=json&tool=formula1&ids=" + ident)
            with urllib.request.urlopen(url, timeout=15) as r:
                rec = json.loads(r.read())["records"][0]
            if rec.get("status") == "error":
                return None
            ident = str(rec.get("pmid") or "")
            if not ident:
                return {"title": "", "container": "", "year": None}
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id={ident}"
        with urllib.request.urlopen(url, timeout=15) as r:
            res = json.loads(r.read())["result"].get(ident) or {}
        if not res or res.get("error"):
            return None
        return {"title": res.get("title", ""), "container": res.get("fulljournalname", ""),
                "year": (res.get("pubdate") or "")[:4]}
    except Exception:   # noqa: BLE001
        return None


def main() -> int:
    found: dict = {}
    files = [f for f in glob.glob(str(ROOT / "database/**/*.csv"), recursive=True) if "legacy" not in f
             and not f.endswith("citation_registry.csv")]
    files += glob.glob(str(ROOT / "database/**/*SOURCES*.md"), recursive=True)
    for f in files:
        text = Path(f).read_text(encoding="utf-8", errors="ignore")
        name = Path(f).name
        for m in DOI.findall(text):
            found.setdefault(("doi", m.rstrip(".").lower()), set()).add(name)
        for m in PMC.findall(text):
            found.setdefault(("pmc", m.upper()), set()).add(name)
        for m in PMID.findall(text):
            found.setdefault(("pmid", m), set()).add(name)
    rows = []
    for (kind, ident), srcs in sorted(found.items()):
        meta = crossref(ident) if kind == "doi" else ncbi(kind, ident)
        status = "verified" if meta is not None else "not_found"
        print(kind, ident, status, (meta or {}).get("title", "")[:70])
        if meta is None:
            continue
        rows.append({"id": ident, "kind": kind, "title": meta["title"], "container": meta["container"],
                     "year": meta["year"] or "", "verified_via": "Crossref" if kind == "doi" else "NCBI E-utilities",
                     "retrieved_on": date.today().isoformat(), "source_files": ";".join(sorted(srcs))})
    with OUT.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=["id", "kind", "title", "container", "year", "verified_via",
                                          "retrieved_on", "source_files"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)}/{len(found)} verified → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
