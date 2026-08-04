"""실험 데이터 입력 회귀 테스트 — 선택 입력이 실제로 판정을 바꾸는지 고정한다.

지키려는 성질:

  1. 카탈로그의 키는 **룰북/근거표가 실제로 참조하는 이름**이어야 한다. 오타가 나면
     아무 규칙도 안 도는데 화면은 "입력됨"이라고 말한다 — 가장 조용한 실패다.
  2. 카탈로그에 없는 키는 **거부**된다. 이 값들은 룰북 조건식 문맥에 그대로 합쳐지므로,
     임의 키를 받으면 사용자가 `is_pediatric` 같은 문맥 이름을 덮어쓸 수 있다.
  3. 실측값을 넣으면 근거 게이트의 선행 요구가 **실제로 줄어든다**.
  4. 확인시험 결과(숫자)는 스펙의 실측값 자리에 꽂혀 다음 판정의 입력이 된다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formula.chem.profile import build_profile
from formula.contracts import (
    ConfirmationResult,
    FormulationSpec,
    Ingredient,
    ProtocolReadiness,
    Recipe,
)
from formula.evidence.gate import EvidenceGate
from formula.experimental_inputs import ExperimentalInputs

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def catalog() -> ExperimentalInputs:
    return ExperimentalInputs(ROOT)


@pytest.fixture(scope="module")
def gate() -> EvidenceGate:
    return EvidenceGate(ROOT)


def _spec(measured=None, flags=None) -> FormulationSpec:
    profile = build_profile("Ibuprofen", base_dir=ROOT, render=False)
    spec = FormulationSpec(api_name="Ibuprofen", dosage_form="tablet",
                           measured_params=dict(measured or {}),
                           properties=dict(flags or {}))
    return spec.with_profile(profile)


def _recipe(strategy="WG", process="wet_granulation") -> Recipe:
    return Recipe(
        api_name="Ibuprofen", candidate_id=f"cand-0-{strategy}", strategy=strategy, process=process,
        ingredients=[Ingredient(name="Ibuprofen", role="api", amount_mg=200, percent=50)],
        packaging="Alu-Alu blister")


# ---------------------------------------------------------------------------
# 1. 카탈로그의 키가 실제로 쓰이는 이름인가
# ---------------------------------------------------------------------------
def test_catalog_keys_are_used_by_rulebook_or_evidence(catalog, gate):
    """모든 입력 항목은 룰북 CSV의 파라미터이거나 근거표가 참조하는 키여야 한다."""
    import csv
    import glob

    rulebook_params = set()
    for path in glob.glob(str(ROOT / "database" / "**" / "*.csv"), recursive=True):
        try:
            with open(path, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    for column in ("parameter", "parameter_name", "property_name"):
                        value = (row.get(column) or "").strip()
                        if value:
                            rulebook_params.add(value)
                    # 물성 플래그는 파라미터 칸이 아니라 **조건식**에 산다
                    # (route_decision_tree의 `moisture_sensitive == True` 처럼).
                    rulebook_params.update(
                        (row.get("condition_expression") or "").replace("==", " ").split())
        except Exception:
            continue

    # 매니페스트의 applies_when도 소비처다 (예: 포장 규칙의 `hygroscopic == True`).
    manifest_text = (ROOT / "config" / "rulebook_manifest.yaml").read_text(encoding="utf-8")

    evidence_text = " ".join(
        f"{row.get('applies_when','')} {row.get('satisfied_when','')} {row.get('result_key','')}"
        for row in gate.requirements)

    unused = [key for key in catalog.fields
              if key not in rulebook_params
              and key not in evidence_text
              and key not in manifest_text]
    assert not unused, f"어디서도 참조되지 않는 입력 항목(오타 의심): {unused}"


def test_catalog_declares_what_each_field_unlocks(catalog):
    """무엇이 열리는지 안 적힌 항목은 아무도 채우지 않는다."""
    assert catalog.fields
    missing = [k for k, f in catalog.fields.items() if not f.get("unlocks")]
    assert not missing, f"unlocks가 비어 있는 항목: {missing}"


# ---------------------------------------------------------------------------
# 2. 허용목록 — 임의 키는 판정 문맥에 들어가지 못한다
# ---------------------------------------------------------------------------
def test_unknown_keys_are_rejected(catalog):
    measured, flags, rejected = catalog.normalize(
        {"angle_of_repose": 48, "is_pediatric": 1, "__builtins__": 1},
        {"hygroscopic": True, "flag": True},
    )
    assert measured == {"angle_of_repose": 48.0}
    assert flags == {"hygroscopic": True}
    assert set(rejected) == {"is_pediatric", "__builtins__", "flag"}


def test_out_of_range_values_are_rejected(catalog):
    _, _, rejected = catalog.normalize({"angle_of_repose": 480}, {})
    assert "angle_of_repose" in rejected


def test_non_numeric_values_are_rejected(catalog):
    measured, _, rejected = catalog.normalize({"angle_of_repose": "많이"}, {})
    assert measured == {} and "angle_of_repose" in rejected


# ---------------------------------------------------------------------------
# 3. 실측값을 넣으면 선행 요구가 줄어든다
# ---------------------------------------------------------------------------
def test_supplied_measurements_close_evidence_gaps(gate):
    before = gate.assess(_spec(), _recipe())
    after = gate.assess(
        _spec(measured={"aqueous_stability_percent": 99.4, "solubility_mg_per_ml": 0.12,
                        "forced_degradation_done": 1}),
        _recipe())
    assert len(after.blocking) < len(before.blocking)
    closed = {g.evidence_key for g in after.satisfied}
    assert "aqueous_process_stability" in closed
    assert "experimental_solubility" in closed


def test_user_measurements_survive_rdkit_merge():
    """RDKit descriptor 병합이 사용자 실측값을 덮어쓰면 안 된다(추정이 실측을 이기면 안 됨)."""
    spec = _spec(measured={"angle_of_repose": 48.0})
    assert spec.measured_params["angle_of_repose"] == 48.0


# ---------------------------------------------------------------------------
# 4. 확인시험 결과가 실측값 자리로 돌아간다
# ---------------------------------------------------------------------------
def test_confirmation_result_lands_in_measured_params():
    from formula.orchestrator.runner import Run

    run = Run(ROOT, "성인용 이부프로펜 정제를 설계해줘")
    spec, recipe = _spec(), _recipe()
    assessment = run.evidence_gate.assess(spec, recipe)
    run.evidence_store[recipe.candidate_id] = {
        "assessment": assessment, "spec": spec, "recipe": recipe, "derived": {},
    }
    target = next(g for g in assessment.blocking if g.result_key == "solubility_mg_per_ml")
    run.confirmations[recipe.candidate_id] = {
        target.requirement_id: ConfirmationResult(
            requirement_id=target.requirement_id, outcome="pass", value_num=0.12),
    }
    run.reassess(recipe.candidate_id)

    # 결과가 스펙의 실측값 자리에 그대로 꽂혔는가 — 되먹임이 문장이 아니라 데이터 이동인가
    assert spec.measured_params["solubility_mg_per_ml"] == 0.12
    assert run.applied_results[recipe.candidate_id] == {"solubility_mg_per_ml": 0.12}

    # 그래서 확인시험 결과 기록을 지워도 충족 상태가 유지된다(실측값 자체가 근거가 됐다)
    run.confirmations[recipe.candidate_id] = {}
    again = run.reassess(recipe.candidate_id)
    satisfied = {g.evidence_key for g in again.satisfied}
    assert "experimental_solubility" in satisfied


def test_failed_confirmation_does_not_write_a_measurement():
    from formula.orchestrator.runner import Run

    run = Run(ROOT, "성인용 이부프로펜 정제를 설계해줘")
    spec, recipe = _spec(), _recipe()
    assessment = run.evidence_gate.assess(spec, recipe)
    run.evidence_store[recipe.candidate_id] = {
        "assessment": assessment, "spec": spec, "recipe": recipe, "derived": {},
    }
    target = next(g for g in assessment.blocking if g.result_key == "solubility_mg_per_ml")
    run.confirmations[recipe.candidate_id] = {
        target.requirement_id: ConfirmationResult(
            requirement_id=target.requirement_id, outcome="fail", value_num=0.001),
    }
    updated = run.reassess(recipe.candidate_id)

    assert "solubility_mg_per_ml" not in spec.measured_params
    assert updated.readiness is ProtocolReadiness.BLOCKED
    assert updated.failed
