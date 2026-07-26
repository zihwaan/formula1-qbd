"""Claude 기반 에이전트 계층.

역할 분담은 README의 원칙 그대로다 — **창의는 AI가, 검증은 규칙이.**
  intake    : 자연어 요구 → 정량 스펙        (창의/해석)
  generator : 전략 브리프 → 처방 후보        (창의)
  judge     : rubric → 정성 평가 점수        (판단)
  reflect   : 반려 사유 → 재설계 지시        (추론)
  consensus : 심사 결과 종합                 (결정론 — LLM 아님)

모든 노드는 자격증명이 없거나 호출이 실패하면 **결정론 폴백**으로 내려간다.
시연 중 네트워크·키 문제로 파이프라인이 멈추지 않게 하기 위한 설계다.
"""

from formula.agents.client import LLMUnavailable, credentials_available

__all__ = ["LLMUnavailable", "credentials_available"]
