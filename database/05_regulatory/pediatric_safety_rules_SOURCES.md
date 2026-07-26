# pediatric_safety_rules.csv — 출처 및 설계 문서

## 1. 이 파일의 상태 — **전 컬럼 채워진 첫 완성본**

46행 × 23컬럼. 43행이 `VERIFIED`이며, **모든 수치가 1차 출처 원문 대조 결과**입니다.
추정하거나 기억으로 채운 임계값은 하나도 없습니다.

| verification_status | 행 수 | 의미 |
|---|---|---|
| `VERIFIED` | 43 | EMA Annex Rev.2 원문에 명시된 값 |
| `NO_SOURCE_FOUND` | 1 | SLS — 근거 없음을 명시적으로 기록 (PED044) |
| `UNVERIFIED_CRITICAL` | 1 | 이산화티타늄 — Annex 미수록 (PED045) |
| `ESCALATION_REQUIRED` | 1 | 향료 — 에이전트 단독 판정 불가 (PED046) |

## 2. ⚠ 중요 — 이전 답변의 수치 일부가 구버전이었습니다

지난 작업에서 확보한 문서는 `corr.1` (2017-10-09) **Superseded 판**이었습니다.
이번에 **Rev. 2 (EMA/CHMP/302620/2017 Rev.2, 2019-11-22 공표)** 전문을 대조한 결과,
소아 안전에 직결되는 항목이 개정되어 있었습니다.

### 에탄올 — 임계값 체계가 전면 개편됨

| | corr.1 (구버전) | **Rev.2 (현행)** |
|---|---|---|
| 기준 단위 | 절대량 (per dose) | **체중당 (mg/kg per dose)** |
| 임계값 | Zero / 100 mg / 3 g per dose | **Zero / 15 mg/kg / 75 mg/kg per dose** |

구버전 수치를 그대로 썼다면 **소아 체중 기반 판정이 통째로 틀렸을 것**입니다.
Rev.2는 또한 정제 코팅 등 공정용제로 쓰여 ICH Q3C 수준 이하로 증발된 에탄올은
환자정보 기재 대상이 아니라고 명시하는데, 이는 코팅 공정 규칙과 직접 연결됩니다.

### 붕산 — 2022-03-29 갱신

Rev.2는 붕산 항목이 2022년 3월 29일자로 갱신되었음을 표시합니다.
문구가 "Do not give to a child less than X years old"에서
"should not be given ... **without medical advice**"로 완화되었고,
Q&A 문서 참조가 Rev.2로 변경되었습니다. 연령별 안전한계(2세 1 mg B/day,
12세 3 mg B/day, 18세 7 mg B/day, 성인 10 mg B/day)는 동일합니다.

**교훈:** 규제 CSV에 `source_version` / `source_updated_on` / `retrieved_on`
세 컬럼이 반드시 필요합니다. 본 파일에는 모두 포함시켰고,
`excipient_master.csv`에도 `ema_annex_version` / `ema_annex_retrieved_on`을 추가했습니다.

## 3. 핵심 설계 — `action` 컬럼이 판정 계층을 결정

중간발표 슬라이드 10의 2단 구조(Hard Fail + 가중점수)를 데이터 레벨에서 구현한 것이
`action` 컬럼입니다. 규칙마다 "이건 거부권인가, 심사관 판단인가, 사람에게 넘길 일인가"를
CSV가 직접 지정합니다.

| action | 행 수 | 동작 | 예시 |
|---|---|---|---|
| `HARD_FAIL` | 15 | 즉시 반려. Reviewer 점수와 무관 | PKU 환자 + 아스파탐 |
| `ESCALATE_TO_HUMAN` | 5 | 데이터 부재·판단 불가 → 사람에게 | 12주 미만 영아 + 아스파탐 |
| `REVIEWER_FLAG` | 13 | 심사관 소집하여 맥락 판단 | 소르비톨 140 mg/kg/day 초과 |
| `LABEL_REQUIRED` | 12 | 반려 아님. 라벨링 요구사항 출력 | 아조색소 함유 표기 |
| `NOT_A_RULE` | 1 | 근거 없음 기록용 (실행 안 됨) | SLS (PED044) |

`ESCALATE_TO_HUMAN`을 별도 액션으로 둔 것이 특히 중요합니다.
"데이터가 없다"와 "안전하다"는 전혀 다른 판정인데, 이를 구분하지 않으면
에이전트가 근거 부재를 안전으로 오독합니다. 슬라이드 6의 에스컬레이션 설계가
여기서 실제 데이터 구조로 구현됩니다.

## 4. ⚠ SLS 문제 — Rev.2에서도 확인, 근거 없음 확정

Rev.2 전문을 재확인한 결과도 동일합니다.

> **Sodium laurilsulfate — 09/10/2017, Corrigendum 19/11/2018 — Route: Cutaneous — Threshold: Zero**
> 국소 피부 반응(따끔거림·작열감). 피부 두께가 부위·연령에 따라 다르고,
> 아토피 피부염 등 피부 장벽 기능이 저하된 환자가 SLS 자극에 더 민감하다는 comment.

**경구 경로 항목이 존재하지 않으며, 소아 mg 상한도 없습니다.**
따라서 PED044를 `NOT_A_RULE` / `NO_SOURCE_FOUND`로 기록했습니다.
규칙 엔진에서 실행되지 않지만, "이 항목은 조사했고 근거가 없었다"는 사실 자체를
데이터로 남기기 위한 행입니다. 이렇게 해두면 나중에 누군가 다시 10 mg을 넣으려 할 때
근거 부재가 기록으로 남아 있습니다.

### 데모 시나리오 교체안 (재확인)

Rev.2 기준으로 아래 3단 반려가 모두 원문 인용 가능합니다:

| 단계 | 반려 사유 | action | 근거 |
|---|---|---|---|
| ① | Lactose × 아민기 API → Maillard | HARD_FAIL | HPE (배합금기) |
| ② | 소아 + 아스파탐, PKU 환자 | HARD_FAIL | PED001, Annex Rev.2 |
| ③ | 바나나향 조성 미확인 | ESCALATE_TO_HUMAN | PED046, Annex 부록 |

특히 ③이 강력합니다. 시연에서 에이전트가 "향료는 안전합니다"라고 하지 않고
**"공급사 사양서가 필요합니다"라고 멈추는 장면**은, 평가 기준의
"AI가 언제 사람에게 확인을 요청하는가"에 대한 가장 설득력 있는 답이 됩니다.
할루시네이션을 막는 시스템이라는 주장을 말이 아니라 동작으로 보여주는 셈입니다.

## 5. 규칙 엔진 구현 시 유의점

### 5.1 체중 기반 임계값은 소아 체중 테이블이 필요

`threshold_unit`이 `mg/kg/day` 또는 `mg/kg`인 규칙(시클로덱스트린, 프로필렌글리콜,
에탄올, 과당, 소르비톨)은 **환자 체중이 있어야 판정 가능**합니다.
연령→체중 변환 테이블(WHO 성장 표준 등)이 별도로 필요하며,
체중 정보가 없으면 `ESCALATE_TO_HUMAN`으로 폴백해야 합니다.
체중을 임의 가정하고 통과 판정을 내리면 그것이 곧 위험한 할루시네이션입니다.

### 5.2 `comparator` 의미

- `gt` = threshold 초과 시 발동
- `gte` = threshold 이상 시 발동
- `lt` = threshold 미만일 때 해당 (나트륨 'sodium-free' 표기 조건, PED034)

### 5.3 가산 효과 (additive effect)

Annex는 과당·소르비톨에 대해 **병용 제품 및 식이 유래분의 가산 효과**를 고려하라고
명시합니다. 즉 단일 제형만 보고 판정하면 불충분합니다.
현재 CSV는 단일 제형 기준이며, 병용 판정은 향후 `multicomponent` 규칙으로
확장해야 합니다. 이 한계를 제안서에 명시하는 편이 심사에서 유리합니다.

### 5.4 `age_group` 값 목록 (18종)

`neonate_under_4weeks`, `infant_under_12weeks`, `child_under_2years`,
`child_under_3years`, `child_under_5years`, `child_under_12years`,
`child_under_18years`, `child_any`, `all`,
`PKU_patient_any_age`, `HFI_patient_any_age`, `galactose_intolerance_any_age`,
`celiac_any_age`, `wheat_allergy_any_age`, `peanut_soya_allergy`,
`diabetes_any_age`, `chewable_chronic_use`, `pediatric_any`

연령 구간이 주(week)와 년(year)으로 섞여 있어 `age_min_value`/`age_min_unit`/
`age_max_value`/`age_max_unit` 4컬럼으로 분리해 두었습니다. 엔진에서는
모두 일(day) 단위로 정규화해 비교하는 것을 권합니다.

## 6. 다음 단계 제안

이 파일에서 **아직 커버 못 한 소아 이슈**가 있습니다:

- **제형 적합성**: 정제 크기·연하 곤란은 Annex 범위 밖입니다.
  EMA *Guideline on pharmaceutical development of medicines for paediatric use*
  (EMA/CHMP/QWP/805880/2012 Rev.2)에서 별도 확보 필요.
- **투여 편의성**: 분할선, 현탁 가능 여부 등.
- **STEP DB 항목**: Annex에 없는 부형제의 소아 노출 자료.

이 세 가지는 `pediatric_formulation_suitability_rules.csv`로 분리하는 것이 맞다고 봅니다.
성격이 "금기·상한"이 아니라 "적합성 평가"라 `REVIEWER_FLAG` 계열이 대부분일 것입니다.

## 7. 참고 문헌

1. **EMA/CHMP. Annex to the European Commission guideline on 'Excipients in the labelling and package leaflet of medicinal products for human use' (SANTE-2017-11668) — Revision 2.** EMA/CHMP/302620/2017 Rev. 2, 공표일 2019-11-22 (Rev.2는 붕산 항목 갱신 포함, 붕산 자체는 2022-03-29자 업데이트 표시). 문서번호 EMA/655784/2022. — **본 파일 전 수치의 출처. 2026-07-24 전문 대조.**
2. EMA. *Q&A on boric acid/borates used as excipients* (EMA/CHMP/619104/2013 Rev.2). — 붕소 환산(1 mg B = 5.7 mg 붕산) 및 상세 계산 근거. (본 작업 미조회, Annex에서 참조 지시)
3. EMA. *Report on ethanol as excipient* (EMA/CHMP/43486/2018), Appendix 1. — 에탄올 BAC 상승 추정. (본 작업 미조회, Annex에서 참조 지시)
4. EMA/PRAC. *Sodium-containing effervescent, dispersible and soluble medicines – Cardiovascular events* (EMA/PRAC/234960/2015). — 나트륨 SmPC 문구. (본 작업 미조회)
5. EMA. *Guideline on pharmaceutical development of medicines for paediatric use* (EMA/CHMP/QWP/805880/2012 Rev.2). — 제형 적합성 항목의 향후 출처. (미조회)
6. EMA. STEP (Safety and Toxicity of Excipients for Paediatrics) Database. — Annex 미수록 부형제의 소아 자료. (미조회)

**주의:** 2024년 4월 Annex 4차 개정(폴리소르베이트 항목 추가)이 공표되었다는 2차 보도가
확인됩니다. 본 파일은 Rev.2 기준이므로, 본선 제출 전 EMA 사이트에서 최신판을 확인하고
`source_version` / `retrieved_on`을 갱신하시기 바랍니다.
