"""v3 — 페이즈 게이트(BCS/DCS·고체상·가용화 전략)와 lab-in-the-loop 데이터 요청.

Formula1_v3/IMPLEMENTATION_GUIDE.md의 §2~§5를 구현한다. 이 패키지가 산출하는 파생값은
전부 `formula.checkers.registry.RulebookRegistry.run(..., derived=...)`가 받는 ctx
시드로 흘러 들어간다 — 기존 배합금기·공정 룰북과 같은 파생 state를 공유하지, 별도
세계를 만들지 않는다.
"""

from formula.biopharm.derived import compute_derived_quantities
from formula.biopharm.gates import evaluate_gate, run_biopharm_gates
from formula.biopharm.seed import seed_known_keys
from formula.biopharm.triggers import evaluate_triggers

__all__ = [
    "compute_derived_quantities",
    "evaluate_gate",
    "run_biopharm_gates",
    "evaluate_triggers",
    "seed_known_keys",
]
