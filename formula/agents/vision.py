"""첨부 이미지 해석 초안 — 이미지 입력이 되는 대회 API 모델로 측정 필드를 제안한다(측정값 입력 개선 요청서 과제 4).

- 제안은 **입력 칸을 채울 뿐** 자동 제출하지 않는다. 화면에 "미확인"으로 뜨고 연구자가 확정해야 들어간다.
- 받을 수 있는 필드는 그 측정의 필드 정의(measurement_output_fields.csv)뿐이고, 타입이 맞지 않는 값은 버린다.
- 무료 Groq 모델은 이미지를 받지 않으므로 대회 API가 아니면 해석하지 않는다(대신 채우지 않음).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from formula.agents import client as C
from formula.biopharm.triggers import check_value, load_output_fields


class FieldDraft(BaseModel):
    key: str
    value: Any = None
    rationale: str = ""


class VisionDraft(BaseModel):
    fields: List[FieldDraft] = Field(default_factory=list)
    notes: str = ""


SYSTEM = """당신은 약물 고체상 분석(XRPD·DSC·TGA·현미경 등) 결과 그림을 읽는 보조자다.
그림에서 **직접 읽히는 것만** 필드로 제안한다. 읽을 수 없거나 추정이 필요한 값은 제안하지 않는다(비워 둔다).
각 제안에는 그림의 어느 부분에서 읽었는지 rationale을 한 문장으로 쓴다. 판정·결론은 쓰지 않는다.
응답은 JSON 객체 하나: {"fields": [{"key": "...", "value": ..., "rationale": "..."}], "notes": "..."}"""


def interpret_image(measurement_id: str, image: bytes, media_type: str, base_dir: Path) -> Dict[str, Any]:
    if not C._dacon_key() or C._DACON_EXHAUSTED["flag"]:
        raise C.LLMUnavailable("이미지 해석은 대회 API 모델에서만 할 수 있습니다(무료 모델은 이미지를 받지 않음)")
    fields = {k: v for k, v in load_output_fields(Path(base_dir)).items() if v.get("measurement_id") == measurement_id}
    spec = "\n".join(
        f"- {k}: {v['field_type']}" + (f" (선택지: {v['enum_values']})" if v.get("enum_values") else "")
        + (f" [{v['unit']}]" if v.get("unit") else "") + f" — {v.get('label_kr', '')}" for k, v in fields.items())
    url = f"data:{media_type};base64,{base64.b64encode(image).decode()}"
    payload = {"model": C.DACON_MODEL, "instructions": SYSTEM, "reasoning": {"effort": "low"},
               "max_output_tokens": 2000, "text": {"format": {"type": "json_object"}},
               "input": [{"role": "user", "content": [
                   {"type": "input_text", "text": f"측정: {measurement_id}\n받을 수 있는 필드(json으로 답하라):\n{spec}"},
                   {"type": "input_image", "image_url": url}]}]}
    httpx = C._httpx()
    try:
        res = httpx.post(f"{C.DACON_BASE_URL}/responses", headers=C._dacon_headers(), json=payload,
                         timeout=C.DACON_TIMEOUT)
        res.raise_for_status()
        draft = VisionDraft.model_validate_json(C._strip_fence(C._dacon_text(res.json())))
    except Exception as exc:   # noqa: BLE001
        raise C._dacon_fail(exc) from exc
    C._count("dacon")
    kept, dropped = {}, []
    reasons = {}
    for f in draft.fields:
        if f.key not in fields or f.value in (None, ""):
            dropped.append(f.key)
            continue
        value = f.value
        t = fields[f.key]["field_type"]
        if t == "number" and isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                dropped.append(f.key)
                continue
        if t == "bool" and isinstance(value, str):
            value = {"true": True, "false": False, "예": True, "아니오": False}.get(value.strip().lower(), value)
        if check_value(f.key, value, fields) is not None:
            dropped.append(f.key)
            continue
        kept[f.key] = value
        reasons[f.key] = f.rationale
    return {"method": "vision_draft", "model": C.DACON_MODEL, "fields": kept, "rationale": reasons,
            "dropped": dropped, "notes": draft.notes, "status": "미확인"}
