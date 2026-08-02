"""물성 예측 계층 — 교차검증·불확실성 정량화·BCS 도출.

팀 리뷰에서 나온 요구를 구현한다.

  1. **불확실성을 정량 기준으로 명시한다.** "여러 값이 있다"가 아니라 두 LogS 예측값의
     편차가 임계(기본 1 log unit)를 넘으면 고불확실성으로 판정한다. 용해도 예측은 ADMET
     속성 중에서도 불확실성이 크므로(SolTranNet 논문 기준 held-out RMSE ≈ 1.7 log),
     단일 점추정을 믿는 대신 **모델 간 불일치 자체를 신호로 쓴다.**
  2. **그 신호를 확인시험 요청으로 잇는다.** 고불확실성이면 실험 용해도 측정을 필수로
     올린다 — 예측 신뢰도 기반 확인시험 트리거.
  3. **BCS 분류를 명시적 노드로 뽑는다.** LogS와 Caco-2가 함께 있으면 등급을 도출해
     이후 후보 생성 전략(가용화 필요 여부)이 참조할 수 있게 한다.

**예측기를 연결하지 않은 상태에서 숫자를 지어내지 않는다.** 기준서 §13이 못 박은 대로
RDKit/SMARTS만으로 용해도·투과도·BCS를 판정할 수 없고, 데이터가 없으면 Safe가 아니라
`request_data`를 돌려준다. 각 예측기는 `available()`로 설치 여부를 스스로 보고하며,
미설치면 결과에 `status="not_connected"`가 남는다.

예측기를 붙이는 방법: 아래 `PREDICTORS`에 어댑터를 추가하면 된다. 어댑터는
`(smiles) -> Optional[float]`와 `available() -> bool`만 만족하면 되고, 나머지 로직
(교차검증·불확실성·BCS·시험 승격)은 그대로 작동한다.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# 두 LogS 예측값이 이만큼 벌어지면 고불확실성으로 본다(팀 리뷰 제안: 1 log unit).
LOGS_DISAGREEMENT_THRESHOLD = 1.0

# ICH M9 기준은 실험으로 판단한다. 아래 경계는 **예측값 기반 사전 분류**이며
# 규제 판정을 대체하지 않는다(기준서 §2.1 BCS 경계, §13).
LOGS_HIGH_SOLUBILITY = -4.0      # log mol/L, 이보다 크면 고용해도 후보
CACO2_HIGH_PERMEABILITY = -5.15  # log cm/s, 이보다 크면 고투과도 후보


@dataclass
class Predictor:
    """외부 예측 모델 어댑터.

    `module`이 임포트되지 않으면 미설치로 보고 예측을 시도하지 않는다.
    """

    name: str
    property: str          # logs | caco2 | logd | pka
    module: str            # 설치 확인용 임포트 경로
    reference: str         # 출처/근거 표기
    fn: Optional[Callable[[str], Optional[float]]] = None

    def available(self) -> bool:
        try:
            importlib.import_module(self.module)
        except Exception:
            return False
        return self.fn is not None

    def predict(self, smiles: str) -> Optional[float]:
        if not self.available() or self.fn is None:
            return None
        try:
            return self.fn(smiles)
        except Exception:
            return None


# 어댑터 등록부. fn=None 이면 "설계상 자리는 있으나 아직 연결 안 됨" 상태다.
# 연결 시 무게가 큰 의존성(torch·chemprop)이 따라오므로 배포 정책은 사람이 정한다.
PREDICTORS: List[Predictor] = [
    Predictor("ADMET-AI", "logs", "admet_ai",
              "Chemprop 기반 GNN, TDC 41개 ADMET 데이터셋"),
    Predictor("SolTranNet", "logs", "soltrannet",
              "SMILES 트랜스포머, 수용해도 전용"),
    Predictor("ADMET-AI", "caco2", "admet_ai",
              "Chemprop 기반 GNN, Caco-2 투과도"),
    Predictor("QupKake", "pka", "qupkake",
              "양자화학 특징 결합 GNN, microstate 단위 pKa"),
]


@dataclass
class PropertyPrediction:
    """한 물성에 대한 예측 묶음과 그 신뢰도 판정."""

    property: str
    values: Dict[str, float] = field(default_factory=dict)   # 모델명 → 값
    consensus: Optional[float] = None
    spread: Optional[float] = None
    high_uncertainty: bool = False
    status: str = "not_connected"    # ok | high_uncertainty | not_connected | request_data
    note: str = ""
    sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "property": self.property, "values": self.values,
            "consensus": self.consensus, "spread": self.spread,
            "high_uncertainty": self.high_uncertainty,
            "status": self.status, "note": self.note, "sources": self.sources,
        }


def predict_property(smiles: str, prop: str) -> PropertyPrediction:
    """한 물성을 등록된 모든 예측기로 계산하고 편차를 본다."""
    result = PropertyPrediction(property=prop)
    for predictor in [p for p in PREDICTORS if p.property == prop]:
        if not predictor.available():
            continue
        value = predictor.predict(smiles)
        if value is not None:
            result.values[predictor.name] = round(float(value), 3)
            result.sources.append(f"{predictor.name} ({predictor.reference})")

    if not result.values:
        result.status = "not_connected"
        result.note = ("예측 모델이 연결되지 않았습니다. 구조만으로는 이 물성을 확정할 수 없으므로"
                       " 실측값을 입력하거나 예측기를 연결해야 합니다(기준서 §13).")
        return result

    numbers = list(result.values.values())
    result.consensus = round(sum(numbers) / len(numbers), 3)

    if len(numbers) >= 2:
        result.spread = round(max(numbers) - min(numbers), 3)
        # 팀 리뷰 제안: 편차가 임계를 넘으면 점추정을 믿지 않고 고불확실성으로 본다.
        if prop == "logs" and result.spread >= LOGS_DISAGREEMENT_THRESHOLD:
            result.high_uncertainty = True
            result.status = "high_uncertainty"
            result.note = (f"두 모델의 LogS 예측이 {result.spread} log 차이 — "
                           f"임계 {LOGS_DISAGREEMENT_THRESHOLD} 이상이라 점추정을 신뢰하지 않습니다. "
                           "실험 용해도 측정을 확인시험으로 요청합니다.")
        else:
            result.status = "ok"
    else:
        result.status = "ok"
        result.note = "단일 모델 예측 — 교차검증 없음. 두 번째 모델을 연결하면 편차로 신뢰도를 볼 수 있습니다."
    return result


def classify_bcs(logs: PropertyPrediction, caco2: PropertyPrediction) -> Dict[str, object]:
    """LogS와 Caco-2로 BCS 등급을 도출한다(팀 리뷰 제안 ③).

    **예측 기반 사전 분류다.** ICH M9의 고용해도는 최고 단회 용량이 pH 1.2–6.8에서
    250 mL 이하에 녹는지 실험으로 판단하고, 고투과도는 사람 흡수·생체이용률 자료로
    판단한다. 여기서 내는 등급은 후보 생성 전략을 고르기 위한 신호이며
    규제 판정을 대체하지 않는다(기준서 §2.1·§13).
    """
    out: Dict[str, object] = {
        "bcs_class": None, "confidence": "none", "basis": "predicted",
        "solubility_logs": logs.consensus, "permeability_caco2": caco2.consensus,
        "status": "request_data",
        "note": "",
        "limitation": "예측 기반 사전 분류 — ICH M9 실험(용해도 250 mL, 사람 흡수)을 대체하지 않음",
    }

    if logs.consensus is None or caco2.consensus is None:
        missing = [n for n, p in (("용해도", logs), ("투과도", caco2)) if p.consensus is None]
        out["note"] = (f"{'·'.join(missing)} 예측값이 없어 BCS를 분류하지 않습니다. "
                       "추정으로 등급을 확정하지 않는 것이 이 시스템의 원칙입니다.")
        return out

    high_sol = logs.consensus >= LOGS_HIGH_SOLUBILITY
    high_perm = caco2.consensus >= CACO2_HIGH_PERMEABILITY
    out["bcs_class"] = {(True, True): "I", (True, False): "III",
                        (False, True): "II", (False, False): "IV"}[(high_sol, high_perm)]
    out["status"] = "predicted"

    if logs.high_uncertainty:
        out["confidence"] = "low"
        out["note"] = ("용해도 예측의 모델 간 편차가 커서 등급 신뢰도가 낮습니다. "
                       "가용화 전략 판단 전에 실험 용해도를 확인하세요.")
    else:
        out["confidence"] = "medium"
        out["note"] = "예측값 기반 등급입니다. 전략 선택의 출발점으로만 쓰세요."
    return out


def build_prediction_layer(smiles: str) -> Dict[str, object]:
    """예측 계층 전체를 한 번에 돌린다 — 물성 예측 → 불확실성 → BCS."""
    logs = predict_property(smiles, "logs")
    caco2 = predict_property(smiles, "caco2")
    pka = predict_property(smiles, "pka")
    bcs = classify_bcs(logs, caco2)

    connected = sorted({p.name for p in PREDICTORS if p.available()})
    return {
        "logs": logs.to_dict(),
        "caco2": caco2.to_dict(),
        "pka": pka.to_dict(),
        "bcs": bcs,
        "connected_predictors": connected,
        "registered_predictors": [
            {"name": p.name, "property": p.property, "reference": p.reference,
             "available": p.available()} for p in PREDICTORS
        ],
    }


def uncertainty_triggered_tests(layer: Dict[str, object]) -> List[Dict[str, str]]:
    """예측 신뢰도에서 곧바로 나오는 확인시험 요청(팀 리뷰 제안 ①).

    ②의 불확실성 출력과 ⑤의 확인시험 요청을 느슨하게 두지 않고 여기서 명시적으로 잇는다.
    """
    requests: List[Dict[str, str]] = []
    logs = layer.get("logs", {}) or {}
    bcs = layer.get("bcs", {}) or {}

    if logs.get("high_uncertainty"):
        requests.append({
            "test": "평형 용해도 측정 (pH 1.2 / 4.5 / 6.8, 37°C)",
            "reason": f"LogS 예측 편차 {logs.get('spread')} log ≥ {LOGS_DISAGREEMENT_THRESHOLD} — 예측 신뢰 불가",
            "tier": "필수", "trigger": "prediction_uncertainty",
        })
    elif logs.get("status") == "not_connected":
        requests.append({
            "test": "평형 용해도 측정 (pH 1.2 / 4.5 / 6.8, 37°C)",
            "reason": "용해도 예측 모델 미연결 — 구조만으로 확정 불가",
            "tier": "필수", "trigger": "prediction_missing",
        })

    if bcs.get("status") == "request_data":
        requests.append({
            "test": "ICH M9 용해도·투과도 자료 확보",
            "reason": "BCS 등급을 결정할 입력이 없음 — 가용화 전략 판단 보류",
            "tier": "필수", "trigger": "bcs_undetermined",
        })
    elif bcs.get("bcs_class") in ("II", "IV"):
        requests.append({
            "test": "생체관련 매질 용출 (FaSSIF/FeSSIF)",
            "reason": f"예측 BCS {bcs.get('bcs_class')} — 난용성으로 가용화 전략 검토 필요",
            "tier": "권장" if bcs.get("confidence") == "medium" else "필수",
            "trigger": "bcs_low_solubility",
        })
    return requests
