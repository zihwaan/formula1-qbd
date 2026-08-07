"""부형제 성분명 해석 — 처방의 자유 표기와 룰북의 표준명을 잇는 다리.

**왜 있는가.** `incompatibility_1to1.csv`는 부형제를 `excipient_name_en`으로 적는다
("Lactose monohydrate"). 처방의 성분명은 설계 LLM이 쓰거나 사용자가 "반드시 포함할
부형제"에 직접 친 자유 표기다 — "유당", "Lactose", "Lactose Monohydrate, NF".
전략 함수가 `excipient in ingredients`로 **문자열 동등 비교**를 하던 동안, 이 셋은
어느 것도 INC002와 만나지 못했다. 규칙은 멀쩡히 있는데 판정이 통과로 나왔다.

미탐 1건 = 놓친 금기다. 그래서 이 계층의 판단 기준은 세 단계로 명시한다.

  exact    표기만 다르고 가리키는 성분이 같다 → 룰을 그대로 발동한다.
           ("유당수화물", "Lactose Monohydrate, NF", "lactose monohydrate")
  generic  처방이 **계열명**을 썼고 룰북 행이 그 계열의 한 등급이다 → 발동하되
           "등급 미지정" 사실을 판정문에 남긴다. ("유당" → 유당수화물 행)
  없음     매칭 실패 → 발동하지 않는다.

`generic`을 발동시키는 근거: 처방이 "유당"이라고만 적었다면 유당수화물도 그 표기가
덮는 범위 안이고, 룰북은 그 조합을 금기로 안다. 여기서 통과를 주면 "이름을 두루뭉술하게
쓰면 게이트를 통과한다"가 된다. 대신 어느 행에 어떻게 걸렸는지를 판정에 실어 사람이
등급을 특정해 다시 돌릴 수 있게 한다.

**표준명 사전은 코드가 아니라 데이터다.** 두 마스터 CSV(이름 en/kr/synonyms)를 그대로
읽고, 규격 토큰과 보충 별칭만 `config/excipient_aliases.yaml`에 둔다 — 새 부형제를
지원하는 일은 마스터에 행을 추가하는 일이지 이 파일을 고치는 일이 아니다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import yaml

# 전략 함수가 원본명 → 표준명 목록을 건네받는 ctx 키.
# 밑줄로 시작하는 키는 파생 state가 아니라 엔진 내부 배선이라 UI로 내보내지 않는다
# (orchestrator/graph.py 가 `_` 접두 키를 걸러낸다).
CTX_IDENTITIES = "_excipient_identities"

# 이름 사전을 뽑아낼 컬럼. 두 마스터가 컬럼명을 달리 쓴다.
_NAME_COLUMNS = (
    "excipient_name_en", "excipient_name_kr",       # 00_master/excipient_master.csv
    "preferred_name_en", "preferred_name_ko",       # reference/excipient_master_iid.csv
    "excipient_name", "excipient", "name", "ingredient_name",  # 기타 표기
)
_CANONICAL_COLUMNS = ("excipient_name_en", "preferred_name_en", "excipient_name", "name")
_SYNONYM_COLUMNS = ("synonyms",)

_MASTER_FILES = (
    "database/00_master/excipient_master.csv",
    "database/reference/excipient_master_iid.csv",
)

# 한글·영숫자만 남기고 나머지는 토큰 구분자로 본다.
_TOKEN_SPLIT = re.compile(r"[^0-9a-z가-힣]+")
_PARENS = re.compile(r"[(（\[]([^)）\]]*)[)）\]]")

Tokens = Tuple[str, ...]


@dataclass(frozen=True)
class ExcipientMatch:
    """룰북 행의 부형제와 처방 성분이 만난 방식."""

    ingredient: str   # 처방에 적힌 원본 표기
    canonical: str    # 룰북 쪽 표준명
    kind: str         # "exact" | "generic"

    @property
    def is_generic(self) -> bool:
        return self.kind == "generic"


# ---------------------------------------------------------------------------
# 정규화
# ---------------------------------------------------------------------------
def _tokenize(name: str, noise: frozenset) -> Tokens:
    text = unicodedata.normalize("NFKC", str(name or "")).lower()
    tokens = [t for t in _TOKEN_SPLIT.split(text) if t]
    kept = tuple(t for t in tokens if t not in noise)
    # 전부 규격 토큰이면(예: "USP") 버리지 않는다 — 빈 이름은 아무것과도 못 만난다
    return kept or tuple(tokens)


def name_variants(name: str, noise: frozenset = frozenset()) -> List[Tokens]:
    """한 표기에서 비교 후보들을 만든다.

    괄호는 같은 성분의 다른 이름을 담는 관용 표기다 — 룰북의 "Glucose (dextrose)"도,
    처방의 "Lactose monohydrate (유당)"도 마찬가지다. 그래서 세 형태를 모두 후보로 둔다:
    괄호 내용을 이어 붙인 형태 · 괄호를 뺀 형태 · 괄호 안만 남긴 형태.
    """
    raw = str(name or "")
    inner = [m.strip() for m in _PARENS.findall(raw) if m.strip()]
    stripped = _PARENS.sub(" ", raw)

    out: List[Tokens] = []
    for candidate in (raw, stripped, *inner):
        tokens = _tokenize(candidate, noise)
        if tokens and tokens not in out:
            out.append(tokens)
    return out


def _key(tokens: Tokens) -> Tokens:
    """어순 무관 비교용 키. "Anhydrous lactose" == "Lactose anhydrous"."""
    return tuple(sorted(tokens))


def _covers(rule: Tokens, generic: Tokens) -> bool:
    """룰북 이름이 처방의 계열명을 특수화한 것인가.

    계열명은 **머리말 또는 꼬리말**로만 인정한다. "lactose" ⊂ "lactose monohydrate"는
    같은 계열이지만, "starch" ⊂ "sodium starch glycolate"는 전혀 다른 부형제다 —
    단순 부분집합으로 보면 후자까지 걸려 잘못된 반려가 나온다.
    """
    if len(generic) >= len(rule):
        return False
    return rule[:len(generic)] == generic or rule[-len(generic):] == generic


# ---------------------------------------------------------------------------
# 표준명 사전
# ---------------------------------------------------------------------------
class ExcipientResolver:
    """마스터 CSV + 별칭 설정에서 "표기 → 표준명" 사전을 만든다."""

    def __init__(self, base_dir: Path, config_path: Optional[Path] = None):
        self.base_dir = Path(base_dir)
        self.config_path = Path(config_path) if config_path else (
            self.base_dir / "config" / "excipient_aliases.yaml")
        config = self._load_config()
        self.noise: frozenset = frozenset(
            _tokenize(t, frozenset())[0] if _tokenize(t, frozenset()) else ""
            for t in config.get("noise_tokens", []) or []
        ) - {""}
        self._aliases: Dict[Tokens, List[str]] = {}
        self._known: Dict[Tokens, str] = {}
        self._load_masters()
        self._load_manual_aliases(config.get("aliases", {}) or {})

    # -- 로딩 ----------------------------------------------------------
    def _load_config(self) -> Dict:
        if not self.config_path.exists():
            return {}
        try:
            return yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _add_alias(self, alias: str, canonical: str) -> None:
        for tokens in name_variants(alias, self.noise):
            key = _key(tokens)
            bucket = self._aliases.setdefault(key, [])
            if canonical not in bucket:
                bucket.append(canonical)

    def _load_masters(self) -> None:
        for relative in _MASTER_FILES:
            path = self.base_dir / relative
            if not path.exists():
                continue
            try:
                frame = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
            except Exception:
                continue
            columns = set(frame.columns)
            canonical_col = next((c for c in _CANONICAL_COLUMNS if c in columns), None)
            if canonical_col is None:
                continue
            for row in frame.to_dict(orient="records"):
                canonical = str(row.get(canonical_col, "")).strip()
                if not canonical:
                    continue
                for tokens in name_variants(canonical, self.noise):
                    self._known.setdefault(_key(tokens), canonical)
                names = [str(row.get(c, "")).strip() for c in _NAME_COLUMNS if c in columns]
                for column in _SYNONYM_COLUMNS:
                    names += [s.strip() for s in str(row.get(column, "")).split(";")]
                for name in names:
                    if name:
                        self._add_alias(name, canonical)

    def _load_manual_aliases(self, aliases: Dict) -> None:
        for alias, targets in aliases.items():
            for canonical in (targets if isinstance(targets, list) else [targets]):
                canonical = str(canonical).strip()
                if not canonical:
                    continue
                self._add_alias(alias, canonical)
                for tokens in name_variants(canonical, self.noise):
                    self._known.setdefault(_key(tokens), canonical)

    # -- 조회 ----------------------------------------------------------
    def canonical_forms(self, name: str) -> List[str]:
        """한 표기가 가리킬 수 있는 표준명들. 자기 자신도 항상 포함한다.

        한글 표기 하나가 여러 영문명에 걸리는 일이 있다(IID 마스터에서 "유당"은
        LACTOSE·LACTOSE MONOHYDRATE·GALACTOSE MONOHYDRATE에 모두 달려 있다).
        그럴 때는 **토큰이 가장 적은 것**만 남긴다 — 가장 포괄적인 계열명이 그 표기가
        실제로 뜻하는 바에 가장 가깝고, 뒤이어 계열 매칭이 하위 등급까지 덮는다.
        마스터에 없는 성분이면 원표기가 곧 표준명이다(문자열 비교 시절의 동작 유지).

        규격 토큰을 턴 형태("lactose monohydrate" ← "Lactose Monohydrate, NF")도 함께
        싣는다. 목록을 받아 쓰는 `IngredientMatcher`는 사전도 규격 어휘도 모르는 순수
        비교기라서, 여기서 넣어 두지 않으면 그쪽에서 다시 만들 방법이 없다.
        """
        out: List[str] = [str(name or "").strip()]
        out += [" ".join(t) for t in name_variants(name, self.noise)]
        hits: List[str] = []
        for tokens in name_variants(name, self.noise):
            hits += [c for c in self._aliases.get(_key(tokens), []) if c not in hits]
        if hits:
            fewest = min(len(_tokenize(c, self.noise)) for c in hits)
            hits = [c for c in hits if len(_tokenize(c, self.noise)) == fewest]
            for canonical in hits:
                out += [canonical, *(" ".join(t) for t in name_variants(canonical, self.noise))]
        seen: List[str] = []
        for value in out:
            if value and value not in seen:
                seen.append(value)
        return seen

    def identities(self, names: Iterable[str]) -> Dict[str, List[str]]:
        """처방 성분명 → 표준명 목록. ctx에 실어 전략 함수로 넘기는 순수 데이터다."""
        return {str(n): self.canonical_forms(n) for n in names if str(n).strip()}

    def is_known(self, name: str) -> bool:
        """부형제 마스터가 아는 성분인가 (룰북 밖 조합 판별용)."""
        return any(_key(t) in self._known or _key(t) in self._aliases
                   for t in name_variants(name, self.noise))

    def known_names(self) -> set:
        """마스터가 아는 표준명 집합(소문자)."""
        return {" ".join(k) for k in self._known}


@lru_cache(maxsize=8)
def excipient_resolver(base_dir: Path, config_path: Optional[Path] = None) -> ExcipientResolver:
    """리졸버는 CSV 1,900행을 읽으므로 base_dir당 한 번만 만든다."""
    return ExcipientResolver(base_dir, config_path)


# ---------------------------------------------------------------------------
# 매칭 (전략 함수 쪽)
# ---------------------------------------------------------------------------
class IngredientMatcher:
    """`identities`(순수 dict)만으로 룰북 행의 부형제와 처방을 대조한다.

    전략 함수는 base_dir을 모른다. 그래서 사전 조회는 레지스트리가 미리 끝내 두고,
    여기는 토큰 비교만 한다 — ctx에 객체가 아니라 문자열만 흐르게 하려는 분리다.
    """

    def __init__(self, identities: Dict[str, Sequence[str]], noise: frozenset = frozenset()):
        self.noise = noise
        # 원본명 → 비교 후보 토큰들
        self._exact: Dict[Tokens, str] = {}
        self._forms: List[Tuple[Tokens, str]] = []
        for original, canonicals in (identities or {}).items():
            for canonical in [original, *(canonicals or [])]:
                for tokens in name_variants(canonical, noise):
                    self._exact.setdefault(_key(tokens), original)
                    if (tokens, original) not in self._forms:
                        self._forms.append((tokens, original))

    def match(self, rule_name: str) -> Optional[ExcipientMatch]:
        """룰북 행의 부형제명이 이 처방에 들어 있는가."""
        canonical = str(rule_name or "").strip()
        variants = name_variants(canonical, self.noise)
        for tokens in variants:
            hit = self._exact.get(_key(tokens))
            if hit is not None:
                return ExcipientMatch(ingredient=hit, canonical=canonical, kind="exact")
        for tokens in variants:
            for generic, original in self._forms:
                if _covers(tokens, generic):
                    return ExcipientMatch(ingredient=original, canonical=canonical,
                                          kind="generic")
        return None


def matcher_for(identities: Optional[Dict[str, Sequence[str]]],
                names: Iterable[str]) -> IngredientMatcher:
    """ctx에 사전이 실려 있으면 그걸 쓰고, 없으면 원표기만으로 만든다.

    전략 함수를 레지스트리 없이 직접 부르는 단위 테스트·스크립트에서도 최소한
    표기 정규화(대소문자·구두점·규격 토큰)는 동작해야 한다.
    """
    if identities:
        return IngredientMatcher(identities)
    return IngredientMatcher({str(n): [] for n in names})
