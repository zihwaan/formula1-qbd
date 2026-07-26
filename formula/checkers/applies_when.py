"""매니페스트/룰북의 조건식을 안전하게 평가한다.

평가 대상은 세 종류다.
  1. 매니페스트의 `applies_when` — "이 룰북이 이번 입력에서 발동하는가"
  2. 매니페스트의 `row_filter`   — "혼합 CSV에서 어떤 행을 쓸 것인가"
  3. 룰북 CSV의 `condition_expression` — route_decision_tree 등 행 자체의 조건

주의: 이 조건식들은 *매니페스트/룰북 저자(팀)*가 작성한 신뢰 입력이지 사용자 입력이 아니다.
그래도 방어적으로, builtins를 제거하고 화이트리스트 컨텍스트만 노출한 제한 eval을 쓴다.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from formula.contracts import FormulationSpec

# eval에 노출할 허용 헬퍼만. __builtins__는 완전히 차단한다.
# len/any/all은 조건식(`len(recommended_routes) == 0`)에 실제로 쓰이므로 명시적으로 넣는다.
_SAFE_GLOBALS: Dict[str, Any] = {
    "__builtins__": {},
    "len": len,
    "any": any,
    "all": all,
    "min": min,
    "max": max,
    "abs": abs,
    "float": float,
    "int": int,
    "str": str,
    "bool": bool,
}

# 룰북 저자에 따라 SQL/DSL 스타일 어휘가 섞여 들어온다(AND/OR/true/false).
# 파이썬 문법으로 정규화한 뒤 평가한다. 단어 경계로만 치환해 식별자를 건드리지 않는다.
_DSL_ALIASES = [
    (re.compile(r"(?<![\w.])AND(?![\w])"), "and"),
    (re.compile(r"(?<![\w.])OR(?![\w])"), "or"),
    (re.compile(r"(?<![\w.])NOT(?![\w])"), "not"),
    (re.compile(r"(?<![\w.])true(?![\w])"), "True"),
    (re.compile(r"(?<![\w.])false(?![\w])"), "False"),
    (re.compile(r"(?<![\w.])null(?![\w])"), "None"),
]


def normalize_expression(expr: str) -> str:
    """DSL 어휘가 섞인 조건식을 파이썬 문법으로 정규화한다."""
    out = expr
    for pattern, replacement in _DSL_ALIASES:
        out = pattern.sub(replacement, out)
    return out


def spec_context(
    spec: FormulationSpec,
    derived: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """조건식에서 참조 가능한 변수들.

    `derived`는 앞 우선순위 스테이지가 산출한 파생값(selected_route, flow_character 등).
    나중 값이 앞 값을 덮어쓰도록 병합 순서를 잡는다: 스펙 → 측정치 → 플래그 → 파생값.
    """
    ctx: Dict[str, Any] = {
        "api_name": spec.api_name,
        "bcs_class": spec.bcs_class,
        "target_patient": spec.target_patient,
        "target_population": "pediatric" if spec.is_pediatric else "adult",
        "dosage_form": spec.dosage_form,
        "is_pediatric": spec.is_pediatric,
        "api_functional_groups": list(spec.api_functional_groups),
        # "이 측정치가 있는가"를 조건으로 쓰는 규칙용 (예: BCS 분류는 실측이 있을 때만)
        "measured_keys": list(spec.measured_params),
        "property_keys": list(spec.properties),
        "true": True,
        "false": False,
        "True": True,
        "False": False,
        "None": None,
        "always": True,
    }
    ctx.update(spec.measured_params)
    # 프로파일 플래그(hygroscopic 등)도 직접 참조 가능하게
    ctx.update(spec.properties)
    if derived:
        ctx.update(derived)
    return ctx


def evaluate(expr: str, context: Dict[str, Any]) -> bool:
    expr = (expr or "true").strip()
    if expr in ("true", "True", "", "always", "N/A"):
        return True
    if expr in ("false", "False"):
        return False
    try:
        return bool(eval(normalize_expression(expr), _SAFE_GLOBALS, context))  # noqa: S307
    except Exception:
        # 조건식 오류 시 보수적으로 발동시키지 않는다(관측 가능한 실패보다 스킵이 안전).
        return False


def row_matches(row: Dict[str, Any], row_filter: Optional[str]) -> bool:
    """혼합 CSV에서 특정 행만 고르는 필터. 예: "eval_type == 'qualitative'"."""
    if not row_filter:
        return True
    return evaluate(row_filter, {**row, "true": True, "false": False})
