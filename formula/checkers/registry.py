"""규칙 카탈로그(rulebook_manifest.yaml)를 읽어 검사기를 자동으로 연결한다.

동작 요약:
  1. 설정 파일(YAML)에서 규칙 목록을 읽는다.
  2. `trigger_priority` 오름차순 **스테이지**로 실행한다. 앞 스테이지가 산출한 파생값
     (flow_character, selected_route, bcs_class …)이 뒤 스테이지의 `applies_when`에 주입된다.
     → 폴더 순서로 순회하면 안 된다. 소아안전(05_regulatory)이 priority 2로 가장 먼저 돈다.
  3. 각 규칙이 '숫자로 판단 가능(quantitative)'이면 결정론적 검사 함수에 연결하고,
     '말로 판단 필요(qualitative)'이면 판단 에이전트(Judge) 명세로 넘긴다.
  4. 규칙(CSV)과 설정 한 줄만 추가하면 검사 능력이 확장된다. 백엔드 코드는 그대로.

근거가 약한 행(NO_SOURCE_FOUND / NOT_A_RULE / LEGACY)은 로딩 단계에서 아예 제외한다.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import yaml
from pydantic import BaseModel, Field

from formula.checkers.applies_when import evaluate, row_matches, spec_context
from formula.checkers.strategies import STRATEGIES
from formula.contracts import (
    EvalType,
    EvidencePolicy,
    FormulationSpec,
    JudgeSpec,
    Recipe,
    RulebookEntry,
    Verdict,
    VerdictStatus,
    evidence_policy,
)


class GateResult(BaseModel):
    """결정론 게이트 1회 실행의 전체 결과."""

    verdicts: List[Verdict] = Field(default_factory=list)
    derived: Dict[str, Any] = Field(default_factory=dict)  # 산출된 파생 state
    skipped_rows: int = 0  # 근거 부족으로 실행되지 않은 행 수
    stopped_at_priority: Optional[int] = None  # HARD_FAIL로 단락된 스테이지

    @property
    def failures(self) -> List[Verdict]:
        return [v for v in self.verdicts if v.failed]

    @property
    def blockers(self) -> List[Verdict]:
        return [v for v in self.verdicts if v.blocking]

    @property
    def escalations(self) -> List[Verdict]:
        return [v for v in self.verdicts if v.status == VerdictStatus.ESCALATE]

    @property
    def passed(self) -> bool:
        """자동 승인 가능한가.

        반려(HARD_FAIL)가 없어야 하고, **판정 보류(ESCALATE)도 없어야** 한다 —
        에스컬레이션은 "에이전트가 판정할 근거가 없다"는 뜻이라 통과로 셀 수 없다.
        """
        return not self.blockers and not self.escalations


class RulebookRegistry:
    """규칙 카탈로그를 로드하고, 입력에 맞는 검사기를 골라 실행한다."""

    def __init__(
        self,
        manifest_path: str | Path,
        base_dir: str | Path | None = None,
        reviewer_registry: str | Path | None = None,
    ):
        self.manifest_path = Path(manifest_path)
        self.base_dir = Path(base_dir) if base_dir else self.manifest_path.parent.parent
        self.entries: List[RulebookEntry] = self._load_manifest()
        self._rows_cache: Dict[str, Tuple[List[Dict[str, Any]], int]] = {}
        # 심사관 명단은 룰북 데이터(reviewer_registry.csv)가 정본이다.
        default_registry = self.base_dir / "database" / "06_config" / "reviewer_registry.csv"
        path = Path(reviewer_registry) if reviewer_registry else default_registry
        self.reviewer_registry_path = path if path.exists() else None
        self.packaging_categories = self._load_packaging_categories()

    def _load_packaging_categories(self) -> Dict[str, List[str]]:
        """포장 식별자 → 서술 범주 사전. 별칭도 같은 범주를 가리키도록 평탄화한다."""
        path = self.manifest_path.parent / "packaging_categories.yaml"
        if not path.exists():
            return {}
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        table: Dict[str, List[str]] = {}
        for key, spec in raw.items():
            traits = [str(t).lower() for t in (spec or {}).get("traits", [])]
            for alias in [key, *(spec or {}).get("aliases", [])]:
                table[str(alias).strip().lower()] = traits
        return table

    def packaging_traits(self, packaging: Optional[str]) -> List[str]:
        """처방의 포장 식별자를 룰북이 쓰는 서술 범주 목록으로 번역한다."""
        text = str(packaging or "").strip().lower()
        if not text:
            return []
        if text in self.packaging_categories:
            return self.packaging_categories[text]
        # 부분 일치 폴백 ("Alu-Alu blister (with desiccant)" 같은 자유 표기 대응)
        for alias, traits in self.packaging_categories.items():
            if alias in text or text in alias:
                return traits
        return []

    # ------------------------------------------------------------------
    # 로딩
    # ------------------------------------------------------------------
    def _load_manifest(self) -> List[RulebookEntry]:
        raw = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or []
        entries = [RulebookEntry(**item) for item in raw]
        return sorted(entries, key=lambda e: (e.trigger_priority, e.id))

    def _load_rows(self, entry: RulebookEntry) -> Tuple[List[Dict[str, Any]], int]:
        """규칙 CSV를 읽어 row_filter와 근거정책을 적용한 행 목록을 돌려준다."""
        cache_key = f"{entry.file}::{entry.row_filter}::{entry.id}"
        if cache_key in self._rows_cache:
            return self._rows_cache[cache_key]

        path = self.base_dir / entry.file
        if not path.exists():
            raise FileNotFoundError(f"[{entry.id}] 룰북 CSV 없음: {path}")
        df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")

        verification_col = entry.schema_map.get("verification_col", "verification_status")
        rows: List[Dict[str, Any]] = []
        skipped = 0
        for row in df.to_dict(orient="records"):
            if not row_matches(row, entry.row_filter):
                continue
            # 기록용/구기준 행은 판정에 쓰지 않는다(개발자 가이드 7장).
            if evidence_policy(row.get(verification_col)) is EvidencePolicy.SKIP:
                skipped += 1
                continue
            rows.append(row)

        self._rows_cache[cache_key] = (rows, skipped)
        return rows, skipped

    # ------------------------------------------------------------------
    # 정량(결정론) 측: 우선순위 스테이지 실행
    # ------------------------------------------------------------------
    def _stages(self) -> Iterable[Tuple[int, List[RulebookEntry]]]:
        buckets: Dict[int, List[RulebookEntry]] = defaultdict(list)
        for entry in self.entries:
            if entry.eval_type == EvalType.QUANTITATIVE:
                buckets[entry.trigger_priority].append(entry)
        for priority in sorted(buckets):
            yield priority, buckets[priority]

    def run(
        self,
        spec: FormulationSpec,
        recipe: Recipe,
        short_circuit: bool = True,
        derived: Optional[Dict[str, Any]] = None,
        on_verdict=None,
        max_priority: Optional[int] = None,
    ) -> GateResult:
        """발동되는 정량 규칙을 우선순위 순으로 실행하고 판정을 모은다.

        short_circuit: HARD_FAIL이 나오면 **그 스테이지까지만** 마치고 멈춘다.
            (같은 우선순위 규칙끼리는 서로를 참조하지 않으므로 함께 돌려도 안전하다)
        on_verdict:   판정 1건마다 호출되는 콜백 — 웹 UI 실시간 스트리밍용.
        max_priority: 여기까지의 스테이지만 실행한다(경로 확정 등 앞단만 돌릴 때).
        """
        result = GateResult(derived=dict(derived or {}))
        ctx = result.derived
        # 처방 자체의 선택(공정·포장)도 조건식에서 참조 가능해야 한다.
        # 예: direct_compression_rules 의 applies_when = "selected_route == 'DC' or process == ...".
        ctx.setdefault("process", recipe.process)
        ctx.setdefault("packaging", recipe.packaging)
        ctx.setdefault("packaging_traits", self.packaging_traits(recipe.packaging))
        ctx.setdefault("candidate_id", recipe.candidate_id)

        for priority, entries in self._stages():
            if max_priority is not None and priority > max_priority:
                break
            scope = spec_context(spec, ctx)
            for entry in entries:
                if not evaluate(entry.applies_when, scope):
                    continue
                strategy_fn = STRATEGIES.get(entry.strategy or "")
                if strategy_fn is None:
                    raise ValueError(f"[{entry.id}] 알 수 없는 전략: {entry.strategy!r}")
                rows, skipped = self._load_rows(entry)
                result.skipped_rows += skipped
                for verdict in strategy_fn(entry, rows, recipe, spec, ctx):
                    result.verdicts.append(verdict)
                    if on_verdict is not None:
                        on_verdict(verdict)
            if short_circuit and any(v.blocking for v in result.verdicts):
                result.stopped_at_priority = priority
                break
        return result

    def run_deterministic_gate(self, spec: FormulationSpec, recipe: Recipe) -> List[Verdict]:
        """하위호환 API — 판정 목록만 필요할 때. 전 스테이지를 끝까지 실행한다."""
        return self.run(spec, recipe, short_circuit=False).verdicts

    # ------------------------------------------------------------------
    # 정성(자연어 판단) 측: 발동될 Judge 명세 목록
    # ------------------------------------------------------------------
    def _registry_judges(self, scope: Dict[str, Any]) -> List[JudgeSpec]:
        """reviewer_registry.csv의 summon_condition으로 심사관을 동적 소집한다."""
        if self.reviewer_registry_path is None:
            return []
        df = pd.read_csv(self.reviewer_registry_path, dtype=str, keep_default_na=False).fillna("")
        judges: List[JudgeSpec] = []
        for row in df.to_dict(orient="records"):
            if not evaluate(row.get("summon_condition", "false"), scope):
                continue
            reviewer_id = row.get("reviewer_id", "")
            judges.append(
                JudgeSpec(
                    reviewer_id=reviewer_id,
                    persona=row.get("reviewer_name_kr") or row.get("reviewer_name_en", ""),
                    rubric_prompt=f"config/prompts/{row.get('reviewer_name_en', reviewer_id)}.txt",
                    retrieval_namespace=row.get("domain", ""),
                    weight=float(row.get("base_weight") or 1.0),
                    summon_condition=row.get("summon_condition", ""),
                )
            )
        return judges

    def active_judges(
        self,
        spec: FormulationSpec,
        derived: Optional[Dict[str, Any]] = None,
    ) -> List[JudgeSpec]:
        """이번 입력에서 동적으로 생성해야 할 판단 에이전트(Judge) 명세.

        두 출처를 합친다: reviewer_registry.csv(정본 명단) + 매니페스트의 qualitative 항목.
        """
        scope = spec_context(spec, derived)
        scope.setdefault("regulatory_narrative_needed", False)
        scope.setdefault("novel_combination_not_in_rulebook", False)
        judges = self._registry_judges(scope)
        seen = {j.reviewer_id for j in judges if j.reviewer_id}
        for entry in self.entries:
            if entry.eval_type != EvalType.QUALITATIVE or entry.judge is None:
                continue
            if not evaluate(entry.applies_when, scope):
                continue
            if entry.judge.reviewer_id and entry.judge.reviewer_id in seen:
                continue
            judges.append(entry.judge)
        return judges

    # ------------------------------------------------------------------
    def known_excipients(self) -> set:
        """부형제 마스터가 아는 성분명(소문자). 룰북 밖 조합을 판별하는 데 쓴다."""
        if getattr(self, "_known_excipients", None) is not None:
            return self._known_excipients

        names: set = set()
        for relative in ("database/00_master/excipient_master.csv",
                         "database/reference/excipient_master_iid.csv"):
            path = self.base_dir / relative
            if not path.exists():
                continue
            try:
                frame = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
            except Exception:
                continue
            for column in ("excipient_name", "excipient", "name", "ingredient_name"):
                if column in frame.columns:
                    names |= {str(v).strip().lower() for v in frame[column] if str(v).strip()}
        self._known_excipients = names
        return names

    # ------------------------------------------------------------------
    def summary(self) -> Dict[str, int]:
        counts = {"total": len(self.entries)}
        for eval_type in EvalType:
            counts[eval_type.value] = sum(1 for e in self.entries if e.eval_type == eval_type)
        counts["priorities"] = len({e.trigger_priority for e in self.entries})
        return counts
