"""Lab-in-the-loop — AI가 실험 결과를 읽고 **다음 실험을 지시**한다.

이 계층의 패러다임은 다음과 같다.

    AI가 가설을 세우고 → 결과 데이터를 직접 해석하고 → 다음 실험을 지시한다.
    사람은 벤치에서 그 실험을 수행하고 결과를 다시 넣는다.

즉 사람이 판단의 병목이 아니라 **실행 장치**로 들어오는 구조다(FutureHouse·Oxford·Fordham의
Robin이 제시한 lab-in-the-loop). 앞선 설계 루프가 "만들기 전에 컴퓨터에서 실패를 겪는" 것이라면,
여기는 "만든 뒤 실제 데이터로 다음 수를 정하는" 반대쪽 절반이다.

`DIRECTIVE_SYSTEM`(3단계 지시 프롬프트)은 Robin의 공개 프롬프트(`robin/prompts.py`,
Future-House/robin)에서 실제로 쓰는 두 패턴을 그대로 가져왔다.

1. **"정확히 N개의 *구별되는* 아이디어"** — Robin의 `CANDIDATE_GENERATION_SYSTEM_MESSAGE`는
   후보를 배열로 강제하며 "distinct"를 명시한다. 진단 가설도 배열(`hypotheses: list`)로
   강제하고, 겹치는 가설을 별도 항목으로 세지 못하게 금지한다 — v1(2026-09-16 배포)에서는
   `direct_next()`가 가설 문장 하나를 이탈 지표 수만큼 복제해 화면에 뿌렸는데, 그러면
   가설이 여러 개처럼 보여도 실제로는 갈라낼 원인이 하나뿐이라 구별시험이 무의미했다.
2. **"필요 없으면 만들지 않는다"** — Robin의 `FOLLOWUP_SYSTEM_MESSAGE`는 "후속 실험을
   제안할 필요가 없으면 제안하지 않아도 된다"고 명시한다. 여기서도 이탈이 없으면
   `hypotheses`를 빈 배열로 두게 강제해, 개수를 채우려고 가짜 가설을 만들지 않는다.

반대로 Robin이 하지 않는 것도 하나 그대로 유지한다 — Robin의 후속 실험 제안은 어세이
카테고리를 자유 텍스트로 적지만("RNA-seq", "Flow Cytometry" 등), 여기서는 시험을
`confirmation_test_master.csv`의 실제 66종으로 제한한다. 자유 텍스트 제안은 재현성 있는
근거를 남기지 못하기 때문이다.

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


class CompetingHypothesis(BaseModel):
    """이탈을 설명하는 경쟁 가설 1건.

    FutureHouse Robin의 후보 생성 프롬프트(`CANDIDATE_GENERATION_SYSTEM_MESSAGE`)는
    "정확히 N개의 **구별되는** 아이디어"를 배열로 강제한다 — 하나를 여러 각도로 재진술한
    게 아니라 실제로 다른 항목이어야 한다는 제약이다. 진단 가설에도 같은 제약을 건다:
    가설끼리 겹치면 애초에 구별시험으로 갈라낼 이유가 없다.
    """

    statement: str = Field(description="이 가설이 설명하는 인과 메커니즘 1~2문장. 다른 가설과 실제로 달라야 한다.")
    supports: List[str] = Field(default_factory=list, description="이 가설이 설명하는 이탈 지표(metric 키) 목록")
    test_ids: List[str] = Field(
        default_factory=list, max_length=2,
        description="이 가설을 다른 가설과 갈라낼 수 있는 확인시험 test_id. confirmation_test_master.csv 안에서만.",
    )
    why: str = Field(description="이 시험 결과가 어느 경우에 이 가설을 지지하고 어느 경우에 배제하는지 1문장")


class Directive(BaseModel):
    """AI가 내리는 다음 실험 지시 — 경쟁 가설의 배열."""

    hypotheses: List[CompetingHypothesis] = Field(default_factory=list, max_length=3)


READ_SYSTEM = """당신은 제제 연구실의 실험 노트를 정량 데이터로 옮기는 판독자다.

절대 규칙:
- **문장에 적힌 수치만 옮긴다.** 추정하지 않고, 환산하지 않고, 빈 값을 채우지 않는다.
- 단위가 다르면 그대로 두지 말고 지표의 단위로 맞춘다(예: 0.5분 → 30초가 아니라 분 단위 유지).
- 지표를 특정할 수 없으면 measurements에 넣지 말고 unreadable에 원문을 남긴다.
- 수치가 아닌 관찰(갈변, 캡핑, 스티킹 등)은 observations에 옮긴다.
- 판독은 해석이 아니다. 원인·대책을 쓰지 않는다."""

DIRECTIVE_SYSTEM = """당신은 제제 개발을 지휘하는 연구 책임자다. 실험 결과 해석을 받고
**서로 다른 원인 가설**을 세운 뒤, 각 가설을 갈라낼 수 있는 다음 시험을 고른다.

절대 규칙:
- 가설은 최대 3개, **서로 실제로 달라야 한다.** 같은 원인을 다르게 표현한 문장을 별도
  가설로 세지 않는다. 경쟁할 원인이 실제로 하나뿐이면 가설도 하나만 낸다 — 개수를
  채우려고 억지로 쪼개지 않는다. 이탈이 전혀 없으면 hypotheses를 빈 배열로 둔다.
- 가설은 **제공된 이탈 지표와 관찰에서만** 근거를 찾는다. 데이터에 없는 메커니즘을
  끌어오지 않는다.
- 시험은 **제공된 확인시험 목록에서만** 고른다. 목록에 없는 시험을 발명하면 안 된다.
  test_id는 목록에 있는 값을 그대로 쓴다.
- **각 가설에는 그 가설만 지지하거나 배제하는 시험을 배정한다.** 모든 가설에 같은
  시험을 반복해서 붙이지 않는다 — 그러면 애초에 가설을 가를 수 없다. 두 가설을 동시에
  가를 수 있는 시험이 있으면 그 시험을 우선한다.
- why는 "이 시험 결과가 어느 경우에 이 가설을 지지하고 어느 경우에 배제하는가"로 쓴다.
  일반론("품질 확인을 위해")을 쓰지 않는다."""


def _load_tests(base_dir: Path) -> pd.DataFrame:
    path = base_dir / "database" / "reference" / "confirmation_test_master.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")


# 이탈 지표 → 확인시험 카테고리. LLM이 없을 때의 결정론 폴백이자, LLM에게 주는 후보를
# 좁히는 필터로도 쓴다(66종 전부를 프롬프트에 넣으면 무료 티어 토큰 예산을 넘긴다).
METRIC_TO_CATEGORY: Dict[str, List[str]] = {
    "dissolution_30min_percent": ["Dissolution", "BCS", "Biopharmaceutics", "Bioperformance",
                                  "Solubility/dissolution", "Particle engineering"],
    "impurity_total_percent": ["Impurity analysis", "Analytical development", "Analytical validation"],
    # 타정압·마손도의 기계적 QC는 이 확인시험 마스터(생물약제학/BCS 확증 중심 66종)에
    # 대응하는 시험이 없다 — 억지로 매칭시키지 않는다. 빈 목록으로 두면 이 계층은 정직하게
    # "확인시험 후보 없음"을 내고, LifecycleService._fallback_diagnosis가 그 경우를 별도로
    # 다룬다(구별 용출 시험 T_DISCRIM으로 대신 좁히는 현실적 대안).
    "tablet_hardness_N": [],
    "friability_percent": [],
    "disintegration_time_min": ["Dissolution", "Solubility/dissolution", "Particle engineering"],
    "moisture_content_percent": ["Water determination"],
    "assay_percent": ["Analytical development", "Analytical validation"],
    "content_uniformity_rsd": ["Analytical development", "Analytical validation", "Sample preparation"],
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


def _test_detail(row: dict, why: str) -> Dict[str, object]:
    return {
        "test_id": row["test_id"],
        "test_name": row["test_name"],
        "test_category": row["test_category"],
        "test_design": row["test_design"],
        "output_variable": row["output_variable"],
        "acceptance_logic": row["acceptance_logic"],
        "unit": row.get("unit", ""),
        "source_reference": row.get("source_reference", ""),
        "source_url": row.get("source_url", ""),
        "why": why,
    }


def _resolve_hypotheses(directive: Directive, by_id: Dict[str, dict]) -> List[Dict[str, object]]:
    """LLM이 낸 가설 중 실제 목록에 있는 시험이 붙은 것만 남긴다.

    목록 밖 test_id를 쓴 가설, 또는 시험이 하나도 안 붙은 가설은 버린다 — 가를 시험이
    없는 가설은 "발명한 원인"과 다를 바 없다(이 시스템의 발명 금지 원칙, 시험 쪽에도 적용).
    """
    resolved = []
    for h in directive.hypotheses:
        test_ids = [t.strip() for t in h.test_ids if t.strip() in by_id][:2]
        if not test_ids:
            continue
        resolved.append({
            "statement": h.statement,
            "supports": [m for m in h.supports if m],
            "discriminating_test_ids": test_ids,
            "tests": [_test_detail(by_id[t], h.why) for t in test_ids],
        })
    return resolved


def direct_next(report: FeedbackReport, base_dir: Path,
                observations: Optional[List[str]] = None) -> Dict[str, object]:
    """해석 결과 → 서로 다른 원인 가설과 각 가설을 가를 시험.

    시험 후보는 실제 마스터 66종에서만 고른다. 반환 dict는 신·구 두 화면을 함께 지원한다 —
    `hypotheses`(배열)는 새 장기 실행 작업함의 경쟁 가설 카드가 읽고, `hypothesis`/`experiments`
    (단수·평탄화)는 기존 1회성 wetlab 패널이 그대로 읽는다.
    """
    tests = _load_tests(base_dir)
    if tests.empty:
        return {"hypothesis": "", "hypotheses": [], "experiments": [], "source": "no-master"}

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
            "이번 결과를 설명하는, 서로 다른 원인 가설을 최대 3개 세우고, "
            "가설마다 그것을 갈라낼 시험을 배정하라.",
            effort="low", wait_budget=LABLOOP_WAIT,
        )
        source = "llm"
    except LLMUnavailable:
        directive = _direct_fallback(off, by_id)
        source = "deterministic-fallback"

    resolved_hypotheses = _resolve_hypotheses(directive, by_id)

    if not resolved_hypotheses and off:  # 전부 걸러졌으면 결정론 폴백으로 채운다
        directive = _direct_fallback(off, by_id)
        resolved_hypotheses = _resolve_hypotheses(directive, by_id)
        source = "deterministic-fallback"

    # 구 wetlab 패널용 평탄화 — 가설 순서대로 시험을 모으되 중복 test_id는 한 번만.
    flat: List[Dict[str, object]] = []
    seen = set()
    for h in resolved_hypotheses:
        for t in h["tests"]:
            if t["test_id"] not in seen:
                seen.add(t["test_id"])
                flat.append(t)

    progression_hypothesis = ""
    if not off and not flat and by_id:
        # 이탈이 없는 경우는 "경쟁 원인"이 아니라 다음 단계로 넘어가는 확정 시험이 필요한
        # 경우다 — hypotheses(경쟁 원인 배열)에 억지로 채워 넣지 않고 구 wetlab 패널이 읽는
        # 평탄화 필드만 채운다. 진단(diagnosis) 경로는 이탈이 있을 때만 호출되므로 영향 없다.
        first_row = next(iter(by_id.values()))
        flat = [_test_detail(first_row, "이탈이 없어 다음 단계 확정 시험을 제안한다.")]
        progression_hypothesis = "[규칙 기반] 이탈이 없어 다음 단계 확정이 필요하다."

    return {
        "hypothesis": (resolved_hypotheses[0]["statement"] if resolved_hypotheses
                      else progression_hypothesis),
        "hypotheses": resolved_hypotheses,
        "experiments": flat,
        "source": source,
        "pool_size": len(by_id),
        "master_size": int(len(tests)),
    }


# 지표별 짧은 원인 가설 문장. LLM 없이도 "지표 하나 = 가설 하나"로 서로 다른 가설을 만든다.
METRIC_HYPOTHESIS_STATEMENTS: Dict[str, str] = {
    "dissolution_30min_percent": "붕해 지연 또는 결합력 과다로 방출이 억제됐을 가능성",
    "tablet_hardness_N": "타정압 또는 결합제 배합비가 목표 범위를 벗어났을 가능성",
    "impurity_total_percent": "배합 상호작용·산화·수분 노출로 분해가 진행됐을 가능성",
    "friability_percent": "과립 결합력 또는 압축 조건이 부족했을 가능성",
    "disintegration_time_min": "붕해제 종류·비율 또는 정제 경도가 붕해를 지연시켰을 가능성",
    "moisture_content_percent": "건조 조건 또는 포장의 수분 차단이 부족했을 가능성",
    "assay_percent": "혼합 균일도 또는 공정 중 손실로 함량이 벗어났을 가능성",
    "content_uniformity_rsd": "혼합 순서·시간 또는 API 입도가 균일도를 저해했을 가능성",
}


def _direct_fallback(off, by_id: Dict[str, dict]) -> Directive:
    """LLM 없이 만드는 지시 — 이탈 지표마다 별도 가설 하나씩(지표 하나 = 가설 하나).

    각 지표에 해당 카테고리의 시험을 배정하므로, 지표가 여러 개면 가설도 여러 개가 되고
    가설마다 붙는 시험도 자연히 달라진다 — LLM 경로가 요구하는 "가설을 가를 수 있는 시험"
    제약을 결정론 경로에서도 같은 모양으로 지킨다.
    """
    hypotheses: List[CompetingHypothesis] = []
    for finding in off[:3]:
        for test_id, row in by_id.items():
            if any(cat.lower() in row["test_category"].lower()
                   for cat in METRIC_TO_CATEGORY.get(finding.metric, [])):
                hypotheses.append(CompetingHypothesis(
                    statement=f"[규칙 기반] {METRIC_HYPOTHESIS_STATEMENTS.get(finding.metric, finding.metric + ' 이탈의 공정·배합 원인')}",
                    supports=[finding.metric],
                    test_ids=[test_id],
                    why=f"{finding.metric} 이탈에 대응하는 {row['test_category']} 계열 확인시험.",
                ))
                break
    # off가 비었을 때(이탈 없음)나, 이탈은 있지만 대응 카테고리가 없을 때(예: 마손도만
    # 이탈) 모두 hypotheses를 억지로 채우지 않는다. 전자는 direct_next()가 별도로
    # "다음 단계 확정" 제안을 만들고, 후자는 호출부(LifecycleService._fallback_diagnosis)가
    # 구별 용출 시험으로 좁히는 최종 폴백을 갖고 있다 — 여기서 근거 없는 매칭을 만들지 않는다.
    return Directive(hypotheses=hypotheses)
