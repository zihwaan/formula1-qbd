"""DevelopmentService — ExperimentalDevelopmentGraph의 오케스트레이터 (명세 v6.1 §3.1, §5, §6).

한 study = 하나의 불변 Handoff에서 VERIFIED design space + scope까지. 이 클래스가 하는 일은
세 가지뿐이다.

1. **artifact → RuleContext 매핑**: 각 단계의 사실(CQA·FMEA 행·요인·plan·모델·영역·확인점)을
   manifest `context_schema` 모양의 dict로 옮긴다. 매핑에는 버전(`CONTEXT_MAPPING_VERSION`)이 붙는다.
2. **룰 집행 결과대로 전이**: `DoeRulebook.evaluate()`의 가장 강한 effect와 전이표만 따른다.
   판정 로직을 여기 쓰지 않는다 — 조건은 전부 `database/07_doe/**.csv` 한 줄이다.
3. **연구자 승인에서 멈추고 재개**: 모든 WAITING_* 상태에서 요청을 끝내고 state를 저장한다.

숫자는 `formula/qbd/`(결정론 엔진)가, 가설과 설명만 `formula/agents/development.py`(LLM)가 낸다.
연구자는 판단을 바꿀 수 있지만 근거 등급은 바꿀 수 없다(§0 경계 12, AA005).
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from formula.agents import development as agents
from formula.development import handoff as ho
from formula.development import states as sm
from formula.development.rules import DoeRulebook, Evaluation, load_rulebook
from formula.development.store import StudyStore, VersionConflict
from formula.qbd import cqa as cqa_mod
from formula.qbd import doe
from formula.qbd import factors as fac_mod
from formula.qbd import fmea as fmea_mod
from formula.qbd.analysis import TOOL_VERSIONS, Fit, fit_summary, model_context
from formula.qbd.design_space import (Domain, compute_region, edge_of, propose_verification_points,
                                      spec_pass)

CONTEXT_MAPPING_VERSION = "ctxmap-1.0"
FACTOR_ORDER = ["filler_ratio", "blend_time", "disintegrant_pct", "lubricant_pct", "lubrication_time",
                "compression_force", "glidant_pct", "api_psd", "sieve_mesh", "transfer_control"]


class StudyError(RuntimeError):
    """연구자에게 그대로 보여 줄 거절 사유 (HTTP 409/422)."""

    def __init__(self, message: str, *, status: int = 409, verdicts: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.status = status
        self.verdicts = verdicts or []


def _sid() -> str:
    return "DS-" + uuid.uuid4().hex[:10]


def _h(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


class DevelopmentService:
    def __init__(self, root: Path, store: Optional[StudyStore] = None):
        self.root = Path(root)
        self.rb: DoeRulebook = load_rulebook(str(self.root / "database" / "07_doe"))
        self.store = store or StudyStore()

    # ======================================================================
    # 공개 API — 모든 mutation은 _mutate()를 지난다 (idempotency · optimistic lock · 이벤트)
    # ======================================================================
    def create(self, handoff: Dict[str, Any], *, mode: str = "demo", actor: str = "researcher",
               idempotency_key: Optional[str] = None, demo_script: Optional[str] = None) -> Dict[str, Any]:
        replay = self.store.replay(idempotency_key)
        if replay:
            return self.view(replay["study_id"])
        if mode not in self.rb.modes:
            raise StudyError(f"알 수 없는 집행 모드 {mode}", status=422)
        sid = _sid()
        st: Dict[str, Any] = {
            "study_id": sid, "mode": mode, "status": "HANDOFF_CREATED", "state_version": 0,
            "created_at": ho.now(), "updated_at": ho.now(), "title": handoff.get("title"),
            "candidate_ref": f"{handoff['candidate_id']}@{handoff['candidate_version']}",
            "handoff": handoff, "handoff_history": [handoff["handoff_id"]],
            "demo_script": demo_script, "assumptions": list(handoff.get("assumptions", [])),
            "timeline": [], "evaluations": {}, "overrides": [], "decisions": [],
            "cqas": {}, "cqa_trace": [], "fmea": {"version": 0, "rows": []}, "factors": {},
            "plans": [], "active_plan": None, "results": {}, "models": {}, "region": None,
            "verification": None, "diagnosis": None, "return_point": None, "messages": [],
            "rulebook": {"id": "07_doe", "version": self.rb.version, "context_mapping": CONTEXT_MAPPING_VERSION},
        }
        self._say(st, "system", f"Handoff {handoff['handoff_id']} 생성 — 후보 {st['candidate_ref']}를 고정했습니다.")
        st["_decisions"] = []
        self._advance(st, actor)
        st.pop("_decisions", None)
        self.store.save(st, expected_version=None, event_type="STUDY_CREATED", idempotency_key=idempotency_key,
                        actor_id=actor, payload={"handoff_id": handoff["handoff_id"], "mode": mode},
                        result={"study_id": sid}, decisions=[], now=ho.now())
        return self.view(sid)

    def act(self, study_id: str, action: str, payload: Dict[str, Any], *, actor: str = "researcher",
            idempotency_key: Optional[str] = None, expected_version: Optional[int] = None) -> Dict[str, Any]:
        replay = self.store.replay(idempotency_key)
        if replay:
            out = self.view(study_id)
            out["replayed"] = True
            return out
        loaded = self.store.load(study_id)
        if not loaded:
            raise StudyError("study 없음", status=404)
        st, version = loaded
        if expected_version is not None and expected_version != version:
            raise VersionConflict(expected_version, version)
        handler = getattr(self, f"_act_{action}", None)
        if handler is None:
            raise StudyError(f"알 수 없는 행동 {action}", status=404)
        if st["status"] in sm.TERMINAL and action not in ("note",):
            raise StudyError(f"종료 상태({st['status']})의 study는 바꿀 수 없습니다. 새 Handoff로 시작하세요.")
        st["_decisions"] = []
        result = handler(st, payload or {}, actor) or {}
        self._advance(st, actor)
        decisions = st.pop("_decisions", [])
        st["decisions"].extend(decisions)
        st["updated_at"] = ho.now()
        self.store.save(st, expected_version=version, event_type=action.upper(), idempotency_key=idempotency_key,
                        actor_id=actor, payload=payload or {}, result={"study_id": study_id, **result},
                        decisions=decisions, now=ho.now())
        out = self.view(study_id)
        out["action_result"] = result
        return out

    def view(self, study_id: str) -> Dict[str, Any]:
        loaded = self.store.load(study_id)
        if not loaded:
            raise StudyError("study 없음", status=404)
        st, version = loaded
        st = dict(st)
        st["state_version"] = version
        st["phase"] = sm.phase_of(st["status"])
        st["phases"] = [{"key": k, "label": lbl} for k, lbl, _ in sm.PHASES]
        st["prompt"] = self._prompt(st)
        st["script"] = ho.LORNOXICAM_SCRIPT if st.get("demo_script") == "lornoxicam" else None
        st["enforced_rule_count"] = sum(self.rb.enforcement_allowed(r, st["mode"]) for r in self.rb.rules)
        if st.get("region") and st["region"].get("grid"):
            st["region"] = {k: v for k, v in st["region"].items() if k != "grid"}
            st["region"]["has_grid"] = True
        return st

    def trace(self, study_id: str) -> Dict[str, Any]:
        st, _ = self.store.load(study_id) or (None, None)
        if not st:
            raise StudyError("study 없음", status=404)
        ids = {
            "candidate": st["candidate_ref"], "handoff_id": st["handoff"]["handoff_id"], "study_id": study_id,
            "cqas": [f"{c['cqa_id']}@{c['version']}" for c in st["cqas"].values()],
            "fmea_version": st["fmea"].get("version"),
            "factors": [f"{f['factor_id']}@{f['version']}" for f in st["factors"].values()],
            "doe_plans": [f"{p['doe_plan_id']}@{p['version']}" for p in st["plans"]],
            "test_results": len(st["results"]),
            "response_models": [f"{m['response_model_id']}@{m['version']}" for ms in st["models"].values() for m in ms],
            "design_space": (f"{st['region']['design_space']['design_space_id']}@{st['region']['design_space']['version']}"
                             if st.get("region") else None),
            "verification_plan_id": (st.get("verification") or {}).get("plan", {}).get("verification_plan_id"),
            "decisions": [d.get("decision_id") for d in st["decisions"]],
        }
        return {"identifiers": ids, "timeline": st["timeline"], "events": self.store.events(study_id),
                "decisions": self.store.decisions(study_id)}

    def region_slice(self, study_id: str, fixed_symbol: str, value_index: int) -> Dict[str, Any]:
        st, _ = self.store.load(study_id) or (None, None)
        if not st or not st.get("region"):
            raise StudyError("영역 없음", status=404)
        g = st["region"]["grid"]
        axes, syms = g["axes"], g["symbols"]
        if fixed_symbol not in syms:
            raise StudyError("알 수 없는 요인", status=422)
        k = syms.index(fixed_symbol)
        shape = [len(a) for a in axes]
        P = np.array(g["P"]).reshape(shape)
        D = np.array([c == "1" for c in g["in_domain"]]).reshape(shape)
        margs = {c: np.array(v).reshape(shape) for c, v in g["marginals"].items()}
        idx = max(0, min(shape[k] - 1, value_index))
        take = lambda arr: np.take(arr, idx, axis=k)   # noqa: E731
        rest = [s for s in syms if s != fixed_symbol]
        worst = None
        if margs:
            names = list(margs)
            stack = np.stack([take(margs[c]) for c in names], axis=-1)
            worst = [[names[int(np.argmin(stack[i, j]))] for j in range(stack.shape[1])] for i in range(stack.shape[0])]
        return {"fixed": fixed_symbol, "fixed_value_coded": axes[k][idx], "index": idx, "x": rest[0], "y": rest[1],
                "x_axis": axes[syms.index(rest[0])], "y_axis": axes[syms.index(rest[1])],
                "P": np.round(take(P), 3).tolist(), "in_domain": take(D).astype(int).tolist(),
                "binding": worst, "threshold": self.rb.const("joint_pass_probability")}

    # ======================================================================
    # 자동 진행 — 결정론 상태를 돌고 WAITING_* 에서 멈춘다
    # ======================================================================
    def _advance(self, st: Dict[str, Any], actor: str) -> None:
        steps = {
            "HANDOFF_CREATED": lambda: self._move(st, "ENTRY_READINESS", "HANDOFF_FIXED"),
            "ENTRY_READINESS": lambda: self._entry_readiness(st),
            "CQA_DRAFTING": lambda: self._cqa_drafting(st),
            "FMEA_DRAFTING": lambda: self._fmea_drafting(st),
            "FACTOR_READINESS": lambda: self._factor_readiness(st),
            "DESIGN_SELECTION": lambda: self._design_selection(st),
            "SCREENING_PLANNING": lambda: self._planning(st, "SCREENING"),
            "RSM_PLANNING": lambda: self._planning(st, "RSM"),
            "RSM_AUGMENTATION": lambda: self._augmentation(st),
            "SCREENING_AUGMENTATION": lambda: self._augmentation(st),
            "SCREENING_ANALYSIS": lambda: self._screening_analysis(st),
            "MODEL_VALIDATION": lambda: self._model_validation(st),
            "REGION_COMPUTATION": lambda: self._region_computation(st),
            "VERIFICATION_PLANNING": lambda: self._verification_planning(st),
            "VERIFICATION_GATE": lambda: self._verification_gate(st),
            "DIAGNOSING": lambda: self._diagnosing(st),
            "REFLECTING": lambda: self._move(st, "WAITING_DIRECTIVE_APPROVAL", "DIRECTIVE_PROPOSED"),
        }
        for _ in range(40):
            before = (st["status"], st["state_version"], len(st["timeline"]))
            fn = steps.get(st["status"])
            if fn is None:
                return
            fn()
            if (st["status"], st["state_version"], len(st["timeline"])) == before:
                return   # 같은 자리에서 막힘 (BLOCK_STAGE) — 연구자 입력을 기다린다

    def _move(self, st: Dict[str, Any], dst: str, reason: str, *, detail: str = "") -> None:
        src = st["status"]
        if not sm.allowed(src, dst):
            # 표 밖 전이는 조용히 일으키지 않는다 — 복귀 지점을 남기고 human triage로
            st["return_point"] = src
            dst, reason = "WAITING_HUMAN_TRIAGE", f"UNKNOWN ({src}→{dst} 전이표에 없음)"
        if dst in sm.GLOBAL_EXCEPTIONS and st.get("return_point") is None:
            st["return_point"] = src
        st["status"] = dst
        st["timeline"].append({"from": src, "to": dst, "reason": reason, "detail": detail, "at": ho.now()})

    def _route(self, st: Dict[str, Any], ev: Evaluation, default: Optional[str] = None, reason: str = "") -> bool:
        """평가 결과로 전이한다. 반환값: 전이했는가."""
        if ev.next_state:
            self._move(st, ev.next_state, ev.reason_code or "", detail=ev.decisive.message if ev.decisive else "")
            return True
        if ev.blocking or ev.requests:
            return False
        if default:
            self._move(st, default, reason or "RULES_PASSED")
            return True
        return False

    def _eval(self, st: Dict[str, Any], key: str, stage: str, subjects, **kw) -> Evaluation:
        overrides = {(o["rule_id"], o.get("subject") or "*") for o in st["overrides"]}
        ev = self.rb.evaluate(stage, subjects, mode=st["mode"], helpers=self._helpers(st),
                              overrides=overrides, **kw)
        st["evaluations"][key] = ev.as_dict()
        return ev

    def _say(self, st: Dict[str, Any], who: str, text: str, **extra) -> None:
        st.setdefault("messages", []).append({"who": who, "text": text, "at": ho.now(),
                                              "state": st.get("status"), **extra})

    def _decide(self, st: Dict[str, Any], kind: str, actor: str, reason: str, **extra) -> Dict[str, Any]:
        d = {"decision_id": "DEC-" + uuid.uuid4().hex[:8], "kind": kind, "actor_id": actor, "reason": reason,
             "state": st["status"], "created_at": ho.now(), **extra}
        st["_decisions"].append(d)
        return d

    # -- 도메인 헬퍼 (manifest functions 중 서비스 몫) ------------------------------
    def _helpers(self, st: Dict[str, Any]) -> Dict[str, Callable]:
        eq_rows = self.rb.master("equipment_capability_master")
        eq_ids = set((st["handoff"].get("equipment_id") or "").split(";"))
        eq_params = {r["capability_parameter"] for r in eq_rows if r["equipment_id"] in eq_ids}

        def equipment_supports(f):
            src = (f.get("id") or "").replace("F_", "")
            if f.get("kind") == "CMA":
                return True   # 칭량으로 바뀌는 조성 요인
            return src in eq_params or bool(eq_ids - {""})

        def redundant(f, fs):
            return sum(1 for x in (fs or []) if x.get("id") == f.get("id")) > 1

        def intersection_empty(f):
            lo, hi = (f.get("low") or {}).get("value"), (f.get("high") or {}).get("value")
            if lo is None or hi is None:
                return False   # 경계가 아직 없으면 교집합을 따질 수 없다 — 그 결측은 FR002가 요청한다
            return lo >= hi

        return {
            "recompute_fingerprint": lambda h: ho.fingerprint(st["handoff"]),
            "equipment_supports": equipment_supports, "redundant_with_any": redundant,
            "protocol_available": lambda level: False,
            "excipient_range_exists": lambda f: bool(st["factors"].get(f.get("id"), {}).get("master_range")),
            "iid_reference_exists": lambda f: False,   # FDA IID snapshot 번들 안 됨 (manifest external_dependencies)
            "intersection_empty": intersection_empty, "block_confounded": lambda plan: False,
            "convertible": lambda a, b: a == b,
        }

    # ======================================================================
    # D1 Entry Readiness
    # ======================================================================
    def _entry_readiness(self, st: Dict[str, Any]) -> None:
        h = st["handoff"]
        cqas, trace = cqa_mod.draft_cqas(self.rb, h)
        st["cqa_candidates"] = cqas
        st["cqa_trace"] = trace
        ctx_h = self._handoff_ctx(h)
        subjects = [("handoff", {"handoff": ctx_h, "cqa_candidates": [cqa_mod.cqa_context(c) for c in cqas.values()]})]
        ev = self._eval(st, "readiness", "ENTRY_READINESS", subjects)
        st["readiness"] = {"requests": [v.as_dict() for v in ev.requests],
                           "blocking": [v.as_dict() for v in ev.blocking]}
        if ev.next_state:
            if ev.next_state == "WAITING_REQUIRED_DATA":
                msgs = " · ".join(dict.fromkeys(v.message.rstrip(".") for v in ev.requests))
                self._say(st, "system", f"진입 전에 필요한 자료가 있습니다: {msgs}", kind="request")
            self._move(st, ev.next_state, ev.reason_code or "")
            return
        if ev.blocking:
            return
        self._say(st, "system", "진입 Readiness 통과 — 조성·공정·설비·시험법이 갖춰졌습니다.")
        self._move(st, "CQA_DRAFTING", "READY")

    def _handoff_ctx(self, h: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "fingerprint": h["formulation_fingerprint"], "candidate_version": h["candidate_version"],
            "qtpp_snapshot_id": h.get("qtpp_snapshot_id"),
            "ingredients": [{"name": i["name"], "pct_w_w": i.get("pct_w_w"), "unit": i.get("unit"),
                             "grade": i.get("grade"), "is_critical": i.get("is_critical", False)}
                            for i in h["ingredients"]],
            "process_steps": [s["unit_op_code"] for s in h["process_steps"]],
            "equipment_id": h.get("equipment_id"), "batch_scale": h.get("batch_scale"),
            "fixed_parameters": [{"name": p["name"], "value": p.get("value"), "unit": p.get("unit"),
                                  "status": p.get("status")} for p in h["fixed_parameters"]],
            "rule_verdicts": [{"status": v.get("status"), "resolved": v.get("resolved", False)}
                              for v in h.get("upstream_verdicts", [])],
            "api_amount_fixed": True, "total_weight_fixed": True,
        }

    def _act_required_data(self, st, p, actor):
        if st["status"] != "WAITING_REQUIRED_DATA":
            raise StudyError("지금은 진입 자료를 받는 단계가 아닙니다.")
        h = copy.deepcopy(st["handoff"])
        if p.get("batch_scale"):
            h["batch_scale"] = str(p["batch_scale"])
        if p.get("equipment_id"):
            h["equipment_id"] = str(p["equipment_id"])
        for g in p.get("grades", []):
            for i in h["ingredients"]:
                if i["name"] == g.get("name"):
                    i["grade"] = g.get("grade") or None
        for fp in p.get("fixed_parameters", []):
            target = next((x for x in h["fixed_parameters"] if x["name"] == fp["name"]), None)
            if target is None:
                target = {"name": fp["name"], "unit": fp.get("unit"), "evidence_ref": None}
                h["fixed_parameters"].append(target)
            if fp.get("status") == "UNKNOWN":
                target.update(value=None, status="UNKNOWN", evidence_ref=fp.get("reason") or "연구자 기록: UNKNOWN")
            elif fp.get("value") not in (None, ""):
                target.update(value=float(fp["value"]), status="SET", evidence_ref=fp.get("reason") or "연구자 입력")
        # Handoff는 고치지 않는다 — 새 revision을 만든다 (§6 D0)
        rev = len(st["handoff_history"]) + 1
        h["handoff_id"] = h["handoff_id"].rsplit("-r", 1)[0] + f"-r{rev}"
        h["formulation_fingerprint"] = ho.fingerprint(h)
        h["created_at"] = ho.now()
        st["handoff"] = h
        st["handoff_history"].append(h["handoff_id"])
        unknown = [x["name"] for x in h["fixed_parameters"] if x["status"] == "UNKNOWN"]
        self._say(st, "researcher", "진입 자료 제출" + (f" — UNKNOWN 기록: {', '.join(unknown)}" if unknown else ""))
        self._decide(st, "REQUIRED_DATA", actor, p.get("reason", ""), handoff_id=h["handoff_id"])
        self._move(st, "ENTRY_READINESS", "DATA_SUBMITTED")
        return {"handoff_id": h["handoff_id"]}

    # ======================================================================
    # D2 CQA Contract
    # ======================================================================
    def _cqa_drafting(self, st):
        if not st["cqas"]:
            st["cqas"] = copy.deepcopy(st.get("cqa_candidates") or cqa_mod.draft_cqas(self.rb, st["handoff"])[0])
        self._check_cqas(st)
        self._say(st, "system", f"CQA 초안 {len(st['cqas'])}개를 제안했습니다. 역할·규격을 확인해 주세요.")
        self._move(st, "WAITING_CQA_APPROVAL", "CQA_DRAFTED")

    def _check_cqas(self, st) -> Evaluation:
        cqas = [cqa_mod.cqa_context(c) for c in st["cqas"].values()]
        subjects = [(c["id"], {"cqa": c}) for c in cqas] + [("CQA 전체", {"cqas": cqas})]
        return self._eval(st, "cqa", "WAITING_CQA_APPROVAL", subjects,
                          rulebooks=["cqa_response_definition_rules", "approval_authority_rules"])

    CQA_FIELDS = {"analysis_role", "acceptance_operator", "lower", "upper", "target", "target_tolerance",
                  "summary_definition", "criterion_source", "rationale_refs", "practical_effect_threshold",
                  "test_method_id", "unit", "criterion_type", "replicate_policy", "assumption"}

    def _act_cqa_edit(self, st, p, actor):
        if st["status"] != "WAITING_CQA_APPROVAL":
            raise StudyError("CQA 계약은 승인 대기 중에만 고칠 수 있습니다.")
        edits = p.get("edits") or [p]
        applied = []
        for e in edits:
            c = st["cqas"].get(e.get("cqa_id"))
            if not c:
                raise StudyError(f"CQA {e.get('cqa_id')} 없음", status=422)
            changes = {k: v for k, v in (e.get("changes") or {}).items() if k in self.CQA_FIELDS}
            if "evidence_status" in (e.get("changes") or {}):
                self._guard_evidence_change(st, e)
            if "analysis_role" in changes and changes["analysis_role"] != c["analysis_role"]:
                change = {"op": "UPDATE", "field": "analysis_role", "from_role": c["analysis_role"],
                          "to_role": changes["analysis_role"], "evidence_ref": e.get("evidence_ref")}
                ev = self._eval(st, "cqa_change", "WAITING_CQA_APPROVAL",
                                [(c["cqa_id"], {"change": change, "cqa": cqa_mod.cqa_context(c)})],
                                rule_ids=["AA001", "AA002"])
                if ev.blocking or (ev.requests and not e.get("evidence_ref")):
                    raise StudyError("이 역할 변경에는 근거가 필요합니다.",
                                     verdicts=[v.as_dict() for v in ev.blocking + ev.requests])
                for w in ev.warnings:
                    self._record_override(st, actor, w.rule_id, w.rule_version, w.effect, c["cqa_id"],
                                          f"역할 {c['analysis_role']}→{changes['analysis_role']}",
                                          e.get("reason") or "", affected=[c["cqa_id"]])
            if "test_method_id" in changes:
                m = cqa_mod.method_index(self.rb).get(changes["test_method_id"])
                changes["test_method_version"] = m["version"] if m else None
                c["has_registered_method"] = bool(m)
            for k in ("lower", "upper", "target", "target_tolerance", "practical_effect_threshold"):
                if k in changes and changes[k] not in (None, ""):
                    changes[k] = float(changes[k])
                elif k in changes:
                    changes[k] = None
            c.update(changes)
            c["version"] += 1
            if changes.get("assumption"):
                note = f"{c['name']} 기준은 연구자 입력 가정"
                if note not in st["assumptions"]:
                    st["assumptions"].append(note)
            applied.append(c["cqa_id"])
            self._decide(st, "CQA_EDIT", actor, e.get("reason", ""), cqa_id=c["cqa_id"], changes=changes)
        self._check_cqas(st)
        self._say(st, "researcher", f"CQA 수정: {', '.join(applied)}")
        return {"applied": applied}

    def _act_cqa_approve(self, st, p, actor):
        self._require(st, "WAITING_CQA_APPROVAL")
        ev = self._check_cqas(st)
        if ev.blocking or ev.requests:
            raise StudyError("CQA 계약을 승인할 수 없습니다 — 규칙이 막고 있습니다.",
                             verdicts=[v.as_dict() for v in ev.blocking + ev.requests])
        for c in st["cqas"].values():
            c["approval_status"] = "APPROVED"
        st["cqa_contract_hash"] = _h({k: {f: c[f] for f in ("analysis_role", "acceptance_operator", "lower",
                                                              "upper", "target", "target_tolerance")}
                                      for k, c in st["cqas"].items()})
        self._decide(st, "CQA_APPROVED", actor, p.get("reason", ""))
        self._say(st, "researcher", "CQA 계약 승인")
        self._move(st, "FMEA_DRAFTING", "APPROVED")
        return {}

    def _act_cqa_reject(self, st, p, actor):
        self._require(st, "WAITING_CQA_APPROVAL")
        st["cqas"] = {}
        self._decide(st, "CQA_REJECTED", actor, p.get("reason", ""))
        self._move(st, "CQA_DRAFTING", "REJECTED")
        return {}

    # ======================================================================
    # D3 FMEA
    # ======================================================================
    def _fmea_drafting(self, st):
        if not st["fmea"]["rows"]:
            rows = fmea_mod.draft_fmea(self.rb, st["handoff"], st["cqas"])
            hyp = agents.fmea_hypotheses(st["handoff"], st["cqas"], rows, fmea_mod.FACTOR_VOCAB)
            st["fmea"] = {"version": st["fmea"]["version"] + 1, "rows": rows + hyp["rows"],
                          "hypotheses_generated_by": hyp["generated_by"], "status": "DRAFT"}
            n_h = len(hyp["rows"])
            self._say(st, "system", f"FMEA 초안: seed {len(rows)}행 + LLM 가설 {n_h}행"
                                    f" ({'LLM' if hyp['generated_by'] == 'llm' else '규칙 기반 대체 — LLM 미사용'}). "
                                    "O는 관찰자료가 없으면 UNKNOWN이고, 그 행은 RPN을 계산하지 않습니다.")
        self._check_fmea(st)
        self._move(st, "WAITING_FMEA_APPROVAL", "FMEA_DRAFTED")

    def _fixed_status(self, st, factor: Optional[str]) -> Optional[str]:
        p = next((x for x in st["handoff"]["fixed_parameters"] if x["name"] == factor), None)
        return p["status"] if p else None

    def _check_fmea(self, st) -> Evaluation:
        subjects = []
        for r in st["fmea"]["rows"]:
            if r.get("deleted"):
                continue
            r["rpn"] = fmea_mod.rpn(r)
            fs = self._fixed_status(st, (r.get("candidate_factors") or [None])[0])
            subjects.append((r["row_id"], {"item": fmea_mod.row_context(r, fs)}))
        return self._eval(st, "fmea", "WAITING_FMEA_APPROVAL", subjects, rule_ids=["FE012"])

    FMEA_FIELDS = {"disposition", "occurrence", "occurrence_evidence", "detectability", "alternative_control",
                   "approval_ref", "severity", "cause", "failure_mode", "local_effect", "cqa_effect",
                   "candidate_factors"}

    def _act_fmea_edit(self, st, p, actor):
        self._require(st, "WAITING_FMEA_APPROVAL")
        applied = []
        for e in p.get("edits") or [p]:
            op = e.get("op", "UPDATE")
            if op == "ADD":
                row = {"row_id": f"R{len(st['fmea']['rows']) + 1:02d}", "seed_id": None, "risk_category": "RESEARCHER",
                       "cause": e["changes"].get("cause", ""), "failure_mode": e["changes"].get("failure_mode", ""),
                       "local_effect": e["changes"].get("local_effect", ""),
                       "cqa_effect": e["changes"].get("cqa_effect", []), "candidate_factors": [],
                       "kind": None, "severity": None, "occurrence": None, "occurrence_evidence": None,
                       "detectability": None, "detection_method_ids": [], "disposition": "REQUEST_DATA",
                       "evidence_status": "EXPERT_ASSUMPTION", "alternative_control": None, "approval_ref": None,
                       "deleted": False, "origin": "RESEARCHER", "detect_note": "", "rpn": None}
                st["fmea"]["rows"].append(row)
                applied.append(row["row_id"])
                continue
            row = next((r for r in st["fmea"]["rows"] if r["row_id"] == e.get("row_id")), None)
            if not row:
                raise StudyError(f"FMEA 행 {e.get('row_id')} 없음", status=422)
            changes = {k: v for k, v in (e.get("changes") or {}).items() if k in self.FMEA_FIELDS}
            if "evidence_status" in (e.get("changes") or {}):
                self._guard_evidence_change(st, e)
            if op == "DELETE":
                change = {"op": "DELETE", "alternative_control": e.get("alternative_control")}
                ctx_row = fmea_mod.row_context({**row, "approval_ref": e.get("approval_ref") or row.get("approval_ref")})
                ev = self._eval(st, "fmea_change", "WAITING_FMEA_APPROVAL",
                                [(row["row_id"], {"change": change, "row": ctx_row})], rule_ids=["AA004"])
                if ev.blocking:
                    raise StudyError("고심각도 행은 대체 관리수단과 승인 근거 없이 삭제할 수 없습니다.",
                                     verdicts=[v.as_dict() for v in ev.blocking])
                row["deleted"] = True
                row["delete_reason"] = e.get("reason")
            else:
                if "occurrence" in changes and changes["occurrence"] not in (None, ""):
                    change = {"op": "UPDATE", "field": "occurrence", "to_value": str(changes["occurrence"]),
                              "evidence_ref": e.get("evidence_ref")}
                    ev = self._eval(st, "fmea_change", "WAITING_FMEA_APPROVAL",
                                    [(row["row_id"], {"change": change})], rule_ids=["AA006"])
                    changes["occurrence"] = int(changes["occurrence"])
                    if ev.warnings:
                        changes["occurrence_evidence"] = changes.get("occurrence_evidence") or "EXPERT_ASSUMPTION"
                        row["occurrence_flag"] = "EXPERT_ASSUMPTION"
                if row.get("evidence_status") == "LLM_HYPOTHESIS" and changes.get("disposition") == "DOE_CANDIDATE":
                    row["hypothesis_status"] = "ADOPTED"   # 채택해도 LLM_HYPOTHESIS 태그는 유지 (D3 표)
                row.update(changes)
            self._decide(st, f"FMEA_{op}", actor, e.get("reason", ""), row_id=row["row_id"], changes=changes)
            applied.append(row["row_id"])
        st["fmea"]["version"] += 1
        self._check_fmea(st)
        self._say(st, "researcher", f"FMEA 수정: {', '.join(applied)}")
        return {"applied": applied}

    def _guard_evidence_change(self, st, e):
        ev = self._eval(st, "evidence_change", "WAITING_FMEA_APPROVAL",
                        [("change", {"change": {"field": "evidence_status", "data_ref": e.get("data_ref")}})],
                        rule_ids=["AA005"])
        if ev.blocking:
            raise StudyError("근거 등급은 데이터 연결 없이 바꿀 수 없습니다 (AA005).",
                             verdicts=[v.as_dict() for v in ev.blocking])
        raise StudyError("근거 등급은 연구자 조작으로 바꾸지 않습니다 — 데이터 제출로만 갱신됩니다.")

    def _act_fmea_approve(self, st, p, actor):
        self._require(st, "WAITING_FMEA_APPROVAL")
        ev = self._check_fmea(st)
        if ev.blocking:
            raise StudyError("FMEA를 승인할 수 없습니다.", verdicts=[v.as_dict() for v in ev.blocking])
        st["fmea"]["status"] = "APPROVED"
        self._decide(st, "FMEA_APPROVED", actor, p.get("reason", ""), fmea_version=st["fmea"]["version"])
        self._say(st, "researcher", f"FMEA v{st['fmea']['version']} 승인")
        self._move(st, "FACTOR_READINESS", "APPROVED")
        return {}

    def _act_fmea_reject(self, st, p, actor):
        self._require(st, "WAITING_FMEA_APPROVAL")
        st["fmea"]["rows"] = []
        self._decide(st, "FMEA_REJECTED", actor, p.get("reason", ""))
        self._move(st, "FMEA_DRAFTING", "REJECTED")
        return {}

    # ======================================================================
    # D4 Factor Readiness
    # ======================================================================
    def _factor_candidates(self, st) -> List[Dict[str, Any]]:
        seen: Dict[str, Dict[str, Any]] = {}
        for r in st["fmea"]["rows"]:
            if r.get("deleted") or r.get("disposition") != "DOE_CANDIDATE":
                continue
            for f in r.get("candidate_factors") or []:
                if self._fixed_status(st, f) == "UNKNOWN":
                    continue
                seen.setdefault(f, {"factor": f, "fmea_refs": []})["fmea_refs"].append(r["row_id"])
        return sorted(seen.values(), key=lambda c: FACTOR_ORDER.index(c["factor"]) if c["factor"] in FACTOR_ORDER else 99)

    def _factor_readiness(self, st):
        inputs = st.setdefault("factor_inputs", {})
        cands = self._factor_candidates(st)
        prev = st["factors"]
        st["factors"] = fac_mod.propose(self.rb, st["handoff"], cands, inputs)
        for fid, f in st["factors"].items():
            if fid in prev:
                f["version"] = prev[fid]["version"] + (1 if _h(prev[fid]["low"]) != _h(f["low"]) or
                                                       _h(prev[fid]["high"]) != _h(f["high"]) else 0)
        ev = self._check_factors(st, "FACTOR_READINESS")
        if not st["factors"]:
            self._say(st, "system", "DoE 요인 후보가 없습니다 — FMEA 처리 방향을 다시 보거나 전략을 검토해야 합니다.")
            self._move(st, "STRATEGY_REVIEW", "NO_FACTOR_CANDIDATE")
            return
        for f in st["factors"].values():
            f["status"] = "REQUEST_DATA" if any(v.subject == f["factor_id"] for v in ev.requests) else \
                ("READY" if f["disposition"] == "DOE_CANDIDATE" else f["disposition"])
        if ev.next_state:
            self._say(st, "system", f"요인 준비: {ev.decisive.message}", kind="request")
            self._move(st, ev.next_state, ev.reason_code or "")
            return
        if ev.blocking or ev.requests:
            return
        self._say(st, "system", f"요인 {len(st['factors'])}개의 수준값을 근거와 함께 제안했습니다. 승인해 주세요.")
        self._move(st, "WAITING_FACTOR_APPROVAL", "READY")

    def _check_factors(self, st, stage: str) -> Evaluation:
        facs = [fac_mod.factor_context(f) for f in st["factors"].values()]
        method = {"repeatability_sd": None, "variance_component_type": "METHOD_REPEATABILITY"}
        comp = {"balance_component": next((f["balance_component"] for f in st["factors"].values()
                                           if f.get("balance_component")), None)}
        h_ctx = self._handoff_ctx(st["handoff"])
        subjects = [("요인 구성", {"composition_group": comp, "factors": facs})]
        for f, fc in zip(st["factors"].values(), facs):
            mr = f.get("master_range") or {"typical_min_pct": None, "typical_max_pct": None}
            item = fmea_mod.row_context(
                {"severity": max([r.get("severity") or 0 for r in st["fmea"]["rows"] if r["row_id"] in f["fmea_refs"]] or [0]) or None,
                 "candidate_factors": [f["source_factor"]], "kind": f["kind"],
                 "detection_method_ids": ["x"], "disposition": f["disposition"]},
                self._fixed_status(st, f["source_factor"]), fc["low"]["value"], fc["high"]["value"])
            subjects.append((f["factor_id"], {"factor": fc, "factors": facs, "master": mr, "method": method,
                                              "item": item, "handoff": h_ctx, "iid": {"max_potency_mg": None}}))

        # 고정·미관리 공정변수 (FE009) — 요인은 아니지만 scope에 기록된다
        for p in st["handoff"]["fixed_parameters"]:
            if p["status"] == "UNKNOWN":
                subjects.append((p["name"], {"item": {"kind": "CPP", "fixed_value_status": "UNKNOWN",
                                                      "controllable": True, "measurable": False,
                                                      "range_definable": False, "prohibited": False,
                                                      "function_locked": False, "severity": None,
                                                      "occurrence": None, "occurrence_evidence": None,
                                                      "disposition": "FIXED", "unit": None,
                                                      "alternative_control": None, "approval_ref": None,
                                                      "low": None, "high": None, "evidence_status": None},
                                             "handoff": h_ctx}))
        for f in st["factors"].values():
            f["width_check"] = "NOT_CHECKED"   # 시험법 반복정밀도 미입력 → FR008 RECORD_NOT_CHECKED
        return self._eval(st, "factors", stage, subjects,
                          rulebooks=["factor_eligibility_rules", "factor_range_constraint_rules",
                                     "approval_authority_rules"])

    def _act_factor_data(self, st, p, actor):
        if st["status"] not in ("WAITING_FACTOR_DATA", "WAITING_FACTOR_APPROVAL", "RANGE_FINDING_RUNS",
                                "STRATEGY_REVIEW"):
            raise StudyError("지금은 요인 자료를 받는 단계가 아닙니다.")
        inputs = st.setdefault("factor_inputs", {})
        for src, vals in (p.get("factors") or {}).items():
            cur = inputs.setdefault(src, {})
            for k in ("low", "high", "source_ref", "evidence_status", "manufacturability_evidence",
                      "disposition", "expected_range_contrast"):
                if k in vals:
                    cur[k] = vals[k]
            if cur.get("evidence_status") not in (None, "LITERATURE_DIRECT", "LITERATURE_DIGITIZED",
                                                  "MEASURED_CONFIRMED", "EXPERT_ASSUMPTION"):
                cur["evidence_status"] = "EXPERT_ASSUMPTION"
        self._decide(st, "FACTOR_DATA", actor, p.get("reason", ""), factors=list((p.get("factors") or {}).keys()))
        self._say(st, "researcher", "요인 범위·근거 제출")
        back = {"WAITING_FACTOR_DATA": "DATA_CONFIRMED", "RANGE_FINDING_RUNS": "RESULTS_CONFIRMED",
                "WAITING_FACTOR_APPROVAL": "REJECTED", "STRATEGY_REVIEW": "REVISE_FACTORS"}[st["status"]]
        self._move(st, "FACTOR_READINESS", back)
        return {}

    def _act_factor_approve(self, st, p, actor):
        self._require(st, "WAITING_FACTOR_APPROVAL")
        ev = self._check_factors(st, "WAITING_FACTOR_APPROVAL")
        if ev.blocking:
            raise StudyError("요인을 승인할 수 없습니다.", verdicts=[v.as_dict() for v in ev.blocking])
        st["design_inputs"] = {"prior_evidence_approved": bool(p.get("prior_evidence_approved")),
                               "extreme_corner_risk": bool(p.get("extreme_corner_risk", True)),
                               "design_type": p.get("design_type"), "seed": int(p.get("seed") or 20260923)}
        for f in st["factors"].values():
            f["approval_status"] = "APPROVED"
        self._decide(st, "FACTORS_APPROVED", actor, p.get("reason", ""), **st["design_inputs"])
        self._say(st, "researcher", "요인·수준값 승인" + (" · 사전근거 승인(RSM 직행 후보)" if p.get("prior_evidence_approved") else ""))
        self._move(st, "DESIGN_SELECTION", "APPROVED")
        return {}

    # ======================================================================
    # D5 설계 선택 · 계획
    # ======================================================================
    def _design_factors(self, st) -> List[doe.Factor]:
        out = []
        for f in st["factors"].values():
            if f.get("disposition") != "DOE_CANDIDATE" or f["low"]["value"] is None:
                continue
            out.append(doe.Factor(f["factor_id"], f["symbol"], float(f["low"]["value"]), float(f["high"]["value"])))
        for i, f in enumerate(out):
            f.symbol = fac_mod.SYMBOLS[i]
            st["factors"][f.factor_id]["symbol"] = f.symbol
        return out

    def _design_selection(self, st):
        fs = self._design_factors(st)
        di = st.get("design_inputs", {})
        direct = len(fs) <= self.rb.const("rsm_max_factors") and di.get("prior_evidence_approved", False)
        plan_ctx = {"stage": "RSM" if direct else "SCREENING",
                    "n_factors": len(fs), "n_continuous": len(fs), "n_categorical": 0,
                    "has_mixture": False, "has_forbidden_combinations": False, "has_hard_to_change": False,
                    "prior_evidence_approved": di.get("prior_evidence_approved", False),
                    "extreme_corner_risk": di.get("extreme_corner_risk", True),
                    "axial_must_stay_in_range": True, "axial_points_safe": False,
                    "interactions_plausible": True, "design_type": di.get("design_type"),
                    "screening_core_reusable": False}
        ev = self._eval(st, "design_selection", "DESIGN_SELECTION", [("설계 선택", {"plan": plan_ctx})],
                        rulebooks=["doe_design_selection_rules"])
        recs = sorted([v for v in ev.verdicts if v.status == "FIRES" and v.result_code in doe.RECOMMENDATION],
                      key=lambda v: v.priority)
        st["design_selection"] = {"recommended": doe.RECOMMENDATION[recs[0].result_code] if recs else None,
                                  "recommended_by": recs[0].rule_id if recs else None, "n_factors": len(fs)}
        if ev.next_state == "RSM_PLANNING":
            self._say(st, "system", f"{ev.decisive.message} ({ev.decisive.rule_id})")
            self._move(st, "RSM_PLANNING", ev.reason_code)
            return
        self._move(st, "SCREENING_PLANNING", "SCREENING_NEEDED")

    def _planning(self, st, stage: str):
        fs = self._design_factors(st)
        di = st.get("design_inputs", {})
        rec = (st.get("design_selection") or {}).get("recommended")
        if stage == "RSM":
            rsm_rec = rec if rec in ("BOX_BEHNKEN", "FACE_CENTERED_CCD", "CCD") else "FACE_CENTERED_CCD"
            if rsm_rec == "BOX_BEHNKEN" and len(fs) != 3:
                rsm_rec = "FACE_CENTERED_CCD"
            rec_type = rsm_rec
        else:
            rec_type = "FRACTIONAL_FACTORIAL"
        chosen = di.get("design_type") or rec_type
        st["design_selection"]["recommended"] = rec_type
        try:
            design = doe.generate(chosen, fs, seed=di.get("seed", 20260923),
                                  centers=int(self.rb.const("screening_center_points")))
        except ValueError as exc:
            design = None
            self._say(st, "system", f"설계를 생성할 수 없습니다: {exc}")
        bal = fac_mod.balance_fn(st["handoff"], list(st["factors"].values()))
        if design is None:
            plan_ctx = {"design_type": chosen, "n_factors": len(fs), "n_categorical": 0, "has_mixture": False,
                        "has_hard_to_change": False}
            ev = self._eval(st, "planning", f"{stage}_PLANNING", [("plan", {"plan": plan_ctx})], rule_ids=["DV013"])
            if not self._route(st, ev):
                self._move(st, "DESIGN_REPLAN", "DESIGN_BACKEND_UNSUPPORTED")
            return
        ctx = doe.validation_context(design, fs, rel_tol=float(self.rb.const("matrix_rank_rel_tolerance")),
                                     balance_fn=bal, prior_evidence_approved=di.get("prior_evidence_approved", False),
                                     extreme_corner_risk=di.get("extreme_corner_risk", True))
        pid = f"PLAN-{stage}-{len(st['plans']) + 1}"
        alias = doe.alias_structure(design["matrix"], design["symbols"])
        balance_min = min((p["balance_component_value"] for p in ctx["design_points"]
                           if p["balance_component_value"] is not None), default=None)
        plan = {
            "doe_plan_id": pid, "version": 1, "study_id": st["study_id"], "handoff_id": st["handoff"]["handoff_id"],
            "stage": stage, "source": "SYSTEM_GENERATED", "design_type": chosen,
            "factor_ids": [f.factor_id for f in fs],
            "response_ids": [c for c, v in st["cqas"].items() if v["analysis_role"] == "DOE_RESPONSE"],
            "intended_model_terms": design["terms"], "standard_matrix_ref": doe.matrix_hash(design["matrix"]),
            "actual_matrix_ref": doe.matrix_hash(design["matrix"]), "alias_structure": alias,
            "block_definition": None, "random_seed": design["seed"], "generator": doe.GENERATOR,
            "diagnostics": {"matrix_rank": ctx["_matrix_rank"], "n_terms": ctx["n_terms"], "n_runs": ctx["n_runs"],
                            "residual_df": ctx["n_runs"] - ctx["n_terms"], "n_center_points": ctx["n_center_points"],
                            "balance_min_pct": balance_min, **design["info"]},
            "override_decision_ids": [], "status": "DRAFT", "approved_by": None, "runs": design["runs"],
            "symbols": {f.symbol: f.factor_id for f in fs}, "recommended": rec_type,
        }
        st["plans"].append(plan)
        st["active_plan"] = pid
        ev = self._eval(st, "planning", f"{stage}_PLANNING", [(pid, {"plan": ctx})],
                        rulebooks=["doe_design_validation_rules", "doe_randomization_blocking_rules",
                                   "factor_range_constraint_rules", "provenance_versioning_rules",
                                   "approval_authority_rules"])
        if ev.next_state:
            plan["status"] = "REJECTED"
            self._say(st, "system", f"설계 {chosen}가 검증을 통과하지 못했습니다: {ev.decisive.message}")
            self._move(st, ev.next_state, ev.reason_code or "")
            return
        if ev.blocking:
            plan["status"] = "REJECTED"
            self._move(st, "DESIGN_REPLAN", "DESIGN_BLOCKED")
            return
        plan["status"] = "DESIGN_VALID"
        self._say(st, "system", f"{chosen} {len(design['runs'])} run 설계를 생성·검증했습니다 "
                                f"(rank {ctx['_matrix_rank']}/{ctx['n_terms']}, 잔차 자유도 {ctx['n_runs'] - ctx['n_terms']}).")
        self._move(st, f"WAITING_{stage}_APPROVAL", "DESIGN_VALID")

    def _plan(self, st) -> Optional[Dict[str, Any]]:
        return next((p for p in st["plans"] if p["doe_plan_id"] == st.get("active_plan")), None)

    def _act_plan_approve(self, st, p, actor):
        if st["status"] not in ("WAITING_RSM_APPROVAL", "WAITING_SCREENING_APPROVAL"):
            raise StudyError("승인할 설계가 없습니다.")
        plan = self._plan(st)
        if plan["design_type"] != plan.get("recommended"):
            ev = self._eval(st, "plan_approval", st["status"],
                            [(plan["doe_plan_id"], {"plan": {"design_type": plan["design_type"]},
                                                    "selector": {"recommended_design_type": plan["recommended"]}})],
                            rule_ids=["AA007"])
            if ev.warnings and not p.get("reason"):
                raise StudyError("권고와 다른 설계입니다 — 사유를 적어 주세요 (AA007).",
                                 verdicts=[v.as_dict() for v in ev.warnings])
            for w in ev.warnings:
                d = self._record_override(st, actor, w.rule_id, w.rule_version, w.effect, plan["doe_plan_id"],
                                          f"{plan['design_type']} 채택", p.get("reason", ""),
                                          affected=[plan["doe_plan_id"]])
                plan["override_decision_ids"].append(d["decision_id"])
        plan["status"] = "APPROVED"
        plan["approved_by"] = actor
        plan["run_sheets"] = self._compile_run_sheets(st, plan)
        self._decide(st, "PLAN_APPROVED", actor, p.get("reason", ""), doe_plan_id=plan["doe_plan_id"])
        self._say(st, "researcher", f"{plan['design_type']} 계획 승인 — 결과 제출을 기다립니다.")
        self._move(st, "RSM_EXECUTION" if plan["stage"] == "RSM" else "SCREENING_EXECUTION", "APPROVED")
        return {}

    def _act_plan_reject(self, st, p, actor):
        if st["status"] not in ("WAITING_RSM_APPROVAL", "WAITING_SCREENING_APPROVAL"):
            raise StudyError("반려할 설계가 없습니다.")
        plan = self._plan(st)
        plan["status"] = "REJECTED"
        if p.get("design_type"):
            st.setdefault("design_inputs", {})["design_type"] = p["design_type"]
        self._decide(st, "PLAN_REJECTED", actor, p.get("reason", ""), doe_plan_id=plan["doe_plan_id"])
        self._move(st, "RSM_PLANNING" if plan["stage"] == "RSM" else "SCREENING_PLANNING", "REJECTED")
        return {}

    def _act_replan(self, st, p, actor):
        if st["status"] not in ("DESIGN_REPLAN", "STRATEGY_REVIEW"):
            raise StudyError("재계획 단계가 아닙니다.")
        target = p.get("target")
        if st["status"] == "STRATEGY_REVIEW" and target == "CANDIDATE_REVISION":
            self._decide(st, "CANDIDATE_REVISION", actor, p.get("reason", ""))
            self._move(st, "CLOSED_SUPERSEDED", "CANDIDATE_PREMISE_FAILURE")
            return {"child_candidate_requested": True}
        if target == "DESIGN_SELECTION" and st["status"] == "DESIGN_REPLAN":
            di = st.setdefault("design_inputs", {})
            di["design_type"] = p.get("design_type")
            if "prior_evidence_approved" in p:
                di["prior_evidence_approved"] = bool(p["prior_evidence_approved"])
            self._move(st, "DESIGN_SELECTION", "DESIGN_ISSUE")
        else:
            self._move(st, "FACTOR_READINESS", "RANGE_ISSUE")
        self._decide(st, "REPLAN", actor, p.get("reason", ""), target=target)
        return {}

    def _compile_run_sheets(self, st, plan) -> Dict[str, Any]:
        """run별 칭량표 — RS 규칙이 판정. 근거 없는 설정값은 만들지 않는다(RS005)."""
        h = st["handoff"]
        unit = h.get("unit_weight_mg")
        n_units = _parse_units(h.get("batch_scale"))
        bal = fac_mod.balance_fn(h, list(st["factors"].values()))
        subjects, sheets = [], {}
        for r in plan["runs"]:
            b = bal(r["actual"]) if bal else None
            batch_g = unit * n_units / 1000 if unit and n_units else None
            run_ctx = {"batch_id": None, "batch_mass_g": batch_g, "ingredient_mg_total": unit,
                       "target_unit_mg": unit, "balance_component_mg": (b * unit / 100) if (b is not None and unit) else None,
                       "settings_complete": all(v is not None for v in r["actual"].values()),
                       "settings_on_resolution": True, "fixed_conditions_match": True}
            sheets[r["doe_run_id"]] = {"settings": r["actual"], "batch_mass_g": batch_g,
                                       "balance_pct": b, "unit_weight_mg": unit}
            subjects.append((r["doe_run_id"], {"run": run_ctx, "equipment": {"working_capacity_min_g": None,
                                                                           "working_capacity_max_g": None}}))
        ev = self._eval(st, "run_sheets", "RUN_SHEET_COMPILE", subjects, rulebooks=["run_sheet_compilation_rules"])
        held = sorted({v.subject for v in ev.blocking + ev.requests})
        for rid, s in sheets.items():
            s["status"] = "HELD" if rid in held else "COMPILED"
        return {"sheets": sheets, "held": held,
                "note": "설비 작업용량이 UNKNOWN이면 RS003이 run sheet 발행을 보류합니다 (결과 입력은 가능)."}

    # ======================================================================
    # D6 결과 제출 · 확인 · 품질 게이트
    # ======================================================================
    def _act_results_submit(self, st, p, actor):
        if st["status"] not in ("RSM_EXECUTION", "SCREENING_EXECUTION"):
            raise StudyError("지금은 실험 결과를 받는 단계가 아닙니다.")
        plan = self._plan(st)
        text = p.get("csv") or ""
        rows = list(csv.DictReader(io.StringIO(text.strip())))
        if not rows:
            raise StudyError("CSV에 행이 없습니다.", status=422)
        cmap: Dict[str, str] = p.get("column_map") or guess_columns(list(rows[0].keys()), st)
        f_cols = {c: t for c, t in cmap.items() if t in plan["factor_ids"]}
        r_cols = {c: t for c, t in cmap.items() if t in st["cqas"]}
        if len(f_cols) != len(plan["factor_ids"]):
            raise StudyError("모든 요인 열을 지정해야 run과 대조할 수 있습니다.", status=422)
        ranges = {f: (st["factors"][f]["high"]["value"] - st["factors"][f]["low"]["value"]) for f in plan["factor_ids"]}
        done = {r["doe_run_id"] for r in self._fit_results(st)}
        free = [r for r in plan["runs"] if r["doe_run_id"] not in done]
        now = ho.now()
        parsed = []
        batch_col = p.get("batch_column") or ("batch_id" if "batch_id" in rows[0] else None)
        for n, row in enumerate(rows):
            settings = {t: _float(row.get(c)) for c, t in f_cols.items()}
            match = None
            for r in free:
                if all(settings[f] is not None and abs(settings[f] - r["actual"][f]) <= 0.01 * ranges[f]
                       for f in plan["factor_ids"]):
                    match = r
                    break
            if match:
                free.remove(match)
            run_id = match["doe_run_id"] if match else f"UNMATCHED-{n + 1}"
            for col, cid in r_cols.items():
                val = _float(row.get(col))
                if val is None:
                    continue
                c = st["cqas"][cid]
                tid = f"TR-{run_id}-{cid}"
                ev_status = row.get("evidence_status") or p.get("evidence_status") or "MEASURED_UNCONFIRMED"
                st["results"][tid] = {
                    "test_result_id": tid, "study_id": st["study_id"], "doe_run_id": run_id,
                    "batch_id": row.get(batch_col) if batch_col else None,
                    "parent_blend_id": row.get("parent_blend_id") or None,
                    "test_method_id": c.get("test_method_id"), "test_method_version": c.get("test_method_version"),
                    "response_id": cid, "individual_values": [], "summary_statistic": {"value": val},
                    "unit": c.get("unit"), "raw_data_refs": [p.get("source") or row.get("source") or "upload"],
                    "evidence_status": ev_status,
                    "replicate_independence": row.get("replicate_independence") or "UNKNOWN",
                    "deviation": row.get("deviation") or None, "human_verification_status": "PENDING",
                    "settings": settings, "submitted_at": now, "plan_id": plan["doe_plan_id"],
                    "matched": bool(match), "source_row": n + 1, "purpose": "FIT",
                }
                parsed.append(tid)
        st["result_batch"] = {"ids": parsed, "column_map": cmap, "unmatched_runs": [r["doe_run_id"] for r in free]}
        self._say(st, "researcher", f"결과 {len(rows)}행 업로드 — {len(parsed)}개 값을 파싱했습니다. 확인해 주세요.")
        self._decide(st, "RESULTS_SUBMITTED", actor, p.get("reason", ""), n_values=len(parsed))
        return {"parsed": len(parsed), "column_map": cmap}

    def _act_results_confirm(self, st, p, actor):
        batch = st.get("result_batch") or {}
        ids = batch.get("ids") or []
        if not ids:
            raise StudyError("확인할 결과가 없습니다.")
        if not p.get("accept", True):
            for tid in ids:
                st["results"][tid]["human_verification_status"] = "REJECTED"
            st["result_batch"] = None
            self._say(st, "researcher", "파싱 결과 반려 — 다시 제출해 주세요.")
            return {"rejected": len(ids)}
        for tid in ids:
            r = st["results"][tid]
            r["human_verification_status"] = "CONFIRMED"
            if r["evidence_status"] == "MEASURED_UNCONFIRMED":
                r["evidence_status"] = "MEASURED_CONFIRMED"   # 자체 실측에만 적용되는 유일한 상향 경로 (#2)
        ev = self._quality_gate(st, ids)
        st["result_batch"] = None
        self._decide(st, "RESULTS_CONFIRMED", actor, p.get("reason", ""), n_values=len(ids))
        failed = {v.subject for v in ev.blocking + ev.requests}
        self._say(st, "system", f"결과 품질 게이트: {len(ids) - len(failed)}개 통과, {len(failed)}개 보류.")
        if ev.next_state == "DIAGNOSING":
            st["diagnosis_trigger"] = {"reason_code": ev.reason_code, "message": ev.decisive.message}
            self._move(st, "DIAGNOSING", ev.reason_code)
            return {}
        if self._fit_ready(st) and st["status"] in ("RSM_EXECUTION", "SCREENING_EXECUTION"):
            self._move(st, "MODEL_VALIDATION" if st["status"] == "RSM_EXECUTION" else "SCREENING_ANALYSIS",
                       "ALL_RUNS_CONFIRMED")
        return {"quality_failed": sorted(failed)}

    def _quality_gate(self, st, ids: List[str]) -> Evaluation:
        subjects = []
        for tid in ids:
            r = st["results"][tid]
            subjects.append((tid, {"result": {
                "id": tid, "batch_id": r["batch_id"], "parent_blend_id": r.get("parent_blend_id"),
                "test_method_version": r["test_method_version"], "response_id": r["response_id"],
                "unit": r["unit"], "target_unit": st["cqas"][r["response_id"]].get("unit"),
                "n_individual_values": len(r["individual_values"]), "evidence_status": r["evidence_status"],
                "replicate_independence": r["replicate_independence"], "deviation": r["deviation"],
                "deviation_resolved": False, "human_verification_status": r["human_verification_status"],
                "settings_within_tolerance": r.get("matched", True), "counted_as_independent_run": True,
                "submitted_at": r["submitted_at"]}}))
        ev = self._eval(st, "result_quality", "RESULT_QUALITY_GATE", subjects, rulebooks=["result_data_quality_rules"])
        bad = {v.subject: v for v in ev.blocking + ev.requests}
        for tid in ids:
            q = st["results"][tid]["quality"] = {"status": "FAIL" if tid in bad else "PASS",
                                                 "reason_code": bad[tid].result_code if tid in bad else None,
                                                 "message": bad[tid].message if tid in bad else None,
                                                 "warnings": [v.result_code for v in ev.warnings if v.subject == tid]}
            if tid in bad:
                st["results"][tid]["run_state"] = "WAITING_BATCH_RESULTS"
            else:
                st["results"][tid]["run_state"] = "EXIT_ANALYSIS"
        return ev

    def _lineage(self, st) -> set:
        """활성 plan과 그 증강 원본(plan id 접두) — 적합 데이터는 이 계보 안의 결과만 쓴다."""
        active = st.get("active_plan") or ""
        return {p["doe_plan_id"] for p in st["plans"] if active.startswith(p["doe_plan_id"])}

    def _fit_results(self, st) -> List[Dict[str, Any]]:
        lineage = self._lineage(st)
        return [r for r in st["results"].values() if r.get("purpose") == "FIT" and r.get("plan_id") in lineage and
                r["human_verification_status"] == "CONFIRMED" and (r.get("quality") or {}).get("status") == "PASS"
                and r.get("matched")]

    def _fit_ready(self, st) -> bool:
        plan = self._plan(st)
        good = self._fit_results(st)
        need = {(run["doe_run_id"], cid) for run in plan["runs"] for cid in plan["response_ids"]}
        have = {(r["doe_run_id"], r["response_id"]) for r in good}
        return need <= have

    # ======================================================================
    # D8 Model validation
    # ======================================================================
    def _dataset(self, st, cid: str) -> Tuple[Dict[str, np.ndarray], np.ndarray, List[str], List[Dict[str, Any]]]:
        rows = [r for r in self._fit_results(st) if r["response_id"] == cid]
        rows.sort(key=lambda r: r["source_row"])
        syms = {f["factor_id"]: f["symbol"] for f in st["factors"].values() if f.get("disposition") == "DOE_CANDIDATE"}
        facs = {f.factor_id: f for f in self._design_factors(st)}
        coded = {syms[fid]: np.array([facs[fid].to_coded(r["settings"][fid]) for r in rows]) for fid in facs}
        y = np.array([r["summary_statistic"]["value"] for r in rows])
        return coded, y, [r.get("batch_id") for r in rows], rows

    def _scope_hash(self, st) -> str:
        return _h({"fp": st["handoff"]["formulation_fingerprint"], "equipment": st["handoff"].get("equipment_id"),
                   "methods": sorted((c["cqa_id"], c.get("test_method_version")) for c in st["cqas"].values())})

    def _model_validation(self, st):
        plan = self._plan(st)
        alpha = float(self.rb.const("alpha"))
        subjects = []
        for cid in plan["response_ids"]:
            versions = st["models"].setdefault(cid, [])
            current = versions[-1] if versions else None
            terms = current["intended_terms"] if current else plan["intended_model_terms"]
            coded, y, batches, rows = self._dataset(st, cid)
            fit = Fit(terms, coded, y, float(self.rb.const("matrix_rank_rel_tolerance")))
            summary = fit_summary(fit, cid)
            if current is None or current.get("_needs_fit"):
                model = {
                    "response_model_id": f"RM-{cid}", "version": len(versions) + (0 if current else 1),
                    "cqa_id": cid, "formula": fit.formula(cid), "intended_terms": list(terms),
                    "reduced_from": current.get("reduced_from") if current else None,
                    "coefficients": {c["term"]: c["estimate"] for c in summary["coefficients"]},
                    "covariance_ref": _h(fit.cov.round(12).tolist()), "fit_stats": summary,
                    "pure_error": summary["pure_error"], "lack_of_fit": summary["lack_of_fit"],
                    "influence_flags": [], "domain_bounds": {"policy": self.rb.const("domain_policy")},
                    "input_result_ids": [r["test_result_id"] for r in rows],
                    "tool_versions": {**TOOL_VERSIONS, "data_hash": _h([coded[k].tolist() for k in sorted(coded)] + [y.tolist()]),
                                      "seed": plan["random_seed"]},
                    "validation_status": "PENDING",
                    "selection_history": (current or {}).get("selection_history", []),
                    "override_decision_ids": (current or {}).get("override_decision_ids", []),
                }
                if current and current.get("_needs_fit"):
                    versions[-1] = model
                else:
                    versions.append(model)
                current = model
            ctx = model_context(fit, alpha=alpha, fit_method="PREPLANNED", scope_hash=self._scope_hash(st),
                                inputs=[{"human_verification_status": r["human_verification_status"],
                                         "evidence_status": r["evidence_status"]} for r in rows],
                                batch_ids=batches)
            cook_flag = float(self.rb.const("cooks_d_flag"))
            current["influence_flags"] = [{"run": rows[i]["doe_run_id"], "source_row": rows[i]["source_row"],
                                           "cooks_d": round(rc["cooks_d"], 3)}
                                          for i, rc in enumerate(ctx["runs"]) if rc["cooks_d"] and rc["cooks_d"] > cook_flag]
            cqa_ctx = cqa_mod.cqa_context(st["cqas"][cid], max_observed=float(y.max()))
            pe_sd = (current.get("pure_error") or {}).get("sd")
            subjects.append((cid, {"model": ctx, "study": {"scope_hash": self._scope_hash(st)}, "cqa": cqa_ctx,
                                   # 시험법 반복정밀도가 비어 있으면 HIGH_PURE_ERROR(SA008)는 NOT_CHECKED가 정상
                                   "method": {"variance_component_type": "METHOD_REPEATABILITY",
                                              "repeatability_sd": None},
                                   "center_points": {"pure_error_sd": pe_sd},
                                   "results": [{"test_method_version": r["test_method_version"]} for r in rows],
                                   "fit_result_ids": [r["test_result_id"] for r in rows],
                                   "range_finding_result_ids": []}))
        ev = self._eval(st, "models", "MODEL_VALIDATION", subjects,
                        rulebooks=["model_validation_rules", "cqa_response_definition_rules",
                                   "provenance_versioning_rules", "screening_analysis_rules"])
        for cid in plan["response_ids"]:
            m = st["models"][cid][-1]
            fired = [v for v in ev.enforced if v.subject == cid and not v.overridden]
            codes = {v.result_code for v in fired}
            if m["validation_status"] == "ACCEPTED_WITH_FLAGS":
                pass
            elif any(v.effect in ("BLOCK_STAGE", "INVALIDATE") for v in fired) or "MODEL_INVALID" in codes:
                m["validation_status"] = "REJECTED"
            elif "HIGH_PURE_ERROR" in codes:
                m["validation_status"] = "HOLD"
            elif "MODEL_FLAGGED" in codes:
                m["validation_status"] = "FLAGGED"
            else:
                m["validation_status"] = "VALID"
            m["rule_codes"] = sorted(codes)
            st["cqas"][cid]["binding_status"] = "NON_BINDING" if "CQA_NON_BINDING" in codes else "BINDING"
        # ACCEPTED_WITH_FLAGS 모델의 MV006은 이미 연구자가 판단했다 — 그 대상의 ROUTE는 다시 세우지 않는다
        accepted = {cid for cid in plan["response_ids"] if st["models"][cid][-1]["validation_status"] == "ACCEPTED_WITH_FLAGS"}
        if ev.decisive and ev.decisive.subject in accepted and ev.decisive.result_code == "MODEL_FLAGGED":
            flagged_left = [c for c in plan["response_ids"] if st["models"][c][-1]["validation_status"] == "FLAGGED"]
            if not flagged_left:
                ev.next_state = None
        statuses = {c: st["models"][c][-1]["validation_status"] for c in plan["response_ids"]}
        self._say(st, "system", "모델 진단: " + ", ".join(f"{st['cqas'][c]['name']} {s}" for c, s in statuses.items()))
        if ev.next_state:
            if ev.next_state == "DIAGNOSING":
                st["diagnosis_trigger"] = {"reason_code": ev.reason_code, "message": ev.decisive.message}
            self._move(st, ev.next_state, ev.reason_code or "", detail=ev.decisive.message)
            return
        if ev.blocking:
            return
        if all(s in ("VALID", "ACCEPTED_WITH_FLAGS") for s in statuses.values()):
            self._move(st, "REGION_COMPUTATION", "VALID")

    def _act_model_reduce(self, st, p, actor):
        self._require(st, "WAITING_MODEL_APPROVAL")
        cid = p.get("cqa_id")
        terms = list(p.get("terms") or [])
        if cid not in st["models"]:
            raise StudyError("모델 없음", status=422)
        if "1" not in terms:
            terms = ["1"] + terms
        ev = self._eval(st, "model_change", "WAITING_MODEL_APPROVAL",
                        [(cid, {"change": {"op": "REDUCE_MODEL", "preserves_hierarchy": doe.is_hierarchical(terms)}})],
                        rule_ids=["AA010"])
        if ev.blocking:
            raise StudyError("계층성을 깨는 축소는 허용되지 않습니다 (AA010).", verdicts=[v.as_dict() for v in ev.blocking])
        prev = st["models"][cid][-1]
        d = self._decide(st, "MODEL_REDUCED", actor, p.get("reason", ""), cqa_id=cid, terms=terms,
                         from_version=prev["version"])
        st["models"][cid].append({
            **{k: prev[k] for k in ("response_model_id", "cqa_id", "domain_bounds")},
            "version": prev["version"] + 1, "intended_terms": terms, "reduced_from": f"{prev['response_model_id']}@{prev['version']}",
            "selection_history": prev.get("selection_history", []) + [{"from": prev["intended_terms"], "to": terms,
                                                                       "by": actor, "decision_id": d["decision_id"],
                                                                       "note": "같은 자료로 계산한 PRESS는 선택 과정을 반영한 독립 추정이 아님"}],
            "override_decision_ids": prev.get("override_decision_ids", []), "validation_status": "PENDING",
            "_needs_fit": True,
        })
        self._say(st, "researcher", f"{st['cqas'][cid]['name']} 모델 축소 승인 → {', '.join(t for t in terms if t != '1')}")
        return {}

    def _act_model_accept(self, st, p, actor):
        self._require(st, "WAITING_MODEL_APPROVAL")
        cid = p.get("cqa_id")
        if not p.get("reason"):
            raise StudyError("flag를 알고 수용하려면 사유가 필요합니다.", status=422)
        m = st["models"][cid][-1]
        d = self._record_override(st, actor, "MV006", "1", "ROUTE", cid, "ACCEPTED_WITH_FLAGS", p["reason"],
                                  affected=[f"{m['response_model_id']}@{m['version']}"])
        m["validation_status"] = "ACCEPTED_WITH_FLAGS"
        m["override_decision_ids"].append(d["decision_id"])
        self._say(st, "researcher", f"{st['cqas'][cid]['name']} 모델을 flag와 함께 수용")
        return {}

    def _act_model_approve(self, st, p, actor):
        self._require(st, "WAITING_MODEL_APPROVAL")
        flagged = [c for c, ms in st["models"].items() if ms[-1]["validation_status"] == "FLAGGED" and not ms[-1].get("_needs_fit")]
        if flagged:
            raise StudyError("판단하지 않은 FLAGGED 모델이 있습니다: " + ", ".join(st["cqas"][c]["name"] for c in flagged))
        self._decide(st, "MODEL_DECISIONS_DONE", actor, p.get("reason", ""))
        self._move(st, "MODEL_VALIDATION", "REDUCTION_APPROVED")
        return {}

    def _act_model_augment(self, st, p, actor):
        self._require(st, "WAITING_MODEL_APPROVAL")
        self._decide(st, "AUGMENT_REQUESTED", actor, p.get("reason", ""))
        self._move(st, "RSM_AUGMENTATION", "AUGMENT_REQUESTED")
        return {}

    def _fits(self, st) -> Dict[str, Fit]:
        plan = self._plan(st)
        out = {}
        for cid in plan["response_ids"]:
            m = st["models"][cid][-1]
            coded, y, _, _ = self._dataset(st, cid)
            out[cid] = Fit(m["intended_terms"], coded, y)
        return out

    # ======================================================================
    # D9 Provisional region
    # ======================================================================
    def _region_computation(self, st):
        plan = self._plan(st)
        fs = self._design_factors(st)
        fits = self._fits(st)
        matrix = np.array([[r["coded"][f.symbol] for f in fs] for r in plan["runs"]])
        domain = Domain(matrix)
        bal = fac_mod.balance_fn(st["handoff"], list(st["factors"].values()))
        res = compute_region(models=fits, cqas=st["cqas"], factors=fs, domain=domain,
                             grid_per_axis=int(self.rb.const("region_grid_points_per_axis")),
                             joint_threshold=float(self.rb.const("joint_pass_probability")),
                             min_edge=float(self.rb.const("setpoint_min_edge_distance_coded")), balance_fn=bal)
        s = res["summary"]
        scope = self._scope(st, plan)
        prev_versions = (st.get("region") or {}).get("history", [])
        version = len(prev_versions) + 1
        ds = {
            "design_space_id": f"DSV-{st['study_id']}", "version": version,
            "source_model_ids": [f"{st['models'][c][-1]['response_model_id']}@{st['models'][c][-1]['version']}" for c in fits],
            "domain_bounds": {"policy": self.rb.const("domain_policy"), "description": domain.describe(plan["design_type"]),
                              "denominator": self.rb.const("feasible_fraction_denominator")},
            "constraints": [{"cqa_id": c, "criterion": cqa_mod.criterion_text(st["cqas"][c])} for c in fits],
            "uncertainty_method": "t 예측분포 (평균 SE² + 잔차분산, df = 잔차 자유도)",
            "joint_probability_policy": {"threshold": self.rb.const("joint_pass_probability"),
                                         "independence_assumed": True, "marginals_stored": True,
                                         "grid_per_axis": self.rb.const("region_grid_points_per_axis")},
            "feasible_region_ref": s["grid_hash"], "recommended_setpoint": s["setpoint"],
            "recommended_operating_range": None, "scope": scope, "verification_plan_id": None,
            "status": "PROVISIONAL", "invalidation_reason": None,
        }
        region_ctx = {"status": "PROVISIONAL", "method": "T_PREDICTIVE_JOINT", "feasible_fraction": s["feasible_fraction"],
                      "scope": {"fixed_conditions_recorded": True, "critical_unmanaged_count": len(scope["unmanaged"]),
                                "limitations_recorded": bool(scope.get("limitations"))},
                      "joint_independence_assumed": True,
                      "setpoint_edge_distance": s["setpoint"]["edge_distance"] if s["setpoint"] else None,
                      "has_operating_range": False, "operating_range_is_subset": None,
                      "criteria_changed_after_results": st.get("cqa_contract_hash") != _h(
                          {k: {f: c[f] for f in ("analysis_role", "acceptance_operator", "lower", "upper", "target",
                                                   "target_tolerance")} for k, c in st["cqas"].items()}),
                      "all_points_in_domain": s["all_points_in_domain"],
                      "domain_policy": self.rb.const("domain_policy"), "scope_hash": self._scope_hash(st)}
        models_ctx = [{"validation_status": st["models"][c][-1]["validation_status"]} for c in fits]
        cqas_ctx = [cqa_mod.cqa_context(c) for c in st["cqas"].values()]
        ev = self._eval(st, "region", "REGION_COMPUTATION",
                        [("영역", {"region": region_ctx, "models": models_ctx, "cqas": cqas_ctx})],
                        rulebooks=["design_space_rules"])
        st["region"] = {"design_space": ds, "summary": s, "grid": res["grid"],
                        "history": prev_versions + [{"version": version, "status": "PROVISIONAL", "at": ho.now(),
                                                     "feasible_fraction": s["feasible_fraction"]}],
                        "symbols": {f.symbol: f.factor_id for f in fs}}
        names = {c: st["cqas"][c]["name"] for c in fits}
        bind = ", ".join(f"{names.get(c, c)} {n}" for c, n in s["binding_cqa_counts"].items())
        self._say(st, "system",
                  f"supported domain 격자 {s['grid_points_in_domain']:,}점 중 평균 기준 통과 {s['mean_ok_fraction']:.1%} → "
                  f"공동확률 ≥ {self.rb.const('joint_pass_probability')} 영역 {s['feasible_fraction']:.1%}. "
                  f"미통과 격자의 경계 주도 CQA: {bind or '없음'}.")
        if ev.next_state:
            self._move(st, ev.next_state, ev.reason_code or "")
            return
        if ev.blocking:
            return
        self._move(st, "WAITING_REGION_APPROVAL", "FEASIBLE")

    def _scope(self, st, plan) -> Dict[str, Any]:
        h = st["handoff"]
        unmanaged = [p["name"] for p in h["fixed_parameters"] if p["status"] == "UNKNOWN"]
        not_eval = [c["name"] for c in st["cqas"].values() if c["analysis_role"] == "MONITOR_ONLY"]
        zones = []
        if plan["design_type"] == "BOX_BEHNKEN":
            zones.append({"zone": "정육면체 꼭짓점 영역", "reason": "BBD 설계점 convex hull 밖 (DV010) — 영역에서 제외"})
        prev = (st.get("region") or {}).get("design_space", {}).get("scope", {})
        return {"fixed_conditions": [p for p in h["fixed_parameters"] if p["status"] != "MISSING"]
                + [{"name": i["name"], "value": i.get("pct_w_w"), "unit": "% w/w", "status": "SET",
                    "evidence_ref": "Handoff"} for i in h["ingredients"] if i["role"] not in ("diluent", "filler", "disintegrant")],
                "unmanaged": unmanaged, "not_evaluated": not_eval,
                "material_lots": [{"note": "API·부형제 lot 각 1개 가정 (결과에 lot 정보 없음)"}],
                "equipment": h.get("equipment_id"), "batch_scale": h.get("batch_scale"),
                "extrapolation_zones": zones, "limitations": prev.get("limitations")}

    def _act_region_approve(self, st, p, actor):
        self._require(st, "WAITING_REGION_APPROVAL")
        st["verification_inputs"] = {"robustness_delta": float(p.get("robustness_delta") or 0.2),
                                     "include_challenge": bool(p.get("include_challenge")),
                                     "reference": p.get("reference")}
        self._decide(st, "REGION_PROVISIONAL_APPROVED", actor, p.get("reason", ""))
        self._say(st, "researcher", "잠정 영역(PROVISIONAL) 승인 — 확인계획으로")
        self._move(st, "VERIFICATION_PLANNING", "PROVISIONAL_APPROVED")
        return {}

    def _act_region_revise(self, st, p, actor):
        self._require(st, "WAITING_REGION_APPROVAL")
        self._decide(st, "REGION_POLICY_REVISION", actor, p.get("reason", ""))
        self._move(st, "REGION_COMPUTATION", "POLICY_REVISION")
        return {}

    # ======================================================================
    # D10 확인계획 · 확인배치 · 2×2 gate
    # ======================================================================
    def _verification_planning(self, st):
        plan = self._plan(st)
        fs = self._design_factors(st)
        fits = self._fits(st)
        matrix = np.array([[r["coded"][f.symbol] for f in fs] for r in plan["runs"]])
        domain = Domain(matrix)
        bal = fac_mod.balance_fn(st["handoff"], list(st["factors"].values()))
        res = compute_region(models=fits, cqas=st["cqas"], factors=fs, domain=domain,
                             grid_per_axis=int(self.rb.const("region_grid_points_per_axis")),
                             joint_threshold=float(self.rb.const("joint_pass_probability")),
                             min_edge=float(self.rb.const("setpoint_min_edge_distance_coded")), balance_fn=bal)
        vi = st.get("verification_inputs") or {}
        prop = propose_verification_points(
            res, models=fits, cqas=st["cqas"], factors=fs, domain=domain,
            joint_threshold=float(self.rb.const("joint_pass_probability")),
            min_edge=float(self.rb.const("setpoint_min_edge_distance_coded")),
            family_alpha=float(self.rb.const("verification_family_alpha")),
            robustness_delta=vi.get("robustness_delta", 0.2), reference=vi.get("reference"),
            include_challenge=vi.get("include_challenge", False))
        vp_id = f"VPLAN-{st['study_id']}-{len((st.get('verification') or {}).get('history', [])) + 1}"
        points = []
        for pt in prop["points"]:
            points.append({**pt, "expected_outcome": pt.get("expected_outcome", "PASS"),
                           "expected_fail_cqa": pt.get("expected_fail_cqa"),
                           "expected_fail_probability": pt.get("expected_fail_probability"),
                           "batch_id": None, "parent_blend_id": None})
        ds = st["region"]["design_space"]
        st["verification"] = {
            "plan": {"verification_plan_id": vp_id, "design_space_id": ds["design_space_id"],
                     "design_space_version": ds["version"], "points": points, "locked_at": None,
                     "approved_by": None, "pi_policy": prop["pi_policy"], "locked_hash": None,
                     "batches_per_point": int(self.rb.const("verification_batches_per_point"))},
            "results": {}, "first_result_submitted_at": None, "gate": None,
            "history": (st.get("verification") or {}).get("history", []),
        }
        ds["verification_plan_id"] = vp_id
        self._check_vplan(st)
        self._say(st, "system", f"확인점 {len(points)}개를 제안했습니다 (필수 3 + 선택/참고 {len(points) - 3}). "
                                f"예측구간은 family {prop['pi_policy']['comparisons'] if prop['pi_policy'] else '-'}개 비교 "
                                f"Bonferroni — 개별 {prop['pi_policy']['per_comparison_level']:.2%}." if prop["pi_policy"] else
                  "확인점을 만들 수 없습니다.")
        self._move(st, "WAITING_VERIFICATION_PLAN_APPROVAL", "PLAN_DRAFTED")

    def _check_vplan(self, st) -> Evaluation:
        vp = st["verification"]["plan"]
        plan_ctx = {"point_roles": [p["role"] for p in vp["points"]], "locked_at": vp["locked_at"]}
        vctx = {"pi_policy": json.dumps(vp["pi_policy"]) if vp["pi_policy"] else None,
                "results_public_before_lock": any(p.get("results_public") for p in vp["points"]
                                                  if p["role"] in ("SETPOINT", "BOUNDARY", "ROBUSTNESS")),
                "first_result_submitted_at": st["verification"].get("first_result_submitted_at"),
                "scope_hash": self._scope_hash(st)}
        subjects = [("확인계획", {"plan": plan_ctx, "verification": vctx})]
        subjects += [(p["point_id"], {"point": {"role": p["role"], "expected_outcome": p["expected_outcome"],
                                                "expected_fail_probability": p.get("expected_fail_probability")}})
                     for p in vp["points"] if p["role"] == "CHALLENGE"]
        return self._eval(st, "verification_plan", "WAITING_VERIFICATION_PLAN_APPROVAL", subjects,
                          rulebooks=["verification_rules"])

    def _act_vplan_lock(self, st, p, actor):
        self._require(st, "WAITING_VERIFICATION_PLAN_APPROVAL")
        ev = self._check_vplan(st)
        if ev.blocking:
            raise StudyError("확인계획을 잠글 수 없습니다.", verdicts=[v.as_dict() for v in ev.blocking])
        vp = st["verification"]["plan"]
        vp["locked_at"] = ho.now()
        vp["approved_by"] = actor
        vp["locked_hash"] = _h({"points": [(q["point_id"], q["settings"], q["predicted"]) for q in vp["points"]],
                                "pi": vp["pi_policy"], "models": st["region"]["design_space"]["source_model_ids"],
                                "cqa": st.get("cqa_contract_hash")})
        self._decide(st, "VERIFICATION_PLAN_LOCKED", actor, p.get("reason", ""), locked_hash=vp["locked_hash"])
        self._say(st, "researcher", f"확인계획 잠금 ({vp['locked_hash']}) — 첫 결과 제출 전에 예측구간이 고정되었습니다.")
        self._move(st, "VERIFICATION_EXECUTION", "PLAN_LOCKED")
        return {}

    def _act_vplan_reject(self, st, p, actor):
        self._require(st, "WAITING_VERIFICATION_PLAN_APPROVAL")
        vi = st.setdefault("verification_inputs", {})
        for k in ("robustness_delta", "include_challenge", "reference"):
            if k in p:
                vi[k] = p[k]
        self._decide(st, "VERIFICATION_PLAN_REJECTED", actor, p.get("reason", ""))
        self._move(st, "VERIFICATION_PLANNING", "REJECTED")
        return {}

    def _act_verification_submit(self, st, p, actor):
        if st["status"] not in ("VERIFICATION_EXECUTION", "VERIFICATION_GATE"):
            raise StudyError("확인배치 결과를 받는 단계가 아닙니다.")
        v = st["verification"]
        vp = v["plan"]
        now = ho.now()
        if v["first_result_submitted_at"] is None:
            v["first_result_submitted_at"] = now
        for pid, entry in (p.get("points") or {}).items():
            pt = next((q for q in vp["points"] if q["point_id"] == pid), None)
            if not pt:
                raise StudyError(f"확인점 {pid} 없음", status=422)
            vals = {c: entry.get("values", {}).get(c) for c in self._applicable_cqas(st)}
            v["results"][pid] = {"batch_id": entry.get("batch_id") or None,
                                 "parent_blend_id": entry.get("parent_blend_id") or None,
                                 "evidence_status": entry.get("evidence_status") or "MEASURED_UNCONFIRMED",
                                 "values": vals, "submitted_at": now, "human_verification_status": "PENDING"}
        self._decide(st, "VERIFICATION_RESULTS_SUBMITTED", actor, p.get("reason", ""), points=list((p.get("points") or {})))
        self._say(st, "researcher", f"확인배치 결과 제출: {', '.join(p.get('points') or {})}")
        return {}

    def _act_verification_confirm(self, st, p, actor):
        if st["status"] not in ("VERIFICATION_EXECUTION", "VERIFICATION_GATE"):
            raise StudyError("확인할 확인배치 결과가 없습니다.")
        v = st["verification"]
        for r in v["results"].values():
            if r["human_verification_status"] == "PENDING":
                r["human_verification_status"] = "CONFIRMED"
                if r["evidence_status"] == "MEASURED_UNCONFIRMED":
                    r["evidence_status"] = "MEASURED_CONFIRMED"
        self._decide(st, "VERIFICATION_RESULTS_CONFIRMED", actor, p.get("reason", ""))
        required = [q for q in v["plan"]["points"] if q["role"] in ("SETPOINT", "BOUNDARY", "ROBUSTNESS")]
        if all(q["point_id"] in v["results"] for q in required) and st["status"] == "VERIFICATION_EXECUTION":
            self._move(st, "VERIFICATION_GATE", "ALL_RUNS_CONFIRMED")
        return {}

    def _applicable_cqas(self, st) -> List[str]:
        return [c for c, x in st["cqas"].items() if x["analysis_role"] in ("DOE_RESPONSE", "MONITOR_ONLY")]

    def _point_eval(self, st, q: Dict[str, Any], r: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        doe_ids = [c for c, x in st["cqas"].items() if x["analysis_role"] == "DOE_RESPONSE"]
        if not r:
            return {"role": q["role"], "spec_pass_all_applicable": None, "within_family_pi_all_doe": None,
                    "expected_outcome": q["expected_outcome"], "batch_id": None, "parent_blend_id": None,
                    "results_confirmed": False, "coverage_complete": False, "evidence_status": None,
                    "expected_fail_cqa": q.get("expected_fail_cqa"),
                    "expected_fail_probability": q.get("expected_fail_probability")}
        per = {}
        for c in self._applicable_cqas(st):
            val = r["values"].get(c)
            sp = spec_pass(st["cqas"][c], val)
            pi = q["predicted"]["cqa"].get(c)
            within = None
            if c in doe_ids and pi and val is not None:
                within = pi["pi_lower"] <= float(val) <= pi["pi_upper"]
            per[c] = {"value": val, "spec_pass": sp, "within_pi": within}
        coverage = all(per[c]["value"] is not None for c in per)
        return {"role": q["role"], "spec_pass_all_applicable": all(x["spec_pass"] for x in per.values() if x["spec_pass"] is not None)
                and coverage, "within_family_pi_all_doe": all(per[c]["within_pi"] for c in doe_ids if c in per),
                "expected_outcome": q["expected_outcome"], "batch_id": r["batch_id"],
                "parent_blend_id": r["parent_blend_id"], "results_confirmed": r["human_verification_status"] == "CONFIRMED",
                "coverage_complete": coverage, "evidence_status": r["evidence_status"],
                "expected_fail_cqa": q.get("expected_fail_cqa"),
                "expected_fail_probability": q.get("expected_fail_probability"), "per_cqa": per}

    def _verification_gate(self, st):
        v = st["verification"]
        vp = v["plan"]
        pts = {q["point_id"]: self._point_eval(st, q, v["results"].get(q["point_id"])) for q in vp["points"]}
        required = [pts[q["point_id"]] for q in vp["points"] if q["role"] in ("SETPOINT", "BOUNDARY", "ROBUSTNESS")]
        fit_batches = [r.get("batch_id") for r in self._fit_results(st)]
        model_ctx = {"input_batch_ids": [b for b in fit_batches if b]}
        strip = lambda d: {k: val for k, val in d.items() if k != "per_cqa"}   # noqa: E731
        common = {"plan": {"locked_at": vp["locked_at"], "point_roles": [q["role"] for q in vp["points"]]},
                  "verification": {"first_result_submitted_at": v["first_result_submitted_at"],
                                   "results_public_before_lock": False, "scope_hash": self._scope_hash(st),
                                   "pi_policy": "BONFERRONI"},
                  "required_points": [strip(x) for x in required], "model": model_ctx,
                  "fit_blend_ids": [r.get("parent_blend_id") for r in self._fit_results(st) if r.get("parent_blend_id")],
                  "points": [strip(x) for x in pts.values()]}
        # 점별 2×2 판정은 결과가 완결·확정되고 확인 판정에 쓸 수 있는 근거 등급일 때만 한다.
        # 미완결(VR014)이나 문헌·합성값(VR015)을 점별 규격 실패로 읽으면 영역을 잘못 무효화한다.
        judgeable = {pid: x for pid, x in pts.items()
                     if x["results_confirmed"] and x["coverage_complete"] and (
                         x["role"] == "REFERENCE_EXISTING" or
                         self.rb.evidence_permits(x["evidence_status"], "VERIFICATION", st["mode"]))}
        subjects = [("확인계획", common)] + [(pid, {"point": strip(x)}) for pid, x in judgeable.items()]
        ev = self._eval(st, "verification_gate", "VERIFICATION_GATE", subjects,
                        rulebooks=["verification_rules", "provenance_versioning_rules"])
        v["gate"] = {"points": pts, "decisive": ev.decisive.as_dict() if ev.decisive else None, "at": ho.now()}
        if ev.next_state:
            ds = st["region"]["design_space"]
            if ev.decisive.effect == "INVALIDATE":
                ds["status"] = "INVALIDATED"
                ds["invalidation_reason"] = f"{ev.reason_code}: {ev.decisive.message} ({ev.decisive.subject})"
                st["region"]["history"][-1]["status"] = "INVALIDATED"
                v["history"].append({"plan_id": vp["verification_plan_id"], "outcome": ev.reason_code})
                st["diagnosis_trigger"] = {"reason_code": ev.reason_code, "message": ev.decisive.message,
                                           "point": ev.decisive.subject}
                self._say(st, "system", f"확인배치 판정 {ev.reason_code} — 영역 v{ds['version']}를 INVALIDATED 처리했습니다.")
            else:
                self._say(st, "system", "필수 확인점 3개가 모두 규격 통과 · family 예측구간 안 — 최종 승인을 요청합니다.")
            self._move(st, ev.next_state, ev.reason_code or "")
            return
        if ev.blocking:
            self._say(st, "system", "확인 판정이 막혔습니다: " + "; ".join(sorted({x.message for x in ev.blocking})),
                      kind="block")

    def _act_finalize(self, st, p, actor):
        self._require(st, "WAITING_FINAL_APPROVAL")
        ds = st["region"]["design_space"]
        if p.get("limitations"):
            ds["scope"]["limitations"] = p["limitations"]
        v = st["verification"]
        required = [x for x in v["gate"]["points"].values() if x["role"] in ("SETPOINT", "BOUNDARY", "ROBUSTNESS")]
        strip = lambda d: {k: val for k, val in d.items() if k != "per_cqa"}   # noqa: E731
        region_ctx = {"status": ds["status"], "has_operating_range": False, "operating_range_is_subset": None,
                      "scope": {"critical_unmanaged_count": len(ds["scope"]["unmanaged"]),
                                "limitations_recorded": bool(ds["scope"].get("limitations")),
                                "fixed_conditions_recorded": True},
                      "scope_hash": self._scope_hash(st)}
        ctx = {"region": region_ctx, "change": {"to_value": "VERIFIED"},
               "required_points": [strip(x) for x in required],
               "promotion_basis_points": [strip(x) for x in required],
               "verification": {"scope_hash": self._scope_hash(st)}}
        ev = self._eval(st, "final", "WAITING_FINAL_APPROVAL", [("최종 영역", ctx)],
                        rulebooks=["design_space_rules", "verification_rules", "approval_authority_rules"])
        if ev.next_state:
            self._move(st, ev.next_state, ev.reason_code or "")
            return {}
        if ev.blocking:
            raise StudyError("최종 승인을 할 수 없습니다.", verdicts=[x.as_dict() for x in ev.blocking])
        ds["status"] = "VERIFIED"
        st["region"]["history"][-1]["status"] = "VERIFIED"
        self._decide(st, "FINAL_REGION_VERIFIED", actor, p.get("reason", ""),
                     design_space=f"{ds['design_space_id']}@{ds['version']}")
        self._say(st, "researcher", "최종 영역 승인 — VERIFIED (내부 사전계획 통과. 규제 승인 Design Space가 아님)")
        self._move(st, "COMPLETED", "APPROVED")
        return {}

    def _act_final_more(self, st, p, actor):
        self._require(st, "WAITING_FINAL_APPROVAL")
        self._decide(st, "MORE_VERIFICATION", actor, p.get("reason", ""))
        self._move(st, "VERIFICATION_PLANNING", "MORE_VERIFICATION")
        return {}

    # ======================================================================
    # 증강 · screening 분석 · 진단
    # ======================================================================
    def _augmentation(self, st):
        """MVP 증강: 중심점 2개(새 블록) + 실패 확인점 근처 표적점. D-optimal은 미지원 (AU003)."""
        plan = self._plan(st)
        fs = self._design_factors(st)
        trig = st.get("diagnosis_trigger") or {}
        ev = self._eval(st, "augmentation", st["status"],
                        [("증강", {"event": {"reason_code": trig.get("reason_code") or "MODEL_INVALID"},
                                   "model": {"invalid_cause": None, "local_prediction_se_high": None}})],
                        rulebooks=["doe_augmentation_rules"])
        extra = [{"coded": {f.symbol: 0.0 for f in fs}, "why": "블록 중심점"} for _ in range(2)]
        pid = (trig.get("point") or "")
        if st.get("verification") and pid:
            q = next((x for x in st["verification"]["plan"]["points"] if x["point_id"] == pid), None)
            if q:
                extra.append({"coded": q["coded"], "why": f"{q['role']} 확인점 표적 run"})
        n0 = len(plan["runs"])
        runs = [dict(r) for r in plan["runs"]]
        for i, e in enumerate(extra):
            runs.append({"std_order": n0 + i + 1, "run_order": n0 + i + 1, "coded": e["coded"],
                         "actual": {f.factor_id: round(f.to_actual(e["coded"][f.symbol]), 6) for f in fs},
                         "center": all(v == 0 for v in e["coded"].values()), "doe_run_id": f"A{i + 1:02d}",
                         "block": 2, "why": e["why"]})
        new = {**copy.deepcopy(plan), "doe_plan_id": f"{plan['doe_plan_id']}-AUG{len(st['plans'])}",
               "version": plan["version"] + 1, "runs": runs, "status": "DESIGN_VALID",
               "block_definition": {"block": "stage", "levels": [1, 2]},
               "augmentation_codes": [x.result_code for x in ev.verdicts if x.status == "FIRES"]}
        new["intended_model_terms"] = plan["intended_model_terms"]
        new["diagnostics"] = {**plan["diagnostics"], "n_runs": len(runs), "augmented_runs": len(extra)}
        st["plans"].append(new)
        st["active_plan"] = new["doe_plan_id"]
        for cid in st["models"]:
            if st["models"][cid]:
                st["models"][cid][-1]["_needs_fit"] = True
        self._say(st, "system", f"증강 계획: {len(extra)} run 추가 (블록 2). 승인해 주세요.")
        self._move(st, "WAITING_SCREENING_APPROVAL" if st["status"] == "SCREENING_AUGMENTATION" else "WAITING_RSM_APPROVAL",
                   "AUGMENT_PLANNED")

    def _screening_analysis(self, st):
        """효과구간 판정(ACTIVE·FIXED·INCONCLUSIVE 상호배타) → 요인 분류 → 경로. 두 번 평가한다:
        1차는 효과별 분류, 2차는 분류가 반영된 요인 목록으로 곡률·활성 요인 없음·재정의 규칙."""
        from formula.qbd.analysis import curvature_test, screening_effects
        plan = self._plan(st)
        alpha = float(self.rb.const("alpha"))
        monitor = [c["name"] for c in st["cqas"].values() if c["analysis_role"] == "MONITOR_ONLY"]
        sym2fid = plan["symbols"]
        effect_subjects, curv_any = [], None
        for cid in plan["response_ids"]:
            coded, y, _, rows = self._dataset(st, cid)
            fit = Fit(plan["intended_model_terms"], coded, y)
            is_c = np.array([all(abs(coded[s_][i]) < 1e-9 for s_ in coded) for i in range(len(y))])
            curv = curvature_test(y, is_c, alpha)
            if curv["significant"] is not None:
                curv_any = bool(curv_any) or curv["significant"]
            aliased = {t for pair in plan["alias_structure"].get("pairs", []) for t in pair if ":" not in t}
            for e in screening_effects(fit, alpha):
                effect_subjects.append((f"{cid}:{sym2fid[e['term']]}", {
                    "effect": {**e, "aliased": e["term"] in aliased, "alias_resolved": False},
                    "cqa": cqa_mod.cqa_context(st["cqas"][cid])}))
        ev1 = self._eval(st, "screening_effects", "SCREENING_ANALYSIS", effect_subjects,
                         rule_ids=["SA001", "SA002", "SA004", "SA006"])
        decisions, classes = [], {}
        for fid in plan["factor_ids"]:
            mine = [v for v in ev1.verdicts if v.subject.endswith(":" + fid)]
            fired = {v.result_code for v in mine if v.status == "FIRES"}
            per_resp = {v.subject.split(":")[0] for v in mine if v.status == "FIRES" and v.result_code == "FACTOR_FIXED"}
            if "FACTOR_ACTIVE" in fired:
                cls = "ACTIVE"
            elif "UNRESOLVED_ALIAS" in fired:
                cls = "ALIASED"
            elif per_resp == set(plan["response_ids"]):
                cls = "FIXED"
            else:
                cls = "INCONCLUSIVE"
            classes[fid] = cls
            decisions.append({"factor_id": fid, "classification": cls, "responses_evaluated": plan["response_ids"],
                              "not_evaluated": monitor, "spec_checked": monitor,
                              "range_tested": {"low": st["factors"][fid]["low"]["value"],
                                               "high": st["factors"][fid]["high"]["value"]},
                              "rationale_codes": sorted({v.result_code for v in mine if v.effect})})
        facs = [{**fac_mod.factor_context(st["factors"][fid]), "disposition": classes[fid]} for fid in plan["factor_ids"]]
        group = [("screening", {"factors": facs, "curvature_test": {"significant": curv_any},
                                "factor": {"redefinition_requested": bool(st.get("factor_redefinition"))}})]
        for fid in plan["factor_ids"]:
            sev = max([r.get("severity") or 0 for r in st["fmea"]["rows"] if r["row_id"] in st["factors"][fid]["fmea_refs"]] or [0])
            group.append((fid, {"decision": {"classification": "FACTOR_FIXED" if classes[fid] == "FIXED" else classes[fid],
                                             "severity": sev or None}}))
        # 분류가 이미 정해진 요인(ACTIVE/FIXED)의 효과는 경로를 다시 정하지 않는다 — 판정이 안 난 요인만 증강 사유가 된다
        open_effects = [(lbl, ctx) for lbl, ctx in effect_subjects
                        if classes[lbl.split(":", 1)[1]] in ("INCONCLUSIVE", "ALIASED")]
        ev = self._eval(st, "screening", "SCREENING_ANALYSIS", open_effects + group,
                        rulebooks=["screening_analysis_rules"])
        for d in decisions:
            if d["classification"] == "FIXED" and any(v.rule_id == "SA005" and v.subject == d["factor_id"]
                                                      and v.status == "FIRES" for v in ev.verdicts):
                d["classification"] = "RETAIN_FOR_SAFETY"
        st["screening"] = {"decisions": decisions, "curvature": curv_any}
        n_active = sum(1 for d in decisions if d["classification"] == "ACTIVE")
        self._say(st, "system", "Screening 판정: " + ", ".join(
            f"{st['factors'][d['factor_id']]['name']} {d['classification']}" for d in decisions)
            + (f" · 곡률 {'감지' if curv_any else '없음'}" if curv_any is not None else " · 곡률 계산 불가"))
        def carry():
            # 다음 RSM에는 ACTIVE 요인만 넘긴다. 나머지는 중심 수준에 고정되어 scope에 남고,
            # RETAIN_FOR_SAFETY(고심각도인데 효과 없음)는 고정하되 검토 표시를 단다(SA005).
            for d in decisions:
                if d["classification"] != "ACTIVE":
                    f = st["factors"][d["factor_id"]]
                    f["disposition"] = "FIXED"
                    if d["classification"] == "RETAIN_FOR_SAFETY":
                        f.setdefault("proposal_notes", []).append("고심각도 요인 — 효과는 없었지만 고정 수준 관리 검토 필요 (SA005)")
            st.setdefault("design_inputs", {})["design_type"] = None
        if ev.next_state:
            if ev.next_state == "RSM_PLANNING":
                carry()
            self._move(st, ev.next_state, ev.reason_code or "", detail=ev.decisive.message)
            return
        if ev.blocking:
            return
        if n_active:
            carry()
            self._move(st, "RSM_PLANNING", "ACTIVE_FACTORS")

    def _diagnosing(self, st):
        trig = st.get("diagnosis_trigger") or {"reason_code": "UNKNOWN"}
        tests = [{"test_id": r["test_id"], "name": r["name_ko"]} for r in self.rb.master("confirmation_test_master")]
        assumptions = [f"{f['name']} 경계 {f['low']['evidence_status']}" for f in st["factors"].values()
                       if "EXPERT_ASSUMPTION" in (f["low"]["evidence_status"], f["high"]["evidence_status"])]
        d = agents.diagnose(trig, [{"rule_id": o["rule_id"], "decision": o["researcher_decision"]} for o in st["overrides"]],
                            assumptions + st["assumptions"], tests)
        st["diagnosis"] = {**d, "trigger": trig, "at": ho.now()}
        self._say(st, "system", f"진단: 경쟁 원인가설 {len(d['hypotheses'])}개, 제안 방향 {d['directive']} "
                                f"({'LLM' if d['generated_by'] == 'llm' else '규칙 기반 대체 — LLM 미사용'}).")
        self._move(st, "REFLECTING", "CAUSE_PROPOSED")

    def _act_directive_approve(self, st, p, actor):
        self._require(st, "WAITING_DIRECTIVE_APPROVAL")
        directive = p.get("directive") or st["diagnosis"]["directive"]
        target = {"DOE_AUGMENT": "RSM_AUGMENTATION", "FACTOR_RANGE_REVISION": "FACTOR_READINESS",
                  "METHOD_PROCESS_CONTROL": "DESIGN_SELECTION", "CANDIDATE_REVISION": "CLOSED_SUPERSEDED"}.get(directive)
        if not target:
            raise StudyError("알 수 없는 directive", status=422)
        self._decide(st, "DIRECTIVE_APPROVED", actor, p.get("reason", ""), directive=directive)
        self._move(st, target, "CANDIDATE_PREMISE_FAILURE" if directive == "CANDIDATE_REVISION" else directive)
        return {"child_candidate_requested": directive == "CANDIDATE_REVISION"}

    def _act_directive_reject(self, st, p, actor):
        self._require(st, "WAITING_DIRECTIVE_APPROVAL")
        self._decide(st, "DIRECTIVE_REJECTED", actor, p.get("reason", ""))
        self._move(st, "DIAGNOSING", "REJECTED")
        return {}

    def _act_triage_resolve(self, st, p, actor):
        if st["status"] not in sm.GLOBAL_EXCEPTIONS:
            raise StudyError("triage 상태가 아닙니다.")
        back = st.get("return_point") or "ENTRY_READINESS"
        st["return_point"] = None
        self._decide(st, "TRIAGE_RESOLVED", actor, p.get("reason", ""), return_to=back)
        st["timeline"].append({"from": st["status"], "to": back, "reason": "TRIAGE_RESOLVED", "at": ho.now()})
        st["status"] = back
        return {}

    # -- override (§2.2) ------------------------------------------------------
    def _act_override(self, st, p, actor):
        rule = self.rb.by_id.get(p.get("rule_id") or "")
        if not rule:
            raise StudyError("규칙 없음", status=422)
        ev = self._eval(st, "override_check", "ANY",
                        [(rule.rule_id, {"rule": {"gate_effect": rule.gate_effect}, "change": {"op": "OVERRIDE"}})],
                        rule_ids=["AA017"])
        if ev.blocking or rule.human_override == "NONE":
            raise StudyError(f"{rule.rule_id}({rule.gate_effect})는 override할 수 없습니다 (AA017).",
                             verdicts=[v.as_dict() for v in ev.blocking])
        if not p.get("reason"):
            raise StudyError("override에는 사유가 필요합니다.", status=422)
        if rule.human_override == "REASON_AND_APPROVER" and not p.get("approver"):
            raise StudyError(f"{rule.rule_id}는 사유와 승인권자({rule.override_approver_role or '승인권자'})가 필요합니다.",
                             status=422)
        if rule.human_override == "ALTERNATIVE_EVIDENCE" and not p.get("evidence_ref"):
            raise StudyError(f"{rule.rule_id}는 대체 근거(evidence_ref)가 필요합니다. 원출처 등급은 바뀌지 않습니다.",
                             status=422)
        d = self._record_override(st, actor, rule.rule_id, rule.version, rule.gate_effect, p.get("subject") or "*",
                                  p.get("decision") or "PROCEED", p["reason"], approver=p.get("approver"),
                                  evidence_ref=p.get("evidence_ref"))
        # 진행 중이던 결정론 상태를 다시 평가하게 한다
        back = {"WAITING_REQUIRED_DATA": "ENTRY_READINESS", "WAITING_FACTOR_DATA": "FACTOR_READINESS",
                "RANGE_FINDING_RUNS": "FACTOR_READINESS"}.get(st["status"])
        if back:
            self._move(st, back, "OVERRIDE")
        return {"decision_id": d["decision_id"]}

    def _record_override(self, st, actor, rule_id, rule_version, effect, subject, decision, reason, *,
                         approver=None, evidence_ref=None, affected=None) -> Dict[str, Any]:
        d = {"decision_id": "OVR-" + uuid.uuid4().hex[:8], "rule_id": rule_id, "rule_version": str(rule_version),
             "original_effect": effect, "researcher_decision": decision, "reason": reason, "approver": approver,
             "actor_id": actor, "affected_artifacts": affected or [subject], "created_at": ho.now(),
             "subject": subject, "evidence_ref": evidence_ref, "kind": "OVERRIDE"}
        st["overrides"].append(d)
        st.setdefault("_decisions", []).append(d)
        return d

    def _require(self, st, state: str) -> None:
        if st["status"] != state:
            raise StudyError(f"지금 상태는 {st['status']}입니다 — 이 행동은 {state}에서만 가능합니다.")

    # ======================================================================
    # 연구자에게 지금 묻는 것 — 화면의 "다음 행동" 카드
    # ======================================================================
    def _prompt(self, st: Dict[str, Any]) -> Dict[str, Any]:
        s = st["status"]
        P = {
            "WAITING_REQUIRED_DATA": ("진입 자료가 필요합니다", "규칙이 요청한 값을 입력하거나, 모르는 고정 공정변수는 UNKNOWN으로 기록하세요. "
                                      "UNKNOWN은 최종 영역의 scope에 '관리되지 않음'으로 남습니다.", ["required_data"]),
            "WAITING_CQA_APPROVAL": ("CQA 계약을 확정해 주세요", "각 CQA의 역할(DoE 반응/모니터링/해당없음)과 절대 규격을 정합니다. "
                                     "시험법·단위·절대 규격이 없는 CQA는 DoE 반응이 될 수 없습니다.", ["cqa_edit", "cqa_approve", "cqa_reject"]),
            "WAITING_FMEA_APPROVAL": ("FMEA 처리 방향을 정해 주세요", "각 실패모드를 DoE 요인 / 고정 / 자료 요청 / 제외 중 하나로 보냅니다. "
                                      "S≥4 행은 대체관리·승인 없이 제외할 수 없고, LLM 가설은 채택해도 가설 태그가 남습니다.",
                                      ["fmea_edit", "fmea_approve", "fmea_reject"]),
            "WAITING_FACTOR_DATA": ("요인 범위의 근거가 필요합니다", "범위(연구 목적)와 출처를 넣어 주세요. 근거 없는 경계는 만들지 않습니다.",
                                    ["factor_data"]),
            "RANGE_FINDING_RUNS": ("끝점 제조 가능성을 확인해 주세요", "극단 조합 2–4개를 먼저 만들어 보고 결과(제조 가능 근거)를 입력하세요. "
                                   "이 run은 적합에 쓰지 않습니다.", ["factor_data"]),
            "WAITING_FACTOR_APPROVAL": ("요인과 수준값을 승인해 주세요", "center는 후보 현재값, 경계는 근거 교집합입니다. 3요인 이하이고 "
                                        "승인된 사전근거가 있으면 RSM으로 직행합니다.", ["factor_approve", "factor_data"]),
            "WAITING_RSM_APPROVAL": ("RSM 설계를 승인해 주세요", "행렬·run order·seed는 코드가 만들었습니다. 권고와 다른 설계를 쓰려면 사유가 필요합니다.",
                                     ["plan_approve", "plan_reject"]),
            "WAITING_SCREENING_APPROVAL": ("Screening 설계를 승인해 주세요", "Resolution·alias를 확인하세요.", ["plan_approve", "plan_reject"]),
            "RSM_EXECUTION": ("실험 결과를 입력해 주세요", "run별 결과 CSV를 올리면 시스템이 설정값으로 run을 대조하고, 확인을 거쳐 품질 게이트로 보냅니다.",
                              ["results_submit", "results_confirm"]),
            "SCREENING_EXECUTION": ("Screening 결과를 입력해 주세요", "run별 결과 CSV를 올려 주세요.", ["results_submit", "results_confirm"]),
            "WAITING_MODEL_APPROVAL": ("모델 판단이 필요합니다", "과적합 flag가 선 모델을 계층성을 지켜 축소하거나, flag를 알고 수용(사유 기록)하세요. "
                                       "p값 기반 자동 항 삭제는 하지 않습니다.", ["model_reduce", "model_accept", "model_approve", "model_augment"]),
            "WAITING_REGION_APPROVAL": ("잠정 영역을 검토해 주세요", "공동확률 영역과 권장 setpoint입니다. 승인하면 PROVISIONAL로 확인계획을 세웁니다.",
                                        ["region_approve", "region_revise"]),
            "WAITING_VERIFICATION_PLAN_APPROVAL": ("확인계획을 잠가 주세요", "확인점·예측구간을 첫 결과 전에 잠급니다. 잠근 뒤에는 수정할 수 없습니다.",
                                                   ["vplan_lock", "vplan_reject"]),
            "VERIFICATION_EXECUTION": ("확인배치 결과를 입력해 주세요", "필수 확인점 3개 × 적용 CQA 전부가 필요합니다. 독립 제조배치(배치·블렌드 ID)여야 하며, "
                                       "문헌·합성값은 확인 판정에 쓸 수 없습니다.", ["verification_submit", "verification_confirm"]),
            "VERIFICATION_GATE": ("확인 판정이 막혔습니다", "막힌 사유를 해소하는 결과를 다시 제출하세요.", ["verification_submit", "verification_confirm"]),
            "WAITING_FINAL_APPROVAL": ("최종 영역을 승인해 주세요", "관리되지 않은 중요 공정변수가 있으면 검증 주장의 한계를 기록해야 합니다.",
                                       ["finalize", "final_more"]),
            "WAITING_DIRECTIVE_APPROVAL": ("진단 결과 다음 방향을 정해 주세요", "경쟁 가설과 제안 방향입니다. 승인하면 해당 단계로 돌아갑니다.",
                                           ["directive_approve", "directive_reject"]),
            "DESIGN_REPLAN": ("설계를 다시 정해야 합니다", "설계 문제면 설계 선택으로, 범위 문제면 요인 준비로 돌아갑니다.", ["replan"]),
            "STRATEGY_REVIEW": ("전략 검토가 필요합니다", "요인을 다시 정하거나 후보 개정(child candidate)을 요청하세요. 규격은 자동 완화하지 않습니다.",
                                ["factor_data", "replan"]),
            "WAITING_HUMAN_TRIAGE": ("사람의 판단이 필요합니다", "전이표에 없는 사유가 발생했습니다. 확인 후 복귀 지점에서 재개합니다.", ["triage_resolve"]),
            "WAITING_AUDIT_REVIEW": ("lineage 검토가 필요합니다", "scope·fingerprint가 어긋났습니다.", ["triage_resolve"]),
            "COMPLETED": ("VERIFIED 최종 영역", "내부 사전계획을 통과한 영역과 성립 조건입니다. 규제기관 승인 Design Space나 PPQ가 아닙니다.", []),
            "INELIGIBLE": ("진입 불가", "상류 Hard Fail이 해소되지 않았습니다. 새 후보로 시작하세요.", []),
            "CLOSED_SUPERSEDED": ("후보 개정으로 종료", "child candidate 요청이 상류로 전달되었습니다.", []),
        }
        title, ask, actions = P.get(s, (s, "", []))
        ev = st["evaluations"]
        return {"title": title, "ask": ask, "actions": actions, "state": s}


def _float(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_units(scale: Optional[str]) -> Optional[int]:
    if not scale:
        return None
    digits = "".join(ch for ch in scale.split("(")[0] if ch.isdigit())
    return int(digits) if digits else None


def guess_columns(cols: List[str], st: Dict[str, Any]) -> Dict[str, str]:
    """CSV 열 → 요인·CQA 추정. 화면이 이 추정을 **보여 주고 연구자가 확정**한다."""
    keys = {
        "F_filler_ratio": ("ratio", "mcc", "filler"), "F_blend_time": ("mix", "blend"),
        "F_disintegrant_pct": ("crospovidone", "disint", "croscarmellose", "ssg"),
        "F_lubricant_pct": ("lubric", "stearate"), "F_compression_force": ("compression", "force"),
        "CQA_DISPERSIBILITY": ("dispers",), "CQA_FRIABILITY": ("friab",), "CQA_DISSOLUTION": ("de30", "dissol"),
        "CQA_CU_AV": ("cu_av", "_av", "uniform"), "CQA_DISINTEGRATION": ("disintegration",),
        "CQA_BREAKING_FORCE": ("hardness", "breaking"), "CQA_ASSAY": ("assay",),
    }
    valid = set(st["factors"]) | set(st["cqas"])
    out = {}
    for c in cols:
        lc = c.lower()
        for target, kws in keys.items():
            if target in valid and target not in out.values() and any(k in lc for k in kws):
                out[c] = target
                break
    return out
