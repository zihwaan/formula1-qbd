"""FastAPI 서버 — 에이전트 실행을 SSE로 중계한다.

엔드포인트
  POST /api/runs                  설계 실행 시작 → run_id
  GET  /api/runs/{id}/stream      TraceEvent SSE 스트림 (UI의 유일한 입력)
  GET  /api/runs/{id}/replay      저장된 이벤트 재생 — 오프라인 시연 안전장치
  GET  /api/runs/{id}             실행 요약
  POST /api/chem/preview          SMILES/API명 → descriptor·구조플래그·2D SVG (RDKit 단독 데모)
  GET  /api/chem/smarts           룰북이 쓰는 구조 패턴 목록 + 발동 규칙
  POST /api/chem/smarts           SMILES × SMARTS 직접 매칭 + 강조 구조
  GET  /api/rules/{rule_id}       규칙 원본 CSV 행 + 출처 (근거 드릴다운)
  GET  /api/runs/{id}/evidence    후보별 근거 충족 판정 + 확인시험 프로토콜 (실험 전 루프)
  POST /api/runs/{id}/confirmation 확인시험 결과 입력 → 근거 재평가 (실험 전 루프)
  POST /api/runs/{id}/approve     연구자 승인 → 실행 가능 공정 프로토콜로 전환
  POST /api/runs/{id}/wetlab      자연어 배치 결과 → 판독·판정·다음 실험 지시 (실험 후 루프)
  GET  /api/meta                  룰북·심사관·LLM 가용성 등 시스템 상태

**루프가 둘이라 입력도 둘이다.** `/confirmation`은 실행 *전* 확인시험 결과라서 입력·근거
계층으로 돌아가고, `/wetlab`은 배치를 만든 *뒤*의 결과라서 설계·프로토콜 개정으로 간다.
한 입력창에 섞으면 결과가 어디로 되먹임되는지가 사라진다.
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
from formula.chem.smarts_probe import match_smarts
from formula.chem.structural_flags import REGISTRY_VERSION, load_flag_definitions
from formula.evidence.gate import EvidenceGate
from formula.contracts import ConfirmationResult, EventKind, TraceEvent, WetLabResult
from formula.feedback.interpreter import WetLabInterpreter
from formula.feedback.labloop import direct_next, read_notes
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
_evidence_gate: Optional[EvidenceGate] = None


def registry() -> RulebookRegistry:
    global _registry
    if _registry is None:
        _registry = RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)
    return _registry


def evidence_gate() -> EvidenceGate:
    """근거 요구표는 실행마다 바뀌지 않으므로 프로세스에 한 번만 읽는다."""
    global _evidence_gate
    if _evidence_gate is None:
        _evidence_gate = EvidenceGate(ROOT)
    return _evidence_gate


# ---------------------------------------------------------------------------
# 요청 모델
# ---------------------------------------------------------------------------
# 공개 엔드포인트라 길이를 묶는다. 자연어 요구가 수십 KB일 이유가 없고,
# 그대로 LLM 프롬프트에 들어가므로 토큰 예산과 비용에 직결된다.
class RunRequest(BaseModel):
    request: str = Field(min_length=1, max_length=2000, description="자연어 설계 요구")
    smiles: Optional[str] = Field(default=None, max_length=500)
    # 현장 제약으로 반드시 써야 하는 부형제. 설계자는 회피할 수 없고 룰북이 판정한다.
    required_excipients: List[str] = Field(default_factory=list, max_length=8)


class ChemRequest(BaseModel):
    api_name: str = Field(default="", max_length=200)
    smiles: Optional[str] = Field(default=None, max_length=500)


class SmartsRequest(BaseModel):
    smiles: str = Field(default="", max_length=500)
    smarts: str = Field(default="", max_length=300)


class WetLabRequest(BaseModel):
    candidate_id: str = Field(default="", max_length=100)
    measurements: Dict[str, float] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)


class ConfirmationEntry(BaseModel):
    """확인시험 1건의 결과 (실행 전 루프)."""

    requirement_id: str = Field(max_length=40)
    outcome: str = Field(default="pass", pattern="^(pass|fail)$")
    value: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=500)


class ConfirmationRequest(BaseModel):
    candidate_id: str = Field(default="", max_length=100)
    entries: List[ConfirmationEntry] = Field(default_factory=list, max_length=20)


class ApprovalRequest(BaseModel):
    candidate_id: str = Field(default="", max_length=100)
    approver: str = Field(default="researcher", max_length=60)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
@app.post("/api/runs")
async def create_run(payload: RunRequest) -> Dict[str, str]:
    # 공개 엔드포인트라 동시 실행을 제한한다 — 무료 티어 rate limit과 파드 메모리 보호.
    if len(ACTIVE) >= MAX_ACTIVE_RUNS:
        raise HTTPException(429, f"동시 실행 {MAX_ACTIVE_RUNS}건 초과 — 잠시 후 다시 시도하세요")

    execution = Run(ROOT, payload.request, smiles=payload.smiles,
                    required_excipients=payload.required_excipients)
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


@app.get("/api/chem/smarts")
async def smarts_catalog() -> Dict[str, Any]:
    """룰북이 쓰는 구조 패턴 목록 — 각 패턴이 어떤 규칙을 발동시키는지 함께 준다.

    화면에서 SMARTS를 직접 시험할 때 "이 패턴이 왜 중요한가"를 바로 보여주기 위한 것이다.
    """
    rows = load_flag_definitions(ROOT)
    return {
        "registry_version": REGISTRY_VERSION,
        "count": len(rows),
        "patterns": [
            {
                "flag_id": row.get("flag_id", ""),
                "flag_name": row.get("flag_name", ""),
                "section": row.get("section", ""),
                "smarts": row.get("smarts", "") or row.get("smarts_pattern", ""),
                "alert_level": row.get("alert_level", ""),
                "specificity": row.get("specificity", ""),
                "triggers_rule": row.get("rulebook_group", "") or row.get("triggers_rule", ""),
                "risk_context": row.get("interpretation", "") or row.get("risk_context", ""),
                "confirmation_test": row.get("confirmation_test", ""),
                "notes": row.get("false_positive_notes", "") or row.get("notes", ""),
            }
            for row in rows
        ],
    }


@app.post("/api/chem/smarts")
async def smarts_match(payload: SmartsRequest) -> Dict[str, Any]:
    """SMILES에 SMARTS를 직접 대 보고, 맞은 원자를 강조한 구조를 돌려준다.

    룰북의 배합금기 판정은 전부 이 SMARTS 매칭에서 출발한다. 판정을 믿으려면
    "그 패턴이 정말 이 분자에 있는가"를 직접 확인할 수 있어야 하므로 화면에 노출한다.
    염 형태는 parent를 추출한 뒤 매칭한다(판정 계층과 같은 규약).
    """
    smiles = (payload.smiles or "").strip()
    smarts = (payload.smarts or "").strip()
    if not smiles or not smarts:
        raise HTTPException(422, "SMILES와 SMARTS를 모두 입력해 주세요.")
    return await asyncio.to_thread(match_smarts, smiles, smarts)


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
# 실험 전 루프 — 근거 충족 게이트 (확인시험 요청 → 결과 입력 → 재평가 → 승인)
#
# 이 루프는 그래프를 다시 돌리지 않는다. 근거 판정은 결정론이라 새로 들어온 확인시험
# 결과만 얹으면 같은 계산이 다시 나오기 때문이다(LLM 호출 0회).
# ---------------------------------------------------------------------------
def _require_run(run_id: str) -> Run:
    execution = RUNS.get(run_id)
    if execution is None:
        raise HTTPException(404, "run 없음")
    return execution


def _evidence_payload(execution: Run, assessment) -> Dict[str, Any]:
    return {
        **assessment.model_dump(mode="json"),
        "protocol": execution.evidence_gate.protocol(assessment),
    }


@app.get("/api/runs/{run_id}/evidence")
async def get_evidence(run_id: str) -> Dict[str, Any]:
    """후보별 근거 충족 판정과 확인시험 프로토콜."""
    execution = _require_run(run_id)
    # 실행이 끝나기 전에도 조회된다 — 근거 노드가 판정한 즉시 store에 쌓이므로 그걸 먼저 본다.
    assessments = {**(execution.final.get("evidence") or {}),
                   **{cid: entry["assessment"] for cid, entry in execution.evidence_store.items()}}
    return {
        "run_id": run_id,
        "winner": execution.final.get("final_candidate"),
        "candidates": {cid: _evidence_payload(execution, a) for cid, a in assessments.items()},
    }


@app.post("/api/runs/{run_id}/confirmation")
async def submit_confirmation(run_id: str, payload: ConfirmationRequest) -> Dict[str, Any]:
    """확인시험 결과를 넣고 근거 판정을 다시 계산한다 (실행 전 루프의 되먹임).

    결과가 '부적합'이면 그 전략은 배제된다 — 근거가 전제를 부정했는데 프로토콜을 내보내는
    것이 가장 위험하므로, 상태를 실행 불가로 유지하고 재설계가 필요하다고 알린다.
    """
    execution = _require_run(run_id)
    candidate_id = payload.candidate_id or execution.final.get("final_candidate") or ""
    if not payload.entries:
        raise HTTPException(422, "확인시험 결과가 비어 있습니다.")

    known = {gap.requirement_id for gap in
             (execution.assessment(candidate_id).gaps if execution.assessment(candidate_id) else [])}
    if not known:
        raise HTTPException(404, "이 후보의 근거 판정을 찾지 못했습니다. 먼저 설계를 실행해 주세요.")

    store = execution.confirmations.setdefault(candidate_id, {})
    unknown: List[str] = []
    for entry in payload.entries:
        if entry.requirement_id not in known:
            unknown.append(entry.requirement_id)   # 이 후보에 요구되지 않은 항목은 받지 않는다
            continue
        store[entry.requirement_id] = ConfirmationResult(**entry.model_dump())
    if not store:
        raise HTTPException(422, f"이 후보에 해당하지 않는 항목입니다: {', '.join(unknown)}")

    try:
        assessment = execution.reassess(candidate_id)
    except KeyError:
        raise HTTPException(404, "후보를 찾지 못했습니다.")

    result = {**_evidence_payload(execution, assessment), "unknown_requirements": unknown}
    execution.bus.publish(TraceEvent(run_id=run_id, node="evidence",
                                     kind=EventKind.CONFIRMATION, payload=result))
    return result


@app.post("/api/runs/{run_id}/approve")
async def approve_protocol(run_id: str, payload: ApprovalRequest) -> Dict[str, Any]:
    """연구자 승인 — 근거가 충족된 후보만 실행 가능 공정 프로토콜로 전환한다."""
    execution = _require_run(run_id)
    candidate_id = payload.candidate_id or execution.final.get("final_candidate") or ""
    try:
        assessment = execution.approve(candidate_id, payload.approver)
    except KeyError:
        raise HTTPException(404, "후보를 찾지 못했습니다.")
    except ValueError as exc:
        # 근거가 비어 있는데 승인되면 이 게이트 자체가 무의미해진다 → 409로 거절.
        raise HTTPException(409, str(exc))

    result = _evidence_payload(execution, assessment)
    execution.bus.publish(TraceEvent(run_id=run_id, node="evidence",
                                     kind=EventKind.APPROVAL, payload=result))
    return result


# ---------------------------------------------------------------------------
# 실험 후 루프 — Lab-in-the-loop (판독 → 판정 → 다음 실험 지시)
# ---------------------------------------------------------------------------
@app.post("/api/runs/{run_id}/wetlab")
async def submit_wetlab(run_id: str, payload: WetLabRequest) -> Dict[str, Any]:
    """배치 결과 한 바퀴: 자연어 판독 → 결정론 판정 → 다음 실험 지시.

    `notes`에 실험 노트를 자연어로 넣으면 거기서 측정값을 뽑아내고, 폼으로 넣은
    `measurements`가 있으면 그 값이 판독값을 덮는다(사람이 명시한 값이 우선).

    입력은 **배치를 이미 만든 뒤**의 결과다. 승인 전 프로토콜로 만든 배치라면 그 사실을
    응답에 남긴다 — 판정은 그대로 하되, 어떤 상태의 프로토콜에서 나온 데이터인지가
    기록에 함께 남아야 한다.
    """
    rules = ROOT / "database" / "legacy" / "wetlab_feedback_rules.csv"
    if not rules.exists():
        raise HTTPException(500, "wetlab_feedback_rules.csv 없음")

    # 1) 판독 (LLM) — 문장에 적힌 수치만 옮긴다
    read = await asyncio.to_thread(read_notes, payload.notes, ROOT)
    measurements = {**read.measurements, **payload.measurements}
    if not measurements:
        raise HTTPException(
            422,
            "실험 결과에서 측정값을 읽지 못했습니다. "
            "예: '용출 30분 62%, 경도 38N, 불순물 0.9%' 처럼 지표와 수치를 함께 적어 주세요.",
        )

    # 2) 판정 (규칙) — 같은 데이터면 항상 같은 해석
    interpreter = WetLabInterpreter(rules)
    report = interpreter.interpret(
        WetLabResult(candidate_id=payload.candidate_id or run_id,
                     measurements=measurements, notes=payload.notes)
    )

    # 3) 지시 (LLM + 확인시험 마스터 66종) — 후보 밖의 시험은 발명하지 못한다
    directive = await asyncio.to_thread(direct_next, report, ROOT, read.observations)

    result: Dict[str, Any] = {
        **report.model_dump(),
        "read": read.model_dump(),
        "directive": directive,
    }
    execution = RUNS.get(run_id)
    if execution is not None:
        assessment = execution.assessment(payload.candidate_id
                                          or execution.final.get("final_candidate") or "")
        result["protocol_state"] = assessment.readiness.value if assessment else "unknown"
        execution.bus.publish(TraceEvent(run_id=run_id, node="labloop",
                                         kind=EventKind.WETLAB, payload=result))
    return result


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
        "evidence": evidence_gate().summary(),
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
