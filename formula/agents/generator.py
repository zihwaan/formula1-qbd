"""설계 에이전트 (Agent 1) — 전략별 처방 후보를 만든다.

초안을 하나만 만들지 않는다. 직접타정·과립·가용화처럼 서로 다른 전략으로 후보를 동시에
생성해 경쟁시키고, 검증을 가장 잘 통과하는 후보가 살아남는다.

LLM에 주는 것: 스펙 + RDKit 프로파일 + RAG 근거(부형제 마스터·배합금기 출처) + 반성 지시.
LLM이 하는 것: 성분·비율·공정 선택. **판정은 하지 않는다.** 포장 사양은 산출물 범위 밖이라 만들지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from formula.agents.client import LLMUnavailable, parse_structured
from formula.contracts import EventKind, FormulationSpec, Ingredient, Recipe
from formula.orchestrator.events import emit
from formula.planner.strategy_planner import _rows as _strategy_family_rows
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
- packaging은 비워 둔다(null) — 포장 사양은 이 시스템의 산출물 범위 밖이다.
- process는 direct_compression / dry_granulation / wet_granulation 중 하나.
- 제공된 배합금기 근거를 반드시 읽고, 금기에 걸리는 조합은 처음부터 피한다.
- rationale에는 왜 이 조합인지 2~3문장으로 적는다. **참고 근거에 실제로 등장하는 구체적
  이유**(부형제 마스터의 기능·용도, 배합금기 출처가 설명하는 메커니즘 등)를 반영한다.
  근거에 없는 일반론("안정성이 좋아서", "널리 쓰여서")만으로 채우지 않는다 — 다음 단계의
  심사관이 rationale과 근거 문서를 대조해 평가하므로, 근거와 무관한 rationale은 그 자리에서
  드러난다.

당신은 판정하지 않는다. 판정은 결정론적 룰북 엔진이 한다."""


def _brief_for(strategy: str, base_dir: Path) -> str:
    """전략 브리프를 찾는다. 레거시 4개(DC/DG/WG/SOLUBILIZATION)는 하드코딩된 문구를,
    v3 전략 코드(CONV_DC·MICRO·ASD_SDD 등)는 strategy_families.csv의 generator_brief를
    쓴다 — 전략표가 늘어나도 이 함수를 다시 고칠 필요가 없다."""
    if strategy in STRATEGY_BRIEFS:
        return STRATEGY_BRIEFS[strategy]
    for row in _strategy_family_rows(Path(base_dir)):
        if row.get("strategy_code") == strategy:
            steps = str(row.get("process_steps") or "").replace(";", " → ")
            brief = str(row.get("generator_brief") or "")
            return f"{row.get('label_kr', strategy)}. {brief}\n공정 단계(참고): {steps}"
    return strategy


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
    from formula.checkers.contract import requested_dose
    req_fb, req_raw, basis = requested_dose(spec)
    profile = spec.api_profile
    factor = getattr(profile, "salt_factor", None) if profile else None
    if req_fb is not None:
        salt_line = (f" 염 형태로 적으려면 API 이름에 염 이름(예: besylate·hydrochloride·염산염)을 붙이고 "
                     f"{req_fb * factor:.3f} mg(염/유리염기 환산계수 {factor})으로 적는다 — 가능하면 유리염기로 적는다."
                     if factor else "")
        parts.append(
            "## API 함량 (요청 — 하드 제약)\n"
            f"API 행은 정확히 1개(role=api), 이름은 '{spec.api_name}', amount_mg는 유리염기 {req_fb:g} mg이다."
            f"{salt_line} 이 값은 결정론 게이트가 ±0.5%로 대조하며, 다르면 반려된다.")
    else:
        parts.append("## API\nAPI 행은 정확히 1개(role=api), 이름은 "
                     f"'{spec.api_name}'로 둔다.")
    if spec.required_excipients:
        listed = ", ".join(spec.required_excipients)
        parts.append(
            "## 반드시 포함할 성분 (현장 제약 — 대체 금지)\n"
            f"{listed}\n"
            "이 성분은 회피하거나 다른 것으로 바꾸지 말고 반드시 처방에 넣는다. "
            "금기 위험이 의심되더라도 판정은 룰북이 하므로, 당신은 제약을 지킨 처방을 제출한다. "
            "고정 목록 밖 성분을 추가할 수는 있지만, 추가 성분은 'LLM 추가 성분'으로 화면에 표시된다."
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
) -> Optional[Recipe]:
    """전략 하나에 대한 후보 처방 1건을 만든다. LLM이 응답하지 않으면 None."""
    node = f"generator:{strategy}"
    emit(node, EventKind.NODE_ENTER, strategy=strategy, candidate_id=candidate_id)

    brief = _brief_for(strategy, base_dir)
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
        # API 표준명은 모델 출력이 아니라 intake가 확정한 이름을 쓴다 — 모델의 오타(예: 'Lornoxcam')가
        # Handoff·study 이름에 영구히 박히지 않게.
        recipe.api_name = spec.api_name
        recipe.packaging = None   # 산출물 범위 밖 — 모델이 적어도 버린다
        # 공정 단계는 모델이 아니라 전략 가족 표가 정한다(같은 전략 = 같은 단계)
        row = next((r for r in _strategy_family_rows(base_dir) if r.get("strategy_code") == strategy), None)
        if row:
            recipe.process_steps = [p.strip() for p in str(row.get("process_steps") or "").split(";") if p.strip()]
    except LLMUnavailable as exc:
        # 설계는 AI의 몫이다. 응답이 없으면 틀에 박힌 처방을 대신 내놓지 않는다 — 후보를 만들지 않고
        # 그 사실을 알린다. 가짜 후보가 룰북을 통과하면 검증 결과까지 가짜가 된다.
        emit(node, EventKind.WARNING, reason=str(exc), no_candidate=True, strategy=strategy,
             message=f"{strategy} 전략 후보를 설계하지 못했습니다 — LLM 응답 없음")
        emit(node, EventKind.NODE_EXIT, candidate_id=candidate_id)
        return None

    emit(node, EventKind.CANDIDATE, source="llm", candidate=recipe.model_dump())
    emit(node, EventKind.NODE_EXIT, candidate_id=candidate_id)
    return recipe


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
