"""측정 필드 정의(measurement_output_fields.csv)가 단일 진실원인지 — 측정값 입력 개선 요청서 과제 1·3 완료 기준."""

import csv
from pathlib import Path

from formula.biopharm.triggers import check_value, group_requests, load_measurement_catalog, load_output_fields

ROOT = Path(__file__).resolve().parents[1]
FIELDS = load_output_fields(ROOT)


def _triggers():
    with (ROOT / "database/reference/data_request_triggers.csv").open(encoding="utf-8-sig") as h:
        return list(csv.DictReader(h))


def test_every_trigger_result_key_is_defined_for_its_measurement():
    for t in _triggers():
        mids = [m.strip() for m in t["measurement_id"].split(";") if m.strip()]
        for k in [k.strip() for k in t["result_keys"].split(";") if k.strip()]:
            assert k in FIELDS and FIELDS[k]["measurement_id"] in mids, (t["trigger_id"], k)


def test_every_field_measurement_exists_in_catalog():
    catalog = load_measurement_catalog(ROOT)
    assert all(f["measurement_id"] in catalog for f in FIELDS.values())


def test_enum_fields_have_values_and_types_are_known():
    for k, f in FIELDS.items():
        assert f["field_type"] in {"number", "bool", "enum", "text", "json"}, k
        if f["field_type"] == "enum":
            assert [v for v in f["enum_values"].split("|") if v], k


def test_request_groups_carry_typed_fields_and_no_card_loses_its_inputs():
    pending = [{"trigger_id": t["trigger_id"], "measurement_ids": [m for m in t["measurement_id"].split(";") if m],
                "result_keys": [k for k in t["result_keys"].split(";") if k], "label": t["trigger_id"]}
               for t in _triggers()]
    for g in group_requests(pending, ROOT):
        assert g["fields"], g["measurement_id"]            # 카드가 떠도 입력 칸이 없는 요청이 없어야 한다
    types = {f["key"]: f["type"] for g in group_requests(pending, ROOT) for f in g["fields"]}
    assert types["salt_screen_done"] == "bool" and types["selected_counterion"] == "text"
    assert types["gfa_class"] == "enum" and types["cd_phase_solubility_type"] == "enum"
    assert {"particle_habit", "psd_modality", "psd_d50_um"} <= set(types)


def test_value_types_are_enforced():
    assert check_value("salt_screen_done", 1, FIELDS)           # bool 칸에 1 → 거부
    assert check_value("salt_screen_done", True, FIELDS) is None
    assert check_value("selected_counterion", "HCl", FIELDS) is None
    assert check_value("gfa_class", "IV", FIELDS)                # 목록 밖
    assert check_value("pka_values_json", [{"pka": 4.7}], FIELDS) is None
    assert check_value("not_a_field", "x", FIELDS) is None       # 정의 없는 키는 기존 검증 경로
