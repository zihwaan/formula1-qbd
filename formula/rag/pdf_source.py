"""참고서적 PDF를 RAG 근거로 색인한다.

부형제 마스터(100행)와 FDA IID(1,796행)는 "어떤 부형제가 있고 얼마나 쓰였나"는 알려주지만
**왜 그 부형제를 쓰는지, 어떤 조건에서 문제가 되는지**는 담고 있지 않다. 그 서술은
참고서적(Handbook of Pharmaceutical Excipients 등)에 있고, 설계·심사 에이전트가
근거로 인용해야 하는 것도 그쪽이다.

## 저작권 취급

이 모듈은 **로컬에 있는 파일만 읽는다.** PDF도, 추출한 텍스트도 저장소에 커밋하지 않는다
(`database/reference/books/`는 gitignore 대상). 색인은 실행 시점에 메모리에서 만들어지고
배포 이미지에도 들어가지 않는다. 즉 검색은 되지만 재배포는 일어나지 않는다.
자료를 팀과 공유해야 하면 파일 자체를 각자 배치하는 방식을 쓴다.

## 인용 단위

책 전체를 한 덩어리로 넣으면 검색이 쓸모없어진다. **부형제 단원(monograph) 단위**로
쪼개는 것이 목표인데, 판본마다 편집이 달라 목차를 신뢰할 수 없으므로 페이지를 기본 단위로
삼고 인접 페이지를 묶는다. 각 조각에 책 제목과 페이지를 달아 두어 심사관이
"어느 책 몇 쪽"까지 인용할 수 있게 한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, List, Tuple

# 참고서적을 놓는 자리. 여러 권을 넣어도 된다.
BOOKS_DIR = "database/reference/books"
# 페이지 하나가 기본 조각이다. 두 쪽을 묶으면 서로 다른 부형제 단원이 한 문서로 섞여
# "유당" 질의에 "마그네슘 스테아레이트" 조각이 걸린다(실측으로 확인). 너무 짧은 쪽만
# 다음 쪽과 합친다.
MIN_CHARS = 200            # 이보다 짧은 조각은 색인 가치가 없다
MAX_CHARS = 4000           # BM25 문서 하나의 상한 (SOURCES.md와 같은 규약)

# 스캔본 머리말/꼬리말에서 반복되는 잡음. 남겨두면 모든 조각이 비슷해져 검색이 무뎌진다.
_NOISE = re.compile(
    r"(?im)^\s*(page\s+\d+|\d+\s*$|copyright.*|all rights reserved.*|"
    r"downloaded from.*|https?://\S+\s*)$"
)


def available() -> bool:
    """pypdf 설치 여부. 없으면 이 계층은 조용히 비활성화된다."""
    try:
        import pypdf  # noqa: F401
        return True
    except Exception:
        return False


def find_books(base_dir: Path) -> List[Path]:
    folder = base_dir / BOOKS_DIR
    if not folder.exists():
        return []
    return sorted(p for p in folder.glob("*.pdf") if p.is_file())


def _clean(text: str) -> str:
    text = _NOISE.sub("", text or "")
    text = re.sub(r"-\n(?=\w)", "", text)      # 줄 끝 하이픈 분철 복원
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _title_of(book: Path, text: str) -> str:
    """조각의 대표 이름 — 부형제 단원 제목처럼 보이는 첫 줄을 쓴다.

    Handbook류는 단원 첫 줄이 부형제명이라 이것만으로도 검색 품질이 크게 올라간다.
    """
    for line in text.splitlines():
        line = line.strip()
        # 너무 길지 않고, 문장이 아니며, 글자로 시작하는 줄을 제목 후보로 본다
        if 3 <= len(line) <= 60 and not line.endswith(".") and line[:1].isalpha():
            return line
    return book.stem


def iter_chunks(book: Path) -> Iterator[Tuple[int, str, str]]:
    """(시작 페이지, 제목, 본문) 조각을 흘린다."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(book))
    except Exception:
        return

    buffer: List[str] = []
    start_page = 1
    for number, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        if not buffer:
            start_page = number
        cleaned = _clean(raw)
        if cleaned:
            buffer.append(cleaned)

        text = "\n".join(buffer).strip()
        # 충분히 길어지면 그 자리에서 끊는다 — 페이지 경계가 곧 조각 경계다.
        if len(text) >= MIN_CHARS:
            yield start_page, _title_of(book, text), text[:MAX_CHARS]
            buffer = []

    text = "\n".join(buffer).strip()
    if len(text) >= MIN_CHARS:
        yield start_page, _title_of(book, text), text[:MAX_CHARS]
