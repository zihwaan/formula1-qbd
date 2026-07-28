"""FastAPI 서버 — 에이전트 실행을 SSE로 중계한다.

엔드포인트
  POST /api/runs                  설계 실행 시작 → run_id
  GET  /api/runs/{id}/stream      TraceEvent SSE 스트림 (UI의 유일한 입력)
  GET  /api/runs/{id}/replay      저장된 이벤트 재생 — 오프라인 시연 안전장치
  GET  /api/runs/{id}             실행 요약
  POST /api/chem/preview          SMILES/API명 → descriptor·구조플래그·2D SVG (RDKit 단독 데모)
  GET  /api/rules/{rule_id}       규칙 원본 CSV 행 + 출처 (근거 드릴다운)
  POST /api/runs/{id}/wetlab      실험 결과 재입력 → FeedbackReport
  GET  /api/meta                  룰북·심사관·LLM 가용성 등 시스템 상태
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from formula.agents.client import credentials_available, provider, provider_label
from formula.checkers.registry import RulebookRegistry
from formula.chem.profile import build_profile
from formula.contracts import EventKind, TraceEvent, WetLabResult
from formula.feedback.interpreter import WetLabInterpreter
from formula.orchestrator.events import event_to_sse
from formula.orchestrator.runner import Run

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"

# 리버스 프록시 뒤 서브경로로 서빙할 때의 접두부 (예: "/formula1").
# 프록시가 접두부를 떼고 넘기므로 FastAPI 라우트는 그대로 두고, HTML에만 base를 주입한다.
# 빈 값이면 단독 실행(http://localhost:8000)과 완전히 동일하게 동작한다.
_prefix = os.environ.get("BASE_PATH", "").strip().strip("/")
BASE_PATH = f"/{_prefix}" if _prefix else ""

# 공개 배포용 상한. 24시간 도는 서버라 인메모리 저장소가 무한히 자라면 안 되고,
# 동시 실행이 몰리면 무료 티어 rate limit을 그대로 태워 버린다.
MAX_STORED_RUNS = 40
MAX_ACTIVE_RUNS = 3

app = FastAPI(title="Formula 1 — QbD 제형 설계 검증 엔진")

# 실행 중/완료된 run 보관 (단일 프로세스 데모용 인메모리 저장소)
RUNS: "OrderedDict[str, Run]" = OrderedDict()
QUEUES: Dict[str, List[asyncio.Queue]] = {}
ACTIVE: set = set()

_registry: Optional[RulebookRegistry] = None


def registry() -> RulebookRegistry:
    global _registry
    if _registry is None:
        _registry = RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)
    return _registry


# ---------------------------------------------------------------------------
# 요청 모델
# ---------------------------------------------------------------------------
# 공개 엔드포인트라 길이를 묶는다. 자연어 요구가 수십 KB일 이유가 없고,
# 그대로 LLM 프롬프트에 들어가므로 토큰 예산과 비용에 직결된다.
class RunRequest(BaseModel):
    request: str = Field(min_length=1, max_length=2000, description="자연어 설계 요구")
    smiles: Optional[str] = Field(default=None, max_length=500)


class ChemRequest(BaseModel):
    api_name: str = Field(default="", max_length=200)
    smiles: Optional[str] = Field(default=None, max_length=500)


class WetLabRequest(BaseModel):
    candidate_id: str = Field(default="", max_length=100)
    measurements: Dict[str, float] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
@app.post("/api/runs")
async def create_run(payload: RunRequest) -> Dict[str, str]:
    # 공개 엔드포인트라 동시 실행을 제한한다 — 무료 티어 rate limit과 파드 메모리 보호.
    if len(ACTIVE) >= MAX_ACTIVE_RUNS:
        raise HTTPException(429, f"동시 실행 {MAX_ACTIVE_RUNS}건 초과 — 잠시 후 다시 시도하세요")

    execution = Run(ROOT, payload.request, smiles=payload.smiles)
    RUNS[execution.run_id] = execution
    QUEUES[execution.run_id] = []
    ACTIVE.add(execution.run_id)

    # 오래된 run은 버린다(재생 기능은 최근 것만 지원). 24시간 도는 서버라 필요하다.
    while len(RUNS) > MAX_STORED_RUNS:
        stale_id, _ = RUNS.popitem(last=False)
        QUEUES.pop(stale_id, None)

    async def drive() -> None:
        try:
            async for event in execution.stream():
                for queue in QUEUES.get(execution.run_id, []):
                    queue.put_nowait(event)
        finally:
            ACTIVE.discard(execution.run_id)
            for queue in QUEUES.get(execution.run_id, []):
                queue.put_nowait(None)

    asyncio.create_task(drive())
    return {"run_id": execution.run_id}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str) -> EventSourceResponse:
    if run_id not in RUNS:
        raise HTTPException(404, "run 없음")
    execution = RUNS[run_id]
    queue: asyncio.Queue = asyncio.Queue()

    # 구독 이전에 이미 지나간 이벤트를 먼저 흘려보낸다(늦게 붙어도 처음부터 보이게)
    for event in list(execution.bus.history):
        queue.put_nowait(event)
    QUEUES.setdefault(run_id, []).append(queue)

    async def publisher():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield {"event": "run.closed", "data": "{}"}
                    break
                yield event_to_sse(event)
        finally:
            if queue in QUEUES.get(run_id, []):
                QUEUES[run_id].remove(queue)

    return EventSourceResponse(publisher())


@app.get("/api/runs/{run_id}/replay")
async def replay_run(run_id: str, delay: float = 0.06) -> EventSourceResponse:
    """저장된 이벤트를 일정 간격으로 재생한다 — 네트워크/API 없이도 시연이 가능하다."""
    if run_id not in RUNS:
        raise HTTPException(404, "run 없음")
    history = list(RUNS[run_id].bus.history)

    async def publisher():
        for event in history:
            yield event_to_sse(event)
            await asyncio.sleep(delay)
        yield {"event": "run.closed", "data": "{}"}

    return EventSourceResponse(publisher())


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> Dict[str, Any]:
    if run_id not in RUNS:
        raise HTTPException(404, "run 없음")
    return RUNS[run_id].summary()


# ---------------------------------------------------------------------------
# RDKit 단독 미리보기 — 팀원이 물성 계층만 따로 확인할 수 있게
# ---------------------------------------------------------------------------
@app.post("/api/chem/preview")
async def chem_preview(payload: ChemRequest) -> Dict[str, Any]:
    name = payload.api_name or payload.smiles or ""
    profile = build_profile(name, smiles=payload.smiles, base_dir=ROOT)
    return profile.model_dump()


# ---------------------------------------------------------------------------
# 근거 드릴다운 — 판정을 클릭하면 원본 CSV 행과 출처를 보여준다
# ---------------------------------------------------------------------------
@app.get("/api/rules/{rule_id}")
async def get_rule(rule_id: str) -> Dict[str, Any]:
    """rule_id로 룰북 전체를 훑어 원본 행을 찾는다."""
    for entry in registry().entries:
        path = ROOT / entry.file
        if not path.exists():
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
        for id_column in ("rule_id", "criterion_id", "scale_id", "config_id", "estimate_id", "flag_id"):
            if id_column not in df.columns:
                continue
            match = df[df[id_column] == rule_id]
            if not match.empty:
                return {
                    "rule_id": rule_id,
                    "rulebook_id": entry.id,
                    "file": entry.file,
                    "layer": entry.layer,
                    "strategy": entry.strategy,
                    "polarity": entry.polarity.value,
                    "row": match.iloc[0].to_dict(),
                    "sources_doc": _sources_for(entry.file),
                }
    raise HTTPException(404, f"규칙 {rule_id} 없음")


def _sources_for(rule_file: str) -> Optional[str]:
    """규칙 CSV와 같은 폴더의 *_SOURCES.md 경로를 찾는다."""
    folder = (ROOT / rule_file).parent
    candidates = sorted(folder.glob("*_SOURCES.md"))
    return str(candidates[0].relative_to(ROOT)) if candidates else None


# ---------------------------------------------------------------------------
# Wet-lab closed loop
# ---------------------------------------------------------------------------
@app.post("/api/runs/{run_id}/wetlab")
async def submit_wetlab(run_id: str, payload: WetLabRequest) -> Dict[str, Any]:
    rules = ROOT / "database" / "legacy" / "wetlab_feedback_rules.csv"
    if not rules.exists():
        raise HTTPException(500, "wetlab_feedback_rules.csv 없음")
    interpreter = WetLabInterpreter(rules)
    report = interpreter.interpret(
        WetLabResult(candidate_id=payload.candidate_id or run_id,
                     measurements=payload.measurements, notes=payload.notes)
    )
    execution = RUNS.get(run_id)
    if execution is not None:
        execution.bus.publish(TraceEvent(run_id=run_id, node="wetlab",
                                         kind=EventKind.WETLAB,
                                         payload=report.model_dump()))
    return report.model_dump()


# ---------------------------------------------------------------------------
# 시스템 상태
# ---------------------------------------------------------------------------
@app.get("/api/meta")
async def meta() -> Dict[str, Any]:
    reg = registry()
    reviewers: List[Dict[str, Any]] = []
    if reg.reviewer_registry_path:
        df = pd.read_csv(reg.reviewer_registry_path, dtype=str, keep_default_na=False).fillna("")
        reviewers = df[["reviewer_id", "reviewer_name_kr", "domain",
                        "summon_condition", "base_weight"]].to_dict(orient="records")
    return {
        "rulebook": reg.summary(),
        "entries": [{"id": e.id, "file": e.file, "layer": e.layer,
                     "eval_type": e.eval_type.value, "strategy": e.strategy,
                     "priority": e.trigger_priority, "polarity": e.polarity.value}
                    for e in reg.entries],
        "reviewers": reviewers,
        "llm_available": credentials_available(),
        "llm_provider": provider(),
        "llm_model": provider_label(),
    }


# ---------------------------------------------------------------------------
# 정적 파일 (빌드 스텝 없는 SPA)
# ---------------------------------------------------------------------------
def _asset_version(name: str) -> str:
    """정적 파일 내용의 짧은 해시. 배포마다 URL이 바뀌어 캐시가 자동으로 갈린다."""
    path = STATIC / name
    if not path.exists():
        return "0"
    return hashlib.sha1(path.read_bytes()).hexdigest()[:8]


@app.get("/")
async def index() -> HTMLResponse:
    """서브경로 배포를 위해 `<base>`와 `window.__BASE__`를 주입해 내려준다.

    BASE_PATH가 비어 있으면 원본 HTML과 동일하다(로컬 단독 실행 그대로).

    또한 `static/app.js` 같은 참조에 내용 해시(`?v=`)를 붙인다. 이 SPA는 빌드 스텝이 없어
    파일명에 해시가 없고, 공개 경로 앞단의 Cloudflare가 `.js`/`.css`를 기본 4시간 캐시한다
    (origin이 Cache-Control을 안 보내면 `max-age=14400`). 해시를 붙이지 않으면 재배포 후에도
    한동안 옛 스크립트가 서빙된다 — 실제로 겪은 문제다.
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    injected = (
        f'<base href="{BASE_PATH}/">\n'
        f'  <script>window.__BASE__ = "{BASE_PATH}";</script>'
    )
    html = html.replace("<!--BASE-->", injected)
    html = re.sub(
        r'(href|src)="static/([^"?]+)"',
        lambda m: f'{m.group(1)}="static/{m.group(2)}?v={_asset_version(m.group(2))}"',
        html,
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """브라우저가 항상 찾는 경로 — 없으면 콘솔에 404가 남는다."""
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


class RevalidatingStatic(StaticFiles):
    """정적 응답에 `no-cache`를 달아 중간 캐시가 항상 재검증하게 한다.

    `?v=` 해시가 이미 캐시를 갈라 주지만, 해시 없이 직접 열린 URL이 4시간 굳는 일을 막는다.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount("/static", RevalidatingStatic(directory=STATIC), name="static")
