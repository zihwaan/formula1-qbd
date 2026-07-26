"""합의 도출 — **결정론**. LLM이 개입하지 않는다.

`database/06_config/severity_scoring_config.csv`(B모델)를 그대로 구동한다:

  · score_affects_pass_fail = false  → 심사관 점수는 후보를 반려시키지 못한다.
    반려 권한은 오직 룰북 HARD_FAIL에만 있다("규칙 = 거부권" 원칙).
  · aggregation_method = weighted_mean_summoned_only
    → 소집된 심사관의 base_weight만 그 세션 안에서 재정규화(합=1)한 뒤 가중평균.
  · tie_breaking = lower_variance_first  → 동점이면 심사관 간 이견이 적은 후보 우선.
  · min_reviewers_for_ranking = 2       → 1명이면 순위는 매기되 저신뢰 플래그.
  · all_candidates_reported = true       → 최하위 후보도 점수·사유와 함께 보고.
  · low_score_to_rulebook_feedback = true→ 반복 저점은 '룰북 누락 가능성'으로 기록.
"""

from __future__ import annotations

import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from formula.contracts import JudgeVerdict

DEFAULT_CONFIG = "database/06_config/severity_scoring_config.csv"


@lru_cache(maxsize=4)
def load_config(base_dir: Path, csv_path: str = DEFAULT_CONFIG) -> Dict[str, str]:
    path = base_dir / csv_path
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
    return {r["config_key"]: r["config_value"] for r in df.to_dict(orient="records")}


def _as_bool(value: str, default: bool = False) -> bool:
    return str(value).strip().lower() in ("true", "yes", "1") if value else default


def normalize_weights(verdicts: List[JudgeVerdict]) -> Dict[str, float]:
    """소집된 심사관들의 가중치를 세션 안에서 재정규화한다(합=1).

    고정 명단이 없으므로 절대 가중치의 합은 1이 아니다 — 매 세션 정규화가 필수다.
    예: 소아(0.30) + 공정(0.25)만 소집 → 0.545 / 0.455
    """
    total = sum(max(v.weight, 0.0) for v in verdicts)
    if total <= 0:
        share = 1.0 / len(verdicts) if verdicts else 0.0
        return {v.reviewer_id or v.persona: share for v in verdicts}
    return {(v.reviewer_id or v.persona): max(v.weight, 0.0) / total for v in verdicts}


def score_candidate(verdicts: List[JudgeVerdict]) -> Dict[str, Any]:
    """후보 1개의 심사 결과를 가중평균 점수로 종합한다."""
    if not verdicts:
        return {"weighted_score": None, "variance": None, "reviewers": 0, "weights": {}}
    weights = normalize_weights(verdicts)
    scores = [v.score for v in verdicts]
    weighted = sum(v.score * weights[v.reviewer_id or v.persona] for v in verdicts)
    variance = statistics.pvariance(scores) if len(scores) > 1 else 0.0
    return {
        "weighted_score": round(weighted, 4),
        "variance": round(variance, 4),
        "reviewers": len(verdicts),
        "weights": {k: round(w, 3) for k, w in weights.items()},
        "scores": {(v.reviewer_id or v.persona): v.score for v in verdicts},
    }


def build_consensus(
    results: List[Dict[str, Any]],
    judge_verdicts: List[JudgeVerdict],
    base_dir: Path,
) -> Dict[str, Any]:
    """게이트 결과 + 심사 결과 → 최종 순위와 선정.

    results: [{candidate_id, passed, blockers, verdicts...}, ...]
    """
    config = load_config(base_dir)
    min_reviewers = int(float(config.get("min_reviewers_for_ranking", 2) or 2))
    score_blocks = _as_bool(config.get("score_affects_pass_fail", "false"))

    by_candidate: Dict[str, List[JudgeVerdict]] = {}
    for verdict in judge_verdicts:
        by_candidate.setdefault(verdict.rulebook_id, []).append(verdict)

    ranked: List[Dict[str, Any]] = []
    for result in results:
        candidate_id = result.get("candidate_id", "")
        summary = score_candidate(by_candidate.get(candidate_id, []))
        # 반려 여부는 오직 룰북 HARD_FAIL이 정한다 — 점수는 순위에만 쓴다.
        eligible = bool(result.get("passed"))
        ranked.append({
            "candidate_id": candidate_id,
            "eligible": eligible,
            "blockers": result.get("blockers", []),
            "low_confidence": summary["reviewers"] < min_reviewers,
            **summary,
        })

    # 통과 후보만 순위 경쟁. 동점이면 분산이 낮은(이견이 적은) 쪽 우선.
    contenders = [r for r in ranked if r["eligible"]]
    contenders.sort(key=lambda r: (-(r["weighted_score"] or 0.0), r["variance"] or 0.0, r["candidate_id"]))
    for rank, row in enumerate(contenders, start=1):
        row["rank"] = rank

    winner = contenders[0]["candidate_id"] if contenders else None

    # 반복 저점은 룰북 커버리지 부족 신호로 기록한다(B모델의 안전판)
    feedback: List[str] = []
    if _as_bool(config.get("low_score_to_rulebook_feedback", "true"), True):
        for row in contenders:
            if (row["weighted_score"] or 1.0) < 0.5:
                feedback.append(
                    f"{row['candidate_id']}: 심사 점수 {row['weighted_score']} — "
                    f"룰북이 못 잡은 위험이 있을 수 있음(룰북 보강 후보)"
                )

    return {
        "model": config.get("consensus_model", "B_quality_ranking"),
        "score_affects_pass_fail": score_blocks,
        "winner": winner,
        "ranked": ranked,
        "contenders": contenders,
        "min_reviewers_for_ranking": min_reviewers,
        "rulebook_feedback": feedback,
        # 전 후보 보고 — 최하위도 버리지 않는다(all_candidates_reported)
        "reported": len(ranked),
    }
