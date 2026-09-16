"""direct_next()가 이탈 지표마다 서로 다른 가설과 그 가설만 가르는 시험을 내는지 고정한다.

FutureHouse Robin의 "정확히 N개의 구별되는 아이디어" 패턴을 진단 가설에 적용한 지점 —
가설 문장 하나를 지표 수만큼 복제하던 이전 동작(2026-09-16 배포분)으로 회귀하지 않도록 한다.
LLM 키 없이 돌아가는 결정론 폴백 경로만 검증한다(CI에 키가 없으므로).
"""

from pathlib import Path

from formula.contracts import FeedbackFinding, FeedbackReport
from formula.feedback.labloop import direct_next

ROOT = Path(__file__).resolve().parents[1]


def _finding(metric: str, measured: float, target: float, operator: str = "<") -> FeedbackFinding:
    return FeedbackFinding(metric=metric, measured=measured, operator=operator, target=target,
                           off_target=True, interpretation=f"{metric} 이탈")


def test_two_off_target_metrics_produce_two_distinct_hypotheses():
    # 확인시험 마스터(66종)는 생물약제학/BCS 확증 중심이라 tablet_hardness_N 같은 기계적
    # QC 지표는 대응 시험이 없다(의도된 데이터 공백, formula/feedback/labloop.py 주석 참고) —
    # 그래서 실제로 시험이 붙는 두 지표(용출·수분)로 검증한다.
    report = FeedbackReport(
        candidate_id="cand-1",
        findings=[
            _finding("dissolution_30min_percent", 58.0, 80.0),
            _finding("moisture_content_percent", 6.5, 4.0, operator=">"),
        ],
        reflection_needed=True,
    )
    directive = direct_next(report, ROOT)

    assert directive["source"] == "deterministic-fallback"  # 테스트 환경엔 LLM 키가 없다
    hypotheses = directive["hypotheses"]
    assert len(hypotheses) == 2

    statements = {h["statement"] for h in hypotheses}
    assert len(statements) == 2  # 가설 문장이 복제되지 않고 실제로 다르다

    # 가설마다 자기 지표에 해당하는 시험이 붙고, 서로 다른 시험이어야 가를 수 있다
    for h in hypotheses:
        assert h["discriminating_test_ids"], h
    test_id_sets = [set(h["discriminating_test_ids"]) for h in hypotheses]
    assert test_id_sets[0] != test_id_sets[1]

    # 구 wetlab 패널 하위호환 — 단수 hypothesis·평탄화 experiments가 여전히 채워진다
    assert directive["hypothesis"] == hypotheses[0]["statement"]
    assert len(directive["experiments"]) >= 2


def test_no_off_target_findings_returns_no_competing_hypotheses():
    """이탈이 없으면 "경쟁 원인" 배열은 비운다 — 원인 진단과 다음 단계 확정 제안은
    의미가 다르므로 hypotheses(경쟁 원인)에 억지로 채우지 않는다(구 wetlab 패널의
    "다음 단계 확정 시험 제안" 기능은 hypothesis/experiments 평탄화 필드로 유지된다)."""
    report = FeedbackReport(
        candidate_id="cand-1",
        findings=[FeedbackFinding(metric="assay_percent", measured=99.0, operator=">",
                                  target=95.0, off_target=False)],
        reflection_needed=False,
    )
    directive = direct_next(report, ROOT)
    assert directive["hypotheses"] == []
    assert directive["hypothesis"]  # 다음 단계 확정 제안 문구는 비어 있지 않다
    assert directive["experiments"]


def test_hypothesis_test_ids_are_always_from_the_real_master():
    report = FeedbackReport(
        candidate_id="cand-1",
        findings=[_finding("impurity_total_percent", 0.9, 0.5, operator=">")],
        reflection_needed=True,
    )
    directive = direct_next(report, ROOT)
    valid_ids = {e["test_id"] for e in directive["experiments"]}
    for h in directive["hypotheses"]:
        assert set(h["discriminating_test_ids"]) <= valid_ids
