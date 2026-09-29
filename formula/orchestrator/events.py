"""TraceEvent 방출·구독 — 웹 UI가 소비하는 유일한 스트림.

LangGraph의 `get_stream_writer()`(custom stream mode)로 이벤트를 흘린다.
노드 안 어디서든 `emit(...)` 한 줄이면 되고, 그래프 실행부는
`graph.astream(..., stream_mode="custom")`으로 그대로 받아 SSE로 중계한다.

LangGraph 런타임 밖(단위 테스트·CLI 데모)에서도 같은 코드가 돌아야 하므로,
writer를 못 얻으면 프로세스 로컬 버스로 폴백한다.
"""

from __future__ import annotations

import contextvars
from typing import Any, Callable, Dict, List, Optional

from formula.contracts import EventKind, TraceEvent

try:  # LangGraph 런타임 안에서만 사용 가능
    from langgraph.config import get_stream_writer
except Exception:  # pragma: no cover - langgraph 미설치 환경 폴백
    get_stream_writer = None  # type: ignore[assignment]


# 현재 실행 중인 run의 컨텍스트 (run_id, 시퀀스 카운터, 폴백 싱크)
_current: contextvars.ContextVar[Optional["EventBus"]] = contextvars.ContextVar(
    "formula_event_bus", default=None
)


class EventBus:
    """한 번의 실행(run)에 대한 이벤트 채널.

    LangGraph writer가 있으면 그쪽으로 보내고, 없으면 sinks로만 보낸다.
    어느 경우든 `history`에 전량 보관해 재생(replay)에 쓴다.
    """

    def __init__(self, run_id: str, sinks: Optional[List[Callable[[TraceEvent], None]]] = None):
        self.run_id = run_id
        self.sinks: List[Callable[[TraceEvent], None]] = list(sinks or [])
        self.history: List[TraceEvent] = []
        self._seq = 0
        # 블라인드 가림표 {실명(소문자) → 요청한 개발코드}. 코드명으로 요청한 실행에서 intake가 채운다 —
        # 같은 버스 객체가 모든 노드 스레드에 공유되므로 여기 두면 이후 모든 이벤트·LLM 호출에 적용된다.
        self.blind: Dict[str, str] = {}

    # -- 컨텍스트 매니저: with EventBus(...) as bus: 안에서 emit()이 이 버스를 찾는다
    def __enter__(self) -> "EventBus":
        self._token = _current.set(self)
        return self

    def __exit__(self, *exc) -> None:
        _current.reset(self._token)

    def subscribe(self, sink: Callable[[TraceEvent], None]) -> None:
        self.sinks.append(sink)

    def publish(self, event: TraceEvent) -> TraceEvent:
        self._seq += 1
        event.seq = self._seq
        self.history.append(event)

        if get_stream_writer is not None:
            try:
                writer = get_stream_writer()
                if writer is not None:
                    writer(event.model_dump(mode="json"))
            except Exception:
                pass  # 그래프 밖에서 호출된 경우 — sinks로만 보낸다

        for sink in self.sinks:
            try:
                sink(event)
            except Exception:
                pass  # 구독자 오류가 실행을 멈추면 안 된다
        return event


def emit(node: str, kind: EventKind, **payload: Any) -> Optional[TraceEvent]:
    """현재 실행 컨텍스트에 이벤트 1건을 흘린다.

    버스가 없으면(테스트 등) 조용히 무시한다 — 관측용 코드가 로직을 깨뜨리지 않게.
    """
    bus = _current.get()
    if bus is None:
        return None
    if bus.blind:
        payload = mask(payload)
    return bus.publish(TraceEvent(run_id=bus.run_id, node=node, kind=kind, payload=payload))


def set_blind(names: Dict[str, str]) -> None:
    """이 실행에서 가릴 실명 → 개발코드. 코드명으로 요청한 물질의 정체를 화면·LLM에 드러내지 않는다."""
    bus = _current.get()
    if bus is not None:
        bus.blind.update({k.lower(): v for k, v in names.items() if k and v and k.lower() != v.lower()})


def mask(value: Any) -> Any:
    """가림표가 있으면 문자열(중첩 dict/list 포함)의 실명을 개발코드로 바꾼다. 없으면 그대로."""
    bus = _current.get()
    if bus is None or not bus.blind:
        return value
    return mask_names(value, bus.blind)


def mask_names(value: Any, names: Dict[str, str]) -> Any:
    """`mask`의 순수 함수판 — 실행 버스 밖(입력 에이전트 응답)에서도 같은 가림표로 가린다."""
    import re
    table = {k.lower(): v for k, v in (names or {}).items() if k and v and k.lower() != v.lower()}
    if not table:
        return value
    pat = re.compile("|".join(re.escape(k) for k in sorted(table, key=len, reverse=True)), re.I)

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            return pat.sub(lambda m: table[m.group(0).lower()], v)
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return type(v)(walk(x) for x in v)
        return v
    return walk(value)


def current_bus() -> Optional[EventBus]:
    return _current.get()


def event_to_sse(event: TraceEvent) -> Dict[str, str]:
    """TraceEvent → sse-starlette가 기대하는 dict."""
    return {"event": event.kind.value, "data": event.model_dump_json()}
