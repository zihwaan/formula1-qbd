"""결정론적 체커 전략 라이브러리.

핵심 설계: 룰북마다 함수를 새로 짜지 않는다. 8개 범용 전략 함수에 매니페스트 `schema`가
CSV 컬럼명을 주입해서 재사용한다. 런타임은 순수 파이썬만 실행 → 동일 입력 = 동일 판정(오차 0%).

전략 시그니처: (entry, rows, recipe, spec, ctx) -> List[Verdict]
  - entry: RulebookEntry (schema 매핑, polarity, severity 포함)
  - rows:  해당 룰북 CSV의 행(dict) 리스트 (row_filter·근거정책 필터 적용 후)
  - recipe, spec: 검증 대상
  - ctx:   앞 우선순위 스테이지가 산출한 파생 state (selected_route 등).
           파생값을 만드는 전략은 이 dict에 직접 기록한다.

판정 어휘: 행의 `action` 컬럼(HARD_FAIL/REVIEWER_FLAG/…)이 판정 종류를 결정한다.
행에 action이 없으면 매니페스트의 `severity`를 폴백으로 쓴다.
"""

from __future__ import annotations

import operator as _op
from typing import Any, Callable, Dict, List, Optional

from formula.checkers.applies_when import evaluate
from formula.contracts import (
    ACTION_TO_STATUS,
    EvidencePolicy,
    FormulationSpec,
    Polarity,
    Recipe,
    RuleAction,
    RulebookEntry,
    Severity,
    Verdict,
    VerdictStatus,
    evidence_policy,
)

# CSV에 담긴 비교 연산자 문자열 → 실제 파이썬 연산자.
# 룰북마다 기호형(`>`)과 워드형(`gt`)이 섞여 있어 양쪽 다 받는다.
_OPERATORS: Dict[str, Callable[[Any, Any], bool]] = {
    ">": _op.gt, "gt": _op.gt,
    ">=": _op.ge, "ge": _op.ge, "gte": _op.ge,
    "<": _op.lt, "lt": _op.lt,
    "<=": _op.le, "le": _op.le, "lte": _op.le,
    "==": _op.eq, "eq": _op.eq, "=": _op.eq,
    "!=": _op.ne, "ne": _op.ne,
}

# 범위 연산자 — threshold_value가 "0.65;0.80" 형태로 하한·상한을 함께 담는다.
_RANGE_OPERATORS = {"between", "range", "range_check", "within"}


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------
def _col(entry: RulebookEntry, key: str, default: Optional[str] = None) -> Optional[str]:
    """schema 매핑에서 실제 CSV 컬럼명을 얻는다."""
    return entry.schema_map.get(key, default)


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce(value: Any) -> Any:
    """CSV는 전부 문자열이므로 비교 전에 bool/숫자로 되돌린다."""
    if isinstance(value, (bool, int, float)):
        return value
    text = str(value).strip()
    lowered = text.lower()
    if lowered in ("true", "yes", "y"):
        return True
    if lowered in ("false", "no", "n"):
        return False
    number = _num(text)
    return number if number is not None else lowered


def _split(value: Any, sep: str = ";") -> List[str]:
    """세미콜론/쉼표 구분 목록 컬럼을 파싱한다."""
    text = str(value or "").strip()
    if not text:
        return []
    parts = text.split(sep) if sep in text else text.split(",")
    return [p.strip() for p in parts if p.strip()]


def _resolve_value(
    source: str,
    param: str,
    recipe: Recipe,
    spec: FormulationSpec,
    ctx: Dict[str, Any],
) -> Any:
    """규칙이 참조하는 값의 출처를 해석한다.

    measured_param(기본)은 측정치 → 파생 state → 속성 플래그 순으로 찾는다.
    공정 룰의 `parameter`가 세 곳 중 어디에 들어올지 CSV만 봐서는 알 수 없기 때문이다.
    """
    if source == "ingredient_mg":
        return recipe.amount_of(param)
    if source == "role_percent":
        return recipe.percent_of_role(param)
    if source == "property":
        return spec.properties.get(param)
    if source == "state":
        return ctx.get(param)
    if source == "spec":
        return getattr(spec, param, None)
    for pool in (spec.measured_params, ctx, spec.properties):
        if param in pool:
            return pool[param]
    return None


def _row_action(entry: RulebookEntry, row: Dict[str, Any]) -> RuleAction:
    """행의 action 컬럼을 읽는다. 없으면 매니페스트 severity를 폴백으로 쓴다."""
    action_col = _col(entry, "action_col", "action")
    raw = row.get(action_col) if action_col else None
    if raw is not None and str(raw).strip():
        return RuleAction.parse(raw)
    return (
        RuleAction.HARD_FAIL
        if entry.severity == Severity.HARD_FAIL
        else RuleAction.REVIEWER_FLAG
    )


def _violation(
    entry: RulebookEntry,
    strategy: str,
    row: Dict[str, Any],
    *,
    reason: str,
    suggestion: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> Verdict:
    """위반 1건을 Verdict으로 만든다. 근거 신뢰도 정책을 여기서 한 번에 적용한다.

    근거가 약한 행(SCHEMA_ONLY/UNVERIFIED/…)은 **HARD_FAIL로 승격되지 못하고**
    심사관 이관(REVIEWER_FLAG)으로 강등된다 — 개발자 가이드 7장의 엔진 규약.
    """
    action = _row_action(entry, row)
    status = ACTION_TO_STATUS[action]
    policy = evidence_policy(row.get(_col(entry, "verification_col", "verification_status")))
    provisional = False
    note = ""

    if policy is EvidencePolicy.ESCALATE:
        action, status = RuleAction.ESCALATE_TO_HUMAN, VerdictStatus.ESCALATE
        note = " [근거: 사람 판단 필요]"
    elif policy is EvidencePolicy.NO_HARD_FAIL and status == VerdictStatus.HARD_FAIL:
        action, status = RuleAction.REVIEWER_FLAG, VerdictStatus.SOFT_FLAG
        provisional = True
        note = " [근거 미검증 → 반려 대신 심사관 이관]"
    elif policy is EvidencePolicy.PROVISIONAL:
        provisional = True
        note = " [잠정값]"

    return Verdict(
        rulebook_id=entry.id,
        strategy=strategy,
        status=status,
        action=action,
        rule_id=str(row.get(_col(entry, "rule_id_col", "rule_id"), "") or ""),
        layer=entry.layer,
        reason=(reason + note).strip(),
        suggestion=suggestion,
        score=0.0 if status != VerdictStatus.PASS else 1.0,
        provisional=provisional,
        citation=str(row.get(_col(entry, "citation_col", "source_citation"), "") or ""),
        evidence={**(evidence or {}), "row": row},
    )


def _pass(entry: RulebookEntry, strategy: str) -> Verdict:
    return Verdict(
        rulebook_id=entry.id,
        strategy=strategy,
        status=VerdictStatus.PASS,
        action=RuleAction.ALLOW,
        layer=entry.layer,
    )


def _fires(condition_true: bool, polarity: Polarity) -> bool:
    """조건 성립 여부 + polarity → 위반인가.

    fail_when : 조건이 참이면 위반   (carr_index > 25 → 유동 불량)
    pass_when : 조건이 거짓이면 위반 (carr_index <= 20 을 만족해야 통과)
    """
    return condition_true if polarity == Polarity.FAIL_WHEN else not condition_true


# ---------------------------------------------------------------------------
# 1) pairwise_membership — (부형제 X, API 작용기 Y) 조합 존재 시 반려
#    예: incompatibility_1to1.csv (Lactose + primary_amine → Maillard)
# ---------------------------------------------------------------------------
def pairwise_membership(entry, rows, recipe: Recipe, spec: FormulationSpec, ctx) -> List[Verdict]:
    left = _col(entry, "left_key", "excipient_name_en")
    right = _col(entry, "right_key", "api_functional_group")
    reason_c = _col(entry, "reason_col", "mechanism")
    sugg_c = _col(entry, "suggestion_col", "alternative_excipient_name")

    ingredients = {n.strip().lower() for n in recipe.ingredient_names()}
    groups = {g.strip().lower() for g in spec.api_functional_groups}
    # 구조 플래그(has_primary_amine)와 룰북 어휘(primary_amine)를 양쪽으로 맞춘다
    groups |= {g[4:] for g in groups if g.startswith("has_")}
    groups |= {f"has_{g}" for g in list(groups)}

    verdicts: List[Verdict] = []
    for row in rows:
        excipient = str(row.get(left, "")).strip().lower()
        fgroup = str(row.get(right, "")).strip().lower()
        if not excipient or not fgroup:
            continue
        # api_functional_group == 'any' 는 작용기와 무관하게 그 부형제 자체가 문제인 행
        if excipient in ingredients and (fgroup == "any" or fgroup in groups):
            verdicts.append(
                _violation(
                    entry, "pairwise_membership", row,
                    reason=str(row.get(reason_c, "")),
                    suggestion=str(row.get(sugg_c, "")),
                    evidence={"excipient": row.get(left), "functional_group": row.get(right)},
                )
            )
    return verdicts or [_pass(entry, "pairwise_membership")]


# ---------------------------------------------------------------------------
# 2) subset_forbidden — 금기 성분 집합이 처방의 부분집합이면 반려
#    예: incompatibility_multicomponent.csv (아민염 + 환원당 + 알칼리활택제)
# ---------------------------------------------------------------------------
def subset_forbidden(entry, rows, recipe: Recipe, spec: FormulationSpec, ctx) -> List[Verdict]:
    combo_c = _col(entry, "combo_col", "component_set")
    reason_c = _col(entry, "reason_col", "mechanism")
    sugg_c = _col(entry, "suggestion_col", "alternative")
    cond_c = _col(entry, "condition_col", "required_conditions")

    # 처방 성분 + 작용기 + 속성 플래그를 합쳐 '존재 집합'을 만든다.
    present = {n.strip().lower() for n in recipe.ingredient_names()}
    present |= {g.strip().lower() for g in spec.api_functional_groups}
    present |= {k.lower() for k, v in spec.properties.items() if v is True}
    present |= {str(v).strip().lower() for v in ctx.values() if isinstance(v, str)}
    if spec.properties.get("moisture_present") or spec.measured_params.get("moisture", 0) > 0:
        present.add("water")
        present.add("moisture")

    verdicts: List[Verdict] = []
    for row in rows:
        forbidden = {c.lower() for c in _split(row.get(combo_c, ""))}
        if not forbidden or not forbidden.issubset(present):
            continue
        # required_conditions("moisture present")가 있으면 그 조건도 성립해야 발동.
        # "all"/"any"처럼 무조건 적용을 뜻하는 어휘는 게이트로 쓰지 않는다.
        condition = str(row.get(cond_c, "") or "").strip().lower()
        if condition not in ("", "none", "n/a", "all", "any", "-"):
            tokens = [t for t in condition.replace(",", " ").split() if t not in ("present", "at")]
            if tokens and not any(t in present for t in tokens):
                continue
        verdicts.append(
            _violation(
                entry, "subset_forbidden", row,
                reason=str(row.get(reason_c, "")),
                suggestion=str(row.get(sugg_c, "")),
                evidence={"component_set": sorted(forbidden), "required_conditions": condition},
            )
        )
    return verdicts or [_pass(entry, "subset_forbidden")]


# ---------------------------------------------------------------------------
# 3) threshold — 행이 (param, operator, threshold) 기준 하나를 서술한다.
#    polarity에 따라 '실패 조건'(fail_when) 또는 '통과 조건'(pass_when)으로 읽는다.
#    operator에는 기호형/워드형 외에 `between`(하한;상한)과 `==`(비수치 동등)도 온다.
# ---------------------------------------------------------------------------
def threshold(entry, rows, recipe: Recipe, spec: FormulationSpec, ctx) -> List[Verdict]:
    param_c = _col(entry, "param_col", "parameter")
    op_c = _col(entry, "operator_col", "operator")
    thr_c = _col(entry, "threshold_col", "threshold_value")
    src_c = _col(entry, "source_col", "source")
    default_src = _col(entry, "source", "measured_param")
    # 연산자 컬럼이 아예 없는 룰북(ICH Q3C 잔류용매 한계 등)은 매니페스트가 상수로 준다
    default_op = _col(entry, "operator", None)
    # 임계값 단위가 값의 단위와 다를 때의 환산 계수 (예: 상한 5 g vs 처방 mg → 1000)
    scale = _num(_col(entry, "threshold_scale", None)) or 1.0
    reason_c = _col(entry, "reason_col", "fail_mode")
    sugg_c = _col(entry, "suggestion_col", "target_range")

    verdicts: List[Verdict] = []
    for row in rows:
        param = str(row.get(param_c, "")).strip()
        op = str(row.get(op_c, "") or default_op or "").strip()
        raw_limit = row.get(thr_c)
        if not param or not op or raw_limit in (None, ""):
            continue  # 수치 기준이 없는 행(실험 필요) → 결정론 판정 대상 아님
        source = str(row.get(src_c) or default_src).strip()
        value = _resolve_value(source, param, recipe, spec, ctx)
        if value is None:
            continue  # 해당 값이 처방/스펙에 없음 → 이 규칙은 적용 대상 아님

        if op.lower() in _RANGE_OPERATORS:
            bounds = [_num(b) for b in _split(raw_limit)]
            lo = bounds[0] if len(bounds) > 0 else None
            hi = bounds[1] if len(bounds) > 1 else None
            numeric = _num(value)
            if numeric is None or (lo is None and hi is None):
                continue
            inside = (lo is None or numeric >= lo) and (hi is None or numeric <= hi)
            # 범위 행은 '이 범위 안이면 통과' 의미이므로 polarity 무관하게 이탈 시 위반
            if inside:
                continue
            verdicts.append(
                _violation(
                    entry, "threshold", row,
                    reason=f"{str(row.get(reason_c, '')).strip()} ({param}={numeric}, 허용 [{lo}, {hi}])",
                    suggestion=str(row.get(sugg_c, "")),
                    evidence={"param": param, "value": numeric, "min": lo, "max": hi},
                )
            )
            continue

        compare = _OPERATORS.get(op.lower())
        if compare is None:
            continue
        left, right = _coerce(value), _coerce(raw_limit)
        if scale != 1.0 and isinstance(right, (int, float)) and not isinstance(right, bool):
            right = right * scale
        if isinstance(left, bool) != isinstance(right, bool) and op.lower() not in ("==", "eq", "=", "!=", "ne"):
            continue  # 타입이 안 맞는 부등호 비교는 판정 불가
        try:
            condition_true = bool(compare(left, right))
        except TypeError:
            continue
        if not _fires(condition_true, entry.polarity):
            continue
        expectation = f"{param} {op} {raw_limit}"
        detail = (f"측정 {param}={left}, 기준 {expectation}"
                  if entry.polarity == Polarity.PASS_WHEN
                  else f"측정 {param}={left} {op} {raw_limit}")
        verdicts.append(
            _violation(
                entry, "threshold", row,
                reason=f"{str(row.get(reason_c, '')).strip()} ({detail})",
                suggestion=str(row.get(sugg_c, "")),
                evidence={"param": param, "value": left, "operator": op,
                          "threshold": right, "polarity": entry.polarity.value},
            )
        )
    return verdicts or [_pass(entry, "threshold")]


# ---------------------------------------------------------------------------
# 4) range — min/max 컬럼 쌍으로 허용 범위가 주어진 경우 (활택제 0.5~2.0% 등)
# ---------------------------------------------------------------------------
def range_check(entry, rows, recipe: Recipe, spec: FormulationSpec, ctx) -> List[Verdict]:
    param_c = _col(entry, "param_col", "functional_category")
    min_c = _col(entry, "min_col", "pct_min")
    max_c = _col(entry, "max_col", "pct_max")
    src_c = _col(entry, "source_col", "source")
    default_src = _col(entry, "source", "role_percent")
    reason_c = _col(entry, "reason_col", "notes")
    sugg_c = _col(entry, "suggestion_col", "pct_typical")

    verdicts: List[Verdict] = []
    for row in rows:
        param = str(row.get(param_c, "")).strip()
        lo, hi = _num(row.get(min_c)), _num(row.get(max_c))
        source = str(row.get(src_c) or default_src).strip()
        value = _resolve_value(source, param, recipe, spec, ctx)
        numeric = _num(value)
        if numeric is None or (lo is None and hi is None):
            continue
        if (lo is None or numeric >= lo) and (hi is None or numeric <= hi):
            continue
        verdicts.append(
            _violation(
                entry, "range", row,
                reason=f"{str(row.get(reason_c, '')).strip()} ({param}={numeric}, 허용 [{lo}, {hi}])",
                suggestion=f"전형값 {row.get(sugg_c, '')}".strip(),
                evidence={"param": param, "value": numeric, "min": lo, "max": hi},
            )
        )
    return verdicts or [_pass(entry, "range")]


# ---------------------------------------------------------------------------
# 5) categorical_requirement — class==X면 [옵션…] 중 하나(또는 role)를 필수
#    예: BCS II/IV → 가용화 전략 필수
# ---------------------------------------------------------------------------
def categorical_requirement(entry, rows, recipe: Recipe, spec: FormulationSpec, ctx) -> List[Verdict]:
    class_c = _col(entry, "class_col", "bcs_class")
    role_c = _col(entry, "required_role_col", "required_role")
    options_c = _col(entry, "options_col", "recommended_strategies")
    reason_c = _col(entry, "reason_col", "strategy_rationale")
    sugg_c = _col(entry, "suggestion_col", "recommended_strategies")
    subject = _col(entry, "subject", "bcs_class")

    subject_value = (
        getattr(spec, subject, None)
        if hasattr(spec, subject)
        else spec.properties.get(subject, ctx.get(subject))
    )
    verdicts: List[Verdict] = []
    for row in rows:
        if str(row.get(class_c, "")).strip() != str(subject_value or "").strip():
            continue
        required_role = str(row.get(role_c, "") or "").strip()
        options = {o.strip().lower() for o in _split(row.get(options_c, ""))}
        has_role = bool(required_role) and any(ing.role == required_role for ing in recipe.ingredients)
        recipe_terms = {n.strip().lower() for n in recipe.ingredient_names()} | {
            (recipe.strategy or "").strip().lower()
        }
        # 옵션은 "solid dispersion (amorphous)"처럼 서술형이라 부분 일치로 본다
        has_option = any(
            opt and any(opt in term or term in opt for term in recipe_terms if term)
            for opt in options
        )
        if has_role or has_option:
            continue
        verdicts.append(
            _violation(
                entry, "categorical_requirement", row,
                reason=str(row.get(reason_c, "")),
                suggestion=str(row.get(sugg_c, "")),
                evidence={"class": subject_value, "required": required_role or sorted(options)},
            )
        )
    return verdicts or [_pass(entry, "categorical_requirement")]


# ---------------------------------------------------------------------------
# 6) conditional_prohibition — 속성 플래그 참이면 특정 옵션 금지
#    예: 흡습성(hygroscopic) → 고투습 포장 금지
# ---------------------------------------------------------------------------
def conditional_prohibition(entry, rows, recipe: Recipe, spec: FormulationSpec, ctx) -> List[Verdict]:
    flag_c = _col(entry, "flag_col", "product_property")
    forbid_c = _col(entry, "forbidden_col", "prohibited_packaging")
    reason_c = _col(entry, "reason_col", "rationale")
    sugg_c = _col(entry, "suggestion_col", "required_packaging")
    target = _col(entry, "target", "packaging")
    traits_key = _col(entry, "traits_key", f"{target}_traits")

    target_value = str(getattr(recipe, target, None) or "").strip().lower()
    if not target_value:
        return [_pass(entry, "conditional_prohibition")]
    # 룰북은 "고투습 포장" 같은 서술 범주로 금지 대상을 적는다.
    # 식별자("PVC blister")를 범주로 번역한 결과가 ctx[traits_key]에 들어 있다.
    traits = {str(t).strip().lower() for t in (ctx.get(traits_key) or [])}
    haystack = traits | {target_value}

    verdicts: List[Verdict] = []
    for row in rows:
        flag = str(row.get(flag_c, "")).strip()
        if not flag:
            continue
        if not bool(spec.properties.get(flag) or ctx.get(flag)):
            continue
        forbidden = [f.lower() for f in _split(row.get(forbid_c, ""))]
        if not any(f and any(f in h or h in f for h in haystack) for f in forbidden):
            continue
        verdicts.append(
            _violation(
                entry, "conditional_prohibition", row,
                reason=str(row.get(reason_c, "")),
                suggestion=str(row.get(sugg_c, "")),
                evidence={"flag": flag, "target": target_value,
                          "traits": sorted(traits), "forbidden": forbidden},
            )
        )
    return verdicts or [_pass(entry, "conditional_prohibition")]


# ---------------------------------------------------------------------------
# 7) band_lookup — 참조표에서 구간/조건에 맞는 등급을 조회해 파생값을 만든다.
#    판정이 아니라 **산출**이 목적이다 (USP<1174> 유동성 등급, ICH M9 BCS 분류).
#
#    두 가지 행 모양을 모두 지원한다:
#      - 구간형: value_min ~ value_max → 등급          (powder_flow_scale)
#      - 술어형: parameter operator threshold → 등급   (bcs_classification_criteria)
#    여러 행이 맞을 때 aggregate=intersect면 교집합을 취한다(BCS class 확정).
# ---------------------------------------------------------------------------
def band_lookup(entry, rows, recipe: Recipe, spec: FormulationSpec, ctx) -> List[Verdict]:
    param_c = _col(entry, "param_col", "parameter")
    min_c = _col(entry, "min_col", "value_min")
    max_c = _col(entry, "max_col", "value_max")
    op_c = _col(entry, "operator_col", "operator")
    thr_c = _col(entry, "threshold_col", "threshold_value")
    out_c = _col(entry, "output_col", "flow_character_normalized")
    aggregate = _col(entry, "aggregate", "first")
    default_src = _col(entry, "source", "measured_param")

    matches: List[Dict[str, Any]] = []
    for row in rows:
        param = str(row.get(param_c, "")).strip()
        if not param:
            continue
        value = _resolve_value(default_src, param, recipe, spec, ctx)
        numeric = _num(value)
        if numeric is None:
            continue

        hit = False
        if min_c in row or max_c in row:  # 구간형
            lo, hi = _num(row.get(min_c)), _num(row.get(max_c))
            if lo is None and hi is None:
                continue
            hit = (lo is None or numeric >= lo) and (hi is None or numeric <= hi)
        if not hit and op_c in row:  # 술어형
            compare = _OPERATORS.get(str(row.get(op_c, "")).strip().lower())
            limit = _num(row.get(thr_c))
            hit = bool(compare and limit is not None and compare(numeric, limit))
        if not hit:
            continue

        outputs = _split(row.get(out_c, "")) or [str(row.get(out_c, "")).strip()]
        matches.append({"param": param, "value": numeric,
                        "outputs": [o for o in outputs if o],
                        "rule_id": row.get(_col(entry, "rule_id_col", "rule_id"),
                                           row.get("scale_id", row.get("criterion_id", "")))})

    if not matches:
        return [_pass(entry, "band_lookup")]

    if aggregate == "intersect":
        resolved: Optional[set] = None
        for m in matches:
            resolved = set(m["outputs"]) if resolved is None else (resolved & set(m["outputs"]))
        candidates = sorted(resolved or set())
        value = candidates[0] if len(candidates) == 1 else None
    else:
        candidates = matches[0]["outputs"]
        value = candidates[0] if candidates else None

    # 산출된 파생값을 state에 기록한다 → 뒤 우선순위 규칙의 applies_when이 참조
    if value is not None:
        for key in entry.provides:
            ctx[key] = value

    verdict = _pass(entry, "band_lookup")
    verdict.evidence = {"provides": {k: value for k in entry.provides},
                        "matches": matches, "candidates": candidates}
    verdict.reason = f"{', '.join(entry.provides) or '등급'} = {value}" if value else "등급 확정 불가(입력 부족)"
    return [verdict]


# ---------------------------------------------------------------------------
# 8) decision_tree — 조건식 행들을 평가해 가능한 공정 경로를 좁힌다.
#    예: route_decision_tree.csv (유동성/수분·열 민감성 → DC / DG / WG 선택)
#    권장 경로가 하나도 남지 않으면 반성 루프가 아니라 **사람에게** 이관한다(무한루프 방지).
# ---------------------------------------------------------------------------
def decision_tree(entry, rows, recipe: Recipe, spec: FormulationSpec, ctx) -> List[Verdict]:
    cond_c = _col(entry, "condition_col", "condition_expression")
    rec_c = _col(entry, "recommend_col", "recommended_routes")
    exc_c = _col(entry, "exclude_col", "excluded_routes")
    prio_c = _col(entry, "priority_col", "route_priority")
    reason_c = _col(entry, "reason_col", "rationale")
    sugg_c = _col(entry, "suggestion_col", "remediation_option")

    from formula.checkers.applies_when import spec_context  # 지역 import: 순환 참조 방지

    scope = spec_context(spec, ctx)
    recommended: Dict[str, int] = {}
    excluded: set = set()
    fired: List[Dict[str, Any]] = []
    meta_rows: List[Dict[str, Any]] = []

    for row in rows:
        expression = str(row.get(cond_c, "") or "").strip()
        # `len(recommended_routes) == 0` 같은 메타 조건은 집계가 끝난 뒤 평가한다
        if "recommended_routes" in expression:
            meta_rows.append(row)
            continue
        if not evaluate(expression, scope):
            continue
        priority = int(_num(row.get(prio_c)) or 99)
        for route in _split(row.get(rec_c, "")):
            recommended[route] = min(recommended.get(route, 99), priority)
        excluded |= set(_split(row.get(exc_c, "")))
        fired.append({"rule_id": row.get("rule_id"), "condition": expression,
                      "recommends": _split(row.get(rec_c, "")),
                      "excludes": _split(row.get(exc_c, ""))})

    viable = {r: p for r, p in recommended.items() if r not in excluded}
    scope["recommended_routes"] = sorted(viable)

    # "가능한 경로가 없다"(에스컬레이션)와 "판단할 입력이 없다"(단순 미측정)는 다르다.
    # 어떤 분기 규칙도 발동하지 않았다면 유동성·안정성 데이터 자체가 없다는 뜻이므로,
    # RTE010(경로 전무) 같은 메타 규칙을 발동시키면 안 된다.
    if not fired:
        verdict = _pass(entry, "decision_tree")
        verdict.reason = "공정 경로 판단 불가 — 유동성/안정성 입력이 없다(측정 필요)"
        verdict.evidence = {"selected_route": None, "reason": "insufficient_input"}
        return [verdict]

    verdicts: List[Verdict] = []
    for row in meta_rows:
        if not evaluate(str(row.get(cond_c, "") or ""), scope):
            continue
        verdicts.append(
            _violation(
                entry, "decision_tree", row,
                reason=str(row.get(reason_c, "")),
                suggestion=str(row.get(sugg_c, "")),
                evidence={"recommended": sorted(viable), "excluded": sorted(excluded), "fired": fired},
            )
        )

    selected = min(viable, key=lambda r: (viable[r], r)) if viable else None
    if selected is not None:
        for key in entry.provides:
            ctx[key] = selected
    ctx["excluded_routes"] = sorted(excluded)
    ctx["recommended_routes"] = sorted(viable)

    if verdicts:
        return verdicts

    verdict = _pass(entry, "decision_tree")
    verdict.reason = f"선택 공정 경로 = {selected} (후보 {sorted(viable)}, 배제 {sorted(excluded)})"
    verdict.evidence = {"selected_route": selected, "recommended": sorted(viable),
                        "excluded": sorted(excluded), "fired": fired}
    return [verdict]


# 전략 이름 → 함수 레지스트리. 매니페스트의 `strategy` 값이 이 키를 참조한다.
STRATEGIES: Dict[str, Callable[..., List[Verdict]]] = {
    "pairwise_membership": pairwise_membership,
    "subset_forbidden": subset_forbidden,
    "threshold": threshold,
    "range": range_check,
    "categorical_requirement": categorical_requirement,
    "conditional_prohibition": conditional_prohibition,
    "band_lookup": band_lookup,
    "decision_tree": decision_tree,
}
