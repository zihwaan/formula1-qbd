"""Formula 1 팀 — QbD 오케스트레이터 기반 매니페스트 구동형 검증 레지스트리.

핵심 아이디어: 룰북(CSV)마다 매니페스트가 "정량(quantitative)이면 결정론적 체커 툴로,
정성(qualitative)이면 Judge 에이전트로" 배선 방식을 스스로 선언한다.
백엔드 코드를 건드리지 않고 CSV + 매니페스트 한 줄만으로 검증 능력을 확장한다.
"""

__all__ = ["contracts", "checkers"]
