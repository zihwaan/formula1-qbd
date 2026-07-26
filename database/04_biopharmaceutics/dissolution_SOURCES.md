# dissolution — 출처 및 설계 문서 (3개 파일)

## 1. 왜 파일이 3개인가

원래 `dissolution_rules.csv` 하나로 계획했으나, "용출"이라는 한 단어 아래
**성격·출처·컬럼 구조가 전혀 다른 세 종류**가 섞여 있었습니다.
한 파일에 합치면 빈 컬럼투성이가 되고, 심사위원이 출처를 물었을 때
"이 값은 USP, 저 값은 ICH M9"를 구분해 답할 수 없습니다.

| 파일 | 행 | 성격 | 출처 |
|---|---|---|---|
| `dissolution_acceptance_usp711.csv` | 6 | **제품 QC 합격판정** (S1/S2/S3 단계) | USP <711> |
| `dissolution_apparatus_usp711.csv` | 4 | **시험 장치·조건** 참조표 | USP <711> |
| `dissolution_biowaiver_ichm9.csv` | 3 | **바이오웨이버 프로파일** 비교 | ICH M9 |

세 파일 전 행이 `VERIFIED`입니다(원문 대조 완료).

**중요한 개념 구분:** QC 판정(USP <711>)과 바이오웨이버 판정(ICH M9)은
목적이 다릅니다. 전자는 "이 배치가 규격에 맞는가"(제조 품질), 후자는
"생동성 시험을 면제받을 수 있는가"(규제 승인)입니다. 룰북에서 이 둘을
섞으면 안 됩니다. BCS 시나리오에 쓰이는 것은 주로 후자입니다.

## 2. dissolution_acceptance_usp711.csv — QC 합격 판정

USP <711> Acceptance Table 1(개별 시료)과 Pooled Sample Table을 원문에서 옮겼습니다.
**3단계 순차 시험** 구조입니다. S1에서 충족되면 종료, 아니면 S2, S3로 진행합니다.

### Acceptance Table 1 (개별 시료, 즉시방출)

| 단계 | 시험 단위 | 누적 | 판정 기준 |
|---|---|---|---|
| S1 | 6 | 6 | 각 단위 ≥ Q+5% |
| S2 | 6 | 12 | 12단위 평균 ≥ Q **그리고** 어떤 단위도 Q−15% 미만 아님 |
| S3 | 12 | 24 | 24단위 평균 ≥ Q, Q−15% 미만이 2단위 이하, 어떤 단위도 Q−25% 미만 아님 |

### Pooled Sample Table (혼합 시료)

| 단계 | 기준 |
|---|---|
| S1 | 평균 용출 ≥ Q+10% |
| S2 | 평균(S1+S2) ≥ Q+5% |
| S3 | 평균(S1+S2+S3) ≥ Q |

Pooled는 개별 시료보다 기준이 높습니다(S1에서 +10% vs +5%).
개별 측정 대신 혼합 시료를 쓸 때 적용합니다.

### ⚠ Q값은 이 파일에 없습니다

가장 중요한 주의점입니다. **Q(목표 용출률)는 개별 약물 monograph에서 옵니다.**
USP <711>은 "Q에서 몇 % 편차까지 허용하는가"의 프레임만 정의하고,
Q 자체(예: 80%)는 각 약물 각조에 있습니다. 이 파일의 기준은 전부 Q 기준
상대값(Q+5%, Q−15% 등)입니다.

따라서 엔진 구현 시 **Q값을 별도로 입력받아야** 합니다. Q가 없으면 판정 불가이며,
임의로 Q=80% 같은 기본값을 넣으면 안 됩니다. Q 미확보 시 `ESCALATE_TO_HUMAN`
또는 해당 약물 monograph 조회가 선행되어야 합니다.

## 3. dissolution_apparatus_usp711.csv — 장치 참조표

USP <711>의 4개 장치 사양입니다. 판정 규칙이 아니라 **어떤 시험을 쓸지 선택**하는
참조표입니다(`reference_table`).

| 장치 | 이름 | 주 용도 | BCS 힌트 |
|---|---|---|---|
| 1 | Basket | 캡슐, 부유 정제 | I, III |
| 2 | Paddle | 일반 정제(최다 사용) | I, II, III |
| 3 | Reciprocating Cylinder | pH 변화 프로파일, 서방정 | — |
| 4 | Flow-Through Cell | 난용성 약물, 싱크 조건 | II, IV |

장치 1·2는 온도 37±0.5°C, 바스켓/블레이드-바닥 간격 25±2 mm가 원문 사양입니다.
장치 3·4는 일본약전(JP) 미채택이라 국제 대응 시 주의가 필요합니다.

**BCS 힌트는 참고용입니다.** 난용성(II/IV)은 싱크 조건 확보가 중요해
Flow-Through Cell이 유리하고, 부유 정제는 Basket이 유리하다는 실무 경향을
담았지만, 최종 장치는 개별 monograph가 지정합니다. `analytical_method_rules.csv`
(미작성)가 이 선택 로직을 담당할 자리입니다.

## 4. dissolution_biowaiver_ichm9.csv — 바이오웨이버 프로파일

ICH M9 기준으로, `bcs_strategy_rules.csv`와 직접 연계됩니다.

| BCS | 용출 요건 | 시간 | 매질 |
|---|---|---|---|
| I | rapid: 85% 이상 | 30분 | pH 1.2, 4.5, 6.8 |
| III | very rapid: 85% 이상 | **15분** | pH 1.2, 4.5, 6.8 |

**Class III가 더 엄격합니다**(15분 vs 30분). 투과도가 제한 요인이라
용출이 매우 빨라야 제형 차이가 흡수에 영향을 안 준다는 논리입니다.
이 점이 BST003(Class III 전략)과 연결됩니다.

### f2 유사인자

두 제품(test/reference)의 용출 프로파일 유사성은 f2로 판정하며, **50–100이면 유사**합니다.
단 **두 제품 모두 15분 내 85% 이상 용출되면 f2 계산이 불필요**합니다(자동 유사 간주).
f2 공식은 파일 note에 기재했습니다. 실제 f2 계산과 해석은 심사관 검토 대상(`hybrid`)입니다.

## 5. BCS 파일들과의 연결 구조

```
api_physicochemical_thresholds.csv (미작성)
    │ RDKit 계산 용해도/투과도
    ▼
bcs_classification_criteria.csv ── class 결정 (I/II/III/IV)
    │
    ├──▶ bcs_strategy_rules.csv ────── class별 전략
    │
    └──▶ dissolution_biowaiver_ichm9.csv ── class별 용출 요건
              (Class I: 30분, Class III: 15분)

dissolution_acceptance_usp711.csv ── QC 판정 (Q값은 monograph에서)
dissolution_apparatus_usp711.csv ── 장치 선택 참조
```

QC 계열(USP <711>)과 바이오웨이버 계열(ICH M9)은 위 그림처럼 **분리된 흐름**입니다.
개발자가 이 둘을 하나의 "용출 검사"로 묶지 않도록, config에서도
`dissolution_acceptance`는 `deterministic`, `dissolution_biowaiver`는 `hybrid`로
구분했습니다.

## 6. 구현 시 유의점 정리

1. **Q값 외부 입력 필수** — acceptance 파일은 Q 없이는 무의미. monograph 조회 필요.
2. **3단계 순차 로직** — S1 통과 시 조기 종료. S3는 누적 24단위. "S2 건너뛰고 S3"는
   불가(S3 판정에 24개 결과 필요).
3. **QC vs 바이오웨이버 혼동 금지** — 목적이 다름. 시나리오엔 주로 바이오웨이버.
4. **f2 면제 조건** — 둘 다 15분내 85%면 f2 계산 안 함. 이 분기를 엔진에 반영.
5. **장치 3·4 JP 미채택** — 국제 규제 대응 시 제약.

## 7. 참고 문헌

1. **USP. General Chapter <711> Dissolution.** Revision Bulletin, Official 2012-02-01. https://www.uspnf.com/sites/default/files/usp_pdf/EN/USPNF/revisions/m99470-gc_711.pdf — `dissolution_acceptance_usp711.csv`(Acceptance Table 1, Pooled Sample Table)와 `dissolution_apparatus_usp711.csv`(장치 1–4 사양) 전량. **2026-07-24 원문 대조.** EP/JP와 조화된 챕터이나 장치 3·4는 JP 미채택.
2. **ICH. M9 Biopharmaceutics Classification System-Based Biowaivers.** Step 4, 2019-11-16. — `dissolution_biowaiver_ichm9.csv`의 rapid/very rapid 기준 및 f2. 앞서 BCS 파일에서 확보한 동일 문서.
3. USP General Chapter <1092> The Dissolution Procedure: Development and Validation — 시험법 개발·검증 상세. 본 작업 미조회, 실제 조건 설정 시 참조 권장.

**주의:** 확보한 USP <711>은 2012 Revision Bulletin입니다. 현행 USP-NF는 추가
개정되었을 수 있으므로(예: 장치 사양 미세 조정, 국가별 텍스트 변경) 본선 전
최신판 대조를 권합니다. Acceptance Table의 통계 구조(S1/S2/S3, Q±편차)는
장기간 안정적으로 유지되어 온 부분입니다.
