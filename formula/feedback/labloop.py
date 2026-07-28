"""Lab-in-the-loop — AI가 실험 결과를 읽고 **다음 실험을 지시**한다.

이 계층의 패러다임은 다음과 같다.

    AI가 가설을 세우고 → 결과 데이터를 직접 해석하고 → 다음 실험을 지시한다.
    사람은 벤치에서 그 실험을 수행하고 결과를 다시 넣는다.

즉 사람이 판단의 병목이 아니라 **실행 장치**로 들어오는 구조다(FutureHouse·Oxford·Fordham의
Robin이 제시한 lab-in-the-loop). 앞선 설계 루프가 "만들기 전에 컴퓨터에서 실패를 겪는" 것이라면,
여기는 "만든 뒤 실제 데이터로 다음 수를 정하는" 반대쪽 절반이다.

세 단계로 나뉘고, 각 단계의 담당이 다르다 — 이 프로젝트의 대원칙(창의는 AI, 판정은 규칙)을
wet-lab 쪽에도 그대로 적용한다.

  1. **판독 (LLM)** — 연구원이 쓴 자연어 실험 노트에서 측정값을 뽑아낸다.
     오직 *문장에 적힌* 수치만 옮기고, 없는 값은 지어내지 않는다.
  2. **판정 (규칙)** — `WetLabInterpreter`가 규격 이탈을 계산한다. 결정론이라 같은 데이터면
     같은 해석이 나온다. LLM은 여기에 개입하지 않는다.
  3. **지시 (LLM + 참조 데이터)** — 이탈 지표에 대해 다음에 무슨 실험을 해야 하는지 정한다.
     **후보는 `confirmation_test_master.csv`의 실제 66종 확인시험뿐이다.** LLM은 그 안에서
     고르고 이유를 쓸 뿐, 시험을 발명하지 못한다. 그래서 모든 지시에 출처(ICH/USP 등)가 붙는다.

LLM이 없으면 1단계는 정규식 판독으로, 3단계는 카테고리 매칭으로 내려간다 — 화면은 계속 돈다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, Field

from formula.agents.client import LLMUnavailable, parse_structured
from formula.contracts import FeedbackReport

# 설계 실행 직후엔 분당 토큰이 거의 비어 있다. 이 두 호출은 사용자가 직접 누른 짧은 요청이라
# 규칙 기반 대체로 내려가는 것보다 조금 더 기다려 실제 판독·지시를 받는 편이 낫다.
LABLOOP_WAIT = 150.0

# 지표별 자연어 판독 힌트. 키는 wetlab_feedback_rules.csv 의 metric 과 일치해야 한다.
METRIC_HINTS: Dict[str, str] = {
    "dissolution_30min_percent": "30분 용출률(%) — '용출', '방출', 'dissolution'",
    "tablet_hardness_N": "정제 경도(N, 뉴턴) — '경도', '강도', 'hardness'",
    "impurity_total_percent": "총 불순물(%) — '불순물', '유연물질', 'impurity'",
    "friability_percent": "마손도(%) — '마손도', 'friability'",
    "disintegration_time_min": "붕해 시간(분) — '붕해', 'disintegration'",
    "moisture_content_percent": "수분 함량(%) — '수분', 'LOD', 'moisture'",
    "assay_percent": "함량(%) — '함량', 'assay'",
    "content_uniformity_rsd": "함량균일성 RSD(%) — '균일성', 'RSD'",
}


class ReadResult(BaseModel):
    """자연어 노트 판독 결과."""

    measurements: Dict[str, float] = Field(
        default_factory=dict,
        description="문장에 명시된 지표만. 추정·환산·보간 금지. 키는 제공된 지표명 그대로.",
    )
    observations: List[str] = Field(
        default_factory=list,
        description="수치가 아닌 관찰(색 변화·점착·캡핑 등)을 원문 표현에 가깝게",
    )
    unreadable: List[str] = Field(
        default_factory=list,
        description="지표를 특정할 수 없거나 단위가 모호해 옮기지 못한 표현",
    )


class NextExperiment(BaseModel):
    """다음에 수행할 확인시험 1건 (AI의 지시)."""

    test_id: str = Field(description="confirmation_test_master.csv 의 test_id 중 하나")
    why: str = Field(description="이번 이탈 지표와 어떻게 연결되는지 1~2문장")
    priority: int = Field(default=2, ge=1, le=3, description="1=먼저, 3=나중")


class Directive(BaseModel):
    """AI가 내리는 다음 실험 지시 묶음."""

    hypothesis: str = Field(description="이번 결과를 설명하는 가설 1~2문장")
    experiments: List[NextExperiment] = Field(default_factory=list)


READ_SYSTEM = """당신은 제제 연구실의 실험 노트를 정량 데이터로 옮기는 판독자다.

절대 규칙:
- **문장에 적힌 수치만 옮긴다.** 추정하지 않고, 환산하지 않고, 빈 값을 채우지 않는다.
- 단위가 다르면 그대로 두지 말고 지표의 단위로 맞춘다(예: 0.5분 → 30초가 아니라 분 단위 유지).
- 지표를 특정할 수 없으면 measurements에 넣지 말고 unreadable에 원문을 남긴다.
- 수치가 아닌 관찰(갈변, 캡핑, 스티킹 등)은 observations에 옮긴다.
- 판독은 해석이 아니다. 원인·대책을 쓰지 않는다."""

DIRECTIVE_SYSTEM = """당신은 제제 개발을 지휘하는 연구 책임자다. 실험 결과 해석을 받고
**다음에 무슨 실험을 해야 하는지** 정한다.

절대 규칙:
- 시험은 **제공된 확인시험 목록에서만** 고른다. 목록에 없는 시험을 발명하면 안 된다.
- test_id는 목록에 있는 값을 그대로 쓴다.
- 이탈한 지표를 실제로 규명·해결하는 데 기여하는 시험만 고른다. 최대 3건.
- **why는 "어느 이탈 지표를 규명하는가"로 시작한다.** 지표 이름을 먼저 적고, 그 시험이
  그 지표의 원인을 어떻게 좁히는지 잇는다. 다른 지표의 사유를 끌어다 붙이면 안 된다.
- 일반론("품질 확인을 위해")을 쓰지 않는다. 시험 하나는 지표 하나에 대응시킨다.
- 이탈이 없으면 다음 단계 확정(안정성·스케일업 등)에 필요한 시험을 고른다."""


def _load_tests(base_dir: Path) -> pd.DataFrame:
    path = base_dir / "database" / "reference" / "confirmation_test_master.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")


# 이탈 지표 → 확인시험 카테고리. LLM이 없을 때의 결정론 폴백이자, LLM에게 주는 후보를
# 좁히는 필터로도 쓴다(66종 전부를 프롬프트에 넣으면 무료 티어 토큰 예산을 넘긴다).
METRIC_TO_CATEGORY: Dict[str, List[str]] = {
    "dissolution_30min_percent": ["Dissolution", "BCS", "Biopharmaceutics"],
    "impurity_total_percent": ["Stability", "Analytical development", "Impurities"],
    "tablet_hardness_N": ["Process", "Compaction", "Tabletting"],
    "friability_percent": ["Process", "Compaction", "Tabletting"],
    "disintegration_time_min": ["Dissolution", "Process"],
    "moisture_content_percent": ["Stability", "Process", "Packaging"],
    "assay_percent": ["Analytical development", "Stability"],
    "content_uniformity_rsd": ["Process", "Analytical development", "Blend uniformity"],
}


def _candidate_tests(tests: pd.DataFrame, metrics: List[str]) -> pd.DataFrame:
    """이탈 지표와 관련된 카테고리의 시험만 남긴다. 못 좁히면 전체를 준다."""
    if tests.empty:
        return tests
    wanted: List[str] = []
    for metric in metrics:
        wanted += METRIC_TO_CATEGORY.get(metric, [])
    if not wanted:
        return tests
    mask = tests["test_category"].str.contains("|".join(re.escape(w) for w in set(wanted)),
                                               case=False, na=False)
    subset = tests[mask]
    return subset if not subset.empty else tests


def read_notes(notes: str, base_dir: Path) -> ReadResult:
    """자연어 실험 노트 → 측정값. LLM이 없으면 정규식으로 판독한다."""
    if not notes.strip():
        return ReadResult()

    listing = "\n".join(f"- {key}: {hint}" for key, hint in METRIC_HINTS.items())
    try:
        return parse_structured(
            ReadResult, READ_SYSTEM,
            f"## 옮길 수 있는 지표\n{listing}\n\n## 실험 노트\n{notes}",
            effort="low", wait_budget=LABLOOP_WAIT,
        )
    except LLMUnavailable:
        return _read_fallback(notes)


# "용출 45%", "경도 55 N", "불순물 0.8 %" 같은 표현을 잡는다.
_NUM = r"(-?\d+(?:\.\d+)?)"
_FALLBACK_PATTERNS: List[tuple] = [
    ("dissolution_30min_percent", rf"(?:용출|방출|dissolution)\D{{0,12}}{_NUM}\s*%"),
    ("tablet_hardness_N", rf"(?:경도|강도|hardness)\D{{0,12}}{_NUM}\s*(?:N\b|뉴턴)"),
    ("impurity_total_percent", rf"(?:불순물|유연물질|impurit\w*)\D{{0,12}}{_NUM}\s*%"),
    ("friability_percent", rf"(?:마손도|friability)\D{{0,12}}{_NUM}\s*%"),
    ("disintegration_time_min", rf"(?:붕해|disintegration)\D{{0,12}}{_NUM}\s*(?:분|min)"),
    ("moisture_content_percent", rf"(?:수분|moisture|LOD)\D{{0,12}}{_NUM}\s*%"),
    ("assay_percent", rf"(?:함량|assay)\D{{0,12}}{_NUM}\s*%"),
    ("content_uniformity_rsd", rf"(?:RSD|균일성)\D{{0,12}}{_NUM}\s*%"),
]


def _read_fallback(notes: str) -> ReadResult:
    """LLM 없이 도는 판독기 — 지표 키워드 + 숫자 + 단위 패턴만 본다."""
    found: Dict[str, float] = {}
    for metric, pattern in _FALLBACK_PATTERNS:
        match = re.search(pattern, notes, re.IGNORECASE)
        if match:
            try:
                found[metric] = float(match.group(1))
            except ValueError:
                continue
    observations = [
        phrase for keyword, phrase in (
            ("갈변", "갈변 관찰"), ("변색", "변색 관찰"), ("캡핑", "캡핑 발생"),
            ("스티킹", "스티킹 발생"), ("점착", "점착 발생"), ("층분리", "층분리 관찰"),
        ) if keyword in notes
    ]
    return ReadResult(measurements=found, observations=observations,
                      unreadable=[] if found else ([notes.strip()[:120]] if notes.strip() else []))


def direct_next(report: FeedbackReport, base_dir: Path,
                observations: Optional[List[str]] = None) -> Dict[str, object]:
    """해석 결과 → 다음 실험 지시. 시험 후보는 실제 마스터 66종에서만 고른다."""
    tests = _load_tests(base_dir)
    if tests.empty:
        return {"hypothesis": "", "experiments": [], "source": "no-master"}

    off = [f for f in report.findings if f.off_target]
    candidates = _candidate_tests(tests, [f.metric for f in off])
    by_id = {row["test_id"]: row for row in candidates.to_dict(orient="records")}

    listing = "\n".join(
        f"- {row['test_id']} · {row['test_name']} [{row['test_category']}] "
        f"측정: {row['output_variable']} · 판정: {row['acceptance_logic']}"
        for row in list(by_id.values())[:28]
    )
    finding_text = "\n".join(
        f"- {f.metric} = {f.measured} (목표 {f.operator}{f.target} 이탈) — {f.interpretation}"
        for f in off
    ) or "- 이탈 지표 없음 (모든 측정값이 규격 충족)"
    observed = "\n".join(f"- {o}" for o in (observations or [])) or "- 특기 관찰 없음"

    try:
        directive = parse_structured(
            Directive, DIRECTIVE_SYSTEM,
            f"## 실험 결과 해석 (결정론 판정)\n{finding_text}\n\n"
            f"## 비정량 관찰\n{observed}\n\n"
            f"## 선택 가능한 확인시험\n{listing}\n\n"
            "다음에 수행할 시험을 최대 3건 고르고, 이번 결과를 설명하는 가설을 함께 써라.",
            effort="low", wait_budget=LABLOOP_WAIT,
        )
        source = "llm"
    except LLMUnavailable:
        directive = _direct_fallback(off, by_id)
        source = "deterministic-fallback"

    # LLM이 목록 밖 test_id를 냈으면 버린다 — 발명한 시험을 지시로 내보내지 않는다.
    resolved = []
    for item in directive.experiments:
        row = by_id.get(item.test_id.strip())
        if row is None:
            continue
        resolved.append({
            "test_id": row["test_id"],
            "test_name": row["test_name"],
            "test_category": row["test_category"],
            "test_design": row["test_design"],
            "output_variable": row["output_variable"],
            "acceptance_logic": row["acceptance_logic"],
            "unit": row.get("unit", ""),
            "source_reference": row.get("source_reference", ""),
            "source_url": row.get("source_url", ""),
            "why": item.why,
            "priority": item.priority,
        })
    resolved.sort(key=lambda e: e["priority"])

    if not resolved:  # 전부 걸러졌으면 결정론 폴백으로 채운다(빈 지시를 내보내지 않는다)
        fallback = _direct_fallback(off, by_id)
        resolved = [{
            **{k: by_id[e.test_id][k] for k in
               ("test_id", "test_name", "test_category", "test_design",
                "output_variable", "acceptance_logic")},
            "unit": by_id[e.test_id].get("unit", ""),
            "source_reference": by_id[e.test_id].get("source_reference", ""),
            "source_url": by_id[e.test_id].get("source_url", ""),
            "why": e.why, "priority": e.priority,
        } for e in fallback.experiments if e.test_id in by_id]
        source = "deterministic-fallback"

    return {
        "hypothesis": directive.hypothesis,
        "experiments": resolved,
        "source": source,
        "pool_size": len(by_id),
        "master_size": int(len(tests)),
    }


def _direct_fallback(off, by_id: Dict[str, dict]) -> Directive:
    """LLM 없이 만드는 지시 — 이탈 지표의 카테고리에서 앞쪽 시험을 그대로 고른다."""
    picks: List[NextExperiment] = []
    for finding in off[:3]:
        for test_id, row in by_id.items():
            if any(cat.lower() in row["test_category"].lower()
                   for cat in METRIC_TO_CATEGORY.get(finding.metric, [])):
                picks.append(NextExperiment(
                    test_id=test_id,
                    why=f"[규칙 기반] {finding.metric} 이탈에 대응하는 "
                        f"{row['test_category']} 계열 확인시험.",
                    priority=1,
                ))
                break
    if not picks and by_id:
        first = next(iter(by_id))
        picks.append(NextExperiment(
            test_id=first, why="[규칙 기반] 이탈이 없어 다음 단계 확정 시험을 제안한다.", priority=2))
    return Directive(
        hypothesis="[규칙 기반] LLM 미사용 — 이탈 지표의 시험 카테고리만으로 선정했다.",
        experiments=picks,
    )
