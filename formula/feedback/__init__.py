"""Lab-in-the-loop 계층: AI가 실험 결과를 판독·해석하고 **다음 실험을 지시**한다.

AI가 판단의 주체이고 사람은 벤치에서 지시된 실험을 수행한다(FutureHouse·Oxford·Fordham의
Robin이 제시한 lab-in-the-loop). 판독과 지시는 LLM, 규격 판정은 결정론 규칙이 맡는다 —
설계 루프와 같은 역할 분담이다. 상세는 `labloop.py`.
"""

from formula.feedback.interpreter import WetLabInterpreter

__all__ = ["WetLabInterpreter"]
