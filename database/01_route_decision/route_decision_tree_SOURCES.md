# route_decision_tree.csv + powder_flow_scale.csv — 출처 및 설계 문서

## 1. 파일이 두 개인 이유

원래 `route_decision_tree.csv` 하나로 계획했으나, 작업 중 **성격이 전혀 다른 두 종류의
데이터가 섞여 있다**는 것이 드러나 분리했습니다.

| 파일 | 행수 | 성격 | 검증 |
|---|---|---|---|
| `powder_flow_scale.csv` | 21 | **약전 원문 수치** — 유동성 등급 판정 기준 | 전 행 `VERIFIED` |
| `route_decision_tree.csv` | 10 | **제제학 판단** — 등급→공정 매핑 | 혼재 |

이 분리가 중요한 이유: USP <1174>는 **유동성을 어떻게 등급화하는지만 정의하고,
"어떤 등급이면 어떤 공정을 써야 하는지는 말하지 않습니다."**
전자는 약전에 명시된 결정론적 기준이고, 후자는 제제학자의 판단 영역입니다.
한 파일에 섞으면 심사위원이 "이 공정 선택 기준의 근거가 USP입니까?"라고 물었을 때
정확히 답할 수 없게 됩니다.

## 2. powder_flow_scale.csv — 전 행 검증 완료

USP <1174> Powder Flow의 Table 1(안식각), Table 2(압축도지수·Hausner비) 원문을
직접 확보하여 구간 값을 그대로 옮겼습니다. 원 출처는 Carr(1965)입니다.

### Table 1 — 안식각 (Angle of Repose)

| 안식각(°) | 유동 특성 |
|---|---|
| 25–30 | Excellent |
| 31–35 | Good |
| 36–40 | Fair — 보조제 불필요 |
| 41–45 | Passable — 걸릴 수 있음 |
| 46–55 | Poor — 교반·진동 필요 |
| 56–65 | Very poor |
| >66 | Very, very poor |

USP는 안식각 40–50 구간에서도 만족스럽게 제조된 제형 사례가 문헌에 있으나,
**50을 넘으면 제조 목적상 허용되는 경우가 드물다**고 명시합니다.
이 서술을 `manufacturing_note` 컬럼에 보존했습니다.

### Table 2 — 압축도지수 및 Hausner비

| 압축도지수(%) | 유동 특성 | Hausner비 |
|---|---|---|
| ≤10 | Excellent | 1.00–1.11 |
| 11–15 | Good | 1.12–1.18 |
| 16–20 | Fair | 1.19–1.25 |
| 21–25 | Passable | 1.26–1.34 |
| 26–31 | Poor | 1.35–1.45 |
| 32–37 | Very poor | 1.46–1.59 |
| >38 | Very, very poor | >1.60 |

### ⚠ 구현 시 반드시 지켜야 할 것 — 측정 조건 고정

USP는 압축도지수와 Hausner비가 **분체의 고유 물성이 아니며 측정 방법에 의존한다**고
명시합니다. 영향 인자로 실린더 직경, 탭 횟수, 시료량, 탭핑 중 회전을 듭니다.
권장 절차는 **250 mL 실린더에 시료 100 g, 3회 측정 평균**입니다.

따라서 `method` 컬럼에 `USP1174_250mL_cylinder_100g`를 명시했습니다.
다른 조건에서 측정된 값을 이 등급표에 그대로 대입하면 판정이 틀어집니다.
엔진에서 입력값의 측정 조건이 불명확하면 `ESCALATE_TO_HUMAN`으로 처리하십시오.

안식각도 마찬가지로 고유 물성이 아니며, 낙하 분체의 충격으로 원뿔 정상이 왜곡되지 않도록
깔때기 높이를 분체 더미 상단에서 2–4 cm로 유지하고, 분체층 위에 원뿔을 형성하라는
권장 절차가 있습니다.

### flow_character_normalized 컬럼

Table 1은 등급명에 서술이 붙어 있고(`Poor - must agitate, vibrate`),
Table 2는 단어만 있습니다(`Poor`). 조인 키로 쓰려면 통일이 필요해서
`flow_character_normalized` 컬럼을 추가했습니다. 세 파라미터 모두 7등급으로 정규화됩니다.

## 3. route_decision_tree.csv — 검증 강도 혼재

10개 규칙 중 8개가 `VERIFIED_SECONDARY`(제제학 문헌 기반), 1개가 `UNVERIFIED`,
1개가 시스템 로직입니다.

### 3.1 주요 분기 근거

**수분·열 민감 API → 수계 습식과립 배제 (RTE004, RTE005)**
건식과립(롤러컴팩션)은 액체나 결합제 용액이 필요 없어 화학적 조성 변화가 없고,
용매나 수분·고온에 민감한 원료에 적합하다는 것이 문헌의 일관된 서술입니다.
습식과립은 건조 단계에서 열 노출이 불가피합니다.

**유동성 불량 → 직접타정 배제 (RTE003)**
직접타정은 유동성과 압축성이 양호한 원료에 적합하되 원료·부형제 선택이 까다롭습니다.
유동성 불량 시 다이 충전 편차로 함량균일성·중량편차 문제가 발생합니다.

**저용량 API → 습식과립 유리 (RTE008)**
습식과립은 소수성 원료의 습윤성을 개선하고 함량균일성을 높이는 장점이 있습니다.

### 3.2 ⚠ 배합금기 파일과의 교차 확인 필요

RTE008에 주석으로 남겼지만 별도로 강조합니다.

`incompatibility_1to1.csv`의 INC001 조사에서 확인된 바로,
Maillard 반응 속도는 **낮은 drug loading, 높은 수분함량, 알칼리성 microenvironmental pH**에서
빨라집니다. 그런데 RTE008은 저용량 API에 습식과립을 권합니다.

즉 **저용량 + 환원당 부형제 + 습식과립**은 세 인자가 동시에 겹치는 최악의 조합입니다.
공정 분기 규칙이 단독으로 "습식과립 권장"을 내면 배합금기 위험이 증폭될 수 있으므로,
엔진에서 `route_decision_tree` → `incompatibility_1to1` 순서로 실행하되
**공정 선택이 배합금기 위험도를 변경할 수 있다는 점을 반성 에이전트가 인지**하도록
설계해야 합니다. 현재 `rulebook_config.csv`의 `trigger_priority`는
route(1) → incompatibility(2)로 이 순서를 반영하고 있습니다.

### 3.3 RTE010 — 모든 공정이 배제된 경우

`ESCALATE_TO_HUMAN`으로 두었습니다. 반성 에이전트로 루프백하면
같은 물성으로 같은 결론에 도달해 무한 루프에 빠집니다.
API 물성 자체를 바꾸는 것(결정형 변경, 입자크기 조절, 공결정 형성)이나
제형 변경은 에이전트의 권한 밖이므로 사람 판단이 필요합니다.
슬라이드 6의 "최대 재시도 횟수 초과 시 에스컬레이션"과 별개로,
**구조적으로 해가 없는 경우를 즉시 감지하는 경로**입니다.

### 3.4 UNVERIFIED 1행

RTE006(유기용매 민감 → 비수계 습식과립 배제)은 논리적으로 자명하나
개별 문헌 출처를 확보하지 못했습니다. 엔진 투입 전 근거 보강이 필요합니다.

## 4. 미해결 — 압축성(compressibility) 정량 지표

`api_compressibility` 컬럼을 `adequate`/`poor`로 두었으나,
**이를 판정할 정량 기준이 아직 없습니다.** USP <1174>는 유동성만 다루고
압축성(정제 성형성)은 범위 밖입니다.

실무에서는 tabletability(인장강도 vs 압축압력), compactibility, Heckel 분석 등을 쓰는데,
이 중 어떤 지표를 쓸지와 임계값은 별도 조사가 필요합니다.
현재는 `REVIEWER_FLAG`로 심사관에게 넘기는 것이 정직한 처리입니다.
`direct_compression_rules.csv` 작성 시 이 부분을 채워야 합니다.

## 5. 참고 문헌

1. **USP. General Chapter <1174> Powder Flow.** United States Pharmacopeia. — `powder_flow_scale.csv` 전 수치의 출처. Table 1(안식각), Table 2(압축도지수·Hausner비), 권장 측정 절차. **2026-07-24 원문 확인.** 참고: 확인한 판본은 USP29–NF24 텍스트이며, 2024년 5월 1일자 조화(harmonization) 개정본이 별도 존재합니다(compressibility index를 Carr index로 병기하는 등 편집상 변경 확인). **본선 전 최신판 대조 권장.**
2. **Carr RL. Evaluating Flow Properties of Solids.** Chem Eng. 1965;72:163–168. — USP <1174> Table 1, Table 2의 원 출처로 약전에 명시됨. 원문 미대조.
3. MilliporeSigma (Sigma-Aldrich) Technical Article. *Tablet Manufacturing Technologies for Solid Drug Formulation* — 직접타정/습식과립/건식과립 비교. RTE004, RTE005의 근거.
4. Pharmaceutical Technology. *Direct Compression Versus Granulation* — RTE001, RTE007, RTE008, RTE009의 근거.
5. Drug-Dev.com. *Formulation Forum — Manufacturing of Solid Oral Dosage Forms by Direct Compression*.

**주의:** 3–5번은 업계 기술 문헌이며 동료심사 논문이 아닙니다. 제안서에서
공정 선택 기준을 주장할 때는 이 한계를 명시하거나, 제제학 교과서
(예: *Pharmaceutical Dosage Forms: Tablets*, Augsburger & Hoag 편)로
근거를 보강하시는 편이 안전합니다.
