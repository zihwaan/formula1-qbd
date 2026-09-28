"""Stage2Service — 2단계 Design Space 도출 study. docs/stage2/DESIGN.md의 15단계 표가 곧 이 파일이다.

- 지금 단계만 바꿀 수 있다. 편집 단계는 [LLM 초안 | 논문 값(CBD 논문 프로토타입만) | 연구자 편집] → 승인, 파생 단계(5·7·11·12)는 코드가 만들고 연구자가 확인한다.
- 앞 단계를 다시 열면 뒤 단계는 '다시 확인 필요(stale)'가 된다 — 지우지 않는다.
- 승인은 결정론 검사(model.check)의 blocking이 없을 때만. 버전·출처(llm/paper/user)·승인은 이력으로 남는다.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from formula.stage2 import agent as AG
from formula.stage2 import doe as T
from formula.stage2 import reference as REF
from formula.stage2 import space as SP
from formula.stage2.model import (DERIVED, EDITABLE, LLM_STEPS, MAX_FACTORS, MAX_RESPONSES, STEPS, TABLE, TITLE,
                                  candidates, check, material_controls, matrix_of, numbers_not_in, risk_cqas, watch_list)
from formula.stage2.store import StudyError, StudyStore, VersionConflict

ACTIONS = ("run", "draft", "use_reference", "save", "approve", "reopen", "attach_images")
MAX_IMAGE_BYTES = 900_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Stage2Service:
    def __init__(self, store: Optional[StudyStore] = None):
        self.store = store or StudyStore(Path(os.environ.get("FORMULA1_STAGE2_DB", "/tmp/formula1/stage2.db")))

    # ── 공개 ─────────────────────────────────────────────────────────────────
    def create(self, prototype: Dict[str, Any], *, title: str, source: Dict[str, Any], reference: bool = False, actor: str = "researcher",
               idempotency_key: Optional[str] = None, origin: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        rep = self.store.replay(idempotency_key)
        if rep:
            return self.view(rep["study_id"])
        sid = "S2-" + uuid.uuid4().hex[:10]
        st = {"study_id": sid, "status": "prototype", "mode": "stage2", "title": title, "candidate_ref": source.get("candidate_ref") or source.get("locator") or "",
              "created_at": _now(), "updated_at": _now(), "source": source, "origin": origin or {}, "reference": bool(reference),
              "steps": {s: {"status": "empty", "source": None, "data": None, "version": 0, "history": [], "checks": [], "llm": None} for s in STEPS},
              "approvals": [], "timeline": [], "images": {}}
        self._set(st, "prototype", _normalize("prototype", prototype), source="upstream", actor=actor)
        self.store.save(st, expected_version=None, event_type="S2_CREATED", idempotency_key=idempotency_key, actor_id=actor,
                        payload={"title": title, "source": source}, result={"study_id": sid}, decisions=[], now=_now())
        return self.view(sid)

    def act(self, sid: str, action: str, payload: Dict[str, Any], *, actor: str = "researcher",
            idempotency_key: Optional[str] = None, expected_version: Optional[int] = None) -> Dict[str, Any]:
        rep = self.store.replay(idempotency_key)
        if rep:
            out = self.view(sid)
            out["replayed"] = True
            return out
        st, version = self._load(sid)
        if expected_version is not None and expected_version != version:
            raise VersionConflict(expected_version, version)
        if action not in ACTIONS:
            raise StudyError(f"알 수 없는 행동 {action}", status=404)
        step = payload.get("step") or st["status"]
        if action != "reopen" and step != st["status"]:
            raise StudyError(f"지금 단계는 '{TITLE.get(st['status'], st['status'])}'입니다 — '{TITLE.get(step, step)}'를 고치려면 먼저 그 단계를 다시 여세요.")
        if st["status"] == "done" and action != "reopen":
            raise StudyError("모든 단계를 마쳤습니다 — 고치려면 단계를 다시 여세요.")
        result = getattr(self, f"_{action}")(st, step, payload, actor) or {}
        st["updated_at"] = _now()
        pay = {k: v for k, v in payload.items() if k not in ("data", "images")}
        self.store.save(st, expected_version=version, event_type=f"S2_{action.upper()}", idempotency_key=idempotency_key, actor_id=actor,
                        payload=pay, result={"study_id": sid, **{k: v for k, v in result.items() if k != "data"}},
                        decisions=[{"action": action, "step": step, **{k: result[k] for k in ("blocked", "provider") if result.get(k)}}], now=_now())
        out = self.view(sid)
        out["action_result"] = result
        return out

    def view(self, sid: str) -> Dict[str, Any]:
        st, version = self._load(sid)
        st["state_version"] = version
        st.pop("images", None)
        ref = self._reference(st) if st.get("reference") else None
        return {"study": st, "current": st["status"], "done": st["status"] == "done",
                "steps": [{"key": s, "n": i + 1, "title": TITLE[s], "table": TABLE.get(s), "status": st["steps"][s]["status"],
                           "editable": s in EDITABLE, "derived": s in DERIVED, "llm": s in LLM_STEPS} for i, s in enumerate(STEPS)],
                "reference": ref, "reference_citation": REF.citation() if ref else None}

    def list(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self.store.list(limit)

    def trace(self, sid: str) -> Dict[str, Any]:
        st, v = self._load(sid)
        return {"study_id": sid, "state_version": v, "approvals": st["approvals"], "timeline": st["timeline"],
                "events": self.store.events(sid), "decisions": self.store.decisions(sid)}

    def surfaces(self, sid: str, slice_factor: Optional[int] = None) -> Dict[str, Any]:
        st, _ = self._load(sid)
        reg = st["steps"]["regression"]["data"]
        if not reg:
            raise StudyError("회귀식이 아직 없습니다.", status=409)
        design = st["steps"]["design"]["data"]
        k = len(design["factors"])
        order = None
        if slice_factor is not None and 0 <= slice_factor < k and k == 3:
            order = [i for i in range(k) if i != slice_factor] + [slice_factor]
        out = T.surfaces(design, reg, order=order)
        out["factor_choices"] = [{"id": i, "name": f["name"]} for i, f in enumerate(design["factors"])] if k == 3 else []
        return _plain(out)

    def space_slice(self, sid: str, fixed: Optional[int] = None, level: Optional[float] = None) -> Dict[str, Any]:
        st, _ = self._load(sid)
        d = st["steps"]["space"]["data"]
        if not d or not st["steps"]["regression"]["data"]:
            raise StudyError("영역을 아직 계산하지 않았습니다.", status=409)
        return _plain(SP.slice_map(st["steps"]["design"]["data"], st["steps"]["regression"]["data"], d.get("specs") or [],
                                   fixed=fixed, level=level))

    def images(self, sid: str) -> Dict[str, bytes]:
        st, _ = self._load(sid)
        return {k: base64.b64decode(v) for k, v in (st.get("images") or {}).items()}

    def raw(self, sid: str) -> Dict[str, Any]:
        st, v = self._load(sid)
        st["state_version"] = v
        return st

    # ── 내부 ─────────────────────────────────────────────────────────────────
    def _load(self, sid: str):
        got = self.store.load(sid)
        if not got:
            raise StudyError("2단계 study 없음", status=404)
        return got

    def _ctx(self, st: Dict[str, Any]) -> Dict[str, Any]:
        return {s: st["steps"][s]["data"] for s in STEPS}

    def _set(self, st, step, data, *, source: str, actor: str, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        s = st["steps"][step]
        if s["data"] is not None:
            s["history"].append({"version": s["version"], "source": s["source"], "at": _now(), "data": s["data"]})
            s["history"] = s["history"][-8:]
        prev = s["source"]
        s["data"] = data
        s["version"] += 1
        s["source"] = source if source != "user" or prev in (None, "user", "code") else (prev if prev.endswith("+user") else f"{prev}+user")
        s["status"] = "draft"
        s["checks"] = check(step, data, self._ctx(st))
        if source == "llm":
            s["llm"] = {"provider": provider, "at": _now()}
            import json
            src = json.dumps({k: v for k, v in self._ctx(st).items() if k != step}, ensure_ascii=False, default=str)
            nums = numbers_not_in(json.dumps(data, ensure_ascii=False, default=str), src)
            if nums:
                s["checks"].append({"level": "warning", "code": "LLM_NUMBERS", "message": "LLM이 쓴 수치 중 입력에 없는 값 — 출처를 확인하세요: " + ", ".join(nums[:15])})
        st["timeline"].append({"step": step, "event": f"{source}_set", "version": s["version"], "by": actor, "at": _now()})
        return s["checks"]

    def _enter(self, st: Dict[str, Any], step: str) -> None:
        """단계에 들어올 때 코드가 만드는 내용(파생 단계 · 추천 후보 · 설계 표 초안 · 회귀 · ANOVA)."""
        ctx = self._ctx(st)
        s = st["steps"][step]
        cq = risk_cqas(ctx["cqa"])
        if step == "rm_matrix":
            self._set(st, step, matrix_of(ctx["rm_just"], cq), source="code", actor="system")
        elif step == "fp_matrix":
            self._set(st, step, matrix_of(ctx["fp_just"], cq), source="code", actor="system")
        elif step == "recommend":         # 5·7의 종합 정리 — 코드가 만든다(DoE 변수를 고르는 단계가 아니다)
            self._set(st, step, {"candidates": candidates(ctx["fp_matrix"]), "watch": watch_list(ctx["fp_matrix"]),
                                 "material_controls": material_controls(ctx["rm_matrix"])}, source="code", actor="system")
        elif step == "design" and s["data"] is None:
            # 요인은 연구자가 정한다(8단계에서 고르지 않는다) — 빈 요인 열 하나로 시작하고, 반응은 High 변수가 걸린 CQA부터
            hi = {}
            for c in (ctx["recommend"] or {}).get("candidates") or []:
                for q in c["high"]:
                    hi[q] = hi.get(q, 0) + 1
            resp = [q for q, _ in sorted(hi.items(), key=lambda kv: -kv[1])][:MAX_RESPONSES] or cq[:1]
            self._set(st, step, {"factors": [{"name": "", "unit": ""}], "responses": [{"name": q, "unit": ""} for q in resp],
                                 "rows": [{"std": 1, "run": 1, "x": [None], "y": [None] * len(resp)}], "note": ""},
                      source="code", actor="system")
        elif step == "regression":
            chosen = {r["response"]: r["family"] for r in (s["data"] or {}).get("responses") or [] if s["source"] and "user" in s["source"]}
            self._set(st, step, _plain(T.regression(ctx["design"], chosen)), source=s["source"] if chosen else "code", actor="system")
        elif step == "surface":
            self._set(st, step, {"responses": [r["response"] for r in ctx["regression"]["responses"] if not r.get("aliased")]}, source="code", actor="system")
        elif step == "anova":
            self._set(st, step, _plain(self._anova(ctx)), source="code", actor="system")
        elif step == "space":
            old = {x["response"]: x for x in ((s["data"] or {}).get("specs") or [])}
            specs = [old.get(r["response"]) or {"response": r["response"], "unit": r.get("unit") or "", "op": "", "lower": None, "upper": None, "basis": ""}
                     for r in ctx["regression"]["responses"] if not r.get("aliased")]
            self._set(st, step, self._space(ctx, specs), source=s["source"] or "code", actor="system")
        elif step == "vplan":
            old = s["data"] or {}
            self._set(st, step, self._vplan(ctx, old.get("delta", SP.ROBUST_DELTA), old.get("reference")), source=s["source"] or "code", actor="system")
        elif step == "verify":
            old = s["data"] or {}
            self._set(st, step, self._verify(ctx, old.get("observations") or [], bool(old.get("independent")), old.get("batches") or {}),
                      source=s["source"] or "code", actor="system")

    def _space(self, ctx, specs) -> Dict[str, Any]:
        specs = [_spec(x) for x in specs]
        ok = any(x["op"] in SP.OPS for x in specs) and all(
            x["op"] not in SP.OPS or all(v is not None for v in ({"LE": [x["upper"]], "GE": [x["lower"]], "BETWEEN": [x["lower"], x["upper"]]}[x["op"]]))
            for x in specs)
        region = _plain(SP.region(ctx["design"], ctx["regression"], specs)) if ok else None
        return {"specs": specs, "region": region}

    def _vplan(self, ctx, delta, reference) -> Dict[str, Any]:
        try:
            delta = min(max(float(delta), 0.0), 1.0)
        except (TypeError, ValueError):
            delta = SP.ROBUST_DELTA
        sp = ctx["space"] or {}
        plan = _plain(SP.plan(ctx["design"], ctx["regression"], sp.get("specs") or [], sp.get("region") or {}, delta=delta, reference=reference))
        return {"delta": delta, "reference": reference, "plan": plan}

    def _verify(self, ctx, observations, independent, batches) -> Dict[str, Any]:
        plan = (ctx["vplan"] or {}).get("plan") or {}
        roles = [p["role"] for p in plan.get("points") or []]
        obs = {o.get("role"): o for o in observations or []}
        observations = [{"role": r, "values": {k: _f(v) for k, v in ((obs.get(r) or {}).get("values") or {}).items()}} for r in roles]
        return {"independent": bool(independent), "batches": {r: str((batches or {}).get(r) or "").strip() for r in roles},
                "observations": observations, "judgement": _plain(SP.judge(plan, observations))}

    def _anova(self, ctx) -> Dict[str, Any]:
        fn, X, rn, Y = T.table_arrays(ctx["design"])
        x = T.to_coded(X, T.coding(X))
        out = []
        for j, r in enumerate(ctx["regression"]["responses"]):
            ok = ~np.isnan(Y[:, j])
            a = T.anova(r["family"], x[ok], Y[ok, j], fn)
            out.append({"response": r["response"], "unit": r.get("unit"), **a})
        return {"responses": out, "factors": fn}

    def _run(self, st, step, p, actor):
        if step != "prototype":
            raise StudyError("'실행'은 1단계(프로토타입)에서만 누릅니다.", status=409)
        return self._approve(st, step, p, actor)

    def _draft(self, st, step, p, actor):
        if step not in LLM_STEPS:
            raise StudyError(f"'{TITLE[step]}'는 LLM이 만들지 않습니다.", status=422)
        ctx = {**self._ctx(st), "handoff": (st.get("source") or {}).get("handoff")}
        try:
            out = AG.draft(step, ctx)
        except AG.LLMUnavailable as exc:
            st["steps"][step]["llm"] = {"provider": None, "error": str(exc)[:200], "at": _now()}
            raise StudyError(f"LLM 응답이 없습니다 — 초안을 만들지 못했습니다. 직접 입력하거나 잠시 후 다시 시도하세요. ({str(exc)[:120]})", status=503)
        data = out["data"]
        checks = self._set(st, step, data, source="llm", actor=actor, provider=out["provider"])
        return {"provider": out["provider"], "blocking": [c["code"] for c in checks if c["level"] == "blocking"]}

    def _use_reference(self, st, step, p, actor):
        if not st.get("reference"):
            raise StudyError("논문 값은 CBD 논문 프로토타입으로 시작한 study에만 있습니다.", status=422)
        if step == "regression":
            data = _plain(T.regression(self._ctx(st)["design"], REF.PAPER_FAMILIES))
        elif step == "space":
            ctx = self._ctx(st)
            paper = REF.specs()
            data = self._space(ctx, [paper.get(r["response"]) or {"response": r["response"], "unit": r.get("unit") or "", "op": ""}
                                     for r in ctx["regression"]["responses"] if not r.get("aliased")])
        elif step == "vplan":
            ctx = self._ctx(st)
            data = self._vplan(ctx, (st["steps"]["vplan"]["data"] or {}).get("delta", SP.ROBUST_DELTA), REF.reference_point())
        else:
            data = REF.step(step)
            if data is None:
                raise StudyError(f"'{TITLE[step]}'에는 논문 값이 없습니다.", status=422)
            data = copy.deepcopy(data)
        checks = self._set(st, step, data, source="paper", actor=actor)
        return {"blocking": [c["code"] for c in checks if c["level"] == "blocking"]}

    def _save(self, st, step, p, actor):
        if step not in EDITABLE:
            raise StudyError(f"'{TITLE[step]}'는 앞 단계에서 코드가 만든 정리입니다 — 고치려면 앞 단계를 다시 여세요.", status=409)
        data = p.get("data")
        if not isinstance(data, dict):
            raise StudyError("저장할 내용이 없습니다.", status=422)
        if step == "regression":
            chosen = {k: v for k, v in (data.get("chosen") or {}).items() if v in T.FAMILIES}
            norm = _plain(T.regression(self._ctx(st)["design"], chosen))
        elif step == "space":
            norm = self._space(self._ctx(st), data.get("specs") or [])
        elif step == "vplan":
            ref = data.get("reference")
            ref = ({"label": str(ref.get("label") or "참고 배치")[:80], "settings": {str(k): _f(v) for k, v in (ref.get("settings") or {}).items()}}
                   if isinstance(ref, dict) and any(_f(v) is not None for v in (ref.get("settings") or {}).values()) else None)
            norm = self._vplan(self._ctx(st), data.get("delta", SP.ROBUST_DELTA), ref)
        elif step == "verify":
            norm = self._verify(self._ctx(st), data.get("observations") or [], bool(data.get("independent")), data.get("batches") or {})
        else:
            norm = _normalize(step, data)
        checks = self._set(st, step, norm, source="user", actor=actor)
        return {"blocking": [c["code"] for c in checks if c["level"] == "blocking"]}

    def _approve(self, st, step, p, actor):
        s = st["steps"][step]
        if s["data"] is None:
            raise StudyError("승인할 내용이 없습니다 — 초안을 만들거나 입력하세요.", status=409)
        s["checks"] = check(step, s["data"], self._ctx(st)) + [c for c in s["checks"] if c["code"] == "LLM_NUMBERS"]
        blocking = [c for c in s["checks"] if c["level"] == "blocking"]
        note = (p.get("note") or "").strip()
        if step == "regression" and any(c["code"] == "REG_OVERFIT" for c in s["checks"]) and not note:
            s["checks"].append({"level": "blocking", "code": "REG_OVERFIT_REASON",
                                "message": "과적합 의심 모형을 그대로 쓰려면 수용 사유를 적어 주세요(또는 차수를 낮추세요)."})
            blocking = [c for c in s["checks"] if c["level"] == "blocking"]
        if blocking:
            return {"blocked": [c["code"] for c in blocking]}
        if step == "vplan":            # 승인 = 결과 전에 확인계획을 잠근다(잠근 뒤에는 다시 열어야만 바뀐다)
            s["data"]["locked_at"] = _now()
            s["data"]["plan_hash"] = hashlib.sha256(json.dumps(s["data"]["plan"], sort_keys=True, default=str).encode()).hexdigest()[:16]
        s["status"] = "approved"
        st["approvals"].append({"step": step, "version": s["version"], "source": s["source"], "by": actor, "at": _now(),
                                "note": (p.get("note") or "").strip() or None})
        i = STEPS.index(step)
        nxt = next((x for x in STEPS[i + 1:] if st["steps"][x]["status"] != "approved"), None)
        st["status"] = nxt or "done"
        st["timeline"].append({"step": step, "event": "approved", "version": s["version"], "by": actor, "at": _now()})
        if nxt:
            if nxt in DERIVED or nxt in ("design", "regression", "space", "vplan", "verify"):
                try:
                    self._enter(st, nxt)
                except (ValueError, np.linalg.LinAlgError) as exc:
                    st["steps"][nxt]["checks"] = [{"level": "blocking", "code": "COMPUTE", "message": f"계산하지 못했습니다: {exc}"}]
            elif st["steps"][nxt]["data"] is not None:
                st["steps"][nxt]["checks"] = check(nxt, st["steps"][nxt]["data"], self._ctx(st))
        return {"next": st["status"]}

    def _reopen(self, st, step, p, actor):
        if step not in STEPS or st["steps"][step]["status"] != "approved":
            raise StudyError("승인한 단계만 다시 열 수 있습니다.", status=409)
        i = STEPS.index(step)
        st["steps"][step]["status"] = "draft"
        for later in STEPS[i + 1:]:
            if st["steps"][later]["status"] in ("approved", "draft"):
                st["steps"][later]["status"] = "stale" if st["steps"][later]["data"] is not None else "empty"
        st["status"] = step
        if step in DERIVED or step in ("regression", "space", "vplan"):
            self._enter(st, step)
        if step == "vplan" and st["steps"]["vplan"]["data"]:
            st["steps"]["vplan"]["data"].pop("locked_at", None)
        st["timeline"].append({"step": step, "event": "reopened", "by": actor, "at": _now(), "reason": p.get("reason")})
        return {}

    def _attach_images(self, st, step, p, actor):
        if step != "surface":
            raise StudyError("곡면 그림은 11단계에서 붙입니다.", status=409)
        imgs = {}
        for k, v in (p.get("images") or {}).items():
            if not isinstance(v, str) or not v.startswith("data:image/png;base64,"):
                continue
            raw = v.split(",", 1)[1]
            if len(raw) * 3 // 4 > MAX_IMAGE_BYTES:
                continue
            imgs[str(k)[:40]] = raw
        st["images"] = dict(list(imgs.items())[:12])
        return {"images": len(st["images"])}

    def _reference(self, st) -> Dict[str, Any]:
        cq = REF.risk()["cqa"]["risk_order"]
        ref = {s: REF.step(s) for s in ("prototype", "qtpp", "cqa", "rm_just", "fp_just", "design")}
        ref["rm_matrix"] = matrix_of(ref["rm_just"], cq)
        ref["fp_matrix"] = matrix_of(ref["fp_just"], cq)
        ref["recommend"] = {"doe_factors": REF.PAPER_DOE_VARIABLES}   # 참고: 논문이 DoE 요인으로 쓴 변수(선택 단계는 없다)
        ref["regression"] = {"families": REF.PAPER_FAMILIES}
        return ref


def _plain(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, np.ndarray):
        return _plain(x.tolist())
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if np.isfinite(v) else None
    return x


def _f(v) -> Optional[float]:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _spec(x: Dict[str, Any]) -> Dict[str, Any]:
    op = str(x.get("op") or "").upper()
    op = op if op in SP.OPS else ""
    return {"response": str(x.get("response") or ""), "unit": str(x.get("unit") or ""), "op": op,
            "lower": _f(x.get("lower")) if op in ("GE", "BETWEEN") else None, "upper": _f(x.get("upper")) if op in ("LE", "BETWEEN") else None,
            "basis": str(x.get("basis") or "").strip()[:300]}


def _normalize(step: str, d: Dict[str, Any]) -> Dict[str, Any]:
    """폼 값 → 저장 모양. 알 수 없는 키는 버린다."""
    txt = lambda v: str(v if v is not None else "").strip()  # noqa: E731
    if step == "prototype":
        ings = [{"name": txt(i.get("name")), "mg": _f(i.get("mg")), "pct": _f(i.get("pct")), "function": txt(i.get("function")),
                 "role": txt(i.get("role")) or "excipient"} for i in d.get("ingredients") or [] if txt(i.get("name"))]
        return {"api": txt(d.get("api")), "dosage_form": txt(d.get("dosage_form")), "route": txt(d.get("route")), "process": txt(d.get("process")),
                "strength_mg": _f(d.get("strength_mg")), "unit_weight_mg": _f(d.get("unit_weight_mg")),
                "process_steps": [txt(x) for x in d.get("process_steps") or [] if txt(x)], "ingredients": ings, "source": d.get("source")}
    if step == "qtpp":
        return {"items": [{"element": txt(i.get("element")), "sub_element": txt(i.get("sub_element")) or None, "target": txt(i.get("target")),
                           "justification": txt(i.get("justification")), "basis": txt(i.get("basis")) or None}
                          for i in d.get("items") or [] if txt(i.get("element")) or txt(i.get("target"))]}
    if step == "cqa":
        return {"items": [{"category": txt(i.get("category")), "attribute": txt(i.get("attribute")), "short": txt(i.get("short")) or txt(i.get("attribute")),
                           "target": txt(i.get("target")), "is_cqa": bool(i.get("is_cqa")), "justification": txt(i.get("justification")),
                           "in_risk_assessment": bool(i.get("in_risk_assessment")), "exclusion_reason": txt(i.get("exclusion_reason")) or None,
                           "basis": txt(i.get("basis")) or None} for i in d.get("items") or [] if txt(i.get("attribute"))]}
    if step in ("rm_just", "fp_just"):
        kinds = ("material",) if step == "rm_just" else ("formulation", "process")
        vars_ = [{"name": txt(v.get("name")), "kind": v.get("kind") if v.get("kind") in kinds else kinds[0]} for v in d.get("variables") or [] if txt(v.get("name"))]
        return {"variables": vars_,
                "items": [{"variable": txt(i.get("variable")), "cqas": [txt(c) for c in i.get("cqas") or [] if txt(c)],
                           "level": i.get("level") if i.get("level") in ("High", "Medium", "Low") else None, "text": txt(i.get("text")),
                           "basis": txt(i.get("basis")) or None} for i in d.get("items") or [] if txt(i.get("variable"))]}
    if step == "design":
        f = [{"name": txt(x.get("name")), "unit": txt(x.get("unit"))} for x in (d.get("factors") or [])[:MAX_FACTORS]]
        r = [{"name": txt(x.get("name")), "unit": txt(x.get("unit"))} for x in (d.get("responses") or [])[:MAX_RESPONSES]]
        rows = []
        for n, row in enumerate(d.get("rows") or []):
            x = [_f(v) for v in (row.get("x") or [])][:len(f)] + [None] * max(0, len(f) - len(row.get("x") or []))
            y = [_f(v) for v in (row.get("y") or [])][:len(r)] + [None] * max(0, len(r) - len(row.get("y") or []))
            if all(v is None for v in x + y):
                continue
            rows.append({"std": _f(row.get("std")) if _f(row.get("std")) is not None else n + 1, "run": _f(row.get("run")) if _f(row.get("run")) is not None else n + 1,
                         "x": x, "y": y})
        return {"factors": f, "responses": r, "rows": rows}
    return d


__all__ = ["Stage2Service", "StudyError", "VersionConflict"]
