"""설계·심사 에이전트에게 근거를 공급하는 검색 계층.

벡터 DB 대신 **BM25**를 쓴다. 이유 세 가지:
  - 재현성 — 임베딩 모델 버전에 결과가 흔들리지 않는다. 같은 질의 = 같은 문서.
  - 설치 간편 — 추가 서비스·GPU·인덱스 파일이 없다(대회 시연 환경에서 중요).
  - 도메인 적합 — 부형제명·규격 용어는 정확 일치가 잘 먹는 어휘다.

색인 대상 3종:
  1. `database/00_master/excipient_master.csv`   (100행, 이도영 정본 — 기능·플래그·EMA 임계)
  2. `database/reference/excipient_master_iid.csv` (1,796행, 조하준 — FDA IID 사용 이력)
  3. `database/**/**_SOURCES.md`                  (15개 문서 — 규칙의 출처 원문)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from rank_bm25 import BM25Okapi

_TOKEN = re.compile(r"[A-Za-z0-9가-힣._%-]+")


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


@dataclass
class Document:
    doc_id: str
    source: str  # excipient_master | excipient_iid | sources
    title: str
    text: str
    meta: Dict[str, Any] = field(default_factory=dict)


class KnowledgeStore:
    """BM25 색인 + 부형제 정확 조회."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.documents: List[Document] = []
        self._bm25: Optional[BM25Okapi] = None
        self._by_excipient: Dict[str, Document] = {}
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        self._index_excipient_master()
        self._index_iid()
        self._index_sources()
        corpus = [_tokenize(f"{d.title} {d.text}") for d in self.documents]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def _index_excipient_master(self) -> None:
        path = self.base_dir / "database" / "00_master" / "excipient_master.csv"
        if not path.exists():
            return
        df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
        for row in df.to_dict(orient="records"):
            name = row.get("excipient_name_en", "")
            text = " ".join(
                f"{k}={v}" for k, v in row.items()
                if v and k not in ("source_ref", "ema_annex_retrieved_on")
            )
            doc = Document(
                doc_id=f"EXC:{row.get('excipient_id', name)}",
                source="excipient_master",
                title=f"{name} ({row.get('excipient_name_kr', '')})",
                text=text,
                meta=row,
            )
            self.documents.append(doc)
            if name:
                self._by_excipient[name.strip().lower()] = doc

    def _index_iid(self) -> None:
        """FDA IID 마스터는 1,796행이라 색인 텍스트를 핵심 컬럼으로 줄인다."""
        path = self.base_dir / "database" / "reference" / "excipient_master_iid.csv"
        if not path.exists():
            return
        df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
        keep = ["preferred_name_en", "preferred_name_ko", "synonyms", "primary_functions",
                "ionic_character", "hygroscopicity", "reducing_sugar", "chemical_reactivity_tags",
                "fda_iid_routes", "fda_iid_dosage_forms"]
        for row in df.to_dict(orient="records"):
            text = " ".join(f"{k}={row.get(k, '')}" for k in keep if row.get(k))
            self.documents.append(
                Document(
                    doc_id=f"IID:{row.get('excipient_id', '')}",
                    source="excipient_iid",
                    title=row.get("preferred_name_en", ""),
                    text=text,
                    meta={k: row.get(k, "") for k in keep},
                )
            )

    def _index_sources(self) -> None:
        """SOURCES.md는 규칙의 근거 원문 — 섹션 단위로 쪼개 색인한다."""
        for path in sorted((self.base_dir / "database").rglob("*_SOURCES.md")):
            content = path.read_text(encoding="utf-8", errors="replace")
            sections = re.split(r"\n(?=#{1,3} )", content)
            for i, section in enumerate(sections):
                section = section.strip()
                if len(section) < 40:
                    continue
                heading = section.splitlines()[0].lstrip("# ").strip()
                self.documents.append(
                    Document(
                        doc_id=f"SRC:{path.stem}#{i}",
                        source="sources",
                        title=f"{path.stem} · {heading}"[:120],
                        text=section[:4000],
                        meta={"file": str(path.relative_to(self.base_dir))},
                    )
                )

    # ------------------------------------------------------------------
    def search(self, query: str, k: int = 5, source: Optional[str] = None) -> List[Document]:
        if self._bm25 is None or not query.strip():
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(zip(scores, self.documents), key=lambda p: -p[0])
        hits = [doc for score, doc in ranked if score > 0 and (source is None or doc.source == source)]
        return hits[:k]

    def excipient(self, name: str) -> Optional[Document]:
        """부형제명 정확 조회(대소문자·공백 정규화)."""
        return self._by_excipient.get((name or "").strip().lower())

    def context_for(self, query: str, k: int = 5) -> str:
        """검색 결과를 LLM 프롬프트에 넣을 텍스트로 직렬화한다."""
        hits = self.search(query, k=k)
        if not hits:
            return "(검색 결과 없음)"
        return "\n\n".join(f"[{d.doc_id}] {d.title}\n{d.text[:900]}" for d in hits)

    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for doc in self.documents:
            counts[doc.source] = counts.get(doc.source, 0) + 1
        counts["total"] = len(self.documents)
        return counts


@lru_cache(maxsize=2)
def get_store(base_dir: Path) -> KnowledgeStore:
    """색인은 비싸므로 프로세스당 한 번만 만든다."""
    return KnowledgeStore(base_dir)
