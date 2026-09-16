from pathlib import Path

from formula.contracts import EvidenceAssessment, Ingredient, ProtocolReadiness, Recipe
from formula.lifecycle import LifecycleService, WorkflowStatus, WorkflowStore


ROOT = Path(__file__).resolve().parents[1]


class _Execution:
    def __init__(self, recipe, assessment):
        self.run_id = "run-lifecycle-test"
        self.state = {"request": "성인용 IR 정제"}
        self.final = {
            "status": "passed",
            "candidates": [recipe],
            "final_candidate": recipe.candidate_id,
        }
        self._assessment = assessment

    def assessment(self, candidate_id):
        return self._assessment if candidate_id == self._assessment.candidate_id else None


def _service(tmp_path):
    return LifecycleService(ROOT, WorkflowStore(tmp_path / "workflow.db"))


def _execution():
    recipe = Recipe(
        api_name="Example API", candidate_id="cand-1", strategy="DC",
        process="direct_compression",
        ingredients=[
            Ingredient(name="Example API", role="api", amount_mg=100, percent=40),
            Ingredient(name="Mannitol", role="diluent", amount_mg=140, percent=56),
            Ingredient(name="Magnesium stearate", role="lubricant", amount_mg=10, percent=4),
        ],
    )
    assessment = EvidenceAssessment(
        candidate_id="cand-1", strategy="DC", process="direct_compression",
        readiness=ProtocolReadiness.READY_FOR_REVIEW, gaps=[],
    )
    return _Execution(recipe, assessment)


def test_long_running_lab_loop_requires_confirmation_before_diagnosis(tmp_path):
    service = _service(tmp_path)
    service.create("성인용 IR 정제", run_id="run-lifecycle-test", project_id="proj-1")
    state = service.sync_design(_execution())
    assert state.status is WorkflowStatus.WAITING_FOR_APPROVAL
    protocol_id = next(iter(state.protocols))
    assert state.protocols[protocol_id]["validation"]["status"] == "READY_FOR_REVIEW"

    state = service.approve_protocol("proj-1", "researcher-1", protocol_id)
    assert state.status is WorkflowStatus.READY_FOR_LAB
    state = service.register_batch("proj-1", {
        "protocol_id": protocol_id, "batch_id": "batch-1",
    })
    assert state.status is WorkflowStatus.WAITING_FOR_RESULT

    state = service.submit_results("proj-1", {
        "batch_id": "batch-1", "result_id": "result-1",
        "measurements": {"dissolution_30min_percent": 62.0},
    })
    assert state.status is WorkflowStatus.RESULT_CONFIRMATION
    assert state.results["result-1"]["human_verification_status"] == "PROPOSED"
    assert "spec_evaluations" not in state.results["result-1"]

    state = service.confirm_results("proj-1", "result-1", "researcher-1")
    assert state.status is WorkflowStatus.DIAGNOSING
    assert state.results["result-1"]["spec_evaluations"][0]["passed"] is False
    assert state.active_candidate_id == "cand-1"  # 첫 실패에서 처방 변경 금지
    diagnosis = next(iter(state.diagnoses.values()))
    assert 1 <= len(diagnosis["hypotheses"]) <= 3


def test_confirmed_cause_creates_versioned_child_and_keeps_parent(tmp_path):
    service = _service(tmp_path)
    service.create("성인용 IR 정제", run_id="run-lifecycle-test", project_id="proj-2")
    state = service.sync_design(_execution())
    protocol_id = next(iter(state.protocols))
    service.approve_protocol("proj-2", "researcher-1", protocol_id)
    service.register_batch("proj-2", {"protocol_id": protocol_id, "batch_id": "batch-1"})
    service.submit_results("proj-2", {
        "batch_id": "batch-1", "result_id": "result-1",
        "measurements": {"dissolution_30min_percent": 62.0},
    })
    state = service.confirm_results("proj-2", "result-1", "researcher-1")
    diagnosis = next(iter(state.diagnoses.values()))
    cause_id = diagnosis["hypotheses"][0]["hypothesis_id"]
    state = service.approve_tests("proj-2", diagnosis["diagnosis_id"],
                                  diagnosis["hypotheses"][0]["discriminating_test_ids"],
                                  "researcher-1")
    assert state.status is WorkflowStatus.WAITING_FOR_CONFIRMATION_TEST
    state = service.confirm_cause("proj-2", cause_id, "researcher-1")
    assert state.status is WorkflowStatus.REFLECTING
    assert "cand-1" in state.candidates
    child = state.candidates[state.active_candidate_id]
    assert child["parent_candidate_id"] == "cand-1"
    assert child["version"] == 2


def test_duplicate_event_key_is_applied_once(tmp_path):
    service = _service(tmp_path)
    service.create("성인용 IR 정제", run_id="run-lifecycle-test", project_id="proj-3")
    state = service.sync_design(_execution())
    protocol_id = next(iter(state.protocols))
    service.approve_protocol("proj-3", "researcher-1", protocol_id)
    first = service.register_batch("proj-3", {
        "protocol_id": protocol_id, "batch_id": "batch-1",
    }, idempotency_key="same-batch-event")
    second = service.register_batch("proj-3", {
        "protocol_id": protocol_id, "batch_id": "batch-1",
    }, idempotency_key="same-batch-event")
    assert first.state_version == second.state_version
    assert len(second.batches) == 1
    events = service.store.events("proj-3")
    assert len([e for e in events if e["idempotency_key"] == "same-batch-event"]) == 1
