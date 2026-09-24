"""FastAPI 서버 — 에이전트 실행을 SSE로 중계한다.

엔드포인트
  GET  /api/inputs                실험 데이터 입력 카탈로그 (무엇을 넣으면 무엇이 열리는가)
  POST /api/runs                  설계 실행 시작 → run_id (실측값 선택 입력 가능)
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
  POST /api/agent/turn            입력 에이전트 — 말 → 제안 카드(실행은 사용자가 확인)
  POST /api/agent/nudge           입력 에이전트 — 상태 변화에 맞춘 다음 행동 제안

ExperimentalDevelopmentGraph (명세 v6.1 — 후보 선택 이후의 뒷부분)
  POST /api/candidates/{id}/development-studies   연구자가 고른 candidate_id@version → 불변 Handoff + study
  POST /api/development-studies/demo/lornoxicam   §19 데모 study (결과는 사전 적재하지 않는다)
  GET  /api/development-studies                   최근 study 목록
  GET  /api/development-studies/{id}              state + 지금 연구자에게 묻는 것(prompt)
  POST /api/development-studies/{id}/actions/{a}  연구자 행동 (Idempotency-Key·Expected-State-Version·Actor-ID 헤더)
  GET  /api/development-studies/{id}/trace        §18 lineage 식별자 + 이벤트·결정 원장
  GET  /api/development-studies/{id}/region-slice 공동확률 영역 단면 (시각화)

**루프가 둘이라 입력도 둘이다.** `/confirmation`은 실행 *전* 확인시험 결과라서 입력·근거
계층으로 돌아가고, `/wetlab`은 배치를 만든 *뒤*의 결과라서 설계·프로토콜 개정으로 간다.
한 입력창에 섞으면 결과가 어디로 되먹임되는지가 사라진다.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from formula.agents import input_agent
from formula.agents.client import credentials_available, provider, provider_label
from formula.checkers.registry import RulebookRegistry
from formula.chem.profile import build_profile, smiles_error
from formula.chem.smarts_probe import match_smarts
from formula.chem.structural_flags import REGISTRY_VERSION, load_flag_definitions
from formula.evidence.gate import EvidenceGate
from formula.experimental_inputs import ExperimentalInputs
from formula.contracts import (
    ConfirmationResult, EventKind, FeedbackFinding, FeedbackReport, TraceEvent, WetLabResult,
)
from formula.feedback.interpreter import WetLabInterpreter
from formula.feedback.labloop import direct_next, read_notes
from formula.development import handoff as dev_handoff
from formula.development.service import DevelopmentService, StudyError
from formula.development.store import VersionConflict
from formula.lifecycle import LifecycleService, WorkflowStatus
from formula.orchestrator.events import event_to_sse
from formula.orchestrator.runner import Run

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"

# 리버스 프록시 뒤 서브경로로 서빙할 때의 접두부 (라이브는 "/formula1").
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
_experimental_inputs: Optional[ExperimentalInputs] = None
_lifecycle: Optional[LifecycleService] = None
_development: Optional[DevelopmentService] = None


def development() -> DevelopmentService:
    global _development
    if _development is None:
        _development = DevelopmentService(ROOT)
    return _development


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


def experimental_inputs() -> ExperimentalInputs:
    global _experimental_inputs
    if _experimental_inputs is None:
        _experimental_inputs = ExperimentalInputs(ROOT)
    return _experimental_inputs


def lifecycle() -> LifecycleService:
    """장기 실행 상태는 프로세스 메모리가 아니라 SQLite에서 읽는다."""
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = LifecycleService(ROOT)
    return _lifecycle


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
    # 이미 갖고 있는 실측값(선택). 카탈로그에 있는 키만 통과한다 — 임의 키를 받으면
    # 룰북 조건식 문맥을 사용자가 덮어쓸 수 있다.
    measured_params: Dict[str, float] = Field(default_factory=dict)
    property_flags: Dict[str, bool] = Field(default_factory=dict)


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
    """확인시험 1건의 결과 (실행 전 루프).

    `value_num`은 그 시험이 산출하는 canonical 측정값이다(요구표의 `result_key`).
    숫자로 들어오면 **스펙의 실측값 자리에 그대로 꽂힌다** — 확인시험 결과가 입력·근거
    계층으로 돌아간다는 말이 문장이 아니라 데이터 이동으로 구현되는 지점이다.
    """

    requirement_id: str = Field(max_length=40)
    outcome: str = Field(default="pass", pattern="^(pass|fail)$")
    value: str = Field(default="", max_length=300)
    value_num: Optional[float] = None
    note: str = Field(default="", max_length=500)


class ConfirmationRequest(BaseModel):
    candidate_id: str = Field(default="", max_length=100)
    entries: List[ConfirmationEntry] = Field(default_factory=list, max_length=20)


class ApprovalRequest(BaseModel):
    candidate_id: str = Field(default="", max_length=100)
    approver: str = Field(default="researcher", max_length=60)


class ProjectCreateRequest(BaseModel):
    request: str = Field(min_length=1, max_length=2000)
    qtpp: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(default="", max_length=120)


class ProjectApprovalRequest(BaseModel):
    protocol_id: str = Field(default="", max_length=100)
    approver: str = Field(default="researcher", max_length=60)
    idempotency_key: str = Field(default="", max_length=120)


class BatchRequest(BaseModel):
    batch_id: str = Field(default="", max_length=100)
    protocol_id: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=1000)
    idempotency_key: str = Field(default="", max_length=120)


class LabResultRequest(BaseModel):
    result_id: str = Field(default="", max_length=100)
    batch_id: str = Field(max_length=100)
    purpose: str = Field(default="batch_cqa", pattern="^(batch_cqa|confirmation_test)$")
    hypothesis_id: str = Field(default="", max_length=100)
    measurements: Dict[str, float] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=3000)
    observations: List[str] = Field(default_factory=list, max_length=30)
    raw_data_refs: List[str] = Field(default_factory=list, max_length=30)
    method_refs: Dict[str, str] = Field(default_factory=dict)
    idempotency_key: str = Field(default="", max_length=120)


class ResultConfirmRequest(BaseModel):
    researcher: str = Field(default="researcher", max_length=60)
    measurements: Dict[str, float] = Field(default_factory=dict)
    idempotency_key: str = Field(default="", max_length=120)


class TestApprovalRequest(BaseModel):
    test_ids: List[str] = Field(default_factory=list, max_length=3)
    researcher: str = Field(default="researcher", max_length=60)
    idempotency_key: str = Field(default="", max_length=120)


class CauseConfirmRequest(BaseModel):
    researcher: str = Field(default="researcher", max_length=60)
    backtrack_target: str = Field(default="PHASE_6_PROCESS", max_length=80)
    idempotency_key: str = Field(default="", max_length=120)


class DesignRunRequest(BaseModel):
    request: str = Field(default="", max_length=2000)
    smiles: Optional[str] = Field(default=None, max_length=500)
    required_excipients: List[str] = Field(default_factory=list, max_length=8)
    measured_params: Dict[str, float] = Field(default_factory=dict)
    property_flags: Dict[str, bool] = Field(default_factory=dict)


async def _drive_execution(execution: Run) -> None:
    """SSE 이벤트를 중계한다.

    v3: 실행 가능 프로토콜·승인·배치 피드백은 이 빌드의 출력 경계 밖이라(§1) 영속
    워크플로(lifecycle) 동기화를 껐다. formula/lifecycle/은 지우지 않았으니 되돌릴
    때는 아래 finally 블록의 주석만 풀면 된다.
    """
    try:
        async for event in execution.stream():
            for queue in QUEUES.get(execution.run_id, []):
                queue.put_nowait(event)
    finally:
        # try:
        #     await asyncio.to_thread(lifecycle().sync_design, execution)
        # except Exception as exc:
        #     execution.bus.publish(TraceEvent(
        #         run_id=execution.run_id, node="lifecycle", kind=EventKind.ERROR,
        #         payload={"error": f"장기 상태 저장 실패: {exc}"},
        #     ))
        ACTIVE.discard(execution.run_id)
        for queue in QUEUES.get(execution.run_id, []):
            queue.put_nowait(None)


# ---------------------------------------------------------------------------
# 입력 카탈로그
# ---------------------------------------------------------------------------
@app.get("/api/inputs")
async def input_catalog() -> Dict[str, Any]:
    """처음부터 넣을 수 있는 실측값 목록. 각 항목이 무엇을 여는지(`unlocks`)까지 준다."""
    return experimental_inputs().catalog()


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
@app.post("/api/runs")
async def create_run(payload: RunRequest) -> Dict[str, Any]:
    # 공개 엔드포인트라 동시 실행을 제한한다 — 무료 티어 rate limit과 파드 메모리 보호.
    if len(ACTIVE) >= MAX_ACTIVE_RUNS:
        raise HTTPException(429, f"동시 실행 {MAX_ACTIVE_RUNS}건 초과 — 잠시 후 다시 시도하세요")

    # 못 읽는 SMILES는 여기서 되돌린다. 그대로 실행하면 구조 플래그가 하나도 안 서고
    # 구조 기반 배합금기가 전부 조용히 넘어간다 — 게이트에도 이관 장치를 뒀지만,
    # 원인이 오타라면 실행을 시작하기 전에 말해 주는 쪽이 옳다.
    invalid = smiles_error(payload.smiles)
    if invalid:
        raise HTTPException(400, invalid)

    # 실측값은 허용목록을 통과한 것만 스펙에 들어간다. 거부된 키는 조용히 버리지 않고
    # 응답에 실어 준다 — 오타를 삼키면 "왜 아무 규칙도 안 도는지" 알 수 없다.
    measured, flags, rejected = experimental_inputs().normalize(
        payload.measured_params, payload.property_flags)

    execution = Run(ROOT, payload.request, smiles=payload.smiles,
                    required_excipients=payload.required_excipients,
                    measured_params=measured, property_flags=flags)
    # v3: 영속 프로젝트(lifecycle)는 만들지 않는다 — 출력 경계가 후보 처방 목록에서
    # 끝난다(§1). 되돌릴 때는 아래 두 줄과 응답의 project_id를 복구하면 된다.
    # project = lifecycle().create(
    #     payload.request, run_id=execution.run_id,
    #     qtpp={"smiles": payload.smiles, "required_excipients": payload.required_excipients},
    #     idempotency_key=f"run:{execution.run_id}:project",
    # )
    RUNS[execution.run_id] = execution
    QUEUES[execution.run_id] = []
    ACTIVE.add(execution.run_id)

    # 오래된 run은 버린다(재생 기능은 최근 것만 지원). 24시간 도는 서버라 필요하다.
    while len(RUNS) > MAX_STORED_RUNS:
        stale_id, _ = RUNS.popitem(last=False)
        QUEUES.pop(stale_id, None)

    asyncio.create_task(_drive_execution(execution))
    return {"run_id": execution.run_id,
            "accepted_inputs": len(measured) + len(flags),
            "rejected_inputs": rejected}


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
    # v3: 영속 워크플로(project/workflow) 조회는 뺐다 — 아래 두 줄을 복구하면 된다.
    # project = lifecycle().store.by_run(run_id)
    # if project:
    #     summary["project_id"] = project.project_id
    #     summary["workflow"] = project.public()
    return RUNS[run_id].summary()


class MeasurementsRequest(BaseModel):
    """v3 — DRQ_NARROW 요청에 대한 실측값 회신. 차단하지 않는다(불변식 I-9) — 값이

    없거나 일부만 와도 그래프는 이미 끝났으므로 즉시 재계산한다."""

    measurements: Dict[str, Union[float, bool, str]] = Field(default_factory=dict, max_length=30)


@app.post("/api/runs/{run_id}/measurements")
async def submit_measurements(run_id: str, payload: MeasurementsRequest) -> Dict[str, Any]:
    """narrows_strategy 데이터 요청에 대한 회신 — 그래프를 다시 돌리지 않고 재계산한다."""
    if run_id not in RUNS:
        raise HTTPException(404, "run 없음")
    execution = RUNS[run_id]
    if not payload.measurements:
        raise HTTPException(422, "측정값이 비어 있습니다.")
    try:
        return await asyncio.to_thread(execution.reassess_with_measurements, payload.measurements)
    except KeyError as exc:
        raise HTTPException(409, f"아직 설계가 끝나지 않았습니다: {exc}")


# ---------------------------------------------------------------------------
# ExperimentalDevelopmentGraph — 후보 선택 이후 (명세 v6.1)
#
# 후보 탐색 그래프와 state를 공유하지 않는다. 연결은 불변 Handoff 하나뿐이다(§1.1).
# 후보 1위가 자동으로 넘어오지 않는다 — 연구자가 카드에서 `이 후보로 개발 착수`를 눌러야 한다.
# ---------------------------------------------------------------------------
class StudyCreateRequest(BaseModel):
    run_id: str
    candidate_version: int = 1
    mode: str = "demo"


class StudyActionRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)


def _study_error(exc: Exception) -> HTTPException:
    if isinstance(exc, VersionConflict):
        return HTTPException(409, {"message": "다른 곳에서 먼저 바뀌었습니다 — 새로 고친 뒤 다시 시도하세요.",
                                   "expected": exc.expected, "actual": exc.actual})
    if isinstance(exc, StudyError):
        return HTTPException(exc.status, {"message": str(exc), "verdicts": exc.verdicts})
    raise exc


@app.post("/api/candidates/{candidate_id}/development-studies")
async def create_study(candidate_id: str, payload: StudyCreateRequest,
                       idempotency_key: Optional[str] = Header(None),
                       actor_id: str = Header("researcher")) -> Dict[str, Any]:
    execution = RUNS.get(payload.run_id)
    if execution is None or not execution.final:
        raise HTTPException(404, "설계 실행이 없거나 아직 끝나지 않았습니다.")
    result = next((r for r in execution.final.get("results", []) if r["candidate_id"] == candidate_id), None)
    if result is None:
        raise HTTPException(404, f"후보 {candidate_id} 없음")
    spec = execution.final.get("spec")
    spec_d = spec.model_dump(mode="json") if hasattr(spec, "model_dump") else (spec or {})
    recipe = result["recipe"].model_dump(mode="json")
    recipe["version"] = payload.candidate_version
    verdicts = [v.model_dump(mode="json") for v in result["verdicts"] if v.rule_id]
    svc = development()
    h = dev_handoff.from_recipe(svc.rb, recipe, run_id=payload.run_id, spec=spec_d,
                                verdicts=[v for v in verdicts if v.get("status") != "pass"], actor=actor_id)
    try:
        return await asyncio.to_thread(svc.create, h, mode=payload.mode, actor=actor_id,
                                       idempotency_key=idempotency_key)
    except Exception as exc:   # noqa: BLE001
        raise _study_error(exc)


@app.post("/api/development-studies/demo/lornoxicam")
async def create_demo_study(mode: str = "demo", idempotency_key: Optional[str] = Header(None),
                            actor_id: str = Header("researcher")) -> Dict[str, Any]:
    svc = development()
    h = dev_handoff.lornoxicam_demo(svc.rb, actor_id)
    try:
        return await asyncio.to_thread(svc.create, h, mode=mode, actor=actor_id,
                                       idempotency_key=idempotency_key, demo_script="lornoxicam")
    except Exception as exc:   # noqa: BLE001
        raise _study_error(exc)


@app.get("/api/development-studies")
async def list_studies() -> Dict[str, Any]:
    return {"studies": development().store.list()}


@app.get("/api/development-studies/{study_id}")
async def get_study(study_id: str) -> Dict[str, Any]:
    try:
        return development().view(study_id)
    except Exception as exc:   # noqa: BLE001
        raise _study_error(exc)


@app.post("/api/development-studies/{study_id}/actions/{action}")
async def study_action(study_id: str, action: str, body: StudyActionRequest,
                       idempotency_key: Optional[str] = Header(None),
                       expected_state_version: Optional[int] = Header(None),
                       actor_id: str = Header("researcher")) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(development().act, study_id, action, body.payload, actor=actor_id,
                                       idempotency_key=idempotency_key, expected_version=expected_state_version)
    except Exception as exc:   # noqa: BLE001
        raise _study_error(exc)


@app.get("/api/development-studies/{study_id}/trace")
async def study_trace(study_id: str) -> Dict[str, Any]:
    try:
        return development().trace(study_id)
    except Exception as exc:   # noqa: BLE001
        raise _study_error(exc)


@app.get("/api/development-studies/{study_id}/region-slice")
async def study_region_slice(study_id: str, fixed: str = "c", index: int = 10) -> Dict[str, Any]:
    try:
        return development().region_slice(study_id, fixed, index)
    except Exception as exc:   # noqa: BLE001
        raise _study_error(exc)


@app.get("/api/development-studies/demo/lornoxicam/csv")
async def demo_csv() -> Dict[str, Any]:
    """데모 업로드 파일 — §15 fixture와 같은 파일. 연구자가 이 내용을 결과 제출로 올린다."""
    path = ROOT / "tests" / "fixtures" / "lornoxicam_table3.csv"
    return {"filename": path.name, "csv": path.read_text(encoding="utf-8"),
            "source": "Almotairi et al., Pharmaceuticals 2022, 15, 1463 — Table 3 (CC BY)"}

class DeclineRequest(BaseModel):
    trigger_ids: List[str] = Field(default_factory=list, max_length=30)


@app.post("/api/runs/{run_id}/decline")
async def decline_requests(run_id: str, payload: DeclineRequest) -> Dict[str, Any]:
    """데이터 요청 건너뛰기 — 멈추지 않고 예측값으로 계속한다. 후보는 provisional 유지."""
    if run_id not in RUNS:
        raise HTTPException(404, "run 없음")
    return RUNS[run_id].decline(payload.trigger_ids)



# ---------------------------------------------------------------------------
# 입력 에이전트 — 사용자와 두 그래프 사이. 말을 제안 카드로 바꾸고, 실행은 사용자가 누른다.
# 맥락은 서버가 run/study에서 직접 읽는다(클라이언트가 보낸 상태를 믿지 않는다).
# ---------------------------------------------------------------------------
class AgentTurn(BaseModel):
    role: str = Field(default="user", pattern="^(user|agent)$")
    text: str = Field(default="", max_length=2000)


class AgentRequest(BaseModel):
    message: str = Field(default="", max_length=2000)
    tab: str = Field(default="discovery", max_length=20)
    run_id: Optional[str] = Field(default=None, max_length=60)
    study_id: Optional[str] = Field(default=None, max_length=80)
    history: List[AgentTurn] = Field(default_factory=list, max_length=12)


_agent_catalog: Optional[Dict[str, Dict[str, Any]]] = None


def agent_catalog() -> Dict[str, Dict[str, Any]]:
    global _agent_catalog
    if _agent_catalog is None:
        _agent_catalog = input_agent.measurement_catalog(ROOT, experimental_inputs())
    return _agent_catalog


def _agent_context(payload: AgentRequest) -> Dict[str, Any]:
    run = RUNS.get(payload.run_id or "")
    run_summary = run.summary() if run is not None and run.final else None
    study = None
    if payload.study_id:
        try:
            study = development().view(payload.study_id)
        except Exception:   # noqa: BLE001 — 없는 study는 맥락에서 뺀다
            study = None
    return input_agent.snapshot(payload.tab, run_summary, study, agent_catalog())


def _pubchem_lookup(name: str) -> Dict[str, Any]:
    from formula.literature import pubchem_summary
    return pubchem_summary(name)


@app.post("/api/agent/turn")
async def agent_turn(payload: AgentRequest) -> Dict[str, Any]:
    if not payload.message.strip():
        raise HTTPException(422, "메시지가 비어 있습니다.")
    ctx = _agent_context(payload)
    history = [h.model_dump() for h in payload.history]
    out, source = await asyncio.to_thread(input_agent.run_turn, payload.message, history, ctx, agent_catalog())
    return await asyncio.to_thread(input_agent.build_response, out, source, payload.message, history, ctx,
                                   agent_catalog(), experimental_inputs(), _pubchem_lookup)


@app.post("/api/agent/nudge")
async def agent_nudge(payload: AgentRequest) -> Dict[str, Any]:
    """상태가 바뀌었을 때 에이전트가 먼저 건네는 말 — LLM 없이 맥락에서만 만든다."""
    return input_agent.nudge(_agent_context(payload)) or {"reply": "", "proposals": []}
# 
# # ---------------------------------------------------------------------------
# # 장기 실행 프로젝트 API — 파드 재시작 뒤에도 승인·실험·진단을 이어 간다.
# # ---------------------------------------------------------------------------
# @app.post("/api/projects")
# async def create_project(payload: ProjectCreateRequest) -> Dict[str, Any]:
#     project = lifecycle().create(payload.request, qtpp=payload.qtpp,
#                                  idempotency_key=payload.idempotency_key)
#     return project.public()
# 
# 
# @app.post("/api/projects/{project_id}/design-runs")
# async def start_project_design(project_id: str, payload: DesignRunRequest) -> Dict[str, Any]:
#     if len(ACTIVE) >= MAX_ACTIVE_RUNS:
#         raise HTTPException(429, f"동시 실행 {MAX_ACTIVE_RUNS}건 초과 — 잠시 후 다시 시도하세요")
#     try:
#         project = lifecycle().state(project_id)
#     except KeyError:
#         raise HTTPException(404, "project 없음")
#     request = payload.request.strip() or project.request
#     invalid = smiles_error(payload.smiles)
#     if invalid:
#         raise HTTPException(400, invalid)
#     measured, flags, rejected = experimental_inputs().normalize(
#         payload.measured_params, payload.property_flags)
#     execution = Run(ROOT, request, smiles=payload.smiles,
#                     required_excipients=payload.required_excipients,
#                     measured_params=measured, property_flags=flags)
#     try:
#         project = lifecycle().bind_run(project_id, execution.run_id)
#     except ValueError as exc:
#         raise HTTPException(409, str(exc))
#     RUNS[execution.run_id] = execution
#     QUEUES[execution.run_id] = []
#     ACTIVE.add(execution.run_id)
#     asyncio.create_task(_drive_execution(execution))
#     return {"project_id": project_id, "run_id": execution.run_id,
#             "state": project.status.value, "rejected_inputs": rejected}
# 
# 
# @app.get("/api/projects/{project_id}/state")
# async def get_project_state(project_id: str) -> Dict[str, Any]:
#     try:
#         return lifecycle().state(project_id).public()
#     except KeyError:
#         raise HTTPException(404, "project 없음")
# 
# 
# @app.get("/api/projects/{project_id}/events")
# async def get_project_events(project_id: str, after: int = 0) -> Dict[str, Any]:
#     try:
#         lifecycle().state(project_id)
#     except KeyError:
#         raise HTTPException(404, "project 없음")
#     return {"project_id": project_id, "events": lifecycle().store.events(project_id, after)}
# 
# 
# @app.get("/api/projects/{project_id}/trace")
# async def get_project_trace(project_id: str) -> Dict[str, Any]:
#     try:
#         return lifecycle().trace(project_id)
#     except KeyError:
#         raise HTTPException(404, "project 없음")
# 
# 
# @app.post("/api/projects/{project_id}/protocols/{protocol_id}/approve")
# async def approve_project_protocol(project_id: str, protocol_id: str,
#                                    payload: ProjectApprovalRequest) -> Dict[str, Any]:
#     try:
#         state = lifecycle().approve_protocol(
#             project_id, payload.approver, protocol_id or payload.protocol_id,
#             payload.idempotency_key,
#         )
#     except KeyError:
#         raise HTTPException(404, "project 없음")
#     except ValueError as exc:
#         raise HTTPException(409, str(exc))
#     return state.public()
# 
# 
# @app.post("/api/projects/{project_id}/batches")
# async def register_project_batch(project_id: str, payload: BatchRequest) -> Dict[str, Any]:
#     try:
#         state = lifecycle().register_batch(project_id, payload.model_dump(), payload.idempotency_key)
#     except KeyError:
#         raise HTTPException(404, "project 없음")
#     except ValueError as exc:
#         raise HTTPException(409, str(exc))
#     return state.public()
# 
# 
# @app.post("/api/projects/{project_id}/lab-results")
# async def submit_project_lab_result(project_id: str, payload: LabResultRequest) -> Dict[str, Any]:
#     data = payload.model_dump()
#     if payload.notes:
#         parsed = await asyncio.to_thread(read_notes, payload.notes, ROOT)
#         data["measurements"] = {**parsed.measurements, **payload.measurements}
#         data["observations"] = [*parsed.observations, *payload.observations]
#         data["parser_confidence"] = 1.0 if not parsed.unreadable else 0.7
#     try:
#         state = lifecycle().submit_results(project_id, data, payload.idempotency_key)
#     except KeyError:
#         raise HTTPException(404, "project 없음")
#     except ValueError as exc:
#         raise HTTPException(409, str(exc))
#     return state.public()
# 
# 
# async def _diagnosis_for(project_id: str, result_id: str,
#                          corrections: Dict[str, float]) -> Optional[Dict[str, Any]]:
#     state = lifecycle().state(project_id)
#     result = state.results.get(result_id)
#     if not result:
#         return None
#     measurements = corrections or result.get("measurements", {})
#     specs = state.candidate_specs.get(result["candidate_id"], [])
#     evaluations = lifecycle().spec_engine.evaluate(specs, measurements)
#     failed = [row for row in evaluations if not row["passed"]]
#     if not failed:
#         return None
#     by_metric = {spec.metric: spec for spec in specs}
#     findings = []
#     for row in evaluations:
#         spec = by_metric[row["metric"]]
#         findings.append(FeedbackFinding(
#             metric=row["metric"], measured=row["measured"], operator=spec.operator,
#             target=spec.target_value, off_target=not row["passed"],
#             interpretation=spec.justification if not row["passed"] else "",
#         ))
#     report = FeedbackReport(candidate_id=result["candidate_id"], findings=findings,
#                             reflection_needed=True, summary="후보별 CQA 이탈 진단")
#     directive = await asyncio.to_thread(
#         direct_next, report, ROOT, result.get("observations", []),
#     )
#     # direct_next()는 서로 다른 원인을 설명하는 가설을 배열로 낸다(가설당 그것만 가르는
#     # 시험이 붙어 있다) — 한 가설 문장을 지표 수만큼 복제하지 않는다. 가설이 하나도 안
#     # 남았으면(예: 시험 카탈로그와 못 붙음) None을 반환해 호출부가 lifecycle의 최종
#     # 폴백(_fallback_diagnosis)으로 넘어가게 한다.
#     raw_hypotheses = directive.get("hypotheses") or []
#     if not raw_hypotheses:
#         return None
#     hypotheses = []
#     for index, h in enumerate(raw_hypotheses, 1):
#         supports = h.get("supports") or []
#         primary_spec = next((by_metric[m] for m in supports if m in by_metric), None)
#         hypotheses.append({
#             "hypothesis_id": f"H{index}",
#             "statement": h.get("statement") or "이탈 원인을 구별해야 합니다.",
#             "supports": supports, "contradicts": [],
#             "missing_evidence": h.get("discriminating_test_ids", []),
#             "discriminating_test_ids": h.get("discriminating_test_ids", []),
#             "revision_hint": primary_spec.justification if primary_spec else h.get("statement", ""),
#             "status": "PROPOSED",
#         })
#     return {"hypotheses": hypotheses, "test_catalog": directive.get("experiments", []),
#             "agent_source": directive.get("source", "deterministic-fallback")}
# 
# 
# @app.post("/api/projects/{project_id}/lab-results/{result_id}/confirm")
# async def confirm_project_lab_result(project_id: str, result_id: str,
#                                      payload: ResultConfirmRequest) -> Dict[str, Any]:
#     try:
#         diagnosis = await _diagnosis_for(project_id, result_id, payload.measurements)
#         state = lifecycle().confirm_results(
#             project_id, result_id, payload.researcher, payload.measurements or None,
#             diagnosis, payload.idempotency_key,
#         )
#     except KeyError:
#         raise HTTPException(404, "project 또는 result 없음")
#     except ValueError as exc:
#         raise HTTPException(409, str(exc))
#     return state.public()
# 
# 
# @app.post("/api/projects/{project_id}/diagnoses/{diagnosis_id}/approve-tests")
# async def approve_project_tests(project_id: str, diagnosis_id: str,
#                                 payload: TestApprovalRequest) -> Dict[str, Any]:
#     try:
#         state = lifecycle().approve_tests(project_id, diagnosis_id, payload.test_ids,
#                                           payload.researcher, payload.idempotency_key)
#     except KeyError:
#         raise HTTPException(404, "project 또는 diagnosis 없음")
#     except ValueError as exc:
#         raise HTTPException(409, str(exc))
#     return state.public()
# 
# 
# @app.post("/api/projects/{project_id}/causes/{cause_id}/confirm")
# async def confirm_project_cause(project_id: str, cause_id: str,
#                                 payload: CauseConfirmRequest) -> Dict[str, Any]:
#     try:
#         state = lifecycle().confirm_cause(project_id, cause_id, payload.researcher,
#                                           payload.backtrack_target, payload.idempotency_key)
#         placeholder = state.active_candidate_id or ""
#         record = state.candidates[placeholder]
#         execution = RUNS.get(state.run_id)
#         if execution is None:
#             # 원인·변경안·자식 후보는 이미 영속화됐다. 기존 설계 컨텍스트가 메모리에 없으면
#             # 과학적 입력을 추정하지 않고 명시적으로 재실행을 요청한다.
#             # 저장된 REFLECTING 상태와 RevisionDirective를 그대로 돌려준다. 새 프로세스에서
#             # 임의로 원 후보를 복원하지 않고, 사용자가 design-runs를 재개하면 이어서 처리한다.
#             return state.public()
#         recipe, gate_result, assessment = await asyncio.to_thread(
#             execution.regenerate_child, record["parent_candidate_id"], placeholder,
#             record["revision_directive"],
#         )
#         state = lifecycle().sync_child(state.run_id, placeholder, recipe, gate_result, assessment)
#     except KeyError:
#         raise HTTPException(404, "project 또는 cause 없음")
#     except ValueError as exc:
#         raise HTTPException(409, str(exc))
#     return state.public()


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
    # 07_doe (ExperimentalDevelopmentGraph) 규칙
    rule = development().rb.by_id.get(rule_id)
    if rule:
        return {"rule_id": rule_id, "rulebook_id": rule.rulebook_id, "file": f"database/07_doe/{rule.file}",
                "layer": "07_doe", "strategy": "ast_whitelist_v1",
                "polarity": "fail_when", "row": rule.row, "sources_doc": "database/07_doe/masters/statistical_sources.csv"}
    raise HTTPException(404, f"규칙 {rule_id} 없음")


def _sources_for(rule_file: str) -> Optional[str]:
    """규칙 CSV와 같은 폴더의 *_SOURCES.md 경로를 찾는다."""
    folder = (ROOT / rule_file).parent
    candidates = sorted(folder.glob("*_SOURCES.md"))
    return str(candidates[0].relative_to(ROOT)) if candidates else None


# # ---------------------------------------------------------------------------
# # 실험 전 루프 — 근거 충족 게이트 (확인시험 요청 → 결과 입력 → 재평가 → 승인)
# #
# # 이 루프는 그래프를 다시 돌리지 않는다. 근거 판정은 결정론이라 새로 들어온 확인시험
# # 결과만 얹으면 같은 계산이 다시 나오기 때문이다(LLM 호출 0회).
# # ---------------------------------------------------------------------------
# def _require_run(run_id: str) -> Run:
#     execution = RUNS.get(run_id)
#     if execution is None:
#         raise HTTPException(404, "run 없음")
#     return execution
# 
# 
# def _evidence_payload(execution: Run, assessment) -> Dict[str, Any]:
#     return {
#         **assessment.model_dump(mode="json"),
#         "protocol": execution.evidence_gate.protocol(assessment),
#     }
# 
# 
# @app.get("/api/runs/{run_id}/evidence")
# async def get_evidence(run_id: str) -> Dict[str, Any]:
#     """후보별 근거 충족 판정과 확인시험 프로토콜."""
#     execution = _require_run(run_id)
#     # 실행이 끝나기 전에도 조회된다 — 근거 노드가 판정한 즉시 store에 쌓이므로 그걸 먼저 본다.
#     assessments = {**(execution.final.get("evidence") or {}),
#                    **{cid: entry["assessment"] for cid, entry in execution.evidence_store.items()}}
#     return {
#         "run_id": run_id,
#         "winner": execution.final.get("final_candidate"),
#         "candidates": {cid: _evidence_payload(execution, a) for cid, a in assessments.items()},
#     }
# 
# 
# @app.post("/api/runs/{run_id}/confirmation")
# async def submit_confirmation(run_id: str, payload: ConfirmationRequest) -> Dict[str, Any]:
#     """확인시험 결과를 넣고 근거 판정을 다시 계산한다 (실행 전 루프의 되먹임).
# 
#     결과가 '부적합'이면 그 전략은 배제된다 — 근거가 전제를 부정했는데 프로토콜을 내보내는
#     것이 가장 위험하므로, 상태를 실행 불가로 유지하고 재설계가 필요하다고 알린다.
#     """
#     execution = _require_run(run_id)
#     candidate_id = payload.candidate_id or execution.final.get("final_candidate") or ""
#     if not payload.entries:
#         raise HTTPException(422, "확인시험 결과가 비어 있습니다.")
# 
#     known = {gap.requirement_id for gap in
#              (execution.assessment(candidate_id).gaps if execution.assessment(candidate_id) else [])}
#     if not known:
#         raise HTTPException(404, "이 후보의 근거 판정을 찾지 못했습니다. 먼저 설계를 실행해 주세요.")
# 
#     store = execution.confirmations.setdefault(candidate_id, {})
#     unknown: List[str] = []
#     for entry in payload.entries:
#         if entry.requirement_id not in known:
#             unknown.append(entry.requirement_id)   # 이 후보에 요구되지 않은 항목은 받지 않는다
#             continue
#         store[entry.requirement_id] = ConfirmationResult(**entry.model_dump())
#     if not store:
#         raise HTTPException(422, f"이 후보에 해당하지 않는 항목입니다: {', '.join(unknown)}")
# 
#     try:
#         assessment = execution.reassess(candidate_id)
#     except KeyError:
#         raise HTTPException(404, "후보를 찾지 못했습니다.")
# 
#     result = {
#         **_evidence_payload(execution, assessment),
#         "unknown_requirements": unknown,
#         # 결과가 실제로 입력 계층의 어느 실측값 자리에 꽂혔는지 — 되먹임의 증거.
#         "applied_measurements": execution.applied_results.get(candidate_id, {}),
#     }
#     execution.bus.publish(TraceEvent(run_id=run_id, node="evidence",
#                                      kind=EventKind.CONFIRMATION, payload=result))
#     try:
#         lifecycle().sync_evidence(run_id, candidate_id, assessment)
#     except KeyError:
#         pass  # 구버전 인메모리 run은 장기 프로젝트가 없을 수 있다.
#     return result
# 
# 
# @app.post("/api/runs/{run_id}/approve")
# async def approve_protocol(run_id: str, payload: ApprovalRequest) -> Dict[str, Any]:
#     """연구자 승인 — 근거가 충족된 후보만 실행 가능 공정 프로토콜로 전환한다."""
#     execution = _require_run(run_id)
#     candidate_id = payload.candidate_id or execution.final.get("final_candidate") or ""
#     try:
#         assessment = execution.approve(candidate_id, payload.approver)
#     except KeyError:
#         raise HTTPException(404, "후보를 찾지 못했습니다.")
#     except ValueError as exc:
#         # 근거가 비어 있는데 승인되면 이 게이트 자체가 무의미해진다 → 409로 거절.
#         raise HTTPException(409, str(exc))
# 
#     result = _evidence_payload(execution, assessment)
#     project = lifecycle().store.by_run(run_id)
#     if project:
#         try:
#             # EvidenceGate의 승인과 실행 프로토콜 승인은 별개지만, 기존 단일 버튼은 두
#             # 검토를 연속 수행하는 하위호환 경로로 유지한다.
#             project = lifecycle().sync_evidence(run_id, candidate_id, assessment)
#             protocol_id = next((pid for pid, p in reversed(list(project.protocols.items()))
#                                 if p.get("candidate_id") == candidate_id), "")
#             if project.status == WorkflowStatus.WAITING_FOR_APPROVAL and protocol_id:
#                 project = lifecycle().approve_protocol(project.project_id, payload.approver, protocol_id)
#             result["workflow"] = project.public()
#         except ValueError as exc:
#             raise HTTPException(409, str(exc))
#     execution.bus.publish(TraceEvent(run_id=run_id, node="evidence",
#                                      kind=EventKind.APPROVAL, payload=result))
#     return result
# 
# 
# # ---------------------------------------------------------------------------
# # 실험 후 루프 — Lab-in-the-loop (판독 → 판정 → 다음 실험 지시)
# # ---------------------------------------------------------------------------
# @app.post("/api/runs/{run_id}/wetlab")
# async def submit_wetlab(run_id: str, payload: WetLabRequest) -> Dict[str, Any]:
#     """배치 결과 한 바퀴: 자연어 판독 → 결정론 판정 → 다음 실험 지시.
# 
#     `notes`에 실험 노트를 자연어로 넣으면 거기서 측정값을 뽑아내고, 폼으로 넣은
#     `measurements`가 있으면 그 값이 판독값을 덮는다(사람이 명시한 값이 우선).
# 
#     입력은 **배치를 이미 만든 뒤**의 결과다. 승인 전 프로토콜로 만든 배치라면 그 사실을
#     응답에 남긴다 — 판정은 그대로 하되, 어떤 상태의 프로토콜에서 나온 데이터인지가
#     기록에 함께 남아야 한다.
#     """
#     rules = ROOT / "database" / "legacy" / "wetlab_feedback_rules.csv"
#     if not rules.exists():
#         raise HTTPException(500, "wetlab_feedback_rules.csv 없음")
# 
#     # 1) 판독 (LLM) — 문장에 적힌 수치만 옮긴다
#     read = await asyncio.to_thread(read_notes, payload.notes, ROOT)
#     measurements = {**read.measurements, **payload.measurements}
#     if not measurements:
#         raise HTTPException(
#             422,
#             "실험 결과에서 측정값을 읽지 못했습니다. "
#             "예: '용출 30분 62%, 경도 38N, 불순물 0.9%' 처럼 지표와 수치를 함께 적어 주세요.",
#         )
# 
#     # 2) 판정 (규칙) — 같은 데이터면 항상 같은 해석
#     interpreter = WetLabInterpreter(rules)
#     report = interpreter.interpret(
#         WetLabResult(candidate_id=payload.candidate_id or run_id,
#                      measurements=measurements, notes=payload.notes)
#     )
# 
#     # 3) 지시 (LLM + 확인시험 마스터 66종) — 후보 밖의 시험은 발명하지 못한다
#     directive = await asyncio.to_thread(direct_next, report, ROOT, read.observations)
# 
#     result: Dict[str, Any] = {
#         **report.model_dump(),
#         "read": read.model_dump(),
#         "directive": directive,
#     }
#     execution = RUNS.get(run_id)
#     if execution is not None:
#         assessment = execution.assessment(payload.candidate_id
#                                           or execution.final.get("final_candidate") or "")
#         result["protocol_state"] = assessment.readiness.value if assessment else "unknown"
#         execution.bus.publish(TraceEvent(run_id=run_id, node="labloop",
#                                          kind=EventKind.WETLAB, payload=result))
#     return result


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
