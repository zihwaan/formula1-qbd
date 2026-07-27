"""LLM 클라이언트 래퍼 — Anthropic(Claude) / Groq(무료 티어) 두 경로를 같은 인터페이스로 감싼다.

이 파일이 강제하는 규약 5가지:

  1. **구조화 출력** — 처방·판정은 전부 Pydantic 모델로 받는다. 자유 텍스트를 파싱하지
     않으므로 파싱 실패라는 실패 모드 자체가 없다.
  2. **프롬프트 캐싱** — 룰북 요약·rubric처럼 여러 호출이 공유하는 접두부를 system 앞단에
     고정 배치하고 `cache_control`을 건다(Anthropic 경로). 심사관 N명이 같은 접두부를 쓴다.
  3. **거부 처리** — `stop_reason == "refusal"`을 content 읽기 전에 분기한다.
  4. **목업 모드** — 자격증명이 없으면 예외를 던지지 않고 `LLMUnavailable`을 올린다.
     호출부는 결정론 폴백으로 내려가고, **시연 중 네트워크/키 문제로 데모가 죽지 않는다.**
  5. **프로바이더 무관** — 호출부(intake·generator·judge·reflect)는 어느 모델이 돌고 있는지
     알 필요가 없다. `parse_structured` / `stream_text` 두 함수가 유일한 접점이다.

프로바이더 선택 (`FORMULA1_LLM_PROVIDER`: auto | anthropic | groq | none, 기본 auto)
  auto → Anthropic 자격증명이 있으면 Anthropic, 없고 GROQ_API_KEY가 있으면 Groq,
         둘 다 없으면 LLMUnavailable(결정론 폴백).

Groq 경로가 Anthropic과 다른 점:
  - 구조화 출력은 `response_format={"type":"json_object"}` + system에 JSON 스키마를 박아
    넣는 방식이다. Groq의 strict `json_schema` 모드는 `$ref`/`anyOf`가 섞인 Pydantic
    스키마를 거부하는 경우가 있어, 호환 범위가 더 넓은 json_object + 검증 재시도를 택했다.
  - 프롬프트 캐싱·thinking 파라미터가 없다. `effort`는 `reasoning_effort`로 매핑한다.
  - 429(무료 티어 rate limit)는 백오프 후 다음 모델로 폴백한다. 전부 실패하면
    LLMUnavailable → 호출부가 결정론 폴백으로 내려가므로 화면은 계속 돌아간다.
"""

from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# 무료(on_demand) 티어의 분당 토큰 한도(TPM). `x-ratelimit-limit-tokens` 헤더로 확인한 값이며,
# **`max_tokens`도 이 한도에 포함된다** — 프롬프트가 짧아도 max_tokens만 크면 413이 난다
# ("Request too large ... on tokens per minute (TPM): Limit 8000, Requested 8264").
# 그래서 헤드룸이 가장 큰 모델을 앞에 세우고, 요청마다 예산에 맞춰 max_tokens를 깎는다.
GROQ_TPM = {
    "llama-3.3-70b-versatile": 12000,
    "openai/gpt-oss-120b": 8000,
    "llama-3.1-8b-instant": 6000,
}
GROQ_MODELS = list(GROQ_TPM)
# 한도의 일부는 항상 프롬프트에 양보한다. 응답은 처방 JSON·심사 소견 수준이라 이 정도면 충분하고,
# 작게 잡을수록 분당 예산이 덜 소모돼 폴백 없이 끝까지 도는 노드가 많아진다.
GROQ_MAX_TOKENS = 1200
GROQ_TPM_MARGIN = 400      # 토큰 추정 오차 흡수용 여유
GROQ_MIN_COMPLETION = 700  # 이보다 적게 남으면 프롬프트를 줄인다
GROQ_TIMEOUT = 150.0

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """LLM을 쓸 수 없다(자격증명 없음/거부/오류). 호출부는 결정론 폴백으로 내려간다."""


# ---------------------------------------------------------------------------
# 프로바이더 판별
# ---------------------------------------------------------------------------
def _anthropic_available() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    config_dir = Path(os.environ.get("ANTHROPIC_CONFIG_DIR", Path.home() / ".config" / "anthropic"))
    return (config_dir / "credentials").exists()


def _groq_key() -> str:
    return os.environ.get("GROQ_API_KEY", "").strip()


@lru_cache(maxsize=1)
def provider() -> str:
    """이번 프로세스가 쓸 프로바이더 이름. "none"이면 LLM 경로 없음."""
    requested = os.environ.get("FORMULA1_LLM_PROVIDER", "auto").strip().lower()
    if requested == "none":
        return "none"
    if requested == "anthropic":
        return "anthropic" if _anthropic_available() else "none"
    if requested == "groq":
        return "groq" if _groq_key() else "none"
    # auto
    if _anthropic_available():
        return "anthropic"
    if _groq_key():
        return "groq"
    return "none"


@lru_cache(maxsize=1)
def credentials_available() -> bool:
    """LLM 경로를 쓸 수 있는지. `/api/meta`의 `llm_available`이 이 값을 그대로 쓴다."""
    return provider() != "none"


def provider_label() -> str:
    """UI에 보여줄 모델 이름 — 어떤 경로로 돌고 있는지 화면에서 구분되게."""
    return {"anthropic": MODEL, "groq": GROQ_MODELS[0], "none": ""}[provider()]


# ---------------------------------------------------------------------------
# Anthropic 경로
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _anthropic_client():
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


def _anthropic_parse(output_format: Type[T], system_prefix: str, user: str,
                     system_suffix: str, effort: str, max_tokens: int) -> T:
    client = _anthropic_client()
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


def _anthropic_stream(system_prefix: str, user: str, on_delta: Optional[Callable[[str], None]],
                      system_suffix: str, effort: str, max_tokens: int) -> str:
    client = _anthropic_client()
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


# ---------------------------------------------------------------------------
# Groq 경로 (OpenAI 호환 chat/completions)
# ---------------------------------------------------------------------------
def _httpx():
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable(f"httpx 없음: {exc}") from exc
    return httpx


def _estimate_tokens(text: str) -> int:
    """토큰 수 보수적 추정. 한글은 글자당 약 1토큰, ASCII는 3.5자당 1토큰으로 잡는다.

    정확할 필요는 없고 **과소추정만 안 하면 된다** — 과소추정하면 413이 난다.
    """
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    return int(ascii_count / 3.5 + (len(text) - ascii_count)) + 1


def _trim_to_tokens(text: str, budget: int) -> str:
    """프롬프트가 예산을 넘으면 가운데를 덜어낸다.

    머리(과제 지시)와 꼬리(개선 지시·마무리 요구)는 판정에 직접 쓰이므로 남기고,
    가운데의 RAG 근거 뭉치를 줄인다. 잘렸다는 사실은 본문에 명시해 모델이 오해하지 않게 한다.
    """
    if _estimate_tokens(text) <= budget or budget <= 0:
        return text
    # 추정식의 역산 대신 글자 기준으로 이분 탐색 없이 근사 — 넉넉히 줄인다.
    keep = max(400, int(len(text) * budget / max(_estimate_tokens(text), 1)) - 200)
    head, tail = keep * 2 // 3, keep // 3
    return (text[:head]
            + "\n\n…(분당 토큰 한도로 참고 근거 일부를 생략했다)…\n\n"
            + text[-tail:])


def _groq_payload(model: str, system: str, user: str, effort: str,
                  max_tokens: int, stream: bool) -> Dict[str, Any]:
    """TPM 예산 안에 들어가도록 max_tokens를 깎고, 그래도 넘치면 프롬프트를 줄인다."""
    budget = GROQ_TPM.get(model, 6000) - GROQ_TPM_MARGIN
    prompt_tokens = _estimate_tokens(system) + _estimate_tokens(user)

    if budget - prompt_tokens < GROQ_MIN_COMPLETION:
        user = _trim_to_tokens(user, budget - _estimate_tokens(system) - GROQ_MIN_COMPLETION)
        prompt_tokens = _estimate_tokens(system) + _estimate_tokens(user)

    allowed = max(256, min(max_tokens, GROQ_MAX_TOKENS, budget - prompt_tokens))

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": allowed,
        "stream": stream,
    }
    if "gpt-oss" in model:
        # gpt-oss의 추론 토큰은 completion에서 나간다. 기본(고노력)으로 두면 추론이 예산을
        # 다 먹고 content가 비어 오므로 항상 low로 고정한다.
        payload["reasoning_effort"] = "low"
    return payload


def _groq_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_groq_key()}", "Content-Type": "application/json"}


def _groq_call(payload: Dict[str, Any]) -> str:
    """비스트리밍 호출 1회. HTTP 오류는 그대로 올려 상위에서 폴백을 판단하게 한다."""
    httpx = _httpx()
    response = httpx.post(GROQ_URL, headers=_groq_headers(), json=payload, timeout=GROQ_TIMEOUT)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"] or ""


def _groq_with_fallback(call: Callable[[str], Any]) -> Any:
    """모델 체인을 돌며 call(model)을 시도한다.

    핵심: **모델마다 TPM 버킷이 따로다.** 한 모델이 429면 기다리는 게 아니라 곧바로 다음
    모델로 넘기는 편이 훨씬 빠르다(분당 총 헤드룸 = 세 모델 합). 체인을 한 바퀴 다 돌아
    전부 막혔을 때만 잠깐 쉬고 두 번째 바퀴를 돈다. 그래도 안 되면 LLMUnavailable →
    호출부가 결정론 폴백으로 내려가고 화면은 계속 진행된다.
    """
    httpx = _httpx()
    last_error: Optional[Exception] = None
    for round_index in range(2):
        if round_index:
            time.sleep(5)  # 체인 전체가 한도에 걸렸다 — 버킷이 조금 회복될 시간만 준다
        for model in GROQ_MODELS:
            try:
                return call(model)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status in (429, 413) or status >= 500:
                    continue  # 다른 TPM 버킷으로 즉시 이동
                raise LLMUnavailable(f"Groq 호출 실패({status}): {exc}") from exc
            except ValidationError as exc:
                last_error = exc  # 스키마 위반 → 힌트를 붙여 다음 모델로
            except Exception as exc:
                last_error = exc
                break
    raise LLMUnavailable(f"Groq 호출 실패: {last_error}")


def _schema_instruction(output_format: Type[T]) -> str:
    """Groq에는 스키마를 프롬프트로 준다 — strict json_schema보다 호환 범위가 넓다."""
    schema = json.dumps(output_format.model_json_schema(), ensure_ascii=False, indent=2)
    return (
        "\n\n## 출력 형식 (반드시 지킬 것)\n"
        "설명·머리말·코드펜스 없이 **JSON 객체 하나만** 출력한다. "
        "아래 JSON Schema를 만족해야 한다.\n\n```json\n" + schema + "\n```"
    )


def _strip_fence(text: str) -> str:
    """모델이 ```json 펜스를 붙였을 때 벗겨낸다. 객체 바깥의 잡텍스트도 잘라낸다."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    start, end = body.find("{"), body.rfind("}")
    return body[start:end + 1] if start != -1 and end > start else body


def _groq_parse(output_format: Type[T], system_prefix: str, user: str,
                system_suffix: str, effort: str, max_tokens: int) -> T:
    system = (system_prefix + ("\n\n" + system_suffix if system_suffix else "")
              + _schema_instruction(output_format))
    hint = ""

    def attempt(model: str) -> T:
        nonlocal hint
        payload = _groq_payload(model, system, user + hint, effort, max_tokens, stream=False)
        payload["response_format"] = {"type": "json_object"}
        raw = _groq_call(payload)
        try:
            return output_format.model_validate_json(_strip_fence(raw))
        except ValidationError as exc:
            # 다음 시도에 무엇이 틀렸는지 알려 준다 — 재시도 성공률이 크게 올라간다.
            hint = f"\n\n## 직전 출력이 스키마를 위반했다 — 고쳐서 다시 출력하라\n{exc}"
            raise

    return _groq_with_fallback(attempt)


def _groq_stream(system_prefix: str, user: str, on_delta: Optional[Callable[[str], None]],
                 system_suffix: str, effort: str, max_tokens: int) -> str:
    system = system_prefix + ("\n\n" + system_suffix if system_suffix else "")

    def attempt(model: str) -> str:
        httpx = _httpx()
        payload = _groq_payload(model, system, user, effort, max_tokens, stream=True)
        chunks: List[str] = []
        with httpx.stream("POST", GROQ_URL, headers=_groq_headers(),
                          json=payload, timeout=GROQ_TIMEOUT) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {})
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                # gpt-oss는 추론 텍스트를 reasoning으로 따로 보낸다. 심사관의 사고 과정을
                # 보여주는 화면이므로 둘 다 흘린다(최종 점수는 별도 구조화 호출로 받는다).
                text = delta.get("content") or delta.get("reasoning") or ""
                if not text:
                    continue
                chunks.append(text)
                if on_delta is not None:
                    on_delta(text)
        return "".join(chunks)

    return _groq_with_fallback(attempt)


# ---------------------------------------------------------------------------
# 공개 인터페이스 — 호출부는 이 두 함수만 안다
# ---------------------------------------------------------------------------
def parse_structured(
    output_format: Type[T],
    system_prefix: str,
    user: str,
    system_suffix: str = "",
    effort: str = "high",
    max_tokens: int = MAX_TOKENS,
) -> T:
    """스키마에 맞는 구조화 출력을 받는다. 실패는 전부 LLMUnavailable로 정규화한다."""
    name = provider()
    if name == "anthropic":
        return _anthropic_parse(output_format, system_prefix, user, system_suffix, effort, max_tokens)
    if name == "groq":
        return _groq_parse(output_format, system_prefix, user, system_suffix, effort, max_tokens)
    raise LLMUnavailable("LLM 자격증명 없음 (ANTHROPIC_API_KEY / GROQ_API_KEY 미설정)")


def stream_text(
    system_prefix: str,
    user: str,
    on_delta: Optional[Callable[[str], None]] = None,
    system_suffix: str = "",
    effort: str = "high",
    max_tokens: int = MAX_TOKENS,
) -> str:
    """토큰을 흘리며 응답을 받는다 — 심사관 사고 과정을 UI에 실시간 노출하는 용도."""
    name = provider()
    if name == "anthropic":
        return _anthropic_stream(system_prefix, user, on_delta, system_suffix, effort, max_tokens)
    if name == "groq":
        return _groq_stream(system_prefix, user, on_delta, system_suffix, effort, max_tokens)
    raise LLMUnavailable("LLM 자격증명 없음 (ANTHROPIC_API_KEY / GROQ_API_KEY 미설정)")


def load_prompt(base_dir: Path, relative: str, fallback: str = "") -> str:
    """config/prompts/ 의 프롬프트 파일을 읽는다. 없으면 fallback."""
    if not relative:
        return fallback
    path = base_dir / relative
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback
