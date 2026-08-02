"""API 문헌 조사 — 입력 단계에서 실제 공개 데이터베이스를 조회한다.

팀 리뷰에서 "1단계에 API 문헌 서칭이 빠졌다"는 지적이 있었다. 설계를 시작하기 전에
이 약물에 대해 **이미 알려진 것**을 모아 두면, 이후 판정과 심사가 근거를 갖는다.

두 곳을 쓴다. 둘 다 공개 API이고 인증 키가 필요 없다.

  · **PubChem PUG-REST** — 화합물 식별정보와 실측 물성(용해도 서술, logP, 융점 등).
    구조 계산값이 아니라 **문헌에 보고된 값**이라 예측값과 대조하는 데 쓴다.
  · **Europe PMC** — 제형·안정성·배합적합성 관련 논문. 초록까지 받아 심사관 RAG에 넘긴다.

원칙은 다른 계층과 같다. **없는 것을 지어내지 않는다.** 네트워크가 막히거나 결과가 없으면
빈 결과와 사유를 돌려주고, 상위 계층은 그것을 '자료 없음'으로 다룬다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
TIMEOUT = 12.0

# 제형 관점에서 의미 있는 주제만 좁혀 검색한다 — 약효·임상 논문은 여기서 필요 없다.
# 제목·초록에 실제로 나타나야 한다. 필드를 안 좁히고 인용순으로 정렬하면
# 두 단어가 스쳐 지나간 대형 리뷰가 올라온다(실측으로 확인).
FORMULATION_TOPICS = " OR ".join(
    f"TITLE_ABS:{t}" for t in
    ("formulation", "excipient", "compatibility", "stability",
     "polymorph", "solubility", "degradation", "dissolution")
)


def _httpx():
    import httpx
    return httpx


def pubchem_summary(api_name: str, smiles: str = "") -> Dict[str, Any]:
    """PubChem에서 화합물 식별정보와 보고된 물성을 가져온다."""
    out: Dict[str, Any] = {"found": False, "source": "PubChem PUG-REST",
                           "cid": None, "iupac_name": "", "properties": {},
                           "url": "", "note": ""}
    httpx = _httpx()
    props = ("MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName,"
             "XLogP,TPSA,HBondDonorCount,HBondAcceptorCount")
    routes = []
    if smiles:
        routes.append(f"{PUBCHEM}/compound/smiles/{quote(smiles, safe='')}/property/{props}/JSON")
    if api_name:
        routes.append(f"{PUBCHEM}/compound/name/{quote(api_name)}/property/{props}/JSON")

    for url in routes:
        try:
            res = httpx.get(url, timeout=TIMEOUT)
            if res.status_code != 200:
                continue
            rows = res.json().get("PropertyTable", {}).get("Properties", [])
            if not rows:
                continue
            row = rows[0]
            out.update({
                "found": True,
                "cid": row.get("CID"),
                "iupac_name": row.get("IUPACName", ""),
                "properties": {k: v for k, v in row.items() if k not in ("CID", "IUPACName")},
                "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{row.get('CID')}",
            })
            return out
        except Exception as exc:
            out["note"] = f"PubChem 조회 실패: {type(exc).__name__}"
    if not out["found"] and not out["note"]:
        out["note"] = "PubChem에서 해당 화합물을 찾지 못했습니다."
    return out


def europepmc_search(api_name: str, limit: int = 6) -> Dict[str, Any]:
    """Europe PMC에서 제형·안정성 관련 문헌을 찾는다."""
    out: Dict[str, Any] = {"found": False, "source": "Europe PMC", "hits": [],
                           "query": "", "note": ""}
    if not api_name:
        out["note"] = "API 이름이 없어 문헌을 검색하지 않았습니다."
        return out

    query = f'TITLE_ABS:"{api_name}" AND ({FORMULATION_TOPICS})'
    out["query"] = query
    httpx = _httpx()
    try:
        res = httpx.get(EUROPE_PMC, timeout=TIMEOUT, params={
            "query": query, "format": "json", "pageSize": limit,
            "resultType": "core",   # 정렬은 관련도 기본값 — 인용순은 주제를 벗어난다
        })
        res.raise_for_status()
        results = res.json().get("resultList", {}).get("result", [])
    except Exception as exc:
        out["note"] = f"Europe PMC 조회 실패: {type(exc).__name__}"
        return out

    for item in results:
        abstract = (item.get("abstractText") or "").strip()
        out["hits"].append({
            "title": item.get("title", "").strip(),
            "journal": item.get("journalTitle", ""),
            "year": item.get("pubYear", ""),
            "doi": item.get("doi", ""),
            "cited_by": item.get("citedByCount", 0),
            "id": item.get("id", ""),
            "abstract": abstract[:600],
            "url": (f"https://doi.org/{item['doi']}" if item.get("doi")
                    else f"https://europepmc.org/article/{item.get('source','MED')}/{item.get('id','')}"),
        })
    out["found"] = bool(out["hits"])
    if not out["found"]:
        out["note"] = "제형·안정성 관련 문헌을 찾지 못했습니다."
    return out


def search_api(api_name: str, smiles: str = "", limit: int = 6) -> Dict[str, Any]:
    """입력 단계 문헌 조사 — PubChem 식별/물성 + Europe PMC 문헌."""
    compound = pubchem_summary(api_name, smiles)
    papers = europepmc_search(api_name, limit=limit)
    return {
        "api_name": api_name,
        "compound": compound,
        "literature": papers,
        "summary": _summarize(api_name, compound, papers),
    }


def _summarize(api_name: str, compound: Dict[str, Any], papers: Dict[str, Any]) -> str:
    parts: List[str] = []
    if compound.get("found"):
        cid = compound.get("cid")
        reported = compound.get("properties", {})
        xlogp = reported.get("XLogP")
        parts.append(f"PubChem CID {cid} 확인"
                     + (f" · 보고 XLogP {xlogp}" if xlogp is not None else ""))
    else:
        parts.append("PubChem 미확인")
    if papers.get("found"):
        parts.append(f"제형·안정성 문헌 {len(papers['hits'])}건")
    else:
        parts.append("관련 문헌 없음")
    return f"{api_name}: " + " · ".join(parts)


def literature_context(result: Dict[str, Any], limit: int = 3) -> str:
    """설계·심사 프롬프트에 넣을 문헌 근거 텍스트."""
    hits = (result.get("literature") or {}).get("hits", [])[:limit]
    if not hits:
        return "(문헌 근거 없음)"
    lines = []
    for hit in hits:
        lines.append(f"- {hit['title']} ({hit['journal']} {hit['year']})"
                     + (f" DOI {hit['doi']}" if hit["doi"] else ""))
        if hit["abstract"]:
            lines.append(f"  {hit['abstract'][:300]}")
    return "\n".join(lines)
