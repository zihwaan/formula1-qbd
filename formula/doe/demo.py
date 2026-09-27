"""CBD 문헌 재현 study의 "입력 채우기" — 폼에 넣을 값만 만든다. 제출은 연구자가 누른다.

값은 전부 픽스처(Monton 2026 표·Methods)에서 온다. 논문에 없는 것(FMEA 점수 등)은 비워 두고 note로 이유를 적는다.
신규 API study에는 채울 데이터가 없다 — None을 돌려준다(가짜 값 금지).
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from formula.doe.replay import FIXTURE, KEY

# 픽스처 반응 → RB02 CQA 템플릿 · M01 시험법
CQA_OF = {"hardness_kgf": ("CQA_BREAKING_FORCE", "TM_BREAK_USP1217"), "dt_s": ("CQA_DISINTEGRATION", "TM_DISINT_USP701"),
          "friability_pct": ("CQA_FRIABILITY", "TM_FRIAB_USP1216")}
FACTOR_KEY = {"X1": ("compression_force", None, "CPP"), "X2": ("filler_ratio", "MCC", "CMA"), "X3": ("disintegrant_pct", "CCS", "CMA")}
QKIND = {"psi": "pressure", "%w/w": "fraction_mass"}


def _by_key(st: Dict[str, Any], fx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """study 요인 ID → 픽스처 요인. 화면에서 고른 순서가 달라도 요인 키(FMEA 후보)로 맞춘다 — 위치로 맞추지 않는다."""
    key_to_fx = {FACTOR_KEY[f["id"]][0]: f for f in fx["factors"]}
    return {fid: key_to_fx[f["key"]] for fid, f in st["factors"].items() if f.get("key") in key_to_fx}


def fixture() -> Dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fill(st: Dict[str, Any], action: str) -> Optional[Dict[str, Any]]:
    if st.get("demo") != "cbd_odt":
        return None
    fx = fixture()
    cite = f"{fx['citation'].split(';')[0]} (doi:{fx['doi']})"
    if action == "cqa_edit":
        edits = []
        mapped = {c for c, _ in CQA_OF.values()}
        for r in fx["responses"]:
            cid, tm = CQA_OF[r["id"]]
            t = fx["test_methods"][r["id"]]
            edits.append({"cqa_id": cid, "analysis_role": "DOE_RESPONSE", "response_key": r["id"], "unit": r["unit"],
                          "acceptance_operator": r["operator"], "lower": r.get("lower"), "upper": r.get("upper"),
                          "test_method_id": tm, "test_method_version": f"as reported · {t['locator']}",
                          "summary_definition": "MEAN" if r["id"] != "friability_pct" else "PERCENT_WEIGHT_LOSS",
                          "replicate_policy": t["text"], "criterion_source": "LITERATURE",
                          "evidence_refs": [f"{cite} {fx['responses_table']}"], "is_cqa": bool(r.get("is_cqa"))})
        for cid, c in st["cqas"].items():
            if cid not in mapped:
                edits.append({"cqa_id": cid, "analysis_role": "NOT_APPLICABLE", "acceptance_operator": None,
                              "rationale": "문헌 재현 범위 밖 — 논문이 이 반응을 보고하지 않았다"})
        return {"edits": edits, "note": f"반응·기준·시험법은 {fx['responses_table']}·Methods 2.2에서 옮겼습니다."}
    if action == "fmea_edit":
        return {"rows": [], "note": "논문에 FMEA 점수가 없어 비워 둡니다 — 발생도는 UNKNOWN(RPN 없음)."}
    if action == "factor_select":
        return {"selected": [{"key": FACTOR_KEY[f["id"]][0], "name": f["name"], "kind": FACTOR_KEY[f["id"]][2],
                              "material_id": FACTOR_KEY[f["id"]][1]} for f in fx["factors"]], "fixed": [],
                "note": f"요인은 {fx['factors_table']}의 X1–X3."}
    if action == "range_submit":
        ev = fx["range_evidence"]
        by = _by_key(st, fx)
        return {"factors": [{"factor_id": fid, "unit": f["unit"], "quantity_kind": QKIND[f["unit"]], "low": f["low"],
                             "center": f["center"], "high": f["high"],
                             "evidence_status": {b: ev["prior_study_status"] for b in ("low", "center", "high")},
                             "range_evidence_refs": [f"{cite} {ev['source_locator']}"], "applicability_confirmed": False}
                            for fid, f in sorted(by.items())],
                "note": f"범위는 {fx['factors_table']}, 근거 등급은 {ev['source_locator']}(선행시험 보고 · 원자료 없음)."}
    if action == "plan_approve":
        tm = fx["test_methods"]
        return {"sampling_plan": " / ".join(f"{k}: {v['text']}" for k, v in tm.items()),
                "stop_criteria": "문헌 재현 — 실행하지 않음(논문 Table 9 결과를 입력)",
                "balance_material": st.get("run_sheet", {}).get("balance_material"),
                "note": "샘플링은 논문 Methods 2.2. 이 study는 제조하지 않으므로 중단 기준은 '실행하지 않음'."}
    if action == "results_submit":
        plan = st["plans"][st["active_plan"]]
        ids = sorted(st["factors"])
        col = {fid: KEY[f["id"]] for fid, f in _by_key(st, fx).items()}
        pool = list(fx["runs"])
        rows = []
        for r in plan["runs"]:
            want = {fid: r["actual"][fid] for fid in ids}
            k = next(i for i, fr in enumerate(pool) if all(abs(fr[col[fid]] - want[fid]) < 1e-6 for fid in ids))
            fr = pool.pop(k)
            vals = {rid: (fr[rid]["mean"] if "mean" in fr[rid] else fr[rid]["value"]) for rid in CQA_OF}
            tag = f"{fx['runs_table']} run {fr['run_order']}"
            rows.append({"run_id": r["run_id"], "batch_id": tag, "parent_blend_id": tag,
                         "test_method_version": "as reported · Methods 2.2", "replicate_independence": "INDEPENDENT_BATCH",
                         "evidence_status": "LITERATURE_DIRECT", "source_locator": tag, "values": vals})
        return {"rows": rows, "note": f"값은 {fx['runs_table']}의 run별 평균. 설계 run과 논문 run은 요인 수준으로 연결했습니다."}
    if action == "model_accept_flags":
        flags = sorted({f["rule_id"] for m in st["models"].values() if m["status"] == "VALID_WITH_FLAGS" for f in m["gate"]["flags"]})
        return {"rationale": f"문헌 재현 — 플래그({', '.join(flags)})를 확인했고, 잠근 기준(p_min)으로 영역을 계산해 본다",
                "note": "사유 문장은 초안입니다. 플래그 내용을 읽고 고치거나 그대로 승인하세요."}
    if action == "revise":
        cur = (st.get("labloop") or {}).get("current") or {}
        return {"reason": f"{cur.get('observed_pattern', '')} — {cur.get('reason_code', '')}로 재검토", "tests": [t["test_id"] for t in cur.get("tests", [])],
                "note": "사유 문장은 초안입니다. 판별시험은 RB18 제안을 모두 골라 두었습니다."}
    return {}
