"""DoeStudyService — v7.0 실험개발 study(샌드박스 모드). docs/doe_v7.0/IMPLEMENTATION_DESIGN.md §3 표가 곧 이 파일이다.

- 상태마다 받을 수 있는 행동은 `contracts.ACTIONS` 뿐이다. 표 밖 행동은 409 — 사람 승인(RB00 9개 지점) 없이 다음 단계로 가는 길이 없다.
- 판정은 `gates`(룰북 행)에서, 숫자는 `design`·`models`·`region`에서 온다. 이 파일은 사실을 모아 넘기고, 룰 next_state대로 옮기기만 한다.
- 룰북 next_state의 v6.1 이름은 `contracts.resolve_state`로 읽는다. 표에 없는 값은 옮기지 않고 UNMAPPED_NEXT_STATE로 남긴다.
- 모든 규칙이 DRAFT라 study는 SANDBOX로만 만든다 — 판정이 study를 라우팅하지만 화면은 DRAFT 배지를 단다.
  production 생성은 `DoePackage.can_enforce`가 참인 규칙이 생길 때까지 거부한다.
- 저장은 v6.1 `StudyStore`(Idempotency-Key · Expected-State-Version · Actor-ID · append-only 이벤트 + 결정 원장).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from formula.development.service import StudyError
from formula.development.store import StudyStore, VersionConflict
from formula.doe import cqa as C
from formula.doe import design as D
from formula.doe import fmea as F
from formula.doe import gates as G
from formula.doe import handoff as H
from formula.doe import labloop as L
from formula.doe import protocol as P
from formula.doe import region as RG
from formula.doe import surfaces as SF
from formula.doe.contracts import (ACTIONS, APPROVAL_POINT, EVIDENCE_STATUSES, REVISE_STATES, STAY, STEP_OF, STEPS,
                                   Decision, FactorSpec, TransitionError, check_transition, resolve_state)
from formula.doe.models import fit_ols, predict, select_model
from formula.doe.package import DoePackage, package

BLOCKING = ("BLOCK_STAGE", "REQUEST_DATA", "INVALIDATE")
# 연구자가 직접 고를 수 있는 범위근거 등급 — FEASIBILITY_CONFIRMED는 feasibility 결과로만 생긴다(근거 등급 수동 상향 금지)
RESEARCHER_RANGE_EVIDENCE = tuple(s for s in EVIDENCE_STATUSES if s != "FEASIBILITY_CONFIRMED")
RESULT_EVIDENCE = ("MEASURED_IN_STUDY", "LITERATURE_DIRECT", "VERIFIED_EXTERNAL_DATA", "MEASURED_PRIOR_BATCH",
                   "SYNTHETIC_DEMO", "LITERATURE_DIGITIZED")
VERIFICATION_ROLES = ("SETPOINT", "BOUNDARY", "ROBUSTNESS")
PI_LEVEL = 0.95
FACTOR_FIELDS = {f.name for f in fields(FactorSpec)}

QUESTIONS = {
    "HANDOFF_RECEIVED": "후보와 기준 처방(REFERENCE_PROTOTYPE)을 확인하세요. 설비·배치 규모·주성분 등급이 비어 있으면 채운 뒤 확인합니다.",
    "CQA_REVIEW": "이번 DoE에서 모델링할 반응(DOE_RESPONSE, 최대 4개)을 고르고 판정 기준·시험법을 확인한 뒤 승인하세요.",
    "FMEA_REVIEW": "실패모드별 심각도·발생도·검출도와 처분을 검토하고 승인하세요. 발생 근거가 없으면 발생도는 UNKNOWN으로 둡니다.",
    "FACTOR_SELECTION": "FMEA의 DoE 후보 요인 중 최대 3개를 고르세요. 고르지 않은 고위험 요인은 고정값과 사유가 필요합니다.",
    "RANGE_EVIDENCE_CHECK": "요인별 low·center·high와 단위, 경계별 근거 등급·출처를 입력하고 승인하세요. 기준 처방값은 중심점으로 복사하지 않습니다.",
    "NEEDS_FEASIBILITY": "경계 근거가 약해 feasibility(2k+1 축점)가 먼저입니다. 계획을 검토하고 승인하세요.",
    "WAITING_FEASIBILITY_RESULTS": "조건마다 제조 가능·측정 가능·치명적 비호환 여부를 입력하세요.",
    "RANGE_REVISION_REQUIRED": "경계 조건이 실패했습니다. 판별시험 후보를 참고해 범위를 다시 입력하세요.",
    "PROTOTYPE_REVISION_REQUIRED": "중심 처방이 실패했습니다. 판별시험 후보를 보고 재검토를 시작하세요(FMEA 검토로 돌아갑니다).",
    "ADVANCED_DESIGN_REQUIRED": "혼합·범주형·변경 곤란 요인은 표준 설계로 만들지 않습니다. 검증된 외부 설계 행렬을 가져오세요.",
    "DOE_PLAN_REVIEW": "실험표와 run sheet를 검토하고 승인하세요. 샘플링 계획과 중단 기준이 필요합니다.",
    "WAITING_FOR_RESULTS": "run마다 결과·batch ID·시험법 버전·독립성·근거 등급을 입력하세요.",
    "RESULT_QUALITY_REVIEW": "입력값을 원자료와 대조해 확인하세요. 확인 전에는 모델을 적합하지 않습니다.",
    "MODEL_FIT": "플래그가 붙은 모델이 있습니다. 사유를 적고 플래그를 승인해야 영역을 계산합니다.",
    "MODEL_INADEQUATE": "모델 또는 영역이 부적합합니다. 판별시험 후보를 보고 재검토를 시작하세요(FMEA 검토로 돌아갑니다).",
    "PROVISIONAL_DESIGN_SPACE": "확인 계획(SETPOINT·BOUNDARY·ROBUSTNESS)을 결과를 보기 전에 잠그세요.",
    "WAITING_VERIFICATION_RESULTS": "확인점마다 새 batch 결과를 입력하세요. 모두 통과하면 최종 승인합니다.",
    "REGION_REVISION_REQUIRED": "확인에서 실패한 점이 있습니다. 판별시험 후보를 보고 재검토를 시작하세요.",
    "VERIFIED_OPERATING_REGION": "확인된 운전 영역입니다 — 샌드박스 판정이며 GMP 지시가 아닙니다.",
}


def _sid() -> str:
    return "D7-" + uuid.uuid4().hex[:10]


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _plain(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, np.ndarray):
        return _plain(x.tolist())
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        v = float(x)
        return None if not np.isfinite(v) else v
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return x


def _num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise StudyError(f"숫자가 아닙니다: {v!r}", status=422)


def _fs(d: Dict[str, Any]) -> FactorSpec:
    return FactorSpec(**{k: v for k, v in d.items() if k in FACTOR_FIELDS})


class DoeStudyService:
    def __init__(self, pkg: Optional[DoePackage] = None, store: Optional[StudyStore] = None):
        self.pkg = pkg or package()
        self.store = store or StudyStore(Path(os.environ.get("FORMULA1_DOE7_DB", "/tmp/formula1/doe7.db")))

    # ======================================================================
    # 공개 API
    # ======================================================================
    def create(self, handoff: Dict[str, Any], *, study_type: str, actor: str = "researcher",
               idempotency_key: Optional[str] = None, execution_mode: str = "SANDBOX",
               demo: Optional[str] = None, dataset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        replay = self.store.replay(idempotency_key)
        if replay:
            return self.view(replay["study_id"])
        if execution_mode != "SANDBOX":
            if not any(self.pkg.can_enforce(r) for v in self.pkg.rulebooks.values() if isinstance(v, list) for r in v):
                raise StudyError("집행 가능한(검토·승인된) 규칙이 없어 production study를 만들 수 없습니다 — SANDBOX만 가능합니다.")
        sid = _sid()
        now = H.now()
        st: Dict[str, Any] = {
            "study_id": sid, "study_type": study_type, "execution_mode": execution_mode, "mode": execution_mode.lower(),
            "status": "HANDOFF_RECEIVED", "state_version": 0, "created_at": now, "updated_at": now,
            "title": handoff.get("title"), "candidate_ref": f"{handoff['candidate_id']}@{handoff['candidate_version']}",
            "demo": demo or ("dataset" if dataset else None), "dataset": dataset, "handoff": handoff, "handoff_history": [handoff["handoff_id"]],
            "cqas": {}, "fmea": {"version": 0, "rows": []}, "factor_candidates": [], "selection": None, "factors": {},
            "range_gate": None, "feasibility": None, "design_decision": None, "plans": [], "active_plan": None,
            "run_sheet": None, "results": {}, "models": {}, "flags_accepted": None, "region": None, "verification": None,
            "labloop": {"current": None, "history": []}, "evaluations": {}, "timeline": [], "approvals": [],
            "action_seq": 0, "package_hash": self.pkg.package_hash, "banner": self.pkg.config.display_banner,
        }
        st["_decisions"] = []
        self._record(st, "handoff", G.handoff_readiness(self.pkg, handoff))
        st.pop("_decisions", None)
        self.store.save(st, expected_version=None, event_type="STUDY_CREATED", idempotency_key=idempotency_key,
                        actor_id=actor, payload={"handoff_id": handoff["handoff_id"], "study_type": study_type},
                        result={"study_id": sid}, decisions=[], now=now)
        return self.view(sid)

    def act(self, study_id: str, action: str, payload: Dict[str, Any], *, actor: str = "researcher",
            idempotency_key: Optional[str] = None, expected_version: Optional[int] = None) -> Dict[str, Any]:
        replay = self.store.replay(idempotency_key)
        if replay:
            out = self.view(study_id)
            out["replayed"] = True
            return out
        st, version = self._load(study_id)
        if expected_version is not None and expected_version != version:
            raise VersionConflict(expected_version, version)
        allowed = ACTIONS.get(st["status"], ())
        if action not in allowed:
            raise StudyError(f"지금 상태({st['status']})에서는 '{action}'을 할 수 없습니다. 가능한 행동: {', '.join(allowed) or '없음'}")
        handler = getattr(self, f"_act_{action}")
        st["_decisions"] = []
        st["action_seq"] = int(st.get("action_seq") or 0) + 1
        before = st["status"]
        result = handler(st, payload or {}, actor) or {}
        # 승인 지점은 실제로 다음 단계로 넘어갔을 때만 승인으로 기록한다(막힌 승인은 승인이 아니다)
        if action in APPROVAL_POINT and (st["status"] != before or result.get("approved")):
            for point in APPROVAL_POINT[action]:
                st["approvals"].append({"point": point, "actor_id": actor, "at": H.now(), "action": action,
                                        "state_version": version + 1, "rationale": (payload or {}).get("rationale")})
        decisions = st.pop("_decisions", [])
        st["updated_at"] = H.now()
        self.store.save(_plain(st), expected_version=version, event_type=action.upper(), idempotency_key=idempotency_key,
                        actor_id=actor, payload=payload or {}, result={"study_id": study_id, **_plain(result)},
                        decisions=decisions, now=H.now())
        out = self.view(study_id)
        out["action_result"] = _plain(result)
        return out

    def view(self, study_id: str) -> Dict[str, Any]:
        st, version = self._load(study_id)
        st["state_version"] = version
        return {"study": st, "prompt": self._prompt(st), "steps": [{"n": i + 1, "name": s} for i, s in enumerate(STEPS)],
                "step": STEP_OF.get(st["status"]), "draft": True, "banner": st.get("banner")}

    def list(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.store.list(limit)

    def trace(self, study_id: str) -> Dict[str, Any]:
        st, version = self._load(study_id)
        plan = self._plan(st)
        lineage = {
            "handoff_id": st["handoff"]["handoff_id"], "formulation_fingerprint": st["handoff"]["formulation_fingerprint"],
            "handoff_history": st["handoff_history"], "cqa_versions": {k: v.get("version") for k, v in st["cqas"].items()},
            "fmea_version": st["fmea"]["version"], "factors": sorted(st["factors"]),
            "plan_matrix_hash": plan and plan.get("matrix_hash"), "plan_locked_hash": plan and plan.get("locked_hash"),
            "result_batch_ids": sorted({r.get("batch_id") for r in st["results"].values() if r.get("batch_id")}),
            "models": {k: (m.get("selected") or {}).get("formula") for k, m in st["models"].items()},
            "region_hash": (st.get("region") or {}).get("hash"),
            "verification_locked_hash": ((st.get("verification") or {}).get("plan") or {}).get("locked_hash"),
            "package_hash": st["package_hash"], "approvals": st["approvals"],
        }
        return {"study_id": study_id, "status": st["status"], "state_version": version, "lineage": lineage,
                "timeline": st["timeline"], "events": self.store.events(study_id), "decisions": self.store.decisions(study_id)}

    # ======================================================================
    # 내부 공통
    # ======================================================================
    def _load(self, study_id: str):
        loaded = self.store.load(study_id)
        if not loaded:
            raise StudyError("study 없음", status=404)
        return loaded

    def _move(self, st: Dict[str, Any], dst: str, reason: str, *, rule: Optional[str] = None) -> None:
        src = st["status"]
        try:
            check_transition(src, dst)
        except TransitionError as exc:
            raise StudyError(str(exc), status=500)
        st["status"] = dst
        st["timeline"].append({"from": src, "to": dst, "reason": reason, "rule": rule, "at": H.now(), "seq": st["action_seq"]})

    def _record(self, st: Dict[str, Any], key: str, decisions: List[Any]) -> List[Dict[str, Any]]:
        ds = [d.as_dict() if isinstance(d, Decision) else d for d in decisions]
        st["evaluations"][key] = {"at_status": st["status"], "at_action": st.get("action_seq", 0), "decisions": ds}
        for d in ds:
            st["_decisions"].append({"stage": key, "state": st["status"], **{k: d.get(k) for k in
                                     ("rule_id", "gate_effect", "result_code", "next_state", "enforced")}})
        return ds

    def _route(self, st: Dict[str, Any], d: Dict[str, Any]) -> bool:
        """룰 판정 한 건의 next_state로 옮긴다. 반환: 옮겼는가."""
        target = resolve_state(d.get("next_state"))
        if target is None:
            st["_decisions"].append({"stage": "routing", "state": st["status"], "rule_id": d.get("rule_id"),
                                     "result_code": "UNMAPPED_NEXT_STATE", "next_state": d.get("next_state")})
            return False
        if target == STAY or target == st["status"]:
            return False
        self._move(st, target, d["result_code"], rule=d["rule_id"])
        return True

    @staticmethod
    def _blocking(ds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [d for d in ds if d.get("gate_effect") in BLOCKING]

    def _decide(self, rb: str, rule_id: str, **detail) -> Dict[str, Any]:
        return G._decide(self.pkg, rb, rule_id, **detail).as_dict()

    def _policy(self, rule_id: str, message: str, **detail) -> Dict[str, Any]:
        """RB05 FMEA 점수 정책(YAML) 위반 — CSV 규칙 행이 아니라 정책 문장이다."""
        return {"rule_id": f"RB05:{rule_id}", "gate_effect": "BLOCK_STAGE", "result_code": rule_id, "next_state": None,
                "message_ko": message, "enforced": False, **detail}

    def _plan(self, st: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        i = st.get("active_plan")
        return st["plans"][i] if i is not None else None

    def _factors(self, st: Dict[str, Any]) -> List[FactorSpec]:
        return [_fs(st["factors"][k]) for k in sorted(st["factors"])]

    def _doe_cqas(self, st: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [c for c in st["cqas"].values() if c.get("analysis_role") == "DOE_RESPONSE"]

    def _response_key(self, c: Dict[str, Any]) -> str:
        return c.get("response_key") or c["cqa_id"]

    def _labloop(self, st: Dict[str, Any], trigger: str) -> None:
        sug = L.suggest(self.pkg, trigger)
        st["labloop"]["current"] = sug and {**sug, "trigger": trigger, "at_status": st["status"]}

    # ======================================================================
    # D0 handoff (RB01)
    # ======================================================================
    def _act_handoff_data(self, st, p, actor):
        """빠진 값을 채운 새 handoff revision — 이전 revision은 남긴다(불변)."""
        h = copy.deepcopy(st["handoff"])
        if p.get("equipment_id"):
            h["equipment_id"] = str(p["equipment_id"])
        if p.get("batch_scale"):
            h["batch_scale"] = p["batch_scale"]
        for mat, grade in (p.get("material_grades") or {}).items():
            for i in h["ingredients"]:
                if i["material_id"] == mat and grade:
                    i["material_grade"] = str(grade)
        n = len(st["handoff_history"])
        h["handoff_id"] = st["handoff_history"][0] + f"-r{n}"
        h["unresolved_fields"] = [f for f in h.get("unresolved_fields", [])
                                  if not ((f == "equipment_id" and h.get("equipment_id")) or (f == "batch_scale" and h.get("batch_scale"))
                                          or (f.startswith("material_grade") and all(i.get("material_grade") for i in h["ingredients"] if i.get("is_critical"))))]
        h["created_by"], h["created_at"] = actor, H.now()
        h["formulation_fingerprint"] = H.fingerprint(h)
        st["handoff"] = h
        st["handoff_history"].append(h["handoff_id"])
        ds = self._record(st, "handoff", G.handoff_readiness(self.pkg, h))
        return {"handoff_id": h["handoff_id"], "blocking": [d["rule_id"] for d in self._blocking(ds)]}

    def _act_handoff_confirm(self, st, p, actor):
        h = st["handoff"]
        ds = G.handoff_readiness(self.pkg, h)
        if h.get("formulation_fingerprint") != H.fingerprint(h):
            ds.append(G._decide(self.pkg, "RB01", "HR012", detail="fingerprint 불일치"))
        ds = self._record(st, "handoff", ds)
        if self._blocking(ds):
            return {"blocked": [d["rule_id"] for d in self._blocking(ds)]}
        st["cqas"] = C.draft(self.pkg, h)
        self._move(st, "CQA_REVIEW", "HANDOFF_CONFIRMED", rule="RB01")
        self._record(st, "cqa", G.cqa_eligibility(self.pkg, st["cqas"]))
        return {}

    # ======================================================================
    # D1 CQA (RB02 · RB03)
    # ======================================================================
    def _act_cqa_edit(self, st, p, actor):
        changed = C.apply_edits(st["cqas"], p.get("edits") or [])
        self._record(st, "cqa", G.cqa_eligibility(self.pkg, st["cqas"]))
        return {"changed": changed}

    def _act_cqa_approve(self, st, p, actor):
        if not self._doe_cqas(st):
            raise StudyError("DOE_RESPONSE로 고른 CQA가 없습니다 — 모델링할 반응을 하나 이상 고르세요.", status=422)
        for c in self._doe_cqas(st):
            if c.get("quantity_kind") and c.get("unit") and G.unit_compatible(self.pkg, c["unit"], c["quantity_kind"]) is False:
                raise StudyError(f"{c['cqa_id']}: 단위 {c['unit']}는 {c['quantity_kind']}의 단위가 아닙니다(M04).", status=422)
        ds = self._record(st, "cqa", G.cqa_eligibility(self.pkg, st["cqas"]))
        if self._blocking(ds):
            return {"blocked": [d["rule_id"] for d in self._blocking(ds)]}
        for c in st["cqas"].values():
            c["approval_status"] = "APPROVED"
        st["criteria_hash"] = _hash({k: {f: c.get(f) for f in ("analysis_role", "acceptance_operator", "lower", "upper", "target",
                                                                   "target_tolerance")} for k, c in st["cqas"].items()})
        st["fmea"] = {"version": st["fmea"]["version"] + 1, "rows": F.draft(self.pkg, st["handoff"]["process_route_id"], list(st["cqas"])),
                      "approved": False}
        self._move(st, "FMEA_REVIEW", "CQA_APPROVED", rule="RB03")
        return {}

    # ======================================================================
    # D2 FMEA (RB04 · RB05)
    # ======================================================================
    def _act_fmea_edit(self, st, p, actor):
        rows = {r["row_id"]: r for r in st["fmea"]["rows"]}
        changed = []
        for e in p.get("rows") or []:
            r = rows.get(e.get("row_id"))
            if r is None:
                raise StudyError(f"FMEA 행 {e.get('row_id')} 없음", status=422)
            before = json.dumps(r, sort_keys=True, default=str)
            if "severity" in e:
                s = e["severity"]
                if s not in (None, "") and int(s) not in (1, 2, 3, 4, 5):
                    raise StudyError("심각도는 1–5(RB05)", status=422)
                r["severity"] = None if s in (None, "") else int(s)
            if "occurrence" in e:
                o = e["occurrence"]
                if o in (None, "", "UNKNOWN"):
                    r["occurrence"] = "UNKNOWN"
                elif int(o) in (1, 3, 5):
                    r["occurrence"] = int(o)
                else:
                    raise StudyError("발생도는 UNKNOWN·1·3·5(RB05)", status=422)
            if "detectability" in e:
                dv = e["detectability"]
                if dv not in (None, "") and int(dv) not in (1, 3, 5):
                    raise StudyError("검출도는 1·3·5(RB05)", status=422)
                r["detectability"] = None if dv in (None, "") else int(dv)
            if "disposition" in e:
                if e["disposition"] not in F.DISPOSITIONS:
                    raise StudyError(f"처분은 {', '.join(F.DISPOSITIONS)} 중 하나", status=422)
                r["disposition"] = e["disposition"]
            for k in ("rationale", "alternative_control", "detection_method_id", "occurrence_evidence"):
                if k in e:
                    r[k] = e[k] or None
            if "evidence_refs" in e:
                r["evidence_refs"] = list(e["evidence_refs"] or [])
            r["rpn"] = F.rpn(r)
            if json.dumps(r, sort_keys=True, default=str) != before:
                changed.append(r["row_id"])
        if changed:
            st["fmea"]["version"] += 1
        self._record(st, "fmea", [self._policy(v["policy"], v["message_ko"], row=v["row_id"]) for v in F.check(st["fmea"]["rows"])])
        return {"changed": changed}

    def _act_fmea_approve(self, st, p, actor):
        ds = self._record(st, "fmea", [self._policy(v["policy"], v["message_ko"], row=v["row_id"]) for v in F.check(st["fmea"]["rows"])])
        if ds:
            return {"blocked": [d["rule_id"] for d in ds]}
        st["fmea"]["approved"] = True
        st["factor_candidates"] = F.factor_candidates(st["fmea"]["rows"])
        self._move(st, "FACTOR_SELECTION", "FMEA_APPROVED", rule="RB05")
        return {}

    # ======================================================================
    # D3 요인 선택 (RB06)
    # ======================================================================
    def _act_factor_select(self, st, p, actor):
        cands = {c["key"]: c for c in st["factor_candidates"]}
        sel = p.get("selected") or []
        if not sel:
            raise StudyError("요인을 하나 이상 고르세요.", status=422)
        cqa_ids = {k for k, c in st["cqas"].items() if c.get("analysis_role") != "NOT_APPLICABLE"}
        selected = []
        for s in sel:
            c = cands.get(s.get("key"))
            if c is None:
                raise StudyError(f"'{s.get('key')}'는 FMEA의 요인 후보가 아닙니다 — FMEA에서 먼저 다루세요.", status=422)
            if s.get("material_id") and not any(i["material_id"] == s["material_id"] for i in st["handoff"]["ingredients"]):
                raise StudyError(f"성분 {s['material_id']}가 handoff에 없습니다.", status=422)
            selected.append({"key": c["key"], "name": s.get("name") or c["key"], "kind": s.get("kind") or c.get("kind") or "CMA",
                             "material_id": s.get("material_id") or None, "linked_cqa_ids": sorted(set(c["linked_cqa_ids"]) & cqa_ids),
                             "fmea_refs": c["fmea_refs"]})
        fixed = {f.get("key"): f for f in (p.get("fixed") or [])}
        chosen = {s["key"] for s in selected}
        unselected = [{**c, "fixed_value": (fixed.get(c["key"]) or {}).get("fixed_value"),
                       "fixed_rationale": (fixed.get(c["key"]) or {}).get("fixed_rationale")}
                      for c in st["factor_candidates"] if c["high_risk"] and c["key"] not in chosen]
        ds = self._record(st, "factors", G.factor_selection(self.pkg, [{**s, "factor_id": s["key"]} for s in selected], unselected))
        if self._blocking(ds):
            return {"blocked": [d["rule_id"] for d in self._blocking(ds)]}
        st["selection"] = {"selected": selected, "fixed": list(fixed.values()), "by": actor, "at": H.now()}
        ings = {i["material_id"]: i for i in st["handoff"]["ingredients"]}
        st["factors"] = {}
        for n, s in enumerate(selected, 1):
            ref = ings.get(s["material_id"] or "", {}).get("percent_w_w")
            st["factors"][f"X{n}"] = {
                **asdict(FactorSpec(f"X{n}", s["name"], "%w/w" if s["material_id"] else None, None, None, None, kind=s["kind"],
                                    quantity_kind="fraction_mass" if s["material_id"] else None, reference_value=ref,
                                    reference_source="handoff REFERENCE_PROTOTYPE" if ref is not None else None)),
                "key": s["key"], "material_id": s["material_id"], "linked_cqa_ids": s["linked_cqa_ids"], "version": 1}
        self._move(st, "RANGE_EVIDENCE_CHECK", "FACTORS_SELECTED", rule="RB06")
        return {}

    # ======================================================================
    # D4 범위 (RB07) · D5 feasibility (RB08)
    # ======================================================================
    def _act_range_submit(self, st, p, actor):
        subs = {f.get("factor_id"): f for f in (p.get("factors") or [])}
        unknown = set(subs) - set(st["factors"])
        if unknown:
            raise StudyError(f"없는 요인: {sorted(unknown)}", status=422)
        for fid, s in subs.items():
            f = st["factors"][fid]
            ev = s.get("evidence_status") or {}
            for b in ("low", "center", "high"):
                v = ev.get(b)
                if v is not None and v not in RESEARCHER_RANGE_EVIDENCE:
                    raise StudyError(f"{fid} {b}: 근거 등급 {v}는 직접 고를 수 없습니다"
                                     + (" — FEASIBILITY_CONFIRMED는 feasibility 결과로만 생깁니다." if v == "FEASIBILITY_CONFIRMED" else "."), status=422)
            for k in ("unit", "quantity_kind"):
                if k in s:
                    f[k] = s[k] or None
            for k in ("low", "center", "high"):
                if k in s:
                    f[k] = _num(s[k])
            f["evidence_status"] = {b: ev.get(b) for b in ("low", "center", "high")}
            f["range_evidence_refs"] = list(s.get("range_evidence_refs") or [])
            f["applicability_confirmed"] = bool(s.get("applicability_confirmed"))
            f["center_source"] = "RESEARCHER_INPUT"          # 기준 처방값을 center로 복사하는 경로는 없다(RE003)
            f["version"] = int(f.get("version") or 1) + 1
        if st["status"] == "RANGE_REVISION_REQUIRED":
            self._move(st, "RANGE_EVIDENCE_CHECK", "RANGE_RESUBMITTED", rule="RB07")
        self._range_gate(st)
        return {"route": st["range_gate"]["route"]["result_code"]}

    def _range_gate(self, st) -> None:
        factors = self._factors(st)
        gate = G.range_evidence(self.pkg, factors, st["study_type"])
        unit_ds = []
        for f in factors:
            if f.unit and f.quantity_kind:
                ok = G.unit_compatible(self.pkg, f.unit, f.quantity_kind)
                if ok is False:
                    unit_ds.append(self._decide("RB07", "RE009", factor=f.factor_id, unit=f.unit, quantity_kind=f.quantity_kind))
                elif ok is None:
                    unit_ds.append(self._decide("RB07", "RE008", factor=f.factor_id, detail=f"M04에 없는 물리량 {f.quantity_kind}"))
        if unit_ds:
            gate["route"] = unit_ds[0]
        gate["unit_checks"] = unit_ds
        st["range_gate"] = gate
        self._record(st, "range", [gate["route"]] + [d for ds in gate["factors"].values() for d in ds] + unit_ds)

    def _act_range_approve(self, st, p, actor):
        if not st.get("range_gate") or any(f.get("low") is None for f in st["factors"].values()):
            raise StudyError("먼저 요인 범위를 제출하세요.", status=409)
        self._range_gate(st)
        route = st["range_gate"]["route"]
        if route["gate_effect"] in BLOCKING:
            return {"blocked": [route["rule_id"]]}
        target = resolve_state(route.get("next_state"))
        if target == "NEEDS_FEASIBILITY":
            plan = G.feasibility_plan(self.pkg, self._factors(st))
            st["feasibility"] = {"plan": plan, "results": None, "route": None, "round": len((st.get("feasibility") or {}).get("history", [])) + 1,
                                 "history": (st.get("feasibility") or {}).get("history", [])}
            self._move(st, "NEEDS_FEASIBILITY", route["result_code"], rule=route["rule_id"])
            self._record(st, "feasibility", plan["checks"])
            return {}
        if target == "DOE_RANGE_READY":
            self._move(st, "DOE_RANGE_READY", route["result_code"], rule=route["rule_id"])
            self._design(st)
            return {}
        self._route(st, route)
        return {}

    def _act_feasibility_plan_approve(self, st, p, actor):
        plan = st["feasibility"]["plan"]
        ds = self._record(st, "feasibility", plan["checks"])
        if self._blocking(ds):
            return {"blocked": [d["rule_id"] for d in self._blocking(ds)]}
        plan["approved_by"], plan["approved_at"] = actor, H.now()
        self._move(st, "WAITING_FEASIBILITY_RESULTS", "FEASIBILITY_PLAN_APPROVED", rule="RB08")
        return {}

    def _act_feasibility_results_submit(self, st, p, actor):
        fz = st["feasibility"]
        res = {}
        for cid, r in (p.get("results") or {}).items():
            res[cid] = {k: (None if r.get(k) is None else bool(r.get(k))) for k in ("manufacturable", "measurable", "critical_incompatibility")}
            res[cid]["note"] = r.get("note")
            res[cid]["batch_id"] = r.get("batch_id")
        ev = G.feasibility_evaluate(self.pkg, fz["plan"], res)
        route = ev["route"]
        self._record(st, "feasibility", [route])
        if route["gate_effect"] in BLOCKING:
            return {"blocked": [route["rule_id"]]}
        fz["results"], fz["route"] = res, route
        fz["history"].append({"round": fz["round"], "plan": fz["plan"], "results": res, "route": route["result_code"], "at": H.now()})
        if route["result_code"] == "FEASIBILITY_PASSED":
            # 새 근거 record — 연구자가 등급을 올린 것이 아니라 이번 feasibility 결과가 경계를 확인했다(FD009: 적합 set에는 넣지 않는다)
            for f in st["factors"].values():
                f["evidence_status"] = {b: "FEASIBILITY_CONFIRMED" for b in ("low", "center", "high")}
                f["range_evidence_refs"] = list(f.get("range_evidence_refs") or []) + [f"feasibility round {fz['round']}"]
            self._move(st, "DOE_RANGE_READY", route["result_code"], rule=route["rule_id"])
            self._design(st)
            return {}
        self._route(st, route)
        self._labloop(st, route["result_code"])
        return {}

    def _act_revise(self, st, p, actor):
        reason = (p.get("reason") or "").strip()
        if not reason:
            raise StudyError("재검토 사유를 적으세요.", status=422)
        cur = st["labloop"].get("current") or {}
        offered = {t["test_id"] for t in cur.get("tests", [])}
        chosen = list(p.get("tests") or [])
        if set(chosen) - offered:
            raise StudyError(f"제안되지 않은 시험: {sorted(set(chosen) - offered)} — M06 판별시험 후보에서만 고릅니다.", status=422)
        st["labloop"]["history"].append({"pattern_id": cur.get("pattern_id"), "trigger": cur.get("trigger"), "from": st["status"],
                                         "chosen_tests": chosen, "reason": reason, "by": actor, "at": H.now()})
        st["labloop"]["current"] = None
        st["fmea"]["approved"] = False
        st["active_plan"], st["run_sheet"], st["results"], st["models"] = None, None, {}, {}
        st["flags_accepted"], st["region"], st["verification"] = None, None, None
        self._move(st, "FMEA_REVIEW", "REVISION_STARTED", rule="RB18")
        return {}

    # ======================================================================
    # D6 설계 (RB09 · RB10) · D7 run sheet (RB11)
    # ======================================================================
    def _design(self, st) -> None:
        factors = self._factors(st)
        sd = G.select_design(self.pkg, factors).as_dict()
        st["design_decision"] = sd
        ds = [sd]
        if st["study_type"] == "LITERATURE_REPLAY":
            ds.append(self._decide("RB09", "DS009"))
        target = resolve_state(sd.get("next_state"))
        if target == "ADVANCED_DESIGN_REQUIRED":
            self._record(st, "design", ds)
            self._move(st, "ADVANCED_DESIGN_REQUIRED", sd["result_code"], rule=sd["rule_id"])
            return
        plan = D.generate(G.DESIGN_OF_CODE[sd["result_code"]], factors, seed=int(self.pkg.rulebooks["RB15"].get("random_seed", 20260926)))
        self._install_plan(st, plan, ds)

    def _install_plan(self, st, plan: Dict[str, Any], ds: List[Dict[str, Any]]) -> None:
        plan["version"] = len(st["plans"]) + 1
        st["plans"].append(plan)
        st["active_plan"] = len(st["plans"]) - 1
        st["run_sheet"] = self._compile(st, plan, self._default_balance(st))
        self._record(st, "design", ds + self._dv(plan, self._factors(st)) + self._rs(st))
        if st["status"] == "DOE_PLAN_REVIEW":
            st["timeline"].append({"from": st["status"], "to": st["status"], "reason": "DOE_PLAN_REPLACED", "rule": "RB10",
                                   "at": H.now(), "seq": st["action_seq"]})
        else:
            self._move(st, "DOE_PLAN_REVIEW", "DOE_PLAN_DRAFTED", rule="RB10")

    def _dv(self, plan, factors) -> List[Dict[str, Any]]:
        """design.validate 검사 → RB10 행."""
        chk = {c["check"]: c for c in plan["validation"]["checks"]}
        out = []
        fail = lambda k: k in chk and not chk[k]["ok"]  # noqa: E731
        if fail("full_quadratic_estimable"):
            out.append(self._decide("RB10", "DV001", detail=chk["full_quadratic_estimable"]["detail"]))
        k = len(factors)
        n_terms = (k + 1) * (k + 2) // 2
        resid = len(plan["runs"]) - n_terms
        if resid < float(self.pkg.constants.get("residual_df_min", 1)):
            out.append(self._decide("RB10", "DV002", residual_df=resid))
        elif resid < float(self.pkg.constants.get("residual_df_warning", 3)):
            out.append(self._decide("RB10", "DV003", residual_df=resid))
        if plan["center_points"] < 2:
            out.append(self._decide("RB10", "DV005"))
        if fail("within_low_high"):
            out.append(self._decide("RB10", "DV006"))
        if plan.get("random_seed") is None:
            out.append(self._decide("RB10", "DV009"))
        if plan["design_type"] == "BBD":
            out.append(self._decide("RB10", "DV010"))
        if fail("coded_actual_round_trip"):
            out.append(self._decide("RB10", "DV015"))
        if fail("run_count") or fail("no_duplicate_noncenter_runs"):
            out.append(self._decide("RB10", "DV016"))
        if fail("randomized"):
            out.append(self._decide("RB10", "DV017"))
        return out

    def _default_balance(self, st) -> Optional[str]:
        comp = {f.get("material_id") for f in st["factors"].values() if f.get("material_id")}
        if not comp:
            return None
        rest = [i for i in st["handoff"]["ingredients"] if i["material_id"] not in comp and not i.get("is_critical")]
        return max(rest, key=lambda i: float(i.get("percent_w_w") or 0))["material_id"] if rest else None

    def _compile(self, st, plan, balance) -> Dict[str, Any]:
        fs = [{"factor_id": k, **st["factors"][k]} for k in sorted(st["factors"])]
        return P.compile_run_sheet(st["handoff"], fs, plan["runs"], balance_material=balance)

    def _rs(self, st) -> List[Dict[str, Any]]:
        rs = st["run_sheet"]
        out = [self._decide("RB11", i["rule_id"], run=i["run_id"], detail=i["message_ko"]) for i in rs["issues"]]
        fixed = st["handoff"].get("fixed_parameters", [])
        if any(fp.get("value") is None or not fp.get("locator") for fp in fixed):
            out.append(self._decide("RB11", "PC007", parameters=[fp.get("name") for fp in fixed if fp.get("value") is None or not fp.get("locator")]))
        proto = st.get("protocol") or {}
        if not proto.get("sampling_plan") or not proto.get("stop_criteria"):
            out.append(self._decide("RB11", "PC008"))
        return out

    def _act_plan_approve(self, st, p, actor):
        plan = self._plan(st)
        st["protocol"] = {"sampling_plan": (p.get("sampling_plan") or "").strip() or None,
                          "stop_criteria": (p.get("stop_criteria") or "").strip() or None}
        bal = p.get("balance_material")
        if bal and bal != (st["run_sheet"] or {}).get("balance_material"):
            if not any(i["material_id"] == bal for i in st["handoff"]["ingredients"]):
                raise StudyError(f"balance 성분 {bal}가 handoff에 없습니다.", status=422)
            st["run_sheet"] = self._compile(st, plan, bal)
        ds = self._record(st, "design", [st["design_decision"]] + self._dv(plan, self._factors(st)) + self._rs(st))
        if self._blocking(ds):
            return {"blocked": [d["rule_id"] for d in self._blocking(ds)]}
        plan["locked_at"], plan["locked_by"] = H.now(), actor
        plan["locked_hash"] = _hash({"runs": plan["runs"], "run_sheet": st["run_sheet"], "protocol": st["protocol"]})
        self._move(st, "WAITING_FOR_RESULTS", "DOE_PLAN_APPROVED", rule="RB10")
        return {}

    def _act_plan_reject(self, st, p, actor):
        if not (p.get("reason") or "").strip():
            raise StudyError("반려 사유를 적으세요.", status=422)
        self._plan(st)["rejected"] = {"by": actor, "at": H.now(), "reason": p["reason"]}
        st["active_plan"], st["run_sheet"] = None, None
        self._move(st, "RANGE_EVIDENCE_CHECK", "DOE_PLAN_REJECTED")
        return {}

    def _imported_plan(self, st, p) -> Dict[str, Any]:
        """실행된(또는 외부에서 검증된) 설계 행렬 → 계획. run 순서는 seed로 무작위화, 설계점 집합이 표준 설계와 같으면
        지지 영역 정책을 그 설계로(design_family). 같은 Validator(RB10)를 다시 지난다."""
        factors = self._factors(st)
        runs_in = p.get("runs") or []
        n_terms = (len(factors) + 1) * (len(factors) + 2) // 2
        if len(runs_in) < n_terms + 1:
            raise StudyError(f"설계 행렬 run이 {len(runs_in)}개 — 2차 모형 항 {n_terms}개 + 잔차 자유도 1 이상이 필요합니다.", status=422)
        seed = int(self.pkg.rulebooks["RB15"].get("random_seed", 20260926))
        order = np.random.default_rng(seed).permutation(len(runs_in))
        runs = []
        for run_no, idx in enumerate(order, 1):
            src = runs_in[idx].get("actual") or {}
            act = {}
            for f in factors:
                v = _num(src.get(f.factor_id))
                if v is None:
                    raise StudyError(f"행렬 {idx + 1}행: 요인 {f.factor_id} 값이 없습니다.", status=422)
                act[f.factor_id] = v
            coded = {f.factor_id: D.to_coded(act[f.factor_id], f) for f in factors}
            runs.append({"run_id": f"R{run_no:02d}", "std_order": int(idx) + 1, "run_order": run_no, "coded": coded, "actual": act,
                         "is_center": all(abs(v) < 1e-12 for v in coded.values()), "label": runs_in[idx].get("label")})
        ids = [f.factor_id for f in factors]
        plan = {"design_type": "IMPORTED", "design_family": D.classify(runs, ids), "factors": ids, "random_seed": seed,
                "center_points": sum(r["is_center"] for r in runs), "runs": runs, "intended_model_family": "HIERARCHICAL_QUADRATIC",
                "source": p.get("source")}
        plan["matrix_hash"] = _hash([[r["std_order"], r["coded"]] for r in runs])
        plan["validation"] = D.validate(plan, factors)
        return plan

    def _act_design_import(self, st, p, actor):
        self._install_plan(st, self._imported_plan(st, p), [st["design_decision"]] if st.get("design_decision") else [])
        return {}

    def _act_plan_import(self, st, p, actor):
        """DOE_PLAN_REVIEW에서 초안 대신 이미 실행된 행렬을 쓴다(선행 batch·외부 원자료·문헌 데이터셋). 초안은 plans[]에 남는다."""
        prev = self._plan(st)
        if prev is not None:
            prev["replaced"] = {"by": actor, "at": H.now(), "reason": p.get("source") or "실행 행렬로 교체"}
        self._install_plan(st, self._imported_plan(st, p), [st["design_decision"]] if st.get("design_decision") else [])
        return {"design_family": self._plan(st).get("design_family")}

    def parse_results_csv(self, study_id: str, text: str) -> Dict[str, Any]:
        from formula.doe import dataset as DS
        st, _ = self._load(study_id)
        if st["status"] != "WAITING_FOR_RESULTS":
            raise StudyError("결과 CSV는 결과 입력 단계에서만 읽습니다.", status=409)
        try:
            return DS.parse_results_csv(st, text)
        except DS.DatasetError as exc:
            raise StudyError(str(exc), status=422)

    # ======================================================================
    # D8 결과 (RB12 · M05)
    # ======================================================================
    def _act_results_submit(self, st, p, actor):
        plan = self._plan(st)
        runs = {r["run_id"]: r for r in plan["runs"]}
        keys = [self._response_key(c) for c in self._doe_cqas(st)]
        rows = {}
        for r in p.get("rows") or []:
            rid = r.get("run_id")
            if rid not in runs:
                raise StudyError(f"계획에 없는 run {rid}", status=422)
            vals = {}
            for k in keys:
                v = (r.get("values") or {}).get(k)
                if v is None or v == "":
                    raise StudyError(f"{rid}: 반응 {k} 값이 없습니다.", status=422)
                vals[k] = _num(v)
            ev = r.get("evidence_status")
            if ev not in RESULT_EVIDENCE:
                raise StudyError(f"{rid}: 근거 등급 {ev}는 결과 등급이 아닙니다({', '.join(RESULT_EVIDENCE)}).", status=422)
            rows[rid] = {"run_id": rid, "batch_id": r.get("batch_id") or None, "parent_blend_id": r.get("parent_blend_id") or None,
                         "test_method_version": r.get("test_method_version") or None,
                         "replicate_independence": r.get("replicate_independence") or "UNKNOWN", "evidence_status": ev,
                         "source_locator": r.get("source_locator"), "values": vals, "human_verification_status": "UNCONFIRMED",
                         "submitted_by": actor, "submitted_at": H.now()}
        missing = sorted(set(runs) - set(rows))
        if missing:
            raise StudyError(f"결과가 없는 run: {', '.join(missing)}", status=422)
        st["results"] = rows
        self._move(st, "RESULT_QUALITY_REVIEW", "RESULTS_SUBMITTED")
        self._record(st, "results", self._quality(st))
        return {}

    def _quality(self, st) -> List[Dict[str, Any]]:
        rows = list(st["results"].values())
        ds = [d.as_dict() for d in G.result_quality(self.pkg, rows, study_type=st["study_type"], plan_locked=bool(self._plan(st).get("locked_hash")))]
        # 같은 batch·같은 blend를 서로 다른 run으로 세면 가짜 반복(RQ009)
        for key in ("batch_id", "parent_blend_id"):
            seen: Dict[str, List[str]] = {}
            for r in rows:
                if r.get(key):
                    seen.setdefault(r[key], []).append(r["run_id"])
            for v, rids in seen.items():
                if len(rids) > 1:
                    ds.append(self._decide("RB12", "RQ009", runs=rids, **{key: v}))
        if any(r["evidence_status"] == "LITERATURE_DIGITIZED" for r in rows):
            ds.append(self._decide("RB12", "RQ011"))
        return ds

    def _act_results_revise(self, st, p, actor):
        self._move(st, "WAITING_FOR_RESULTS", "RESULTS_REVISION")
        return {}

    def _act_results_confirm(self, st, p, actor):
        for r in st["results"].values():
            r["human_verification_status"] = "CONFIRMED"
            r["confirmed_by"], r["confirmed_at"] = actor, H.now()
        ds = self._record(st, "results", self._quality(st))
        if self._blocking(ds):
            return {"blocked": sorted({d["rule_id"] for d in self._blocking(ds)})}
        self._move(st, "MODEL_FIT", "RESULTS_CONFIRMED", rule="RB12")
        self._fit(st)
        return {}

    # ======================================================================
    # D9 모델 (RB14 · RB15) · D10 영역 (RB16)
    # ======================================================================
    def _coded(self, st):
        plan = self._plan(st)
        ids = sorted(st["factors"])
        runs = plan["runs"]
        coded = {i: np.array([r["coded"][i] for r in runs], dtype=float) for i in ids}
        center = np.array([r["is_center"] for r in runs])
        return ids, runs, coded, center

    def _fit(self, st) -> None:
        ids, runs, coded, center = self._coded(st)
        ds, statuses = [], {}
        for c in self._doe_cqas(st):
            key = self._response_key(c)
            y = np.array([st["results"][r["run_id"]]["values"][key] for r in runs], dtype=float)
            res = select_model(coded, y, center_mask=center, constants=self.pkg.constants)
            gate = res.get("gate") or {"status": res["status"], "blocks": [], "flags": []}
            for b in gate["blocks"]:
                ds.append(self._decide("RB14", b["rule_id"], response=key, detail=b["detail"]))
            for fl in gate["flags"]:
                ds.append(self._decide("RB14", fl["rule_id"], response=key, detail=fl["detail"]))
            sel = res.get("selected")
            st["models"][c["cqa_id"]] = _plain({
                "response_key": key, "status": res["status"], "gate": gate, "policy": res.get("policy"),
                "best_cv": res.get("best_cv"), "one_se_set": res.get("one_se_set"), "history": res.get("history"),
                "candidates": res.get("candidates"), "estimable": res.get("estimable"),
                "selected": sel and {k: sel[k] for k in ("formula", "terms", "coef", "cov", "mse", "df_resid", "r2", "adj_r2", "pred_r2",
                                                         "cv_rmse", "aicc", "lack_of_fit", "p", "n") if k in sel}})
            statuses[c["cqa_id"]] = res["status"]
        self._record(st, "model", ds)
        if any(s == "MODEL_INADEQUATE" for s in statuses.values()):
            lof = any(d["rule_id"] == "MV004" for d in ds)
            self._move(st, "MODEL_INADEQUATE", "MODEL_INVALID", rule="RB14")
            self._labloop(st, "MODEL_LOF_DIAGNOSIS" if lof else "MODEL_PREDICTIVITY_DIAGNOSIS")
            return
        if any(s == "VALID_WITH_FLAGS" for s in statuses.values()):
            return        # MODEL_FIT에 머문다 — 연구자의 MODEL_ACCEPTANCE_WITH_FLAGS 승인 대기
        self._region(st)

    def _act_model_accept_flags(self, st, p, actor):
        why = (p.get("rationale") or "").strip()
        if not why:
            raise StudyError("플래그를 받아들이는 사유를 적으세요.", status=422)
        flagged = [k for k, m in st["models"].items() if m["status"] == "VALID_WITH_FLAGS"]
        if not flagged:
            raise StudyError("승인할 플래그가 없습니다.", status=409)
        for k in flagged:
            st["models"][k]["status"] = "ACCEPTED_WITH_FLAGS"
        st["flags_accepted"] = {"by": actor, "at": H.now(), "rationale": why, "responses": flagged}
        self._region(st)
        return {"approved": True}

    def _responses(self, st) -> List[Dict[str, Any]]:
        out = []
        for c in self._doe_cqas(st):
            op, lo, hi = c.get("acceptance_operator"), c.get("lower"), c.get("upper")
            if op == "TARGET_TOL":
                op, lo, hi = "BETWEEN", c["target"] - c["target_tolerance"], c["target"] + c["target_tolerance"]
            out.append({"id": c["cqa_id"], "key": self._response_key(c), "operator": op, "lower": lo, "upper": hi,
                        "unit": c.get("unit"), "name": c.get("name")})
        return out

    def _design_type(self, st) -> str:
        plan = self._plan(st)
        return plan.get("design_family") or plan["design_type"]

    def _region(self, st) -> None:
        ds = []
        bad = [k for k, m in st["models"].items() if m["status"] not in ("VALID", "ACCEPTED_WITH_FLAGS")]
        if bad:
            ds.append(self._decide("RB16", "DR001", responses=bad))
        resp = self._responses(st)
        if any(r["operator"] not in ("LE", "GE", "BETWEEN") for r in resp):
            ds.append(self._decide("RB16", "DR002", responses=[r["id"] for r in resp if r["operator"] not in ("LE", "GE", "BETWEEN")]))
        if self._blocking(ds):
            self._record(st, "region", ds)
            return
        ids = sorted(st["factors"])
        models = {k: m["selected"] for k, m in st["models"].items()}
        region = RG.compute_region(self._design_type(st), ids, models, resp,
                                   steps=int(self.pkg.constants.get("region_grid_points_per_axis", 21)),
                                   p_min=float(self.pkg.constants.get("joint_pass_probability", RG.P_MIN_DEMO)))
        region["criteria_hash"] = st.get("criteria_hash")
        region["model_formulas"] = {k: m["formula"] for k, m in models.items()}
        ds.append(self._decide("RB16", "DR007"))
        if region["status"] != "PROVISIONAL":
            d = self._decide("RB16", "DR018", max_joint_p=region["setpoint_joint_p"], p_min=region["policy"]["p_min"])
            ds.append(d)
            st["region"] = _plain(region)
            self._record(st, "region", ds)
            self._route(st, d)
            self._labloop(st, "REGION_EMPTY_DIAGNOSIS")
            return
        region["proposal"] = self._proposal(st, region)
        st["region"] = _plain(region)
        self._record(st, "region", ds)
        self._move(st, "PROVISIONAL_DESIGN_SPACE", "REGION_PROVISIONAL", rule="RB16")

    def _joint(self, st, P: np.ndarray) -> np.ndarray:
        ids = sorted(st["factors"])
        pts = {i: P[:, j] for j, i in enumerate(ids)}
        joint = np.ones(len(P))
        for r in self._responses(st):
            m = st["models"][r["id"]]["selected"]
            pr = predict(m, pts)
            joint *= RG.pass_prob(r, pr["mean"], pr["se_pred"], m["df_resid"])
        return joint

    def _proposal(self, st, region) -> List[Dict[str, Any]]:
        """확인점 제안 — SETPOINT = 공동 통과확률 최대점, BOUNDARY = 영역 안에서 setpoint와 가장 먼 점,
        ROBUSTNESS = setpoint에서 모든 요인을 격자 한 칸씩 동시에 움직인 점(영역 안인 방향). 연구자가 고칠 수 있다."""
        ids = sorted(st["factors"])
        steps = region["policy"]["grid_steps"]
        g = np.linspace(-1, 1, steps)
        P = np.array(np.meshgrid(*[g] * len(ids), indexing="ij")).reshape(len(ids), -1).T
        P = P[RG.in_domain(self._design_type(st), P)]
        joint = self._joint(st, P)
        ok = joint >= region["policy"]["p_min"]
        sp = np.array([region["setpoint_coded"][i] for i in ids])
        feas = P[ok]
        bd = feas[int(np.argmax(np.linalg.norm(feas - sp, axis=1)))]
        step = g[1] - g[0]
        away = np.where(bd - sp >= 0, -1.0, 1.0)          # 경계점 반대 방향이 먼저
        rb = None
        for cand in (sp + step * away, sp - step * away):
            cand = np.clip(cand, -1, 1)
            if RG.in_domain(self._design_type(st), cand[None, :])[0] and self._joint(st, cand[None, :])[0] >= region["policy"]["p_min"]:
                rb = cand
                break
        pts = [("SETPOINT", sp), ("BOUNDARY", bd)] + ([("ROBUSTNESS", rb)] if rb is not None else [])
        fs = {f.factor_id: f for f in self._factors(st)}
        return [{"role": role, "coded": {i: float(v[j]) for j, i in enumerate(ids)},
                 "actual": {i: D.to_actual(float(v[j]), fs[i]) for j, i in enumerate(ids)},
                 "joint_p": float(self._joint(st, v[None, :])[0])} for role, v in pts]

    # ======================================================================
    # D11 확인 (RB17)
    # ======================================================================
    def _act_vplan_lock(self, st, p, actor):
        ids = sorted(st["factors"])
        points = p.get("points") or []
        ds = []
        roles = [pt.get("role") for pt in points]
        if any(r not in VERIFICATION_ROLES for r in roles) or any(r not in roles for r in VERIFICATION_ROLES):
            ds.append(self._decide("RB17", "VR001", roles=roles))
        coded_pts = []
        for pt in points:
            c = {i: _num((pt.get("coded") or {}).get(i)) for i in ids}
            if any(v is None for v in c.values()):
                raise StudyError(f"{pt.get('role')}: 요인 coded 값이 빠졌습니다.", status=422)
            coded_pts.append((pt.get("role"), c))
        dom = RG.in_domain(self._design_type(st), np.array([[c[i] for i in ids] for _, c in coded_pts])) if coded_pts else []
        if not all(bool(x) for x in dom):
            ds.append(self._decide("RB16", "DR003", roles=[r for (r, _), ok in zip(coded_pts, dom) if not ok]))
        ds = self._record(st, "verification", ds)
        if self._blocking(ds):
            return {"blocked": [d["rule_id"] for d in self._blocking(ds)]}
        models = {k: m["selected"] for k, m in st["models"].items()}
        keys = [r["id"] for r in self._responses(st)]
        fs = {f.factor_id: f for f in self._factors(st)}
        locked = []
        for role, c in coded_pts:
            lp = RG.lock_verification_plan(c, keys, models, level=PI_LEVEL, role=role)
            lp["actual"] = {i: D.to_actual(c[i], fs[i]) for i in ids}
            locked.append(lp)
        plan = {"points": locked, "pi_policy": {"level": PI_LEVEL, "method": "t 예측구간(잔차 df), 결과 전 계산"},
                "locked_at": H.now(), "locked_by": actor, "scope_hash": st["region"]["hash"]}
        plan["locked_hash"] = _hash(plan)
        st["verification"] = {"plan": _plain(plan), "submissions": [], "verdict": None}
        self._move(st, "WAITING_VERIFICATION_RESULTS", "VERIFICATION_PLAN_LOCKED", rule="RB17")
        return {}

    def _act_verification_submit(self, st, p, actor):
        v = st["verification"]
        plan = v["plan"]
        roles = {pt["role"]: pt for pt in plan["points"]}
        resp = {r["id"]: r for r in self._responses(st)}
        subs = {s.get("role"): s for s in (p.get("points") or [])}
        fit_batches = {r.get("batch_id") for r in st["results"].values() if r.get("batch_id")}
        fit_blends = {r.get("parent_blend_id") for r in st["results"].values() if r.get("parent_blend_id")}
        ds, dep = [], set()
        coverage_ok = all(r in subs and all(subs[r].get("values", {}).get(k) for k in resp) for r in roles)
        if not coverage_ok:
            ds.append(self._decide("RB17", "VR014", missing=[r for r in roles if r not in subs]))
        batches = [s.get("batch_id") for s in subs.values()]
        if any(not b for b in batches):
            ds.append(self._decide("RB12", "RQ001"))
        for role, s in subs.items():
            if s.get("batch_id") in fit_batches or (s.get("parent_blend_id") and s["parent_blend_id"] in fit_blends):
                ds.append(self._decide("RB17", "VR003", role=role, batch_id=s.get("batch_id")))
                ds.append(self._decide("RB17", "VR019", role=role))
                dep.add(role)
        if len(set(b for b in batches if b)) < len([b for b in batches if b]):
            ds.append(self._decide("RB17", "VR013", batches=batches))
            dep |= set(subs)
        blends = [s.get("parent_blend_id") for s in subs.values() if s.get("parent_blend_id")]
        if len(set(blends)) < len(blends):
            ds.append(self._decide("RB12", "RQ009", parent_blends=blends))
            dep |= set(subs)
        for role, s in subs.items():
            ev = s.get("evidence_status")
            independent = role not in dep
            if not (G.evidence_permits(self.pkg, ev, "VERIFICATION") and (ev != G.VERIFICATION_BATCH or independent)):
                ds.append(self._decide("RB17", "VR015", role=role, evidence=ev))
        sub_rec = {"at": H.now(), "by": actor, "points": _plain(list(subs.values()))}
        v["submissions"].append(sub_rec)
        if v.get("first_result_at") is None:
            v["first_result_at"] = sub_rec["at"]
        if self._blocking(ds):
            self._record(st, "verification", ds)
            return {"blocked": sorted({d["rule_id"] for d in self._blocking(ds)})}
        points, codes = [], []
        for role, pt in roles.items():
            lots = {rid: [float(x) for x in subs[role]["values"][rid]] for rid in resp}
            ev = RG.evaluate_verification(pt, lots, resp)
            points.append({"role": role, "batch_id": subs[role].get("batch_id"), **ev})
            codes.append(ev["route"])
            rule = {"VERIFICATION_PASSED": "VR004", "VERIFICATION_MODEL_MISMATCH": "VR005"}.get(ev["route"], "VR006")
            ds.append(self._decide("RB17", rule, role=role))
        worst = next((c for c in ("VERIFICATION_MODEL_AND_SPEC_FAILURE", "VERIFICATION_SPEC_FAILURE", "VERIFICATION_MODEL_MISMATCH") if c in codes),
                     "VERIFICATION_PASSED")
        v["verdict"] = {"points": points, "route": worst, "all_pass": worst == "VERIFICATION_PASSED"}
        if worst == "VERIFICATION_PASSED":
            ds.append(self._decide("RB17", "VR011"))
            self._record(st, "verification", ds)
            return {"all_pass": True}
        self._record(st, "verification", ds)
        self._move(st, "REGION_REVISION_REQUIRED", worst, rule="RB17")
        self._labloop(st, worst)
        return {}

    def _act_final_approve(self, st, p, actor):
        v = st.get("verification") or {}
        if not (v.get("verdict") or {}).get("all_pass"):
            raise StudyError("모든 확인점이 통과해야 최종 승인할 수 있습니다(VR011).", status=409)
        if not (p.get("rationale") or "").strip():
            raise StudyError("최종 승인 사유를 적으세요.", status=422)
        self._record(st, "verification", [self._decide("RB17", "VR020")])
        st["region"]["status"] = "VERIFIED"
        st["region"]["verified_by"], st["region"]["verified_at"] = actor, H.now()
        self._move(st, "VERIFIED_OPERATING_REGION", "VERIFICATION_PASSED", rule="RB17 VR020")
        return {}

    # ======================================================================
    # 화면 — 지금 묻는 것 · 곡면
    # ======================================================================
    def _prompt(self, st) -> Dict[str, Any]:
        s = st["status"]
        cur = [e for e in st["evaluations"].values() if e["at_action"] == st.get("action_seq")]
        blocking = [d for e in cur for d in e["decisions"] if d.get("gate_effect") in BLOCKING]
        actions = [{"action": a, "approval_points": list(APPROVAL_POINT.get(a, ()))} for a in ACTIONS.get(s, ())]
        extra: Dict[str, Any] = {}
        if s == "MODEL_FIT":
            extra["flagged"] = [k for k, m in st["models"].items() if m["status"] == "VALID_WITH_FLAGS"]
        if s == "WAITING_VERIFICATION_RESULTS":
            extra["awaiting_final_approval"] = bool(((st.get("verification") or {}).get("verdict") or {}).get("all_pass"))
        return {"status": s, "step": STEP_OF.get(s), "question_ko": QUESTIONS.get(s, ""), "actions": actions,
                "blocking": blocking, "labloop": st["labloop"].get("current"), **extra}

    def surfaces(self, study_id: str, source: str = "selected", steps: int = 25, slice_factor: Optional[str] = None) -> Dict[str, Any]:
        """반응(행) × 세 번째 요인 수준(열) 곡면 격자. source=published는 문헌 재현 study에서만 — 논문 항 구성으로 같은 원자료를 재적합."""
        from formula.doe import dataset as DS
        st, _ = self._load(study_id)
        if not st["models"]:
            raise StudyError("아직 적합된 모델이 없습니다.", status=409)
        ids, runs, coded, center = self._coded(st)
        resp = self._responses(st)
        rows = [{"coded": r["coded"], "y": {c["id"]: st["results"][r["run_id"]]["values"][c["key"]] for c in resp}} for r in runs]
        models, info = {}, {}
        if source == "published":
            terms = DS.reported_terms(st)
            if terms is None:
                raise StudyError("보고된 모형 항 구성은 데이터셋에 reported_models가 있는 study에만 있습니다.", status=422)
            for c in resp:
                y = np.array([row["y"][c["id"]] for row in rows], dtype=float)
                m = fit_ols(terms[c["id"]], coded, y, center)
                models[c["id"]] = m
                info[c["id"]] = {"formula": m["formula"], "status": "PUBLISHED_TERMS_REFIT"}
        else:
            for k, m in st["models"].items():
                models[k] = m["selected"]
                info[k] = {"formula": m["selected"]["formula"], "status": m["status"]}
        responses = [{**c, **info.get(c["id"], {})} for c in resp]
        ids = sorted(st["factors"])
        if st.get("dataset"):            # 데이터셋 study는 데이터셋의 요인 순서(보고 그림과 같은 축 · 단면)
            pos = {f["key"]: n for n, f in enumerate(st["dataset"]["factors"])}
            ids.sort(key=lambda fid: pos.get(st["factors"][fid].get("key"), 99))
        if slice_factor in ids and len(ids) == 3:
            ids = [i for i in ids if i != slice_factor] + [slice_factor]
        out = SF.build(self._factors(st), models, responses, rows, design_type=self._design_type(st), steps=steps, order=ids)
        out["source"] = source
        out["factor_choices"] = [{"id": fid, "name": st["factors"][fid]["name"]} for fid in sorted(st["factors"])]
        out["published_available"] = bool((st.get("dataset") or {}).get("reported_models"))
        return _plain(out)

    def surface(self, study_id: str, response: Optional[str] = None, x3: float = 0.0, steps: int = 31) -> Dict[str, Any]:
        """반응 곡면 격자(X1×X2, 3요인이면 X3 고정 coded 값) + 공동 통과확률 + 실험점. 3D·contour 공용."""
        st, _ = self._load(study_id)
        if not st["models"]:
            raise StudyError("아직 적합된 모델이 없습니다.", status=409)
        ids = sorted(st["factors"])
        fs = {f.factor_id: f for f in self._factors(st)}
        resp = {r["id"]: r for r in self._responses(st)}
        rid = response if response in st["models"] else next(iter(st["models"]))
        g = np.linspace(-1, 1, steps)
        if len(ids) == 1:
            P = g[:, None]
        else:
            A, B = np.meshgrid(g, g, indexing="ij")
            cols = [A.ravel(), B.ravel()] + ([np.full(A.size, float(x3))] if len(ids) == 3 else [])
            P = np.stack(cols, axis=1)
        pts = {i: P[:, j] for j, i in enumerate(ids)}
        m = st["models"][rid]["selected"]
        mean = predict(m, pts)["mean"]
        dom = RG.in_domain(self._design_type(st), P)
        have_all = all(st["models"][k].get("selected") for k in resp)
        joint = self._joint(st, P) if have_all else None
        shape = (steps,) if len(ids) == 1 else (steps, steps)
        plan = self._plan(st)
        pts_out = []
        for r in plan["runs"]:
            if len(ids) == 3 and abs(r["coded"][ids[2]] - x3) > 1e-9:
                continue
            res = st["results"].get(r["run_id"], {})
            pts_out.append({"run_id": r["run_id"], "coded": r["coded"], "actual": r["actual"],
                            "y": (res.get("values") or {}).get(st["models"][rid]["response_key"])})
        axes = {i: {"coded": g.tolist(), "actual": [D.to_actual(float(c), fs[i]) for c in g], "name": fs[i].name, "unit": fs[i].unit}
                for i in ids[:2]}
        return _plain({"response": rid, "responses": list(st["models"]), "spec": resp.get(rid), "formula": m["formula"],
                       "status": st["models"][rid]["status"], "x3": x3 if len(ids) == 3 else None,
                       "x3_actual": D.to_actual(float(x3), fs[ids[2]]) if len(ids) == 3 else None,
                       "x3_factor": ids[2] if len(ids) == 3 else None, "axes": axes, "factors": ids,
                       "mean": mean.reshape(shape), "domain": dom.reshape(shape),
                       "joint": joint.reshape(shape) if joint is not None else None,
                       "p_min": float(self.pkg.constants.get("joint_pass_probability", RG.P_MIN_DEMO)), "points": pts_out})
