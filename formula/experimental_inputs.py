"""실험 데이터 입력 카탈로그 — 사용자가 처음부터 넣는 실측값의 **허용목록**.

이 계층이 존재하는 이유는 두 가지다.

1. **보안.** 여기 값들은 룰북 조건식(`applies_when`)이 평가되는 문맥에 그대로 합쳐진다.
   임의 키를 받으면 사용자가 `is_pediatric`이나 `flag` 같은 문맥 이름을 덮어써서 판정을
   비틀 수 있다. 그래서 카탈로그에 있는 키만 통과시키고 나머지는 버린다(조용히 버리지 않고
   `rejected`로 돌려준다 — 오타를 삼키면 아무 규칙도 안 도는데 이유를 알 수 없다).
2. **설명 가능성.** 어떤 값을 넣으면 무엇이 달라지는지(`unlocks`)를 화면이 그대로 읽어
   보여준다. 빈칸을 채울 이유가 없으면 아무도 실측값을 넣지 않는다.

카탈로그는 `config/experimental_inputs.yaml`이고, 항목 추가는 데이터 편집이지 코드 수정이 아니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

CATALOG_FILE = Path("config") / "experimental_inputs.yaml"


class ExperimentalInputs:
    """카탈로그 로더 + 입력 정규화기."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.groups: List[Dict[str, Any]] = []
        self.fields: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        path = self.base_dir / CATALOG_FILE
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.groups = data.get("groups", []) or []
        for group in self.groups:
            for field in group.get("fields", []) or []:
                key = (field.get("key") or "").strip()
                if key:
                    self.fields[key] = {**field, "group": group.get("id", "")}

    # ── 조회 ────────────────────────────────────────────────────────
    def catalog(self) -> Dict[str, Any]:
        """화면이 폼을 그릴 때 쓰는 표현."""
        return {"groups": self.groups, "count": len(self.fields)}

    def numeric_keys(self) -> List[str]:
        return [k for k, f in self.fields.items() if f.get("type", "number") == "number"]

    def boolean_keys(self) -> List[str]:
        return [k for k, f in self.fields.items() if f.get("type") == "bool"]

    # ── 정규화 ──────────────────────────────────────────────────────
    def normalize(
        self,
        measured: Dict[str, Any] | None = None,
        flags: Dict[str, Any] | None = None,
    ) -> Tuple[Dict[str, float], Dict[str, bool], List[str]]:
        """입력을 (실측값, 플래그, 거부된 키)로 가른다.

        범위를 벗어난 값도 거부한다 — 안식각 480°가 조용히 들어가면 유동성 등급이
        엉뚱하게 나오고, 그 판정이 어디서 틀렸는지 추적하기 어려워진다.
        """
        numbers: Dict[str, float] = {}
        booleans: Dict[str, bool] = {}
        rejected: List[str] = []

        for key, raw in (measured or {}).items():
            field = self.fields.get(key)
            if field is None or field.get("type", "number") != "number":
                rejected.append(key)
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                rejected.append(key)
                continue
            low, high = field.get("min"), field.get("max")
            if (low is not None and value < float(low)) or (high is not None and value > float(high)):
                rejected.append(key)
                continue
            numbers[key] = value

        for key, raw in (flags or {}).items():
            field = self.fields.get(key)
            if field is None or field.get("type") != "bool":
                rejected.append(key)
                continue
            booleans[key] = bool(raw)

        return numbers, booleans, rejected

    def summary(self, measured: Dict[str, float], flags: Dict[str, bool]) -> List[Dict[str, str]]:
        """무엇이 들어왔고 그게 무엇을 여는지 — 트레이스/화면에 남길 설명."""
        out: List[Dict[str, str]] = []
        for key, value in {**measured, **flags}.items():
            field = self.fields.get(key, {})
            out.append({
                "key": key,
                "label": field.get("label", key),
                "value": ("예" if value is True else "아니오" if value is False
                          else f"{value}{field.get('unit', '')}"),
                "unlocks": field.get("unlocks", ""),
            })
        return out
