"""Formula 1 장기 실행 상태기계.

오케스트레이터가 과학적 판단을 만들지 않도록, 이 파일은 상태·권한·재시도 예산만 다룬다.
규격 비교는 CandidateSpecEngine, 프로토콜 검증은 ProtocolValidator가 맡는다.
"""

from __future__ import annotations

import copy
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import CandidateSpec, EventEnvelope, ProjectState, WorkflowStatus
from .protocol import ProtocolCompiler, ProtocolValidator
from .spec_engine import CandidateSpecEngine
from .store import WorkflowStore


DEFAULT_BUDGETS = {
    "rule_revision_attempt": 5,
    "evidence_round": 3,
    "lab_iteration": 5,
    "diagnostic_round": 3,
}


class LifecycleService:
    def __init__(self, base_dir: Path, store: Optional[WorkflowStore] = None):
        self.base_dir = Path(base_dir)
        self.store = store or WorkflowStore()
        self.spec_engine = CandidateSpecEngine(self.base_dir)
        self.compiler = ProtocolCompiler(self.base_dir)
        self.validator = ProtocolValidator()

    def create(self, request: str, run_id: str = "", qtpp: Optional[Dict[str, Any]] = None,
               project_id: str = "", idempotency_key: str = "") -> ProjectState:
        project_id = project_id or f"proj-{uuid.uuid4().hex[:12]}"
        existing = self.store.get(project_id)
        if existing:
            return existing
        state = ProjectState(project_id=project_id, run_id=run_id, request=request,
                             qtpp=qtpp or {},
                             pending_actions=[self._action("RUN_DESIGN", "설계 후보를 생성하고 검증합니다.")])
        event = self._event(state, "PROJECT_CREATED", {"request": request},
                            idempotency_key=idempotency_key)
        return self.store.create(state, event)

    def state(self, project_id: str) -> ProjectState:
        state = self.store.get(project_id)
        if state is None:
            raise KeyError(project_id)
        return state

    def bind_run(self, project_id: str, run_id: str) -> ProjectState:
        state = self.state(project_id)
        state.run_id = run_id
        state.status = WorkflowStatus.DESIGNING
        state.pending_actions = [self._action("WAIT_FOR_DESIGN", "설계 그래프 실행 결과를 기다립니다.")]
        return self._save(state, "DESIGN_RUN_STARTED", {"run_id": run_id})

    def sync_design(self, execution: Any) -> ProjectState:
        state = self.store.by_run(execution.run_id)
        if state is None:
            state = self.create(execution.state.get("request", ""), run_id=execution.run_id)
        final = execution.final or {}
        status = str(final.get("status") or "")
        if status in {"infeasible", "exhausted", "escalated", "error"}:
            state.status = (WorkflowStatus.INFEASIBLE if status == "infeasible"
                            else WorkflowStatus.ESCALATED)
            state.pending_actions = [self._action("HUMAN_REVIEW", "자동 설계가 멈춘 이유를 검토합니다.")]
            return self._save(state, "HUMAN_ESCALATION_REQUESTED", {"design_status": status})

        for recipe in final.get("candidates", []):
            data = recipe.model_dump(mode="json") if hasattr(recipe, "model_dump") else dict(recipe)
            candidate_id = data.get("candidate_id") or f"cand-{uuid.uuid4().hex[:8]}"
            old = state.candidates.get(candidate_id, {})
            state.candidates[candidate_id] = {
                "candidate_id": candidate_id,
                "parent_candidate_id": old.get("parent_candidate_id"),
                "version": int(old.get("version", 1)),
                "recipe": data,
                "status": "VALIDATED",
                "created_at": old.get("created_at", time.time()),
            }
            state.candidate_specs.setdefault(candidate_id, self.spec_engine.snapshot(candidate_id))

        winner = final.get("final_candidate")
        if not winner or winner not in state.candidates:
            state.status = WorkflowStatus.ESCALATED
            state.pending_actions = [self._action("HUMAN_REVIEW", "권고 후보가 없어 설계 결과를 검토합니다.")]
            return self._save(state, "HUMAN_ESCALATION_REQUESTED", {"reason": "no_winner"})

        state.active_candidate_id = winner
        assessment = execution.assessment(winner)
        if assessment and assessment.blocking:
            state.status = WorkflowStatus.WAITING_FOR_EVIDENCE
            state.pending_actions = [self._action(
                "SUBMIT_EVIDENCE", "실행 전 필수 근거를 확인시험으로 채웁니다.",
                {"candidate_id": winner, "gaps": [g.model_dump(mode="json") for g in assessment.blocking]},
            )]
        else:
            self._compile(state, winner)
        return self._save(state, "DESIGN_RUN_COMPLETED", {
            "candidate_id": winner,
            "candidate_count": len(state.candidates),
            "rule_gate": "passed",
            "evidence_readiness": getattr(getattr(assessment, "readiness", None), "value", "unknown"),
        }, candidate_id=winner)

    def sync_evidence(self, run_id: str, candidate_id: str, assessment: Any) -> ProjectState:
        state = self._by_run_required(run_id)
        state.evidence_round += 1
        if state.evidence_round > DEFAULT_BUDGETS["evidence_round"]:
            state.status = WorkflowStatus.ESCALATED
            state.pending_actions = [self._action("HUMAN_REVIEW", "근거 확인 라운드 한도를 넘었습니다.")]
            return self._save(state, "HUMAN_ESCALATION_REQUESTED", {"loop": "evidence_round"})
        if assessment.blocking:
            state.status = WorkflowStatus.WAITING_FOR_EVIDENCE
            state.pending_actions = [self._action(
                "SUBMIT_EVIDENCE", "남은 실행 전 근거를 확인합니다.",
                {"candidate_id": candidate_id,
                 "gaps": [g.model_dump(mode="json") for g in assessment.blocking]},
            )]
        else:
            reusable = next((p for p in state.protocols.values()
                             if p.get("candidate_id") == candidate_id
                             and p.get("status") in {"READY_FOR_REVIEW", "APPROVED"}), None)
            if reusable:
                state.status = (WorkflowStatus.READY_FOR_LAB if reusable["status"] == "APPROVED"
                                else WorkflowStatus.WAITING_FOR_APPROVAL)
                state.pending_actions = ([] if reusable["status"] == "APPROVED" else [self._action(
                    "APPROVE_PROTOCOL", "연구자가 프로토콜과 잔여 위험을 검토합니다.",
                    {"protocol_id": reusable["protocol_id"]},
                )])
            else:
                self._compile(state, candidate_id)
        return self._save(state, "EVIDENCE_RESULT_CONFIRMED", {
            "candidate_id": candidate_id,
            "readiness": assessment.readiness.value,
            "remaining_blocking": len(assessment.blocking),
        }, candidate_id=candidate_id)

    def approve_protocol(self, project_id: str, approver: str,
                         protocol_id: str = "", idempotency_key: str = "") -> ProjectState:
        duplicate = self.store.project_for_idempotency(idempotency_key)
        if duplicate:
            return duplicate
        state = self.state(project_id)
        if state.status != WorkflowStatus.WAITING_FOR_APPROVAL:
            raise ValueError("검증 완료된 프로토콜만 승인할 수 있습니다.")
        protocol = self._protocol(state, protocol_id)
        if protocol.get("validation", {}).get("status") != "READY_FOR_REVIEW":
            raise ValueError("Protocol Validator를 통과하지 못했습니다.")
        protocol["status"] = "APPROVED"
        protocol["approved_by"] = approver
        protocol["approved_at"] = time.time()
        state.status = WorkflowStatus.READY_FOR_LAB
        state.pending_actions = [self._action(
            "REGISTER_BATCH", "승인된 프로토콜로 만든 실제 배치를 등록합니다.",
            {"protocol_id": protocol["protocol_id"]},
        )]
        return self._save(state, "PROTOCOL_APPROVED", {
            "protocol_id": protocol["protocol_id"], "approver": approver,
        }, candidate_id=protocol["candidate_id"], protocol_version=protocol["version"],
           idempotency_key=idempotency_key, actor={"type": "researcher", "id": approver})

    def register_batch(self, project_id: str, payload: Dict[str, Any],
                       idempotency_key: str = "") -> ProjectState:
        duplicate = self.store.project_for_idempotency(idempotency_key)
        if duplicate:
            return duplicate
        state = self.state(project_id)
        if state.status != WorkflowStatus.READY_FOR_LAB:
            raise ValueError("승인된 프로토콜이 있어야 배치를 등록할 수 있습니다.")
        if state.lab_iteration >= DEFAULT_BUDGETS["lab_iteration"]:
            state.status = WorkflowStatus.ESCALATED
            state.pending_actions = [self._action("HUMAN_REVIEW", "배치 반복 한도를 넘었습니다.")]
            return self._save(state, "HUMAN_ESCALATION_REQUESTED", {"loop": "lab_iteration"})
        protocol = self._protocol(state, str(payload.get("protocol_id") or ""))
        if protocol.get("status") != "APPROVED":
            raise ValueError("승인되지 않은 프로토콜로 배치를 등록할 수 없습니다.")
        batch_id = str(payload.get("batch_id") or f"batch-{uuid.uuid4().hex[:12]}")
        if batch_id in state.batches:
            raise ValueError("이미 등록된 batch_id입니다.")
        state.lab_iteration += 1
        state.batches[batch_id] = {
            "batch_id": batch_id,
            "candidate_id": protocol["candidate_id"],
            "protocol_id": protocol["protocol_id"],
            "protocol_version": protocol["version"],
            "status": "REGISTERED",
            "note": str(payload.get("note") or ""),
            "created_at": time.time(),
        }
        state.status = WorkflowStatus.WAITING_FOR_RESULT
        state.pending_actions = [self._action(
            "SUBMIT_LAB_RESULT", "이 배치의 원자료·수치·관찰을 입력합니다.", {"batch_id": batch_id},
        )]
        return self._save(state, "BATCH_REGISTERED", state.batches[batch_id],
                          candidate_id=protocol["candidate_id"], batch_id=batch_id,
                          protocol_version=protocol["version"], idempotency_key=idempotency_key)

    def submit_results(self, project_id: str, payload: Dict[str, Any],
                       idempotency_key: str = "") -> ProjectState:
        duplicate = self.store.project_for_idempotency(idempotency_key)
        if duplicate:
            return duplicate
        state = self.state(project_id)
        if state.status not in {WorkflowStatus.WAITING_FOR_RESULT,
                                WorkflowStatus.WAITING_FOR_CONFIRMATION_TEST}:
            raise ValueError("현재 상태에서는 실험결과를 제출할 수 없습니다.")
        batch_id = str(payload.get("batch_id") or "")
        if batch_id not in state.batches:
            raise ValueError("등록된 batch_id가 아닙니다.")
        measurements = {str(k): float(v) for k, v in (payload.get("measurements") or {}).items()}
        if not measurements and not payload.get("observations"):
            raise ValueError("측정값 또는 관찰이 하나 이상 필요합니다.")
        result_id = str(payload.get("result_id") or f"result-{uuid.uuid4().hex[:12]}")
        state.results[result_id] = {
            "result_id": result_id,
            "batch_id": batch_id,
            "candidate_id": state.batches[batch_id]["candidate_id"],
            "purpose": str(payload.get("purpose") or "batch_cqa"),
            "hypothesis_id": str(payload.get("hypothesis_id") or ""),
            "measurements": measurements,
            "observations": list(payload.get("observations") or []),
            "raw_data_refs": list(payload.get("raw_data_refs") or []),
            "method_refs": dict(payload.get("method_refs") or {}),
            "human_verification_status": "PROPOSED",
            "parser_confidence": payload.get("parser_confidence"),
            "created_at": time.time(),
        }
        state.status = WorkflowStatus.RESULT_CONFIRMATION
        state.pending_actions = [self._action(
            "CONFIRM_LAB_RESULT", "AI가 옮긴 값·단위·시험법을 연구자가 원자료와 대조합니다.",
            {"result_id": result_id},
        )]
        return self._save(state, "LAB_RESULT_SUBMITTED", {"result_id": result_id,
                          "human_verification_status": "PROPOSED"},
                          candidate_id=state.results[result_id]["candidate_id"], batch_id=batch_id,
                          idempotency_key=idempotency_key)

    def confirm_results(self, project_id: str, result_id: str, researcher: str,
                        corrections: Optional[Dict[str, float]] = None,
                        diagnosis: Optional[Dict[str, Any]] = None,
                        idempotency_key: str = "") -> ProjectState:
        duplicate = self.store.project_for_idempotency(idempotency_key)
        if duplicate:
            return duplicate
        state = self.state(project_id)
        result = state.results.get(result_id)
        if result is None:
            raise KeyError(result_id)
        if state.status != WorkflowStatus.RESULT_CONFIRMATION:
            raise ValueError("결과 확인 대기 상태가 아닙니다.")
        if corrections:
            result["measurements"] = {str(k): float(v) for k, v in corrections.items()}
        result["human_verification_status"] = "CONFIRMED"
        result["confirmed_by"] = researcher
        result["confirmed_at"] = time.time()
        candidate_id = result["candidate_id"]
        if result.get("purpose") == "confirmation_test":
            hypothesis_id = result.get("hypothesis_id")
            if not hypothesis_id:
                raise ValueError("확인시험 결과에는 hypothesis_id가 필요합니다.")
            diagnosis, hypothesis = self._find_hypothesis(state, hypothesis_id)
            if diagnosis.get("status") != "TESTS_APPROVED":
                raise ValueError("승인된 확인시험 계획에 대한 결과가 아닙니다.")
            hypothesis["confirmation_result_id"] = result_id
            hypothesis["status"] = "EVIDENCE_RECEIVED"
            diagnosis["status"] = "EVIDENCE_RECEIVED"
            state.status = WorkflowStatus.DIAGNOSING
            state.pending_actions = [self._action(
                "CONFIRM_ROOT_CAUSE",
                "확인시험 결과가 가설을 지지하는지 연구자가 검토해 원인을 확정하거나 기각합니다.",
                {"diagnosis_id": diagnosis["diagnosis_id"], "hypothesis_id": hypothesis_id,
                 "result_id": result_id},
            )]
            return self._save(state, "LAB_RESULT_CONFIRMED", {
                "result_id": result_id, "purpose": "confirmation_test",
                "hypothesis_id": hypothesis_id, "human_verification_status": "CONFIRMED",
            }, candidate_id=candidate_id, batch_id=result["batch_id"],
               idempotency_key=idempotency_key,
               actor={"type": "researcher", "id": researcher})
        specs = state.candidate_specs.get(candidate_id, [])
        evaluations = self.spec_engine.evaluate(specs, result["measurements"])
        result["spec_evaluations"] = evaluations
        failed = [row for row in evaluations if not row["passed"]]
        if not failed:
            state.status = WorkflowStatus.COMPLETED
            state.pending_actions = []
            event_type = "PROJECT_COMPLETED"
        else:
            state.status = WorkflowStatus.DIAGNOSING
            state.diagnostic_round += 1
            if state.diagnostic_round > DEFAULT_BUDGETS["diagnostic_round"]:
                state.status = WorkflowStatus.ESCALATED
                state.pending_actions = [self._action("HUMAN_REVIEW", "진단 라운드 한도를 넘었습니다.")]
                event_type = "HUMAN_ESCALATION_REQUESTED"
            else:
                diag = diagnosis or self._fallback_diagnosis(failed)
                diagnosis_id = str(diag.get("diagnosis_id") or f"diag-{uuid.uuid4().hex[:10]}")
                diag["diagnosis_id"] = diagnosis_id
                diag["result_id"] = result_id
                diag["status"] = "PROPOSED"
                state.diagnoses[diagnosis_id] = diag
                state.pending_actions = [self._action(
                    "APPROVE_CONFIRMATION_TEST", "첫 실패에서는 처방을 바꾸지 않습니다. 경쟁 가설을 구별할 시험을 승인합니다.",
                    {"diagnosis_id": diagnosis_id, "hypotheses": diag.get("hypotheses", [])},
                )]
                event_type = "DIAGNOSIS_PROPOSED"
        return self._save(state, event_type, {
            "result_id": result_id, "failed_cqas": [f["metric"] for f in failed],
            "human_verification_status": "CONFIRMED",
        }, candidate_id=candidate_id, batch_id=result["batch_id"],
           idempotency_key=idempotency_key, actor={"type": "researcher", "id": researcher})

    def approve_tests(self, project_id: str, diagnosis_id: str, test_ids: List[str],
                      researcher: str, idempotency_key: str = "") -> ProjectState:
        duplicate = self.store.project_for_idempotency(idempotency_key)
        if duplicate:
            return duplicate
        state = self.state(project_id)
        diagnosis = state.diagnoses.get(diagnosis_id)
        if diagnosis is None:
            raise KeyError(diagnosis_id)
        allowed = {test for h in diagnosis.get("hypotheses", [])
                   for test in h.get("discriminating_test_ids", [])}
        selected = [test for test in test_ids if test in allowed]
        if not selected:
            raise ValueError("진단 가설에 등록된 확인시험만 승인할 수 있습니다.")
        diagnosis["approved_test_ids"] = selected
        diagnosis["status"] = "TESTS_APPROVED"
        state.status = WorkflowStatus.WAITING_FOR_CONFIRMATION_TEST
        state.pending_actions = [self._action(
            "RUN_CONFIRMATION_TEST", "승인된 구별시험을 수행하고 결과를 입력합니다.",
            {"diagnosis_id": diagnosis_id, "test_ids": selected},
        )]
        return self._save(state, "CONFIRMATION_TEST_APPROVED", {
            "diagnosis_id": diagnosis_id, "test_ids": selected,
        }, idempotency_key=idempotency_key, actor={"type": "researcher", "id": researcher})

    def confirm_cause(self, project_id: str, cause_id: str, researcher: str,
                      backtrack_target: str = "PHASE_6_PROCESS",
                      idempotency_key: str = "") -> ProjectState:
        duplicate = self.store.project_for_idempotency(idempotency_key)
        if duplicate:
            return duplicate
        state = self.state(project_id)
        diagnosis, hypothesis = self._find_hypothesis(state, cause_id)
        if state.status not in {WorkflowStatus.DIAGNOSING,
                                WorkflowStatus.WAITING_FOR_CONFIRMATION_TEST}:
            raise ValueError("현재 상태에서는 원인을 확정할 수 없습니다.")
        hypothesis["status"] = "CONFIRMED"
        diagnosis["status"] = "CAUSE_CONFIRMED"
        parent_id = state.active_candidate_id or ""
        parent = state.candidates.get(parent_id)
        if parent is None:
            raise ValueError("활성 후보가 없습니다.")
        directive = {
            "source": "LAB_CONFIRMED_CAUSE",
            "cause_id": cause_id,
            "backtrack_target": backtrack_target,
            "changes": [{"field": "formulation_or_process",
                         "operation": "REQUEST_EVIDENCE_BOUNDED_CHANGE",
                         "bound_source": "confirmed-cause-and-rulebook"}],
            "reason_refs": [f"diagnosis:{diagnosis['diagnosis_id']}", f"hypothesis:{cause_id}"],
            "instruction": hypothesis.get("revision_hint") or hypothesis.get("statement"),
        }
        child_id = f"cand-lab-{state.lab_iteration + 1}-{uuid.uuid4().hex[:6]}"
        child = copy.deepcopy(parent)
        child.update({"candidate_id": child_id, "parent_candidate_id": parent_id,
                      "version": int(parent.get("version", 1)) + 1,
                      "status": "AWAITING_REGENERATION", "revision_directive": directive,
                      "created_at": time.time()})
        state.candidates[child_id] = child
        state.active_candidate_id = child_id
        state.status = WorkflowStatus.REFLECTING
        state.pending_actions = [self._action(
            "REGENERATE_CHILD", "확인된 원인만 반영해 자식 후보를 만들고 모든 게이트를 다시 실행합니다.",
            {"parent_candidate_id": parent_id, "child_candidate_id": child_id,
             "revision_directive": directive},
        )]
        return self._save(state, "ROOT_CAUSE_CONFIRMED", {
            "cause_id": cause_id, "child_candidate_id": child_id,
            "revision_directive": directive,
        }, candidate_id=parent_id, idempotency_key=idempotency_key,
           actor={"type": "researcher", "id": researcher})

    def sync_child(self, run_id: str, placeholder_id: str, recipe: Any,
                   gate_result: Dict[str, Any], assessment: Any) -> ProjectState:
        state = self._by_run_required(run_id)
        record = state.candidates.pop(placeholder_id)
        recipe_data = recipe.model_dump(mode="json") if hasattr(recipe, "model_dump") else dict(recipe)
        child_id = recipe_data.get("candidate_id") or placeholder_id
        record.update({"candidate_id": child_id, "recipe": recipe_data,
                       "status": "VALIDATED" if gate_result.get("passed") else "RULE_FAILED"})
        state.candidates[child_id] = record
        state.active_candidate_id = child_id
        state.candidate_specs[child_id] = self.spec_engine.snapshot(child_id)
        if not gate_result.get("passed"):
            state.rule_revision_attempt += 1
            if state.rule_revision_attempt >= DEFAULT_BUDGETS["rule_revision_attempt"]:
                state.status = WorkflowStatus.ESCALATED
                state.pending_actions = [self._action("HUMAN_REVIEW", "규칙 재설계 한도를 넘었습니다.")]
            else:
                state.status = WorkflowStatus.DESIGNING
                state.pending_actions = [self._action("REVISE_RULE_FAILURE", "규칙 위반 근거로 다시 설계합니다.")]
        elif assessment and assessment.blocking:
            state.status = WorkflowStatus.WAITING_FOR_EVIDENCE
            state.pending_actions = [self._action("SUBMIT_EVIDENCE", "자식 후보의 선행 근거를 채웁니다.")]
        else:
            self._compile(state, child_id)
        return self._save(state, "CHILD_CANDIDATE_CREATED", {
            "candidate_id": child_id, "parent_candidate_id": record.get("parent_candidate_id"),
            "rule_gate_passed": bool(gate_result.get("passed")),
            "evidence_gate_passed": not bool(assessment and assessment.blocking),
        }, candidate_id=child_id)

    def trace(self, project_id: str) -> Dict[str, Any]:
        state = self.state(project_id)
        return {"project_id": project_id, "state_version": state.state_version,
                "events": self.store.events(project_id),
                "decisions": self.store.decisions(project_id)}

    def _compile(self, state: ProjectState, candidate_id: str) -> None:
        candidate = state.candidates[candidate_id]
        specs = [s.model_dump(mode="json") if hasattr(s, "model_dump") else s
                 for s in state.candidate_specs.get(candidate_id, [])]
        protocol = self.compiler.compile(candidate, specs)
        protocol["validation"] = self.validator.validate(protocol)
        protocol["status"] = protocol["validation"]["status"]
        state.protocols[protocol["protocol_id"]] = protocol
        if protocol["status"] == "BLOCKED":
            state.status = WorkflowStatus.PROTOCOL_DRAFT
            state.pending_actions = [self._action(
                "RESOLVE_PROTOCOL_GAPS", "질량수지·중요변수·출처 누락을 보완합니다.",
                {"protocol_id": protocol["protocol_id"],
                 "errors": protocol["validation"]["errors"]},
            )]
        else:
            state.status = WorkflowStatus.WAITING_FOR_APPROVAL
            state.pending_actions = [self._action(
                "APPROVE_PROTOCOL", "연구자가 프로토콜과 잔여 위험을 검토합니다.",
                {"protocol_id": protocol["protocol_id"]},
            )]

    @staticmethod
    def _fallback_diagnosis(failed: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        mapping = {
            "dissolution_30min_percent": ("용출 저하에는 붕해 지연·젖음성·입도 영향이 경쟁 원인입니다.", ["T_DISS_PROFILE", "T_PSD_DISS"], "붕해·압축 조건과 가용화 전략을 근거 범위에서 재검토"),
            "tablet_hardness_N": ("타정압과 결합력의 균형이 목표 범위를 벗어났을 가능성입니다.", ["T_DISCRIM"], "타정압 또는 결합제 범위를 등록 설비 한계 안에서 조정"),
            "friability_percent": ("과립 결합력이나 압축 조건이 부족했을 가능성입니다.", ["T_DISCRIM"], "결합력과 압축 공정변수를 확인시험 결과에 따라 조정"),
            "impurity_total_percent": ("배합 상호작용·산화·수분 노출이 경쟁 원인입니다.", ["T_FORCED", "T_SPECIFICITY"], "확인된 분해 경로에 해당하는 성분 또는 포장만 변경"),
        }
        hypotheses = []
        for i, row in enumerate(failed[:3], 1):
            statement, tests, hint = mapping.get(row["metric"], (
                f"{row['metric']} 이탈의 공정·배합 원인을 구별해야 합니다.", ["T_METHOD_COMPARE"],
                "확인시험 결과가 지지하는 변수만 변경"))
            hypotheses.append({"hypothesis_id": f"H{i}", "statement": statement,
                               "supports": [row["metric"]], "contradicts": [],
                               "missing_evidence": tests, "discriminating_test_ids": tests,
                               "revision_hint": hint, "status": "PROPOSED"})
        return {"hypotheses": hypotheses}

    def _protocol(self, state: ProjectState, protocol_id: str) -> Dict[str, Any]:
        if protocol_id:
            protocol = state.protocols.get(protocol_id)
        else:
            protocol = next((p for p in reversed(list(state.protocols.values()))
                             if p.get("candidate_id") == state.active_candidate_id), None)
        if protocol is None:
            raise ValueError("프로토콜을 찾지 못했습니다.")
        return protocol

    @staticmethod
    def _find_hypothesis(state: ProjectState, cause_id: str):
        for diagnosis in state.diagnoses.values():
            for hypothesis in diagnosis.get("hypotheses", []):
                if hypothesis.get("hypothesis_id") == cause_id:
                    return diagnosis, hypothesis
        raise KeyError(cause_id)

    def _by_run_required(self, run_id: str) -> ProjectState:
        state = self.store.by_run(run_id)
        if state is None:
            raise KeyError(run_id)
        return state

    def _save(self, state: ProjectState, event_type: str, payload: Dict[str, Any],
              candidate_id: str = "", batch_id: str = "", protocol_version: Optional[int] = None,
              idempotency_key: str = "", actor: Optional[Dict[str, str]] = None) -> ProjectState:
        expected = state.state_version
        event = self._event(state, event_type, payload, candidate_id, batch_id,
                            protocol_version, idempotency_key, actor)
        decision_id = self.store.decision(state.project_id, event_type, {
            "event_id": event.event_id, "status": state.status.value,
            "candidate_id": candidate_id, "inputs": payload,
            "ruleset": "rulebook_manifest.yaml", "schema_version": "1.0",
        })
        state.decision_refs.append(decision_id)
        saved, _ = self.store.save(state, event, expected_version=expected)
        return saved

    @staticmethod
    def _event(state: ProjectState, event_type: str, payload: Dict[str, Any],
               candidate_id: str = "", batch_id: str = "",
               protocol_version: Optional[int] = None, idempotency_key: str = "",
               actor: Optional[Dict[str, str]] = None) -> EventEnvelope:
        return EventEnvelope(event_type=event_type, project_id=state.project_id,
                             run_id=state.run_id, candidate_id=candidate_id,
                             batch_id=batch_id, protocol_version=protocol_version,
                             payload=payload, idempotency_key=idempotency_key or uuid.uuid4().hex,
                             created_by=actor or {"type": "system", "id": "orchestrator"})

    @staticmethod
    def _action(action_type: str, label: str,
                context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"action_id": f"act-{uuid.uuid4().hex[:10]}", "type": action_type,
                "label": label, "context": context or {}, "created_at": time.time()}
