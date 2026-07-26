"""골든 시나리오 데모 — 결정론 검증 계층이 실제로 무엇을 잡아내는지 보여준다.

두 장면으로 구성했다.

  1장. **RDKit이 기존 데모의 전제를 무너뜨린 지점**
       아세트아미노펜은 아미드(N-(4-hydroxyphenyl)acetamide)라 유리 아민이 없다.
       예전 데모는 `api_functional_groups=["Primary Amine"]`을 하드코딩해 유당-Maillard
       반려를 만들었지만, 구조를 실제로 계산하면 그 반려는 성립하지 않는다.

  2장. **실제로 성립하는 반려 → 재설계 → 통과**
       플루옥세틴은 2차 아민이고, 룰북 INC002가 바로 그 사례(Wirth 1998)를 근거로 담고 있다.
       유당을 쓴 초안이 HARD_FAIL → 반성 → 만니톨로 교체 → 통과.

실행:  .venv/bin/python scripts/demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from formula.checkers.registry import RulebookRegistry  # noqa: E402
from formula.chem.profile import build_profile  # noqa: E402
from formula.contracts import FormulationSpec, Ingredient, Recipe  # noqa: E402
from formula.orchestrator.runner import Run  # noqa: E402

BAR = "─" * 78
MARK = {"hard_fail": "⛔", "soft_flag": "⚠️ ", "escalate": "🙋", "advisory": "🏷 ",
        "exclude_route": "🚫", "pass": "  "}


def scene1(registry: RulebookRegistry) -> None:
    print("\n" + "=" * 78)
    print("1장 · RDKit이 밝힌 것 — 아세트아미노펜에는 유리 아민이 없다")
    print("=" * 78)

    for api in ("Acetaminophen", "Fluoxetine HCl"):
        profile = build_profile(api, base_dir=ROOT, render=False)
        flags = ", ".join(profile.flag_names()) or "(검출 없음)"
        print(f"\n  {api:<18} {profile.smiles}")
        print(f"  {'구조 플래그':<18} {flags}")

    print(f"\n{BAR}")
    print("  같은 처방(유당 함유)을 두 API로 각각 검증하면:")

    for api in ("Acetaminophen", "Fluoxetine HCl"):
        profile = build_profile(api, base_dir=ROOT, render=False)
        spec = FormulationSpec(api_name=api, target_patient="pediatric_under_12",
                               dosage_form="tablet").with_profile(profile)
        recipe = Recipe(
            api_name=api, candidate_id=f"draft-{api}",
            ingredients=[
                Ingredient(name=api, role="api", amount_mg=160, percent=53),
                Ingredient(name="Lactose monohydrate", role="diluent", amount_mg=95, percent=32),
                Ingredient(name="Croscarmellose sodium", role="superdisintegrant", amount_mg=9, percent=3),
                Ingredient(name="Magnesium stearate", role="lubricant", amount_mg=3, percent=1),
            ],
            process="direct_compression", packaging="Alu-Alu blister")
        result = registry.run(spec, recipe, short_circuit=False)
        blockers = result.blockers
        print(f"\n  · {api}: {'반려 ' + str(len(blockers)) + '건' if blockers else '반려 없음'}")
        for verdict in blockers:
            print(f"      ⛔ {verdict.rule_id} {verdict.reason[:64]}")

    print(f"""
{BAR}
  → 유당-Maillard 반려는 **아민을 가진 약물에서만** 성립한다.
    기존 데모(scripts/demo.py 구버전)는 아세트아미노펜에 작용기를 손으로 적어 넣어
    이 반려를 만들어냈다. RDKit을 붙이는 순간 그 전제가 사라진다.
    (개발자 가이드 §9.3: 나머지 반려 사유였던 'SLS 소아 10mg'도 PED044에서
     verification_status=NO_SOURCE_FOUND / action=NOT_A_RULE 로 폐기됐고,
     이 엔진은 그런 행을 로딩 단계에서 자동 제외한다)""")


async def scene2() -> None:
    print("\n" + "=" * 78)
    print("2장 · 실제로 성립하는 반려 → 반성 → 통과  (전체 에이전트 그래프)")
    print("=" * 78)

    run = Run(ROOT, "소아용 플루옥세틴 정제를 설계해줘")
    async for event in run.stream():
        payload = event.payload
        kind = event.kind.value
        if kind == "chem.profile":
            flags = [f["flag_name"] for f in payload["flags"] if f["present"]]
            print(f"\n  [RDKit] {payload['api_name']} → {flags}")
        elif kind == "node.exit" and payload.get("strategies"):
            print(f"  [route] 경쟁 전략: {', '.join(payload['strategies'])}")
        elif kind == "candidate":
            diluent = next((i["name"] for i in payload["candidate"]["ingredients"]
                            if i["role"] == "diluent"), "-")
            print(f"  [설계] {payload['candidate']['candidate_id']:<14} 희석제 {diluent}")
        elif kind == "rule.fired":
            print(f"       {MARK.get(payload['status'], '  ')} {payload['rulebook_id']}/"
                  f"{payload['rule_id']}: {payload['reason'][:58]}")
        elif kind == "verdict":
            print(f"  [게이트] {payload['candidate_id']:<14} "
                  f"{'통과' if payload['passed'] else '반려'} "
                  f"(판정 {payload['total']} · 위반 {payload['failures']})")
        elif kind == "reflect":
            print(f"\n  [반성] {payload['root_cause']}\n         지시 → {payload['directive']}\n")
        elif kind == "judge.summoned":
            print(f"  [소집] {payload['reviewer_id']} {payload['persona']} "
                  f"— 조건 {payload['summon_condition']}")
        elif kind == "consensus":
            print(f"\n  [합의] 모델 {payload['model']} · 선정 {payload['winner']}")
            for row in payload["ranked"]:
                rank = f"#{row['rank']}" if row.get("rank") else "— "
                print(f"         {rank} {row['candidate_id']:<14} 점수 {row['weighted_score']} "
                      f"· 심사관 {row['reviewers']}명 · 가중치 {row['weights']}")

    summary = run.summary()
    print(f"\n{BAR}")
    print(f"  결과: status={summary['status']} · 선정={summary['winner']} · "
          f"재설계 {summary['reflection_count']}회")


def main() -> None:
    registry = RulebookRegistry(ROOT / "config" / "rulebook_manifest.yaml", base_dir=ROOT)
    summary = registry.summary()
    print(f"규칙 카탈로그: 총 {summary['total']}종 "
          f"(정량 {summary['quantitative']} · 정성 {summary['qualitative']} · 참조 {summary['reference']}) "
          f"· 실행 스테이지 {summary['priorities']}단계")

    scene1(registry)
    asyncio.run(scene2())

    print("\n" + "=" * 78)
    print("  웹에서 보려면:  .venv/bin/uvicorn web.server:app --port 8000")
    print("  SMARTS 검증:    .venv/bin/python scripts/verify_smarts.py")
    print("=" * 78)


if __name__ == "__main__":
    main()
