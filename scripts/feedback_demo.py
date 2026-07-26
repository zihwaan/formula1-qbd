"""Closed-loop 데모: wet-lab 실험 결과 재입력 → 결정론적 해석 → 재설계 피드백.

시나리오를 이어서 본다:
  1. 검증을 통과한 처방(BCS II 난용성 API, 가용화 전략 적용)을 연구원이 wet-lab에서 제조·시험.
  2. 고정된 실험 결과(용출률 미달 등)를 시스템에 재입력(human-in-the-loop).
  3. 해석기가 목표 대비 gap을 계산하고, 실패 원인 해석 + 재설계 방향을 돌려준다.
  4. 개선안을 재제조한 2차 실험 결과를 다시 넣으면 목표를 충족(loop 종료)함을 보여준다.

LLM 없이 결정론적 해석 계층만으로 'closed-loop 자가수정'의 뼈대가 도는 것을 확인하는 용도.
실행:  .venv/bin/python scripts/feedback_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from formula.feedback import WetLabInterpreter  # noqa: E402
from formula.contracts import WetLabResult  # noqa: E402


def print_report(title: str, report) -> None:
    print(f"\n=== {title} ===")
    print(f"측정 지표 {len(report.findings)}건 · 목표 이탈 {len(report.off_target_findings)}건")
    for f in report.findings:
        mark = "❌ 이탈" if f.off_target else "✅ 충족"
        print(f"  [{mark}] {f.metric} = {f.measured} (목표 {f.operator}{f.target} 이면 이탈)")
        if f.off_target:
            print(f"         원인: {f.interpretation}")
            print(f"         ↳ 재설계 제안: {f.suggested_revision}")
    print(f"  → reflection 필요: {'예' if report.reflection_needed else '아니오'}")


def main() -> None:
    interp = WetLabInterpreter(ROOT / "database" / "legacy" / "wetlab_feedback_rules.csv")

    # 1차 실험 결과(고정): 가용화 전략을 적용했으나 30분 용출률이 목표 80%에 크게 미달.
    result_v1 = WetLabResult(
        candidate_id="cand-solid-dispersion-v1",
        measurements={
            "dissolution_30min_percent": 45.0,  # 목표 미달 → 이탈
            "tablet_hardness_N": 85.0,          # 정상
            "impurity_total_percent": 0.2,      # 정상
            "assay_percent": 98.5,              # 정상
        },
        notes="고분자(PVP-VA) 1:3 고체분산체, HME 공정",
    )
    report_v1 = interp.interpret(result_v1)
    print_report("1차 실험 결과 해석", report_v1)

    # 2차 실험 결과(고정): 제안대로 고분자 비율↓ + Crospovidone 2% 추가 후 재제조.
    result_v2 = WetLabResult(
        candidate_id="cand-solid-dispersion-v2",
        measurements={
            "dissolution_30min_percent": 88.0,  # 목표 충족
            "tablet_hardness_N": 78.0,
            "impurity_total_percent": 0.2,
            "assay_percent": 99.1,
        },
        notes="고분자 비율 하향 + Crospovidone 2% 추가 (v1 피드백 반영)",
    )
    report_v2 = interp.interpret(result_v2)
    print_report("2차 실험 결과 해석 (피드백 반영)", report_v2)

    print("\n──────────────────────────────")
    print(f"결과: 1차 이탈 {len(report_v1.off_target_findings)}건 → 재설계 → 2차 이탈 {len(report_v2.off_target_findings)}건")
    print("closed-loop:", "수렴(목표 충족) ✅" if not report_v2.reflection_needed else "추가 재설계 필요 ❌")


if __name__ == "__main__":
    main()
