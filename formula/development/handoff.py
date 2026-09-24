"""CandidateDevelopmentHandoff 생성 — 명세 v6.1 §6 D0, §10.1.

두 그래프를 잇는 유일한 연결이다. Handoff는 불변이며, 필요 자료 제출로 내용이 바뀌면
기존 것을 고치지 않고 **새 revision**(handoff_id `-rN`)과 새 fingerprint를 만든다.
fingerprint는 조성·공정·고정변수·배치규모·설비·QTPP의 정규화 JSON 해시다(PV001이 재계산해 대조).

후보 1위가 자동으로 넘어오지 않는다(§0 경계 1) — 연구자가 `candidate_id@version`을 눌러야
여기까지 온다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from formula.development.rules import DoeRulebook

DC_FIXED = [("blend_time", "min"), ("lubrication_time", "min"), ("compression_force", "kN")]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def fingerprint(h: Dict[str, Any]) -> str:
    core = {
        "candidate": f"{h['candidate_id']}@{h['candidate_version']}",
        "ingredients": sorted((i["name"], i.get("role"), i.get("pct_w_w"), i.get("grade")) for i in h["ingredients"]),
        "route": h["process_route_id"], "steps": [s["unit_op_code"] for s in h["process_steps"]],
        "fixed": sorted((p["name"], str(p.get("value")), p.get("status")) for p in h["fixed_parameters"]),
        "batch_scale": h.get("batch_scale"), "equipment": h.get("equipment_id"),
        "qtpp": h.get("qtpp_snapshot_id"),
    }
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, default=str).encode()).hexdigest()[:20]


def process_steps(rb: DoeRulebook, route: str) -> List[Dict[str, Any]]:
    return [{"unit_op_code": r["unit_op_code"], "name": r["name_ko"], "order": int(r["order"])}
            for r in rb.master("process_unit_operation_master") if r["process_route"] == route]


def _route_of(process: str) -> str:
    p = (process or "").lower()
    if "direct" in p or p in ("dc", "직접타정"):
        return "direct_compression"
    return p or "unknown"


def from_recipe(rb: DoeRulebook, recipe: Dict[str, Any], *, run_id: str, spec: Dict[str, Any],
                verdicts: List[Dict[str, Any]], actor: str) -> Dict[str, Any]:
    """상류 후보(Recipe dict) → Handoff. 모르는 값은 None/MISSING으로 둔다 — 채우는 건 연구자다."""
    total = sum(i.get("amount_mg") or 0 for i in recipe["ingredients"]) or None
    ings = []
    for i in recipe["ingredients"]:
        pct = i.get("percent")
        if pct is None and total and i.get("amount_mg") is not None:
            pct = round(100 * i["amount_mg"] / total, 4)
        ings.append({"name": i["name"], "role": i.get("role") or "other", "amount_mg": i.get("amount_mg"),
                     "pct_w_w": pct, "unit": "mg" if i.get("amount_mg") is not None else None,
                     "grade": None, "is_critical": i.get("role") == "api"})
    route = _route_of(recipe.get("process", ""))
    props = spec.get("properties") or {}
    api = {"name": recipe.get("api_name"), "dose_mg": next((i.get("amount_mg") for i in recipe["ingredients"]
                                                           if i.get("role") == "api"), None),
           "pct_w_w": next((i["pct_w_w"] for i in ings if i["role"] == "api"), None),
           "bcs_class": spec.get("bcs_class"), "flags": [k for k, v in props.items() if v is True]}
    version = int(recipe.get("version") or 1)
    h = {
        "handoff_id": f"HO-{recipe['candidate_id']}-v{version}-r1", "project_id": run_id,
        "candidate_id": recipe["candidate_id"], "candidate_version": version,
        "formulation_fingerprint": "", "qtpp_snapshot_id": f"QTPP-{run_id}",
        "ingredients": ings, "process_route_id": route, "process_steps": process_steps(rb, route),
        "fixed_parameters": [{"name": n, "value": None, "unit": u, "status": "MISSING", "evidence_ref": None}
                             for n, u in DC_FIXED] if route == "direct_compression" else [],
        "batch_scale": None, "evidence_snapshot_id": f"EV-{run_id}-{recipe['candidate_id']}",
        "rule_verdict_ids": [v.get("rule_id", "") for v in verdicts if v.get("rule_id")],
        "rulebook_version": rb.version, "created_by": actor, "created_at": now(),
        "dosage_form": "tablet", "release_type": "immediate_release", "coating": "none", "api": api,
        "equipment_id": None, "unit_weight_mg": total,
        "upstream_verdicts": [{"rule_id": v.get("rule_id"), "status": _vstatus(v.get("status")),
                               "resolved": False} for v in verdicts],
        "title": f"{recipe.get('api_name') or 'API'} · {recipe.get('strategy') or ''} ({recipe['candidate_id']}@{version})",
        "assumptions": [],
    }
    h["formulation_fingerprint"] = fingerprint(h)
    return h


def _vstatus(s: Optional[str]) -> str:
    s = (s or "").lower()
    return "hard_fail" if s in ("hard_fail", "fail") else s


def lornoxicam_demo(rb: DoeRulebook, actor: str) -> Dict[str, Any]:
    """명세 §19 데모 후보. 조성 비율은 **데모 가정**이다(원문 대조 전) — 화면에 가정으로 표시한다.

    요인 중심값(MCC:만니톨 2, 혼합 10분, 크로스포비돈 6 %)은 Almotairi 2022 설계 중심점과 같다.
    API·SLS·활택제 비율과 정제 중량 200 mg은 논문 대조 전 가정값이라 scope·화면에 가정으로 남긴다.
    """
    ings = [
        {"name": "Lornoxicam", "role": "api", "pct_w_w": 4.0, "amount_mg": 8.0, "grade": "Ph. Eur.",
         "is_critical": True},
        {"name": "Microcrystalline cellulose", "role": "diluent", "pct_w_w": 58.6667, "amount_mg": 117.333,
         "grade": "PH-102 (가정)", "is_critical": False},
        {"name": "Mannitol", "role": "diluent", "pct_w_w": 29.3333, "amount_mg": 58.667,
         "grade": "DC grade (가정)", "is_critical": False},
        {"name": "Crospovidone", "role": "disintegrant", "pct_w_w": 6.0, "amount_mg": 12.0, "grade": None,
         "is_critical": False},
        {"name": "Sodium lauryl sulfate", "role": "surfactant", "pct_w_w": 1.0, "amount_mg": 2.0, "grade": None,
         "is_critical": False},
        {"name": "Magnesium stearate", "role": "lubricant", "pct_w_w": 1.0, "amount_mg": 2.0, "grade": None,
         "is_critical": False},
    ]
    for i in ings:
        i["unit"] = "mg"
    h = {
        "handoff_id": "HO-LX-DT-001-v1-r1", "project_id": "demo-lornoxicam", "candidate_id": "LX-DT-001",
        "candidate_version": 1, "formulation_fingerprint": "", "qtpp_snapshot_id": "QTPP-LX-DT-01",
        "ingredients": ings, "process_route_id": "direct_compression",
        "process_steps": process_steps(rb, "direct_compression"),
        "fixed_parameters": [
            {"name": "blend_time", "value": 10.0, "unit": "min", "status": "SET", "evidence_ref": "Almotairi 2022 중심점"},
            {"name": "compression_force", "value": None, "unit": "kN", "status": "MISSING", "evidence_ref": None},
        ],
        "batch_scale": None, "evidence_snapshot_id": "EV-LX-2022", "rule_verdict_ids": [],
        "rulebook_version": rb.version, "created_by": actor, "created_at": now(),
        "dosage_form": "dispersible_tablet", "release_type": "immediate_release", "coating": "none",
        "api": {"name": "Lornoxicam", "dose_mg": 8.0, "pct_w_w": 4.0, "bcs_class": "II", "flags": []},
        "equipment_id": "EQ_LX_MIXER;EQ_LX_PRESS", "unit_weight_mg": 200.0, "upstream_verdicts": [],
        "title": "Lornoxicam 분산정 (LX-DT-001@1) — Almotairi 2022",
        "assumptions": ["조성 비율(API 4 %, SLS 1 %, MgSt 1 %)과 정제 중량 200 mg은 데모 가정 — 원문 대조 전",
                        "요인 중심값은 Almotairi 2022 설계 중심점"],
    }
    h["formulation_fingerprint"] = fingerprint(h)
    return h


# 데모 연구자 입력 — 인계 문서 §9 표에 고정된 가정 + 각 단계의 연구자 결정.
# UI는 이 값을 폼에 **미리 채워 보여 줄 뿐**이고, 제출은 연구자가 버튼으로 한다.
LORNOXICAM_SCRIPT: Dict[str, Any] = {
    "required_data": {
        "batch_scale": "1,000정 (데모 가정)",
        "fixed_parameters": [{"name": "compression_force", "status": "UNKNOWN", "value": None,
                              "reason": "논문 미보고 — scope 제한으로 기록"}],
    },
    "cqa_edits": [
        {"cqa_id": "CQA_DISSOLUTION", "changes": {
            "summary_definition": "DE30 (0–30분 용출효율)", "test_method_id": "TM_DISS_USP711_DE",
            "unit": "DE %", "acceptance_operator": "GE", "lower": 75, "criterion_source": "PROJECT_TARGET",
            "rationale_refs": "연구자 입력 가정 (인계 문서 §9)", "assumption": True},
         "reason": "DE30 ≥ 75 %는 프로젝트 목표 가정"},
        {"cqa_id": "CQA_ASSAY", "changes": {"acceptance_operator": "BETWEEN", "lower": 90, "upper": 110,
                                            "criterion_source": "PROJECT_TARGET", "rationale_refs": "데모 가정",
                                            "assumption": True}, "reason": "모노그래프 대조 전 가정"},
        {"cqa_id": "CQA_BREAKING_FORCE", "changes": {"acceptance_operator": "BETWEEN", "lower": 30, "upper": 100,
                                                     "criterion_source": "PROJECT_TARGET", "rationale_refs": "데모 가정",
                                                     "assumption": True}, "reason": "경도는 모니터링 — 가정 기준"},
        {"cqa_id": "CQA_IMPURITIES", "changes": {"acceptance_operator": "LE", "upper": 1.0,
                                                 "criterion_source": "PROJECT_TARGET", "rationale_refs": "데모 가정",
                                                 "assumption": True}, "reason": "ICH Q3B 대조 전 가정"},
        {"cqa_id": "CQA_TABLET_WEIGHT_RSD", "changes": {"acceptance_operator": "LE", "upper": 5.0,
                                                        "criterion_source": "PROJECT_TARGET",
                                                        "rationale_refs": "데모 가정", "assumption": True},
         "reason": "IPC 가정 기준"},
        {"cqa_id": "CQA_DISINTEGRATION", "changes": {"acceptance_operator": "LE", "upper": 3.0,
                                                     "criterion_source": "PROJECT_TARGET",
                                                     "rationale_refs": "데모 가정", "assumption": True},
         "reason": "분산정 붕해 가정 기준"},
    ],
    "fmea_edits": [
        {"row_id": "FM008", "changes": {"disposition": "FIXED"}, "reason": "SLS·활택시간은 고정 관리 (연구 범위 밖)"},
        {"row_id": "FM010", "changes": {"disposition": "FIXED"},
         "reason": "압축력은 고정이지만 값 미기록 — 고심각도·검출 불가로 공백 표시, scope unmanaged"},
        {"row_id": "FM011", "changes": {"disposition": "FIXED"}, "reason": "압축력 — 위와 같음"},
        {"row_id": "FM014", "changes": {"occurrence": 1, "occurrence_evidence": "DSC/FTIR (Almotairi 2022)",
                                        "disposition": "FIXED", "alternative_control": "원료 규격 + DSC/FTIR 스크리닝"},
         "evidence_ref": "Almotairi 2022 DSC·FTIR", "reason": "상호작용 실측 음성 — O=1 (부분 근거)"},
    ],
    "factor_inputs": {
        "filler_ratio": {"low": 1, "high": 3, "source_ref": "Almotairi 2022 Table 1 (연구 범위)",
                         "evidence_status": "LITERATURE_DIRECT",
                         "manufacturability_evidence": "Almotairi 2022 — 15 run 전부 제조 보고"},
        "blend_time": {"low": 5, "high": 15, "source_ref": "Almotairi 2022 Table 1 (연구 범위)",
                       "evidence_status": "LITERATURE_DIRECT",
                       "manufacturability_evidence": "Almotairi 2022 — 15 run 전부 제조 보고"},
        "disintegrant_pct": {"low": 2, "high": 10, "source_ref": "Almotairi 2022 Table 1 (연구 범위)",
                             "evidence_status": "LITERATURE_DIRECT",
                             "manufacturability_evidence": "Almotairi 2022 — 15 run 전부 제조 보고"},
    },
    "factor_approval": {"prior_evidence_approved": True, "extreme_corner_risk": True,
                        "reason": "Almotairi 2022 선행 연구가 3요인 곡률을 보고 — RSM 직행 근거로 승인"},
    "column_map": {"x1_mcc_mannitol_ratio": "F_filler_ratio", "x2_mixing_time_min": "F_blend_time",
                   "x3_crospovidone_pct": "F_disintegrant_pct", "y1_dispersibility_s": "CQA_DISPERSIBILITY",
                   "y2_friability_pct": "CQA_FRIABILITY", "y3_de30_pct": "CQA_DISSOLUTION",
                   "y4_cu_av": "CQA_CU_AV"},
    "model_reduction": {"cqa_id": "CQA_FRIABILITY", "terms": ["1", "a", "b", "c"],
                        "reason": "전체 이차모형 예측 R² 0.25 — 계층성 유지 선형 축소"},
    # MV006(adj R² − pred R² > 0.20)은 AV(0.885 − 0.481)에도 걸린다 — 명세 §19 서술은 경고만 언급하지만
    # 룰북대로면 연구자 판단이 필요하다. 골든 영역은 AV 전체 이차모형을 그대로 쓰므로 "flag와 함께 수용"이 일치한다.
    "model_accept": {"cqa_id": "CQA_CU_AV",
                     "reason": "예측력이 낮음(pred R² 0.48)을 알고 수용 — 넓은 예측구간이 공동확률에 그대로 반영된다"},
    "reference_existing": {"F_filler_ratio": 3.0, "F_blend_time": 11.0, "F_disintegrant_pct": 6.23},
    "limitations": "압축력 미기록(UNKNOWN) — 영역은 논문 제조 조건의 압축력에서만 성립한다고 가정",
}
