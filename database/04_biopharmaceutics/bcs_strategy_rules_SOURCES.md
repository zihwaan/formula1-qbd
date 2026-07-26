# bcs_classification_criteria.csv + bcs_strategy_rules.csv — 출처 및 설계 문서

## 1. 파일을 둘로 나눈 이유 (route와 동일한 원칙)

- `bcs_classification_criteria.csv` (10행) — **ICH M9 규제 명시 경계값.** 전 행 검증
- `bcs_strategy_rules.csv` (4행) — **class별 제형 전략.** 제제학 판단, 심사관 연계

경계값(용해도 250 mL, 투과도 85%)은 규제 문서가 못박은 결정론적 기준이고,
"Class II면 가용화 전략을 쓴다"는 제제학자의 판단입니다. USP <1174>를
powder_flow_scale와 route_decision_tree로 나눈 것과 같은 이유입니다.

## 2. bcs_classification_criteria.csv — ICH M9 기준

현행 국제조화 기준인 **ICH M9 (Step 4, 2019-11-16)**을 1차 근거로 삼았습니다.
FDA·EMA·WHO가 이 문서로 수렴했으므로 단일 출처로 적합합니다.

### 경계값 요약

| 기준 | 값 | 조건 |
|---|---|---|
| 고용해 (high solubility) | 용량:용해도 ≤ 250 mL | 최고 1회 치료용량이 pH 1.2–6.8 전 구간에서 완전 용해, 37±1°C |
| 저용해 | > 250 mL | pH 1.2–6.8 중 **한 지점이라도** 초과 시 |
| 고투과 (high permeability) | 절대 생체이용률 ≥ 85% | 또는 미변화체(+Phase1 산화/Phase2 포합 대사체) 요중 회수 ≥85% |
| 저투과 | < 85% | |
| 분해 배제 | 분해 >10% 시 | high permeability 분류 불가 |
| very rapid 용출 | 15분 내 ≥85% | Class III 바이오웨이버 요건 |
| rapid 용출 | 30분 내 ≥85% | Class I 바이오웨이버 요건 |

### ⚠ 구 기준(LEGACY)을 별도 행으로 보존한 이유

BCS009, BCS010은 **구 FDA 2000 기준**(pH 1–7.5, 투과도 90%)입니다.
현행과 다릅니다. `verification_status = LEGACY`로 표기했고 **판정에 사용 금지**입니다.

이걸 남겨둔 이유: 문헌의 옛 BCS 분류가 이 구 기준으로 되어 있을 수 있습니다.
어떤 약물이 "과거엔 Class I이었는데 현행 기준으론 다르게 분류"되는 경우를
구분하려면 두 기준을 다 알아야 합니다. 아세트아미노펜이 정확히 그런 사례입니다(아래).

## 3. ⚠⚠ 데모 시나리오의 핵심 오류 — 아세트아미노펜은 Class I이 아닙니다

이게 이번 조사에서 가장 중요한 발견입니다.

시나리오 문서와 슬라이드 12는 "아세트아미노펜은 물에 잘 녹으므로 가용화 심사관이
필요 없다"는 논리로 되어 있습니다. **용해도 부분은 맞지만, 결론의 전제가 틀렸습니다.**

문헌 확인 결과:
- 아세트아미노펜은 고용해가 맞습니다(37°C에서 약 23.7 mg/mL, pH 9 이하에서 pH 비의존).
- **그러나 투과도가 낮아 현행 규제 기준상 BCS Class III입니다.**
  흡수율이 고투과 컷오프(구 기준 90%, 현행 85%)에 못 미칩니다.
  생체이용률이 약 88%라 경계선상이지만, 공식 바이오웨이버 monograph는 Class III로 분류합니다.
- WHO 전문위 보고서 등 일부는 Class I로 보기도 해서 **논쟁적**이지만,
  현행 규제 관점의 기본값은 Class III입니다.

### 이것이 데모에 주는 영향

"잘 녹으니 가용화 심사관 미소집"이라는 **결론 자체는 유효**합니다.
Class III는 용해도가 아니라 투과도가 문제라 가용화가 무의미하기 때문입니다(BST003).
즉 가용화 심사관을 안 부르는 건 맞습니다.

**하지만 이유가 다릅니다.** 시나리오는 "잘 녹아서 가용화 불필요"라고 설명하는데,
정확히는 "Class III라서 애초에 가용화로 해결될 문제가 아님"입니다.
약제학 전공 심사위원은 이 차이를 압니다. "아세트아미노펜을 Class I처럼 다루셨는데
실제론 Class III 아닙니까?"라는 질문이 나오면, 시스템이 BCS 분류를
제대로 못 한다는 인상을 줍니다.

### 권고

두 가지 방법이 있습니다.

1. **시나리오 설명을 정확히 수정** — "아세트아미노펜은 BCS Class III(고용해·저투과)이므로,
   용해도가 아니라 투과도가 흡수를 제한한다. 가용화 전략은 이 경우 부적절하며,
   따라서 가용화 심사관은 소집되지 않는다." → 오히려 시스템이 BCS를 정확히
   이해하고 있음을 보여주는 장면으로 전환됩니다.

2. **데모 API를 명확한 Class I 약물로 교체** — 이전에 논의한 Maillard/아민기 이슈도
   함께 있으므로, 실제 1차 아민이면서 Class I인 약물을 고르면 두 문제가 동시에 해결됩니다.

1번을 권합니다. 수정이 작고, "우리 시스템은 고용해라도 Class III면 가용화가
답이 아님을 안다"는 게 오히려 강력한 시연 포인트가 됩니다.

## 4. bcs_strategy_rules.csv — class별 전략

| Class | 용해도/투과도 | 제한 요인 | 전략 | action |
|---|---|---|---|---|
| I | 고/고 | 없음 | 표준 즉시방출 | ALLOW |
| II | 저/고 | 용해도 | 입자크기 감소, 고체분산, 지질기반/SEDDS, 염, 시클로덱스트린 | REVIEWER_FLAG (가용화) |
| III | 고/저 | 투과도 | very rapid 용출, 부형제 엄격 통제 | REVIEWER_FLAG (규제취지) |
| IV | 저/저 | 둘 다 | 경구 부적합 경우 많음 | ESCALATE_TO_HUMAN |

### 설계 포인트

**Class III에 가용화 전략을 적용하는 것은 오답입니다(BST003 note).**
문제가 용해도가 아니라 투과도이기 때문입니다. 시스템이 Class III 약물에
가용화 심사관을 소집하면 그 자체가 논리 오류입니다. 그래서 Class III의
reviewer_summon은 가용화가 아니라 규제취지 심사관(부형제가 투과도/위배출에
미치는 영향 통제)으로 연결했습니다. Dahan et al.(AAPS J 2016)이 BCS Class III에서
부형제가 투과도에 미치는 영향을 다룬 근거입니다.

**Class IV는 ESCALATE_TO_HUMAN.** route_decision_tree의 RTE010(해 없음)과
같은 성격입니다. 제형 전략만으로 해결이 어려워 사람 판단이 필요합니다.

**Class I은 ALLOW이며 가용화 심사관 불필요.** 데모의 "잘 녹는 API는 심사관 미소집"
원칙이 여기 해당합니다(단, 위 3절대로 아세트아미노펜은 Class III임에 유의).

## 5. 구현 시 유의점

### 5.1 분류는 계산, 전략은 매핑

`bcs_classification_criteria.csv`는 RDKit 등으로 계산한 용해도/투과도 예측값을
class로 변환하는 데 씁니다. 단 **투과도는 RDKit으로 직접 안 나옵니다.**
logP 등에서 추정하거나 외부 예측 모델이 필요하며, 실측 생체이용률이 있으면 우선합니다.
`api_physicochemical_thresholds.csv`(미작성)가 이 계산-분류 연결을 담당해야 합니다.

### 5.2 투과도 데이터 부재 시 처리

용해도는 계산으로 비교적 신뢰도 있게 나오지만, 투과도는 불확실합니다.
투과도 근거가 약하면 class 확정이 안 되므로, **저신뢰 분류는 ESCALATE_TO_HUMAN
또는 REVIEWER_FLAG로 처리**하고 자동 통과시키지 마십시오.
아세트아미노펜처럼 경계선(BA 88%) 약물은 특히 그렇습니다.

### 5.3 dose_solubility_volume 계산

고용해 판정은 단순 용해도(mg/mL)가 아니라 **용량:용해도比**입니다.
최고 1회 용량(mg) / 용해도(mg/mL) ≤ 250 mL 여부로 판정하므로,
API 용량 정보가 반드시 입력에 있어야 합니다. Dose number D0 = M0/(V0×Cs)도
동일 개념입니다. 용량 없이 용해도만으로 판정하면 틀립니다.

## 6. 참고 문헌

1. **ICH. M9 Biopharmaceutics Classification System-Based Biowaivers.** Step 4, 2019-11-16. https://database.ich.org/sites/default/files/M9_Guideline_Step4_2019_1116.pdf — `bcs_classification_criteria.csv`의 현행 경계값 전부. 원문 확인.
2. **FDA. M9 Biopharmaceutics Classification System-Based Biowaivers Guidance.** (FDA media 148472) — ICH M9의 FDA 이행본. 투과도 85% 및 대사체 기준.
3. FDA. *Waiver of In Vivo BA/BE Studies for IR Solid Oral Dosage Forms Based on a BCS* — 구 2000 기준(LEGACY 행)의 출처.
4. **Kalantzi L, Reppas C, Dressman JB, et al. Biowaiver monographs for immediate release solid oral dosage forms: Acetaminophen (paracetamol).** J Pharm Sci. 2006. — 아세트아미노펜 Class III 분류 근거(3절).
5. **Dahan A, et al. The Effect of Excipients on the Permeability of BCS Class III Compounds and Implications for Biowaivers.** AAPS J. 2016. PMC4689772 — Class III 부형제-투과도 통제 근거(BST003).
6. Amidon GL, Lennernäs H, Shah VP, Crison JR. A theoretical basis for a biopharmaceutic drug classification. Pharm Res. 1995;12:413. — BCS 원전.
7. Charurin P 등 / WHO TRS 937 Annex 8 — 저용해 정의(한 pH라도 250 mL 초과) 근거.

**주의:** 4·5번 monograph/논문은 원문 전문이 아니라 초록·발췌 수준에서 확인했습니다.
아세트아미노펜 분류처럼 데모에 직접 쓰이는 사항은 본선 전 monograph 원문 확보를 권합니다.
