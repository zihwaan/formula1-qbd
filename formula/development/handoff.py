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
    """시연 후보 — Almotairi et al., Pharmaceuticals 2022, 15, 1463 (CC BY, PMC9785951)의 **실제 처방**.

    조성은 설계 중심점 F2(Table 10): MCC 59.2 % · 만니톨 29.6 % · 크로스포비돈 6 % · 로녹시캄 3.2 %(8 mg)
    · SLS 2 %(활택제). 정제 250 mg, 10 mm 평면 펀치, Turbula S27 → Erweka EKO 단발 타정기(§3.2.4).
    논문에 없는 값(원료 등급, 배치 규모, 압축력)은 비워 둔다 — 진입 Readiness가 요청하고, 연구자가
    논문에 적힌 사실(공급처·미보고)을 그대로 기록한다. 지어낸 수치는 하나도 넣지 않는다.
    """
    unit = 250.0
    rows = [("Lornoxicam", "api", 3.2, True), ("Microcrystalline cellulose", "diluent", 59.2, False),
            ("Mannitol", "diluent", 29.6, False), ("Crospovidone", "disintegrant", 6.0, False),
            ("Sodium lauryl sulfate", "lubricant", 2.0, False)]
    ings = [{"name": n, "role": r, "pct_w_w": pct, "amount_mg": round(unit * pct / 100, 3), "unit": "mg",
             "grade": None, "is_critical": crit} for n, r, pct, crit in rows]
    h = {
        "handoff_id": "HO-LX-DT-F2-v1-r1", "project_id": "almotairi-2022", "candidate_id": "LX-DT-F2",
        "candidate_version": 1, "formulation_fingerprint": "", "qtpp_snapshot_id": "QTPP-LX-DT (Almotairi 2022 §1)",
        "ingredients": ings, "process_route_id": "direct_compression",
        "process_steps": process_steps(rb, "direct_compression"),
        "fixed_parameters": [
            {"name": "blend_time", "value": 10.0, "unit": "min", "status": "SET",
             "evidence_ref": "Almotairi 2022 Table 9 — 설계 중심점"},
            {"name": "lubrication_time", "value": 3.0, "unit": "min", "status": "SET",
             "evidence_ref": "Almotairi 2022 §3.2.4 — SLS 첨가 후 3분 추가 혼합"},
            {"name": "compression_force", "value": None, "unit": "kN", "status": "MISSING", "evidence_ref": None},
        ],
        "batch_scale": None, "evidence_snapshot_id": "PMC9785951", "rule_verdict_ids": [],
        "rulebook_version": rb.version, "created_by": actor, "created_at": now(),
        "dosage_form": "dispersible_tablet", "release_type": "immediate_release", "coating": "none",
        "api": {"name": "Lornoxicam", "dose_mg": 8.0, "pct_w_w": 3.2, "bcs_class": "II", "flags": []},
        "equipment_id": "EQ_LX_MIXER;EQ_LX_PRESS", "unit_weight_mg": unit, "upstream_verdicts": [],
        "title": "Lornoxicam 분산정 (LX-DT-F2@1) — Almotairi 2022",
        "sources": ["조성(F2)·정제 250 mg: Almotairi 2022 Table 10, §3.2.4",
                    "요인 범위 Table 9 · 실측 15 run Table 3 · 최적처방 관측값 Table 5·6",
                    "원료 공급처 §3.1 · 설비 §3.2.4 · DSC/FTIR §2.2–2.3",
                    "BCS II: Almotairi 2022 §2.11"],
        "assumptions": [],
    }
    h["formulation_fingerprint"] = fingerprint(h)
    return h


CITE = "Almotairi 2022"
# 가이드 시연의 연구자 입력 — 전부 논문에 적힌 사실이거나, 논문에 없다는 사실의 기록이다.
# DE30 ≥ 75 %만 예외로 논문 값이 아니라 인계 문서 §9가 지정한 프로젝트 목표값이며, 화면에 '가정'으로 표시한다.
# UI는 이 값을 폼에 채워 보여 줄 뿐이고, 제출은 연구자가 버튼으로 한다.
LORNOXICAM_SCRIPT: Dict[str, Any] = {
    "required_data": {
        "batch_scale": "UNKNOWN — 논문 미보고",
        "grades": [{"name": "Lornoxicam", "grade": f"등급 미기재 · 공급처 Tabuk Pharmaceuticals ({CITE} §3.1)"}],
        "fixed_parameters": [{"name": "compression_force", "status": "UNKNOWN", "value": None,
                              "reason": f"{CITE} 미보고 — scope 제한으로 기록"}],
    },
    "cqa_edits": [
        {"cqa_id": "CQA_DISSOLUTION", "changes": {
            "summary_definition": "DE30 (0–30분 용출효율)", "test_method_id": "TM_DISS_USP711_DE",
            "unit": "DE %", "acceptance_operator": "GE", "lower": 75, "criterion_source": "PROJECT_TARGET",
            "rationale_refs": "인계 문서 §9 — 프로젝트 목표값(논문 기준 아님)", "assumption": True},
         "reason": "DE30 ≥ 75 %는 프로젝트 목표값"},
        {"cqa_id": "CQA_ASSAY", "changes": {"acceptance_operator": "BETWEEN", "lower": 85, "upper": 115,
                                            "criterion_source": "PHARMACOPEIA",
                                            "rationale_refs": f"{CITE} §2.14.4 — USP 인용 85–115 %"},
         "reason": "논문이 인용한 함량 기준"},
        {"cqa_id": "CQA_BREAKING_FORCE", "changes": {"analysis_role": "NOT_APPLICABLE", "acceptance_operator": ""},
         "evidence_ref": f"{CITE} Table 2 — 경도는 측정값만 보고, 판정 기준 미제시",
         "reason": "판정 기준 없음 — 이 study에서 판정하지 않음"},
        {"cqa_id": "CQA_IMPURITIES", "changes": {"analysis_role": "NOT_APPLICABLE", "acceptance_operator": ""},
         "evidence_ref": f"{CITE} — 유연물질 미측정", "reason": "측정 자료 없음"},
        {"cqa_id": "CQA_TABLET_WEIGHT_RSD", "changes": {"analysis_role": "NOT_APPLICABLE", "acceptance_operator": ""},
         "evidence_ref": f"{CITE} Table 2 — 중량은 평균 ± RSD만 보고, RSD 기준 미제시",
         "reason": "판정 기준 없음"},
        {"cqa_id": "CQA_FINENESS_OF_DISPERSION", "changes": {"analysis_role": "NOT_APPLICABLE", "acceptance_operator": ""},
         "evidence_ref": f"{CITE} — 분산 미세도 미측정", "reason": "측정 자료 없음"},
        {"cqa_id": "CQA_DISINTEGRATION", "changes": {"analysis_role": "NOT_APPLICABLE", "acceptance_operator": ""},
         "evidence_ref": "분산정의 붕해는 분산시간 CQA(Ph. Eur. 3분)로 판정",
         "reason": "분산시간 CQA와 중복"},
    ],
    "fmea_edits": [
        {"row_id": "FM008", "changes": {"disposition": "FIXED"},
         "reason": f"SLS 2 %·활택 혼합 3분 고정 ({CITE} §3.2.4)"},
        {"row_id": "FM010", "changes": {"disposition": "FIXED"},
         "reason": "압축력은 고정이지만 논문 미보고 — 고심각도·검출 불가, scope unmanaged"},
        {"row_id": "FM011", "changes": {"disposition": "FIXED"}, "reason": "압축력 — 위와 같음"},
        {"row_id": "FM014", "changes": {"occurrence": 1,
                                        "occurrence_evidence": f"{CITE} §2.2–2.3 DSC·FTIR — 상호작용 없음",
                                        "disposition": "FIXED",
                                        "alternative_control": "원료 규격 + DSC/FTIR 적합성 확인"},
         "evidence_ref": f"{CITE} §2.2–2.3", "reason": "상호작용 실측 음성 — O = 1 (부분 근거)"},
    ],
    "factor_inputs": {
        src: {"low": lo, "high": hi, "source_ref": f"{CITE} Table 9 (연구 범위)",
              "evidence_status": "LITERATURE_DIRECT",
              "manufacturability_evidence": f"{CITE} Table 2 — 15개 처방 모두 제조·평가됨"}
        for src, lo, hi in (("filler_ratio", 1, 3), ("blend_time", 5, 15), ("disintegrant_pct", 2, 10))
    },
    "factor_approval": {"prior_evidence_approved": True, "extreme_corner_risk": True,
                        "reason": f"{CITE}가 같은 3요인의 곡률을 보고 — RSM 직행 근거로 승인"},
    "column_map": {"x1_mcc_mannitol_ratio": "F_filler_ratio", "x2_mixing_time_min": "F_blend_time",
                   "x3_crospovidone_pct": "F_disintegrant_pct", "y1_dispersibility_s": "CQA_DISPERSIBILITY",
                   "y2_friability_pct": "CQA_FRIABILITY", "y3_de30_pct": "CQA_DISSOLUTION",
                   "y4_cu_av": "CQA_CU_AV"},
    "model_reduction": {"cqa_id": "CQA_FRIABILITY", "terms": ["1", "a", "b", "c"],
                        "reason": "전체 이차모형 예측 R² 0.25 — 계층성 유지 선형 축소"},
    # MV006(조정 R² − 예측 R² > 0.20)은 AV(0.885 − 0.481)에도 걸린다. 영역은 AV 전체 이차모형을 쓰므로
    # 연구자가 이를 알고 수용한다.
    "model_accept": {"cqa_id": "CQA_CU_AV",
                     "reason": "예측력이 낮음(pred R² 0.48)을 알고 수용 — 넓은 예측구간이 공동확률에 그대로 반영된다"},
    "reference_existing": {"F_filler_ratio": 3.0, "F_blend_time": 11.0, "F_disintegrant_pct": 6.23},
    # 논문 최적처방 배치의 공개된 관측값 — Table 5(분산시간·마손도·DE·AV), Table 6 초기 함량.
    "reference_results": {
        "batch_id": f"{CITE} 최적처방 (Table 5)", "parent_blend_id": f"{CITE} 최적처방",
        "evidence_status": "LITERATURE_DIRECT",
        "values": {"CQA_DISPERSIBILITY": 4.4, "CQA_FRIABILITY": 0.19, "CQA_DISSOLUTION": 80.64,
                   "CQA_CU_AV": 4.65, "CQA_ASSAY": 99.62},
    },
    "limitations": "압축력·배치 규모 미보고(UNKNOWN) — 영역은 논문 제조 조건(Turbula S27, Erweka EKO, 10 mm 펀치)에서만 성립",
}
