"""Claude 클라이언트 래퍼.

이 파일이 강제하는 규약 4가지:

  1. **구조화 출력** — 처방·판정은 전부 Pydantic 모델로 받는다(`messages.parse`).
     자유 텍스트를 파싱하지 않으므로 파싱 실패라는 실패 모드 자체가 없다.
  2. **프롬프트 캐싱** — 룰북 요약·rubric처럼 여러 호출이 공유하는 접두부를 system 앞단에
     고정 배치하고 `cache_control`을 건다. 심사관 N명이 같은 접두부를 쓰므로 캐시 read로 받는다.
  3. **거부 처리** — `stop_reason == "refusal"`을 content 읽기 전에 분기한다.
  4. **목업 모드** — 자격증명이 없으면 예외를 던지지 않고 `LLMUnavailable`을 올린다.
     호출부는 결정론 폴백으로 내려가고, **시연 중 네트워크/키 문제로 데모가 죽지 않는다.**
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """LLM을 쓸 수 없다(자격증명 없음/거부/오류). 호출부는 결정론 폴백으로 내려간다."""


@lru_cache(maxsize=1)
def credentials_available() -> bool:
    """API 키 또는 `ant auth login` 프로필이 있는지 확인한다.

    ANTHROPIC_API_KEY가 비어 있어도 프로필이 있으면 SDK가 알아서 집어 간다.
    """
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    config_dir = Path(os.environ.get("ANTHROPIC_CONFIG_DIR", Path.home() / ".config" / "anthropic"))
    return (config_dir / "credentials").exists()


@lru_cache(maxsize=1)
def _client():
    if not credentials_available():
        raise LLMUnavailable("ANTHROPIC_API_KEY 미설정 · ant auth login 프로필 없음")
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable(f"anthropic SDK 없음: {exc}") from exc
    return anthropic.Anthropic()


def _system_blocks(prefix: str, suffix: str = "") -> List[Dict[str, Any]]:
    """캐시 가능한 접두부 + 호출별 접미부로 system을 구성한다.

    접두부 끝에 캐시 breakpoint를 걸어, 뒤따르는 가변 내용이 캐시를 무효화하지 않게 한다.
    """
    blocks: List[Dict[str, Any]] = [
        {"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}
    ]
    if suffix:
        blocks.append({"type": "text", "text": suffix})
    return blocks


def _check_refusal(response) -> None:
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise LLMUnavailable(f"모델이 요청을 거부함 (category={category})")


def parse_structured(
    output_format: Type[T],
    system_prefix: str,
    user: str,
    system_suffix: str = "",
    effort: str = "high",
    max_tokens: int = MAX_TOKENS,
) -> T:
    """스키마에 맞는 구조화 출력을 받는다. 실패는 전부 LLMUnavailable로 정규화한다."""
    client = _client()
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=_system_blocks(system_prefix, system_suffix),
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
        )
    except Exception as exc:
        raise LLMUnavailable(f"구조화 출력 호출 실패: {exc}") from exc

    _check_refusal(response)
    parsed = getattr(response, "parsed_output", None)
    if parsed is None:
        raise LLMUnavailable("구조화 출력이 비어 있음")
    return parsed


def stream_text(
    system_prefix: str,
    user: str,
    on_delta: Optional[Callable[[str], None]] = None,
    system_suffix: str = "",
    effort: str = "high",
    max_tokens: int = MAX_TOKENS,
) -> str:
    """토큰을 흘리며 응답을 받는다 — 심사관 사고 과정을 UI에 실시간 노출하는 용도."""
    client = _client()
    chunks: List[str] = []
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": effort},
            system=_system_blocks(system_prefix, system_suffix),
            messages=[{"role": "user", "content": user}],
        ) as stream:
            for text in stream.text_stream:
                chunks.append(text)
                if on_delta is not None:
                    on_delta(text)
            _check_refusal(stream.get_final_message())
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(f"스트리밍 호출 실패: {exc}") from exc
    return "".join(chunks)


def load_prompt(base_dir: Path, relative: str, fallback: str = "") -> str:
    """config/prompts/ 의 프롬프트 파일을 읽는다. 없으면 fallback."""
    if not relative:
        return fallback
    path = base_dir / relative
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback
