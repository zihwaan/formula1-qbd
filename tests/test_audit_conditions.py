"""데이터 조건식 전수검사 — 모든 조건식의 변수 이름이 실제로 채워지는 이름이어야 한다(죽은 규칙 방지)."""

from scripts.audit_conditions import main


def test_no_condition_references_an_unknown_name():
    assert main() == 0
