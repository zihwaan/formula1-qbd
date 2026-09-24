"""입력 에이전트 — 사용자와 두 그래프(후보 탐색 · 개발 스튜디오) 사이에서 대화를 받아 제어한다.

하는 일
  1. **맥락을 들고 있다.** 지금 어느 탭인지, 실행 중인 설계·후보·남은 데이터 요청·되돌림 제약,
     개발 스튜디오의 현재 상태와 막힌 규칙까지 서버가 요약한 스냅숏을 받아 대화한다.
  2. **말을 행동으로 바꾼다.** "성인용 이부프로펜 200mg" → 설계 실행 초안, "녹는점 76도" → 측정값 제출,
     "압축력은 몰라요" → 스튜디오 진입 자료(UNKNOWN 기록). 행동은 **제안 카드**로만 내고,
     실행은 사용자가 확인 버튼을 눌러야 한다.
  3. **먼저 말을 건다.** 설계가 끝나거나 스튜디오 상태가 바뀌면 다음에 할 일을 짚는다(nudge).
  4. **빠진 것을 묻는다.** 설계에는 SMILES와 1회 용량이 필요하다 — 없으면 묻는다.

지키는 선 (프롬프트가 아니라 코드로 강제한다)
  - **숫자와 SMILES를 지어내지 않는다.** 제안에 들어간 모든 숫자는 사용자가 실제로 쓴 글에 있어야
    하고, SMILES는 사용자 입력·내장 사전·PubChem 조회에서만 온다. LLM이 낸 값은 이 검사에서 빠진다.
  - **허용된 행동만.** 측정값 키는 실험 입력 허용목록·현재 요청의 결과 키 안에서, 스튜디오 행동은
    지금 상태가 허용하는 것만. 판정은 여전히 룰북과 엔진이 한다 — 에이전트는 입력을 정리할 뿐이다.
  - LLM이 응답하지 않으면 규칙 기반 해석(사용자 글에서 값 추출)으로 동작하고, 그 사실을 밝힌다.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field

from formula.agents.client import LLMUnavailable, parse_structured

WAIT = 20.0
NUM = r"-?\d+(?:\.\d+)?"


# ── LLM 구조화 출력 ─────────────────────────────────────────────────────
class RunDraft(BaseModel):
    api_name: str = ""
    smiles: str = ""
    dose_mg: Optional[float] = None
    target_population: Literal["", "adult", "pediatric", "geriatric"] = ""
    dosage_form: str = ""
    required_excipients: List[str] = Field(default_factory=list)
    measured: Dict[str, float] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    reply: str = Field(description="사용자에게 할 말(한국어 2~4문장). 숫자를 새로 만들지 않는다")
    intent: Literal["start_run", "submit_measurements", "studio_action", "develop_candidate",
                    "explain", "clarify", "none"] = "none"
    run: Optional[RunDraft] = None
    measurements: Dict[str, Union[float, str, bool]] = Field(default_factory=dict)
    studio_action: str = ""
    studio_payload: Dict[str, Any] = Field(default_factory=dict)
    candidate_id: str = ""
    asks: List[str] = Field(default_factory=list)


SYSTEM = """당신은 Formula 1 제형 설계 시스템의 입력 에이전트다. 사용자의 말을 시스템이 실행할 수 있는
구조화된 입력으로 바꾸고, 지금 맥락에서 다음에 할 일을 제안한다. 판정은 하지 않는다(룰북과 엔진이 한다).

규칙:
- 숫자(용량·측정값·범위·규격)와 SMILES는 **사용자가 쓴 글에 있는 것만** 옮긴다. 추측·기억으로 채우지 않는다.
  모르면 비워 둔다.
- 약 이름(또는 SMILES)이 있으면 **start_run**을 고르고 run을 채운다. api_name은 표준 영문명.
  SMILES를 사용자가 안 줬으면 비워 둔다 — 시스템이 내장 사전·PubChem에서 출처와 함께 찾는다(묻지 않는다).
  용량이 없으면 dose_mg를 비워 둔다 — 시스템이 따로 묻는다. 대화 앞부분에서 말한 조건도 run에 모은다.
- intent 고르기:
  start_run — 새 설계 요청(약 이름/SMILES·대상·제형·반드시 넣을 부형제·용량·이미 아는 실측값)
  submit_measurements — 데이터 요청에 대한 측정값(키는 아래 '받을 수 있는 측정 키'에서만)
  studio_action — 개발 스튜디오 행동(아래 '지금 가능한 스튜디오 행동'에서만, payload는 그 행동의 형식)
  develop_candidate — 특정 후보를 개발 스튜디오로 넘기기(candidate_id)
  explain — 지금 상태·판정 이유 설명
  clarify — 정보가 부족해 되묻기
- target_population: adult / pediatric / geriatric.
- 스튜디오에서 사용자가 "모른다/없다/미보고"라고 하면 그것도 입력이다: 값을 묻지 말고 studio_action으로
  해당 항목을 status "UNKNOWN"과 reason(사용자 말 요약)으로 기록한다(예: required_data의 fixed_parameters).
- asks에는 예시 값(숫자)을 들지 않는다.
- reply는 짧고 구체적으로. 무엇을 제안했는지, 확인 버튼을 눌러야 실행된다는 것을 알린다."""

STUDIO_FORMATS = {
    "required_data": '{"batch_scale": "문자열 또는 UNKNOWN — 사유", "fixed_parameters": [{"name": "compression_force", "status": "UNKNOWN"|"SET", "value": 숫자, "reason": "..."}], "grades": [{"name": "성분명", "grade": "..."}]}',
    "cqa_edit": '{"edits": [{"cqa_id": "CQA_…", "changes": {"analysis_role": "DOE_RESPONSE|MONITOR_ONLY|NOT_APPLICABLE", "acceptance_operator": "LE|GE|BETWEEN", "lower": 숫자, "upper": 숫자, "summary_definition": "…"}, "evidence_ref": "…", "reason": "…"}]}',
    "cqa_approve": "{}", "fmea_approve": "{}", "plan_approve": "{}", "model_approve": "{}",
    "vplan_lock": "{}", "region_approve": "{}",
    "factor_data": '{"factors": {"filler_ratio|blend_time|disintegrant_pct|…": {"low": 숫자, "high": 숫자, "source_ref": "…"}}}',
    "factor_approve": '{"prior_evidence_approved": true|false, "reason": "…"}',
    "model_reduce": '{"cqa_id": "CQA_…", "terms": ["1","a","b","c"], "reason": "…"}',
    "model_accept": '{"cqa_id": "CQA_…", "reason": "…"}',
    "finalize": '{"limitations": "…"}',
    "directive_approve": '{"directive": "DOE_AUGMENT|FACTOR_RANGE_REVISION|METHOD_PROCESS_CONTROL|CANDIDATE_REVISION", "reason": "…"}',
}


# ── 숫자 가드 — 제안의 모든 숫자는 사용자 글에 있어야 한다 ─────────────────────
def numbers_in(text: str) -> List[float]:
    return [float(x) for x in re.findall(NUM, text.replace(",", ""))]


def _grounded(value: float, pool: List[float]) -> bool:
    return any(abs(value - p) <= 1e-9 * max(1.0, abs(p)) for p in pool)


def strip_ungrounded(obj: Any, pool: List[float], dropped: List[str], path: str = "") -> Any:
    """사용자 글에 없는 숫자를 제거한다(bool은 숫자가 아니다). 제거한 위치는 dropped에 남긴다."""
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int, float)):
        if _grounded(float(obj), pool):
            return obj
        dropped.append(path or "값")
        return None
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nv = strip_ungrounded(v, pool, dropped, f"{path}.{k}" if path else str(k))
            if nv is not None or v is None:
                out[k] = nv
        return out
    if isinstance(obj, list):
        return [x for x in (strip_ungrounded(v, pool, dropped, f"{path}[{i}]") for i, v in enumerate(obj))
                if x is not None]
    return obj


# ── 규칙 기반 해석 (LLM이 없을 때도 사용자 글에서 값만 뽑는다) ──────────────────
_POP = [("pediatric", ("소아", "어린이", "아동", "pediatric", "child")),
        ("geriatric", ("고령", "노인", "geriatric", "elderly")),
        ("adult", ("성인", "adult"))]
_FORM = [("capsule", ("캡슐", "capsule")), ("oral_liquid", ("시럽", "현탁", "액상", "syrup")),
         ("dispersible_tablet", ("분산정",)), ("tablet", ("정제", "tablet", "알약"))]


def rule_parse(message: str, ctx: Dict[str, Any], catalog: Dict[str, Dict[str, Any]]) -> AgentOutput:
    from formula.agents.intake import _fallback as parse_request
    from formula.chem.profile import smiles_error

    text = message.strip()
    low = text.lower()
    out = AgentOutput(reply="", intent="none")

    # 측정값: "라벨/키 (은|는|=|:) 숫자" — 받을 수 있는 키만
    labels = {**{k: k for k in catalog}, **{str(v.get("label") or ""): k for k, v in catalog.items() if v.get("label")}}
    for name in sorted(labels, key=len, reverse=True):
        if not name:
            continue
        m = re.search(re.escape(name.lower()) + r"\s*(?:은|는|이|가|=|:)?\s*(?:약\s*)?(" + NUM + r")", low)
        if m and labels[name] not in out.measurements:
            out.measurements[labels[name]] = float(m.group(1))

    tab = ctx.get("tab")
    study = ctx.get("study") or {}
    if tab == "studio" and study:
        actions = study.get("actions") or []
        if "required_data" in actions:
            payload: Dict[str, Any] = {"fixed_parameters": []}
            if re.search(r"압축력.{0,12}(모름|몰라|모르|unknown|미보고|없)", low):
                payload["fixed_parameters"].append({"name": "compression_force", "status": "UNKNOWN",
                                                     "reason": "연구자 대화: 값 모름"})
            m = re.search(r"(?:배치\s*규모|배치\s*크기)\s*(?:은|는|=|:)?\s*([^\s,.]+정|UNKNOWN|미보고|모름)", text)
            if m:
                payload["batch_scale"] = m.group(1) if m.group(1) not in ("모름",) else "UNKNOWN — 연구자 대화: 모름"
            if payload["fixed_parameters"] or payload.get("batch_scale"):
                out.intent, out.studio_action, out.studio_payload = "studio_action", "required_data", payload
        approve = next((a for a in actions if a.endswith("_approve") or a in ("vplan_lock",)), None)
        if out.intent == "none" and approve and re.search(r"(승인|잠가|잠금|확정|approve)", low):
            out.intent, out.studio_action = "studio_action", approve
        if out.intent == "none" and re.search(r"(왜|설명|무슨|뭐가|막혀|막힌)", low):
            out.intent = "explain"
        return out

    run = ctx.get("run") or {}
    if run and out.measurements and not re.search(r"(설계|만들어|처방)", low):
        out.intent = "submit_measurements"
        return out
    m = re.search(r"(cand-[\w-]+)", text)
    if run and m and re.search(r"(개발|착수|넘겨|스튜디오)", low):
        out.intent, out.candidate_id = "develop_candidate", m.group(1)
        return out
    if run and re.search(r"(왜|설명|무슨|어떻게 됐|결과)", low) and not re.search(r"(설계해|만들어)", low):
        out.intent = "explain"
        return out

    # 새 설계 요청
    parsed = parse_request(text)
    smiles = next((tok for tok in re.findall(r"[A-Za-z0-9@+\-\[\]\(\)=#\\/\.%]{4,}", text)
                   if re.search(r"[cCnNoO]", tok) and re.search(r"[\(\)=\[\]#]|c1|C1", tok)
                   and smiles_error(tok) is None), "")
    dose = re.search(r"(" + NUM + r")\s*(?:mg|밀리그램)", low)
    pop = next((p for p, keys in _POP if any(k in low for k in keys)), "")
    form = next((f for f, keys in _FORM if any(k in low for k in keys)), "")
    pinned = []
    for ex in ("유당", "lactose", "만니톨", "mannitol", "미결정셀룰로오스", "mcc", "크로스포비돈", "crospovidone"):
        if ex in low and re.search(r"(반드시|꼭|필수|넣어)", low):
            pinned.append({"유당": "Lactose monohydrate", "lactose": "Lactose monohydrate", "만니톨": "Mannitol",
                           "mannitol": "Mannitol", "미결정셀룰로오스": "Microcrystalline cellulose",
                           "mcc": "Microcrystalline cellulose", "크로스포비돈": "Crospovidone",
                           "crospovidone": "Crospovidone"}[ex])
    from formula.chem.profile import resolve_smiles
    api = parsed.api_name if resolve_smiles(parsed.api_name) else ""
    if api or smiles or re.search(r"(설계|만들어|처방)", low):
        out.intent = "start_run"
        out.run = RunDraft(api_name=api, smiles=smiles, dose_mg=float(dose.group(1)) if dose else None,
                           target_population=pop, dosage_form=form, required_excipients=list(dict.fromkeys(pinned)),
                           measured={k: v for k, v in out.measurements.items() if isinstance(v, float)})
    return out


# ── 맥락 요약 (LLM 입력) ─────────────────────────────────────────────────
def context_text(ctx: Dict[str, Any]) -> str:
    lines = [f"탭: {ctx.get('tab') or 'discovery'}"]
    run = ctx.get("run") or {}
    if run:
        lines.append(f"설계 실행: 상태 {run.get('status')} · 권고 {run.get('winner') or '없음'} · 후보 "
                     + ", ".join(f"{c['candidate_id']}({'통과' if c.get('passed') else '반려'})" for c in run.get("candidates", [])))
        if run.get("request_groups"):
            lines.append("남은 데이터 요청: " + "; ".join(
                f"{g['name']}(Tier {g['tier']}) → {', '.join(g['result_keys'])}" for g in run["request_groups"]))
        if run.get("backtrack"):
            lines.append(f"마지막 되돌림: {run['backtrack'].get('transition_id')} → {run['backtrack'].get('return_phase')}")
    study = ctx.get("study") or {}
    if study:
        lines.append(f"개발 스튜디오: {study.get('title')} · 상태 {study.get('status')} — {study.get('prompt_title')}")
        if study.get("blocking"):
            lines.append("막힌 규칙: " + "; ".join(study["blocking"][:5]))
        if study.get("actions"):
            lines.append("지금 가능한 스튜디오 행동: " + ", ".join(
                f"{a} {STUDIO_FORMATS.get(a, '{}')}" for a in study["actions"] if a in STUDIO_FORMATS))
    keys = ctx.get("measurement_keys") or []
    if keys:
        lines.append("받을 수 있는 측정 키: " + ", ".join(keys[:60]))
    return "\n".join(lines)


def llm_turn(message: str, history: List[Dict[str, str]], ctx: Dict[str, Any]) -> AgentOutput:
    convo = "\n".join(f"{h.get('role')}: {h.get('text')}" for h in history[-6:])
    user = f"## 지금 맥락\n{context_text(ctx)}\n\n## 최근 대화\n{convo or '(없음)'}\n\n## 사용자\n{message}"
    return parse_structured(AgentOutput, SYSTEM, user, effort="low", max_tokens=900, wait_budget=WAIT)


def run_turn(message: str, history: List[Dict[str, str]], ctx: Dict[str, Any],
             catalog: Dict[str, Dict[str, Any]]) -> Tuple[AgentOutput, str]:
    """LLM으로 해석하고, 안 되면 규칙 기반 해석으로 내려간다. (결과, 출처)"""
    try:
        out = llm_turn(message, history, ctx)
    except LLMUnavailable:
        return rule_parse(message, ctx, catalog), "rules"
    # 규칙 기반 해석은 바닥이다 — LLM이 되묻기만 했는데 글에서 행동이 명확히 읽히면 그 행동을 제안한다.
    if out.intent in ("clarify", "none", "explain"):
        floor = rule_parse(message, ctx, catalog)
        if floor.intent in ("studio_action", "submit_measurements"):
            floor.reply = ""
            return floor, "llm+rules"
    return out, "llm"


# ── 측정 키 어휘 ────────────────────────────────────────────────────────
# 말로 들어온 측정 이름을 시스템 키로 옮기는 사전(값이 아니라 이름만). 카탈로그에 있는 키만 쓴다.
KEY_WORDS = {
    "녹는점": "tm_c", "융점": "tm_c", "용해도": "solubility_mg_per_ml", "수분": "water_content_percent",
    "안식각": "angle_of_repose", "압축성": "compressibility_index", "카르 지수": "compressibility_index",
    "하우스너": "hausner_ratio", "용량": "dose_mg", "흡수율": "fraction_absorbed",
    "잔존율": "aqueous_stability_percent", "pka": "pka_acid", "logd": "logd_7_4",
}


def measurement_catalog(base_dir, inputs) -> Dict[str, Dict[str, Any]]:
    """받을 수 있는 측정 키 — 실험 입력 허용목록 + 측정 카탈로그의 산출 필드."""
    from pathlib import Path
    from formula.biopharm.triggers import load_measurement_catalog

    out: Dict[str, Dict[str, Any]] = {}
    for key, field in inputs.fields.items():
        out[key] = {"label": field.get("label", key), "type": field.get("type", "number"), "source": "inputs"}
    for mid, meta in load_measurement_catalog(Path(base_dir)).items():
        for k in [f.strip() for f in str(meta.get("output_fields") or "").split(";") if f.strip()]:
            out.setdefault(k, {"label": k, "type": "measurement", "source": mid, "method": meta.get("name_kr", mid)})
    for word, key in KEY_WORDS.items():
        if key in out:
            out.setdefault(word, {"label": word, "alias_of": key})
    return out


def _canon_key(key: str, catalog: Dict[str, Dict[str, Any]]) -> Optional[str]:
    meta = catalog.get(key)
    if meta is None:
        return None
    return meta.get("alias_of") or key


# ── 맥락 스냅숏 (서버가 만든다 — 클라이언트가 보낸 상태를 믿지 않는다) ─────────────
def snapshot(tab: str, run: Optional[Dict[str, Any]], study: Optional[Dict[str, Any]],
             catalog: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {"tab": tab if tab in ("discovery", "studio") else "discovery"}
    if run:
        ranked = {r.get("candidate_id"): r for r in run.get("ranked", [])}
        ctx["run"] = {
            "run_id": run.get("run_id"), "status": run.get("status"), "winner": run.get("winner"),
            "candidates": [{"candidate_id": c, "passed": c in ranked or c == run.get("winner")}
                           for c in run.get("candidates", [])],
            "passed": list(ranked) or ([run["winner"]] if run.get("winner") else []),
            "request_groups": [{k: g.get(k) for k in ("measurement_id", "name", "tier", "sample_mg",
                                                        "result_keys", "triggers", "reasons")}
                               for g in run.get("request_groups", [])],
            "backtrack": run.get("backtrack") or {},
            "constraints": run.get("constraints") or {},
            "strategies": run.get("strategies") or [],
        }
    if study:
        prompt = study.get("prompt") or {}
        blocking = []
        for key, ev in (study.get("evaluations") or {}).items():
            for v in ev.get("verdicts", []):
                if v.get("effect") in ("BLOCK", "INVALIDATE", "REQUEST_DATA") and v.get("status") in ("FIRES", "MISSING"):
                    blocking.append(f"{v.get('rule_id')}: {v.get('message')}")
        ctx["study"] = {"study_id": study.get("study_id"), "status": study.get("status"),
                        "state_version": study.get("state_version"),
                        "title": (study.get("candidate") or {}).get("api_name") or study.get("candidate_ref"),
                        "prompt_title": prompt.get("title"), "ask": prompt.get("ask"),
                        "actions": prompt.get("actions") or [], "blocking": list(dict.fromkeys(blocking))[:8]}
    ctx["measurement_keys"] = [k for k, m in catalog.items() if not m.get("alias_of")]
    return ctx


# ── 제안 만들기 — 가드레일은 여기서 코드로 ─────────────────────────────────
POP_KR = {"adult": "성인용", "pediatric": "소아용", "geriatric": "고령자용"}
FORM_KR = {"tablet": "정제", "capsule": "캡슐", "oral_liquid": "경구 액제", "dispersible_tablet": "분산정"}


def _find_smiles(draft: RunDraft, user_text: str, lookup) -> Tuple[str, Dict[str, Any]]:
    """SMILES는 사용자 글 → 내장 사전 → PubChem 순으로만 얻는다. LLM 기억은 쓰지 않는다."""
    from formula.chem.profile import resolve_smiles, smiles_error

    if draft.smiles and draft.smiles in user_text and smiles_error(draft.smiles) is None:
        return draft.smiles, {"kind": "user", "label": "사용자 입력"}
    if draft.api_name:
        known = resolve_smiles(draft.api_name)
        if known:
            return known, {"kind": "dictionary", "label": "내장 구조 사전"}
        if lookup:
            try:
                found = lookup(draft.api_name)
            except Exception:   # noqa: BLE001 — 조회 실패는 '못 찾음'이다
                found = {}
            props = (found or {}).get("properties") or {}
            smi = props.get("CanonicalSMILES") or props.get("SMILES") or props.get("ConnectivitySMILES") or ""
            if found.get("found") and smi and smiles_error(smi) is None:
                return smi, {"kind": "pubchem", "label": f"PubChem CID {found.get('cid')}",
                             "url": found.get("url"), "cid": found.get("cid")}
    return "", {}


def build_response(out: AgentOutput, source: str, message: str, history: List[Dict[str, str]],
                   ctx: Dict[str, Any], catalog: Dict[str, Dict[str, Any]], inputs, lookup=None) -> Dict[str, Any]:
    user_text = "\n".join([h.get("text", "") for h in history if h.get("role") == "user"][-6:] + [message])
    pool = numbers_in(user_text)
    dropped: List[str] = []
    proposals: List[Dict[str, Any]] = []
    asks = list(out.asks)
    notes: List[str] = []
    run = ctx.get("run") or {}
    study = ctx.get("study") or {}

    if out.intent in ("clarify", "none") and out.run and (out.run.api_name or out.run.smiles):
        out.intent = "start_run"
    if out.intent == "start_run" and out.run:
        d = out.run
        dose = strip_ungrounded(d.dose_mg, pool, dropped, "dose_mg") if d.dose_mg is not None else None
        measured = {}
        for k, v in strip_ungrounded(dict(d.measured), pool, dropped, "measured").items():
            key = _canon_key(k, catalog)
            if key:
                measured[key] = v
        if dose is not None:
            measured["dose_mg"] = dose
        nums, flags, rejected = inputs.normalize(measured, {})
        smiles, smiles_src = _find_smiles(d, user_text, lookup)
        missing = []
        if not smiles:
            missing.append("smiles")
            asks.append(f"{d.api_name or '주성분'}의 구조(SMILES)를 알려 주세요 — 이름으로 공개 DB에서 찾지 못했습니다."
                        if d.api_name else "어떤 주성분(약 이름 또는 SMILES)으로 설계할까요?")
        if "dose_mg" not in nums:
            missing.append("dose_mg")
            asks.append("1회 투여 용량(mg)이 얼마인가요? 용량이 있어야 용량/용해도 부피와 BCS 관문이 계산됩니다.")
        name = d.api_name[:1].upper() + d.api_name[1:]
        label = " ".join(x for x in (POP_KR.get(d.target_population, ""), name,
                                     FORM_KR.get(d.dosage_form, "")) if x)
        said = [h.get("text", "") for h in history if h.get("role") == "user"][-3:] + [message]
        request = f"{label} — " + " / ".join(t for t in said if t)
        # 실행 제안의 말은 코드가 만든다 — LLM 문장이 이미 찾은 구조를 다시 묻거나 없는 값을 말하지 않게.
        asks = [a for a in asks if not re.search(r"(smiles|구조|용량|mg)", a.lower())] + asks[len(out.asks):]
        found = f"구조는 {smiles_src.get('label')}에서 가져왔습니다." if smiles else ""
        out.reply = (f"{label or '요청'} 설계 실행을 준비했습니다. {found}" if not missing else
                     f"{label or '요청'} 설계에 필요한 정보가 아직 빠져 있습니다. {found}")
        proposals.append({
            "kind": "start_run", "ready": not missing, "missing": missing,
            "title": f"설계 실행: {label or '새 설계'}",
            "request": request[:2000], "smiles": smiles, "smiles_source": smiles_src,
            "required_excipients": d.required_excipients[:8],
            "measured_params": nums, "rejected": rejected,
        })

    elif out.intent == "submit_measurements" and run:
        allowed = {k for g in run.get("request_groups", []) for k in g.get("result_keys") or []} | set(ctx.get("measurement_keys") or [])
        clean: Dict[str, Any] = {}
        for k, v in out.measurements.items():
            key = _canon_key(k, catalog)
            if not key or key not in allowed:
                notes.append(f"'{k}'는 받을 수 있는 측정 키가 아니라 뺐습니다.")
                continue
            if isinstance(v, bool) or isinstance(v, str):
                if isinstance(v, str) and v not in user_text:
                    dropped.append(key)
                    continue
                clean[key] = v
            else:
                g = strip_ungrounded(v, pool, dropped, key)
                if g is not None:
                    clean[key] = g
        if clean:
            proposals.append({"kind": "submit_measurements", "ready": True, "run_id": run.get("run_id"),
                              "title": "측정값 제출 → 재계산", "measurements": clean})

    elif out.intent == "studio_action" and study:
        action = out.studio_action
        if action not in (study.get("actions") or []):
            notes.append(f"'{action}'은 지금 상태({study.get('status')})에서 할 수 있는 행동이 아닙니다.")
        else:
            payload = strip_ungrounded(out.studio_payload or {}, pool, dropped, action)
            proposals.append({"kind": "studio_action", "ready": True, "study_id": study.get("study_id"),
                              "state_version": study.get("state_version"), "action": action,
                              "title": f"개발 스튜디오: {action}", "payload": payload})

    elif out.intent == "develop_candidate" and run:
        if out.candidate_id in (run.get("passed") or []):
            proposals.append({"kind": "develop_candidate", "ready": True, "run_id": run.get("run_id"),
                              "candidate_id": out.candidate_id, "title": f"{out.candidate_id}로 개발 착수"})
        else:
            notes.append("룰북을 통과한 후보만 개발 스튜디오로 넘길 수 있습니다.")

    reply = out.reply.strip()
    if out.intent == "explain" or (not reply and not proposals and not asks):
        grounded_pool = pool + numbers_in(context_text(ctx))
        if not reply or any(not _grounded(n, grounded_pool) for n in numbers_in(reply)):
            reply = explain(ctx)
    if dropped:
        notes.append("사용자 글에 없는 숫자는 옮기지 않았습니다: " + ", ".join(dict.fromkeys(dropped)))
    if source == "rules":
        notes.append("LLM 응답이 없어 규칙 기반으로 글에서 값만 읽었습니다.")
        if not reply:
            reply = ("요청을 읽었습니다." if proposals else
                     "빠진 정보가 있습니다." if asks else "무엇을 도와드릴지 조금 더 구체적으로 말씀해 주세요.")
    # 예시 숫자·빈 버튼 안내는 걷어 낸다 — 제안이 없는데 "확인을 누르라"거나, 예시 값이 입력처럼 읽히지 않게
    asks = [re.sub(r"\s*\((?:예|e\.g\.)[^)]*\)", "", a).strip() for a in asks]
    if not any(p.get("ready") for p in proposals):
        reply = " ".join(x for x in re.split(r"(?<=[.!?])\s+", reply) if "버튼" not in x and "눌러" not in x).strip()
    if not reply and proposals:
        reply = "말씀하신 내용을 실행할 수 있는 입력으로 정리했습니다."
    if any(p.get("ready") for p in proposals) and "확인" not in reply:
        reply += " 아래 카드를 확인하고 실행을 눌러야 반영됩니다."
    return {"reply": reply.strip(), "intent": out.intent, "proposals": proposals,
            "asks": list(dict.fromkeys(asks)), "notes": notes, "source": source}


def explain(ctx: Dict[str, Any]) -> str:
    """지금 상태를 맥락에서만 설명한다(새 사실을 만들지 않는다)."""
    study = ctx.get("study") or {}
    run = ctx.get("run") or {}
    if ctx.get("tab") == "studio" and study:
        text = f"지금은 '{study.get('prompt_title')}' 단계입니다. {study.get('ask') or ''}"
        if study.get("blocking"):
            text += " 막고 있는 규칙: " + "; ".join(study["blocking"][:3]) + "."
        return text
    if run:
        status = run.get("status")
        parts = {
            "passed": f"설계가 끝났고 권고 후보는 {run.get('winner')}입니다.",
            "passed_unranked": "룰북을 통과한 후보가 있지만 심사 점수가 없어 순위를 매기지 못했습니다.",
            "qtpp_review": "되돌림 제약을 모두 반영하면 남는 전략이 없습니다 — 요구사항(QTPP)을 다시 정해야 합니다.",
            "infeasible": "반드시 넣어야 하는 부형제가 룰북 금기에 걸려 통과할 수 없습니다.",
            "no_design": "설계 LLM이 응답하지 않아 후보가 만들어지지 않았습니다.",
            "escalate": "이관 판정이 나와 사람의 검토가 필요합니다.",
            "exhausted": "되돌림 한도 안에서 통과 후보를 찾지 못했습니다.",
        }
        text = parts.get(status, f"설계 상태: {status}.")
        bt = run.get("backtrack") or {}
        if bt.get("transition_id"):
            text += f" 마지막 되돌림은 {bt['transition_id']} → {bt.get('return_phase')}({bt.get('directive_hint') or ''})."
        groups = run.get("request_groups") or []
        if groups:
            g = groups[0]
            text += f" 남은 데이터 요청 {len(groups)}건 중 가장 가벼운 것은 {g.get('name')}({', '.join(g.get('result_keys') or [])})입니다."
        return text
    return "약 이름(또는 SMILES), 대상 환자, 제형, 1회 용량을 말씀해 주시면 설계 실행을 준비하겠습니다."


def nudge(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """상태가 바뀌었을 때 먼저 건네는 말 + 바로 누를 수 있는 제안(판정은 하지 않는다)."""
    study = ctx.get("study") or {}
    run = ctx.get("run") or {}
    proposals: List[Dict[str, Any]] = []
    if ctx.get("tab") == "studio" and study:
        text = explain(ctx)
        quick = [a for a in study.get("actions") or [] if a in ("cqa_approve", "fmea_approve", "plan_approve",
                                                                  "model_approve", "region_approve", "vplan_lock")]
        for a in quick[:1]:
            proposals.append({"kind": "studio_action", "ready": True, "study_id": study.get("study_id"),
                              "state_version": study.get("state_version"), "action": a, "payload": {},
                              "title": f"개발 스튜디오: {a}", "confirm_note": "승인은 연구자의 판단입니다 — 화면의 내용을 확인한 뒤 누르세요."})
        if "required_data" in (study.get("actions") or []):
            text += " 모르는 값은 '압축력은 모름'처럼 말해 주시면 UNKNOWN 기록으로 정리하겠습니다."
        return {"reply": text, "proposals": proposals, "asks": [], "notes": [], "source": "context"}
    if run:
        text = explain(ctx)
        if run.get("status") in ("passed", "passed_unranked") and run.get("passed"):
            cid = run.get("winner") or run["passed"][0]
            proposals.append({"kind": "develop_candidate", "ready": True, "run_id": run.get("run_id"),
                              "candidate_id": cid, "title": f"{cid}로 개발 착수"})
        if run.get("request_groups"):
            text += " 측정값이 있으면 이름과 값을 그대로 말해 주세요 — 제출 카드로 바꿔 드립니다. 없으면 건너뛰어도 예측값으로 계속합니다."
        return {"reply": text, "proposals": proposals, "asks": [], "notes": [], "source": "context"}
    return None
