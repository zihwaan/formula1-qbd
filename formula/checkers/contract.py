"""입력 계약 검사 — 후보 처방이 **사용자의 요청**과 맞는지를 결정론으로 대조한다(우선순위 0).

배합금기·공정 규칙은 "이 조성이 위험한가"를 본다. 여기는 그 앞의 질문이다 — "이 조성이 요청한
그 약인가". 설계 LLM이 API를 빠뜨리거나(데모 ① CONV_WG), 요청 용량을 무시하거나(8 mg → 10 mg,
2.5 mg → 50 mg), 고정 부형제를 빼도 배합금기 규칙은 그걸 모른다. LLM 출력은 신뢰하지 않고 여기서
대조한다(개발자 수정 과제 P0-1·P1-1, 2026-09-26).

규칙의 문구·허용오차·출처는 `database/06_config/request_contract_rules.csv`, 라벨 1일 최대 용량은
`database/05_regulatory/max_daily_dose.csv`에 있다 — 코드는 대조만 한다. 행의 verification_status가
반려 권한을 정하는 것은 다른 룰북과 같다(검증되지 않은 행은 심사관 표시로 강등).
"""

from __future__ import annotations

import csv as csv_mod
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from formula.checkers.excipients import IngredientMatcher
from formula.contracts import (
    ACTION_TO_STATUS, EvidencePolicy, FormulationSpec, Recipe, RuleAction, Verdict, VerdictStatus,
    evidence_policy,
)

CONTRACT_CSV = "database/06_config/request_contract_rules.csv"
MAX_DOSE_CSV = "database/05_regulatory/max_daily_dose.csv"
API_ROLES = {"api", "active", "drug", "active_ingredient"}


@lru_cache(maxsize=4)
def _rows(path: Path) -> tuple:
    if not path.exists():
        return ()
    with path.open(encoding="utf-8-sig", newline="") as h:
        return tuple(csv_mod.DictReader(h))


def _row(base_dir: Path, check: str) -> Optional[Dict[str, str]]:
    return next((r for r in _rows(Path(base_dir) / CONTRACT_CSV) if r.get("check") == check), None)


def _verdict(rulebook_id: str, row: Dict[str, str], status: Optional[VerdictStatus], reason: str,
             evidence: Dict[str, Any], suggestion: str = "") -> Verdict:
    """행의 action과 근거 상태로 판정을 만든다(검증 안 된 행은 HARD_FAIL을 못 낸다)."""
    action = RuleAction.parse(row.get("action"))
    st = status or ACTION_TO_STATUS[action]
    provisional = False
    policy = evidence_policy(row.get("verification_status"))
    if st == VerdictStatus.HARD_FAIL and policy is EvidencePolicy.NO_HARD_FAIL:
        action, st, provisional = RuleAction.REVIEWER_FLAG, VerdictStatus.SOFT_FLAG, True
        reason += " [근거 미검증 → 반려 대신 심사관 표시]"
    elif policy is EvidencePolicy.PROVISIONAL:
        provisional = True
    return Verdict(rulebook_id=rulebook_id, strategy="request_contract", status=st, action=action,
                   rule_id=row.get("rule_id", ""), layer="contract", reason=reason,
                   suggestion=suggestion or row.get("suggestion", ""),
                   score=0.0 if st == VerdictStatus.HARD_FAIL else 1.0, provisional=provisional,
                   citation=row.get("source_citation", ""), evidence={"row": dict(row), **evidence})


def _pass(rulebook_id: str, row: Dict[str, str], reason: str, evidence: Dict[str, Any]) -> Verdict:
    return Verdict(rulebook_id=rulebook_id, strategy="request_contract", status=VerdictStatus.PASS,
                   action=RuleAction.ALLOW, rule_id=row.get("rule_id", ""), layer="contract",
                   reason=reason, citation=row.get("source_citation", ""), evidence=evidence)


def api_rows(recipe: Recipe) -> list:
    return [i for i in recipe.ingredients if str(i.role or "").strip().lower() in API_ROLES]


def free_base_mg(amount: Optional[float], name: str, salt_factor: Optional[float],
                 salt_tokens: Sequence[str]) -> Optional[float]:
    """처방에 적힌 API 함량을 유리염기로 환산한다. 이름에 염 표기가 있으면 염 기준으로 읽는다."""
    if amount is None:
        return None
    low = name.lower()
    if salt_factor and any(t and t in low for t in salt_tokens):
        return amount / salt_factor
    return amount


def requested_dose(spec: FormulationSpec) -> tuple:
    """(요청 1회 용량 유리염기 mg, 원래 값, 기준). 없으면 (None, None, 기준)."""
    raw = spec.measured_params.get("dose_mg")
    basis = str(spec.properties.get("dose_basis") or "free_base")
    if raw is None:
        return None, None, basis
    factor = getattr(spec.api_profile, "salt_factor", None) if spec.api_profile else None
    fb = raw / factor if (basis == "salt" and factor) else raw
    return fb, raw, basis


def check(spec: FormulationSpec, recipe: Recipe, base_dir: Path, matcher: IngredientMatcher,
          pinned_identities: Dict[str, Sequence[str]]) -> List[Verdict]:
    base_dir = Path(base_dir)
    out: List[Verdict] = []
    profile = spec.api_profile
    salt_factor = getattr(profile, "salt_factor", None) if profile else None
    apis = api_rows(recipe)

    # RC001 — API가 정확히 1행
    row = _row(base_dir, "API_PRESENT")
    if row:
        ev = {"api_rows": [i.name for i in apis]}
        if len(apis) != 1:
            out.append(_verdict("request_contract", row, None,
                                f"{row['reason']} (API 행 {len(apis)}개: {', '.join(ev['api_rows']) or '없음'})", ev))
        else:
            out.append(_pass("request_contract", row, "API 1행", ev))

    # RC002 — 요청 용량과 함량 일치 (유리염기 환산)
    row = _row(base_dir, "API_DOSE_MATCH")
    req_fb, req_raw, basis = requested_dose(spec)
    if row and len(apis) == 1:
        api = apis[0]
        tokens = [t.strip().lower() for t in str(row.get("salt_name_tokens") or "").split(";") if t.strip()]
        cand_fb = free_base_mg(api.amount_mg, api.name, salt_factor, tokens)
        ev = {"requested_mg": req_raw, "requested_basis": basis, "requested_free_base_mg": req_fb,
              "candidate_name": api.name, "candidate_amount_mg": api.amount_mg,
              "candidate_free_base_mg": None if cand_fb is None else round(cand_fb, 4),
              "salt_factor": salt_factor}
        if req_fb is None:
            out.append(_verdict("request_contract", row, VerdictStatus.SOFT_FLAG,
                                "요청 1회 용량이 없어 함량을 검사하지 못했다 — 용량을 입력하면 결정론으로 대조한다", ev,
                                suggestion="1회 투여 용량(mg)을 입력"))
        elif cand_fb is None:
            out.append(_verdict("request_contract", row, None, f"{row['reason']} (후보에 API 함량이 없다)", ev))
        else:
            tol = float(row.get("tolerance_pct") or 0.5)
            dev = abs(cand_fb - req_fb) / req_fb * 100 if req_fb else 100.0
            ev["deviation_pct"] = round(dev, 3)
            if dev > tol:
                out.append(_verdict(
                    "request_contract", row, None,
                    f"{row['reason']} (요청 {req_fb:g} mg 유리염기 vs 후보 {api.name} {api.amount_mg:g} mg"
                    f"{f' → 유리염기 {cand_fb:.3g} mg' if abs(cand_fb - (api.amount_mg or 0)) > 1e-9 else ''}, "
                    f"차이 {dev:.1f}% > 허용 {tol}%)", ev,
                    suggestion=(f"API {req_fb:g} mg(유리염기)" + (f" = 염 {req_fb * salt_factor:.2f} mg" if salt_factor else ""))))
            else:
                out.append(_pass("request_contract", row, f"함량 일치 (차이 {dev:.2f}%)", ev))

    # MAX_DAILY_DOSE — 라벨 1일 최대 용량(구조로 대조: parent InChIKey 골격)
    mdd = _max_dose_row(base_dir, profile, spec.api_name)
    if len(apis) == 1:
        api = apis[0]
        crow = _row(base_dir, "API_DOSE_MATCH") or {}
        tokens = [t.strip().lower() for t in str(crow.get("salt_name_tokens") or "").split(";") if t.strip()]
        cand_fb = free_base_mg(api.amount_mg, api.name, salt_factor, tokens)
        if mdd is not None and cand_fb is not None:
            limit = float(mdd["max_daily_dose_free_base_mg"])
            ev = {"candidate_free_base_mg": round(cand_fb, 4), "max_daily_free_base_mg": limit,
                  "label": mdd.get("source_citation"), "label_quote": mdd.get("label_quote")}
            if cand_fb > limit:
                out.append(_verdict("max_daily_dose", mdd, None,
                                    f"1회 함량 {cand_fb:.3g} mg(유리염기)이 라벨 1일 최대 용량 {limit:g} mg을 넘는다 "
                                    f"— “{mdd.get('label_quote')}”", ev,
                                    suggestion=f"1회 함량을 {limit:g} mg 이하로"))
            else:
                out.append(_pass("max_daily_dose", mdd, f"라벨 1일 최대 {limit:g} mg 이내", ev))
        elif mdd is None:
            out.append(Verdict(rulebook_id="max_daily_dose", strategy="request_contract",
                               status=VerdictStatus.ADVISORY, action=RuleAction.LABEL_REQUIRED, rule_id="MDD000",
                               layer="contract",
                               reason="허가 라벨의 1일 최대 용량 행이 없는 물질 — 최대 용량 규칙을 적용하지 않았다(표시만)",
                               evidence={"api_name": spec.api_name,
                                         "inchikey": getattr(profile, "inchikey", "") if profile else ""}))

    # RC003 / RC004 — 고정 부형제
    pinned = [p for p in (spec.required_excipients or []) if p.strip()]
    row = _row(base_dir, "FIXED_EXCIPIENT_PRESENT")
    hits: Dict[str, str] = {}
    for p in pinned:
        for name in [p, *pinned_identities.get(p, [])]:
            hit = matcher.match(name)
            if hit is not None:
                hits[p] = hit.ingredient
                break
    if row and pinned:
        missing = [p for p in pinned if p not in hits]
        ev = {"pinned": pinned, "found": hits, "missing": missing}
        if missing:
            out.append(_verdict("request_contract", row, None,
                                f"{row['reason']} (빠짐: {', '.join(missing)})", ev))
        else:
            out.append(_pass("request_contract", row, "고정 부형제 전부 포함", ev))
    row = _row(base_dir, "LLM_ADDED_EXCIPIENT")
    if row and pinned:
        found = set(hits.values())
        added = [i.name for i in recipe.ingredients
                 if i.name not in found and str(i.role or "").strip().lower() not in API_ROLES]
        if added:
            out.append(_verdict("request_contract", row, VerdictStatus.ADVISORY,
                                f"{row['reason']}: {', '.join(added)}", {"llm_added": added, "pinned": pinned}))
    return out


def _max_dose_row(base_dir: Path, profile, api_name: str) -> Optional[Dict[str, str]]:
    rows = _rows(Path(base_dir) / MAX_DOSE_CSV)
    key = (getattr(profile, "inchikey", "") or "")[:14] if profile else ""
    if key:
        hit = next((r for r in rows if r.get("parent_inchikey_skeleton") == key), None)
        if hit:
            return hit
    name = (api_name or "").strip().lower()
    return next((r for r in rows if r.get("api_name") and r["api_name"].lower() in name), None)
