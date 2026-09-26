"""데이터 요청 — Formula1_v3/IMPLEMENTATION_GUIDE.md §2.3·§3.3·§5.

`data_request_triggers.csv`에서 "지금 유효한 요청"만 골라내는 순수 조회 함수다.
**그래프를 절대 막지 않는다**(불변식 I-9) — plan()·candidate 출력은 이 함수의 결과와
무관하게 항상 진행한다. urgency=narrows_strategy는 phase_gates 직후 스펙 수준에서
한 번, refines_confidence는 GATE를 통과한 후보마다 따로 평가한다.
"""

from __future__ import annotations

import logging

import csv as csv_mod
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from formula.checkers.applies_when import evaluate
from formula.contracts import PendingRequest

CSV_PATH = "database/reference/data_request_triggers.csv"


@lru_cache(maxsize=4)
def _rows(base_dir: Path) -> List[Dict[str, str]]:
    path = Path(base_dir) / CSV_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv_mod.DictReader(handle))


def _split(value: Any) -> List[str]:
    return [p.strip() for p in str(value or "").split(";") if p.strip()]


def evaluate_triggers(
    ctx: Dict[str, Any],
    urgency: str,
    base_dir: Path,
    strategy: str = "",
    process_steps: Optional[List[str]] = None,
    flags: Optional[List[str]] = None,
) -> List[PendingRequest]:
    """satisfied_when이 아직 거짓이고 condition_expression이 참인 행만 요청으로 낸다.

    이미 풀린 요청(satisfied_when이 참)은 다음 턴에 목록에서 저절로 빠진다(불변식
    I-12) — 별도 "지웠다"는 기록을 남기지 않아도 재계산 자체가 사라짐을 보장한다.
    """
    flags_l = {f.strip().lower() for f in (flags or [])}
    steps_l = {s.strip().lower() for s in (process_steps or [])}

    def has_flag(name: str) -> bool:
        name = str(name).strip().lower()
        return name in flags_l or f"has_{name}" in flags_l or bool(ctx.get(f"has_{name}"))

    def has_step(name: str) -> bool:
        return str(name).strip().lower() in steps_l

    scope: Dict[str, Any] = {**ctx, "strategy": strategy, "has_flag": has_flag, "has_step": has_step}

    out: List[PendingRequest] = []
    for row in _rows(Path(base_dir)):
        if (row.get("urgency") or "").strip() != urgency:
            continue
        condition = str(row.get("condition_expression") or "").strip()
        if not evaluate(condition, scope):
            continue
        satisfied = str(row.get("satisfied_when") or "").strip()
        if satisfied and evaluate(satisfied, scope):
            continue
        kind, label = _reason(str(row.get("trigger_id") or ""), scope, str(row.get("rationale") or ""))
        out.append(PendingRequest(
            trigger_id=str(row.get("trigger_id") or ""),
            urgency=urgency,
            measurement_ids=_split(row.get("measurement_id")),
            result_keys=_split(row.get("result_keys")),
            label=label,
            why=str(row.get("rationale") or ""),
            fallback=str(row.get("fallback_if_declined") or ""),
            strategy=strategy,
            reason_kind=kind,
        ))
    return out


def _reason(trigger_id: str, ctx: Dict[str, Any], rationale: str):
    """발동 사유를 화면에 구분해 보여 준다. 용해도 요청은 두 가지 이유로 켜진다:
    예측이 **낮거나 모르기** 때문인지, 두 예측 모델이 **1 log 이상 어긋나기** 때문인지."""
    if trigger_id == "DRQ_SOL":
        a, b = ctx.get("logs_esol"), ctx.get("logs_gse")
        if a is not None and b is not None and abs(a - b) >= 1.0:
            return "disagreement", f"두 예측 모델(ESOL {a:.2f} · GSE {b:.2f})이 {abs(a - b):.2f} log 어긋나 예측을 신뢰할 수 없음"
        if ctx.get("bcs_source") == "ph_dependent_unmeasured":
            return "ph_dependent", "이온화 가능한 약물 — pH 1.2·4.5·6.8에서 용해도가 달라 단일 예측으로 판정하지 않음(평형용해도 필요)"
        return "low_or_unknown", "예측 용해도가 낮거나(또는 계산 불가) — 용량을 녹일 수 있는지 실측이 필요"
    return "rule", rationale[:120]


def group_requests(pending: List[Dict[str, Any]], base_dir: Path,
                   declined: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """같은 시험을 가리키는 요청을 하나로 합치고, 시료가 적게 드는 시험부터 정렬한다.

    예: 고체상 세트(DRQ_SOLIDFORM)와 녹는점(DRQ_TM)이 모두 DSC를 가리키면 DSC 한 번으로 묻는다.
    연구자가 건너뛴 요청(declined)은 목록에서 빠지고, 거절 시의 대체 경로만 남는다.
    """
    catalog = load_measurement_catalog(Path(base_dir))
    fields = load_output_fields(Path(base_dir))
    declined_set = set(declined or [])
    groups: Dict[str, Dict[str, Any]] = {}
    for req in pending:
        if req.get("trigger_id") in declined_set:
            continue
        for mid in req.get("measurement_ids") or []:
            meta = catalog.get(mid, {})
            g = groups.setdefault(mid, {
                "measurement_id": mid, "name": meta.get("name_kr") or mid,
                "tier": meta.get("tier") or "", "sample_mg": meta.get("indicative_sample_mg") or "",
                "method": meta.get("method_summary") or "",
                "outputs": _split(meta.get("output_fields")), "triggers": [], "result_keys": [],
                "reasons": [], "fallbacks": []})
            if req.get("trigger_id") not in g["triggers"]:
                g["triggers"].append(req.get("trigger_id"))
                g["reasons"].append({"trigger_id": req.get("trigger_id"), "kind": req.get("reason_kind") or "",
                                     "text": req.get("label") or req.get("why") or ""})
                if req.get("fallback"):
                    g["fallbacks"].append(req.get("fallback"))
            # 어느 시험이 어느 값을 내는지는 필드 정의 파일이 기준이다. 정의에 없는 키는 조용히 버리지 않고
            # 경고를 남긴다 — 버리면 카드는 뜨는데 입력 칸이 없는 요청이 생긴다(측정값 입력 개선 요청서 과제 1).
            allowed = {k for k, r in fields.items() if r.get("measurement_id") == mid}
            multi = len(req.get("measurement_ids") or []) > 1
            for k in req.get("result_keys") or []:
                if k in allowed and k not in g["result_keys"]:
                    g["result_keys"].append(k)
                elif k not in allowed and not multi and k not in fields:
                    log.warning("trigger %s result_key %s 가 %s 필드 정의에 없음", req.get("trigger_id"), k, mid)

    for g in groups.values():
        g["fields"] = [field_spec(k, fields) for k in g["result_keys"]]

    def tier_key(g):
        t = str(g["tier"])
        return (int(t) if t.isdigit() else 9, float(g["sample_mg"] or 999), g["measurement_id"])
    return sorted(groups.values(), key=tier_key)


log = logging.getLogger(__name__)
CATALOG_PATH = "database/reference/measurement_catalog.csv"
FIELDS_PATH = "database/reference/measurement_output_fields.csv"


@lru_cache(maxsize=4)
def load_output_fields(base_dir: Path) -> Dict[str, Dict[str, str]]:
    """측정 산출 필드의 단일 진실원 — 타입(number·bool·enum·text·json)·단위·선택지·라벨."""
    path = Path(base_dir) / FIELDS_PATH
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {r["field_key"]: r for r in csv_mod.DictReader(handle) if r.get("field_key")}


def field_spec(key: str, fields: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    f = fields.get(key, {})
    return {"key": key, "type": f.get("field_type") or "number", "unit": f.get("unit", ""),
            "enum": [v for v in (f.get("enum_values") or "").split("|") if v],
            "label": f.get("label_kr") or key, "help": f.get("help_kr", "")}


def check_value(key: str, value: Any, fields: Dict[str, Dict[str, str]]) -> Optional[str]:
    """필드 타입에 맞는지 — 맞으면 None, 아니면 사유. 정의 없는 키는 검사하지 않는다(기존 입력 경로)."""
    f = fields.get(key)
    if f is None:
        return None
    t = f.get("field_type") or "number"
    ok = ((t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
          or (t == "bool" and isinstance(value, bool))
          or (t == "enum" and value in (f.get("enum_values") or "").split("|"))
          or (t == "text" and isinstance(value, str) and value.strip() != "")
          or (t == "json" and isinstance(value, (list, dict))))
    return None if ok else f"{key}: {t} 타입이 필요합니다 (받은 값: {value!r})"


@lru_cache(maxsize=4)
def load_measurement_catalog(base_dir: Path) -> Dict[str, Dict[str, str]]:
    """measurement_id → 카탈로그 행. Tier 오름차순 정렬에 쓴다(가이드 §2.3 원칙 1)."""
    path = Path(base_dir) / CATALOG_PATH
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["measurement_id"]: row for row in csv_mod.DictReader(handle)
                if row.get("measurement_id")}
