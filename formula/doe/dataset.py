"""DoE 데이터셋 — run 단위 실험 데이터를 가진 어떤 DoE든 같은 study 흐름으로 넣는 공통 형식.

CBD ODT 문헌 재현은 이 형식의 한 사례일 뿐이다(`from_cbd_fixture`). 연구실의 선행 batch, 외부 원자료, 문헌 표 모두
같은 스키마로 들어오고, study는 같은 단계(CQA → FMEA → 요인 → 범위 → 실험표 → 결과 → 모델 → 영역 → 확인)를 거친다.

데이터셋이 하는 일은 두 가지뿐이다.
1. **handoff 원천** — 처방·공정·설비(없으면 비워 두고 RB01이 요청).
2. **폼 채우기 원천** — 각 단계 폼에 데이터셋 값을 넣는다. 제출·승인은 연구자가 누른다. 판정은 룰북이 한다.

데이터셋에 없는 값은 만들지 않는다. 예: FMEA 점수가 없으면 비워 둔다, 확인 역할이 SETPOINT 하나뿐이면 그대로 두고 VR001이 막는다.

스키마(요지) — 전체 설명은 `SCHEMA_DOC`:
  title, source{citation, doi, locator}, study_type(NEW_API|LITERATURE_REPLAY), result_evidence_status,
  formulation{dosage_form, cqa_dosage_form, unit_weight_mg, ingredients[{material, function, pct, mg, grade, is_api}],
              route, steps[], equipment, batch_scale{}, fixed_parameters[{name, value, unit, locator}]},
  factors[{id, name, key(FMEA 후보 요인), unit, quantity_kind, low, center, high, kind(CPP|CMA), material, reference_value,
           evidence_status, refs[]}]  (1–3개),
  responses[{id, name, cqa_id, unit, operator(LE|GE|BETWEEN|TARGET_TOL), lower, upper, target, tolerance, test_method_id,
             test_method_version, summary, replicate_policy, is_cqa, refs[]}]  (1–4개),
  runs[{label, batch_id, blend_id, factors{factor_id: 실제값}, responses{response_id: 값}}],
  reported_models{response_id: {terms[], locator}}  (선택 — 보고된 항 구성으로 같은 원자료를 재적합해 비교),
  verification{points[{role, factors{}, batch_id, blend_id, lots{response_id: [값…]}, evidence_status}]}  (선택)
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from formula.doe import design as D
from formula.doe.package import DoePackage

OPERATORS = ("LE", "GE", "BETWEEN", "TARGET_TOL")
STUDY_TYPES = ("NEW_API", "LITERATURE_REPLAY")
RESULT_EVIDENCE = ("MEASURED_IN_STUDY", "MEASURED_PRIOR_BATCH", "LITERATURE_DIRECT", "VERIFIED_EXTERNAL_DATA", "LITERATURE_DIGITIZED")
RANGE_EVIDENCE = ("MEASURED_PRIOR_BATCH", "VERIFIED_EXTERNAL_DATA", "REPORTED_NO_RAW_DATA", "EXPERT_PROPOSAL", "UNVERIFIED_PROPOSAL")
MAX_FACTORS, MAX_RESPONSES, MAX_RUNS = 3, 4, 200

SCHEMA_DOC = __doc__


class DatasetError(ValueError):
    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def fmea_factor_keys(pkg: DoePackage) -> List[str]:
    keys = set()
    for r in pkg.rows("RB04"):
        keys |= {k for k in (r.get("candidate_factor") or "").split(";") if k and k != "—"}
    return sorted(keys)


def _num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def validate(pkg: DoePackage, ds: Dict[str, Any]) -> Dict[str, Any]:
    """구조 검사만 한다(판정은 룰북 몫). 반환: 정규화된 데이터셋. 오류가 있으면 DatasetError(모든 오류 목록)."""
    err: List[str] = []
    if not isinstance(ds, dict):
        raise DatasetError(["데이터셋은 JSON 객체여야 합니다."])
    out = json.loads(json.dumps(ds))            # 사본
    if not str(out.get("title") or "").strip():
        err.append("title이 없습니다.")
    src = out.get("source") or {}
    if not str(src.get("citation") or src.get("locator") or "").strip():
        err.append("source.citation(또는 locator)이 없습니다 — 출처 없는 데이터는 받지 않습니다.")
    out.setdefault("study_type", "NEW_API")
    if out["study_type"] not in STUDY_TYPES:
        err.append(f"study_type은 {', '.join(STUDY_TYPES)} 중 하나입니다.")
    out.setdefault("result_evidence_status", "LITERATURE_DIRECT" if out["study_type"] == "LITERATURE_REPLAY" else "MEASURED_PRIOR_BATCH")
    if out["result_evidence_status"] not in RESULT_EVIDENCE:
        err.append(f"result_evidence_status는 {', '.join(RESULT_EVIDENCE)} 중 하나입니다.")
    keys = set(fmea_factor_keys(pkg))
    fac = out.get("factors") or []
    if not 1 <= len(fac) <= MAX_FACTORS:
        err.append(f"요인은 1–{MAX_FACTORS}개입니다(현재 {len(fac)}).")
    fids = []
    for n, f in enumerate(fac, 1):
        f.setdefault("id", f"X{n}")
        fids.append(f["id"])
        tag = f"요인 {f['id']}"
        if f.get("key") not in keys:
            err.append(f"{tag}: key '{f.get('key')}'는 FMEA 후보 요인이 아닙니다({', '.join(sorted(keys))}).")
        for k in ("low", "center", "high"):
            f[k] = _num(f.get(k))
            if f[k] is None:
                err.append(f"{tag}: {k} 숫자가 없습니다.")
        if None not in (f["low"], f["center"], f["high"]) and not f["low"] < f["center"] < f["high"]:
            err.append(f"{tag}: low < center < high 이어야 합니다.")
        if not f.get("unit"):
            err.append(f"{tag}: unit이 없습니다.")
        f.setdefault("kind", "CMA" if f.get("material") else "CPP")
        if f.get("evidence_status") and f["evidence_status"] not in RANGE_EVIDENCE:
            err.append(f"{tag}: evidence_status는 {', '.join(RANGE_EVIDENCE)} 중 하나입니다.")
    if len(set(fids)) != len(fids):
        err.append("요인 id가 겹칩니다.")
    if len({f.get("key") for f in fac}) != len(fac):
        err.append("같은 FMEA 요인(key)을 두 번 쓸 수 없습니다.")
    resp = out.get("responses") or []
    if not 1 <= len(resp) <= MAX_RESPONSES:
        err.append(f"반응은 1–{MAX_RESPONSES}개입니다(현재 {len(resp)}).")
    rids = []
    for r in resp:
        tag = f"반응 {r.get('id')}"
        if not r.get("id") or not r.get("cqa_id"):
            err.append(f"{tag}: id와 cqa_id(RB02 CQA 템플릿)가 필요합니다.")
        rids.append(r.get("id"))
        if r.get("operator") not in OPERATORS:
            err.append(f"{tag}: operator는 {', '.join(OPERATORS)} 중 하나입니다.")
        for k in ("lower", "upper", "target", "tolerance"):
            if k in r:
                r[k] = _num(r[k])
    if len(set(rids)) != len(rids) or len({r.get("cqa_id") for r in resp}) != len(resp):
        err.append("반응 id·cqa_id가 겹칩니다.")
    runs = out.get("runs") or []
    k = len(fac)
    need = (k + 1) * (k + 2) // 2 + 1 if k else 0
    if not need <= len(runs) <= MAX_RUNS:
        err.append(f"run은 {need}–{MAX_RUNS}개여야 합니다(2차 모형 항 수 + 잔차 자유도 1, 현재 {len(runs)}).")
    for n, run in enumerate(runs, 1):
        run.setdefault("label", f"run {n}")
        fv = run.get("factors") or {}
        for fid in fids:
            v = _num(fv.get(fid))
            if v is None:
                err.append(f"{run['label']}: 요인 {fid} 값이 없습니다.")
            else:
                fv[fid] = v
                f = next(x for x in fac if x["id"] == fid)
                if None not in (f["low"], f["high"]) and not f["low"] - 1e-9 <= v <= f["high"] + 1e-9:
                    err.append(f"{run['label']}: {fid}={v}는 범위 {f['low']}–{f['high']} 밖입니다.")
        run["factors"] = fv
        rv = run.get("responses") or {}
        for rid in rids:
            v = _num(rv.get(rid))
            if v is None:
                err.append(f"{run['label']}: 반응 {rid} 값이 없습니다.")
            rv[rid] = v
        run["responses"] = rv
    for rid, m in (out.get("reported_models") or {}).items():
        if rid not in rids:
            err.append(f"reported_models: 없는 반응 {rid}")
        for t in m.get("terms", []):
            if any(p not in fids for p in t.replace("^2", "").split(":")):
                err.append(f"reported_models {rid}: 항 {t}의 요인이 factors에 없습니다.")
    if err:
        raise DatasetError(err[:40])
    return out


# ── handoff ─────────────────────────────────────────────────────────────────
def handoff(ds: Dict[str, Any], actor: str) -> Dict[str, Any]:
    from formula.doe import handoff as H
    fm = ds.get("formulation") or {}
    src = ds.get("source") or {}
    ings = []
    for i in fm.get("ingredients") or []:
        ings.append({"material_id": i["material"], "material_grade": i.get("grade"), "function": i.get("function") or "other",
                     "amount_mg": _num(i.get("mg")), "percent_w_w": _num(i.get("pct")), "unit": "mg" if i.get("mg") is not None else ("%w/w" if i.get("pct") is not None else None),
                     "value_role": "REFERENCE_PROTOTYPE", "is_critical": bool(i.get("is_api")),
                     "evidence_ref": i.get("locator") or src.get("locator") or src.get("citation")})
    h = {"handoff_id": f"HO-DS-{H.fingerprint_text(ds.get('title', ''))[:10]}", "project_id": "DATASET",
         "candidate_id": ds.get("candidate_id") or "DATASET", "candidate_version": int(ds.get("candidate_version") or 1),
         "dosage_form": fm.get("dosage_form") or "tablet", "cqa_dosage_form": fm.get("cqa_dosage_form") or fm.get("dosage_form") or "tablet",
         "target_strength_mg": next((_num(i.get("mg")) for i in fm.get("ingredients") or [] if i.get("is_api")), None),
         "unit_weight_mg": _num(fm.get("unit_weight_mg")), "batch_scale": fm.get("batch_scale") or None, "ingredients": ings,
         "process_route_id": H.route_of(fm.get("route") or ""),
         "process_steps": [{"order": k + 1, "text": s} for k, s in enumerate(fm.get("steps") or [])],
         "equipment_id": fm.get("equipment") or None, "fixed_parameters": [dict(p) for p in fm.get("fixed_parameters") or []],
         "unresolved_fields": [], "rule_verdicts": [], "qtpp_snapshot_id": f"QTPP-DS-{src.get('doi') or src.get('locator') or 'dataset'}",
         "evidence_snapshot_id": f"EV-DS-{src.get('pmcid') or src.get('doi') or 'dataset'}", "source": src,
         "title": ds["title"], "created_by": actor, "created_at": H.now()}
    h["formulation_fingerprint"] = H.fingerprint(h)
    return h


# ── 요인 대응 — 화면에서 고른 순서와 무관하게 FMEA key로 맞춘다(위치로 맞추지 않는다) ─────────────
def by_key(st: Dict[str, Any], ds: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    k2f = {f["key"]: f for f in ds["factors"]}
    return {fid: k2f[f["key"]] for fid, f in st["factors"].items() if f.get("key") in k2f}


def _resp_by_cqa(ds: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {r["cqa_id"]: r for r in ds["responses"]}


def _study_value_key(st: Dict[str, Any], r: Dict[str, Any]) -> str:
    c = st["cqas"].get(r["cqa_id"]) or {}
    return c.get("response_key") or r["id"]


def _match_runs(st: Dict[str, Any], ds: Dict[str, Any], plan_runs: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """계획 run ↔ 데이터셋 run을 요인 실제값으로 짝짓는다(같은 점이 여럿이면 순서대로). 반환: {run_id: ds_run}, 짝 없는 run_id."""
    bk = by_key(st, ds)
    pool = list(ds["runs"])
    tol = {fid: 1e-6 * max(abs(st["factors"][fid]["high"] - st["factors"][fid]["low"]), 1e-9) for fid in bk}
    out, miss = {}, []
    for r in plan_runs:
        k = next((i for i, dr in enumerate(pool) if all(abs(dr["factors"][f["id"]] - r["actual"][fid]) <= tol[fid] for fid, f in bk.items())), None)
        if k is None:
            miss.append(r["run_id"])
        else:
            out[r["run_id"]] = pool.pop(k)
    return out, miss


def fill(st: Dict[str, Any], action: str) -> Optional[Dict[str, Any]]:
    """지금 단계 폼에 넣을 값. 데이터셋이 없는 study(① 후보에서 연 신규 API)는 None — 가짜 값 금지."""
    ds = st.get("dataset")
    if not ds:
        return None
    src = ds.get("source") or {}
    cite = src.get("citation") or src.get("locator") or ""
    if action == "cqa_edit":
        mapped = _resp_by_cqa(ds)
        edits = []
        for cid, r in mapped.items():
            edits.append({"cqa_id": cid, "analysis_role": "DOE_RESPONSE", "response_key": r["id"], "unit": r.get("unit"),
                          "acceptance_operator": r["operator"], "lower": r.get("lower"), "upper": r.get("upper"),
                          "target": r.get("target"), "target_tolerance": r.get("tolerance"),
                          "test_method_id": r.get("test_method_id"), "test_method_version": r.get("test_method_version"),
                          "summary_definition": r.get("summary"), "replicate_policy": r.get("replicate_policy"),
                          "criterion_source": r.get("criterion_source") or ("LITERATURE" if ds["study_type"] == "LITERATURE_REPLAY" else None),
                          "evidence_refs": r.get("refs") or ([cite] if cite else []), "is_cqa": bool(r.get("is_cqa", True))})
        for cid in st["cqas"]:
            if cid not in mapped:
                edits.append({"cqa_id": cid, "analysis_role": "NOT_APPLICABLE", "acceptance_operator": None,
                              "rationale": "데이터셋 범위 밖 — 이 반응의 run 데이터가 없다"})
        return {"edits": edits, "note": f"반응·기준·시험법은 데이터셋({cite})에서 옮겼습니다. 비어 있는 칸은 데이터셋에 없는 값입니다."}
    if action == "fmea_edit":
        rows = ds.get("fmea") or []
        return {"rows": rows, "note": "데이터셋에 FMEA 점수가 없어 비워 둡니다 — 발생도는 UNKNOWN(RPN 없음)." if not rows else "FMEA 값은 데이터셋에서 옮겼습니다."}
    if action == "factor_select":
        return {"selected": [{"key": f["key"], "name": f["name"], "kind": f.get("kind", "CMA"), "material_id": f.get("material")} for f in ds["factors"]],
                "fixed": ds.get("fixed_factors") or [], "note": "요인은 데이터셋의 factors."}
    if action == "range_submit":
        out = []
        for fid, f in sorted(by_key(st, ds).items()):
            ev = f.get("evidence_status")
            out.append({"factor_id": fid, "unit": f["unit"], "quantity_kind": f.get("quantity_kind"), "low": f["low"], "center": f["center"],
                        "high": f["high"], "evidence_status": {b: ev for b in ("low", "center", "high")} if ev else {},
                        "range_evidence_refs": f.get("refs") or ([cite] if cite else []), "applicability_confirmed": bool(f.get("applicability_confirmed"))})
        return {"factors": out, "note": "범위·근거 등급은 데이터셋에서 옮겼습니다."}
    if action == "plan_approve":
        p = ds.get("protocol") or {}
        return {"sampling_plan": p.get("sampling_plan") or " / ".join(f"{r['id']}: {r['replicate_policy']}" for r in ds["responses"] if r.get("replicate_policy")),
                "stop_criteria": p.get("stop_criteria") or ("문헌 재현 — 실행하지 않음(보고된 run 결과를 입력)" if ds["study_type"] == "LITERATURE_REPLAY" else ""),
                "balance_material": (st.get("run_sheet") or {}).get("balance_material"),
                "note": "샘플링은 데이터셋 시험 조건. 중단 기준이 데이터셋에 없으면 연구자가 적습니다."}
    if action == "plan_import":
        bk = by_key(st, ds)
        return {"runs": [{"actual": {fid: run["factors"][f["id"]] for fid, f in bk.items()}, "label": run["label"]} for run in ds["runs"]],
                "source": f"{cite} — 실행된 설계 행렬",
                "note": "데이터셋의 실행 행렬로 계획을 바꿉니다(같은 Validator로 다시 검사)."}
    if action == "results_submit":
        plan = st["plans"][st["active_plan"]]
        pairs, miss = _match_runs(st, ds, plan["runs"])
        rows = []
        for r in plan["runs"]:
            dr = pairs.get(r["run_id"])
            if not dr:
                continue
            rows.append({"run_id": r["run_id"], "batch_id": dr.get("batch_id") or dr["label"], "parent_blend_id": dr.get("blend_id") or dr.get("batch_id") or dr["label"],
                         "test_method_version": dr.get("test_method_version") or ds.get("test_method_version") or "as reported",
                         "replicate_independence": dr.get("replicate_independence") or "INDEPENDENT_BATCH",
                         "evidence_status": ds["result_evidence_status"], "source_locator": dr["label"],
                         "values": {_study_value_key(st, resp): dr["responses"][resp["id"]] for resp in ds["responses"]}})
        note = "값은 데이터셋 run. 설계 run과 데이터셋 run은 요인 실제값으로 짝지었습니다."
        if miss:
            note += f" 짝이 없는 계획 run {len(miss)}개 — 데이터셋의 실행 행렬이 표준 설계와 다르면 실험표 단계에서 '실행 행렬 가져오기'를 쓰세요."
        return {"rows": rows, "unmatched": miss, "note": note}
    if action == "model_accept_flags":
        flags = sorted({f["rule_id"] for m in st["models"].values() if m["status"] == "VALID_WITH_FLAGS" for f in m["gate"]["flags"]})
        return {"rationale": f"플래그({', '.join(flags)})를 확인했고, 잠근 기준(p_min)으로 영역을 계산해 본다",
                "note": "사유 문장은 초안입니다. 플래그 내용을 읽고 고치거나 그대로 승인하세요."}
    if action in ("vplan_lock", "verification_submit"):
        pts = (ds.get("verification") or {}).get("points") or []
        if not pts:
            return {"note": "데이터셋에 확인점이 없습니다 — 제안점을 검토하거나 직접 입력하세요."}
        bk = by_key(st, ds)
        fs = {fid: st["factors"][fid] for fid in bk}
        from formula.doe.service import _fs
        if action == "vplan_lock":
            return {"points": [{"role": p["role"], "coded": {fid: D.to_coded(p["factors"][f["id"]], _fs({"factor_id": fid, **fs[fid]}))
                                                              for fid, f in bk.items()}} for p in pts],
                    "note": f"확인점은 데이터셋에서 옮겼습니다(역할 {', '.join(p['role'] for p in pts)})."}
        return {"points": [{"role": p["role"], "batch_id": p.get("batch_id"), "parent_blend_id": p.get("blend_id"),
                            "evidence_status": p.get("evidence_status") or ds["result_evidence_status"],
                            "values": {_study_value_key(st, r): p["lots"].get(r["id"], []) for r in ds["responses"]}} for p in pts],
                "note": "확인 lot은 데이터셋에서 옮겼습니다. 근거 등급이 확인 용도로 허용되는지는 M05가 판정합니다."}
    if action == "revise":
        cur = (st.get("labloop") or {}).get("current") or {}
        return {"reason": f"{cur.get('observed_pattern', '')} — {cur.get('reason_code', '')}로 재검토",
                "tests": [t["test_id"] for t in cur.get("tests", [])], "note": "사유 문장은 초안입니다. 판별시험은 RB18 제안을 모두 골라 두었습니다."}
    return {}


def reported_terms(st: Dict[str, Any]) -> Optional[Dict[str, List[str]]]:
    """보고된 모형 항 구성(데이터셋 reported_models)을 study 요인 ID로 옮긴다 — 계수는 베끼지 않고 같은 원자료에 재적합한다."""
    ds = st.get("dataset")
    if not ds or not ds.get("reported_models"):
        return None
    ren = {f["id"]: fid for fid, f in by_key(st, ds).items()}
    r2c = {r["id"]: r["cqa_id"] for r in ds["responses"]}

    def tr(t: str) -> str:
        if t.endswith("^2"):
            return ren[t[:-2]] + "^2"
        if ":" in t:
            a, b = sorted(ren[p] for p in t.split(":"))
            return f"{a}:{b}"
        return ren[t]
    return {r2c[rid]: ["1"] + [tr(t) for t in m["terms"]] for rid, m in ds["reported_models"].items() if rid in r2c}


# ── 결과 CSV — 어떤 study든 run 단위 결과를 붙여 넣는다 ─────────────────────────────
META = {"batch_id": "batch_id", "batch": "batch_id", "parent_blend_id": "parent_blend_id", "blend_id": "parent_blend_id", "blend": "parent_blend_id",
        "test_method_version": "test_method_version", "method_version": "test_method_version",
        "replicate_independence": "replicate_independence", "evidence_status": "evidence_status"}


def parse_results_csv(st: Dict[str, Any], text: str) -> Dict[str, Any]:
    """머리행: run_id(선택) · 요인(ID 또는 이름) · 반응(response_key·CQA ID·이름) · batch_id·blend_id 등.
    run_id가 없으면 요인 실제값으로 계획 run에 짝짓는다. 반환은 results_submit 폼 값 — 제출하지 않는다."""
    plan = st["plans"][st["active_plan"]]
    try:
        rows = list(csv.DictReader(io.StringIO(text.strip()), delimiter="\t" if "\t" in text.split("\n", 1)[0] else ","))
    except csv.Error as exc:
        raise DatasetError([f"CSV를 읽지 못했습니다: {exc}"])
    if not rows:
        raise DatasetError(["CSV에 데이터 행이 없습니다."])
    norm = lambda s: (s or "").strip().lower().replace(" ", "")  # noqa: E731
    head = {norm(h): h for h in rows[0].keys()}
    fcol = {}
    for fid, f in st["factors"].items():
        h = head.get(norm(fid)) or head.get(norm(f.get("name")))
        if h:
            fcol[fid] = h
    rcol = {}
    for cid, c in st["cqas"].items():
        if c.get("analysis_role") != "DOE_RESPONSE":
            continue
        key = c.get("response_key") or cid
        h = head.get(norm(key)) or head.get(norm(cid)) or head.get(norm(c.get("name")))
        if h:
            rcol[key] = h
    need = [c.get("response_key") or cid for cid, c in st["cqas"].items() if c.get("analysis_role") == "DOE_RESPONSE"]
    errs = [f"반응 열 '{k}'가 없습니다." for k in need if k not in rcol]
    run_col = head.get("run_id") or head.get("run")
    if not run_col and len(fcol) < len(st["factors"]):
        errs.append("run_id 열이 없으면 모든 요인 열(ID 또는 이름)이 있어야 계획 run에 짝지을 수 있습니다.")
    if errs:
        raise DatasetError(errs)
    by_id = {r["run_id"]: r for r in plan["runs"]}
    free = list(plan["runs"])
    out, unmatched = [], []
    for n, row in enumerate(rows, 1):
        target = None
        if run_col and (row.get(run_col) or "").strip() in by_id:
            target = by_id[row[run_col].strip()]
        elif fcol:
            vals = {fid: _num(row.get(h)) for fid, h in fcol.items()}
            tol = {fid: 1e-6 * max(abs(st["factors"][fid]["high"] - st["factors"][fid]["low"]), 1e-9) for fid in fcol}
            target = next((r for r in free if all(vals[fid] is not None and abs(vals[fid] - r["actual"][fid]) <= tol[fid] for fid in fcol)), None)
        if target is None or target not in free:
            unmatched.append(n)
            continue
        free.remove(target)
        item = {"run_id": target["run_id"], "values": {k: _num(row.get(h)) for k, h in rcol.items()}}
        for h, v in row.items():
            m = META.get(norm(h))
            if m and (v or "").strip():
                item[m] = v.strip()
        out.append(item)
    return {"rows": out, "unmatched_csv_rows": unmatched, "runs_without_data": [r["run_id"] for r in free],
            "note": f"CSV {len(rows)}행 중 {len(out)}행을 계획 run에 짝지었습니다."
                    + (f" 짝 없는 CSV 행: {unmatched}." if unmatched else "") + (f" 값이 없는 run {len(free)}개." if free else "")}


# ── CBD ODT(Monton 2026) — 공통 형식의 한 사례 ────────────────────────────────────
CBD_FACTOR = {"X1": ("compression_force", None, "CPP", "pressure"), "X2": ("filler_ratio", "MCC", "CMA", "fraction_mass"),
              "X3": ("disintegrant_pct", "CCS", "CMA", "fraction_mass")}
CBD_RESPONSE = {"hardness_kgf": ("CQA_BREAKING_FORCE", "TM_BREAK_USP1217", "MEAN"), "dt_s": ("CQA_DISINTEGRATION", "TM_DISINT_USP701", "MEAN"),
                "friability_pct": ("CQA_FRIABILITY", "TM_FRIAB_USP1216", "PERCENT_WEIGHT_LOSS")}


def from_cbd_fixture(fx: Dict[str, Any]) -> Dict[str, Any]:
    cite = f"{fx['citation'].split(';')[0]} (doi:{fx['doi']})"
    pr = fx["process"]
    ev = fx["range_evidence"]
    key_of = {"X1": "force_psi", "X2": "mcc_pct", "X3": "ccs_pct"}
    return {
        "title": "CBD 구강붕해정 — Monton 2026 문헌 재현", "candidate_id": "CBD_ODT_PROTOTYPE",
        "source": {"citation": fx["citation"], "doi": fx["doi"], "pmcid": fx["pmcid"], "locator": f"{fx['prototype_table']} · {fx['runs_table']}"},
        "study_type": "LITERATURE_REPLAY", "result_evidence_status": "LITERATURE_DIRECT",
        "formulation": {"dosage_form": "odt", "cqa_dosage_form": "tablet", "unit_weight_mg": 250,
                        "ingredients": [{"material": i["material"], "function": i["function"], "mg": i["mg"], "pct": i["pct"], "grade": i.get("grade"),
                                         "is_api": i["function"] == "API", "locator": f"{fx['doi']} {fx['prototype_table']}"} for i in fx["prototype"]],
                        "route": pr["route"], "steps": pr["steps_as_reported"], "equipment": pr["equipment"], "batch_scale": pr["batch_scale"],
                        "fixed_parameters": pr["fixed_parameters"]},
        "factors": [{"id": f["id"], "name": f["name"], "key": CBD_FACTOR[f["id"]][0], "material": CBD_FACTOR[f["id"]][1], "kind": CBD_FACTOR[f["id"]][2],
                     "unit": f["unit"], "quantity_kind": CBD_FACTOR[f["id"]][3], "low": f["low"], "center": f["center"], "high": f["high"],
                     "reference_value": f.get("reference_value"), "evidence_status": ev["prior_study_status"],
                     "refs": [f"{cite} {ev['source_locator']}"]} for f in fx["factors"]],
        "responses": [{"id": r["id"], "name": r["name"], "cqa_id": CBD_RESPONSE[r["id"]][0], "unit": r["unit"], "operator": r["operator"],
                       "lower": r.get("lower"), "upper": r.get("upper"), "test_method_id": CBD_RESPONSE[r["id"]][1],
                       "test_method_version": f"as reported · {fx['test_methods'][r['id']]['locator']}", "summary": CBD_RESPONSE[r["id"]][2],
                       "replicate_policy": fx["test_methods"][r["id"]]["text"], "is_cqa": bool(r.get("is_cqa")),
                       "refs": [f"{cite} {fx['responses_table']}"]} for r in fx["responses"]],
        "runs": [{"label": f"{fx['runs_table']} run {run['run_order']}", "factors": {fid: run[col] for fid, col in key_of.items()},
                  "responses": {rid: (run[rid]["mean"] if "mean" in run[rid] else run[rid]["value"]) for rid in CBD_RESPONSE}} for run in fx["runs"]],
        "test_method_version": "as reported · Methods 2.2",
        "reported_models": {rid: {"terms": m["anova_terms"], "locator": fx["published_models_table"]} for rid, m in fx["published_models"].items()},
        "verification": {"points": [{"role": "SETPOINT", "factors": {fid: fx["optimum"][col] for fid, col in key_of.items()},
                                     "batch_id": f"{fx['optimum_table']} lots", "blend_id": f"{fx['optimum_table']} lots",
                                     "evidence_status": "LITERATURE_DIRECT",
                                     "lots": {rid: v["lots"] for rid, v in fx["verification"].items() if isinstance(v, dict)}}]},
    }


def cbd() -> Dict[str, Any]:
    from formula.doe.replay import FIXTURE
    return from_cbd_fixture(json.loads(FIXTURE.read_text(encoding="utf-8")))
