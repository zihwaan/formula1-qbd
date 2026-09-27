"""D7 run sheet — 승인된 actual matrix → run별 칭량표. 조성 요인(%w/w)이 바뀌면 balance 성분으로 100%를 맞추고,
음수면 RS002(차단). 근거 없는 설비 설정값은 만들지 않는다(PC007) — 연구자 검토용 프로토콜이지 GMP 지시서가 아니다."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def compile_run_sheet(handoff: Dict[str, Any], factors: List[Dict[str, Any]], runs: List[Dict[str, Any]], *,
                      balance_material: Optional[str]) -> Dict[str, Any]:
    unit = float(handoff.get("unit_weight_mg") or 0) or None
    ings = handoff["ingredients"]
    comp = {f["factor_id"]: f for f in factors if f.get("material_id")}
    sheets, issues = [], []
    for r in runs:
        pct = {i["material_id"]: float(i.get("percent_w_w") or 0) for i in ings}
        for fid, f in comp.items():
            pct[f["material_id"]] = float(r["actual"][fid])
        if balance_material and balance_material in pct:
            others = sum(v for k, v in pct.items() if k != balance_material)
            pct[balance_material] = round(100 - others, 6)
        total = sum(pct.values())
        rows = [{"material_id": k, "pct_w_w": round(v, 4), "mg_per_unit": round(unit * v / 100, 4) if unit else None,
                 "changed": k in {f["material_id"] for f in comp.values()} or k == balance_material} for k, v in pct.items()]
        if balance_material and pct.get(balance_material, 0) < 0:
            issues.append({"rule_id": "RS002", "run_id": r["run_id"], "message_ko": f"balance 성분({balance_material})이 음수"})
        if abs(total - 100) > 0.5:
            issues.append({"rule_id": "RS001", "run_id": r["run_id"], "message_ko": f"조성 합 {total:.2f}%"})
        settings = {f["name"]: {"value": r["actual"][f["factor_id"]], "unit": f.get("unit")} for f in factors if not f.get("material_id")}
        sheets.append({"run_id": r["run_id"], "run_order": r["run_order"], "std_order": r["std_order"], "ingredients": rows,
                       "process_settings": settings, "fixed_parameters": handoff.get("fixed_parameters", [])})
    request = []
    if not handoff.get("equipment_id"):
        request.append({"rule_id": "RS003", "message_ko": "설비 작업 용량을 알 수 없어 배치 용량 검사를 못 했습니다(미검사)."})
    return {"runs": sheets, "issues": issues, "requests": request, "balance_material": balance_material,
            "unit_weight_mg": unit, "note": "연구자 검토용 실행 프로토콜 — GMP SOP·제조지시서가 아니다."}
