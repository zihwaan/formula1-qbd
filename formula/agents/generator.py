"""설계 에이전트 (Agent 1) — 전략별 처방 후보를 만든다.

초안을 하나만 만들지 않는다. 직접타정·과립·가용화처럼 서로 다른 전략으로 후보를 동시에
생성해 경쟁시키고, 검증을 가장 잘 통과하는 후보가 살아남는다.

LLM에 주는 것: 스펙 + RDKit 프로파일 + RAG 근거(부형제 마스터·배합금기 출처) + 반성 지시.
LLM이 하는 것: 성분·비율·공정·포장 선택. **판정은 하지 않는다.**
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from formula.agents.client import LLMUnavailable, parse_structured
from formula.contracts import EventKind, FormulationSpec, Ingredient, Recipe
from formula.orchestrator.events import emit
from formula.rag.store import get_store

# 후보를 서로 다르게 만드는 전략 브리프. route_decision_tree가 산출한 경로에 맞춰 고른다.
STRATEGY_BRIEFS: Dict[str, str] = {
    "DC": "직접타정(Direct Compression). 공정 단계가 가장 적어 비용·시간이 유리하다. "
          "유동성과 압축성이 좋은 부형제(미결정셀룰로오스, 무수인산수소칼슘 등)를 중심으로 구성한다.",
    "DG": "건식과립(Dry Granulation, 롤러컴팩션). 수분·열에 민감한 API에 적합하다. "
          "액체·결합제를 쓰지 않아 화학적 조성 변화가 없다.",
    "WG": "습식과립(Wet Granulation). 유동성·함량균일성 개선에 유리하다. "
          "수분·열 안정성이 확보된 경우에만 선택한다.",
    "SOLUBILIZATION": "가용화 전략. 난용성(BCS II/IV) API의 용출을 개선한다. "
                      "고체분산체·계면활성제·사이클로덱스트린 중 하나를 명시적으로 채택한다.",
}

SYSTEM = """당신은 경구 고형제 처방을 설계하는 제제 연구원이다.

지켜야 할 것:
- 성분마다 role을 정확히 붙인다: api / diluent / binder / disintegrant / superdisintegrant /
  lubricant / glidant / surfactant_wetting / film_coating / sweetener / flavoring / colorant
  (이 어휘는 배합비 룰북 excipient_functional_ratio_rules.csv 의 functional_category와 일치해야 한다)
- 모든 부형제에 amount_mg와 percent를 모두 채운다. percent 합계는 100에 근접해야 한다.
- packaging은 다음 중 하나로 적는다: PVC blister / Alu-Alu blister / HDPE bottle with desiccant /
  amber glass bottle / CRC bottle
- process는 direct_compression / dry_granulation / wet_granulation 중 하나.
- 제공된 배합금기 근거를 반드시 읽고, 금기에 걸리는 조합은 처음부터 피한다.
- rationale에는 왜 이 조합인지 2~3문장으로 적는다.

당신은 판정하지 않는다. 판정은 결정론적 룰북 엔진이 한다."""


def _context(spec: FormulationSpec, base_dir: Path) -> str:
    """RAG로 이번 API에 관련된 근거를 모아 프롬프트에 넣는다."""
    store = get_store(base_dir)
    groups = " ".join(spec.api_functional_groups)
    query = f"{spec.api_name} {groups} 배합금기 부형제 {spec.dosage_form}"
    return store.context_for(query, k=6)


def _constraint_block(spec: FormulationSpec, directive: str) -> str:
    """현장 제약과 개선 지시를 프롬프트 말미에 붙인다.

    **필수 성분은 회피 대상이 아니다.** 기존 생산라인·단가·공급 계약 때문에 반드시 써야 하는
    부형제가 있으면 그대로 넣고, 그것이 금기에 걸리는지는 룰북이 판정한다. 설계자가 알아서
    피해 버리면 검증 계층이 무엇을 잡아내는지 화면에 드러나지 않는다(이 시스템의 요지).
    """
    parts: List[str] = []
    if spec.required_excipients:
        listed = ", ".join(spec.required_excipients)
        parts.append(
            "## 반드시 포함할 성분 (현장 제약 — 대체 금지)\n"
            f"{listed}\n"
            "이 성분은 회피하거나 다른 것으로 바꾸지 말고 반드시 처방에 넣는다. "
            "금기 위험이 의심되더라도 판정은 룰북이 하므로, 당신은 제약을 지킨 처방을 제출한다."
        )
    if directive:
        parts.append(f"## 직전 반려에 대한 개선 지시\n{directive}")
    return "\n\n" + "\n\n".join(parts) + "\n" if parts else "\n"


def generate(
    spec: FormulationSpec,
    strategy: str,
    base_dir: Path,
    candidate_id: str,
    directive: str = "",
) -> Recipe:
    """전략 하나에 대한 후보 처방 1건을 만든다."""
    node = f"generator:{strategy}"
    emit(node, EventKind.NODE_ENTER, strategy=strategy, candidate_id=candidate_id)

    brief = STRATEGY_BRIEFS.get(strategy, strategy)
    profile = spec.api_profile
    descriptor_text = (
        ", ".join(f"{k}={v:.2f}" for k, v in (profile.descriptors or {}).items())
        if profile else "(계산 없음)"
    )
    flag_text = ", ".join(profile.flag_names()) if profile else "(없음)"

    user = f"""## 설계 대상
API: {spec.api_name}
대상 환자: {spec.target_patient}
제형: {spec.dosage_form}
API 구조 플래그(RDKit): {flag_text or '(검출 없음)'}
API descriptor: {descriptor_text}
속성 플래그: {spec.properties}

## 이번 후보의 전략
{brief}

## 참고 근거 (부형제 마스터 · 배합금기 출처)
{_context(spec, base_dir)}
{_constraint_block(spec, directive)}
위 전략에 맞는 처방 1건을 설계하라. candidate_id는 "{candidate_id}", strategy는 "{strategy}"로 둔다."""

    try:
        recipe = parse_structured(Recipe, SYSTEM, user)
        recipe.candidate_id = candidate_id
        recipe.strategy = strategy
        source = "llm"
    except LLMUnavailable as exc:
        recipe = _fallback(spec, strategy, candidate_id, directive)
        source = "deterministic-fallback"
        emit(node, EventKind.WARNING, reason=str(exc), fallback=True)

    emit(node, EventKind.CANDIDATE, source=source, candidate=recipe.model_dump())
    emit(node, EventKind.NODE_EXIT, candidate_id=candidate_id)
    return recipe


def _fallback(spec: FormulationSpec, strategy: str, candidate_id: str, directive: str) -> Recipe:
    """LLM 없이 만드는 표준 처방 — 시연 안전장치.

    **배합금기를 미리 피하지 않는다.** 초안은 가장 흔한 희석제(유당)를 그대로 쓰고,
    반려된 뒤 반성 지시를 받았을 때만 교체한다. 설계자가 룰북의 일을 대신하면
    '검증이 무엇을 잡아내는지'가 보이지 않기 때문이다 — 이 시스템의 요점이 사라진다.
    """
    directive_lower = directive.lower()
    avoid_lactose = any(k in directive_lower for k in ("유당", "lactose", "만니톨", "mannitol"))
    diluent = "Mannitol" if avoid_lactose else "Lactose monohydrate"
    process = {"DC": "direct_compression", "DG": "dry_granulation",
               "WG": "wet_granulation"}.get(strategy, "direct_compression")
    hygroscopic = bool(spec.properties.get("hygroscopic"))

    ingredients = [
        Ingredient(name=spec.api_name, role="api", amount_mg=160, percent=53.3),
        Ingredient(name=diluent, role="diluent", amount_mg=95, percent=31.7),
        Ingredient(name="Microcrystalline cellulose", role="diluent", amount_mg=30, percent=10.0),
        Ingredient(name="Croscarmellose sodium", role="superdisintegrant", amount_mg=9, percent=3.0),
        Ingredient(name="Magnesium stearate", role="lubricant", amount_mg=3, percent=1.0),
        Ingredient(name="Colloidal silicon dioxide", role="glidant", amount_mg=3, percent=1.0),
    ]
    if strategy == "SOLUBILIZATION":
        ingredients.append(Ingredient(name="Poloxamer 188", role="surfactant_wetting",
                                      amount_mg=6, percent=2.0))

    # 현장 제약으로 못 박은 성분은 폴백에서도 반드시 넣는다(회피하지 않는다).
    present = {i.name.lower() for i in ingredients}
    for name in spec.required_excipients:
        if name.lower() not in present:
            ingredients.append(Ingredient(name=name, role="excipient", amount_mg=20, percent=6.7))

    return Recipe(
        api_name=spec.api_name,
        candidate_id=candidate_id,
        strategy=strategy,
        ingredients=ingredients,
        process=process,
        packaging="Alu-Alu blister" if hygroscopic else "PVC blister",
        rationale=f"[결정론 폴백] {STRATEGY_BRIEFS.get(strategy, strategy)} "
                  f"희석제는 {diluent}을 선택했다.",
    )


def plan_strategies(spec: FormulationSpec, derived: Optional[Dict] = None) -> List[str]:
    """이번 설계에서 경쟁시킬 전략을 고른다.

    route_decision_tree가 배제한 경로는 후보로 만들지 않는다 — 낭비를 막는다.
    """
    derived = derived or {}
    excluded = set(derived.get("excluded_routes") or [])
    recommended = [r for r in (derived.get("recommended_routes") or []) if r not in excluded]

    strategies = [r for r in recommended if r in STRATEGY_BRIEFS] or ["DC", "WG"]
    if spec.bcs_class in ("II", "IV"):
        strategies.append("SOLUBILIZATION")
    # 후보 수는 3개로 제한 — 비용/시간 대비 다양성이 충분하다
    return list(dict.fromkeys(strategies))[:3]
