# Formula 1 — Experimental Development & DoE Agent Architecture v7.0

> 개발자 구현 명세 · 2026-09-26  
> 상류 시스템: 기존 Formula 1 CandidateDiscoveryGraph  
> 신규 시스템: ExperimentalDevelopmentGraph  
> 기준 데모: CBD ODT 문헌 재현 + 신규 API feasibility 분기  
> 종료점: 독립 확인실험을 통과한 VERIFIED_OPERATING_REGION  
> 명시적 제외: 관리전략(Control Strategy), PAT, PPQ, 상업 스케일업

---

## 0. 문서 목적과 최종 결론

이 문서는 기존 Formula 1 후보처방 생성 시스템 뒤에 붙는 실험개발·DoE·반응표면·검증 루프의 구현 계약이다. 핵심 설계는 다음과 같다.

1. 상류 시스템이 만든 처방의 mg 값은 검증된 최적값이나 DoE 중심점이 아니라 참고 처방값이다.
2. 연구자는 논문 표와 유사한 화면에서 CQA를 검토하고, 그중 DoE 반응을 최대 4개 선택한다.
3. 초기위험평가/FMEA가 제안한 변수 중 연구자가 최대 3개 요인을 선택한다.
4. 연구자가 각 요인의 low/center/high를 입력하되, 시스템은 값의 출처와 실험 근거를 검사한다.
5. 근거가 충분하면 RSM으로 진행하고, 근거가 부족한 신규 API는 NEEDS_FEASIBILITY로 보내 소규모 범위확인 실험을 먼저 수행한다.
6. 설계행렬, 회귀계수, 모델 선택, 통계진단, 영역 계산과 상태승격은 결정론 코드가 수행한다.
7. LLM은 CQA·FMEA 후보, 설명, 실패 가설과 다음 실험 초안을 제시하지만 숫자·통계판정·상태를 임의로 확정하지 않는다.
8. 유효한 모델로 만든 영역은 먼저 PROVISIONAL_DESIGN_SPACE이며, 독립 확인배치를 통과한 뒤에만 VERIFIED_OPERATING_REGION이 된다.

사용자 흐름:

> 후보 확인 → CQA 선택 → 요인 선택 → 3수준 입력 → 실험표 실행 → 자동 모델·곡면 → 확인실험

---

## 1. v6.1에서 바뀌는 핵심 사항

| 영역 | v6.1 | v7.0 결정 |
|---|---|---|
| 후보 처방값 | 기본적으로 factor center에 사용 | reference_value일 뿐이다. center 자동 승계 금지 |
| CQA 화면 | 계약 중심의 상세 설정 | 논문식 표를 기본 화면으로 제공; DoE 반응은 최대 4개 |
| 요인 화면 | 상세 FMEA와 별도 Range Proposer | 위험평가 요약에서 최대 3개 선택; 상세 FMEA는 고급 보기 |
| 수준값 | 시스템 제안 후 승인 | 사용자가 low/center/high 입력·승인; 시스템은 근거·단위·제약 검증 |
| 근거 없는 범위 | 범위확인 run 제안 | 명시적 NEEDS_FEASIBILITY 상태와 전용 micro-study 도입 |
| Screening DoE | 4요인까지 주요 경로 | 최대 3개 선택 후 RSM 직행이 기본; 후보가 많을 때만 선택적 고급 경로 |
| 회귀항 선택 | 전체모형 후 연구자 승인 축소 | 사전 정의 후보군에서 자동 계층적 모델 선택 |
| 2요인 설계 | 여러 정책 중 선택 | 연속형 기본값: face-centered CCD 13 runs |
| 3요인 설계 | CCD/BBD 정책 | 연속형 기본값: BBD 17 runs |
| 시각화 | contour/slice 중심 | Matplotlib Axes3D 곡면 + 2D contour + 다중 CQA 중첩 |
| 종료점 | 검증된 design space | VERIFIED_OPERATING_REGION; 규제 승인 Design Space라고 주장하지 않음 |
| 관리전략 | 범위 밖 | 계속 제외. 관련 객체·API·화면을 만들지 않음 |
| 데모 | Lornoxicam 중심 | CBD ODT를 주 데모로 교체; 기존 사례는 회귀 테스트 fixture로 유지 가능 |

---

## 2. 시스템 경계

### 2.1 두 bounded context

| Context | 책임 | 입력 | 출력 |
|---|---|---|---|
| CandidateDiscoveryGraph | API 특성 해석, 제형전략·후보처방 생성, 기존 Rulebook/Evidence Gate, 후보 순위화 | QTPP, API 정보, 실측값 | CandidatePortfolio |
| ExperimentalDevelopmentGraph | CQA 계약, 위험평가, 범위 근거, feasibility, DoE, 모델, 영역, 확인실험 | 선택된 candidate_id@version | VERIFIED_OPERATING_REGION + scope |

두 그래프는 내부 상태를 공유하지 않는다. 연구자가 특정 후보 버전을 선택하면 immutable handoff를 생성한다. 상류 후보가 이후 수정되어도 진행 중인 실험개발 study를 덮어쓰지 않는다.

### 2.2 MVP 포함 범위

- 저분자 경구용 속방정 및 ODT/분산정
- 직접타정 중심, 고정 연구실 설비와 실험실 규모
- DoE 반응 최대 4개
- RSM 요인 최대 3개, 기본적으로 연속형 요인
- CQA 예: 경도/인장강도, 붕해·분산시간, 마손도, 용출 요약값, 함량균일성
- 1요인 quadratic, 2요인 face-centered CCD, 3요인 BBD
- 구조화 결과 입력과 자연어 보조 입력
- 독립 확인실험과 Lab-in-the-loop 재설계

### 2.3 MVP 제외 범위

- 관리전략, PAT, 공정관리 한계와 실시간 방출
- PPQ, 상업생산 공정검증, 스케일업 자동 전환
- 임상 유효성·생체이용률 추론
- 무균제제, 바이오의약품, 복잡한 방출제어 제형
- split-plot, definitive screening, 혼합물-공정 결합설계의 완전 자동화
- 규제기관 승인 의미의 Design Space 선언

혼합물 제약, 범주형 요인, hard-to-change 요인이 감지되면 표준 CCD/BBD로 강제 변환하지 않고 ADVANCED_DESIGN_REQUIRED로 보낸다.

---

## 3. 전체 아키텍처

~~~mermaid
flowchart TD
    A["Candidate Discovery"] --> B["Immutable Handoff"]
    B --> C["CQA + FMEA Workspace"]
    C --> D["Factor and Range Gate"]
    D -->|"근거 부족"| E["Feasibility Micro-study"]
    E --> D
    D -->|"범위 준비"| F["DoE Plan + Protocol"]
    F --> G["Lab Results + Quality Gate"]
    G --> H["Automatic Model Selection"]
    H -->|"부적합"| I["Diagnosis + Reflection"]
    I --> C
    H -->|"유효"| J["Provisional Design Space"]
    J --> K["Independent Verification"]
    K -->|"실패"| I
    K -->|"통과"| L["Verified Operating Region"]
~~~

### 3.1 횡단 계층

| 계층 | 책임 |
|---|---|
| Development Orchestrator | 상태 전이, 승인 대기, WAIT/RESUME, 실패 라우팅, idempotency |
| Deterministic Services | 룰 평가, 행렬 생성·검증, 회귀, 모델 선택, 영역·확인 판정 |
| Proposal Agents | CQA/FMEA 후보, 설명, 경쟁 가설, 다음 실험·개정안 초안 |
| Researcher UI | 후보·CQA·요인·범위·프로토콜·파싱 결과·영역 승인 |
| Artifact Stores | 원자료, 행렬, 모델, 그림, 룰·도구 버전, 승인·override 이력 |

### 3.2 권한 경계

| 행위 | LLM | 결정론 코드 | 연구자 |
|---|:---:|:---:|:---:|
| CQA/FMEA 후보 제안 | 가능 | 템플릿·룰 보조 | 승인·수정 |
| low/center/high 숫자 확정 | 불가 | 근거·범위 검증 | 가능 |
| 설계행렬 생성 | 불가 | 가능 | 승인 |
| 회귀계수·R² 계산 | 불가 | 가능 | 열람 |
| 최적 회귀식 선택 | 설명만 | 가능 | 정책 override만 |
| CQA 규격 생성 | 불가 | 형식 검증만 | 출처와 함께 입력·승인 |
| 영역 상태 승격 | 불가 | gate 판정 | 최종 승인 |
| 실패 원인가설 | 가능 | 룰 매칭 | 검토·시험 선택 |
| 과거 artifact 수정 | 불가 | 불가 | 새 버전만 생성 |

### 3.3 Agent 출력 계약과 장애 처리

- 모든 Agent 출력은 Pydantic/JSON Schema로 검증하고 자유서술문을 상태 전이 입력으로 직접 사용하지 않는다.
- LLM이 unavailable 또는 schema-invalid이면 템플릿·Rulebook 결과만 제공하고 상태는 안전하게 WAIT/REVIEW에 둔다.
- LLM 재시도는 같은 artifact version과 prompt version에서 제한 횟수만 허용한다.
- 숫자, 단위, 실험행렬, 통계량을 Agent 응답에서 받아 그대로 저장하지 않는다.
- Agent가 제안한 evidence reference는 실제 source registry에 존재하는지 확인한 뒤에만 연결한다.
- 모델 설명 생성 실패는 통계 artifact 생성을 무효화하지 않지만, 통계 gate 실패를 설명 Agent가 통과로 바꿀 수는 없다.

---

## 4. 사용자 경험: 6단계 Wizard

### 화면 1. 후보처방 확인

표시 항목:

- candidate_id@version, 제형, 목표 함량, 총정중량, 공정경로
- 성분별 mg와 %w/w
- 각 수치의 역할: REFERENCE_PROTOTYPE
- 측정값, 예측값, 문헌값, 전문가 가정의 출처 배지
- 미해결 정보와 기존 Rulebook 판정

필수 안내:

> 이 처방은 DoE의 기준 후보이며, 표시된 수치는 검증된 최적값 또는 요인 중심점이 아닙니다.

연구자가 “이 후보로 실험개발 시작”을 누르면 handoff가 잠긴다.

### 화면 2. CQA 검토와 반응 선택

논문 Table 형식으로 보여준다.

| 품질특성 | 목표/허용기준 | CQA? | 근거 | 분석 역할 |
|---|---|---:|---|---|
| Hardness | 4–6 kgf | Yes | 붕해·취급성 영향 | DOE_RESPONSE |
| Disintegration | ≤30 s | Yes | ODT 기능성 | DOE_RESPONSE |
| Friability | ≤1.0% | No (CBD 논문) | 취급성·기계적 건전성 | DOE_RESPONSE |
| Assay | 승인 기준 | Yes | 용량 정확성 | MONITOR_ONLY |

중요한 구분:

- is_cqa: 제품에서 중요한 품질특성인지 여부
- analysis_role: 이번 DoE에서 수학적으로 모델링할지 여부

제품 CQA 전체가 4개로 제한되는 것이 아니다. DOE_RESPONSE만 최대 4개이며 나머지는 MONITOR_ONLY로 측정·판정할 수 있다. 또한 논문의 friability처럼 저자가 CQA는 아니라고 분류했어도 최적화에 필요한 품질반응으로 모델링할 수 있다. 따라서 내부 객체는 일반 Quality Attribute를 담고 is_cqa와 analysis_role을 별도 축으로 유지해야 한다.

DOE_RESPONSE가 되려면 시험법, 단위, 요약함수, 방향과 절대 허용기준이 모두 있어야 한다. “최대한 높게” 같은 상대 목표만 있으면 영역 계산을 막는다.

### 화면 3. 초기위험평가와 요인 선택

기본 화면:

| 변수 | CMA/CPP | 연결 CQA | 위험 | 근거 | 선택 |
|---|---|---|---|---|---:|
| MCC 비율 | CMA | 경도, 붕해, 마손도 | High | 기능·문헌·FMEA | 선택 |
| CCS 비율 | CMA | 붕해, 용출 | High | 기능·문헌·FMEA | 선택 |
| 압축력 | CPP | 경도, 붕해, 마손도 | High | 공정 기전 | 선택 |

연구자는 최대 3개를 선택한다. 상세 보기에서는 cause → failure mode → local effect → CQA effect, S/O/D, 근거와 불확실성을 확인한다.

요인 후보가 4개 이상이면 두 선택지를 제공한다.

1. 위험·기전 근거로 최대 3개를 선택하고 나머지를 고정한다.
2. 고급 모드에서 별도 Screening DoE를 수행한다.

Screening은 기본 사용자 흐름에 강제하지 않는다.

### 화면 4. 3수준과 근거 입력

| 필드 | 예시 |
|---|---|
| factor | MCC 비율 |
| type | continuous CMA |
| unit | %w/w |
| low / center / high | 30 / 40 / 50 |
| reference value | 상류 처방 40% |
| range basis | preliminary study, literature, prior batch, expert proposal |
| source locator | 논문 §2.2.2 또는 batch ID |

규칙:

- reference_value와 center는 별도 필드다.
- 값이 같아도 근거가 다르면 우연히 일치한 것으로 기록한다.
- low < center < high, 단위, 설비 한계, 안전 한계, 조성 합계, balance 성분, 금지조합을 검사한다.
- 사용자가 입력한 값도 근거가 없으면 UNVERIFIED_PROPOSAL이다.

범위근거 gate 결과는 DOE_RANGE_READY, NEEDS_FEASIBILITY, ADVANCED_DESIGN_REQUIRED 중 하나다.

### 화면 5. 실험표와 결과

- 시스템이 설계형과 run 수를 설명한다.
- coded/actual matrix, randomization seed, 중심점 반복, run별 칭량표를 제공한다.
- 연구자 승인 후 WAITING_FOR_RESULTS로 전환한다.
- CSV/XLSX 업로드 또는 구조화 폼을 기본 입력으로 사용한다.
- 자연어 입력은 보조 기능이며, 추출값의 사용자 확인 전에는 분석하지 않는다.

### 화면 6. 모델·반응표면·영역·확인실험

각 반응별 표시:

- 자동 선택된 coded equation과 actual-unit equation
- R², adjusted R², predicted R², PRESS/RMSE, lack-of-fit, 잔차·영향점
- 선택된 항과 선택 이유
- VALID, VALID_WITH_FLAGS, MODEL_INADEQUATE
- Axes3D 반응표면, 2D contour, 실험점, 허용영역
- 다중 CQA 중첩영역과 verification point

모델이 부적합해도 “best available equation”은 설명용으로 표시할 수 있으나 영역 생성은 금지한다.

---

## 5. 상태기계

~~~mermaid
stateDiagram-v2
    [*] --> HANDOFF_RECEIVED
    HANDOFF_RECEIVED --> CQA_REVIEW
    CQA_REVIEW --> FMEA_REVIEW
    FMEA_REVIEW --> FACTOR_SELECTION
    FACTOR_SELECTION --> RANGE_EVIDENCE_CHECK
    RANGE_EVIDENCE_CHECK --> NEEDS_FEASIBILITY: 근거 부족
    RANGE_EVIDENCE_CHECK --> ADVANCED_DESIGN_REQUIRED: 혼합·범주형·HTC
    ADVANCED_DESIGN_REQUIRED --> DOE_PLAN_REVIEW: 검증된 설계 import
    NEEDS_FEASIBILITY --> WAITING_FEASIBILITY_RESULTS: 계획 승인
    WAITING_FEASIBILITY_RESULTS --> DOE_RANGE_READY: 경계 실행 가능
    WAITING_FEASIBILITY_RESULTS --> RANGE_REVISION_REQUIRED: 경계 실패
    WAITING_FEASIBILITY_RESULTS --> PROTOTYPE_REVISION_REQUIRED: 중심 실패
    RANGE_REVISION_REQUIRED --> RANGE_EVIDENCE_CHECK
    PROTOTYPE_REVISION_REQUIRED --> FMEA_REVIEW
    RANGE_EVIDENCE_CHECK --> DOE_RANGE_READY: 근거 충족
    DOE_RANGE_READY --> DOE_PLAN_REVIEW
    DOE_PLAN_REVIEW --> WAITING_FOR_RESULTS: 계획 승인
    DOE_PLAN_REVIEW --> RANGE_EVIDENCE_CHECK: 반려
    WAITING_FOR_RESULTS --> RESULT_QUALITY_REVIEW
    RESULT_QUALITY_REVIEW --> WAITING_FOR_RESULTS: 보완 필요
    RESULT_QUALITY_REVIEW --> MODEL_FIT: 통과
    MODEL_FIT --> MODEL_INADEQUATE: 검증 실패
    MODEL_INADEQUATE --> FMEA_REVIEW: 진단·개정
    MODEL_FIT --> PROVISIONAL_DESIGN_SPACE: 유효
    PROVISIONAL_DESIGN_SPACE --> WAITING_VERIFICATION_RESULTS
    WAITING_VERIFICATION_RESULTS --> REGION_REVISION_REQUIRED: 확인 실패
    REGION_REVISION_REQUIRED --> FMEA_REVIEW
    WAITING_VERIFICATION_RESULTS --> VERIFIED_OPERATING_REGION: 확인 통과
    VERIFIED_OPERATING_REGION --> [*]
~~~

CONTROL_STRATEGY, PPQ_READY, COMMERCIAL_RELEASE 상태는 만들지 않는다.

상태 이름을 혼용하지 않는다. PROVISIONAL_DESIGN_SPACE와 VERIFIED_OPERATING_REGION은 study workflow state이고, DesignSpaceVersion.status의 PROVISIONAL/VERIFIED/INVALIDATED는 artifact 상태다. 전이는 reason-code registry가 담당하며 둘을 문자열 비교로 암묵적으로 연결하지 않는다.

### 5.1 공통 전이 규칙

- 모든 mutation은 Expected-State-Version을 검사한다.
- 외부 실험을 기다릴 때 checkpoint를 저장하고 요청을 종료한다.
- 같은 Idempotency-Key의 이벤트는 한 번만 적용한다.
- 승인·반려·override는 actor, 시각, 사유, 영향 artifact를 기록한다.
- 실패는 문자열 분기 대신 versioned reason_code로 라우팅한다.
- 과거 결과를 덮어쓰지 않고 새 artifact version을 만든다.

---

## 6. 단계별 처리 계약

### D0. Immutable Candidate Handoff

필수 입력:

- candidate_id@version, formulation fingerprint
- QTPP snapshot
- 성분명·등급·기능·mg·%w/w
- 공정경로와 단계
- 배치 규모와 설비
- 기존 Rulebook 판정과 evidence snapshot
- 미해결 값과 가정

상류 mg 값에는 반드시 value_role=REFERENCE_PROTOTYPE을 붙인다. 이 값을 factor center로 복사하는 코드는 금지한다.

### D1. CQA Contract

CQA Mapper는 QTPP, 제형, 방출 특성, 환자·투여 요구, 공정경로를 이용해 CQA 후보를 제안한다. QTPP가 CQA를 기계적으로 “자동 도출”하는 것이 아니라 잠재 품질특성을 매핑하고 연구자가 확정한다.

각 DOE_RESPONSE 필수값:

- response definition과 요약함수
- 단위
- LE, GE, BETWEEN, TARGET_TOL, PASS_FAIL 중 하나
- 수치 기준 또는 명시적 판정절차
- 시험법 ID·버전
- 표본수·반복 구조
- 기준 출처와 적용 범위

### D2. Initial Risk Assessment / FMEA

입력은 승인된 CQA, unit operation map, 성분·등급, 기존 배합·공정 Rulebook, 문헌과 실험데이터다.

FMEA 행:

> material/process cause → failure mode → local effect → CQA effect → existing control/detection → S/O/D → candidate factor

생성 원칙:

- Rulebook 매칭은 RULE_SUPPORTED로 표시한다.
- 실제 batch 데이터는 DATA_SUPPORTED로 표시한다.
- LLM이 추가한 누락 가능성은 LLM_HYPOTHESIS로 분리한다.
- Severity는 CQA 영향에 근거한다.
- Occurrence는 관찰 데이터가 없으면 UNKNOWN이다.
- Detectability는 실제 시험법·관찰기전이 없으면 확정하지 않는다.
- RPN은 정렬 보조값이며 RPN 하나로 요인을 자동 제외하지 않는다.
- 고심각도 행을 제외하려면 대체 근거와 연구자 사유가 필요하다.

### D3. Factor Selection

- 기본 RSM 요인은 2개 또는 3개다.
- 연구자가 최대 3개를 선택한다.
- 각 요인은 하나 이상의 CQA와 연결되어야 한다.
- 선택하지 않은 고위험 변수는 고정값·고정 근거와 not_evaluated scope를 남긴다.
- 4개 이상을 탐색할 필요가 있으면 OPTIONAL_SCREENING을 제안한다.

### D4. Range Evidence Gate

| 상태 | 의미 | 신규 API에서 RSM 직행 |
|---|---|:---:|
| MEASURED_PRIOR_BATCH | 동일 API·등급·설비·규모의 실제 batch | 가능 |
| FEASIBILITY_CONFIRMED | 이 프로젝트 micro-study로 확인 | 가능 |
| VERIFIED_EXTERNAL_DATA | 적용성이 확인된 외부 원자료 | 조건부 가능 |
| REPORTED_NO_RAW_DATA | 논문이 선행시험을 보고했으나 원자료 없음 | 문헌 재현 모드만 가능 |
| EXPERT_PROPOSAL | 전문가 제안, 직접 근거 없음 | 불가 |
| UNVERIFIED_PROPOSAL | UI에 입력했으나 근거 미검증 | 불가 |

신규 API 프로젝트에서 마지막 세 상태만 있으면 NEEDS_FEASIBILITY다. 문헌 재현 데모에서는 REPORTED_NO_RAW_DATA 범위를 사용할 수 있지만 화면에 “문헌 재현 전용, 독립 검증 아님”을 표시한다.

### D5. Feasibility Range-confirmation Micro-study

목적은 최적화가 아니라 제안한 경계가 제조·측정 가능한지 확인하는 것이다.

기본 계획은 2k+1 조건이다. 여기서 2k+1은 2의 k제곱 + 1 full factorial이 아니라, 각 요인의 low/high를 하나씩 확인하는 2k개 축점 + 중심점 1개라는 뜻이다.

- 2요인: 중심 + X1 low/high + X2 low/high = 5조건
- 3요인: 중심 + X1 low/high + X2 low/high + X3 low/high = 7조건
- 한 요인을 바꿀 때 다른 요인은 중심에 둔다.

평가:

- 제조 가능 여부와 중대한 공정 실패
- 반응이 시험법 범위에서 측정 가능한지
- 치명적 배합금기·분해·고체상 변화
- 설비·조성 제약 위반
- 중심점 prototype 자체의 기본 성립성

최종 CQA 규격을 모두 만족해야 통과하는 단계는 아니다.

| 결과 | 다음 상태 |
|---|---|
| 중심·모든 경계 실행 가능 | DOE_RANGE_READY |
| 일부 경계만 실패 | RANGE_REVISION_REQUIRED |
| 중심점 실패 | PROTOTYPE_REVISION_REQUIRED |
| 결과 누락·시험 오류 | WAITING_FEASIBILITY_RESULTS 또는 재시험 검토 |

Feasibility 결과는 기본적으로 RSM fitting set에 넣지 않는다. 사후 편입이 필요하면 분석계획을 새 버전으로 만들고 독립성·방법 일치성을 검증한다.

### D6. DoE Design Selection

| 요인 구조 | 기본 설계 | 기본 run 수 | 비고 |
|---|---|---:|---|
| 연속형 1개 | 3수준 quadratic with replication | 7 | low 2, center 3, high 2 |
| 연속형 2개 | face-centered CCD, α=1 | 13 | 4 factorial + 4 axial + center 5 |
| 연속형 3개 | Box–Behnken Design | 17 | 12 edge-midpoint + center 5 |
| 4개 이상 후보 | optional screening | 정책별 | RSM 전 active factor 축소 |
| mixture/sum constraint | mixture design 필요 | 별도 | 표준 CCD/BBD 금지 |
| 범주형 포함 | custom/D-optimal 검토 | 별도 | 숫자 3수준으로 위장 금지 |
| hard-to-change | split-plot 검토 | 별도 | 완전무작위화 금지 |

설계 Validator 필수 검사:

- coded↔actual round trip
- 설계행렬 rank와 intended model estimability
- 중복·누락 run
- 중심점 반복수와 pure error 자유도
- random seed와 run order
- low/center/high 범위
- 모든 run의 조성합, 음수 balance, 금지조합
- 설비 운전범위와 안전범위
- alias/block 구조

구형 pyDOE에 직접 결합하지 않는다. Python 3.13/NumPy 호환성 문제가 있는 pyDOE 대신 pyDOE3 또는 내부 생성기를 adapter 뒤에 두고, 생성 후 자체 Validator를 반드시 실행한다.

### D7. Run Sheet / Research Protocol

Run Sheet Compiler는 승인된 actual matrix를 다음으로 변환한다.

- run ID와 무작위 실행순서
- 각 run의 성분별 칭량값
- 고정값과 변경값
- 등록 설비와 설정값
- 공정 단계·샘플링·시험항목
- 중단 기준과 일탈 기록란
- 필요한 정제 수와 원료 예산

근거가 없는 RPM·시간·압력은 만들지 않고 REQUEST_DATA를 반환한다. 출력은 연구자 검토용 실행 프로토콜이며 GMP SOP나 검증된 제조지시서가 아니다.

### D8. Result Ingestion and Quality Gate

권장 입력 우선순위:

1. 구조화 CSV/XLSX + 원자료 링크
2. 화면 폼
3. 자연어 실험노트 파싱 후 연구자 확인

저장 단위:

- run_id, 독립 batch_id, parent_blend_id
- planned settings와 actual settings
- test method/version
- individual values와 summary statistic
- 단위, 시점, 보관조건
- raw data refs
- deviation와 review status
- 독립 제조반복/배치 내 반복/기술 반복 구분

분석 차단 조건:

- 단위 불일치 또는 변환 불가능
- run–batch 연결 없음
- 독립성 UNKNOWN
- 필수 반응 누락
- 미해결 일탈
- 계획과 actual setting의 허용범위 초과
- 시험법 버전 혼재

### D9. Automatic Hierarchical Model Selection

사용자가 회귀항을 하나씩 고르지 않는다. 대신 결과를 보기 전에 버전 고정된 모델 선택 정책을 적용한다.

후보 항:

- intercept
- main effects
- two-factor interactions
- pure quadratic terms
- 계획된 block term
- response별 사전 허용 transformation

강한 계층성:

- XiXj가 있으면 Xi, Xj가 모두 있어야 한다.
- Xi²가 있으면 Xi가 있어야 한다.
- block term은 선택 대상이 아니라 계획대로 유지한다.

선택 알고리즘:

1. 사전 정의된 계층적 후보 모형 집합을 생성한다.
2. rank deficient, 잔차 자유도 부족, 심각한 condition number를 가진 모형을 제거한다.
3. 각 모형에서 OLS, PRESS/LOOCV, predicted R², adjusted R², RMSE, AICc를 계산한다.
4. 중심점 반복이 있으면 pure error와 lack-of-fit을 계산한다. LOF_NOT_ESTIMABLE을 비유의와 혼동하지 않는다.
5. 잔차 정규성·등분산성·독립성, 영향점, 비현실 예측을 진단한다.
6. 기본 선택정책은 CV RMSE가 최소인 모형과 one-standard-error 범위에 든 모형군을 만든 뒤, 그중 항 수가 가장 적은 계층적 모형을 선택하는 것이다. 다시 동률이면 AICc, adjusted R², 정규화한 formula 문자열 순으로 결정한다. 정책은 model_selection_policy로 버전 고정한다.
7. 선택 과정과 탈락 이유를 selection_history에 보존한다.
8. 가장 나은 모형도 validation gate를 통과하지 못하면 MODEL_INADEQUATE로 표시하고 영역을 만들지 않는다.

표시 지표:

- R², adjusted R², predicted R²
- PRESS, RMSE, AICc
- residual/pure-error/lack-of-fit df
- LOF p-value 또는 NOT_ESTIMABLE
- max leverage, Cook's distance
- 잔차 플롯과 actual-vs-predicted
- transformation과 보고 척도

R²가 가장 높은 식을 무조건 선택하지 않는다. 작은 실험에서 과도한 항은 훈련 R²를 높이면서 예측성을 떨어뜨릴 수 있기 때문이다.

### D10. Response Surface and Provisional Design Space

시각화:

- 2요인: Axes3D에 X1, X2, 예측 Y를 표시하고 실험점을 겹친다.
- 바닥면에 2D contour와 규격 경계를 투영한다.
- 3요인: X3를 low/center/high 또는 slider 값으로 고정한 slice를 제공한다.
- 반응별 tab과 모든 CQA 중첩 view를 제공한다.
- 실험영역 밖은 색칠하지 않고 EXTRAPOLATION으로 마스킹한다.

영역 계산:

1. 설계행렬이 지지하는 domain을 정의한다. 기본은 설계점 convex hull + 조성·설비 제약이다.
2. domain 내부 grid에서 반응별 예측분포를 계산한다.
3. 각 CQA의 절대 criterion을 적용한다.
4. uncertainty policy에 따라 평균 기준, 동시 예측구간 또는 공동 통과확률을 계산한다.
5. 모든 DOE_RESPONSE 조건을 만족하는 교집합을 저장한다.

데모 기본값으로 공동 통과확률 p_min=0.90을 사용할 수 있으나 보편 규제 기준으로 표현하지 않는다. 반응 간 독립을 가정해 확률을 곱한 경우 dependence_assumption=INDEPENDENT_APPROXIMATION을 반드시 표시한다.

생성 조건:

- 모든 response model이 VALID 또는 허용된 VALID_WITH_FLAGS
- 영역이 experimental domain 내부
- 기준·모델·grid·seed·불확실성 방법이 잠김
- feasible set이 비어 있지 않음

출력 상태는 PROVISIONAL_DESIGN_SPACE다.

### D11. Independent Verification

verification plan은 결과를 보기 전에 잠근다.

권장 역할:

- SETPOINT: 권장점 재현
- BOUNDARY: 영역 경계의 지배 CQA 확인
- ROBUSTNESS: 작은 동시 변동에서 통과 확인
- CHALLENGE: 선택 사항; 예상 실패의 식별력 확인
- REFERENCE_EXISTING: 참고만 하며 승격 근거로 사용하지 않음

독립성:

- 새 제조 batch/lot이어야 한다.
- 같은 blend를 나눈 정제나 재측정은 독립 batch가 아니다.
- verification batch는 model fitting set에 넣지 않는다.

최소 batch 수를 전 프로젝트에 동일하게 고정하지 않는다. CBD 문헌 재현은 저자가 수행한 최적점 3개 독립 lot을 그대로 재현한다. 신규 API 프로젝트는 위험도, 영역 크기, 허용 예측오차에 따라 setpoint·boundary·robustness의 수와 반복을 계획한다.

| 규격 | 잠긴 예측구간 | 해석 |
|---|---|---|
| Pass | Inside | 해당 점 확인 |
| Pass | Outside | 제품은 통과했으나 모델 불일치; 모델/영역 재검토 |
| Fail | Inside | 규격 또는 점 선택 문제; 영역 승격 금지 |
| Fail | Outside | 모델·영역 무효화 가능성이 큼 |

모든 필수 점과 반응이 사전 계획을 충족한 뒤 연구자가 승인해야 VERIFIED_OPERATING_REGION으로 승격한다. 이 상태도 해당 설비·규모·원료등급·시험법·실험 domain에서의 내부 검증을 뜻할 뿐 규제 승인 Design Space를 의미하지 않는다.

### D12. Lab-in-the-loop and Backtracking

실험 실패는 곧바로 새 처방을 생성하는 신호가 아니다.

~~~mermaid
flowchart TD
    A["실험결과"] --> B["구조화 + 사용자 확인"]
    B --> C["결과 품질·규격 판정"]
    C --> D["경쟁 가설 최대 3개"]
    D --> E["판별시험 선택"]
    E --> F["확인결과"]
    F --> G["개정 directive"]
    G --> H["Rulebook 재검증"]
~~~

Reflection Agent 허용 출력:

- DOE_AUGMENT: 추가 설계점 또는 반복
- FACTOR_RANGE_REVISION: 경계 축소·이동
- FACTOR_SET_REVISION: 요인 재선택
- METHOD_OR_PROCESS_VARIANCE_REVIEW: 시험법·공정 편차 점검
- PROTOTYPE_REVISION: 상류 후보 전제 수정 요청

LLM은 데이터베이스를 직접 고치지 않는다. 구조화된 directive를 만들고 연구자 승인 후 Orchestrator가 새 artifact를 생성한다.

---

## 7. 핵심 데이터 계약

실제 구현은 Pydantic model + JSON Schema로 관리한다.

### 7.1 CandidateDevelopmentHandoff

~~~yaml
handoff_id: uuid
project_id: uuid
candidate_id: string
candidate_version: integer
formulation_fingerprint: sha256
qtpp_snapshot_id: uuid
dosage_form: string
target_strength_mg: number
batch_scale:
  value: number
  unit: string
ingredients:
  - material_id: string
    material_grade: string
    function: string
    amount_mg: number
    percent_w_w: number
    value_role: REFERENCE_PROTOTYPE
    evidence_ref: string|null
process_route_id: string
process_steps: []
fixed_parameters: []
unresolved_fields: []
evidence_snapshot_id: uuid
rulebook_release_id: string
created_by: string
created_at: datetime
~~~

### 7.2 CQASpec

~~~yaml
cqa_id: string
name: string
is_cqa: true|false
analysis_role: DOE_RESPONSE|MONITOR_ONLY|NOT_APPLICABLE
target_text: string
acceptance_operator: LE|GE|BETWEEN|TARGET_TOL|PASS_FAIL
lower: number|null
upper: number|null
target: number|null
target_tolerance: number|null
unit: string
summary_definition: string
test_method_id: string
test_method_version: string
sample_structure: object
rationale: string
evidence_refs: []
approval_status: DRAFT|APPROVED|REJECTED
~~~

### 7.3 FMEARow and FactorDefinition

~~~yaml
fmea_row:
  cause: string
  failure_mode: string
  local_effect: string
  cqa_effect_ids: []
  unit_operation_id: string|null
  severity: integer
  occurrence: integer|null
  detectability: integer|null
  occurrence_status: SCORED|UNKNOWN
  evidence_class: RULE_SUPPORTED|DATA_SUPPORTED|LITERATURE|LLM_HYPOTHESIS
  evidence_refs: []
  candidate_factor_id: string|null

factor:
  factor_id: string
  name: string
  kind: CMA|CPP|CATEGORICAL|MIXTURE_COMPONENT|HARD_TO_CHANGE
  data_type: CONTINUOUS|CATEGORICAL
  unit: string|null
  reference_value: number|string|null
  reference_source: string|null
  low: number|string
  center: number|string
  high: number|string
  range_basis: MEASURED_PRIOR_BATCH|FEASIBILITY_CONFIRMED|VERIFIED_EXTERNAL_DATA|REPORTED_NO_RAW_DATA|EXPERT_PROPOSAL|UNVERIFIED_PROPOSAL
  range_evidence_refs: []
  constraints: []
  selected_for_doe: boolean
  fmea_refs: []
~~~

### 7.4 FeasibilityPlan and DoEPlan

~~~yaml
feasibility_plan:
  plan_id: uuid
  factor_version_ids: []
  design_type: AXIAL_2K_PLUS_1
  conditions: []
  acceptance_checks: []
  fitting_eligibility: EXCLUDED_BY_DEFAULT
  approved_by: string|null

doe_plan:
  plan_id: uuid
  version: integer
  design_type: ONE_FACTOR_QUADRATIC|FCCD|BBD|OPTIONAL_SCREENING|IMPORTED
  factor_version_ids: []
  response_version_ids: []
  intended_model_family: HIERARCHICAL_QUADRATIC
  coded_matrix_ref: uri
  actual_matrix_ref: uri
  random_seed: integer
  center_points: integer
  block_definition: object|null
  validator_report_ref: uri
  source: SYSTEM_GENERATED|RESEARCHER_PROVIDED|LITERATURE_REPLAY
  approval_status: DRAFT|APPROVED|REJECTED
~~~

### 7.5 TestResult and ResponseModel

~~~yaml
test_result:
  result_id: uuid
  run_id: string
  batch_id: string
  parent_blend_id: string|null
  response_id: string
  test_method_id: string
  test_method_version: string
  planned_settings: object
  actual_settings: object
  individual_values: []
  summary_statistic: object
  unit: string
  raw_data_refs: []
  replicate_independence: INDEPENDENT_BATCH|WITHIN_BATCH|TECHNICAL_REPEAT|UNKNOWN
  deviation: object|null
  human_verification_status: PENDING|CONFIRMED|REJECTED

response_model:
  model_id: uuid
  response_id: string
  formula_coded: string
  formula_actual: string
  terms: []
  coefficients: object
  covariance_ref: uri
  fit_stats: object
  lack_of_fit: object|null
  residual_diagnostics: object
  transformation: object|null
  selection_policy_version: string
  selection_history: []
  input_result_ids: []
  tool_versions: object
  validation_status: VALID|VALID_WITH_FLAGS|MODEL_INADEQUATE
~~~

### 7.6 DesignSpaceVersion and VerificationPlan

~~~yaml
design_space:
  design_space_id: uuid
  version: integer
  model_ids: []
  supported_domain_ref: uri
  domain_membership_policy: object
  constraints: []
  uncertainty_policy: object
  grid_policy: object
  feasible_region_ref: uri
  visualization_refs: []
  scope:
    equipment_id: string
    batch_scale: object
    material_grades: []
    fixed_parameters: []
    unmanaged_parameters: []
    monitor_only_cqas: []
    extrapolation_excluded: true
  status: PROVISIONAL|VERIFIED|INVALIDATED

verification_plan:
  plan_id: uuid
  design_space_id: uuid
  design_space_version: integer
  points: []
  batches_per_point: integer
  required_response_ids: []
  prediction_interval_policy: object
  locked_hash: sha256
  locked_at: datetime
  approved_by: string
~~~

---

## 8. 필요한 룰북과 마스터

룰북은 LLM prompt가 아니라 결정론 서비스가 평가하는 versioned policy다.

| ID | 파일/테이블 | 역할 |
|---|---|---|
| RB00 | development_policy.yaml | 최대 CQA/요인, 지원 설계, 상태·override 정책 |
| RB01 | handoff_readiness_rules.csv | 조성·단위·등급·공정·설비·시험법 진입 검사 |
| RB02 | qtpp_cqa_mapping.csv | 제형/QTPP → CQA 후보 매핑 |
| RB03 | cqa_response_eligibility.csv | DOE_RESPONSE 필수 기준·시험법·요약함수 검사 |
| RB04 | fmea_failure_mode_master.csv | 단위공정·원료·CPP/CMA별 알려진 failure mode |
| RB05 | fmea_scoring_policy.yaml | S/O/D 정의, UNKNOWN 처리, 고심각도 보호 |
| RB06 | factor_selection_rules.csv | CQA 연결, 조절 가능성, 교락, 제외 조건 |
| RB07 | factor_range_evidence_rules.csv | 경계별 허용 evidence class와 적용성 검사 |
| RB08 | feasibility_decision_rules.csv | NEEDS_FEASIBILITY와 결과 라우팅 |
| RB09 | doe_design_selection_rules.csv | 1/2/3요인 설계 선택, 미지원 구조 차단 |
| RB10 | doe_matrix_validation_rules.csv | rank, bounds, center, randomization, 조성 제약 |
| RB11 | protocol_compilation_rules.csv | 칭량, 설비, 단계, 샘플링, 중단 기준 완결성 |
| RB12 | result_quality_rules.csv | 단위, 방법 버전, 독립성, 누락, 일탈 판정 |
| RB13 | model_candidate_policy.yaml | 계층적 후보군과 transformation 허용범위 |
| RB14 | model_validation_rules.csv | df, rank, LOF, predictive performance, 잔차 gate |
| RB15 | model_selection_policy.yaml | scoring, 단순성 tie-break, 재현 가능한 자동 선택 |
| RB16 | design_region_rules.csv | domain, criterion, uncertainty, 빈 영역 처리 |
| RB17 | verification_rules.csv | plan lock, 독립성, coverage, 승격·무효화 |
| RB18 | labloop_backtrack_rules.csv | 실패 패턴 → 확인시험·복귀 상태 |
| M01 | test_method_registry.csv | quantity kind, 단위, 반복구조, 방법 버전 |
| M02 | equipment_capability_master.csv | 설비별 허용 운전범위와 분해능 |
| M03 | material_grade_master.csv | 원료 identity, grade, 기능, 제약 |
| M04 | unit_conversion_registry.yaml | 허용 단위변환과 정밀도 |
| M05 | evidence_permission_matrix.csv | 출처 유형별 허용 용도 |
| M06 | confirmation_test_master.csv | Lab-in-the-loop가 선택할 수 있는 확인시험 |
| M07 | reason_code_catalog.csv | 상태 전이의 단일 reason-code registry |

### 8.1 룰 실행 계약

- eval() 금지. AST allowlist 또는 구조화 predicate DSL만 사용한다.
- 모든 필드경로·함수 인자·반환형을 typed RuleContext와 대조한다.
- load_enabled와 enforcement_enabled를 분리한다.
- production은 APPROVED release만 집행한다.
- demo/문헌 데이터는 sandbox namespace에 격리한다.
- rule 결과는 PASS, WARNING, REQUEST_DATA, ROUTE, BLOCK_STAGE, INVALIDATE 중 하나다.
- BLOCK_STAGE와 INVALIDATE는 연구자가 우회할 수 없다.
- 근거 등급은 연구자가 수동 상향할 수 없다. 새 근거 record로만 승격한다.

---

## 9. 저장 구조

### 9.1 주요 테이블

| 테이블 | 주요 키/관계 |
|---|---|
| development_study | study_id, handoff, current_state, state_version |
| candidate_handoff | immutable candidate snapshot, fingerprint |
| cqa_spec_version | study–CQA contract |
| fmea_version, fmea_row | 위험가설과 근거 lineage |
| factor_version, factor_range_evidence | 기준값, 3수준, 출처 |
| feasibility_plan, feasibility_condition | 2k+1 범위확인 계획 |
| doe_plan, doe_run | coded/actual matrix와 실행상태 |
| test_result, raw_artifact | 결과와 원자료 |
| analysis_plan | 모델 후보·선택 정책 잠금 |
| response_model_version | 식, 계수, 공분산, 진단, selection history |
| design_space_version | supported domain, constraints, grid/region artifact |
| verification_plan, verification_point | 사전잠금 확인계획 |
| decision_ledger | rule·human·agent 결정 |
| event_log | append-only state event |
| approval, override_decision | 승인과 허용된 override |

### 9.2 저장 원칙

- 큰 행렬·그림·chromatogram은 object storage, DB에는 URI와 checksum을 저장한다.
- 모델은 pickle만 저장하지 않고 formula, coefficient, covariance, package version을 구조화 저장한다.
- 모든 artifact는 created_from, supersedes, rulebook_release_id, tool_versions를 가진다.
- 삭제 대신 SUPERSEDED/INVALIDATED로 이력을 보존한다.

---

## 10. API 계약

| Method | Endpoint | 책임 |
|---|---|---|
| POST | /api/development-studies/from-candidate | 선택 후보 버전으로 handoff·study 생성 |
| GET | /api/development-studies/{id} | 상태, blockers, 다음 행동 조회 |
| GET/PUT | /api/development-studies/{id}/cqas | CQA 표 조회·승인 |
| POST | /api/development-studies/{id}/fmea/draft | FMEA 초안 생성 |
| PATCH | /api/development-studies/{id}/fmea | 행 수정과 연구자 판단 기록 |
| POST | /api/development-studies/{id}/fmea/approve | 위험평가 승인 |
| PUT | /api/development-studies/{id}/factors | 최대 3개 요인·3수준 제출 |
| POST | /api/development-studies/{id}/range-evidence/evaluate | direct DoE/feasibility/advanced route 판정 |
| POST | /api/development-studies/{id}/feasibility-plans | 2k+1 계획 생성 |
| POST | /api/feasibility-plans/{id}/results | feasibility 결과 제출·판정 |
| POST | /api/development-studies/{id}/doe-plans | 설계 선택·행렬 생성 |
| POST | /api/development-studies/{id}/doe-plans/import | 문헌/외부 행렬 import 후 동일 검증 |
| POST | /api/doe-plans/{id}/approve | 실험계획 잠금 |
| POST | /api/doe-plans/{id}/protocol/compile | run sheet·프로토콜 생성 |
| POST | /api/doe-plans/{id}/results/import | 구조화 결과·원자료 업로드 |
| POST | /api/doe-plans/{id}/results/parse-notes | 자연어 보조 파싱 |
| POST | /api/doe-plans/{id}/results/confirm | 연구자 추출값 확인 |
| POST | /api/doe-plans/{id}/models/fit | 자동 계층적 모델 선택 |
| GET | /api/response-models/{id}/diagnostics | 식·지표·잔차·selection history |
| POST | /api/development-studies/{id}/design-spaces | provisional 영역 계산 |
| GET | /api/design-spaces/{id}/plots | Axes3D/contour/slice artifact |
| POST | /api/design-spaces/{id}/verification-plans | 확인점 생성·잠금 |
| POST | /api/verification-plans/{id}/results | 독립 확인결과 제출 |
| POST | /api/verification-plans/{id}/evaluate | 확인 gate와 승격/복귀 |
| POST | /api/development-studies/{id}/feedback | 실패 가설·판별시험·revision draft |
| GET | /api/development-studies/{id}/trace | 전체 lineage와 decision ledger |

모든 mutation header:

~~~text
Idempotency-Key
Expected-State-Version
Actor-ID
Approval-Note 또는 Reason
~~~

---

## 11. 코드 구조와 기존 저장소 접점

~~~text
formula/
├── orchestrator/                  # 기존 CandidateDiscoveryGraph 유지
├── development/
│   ├── contracts.py
│   ├── handoff.py
│   ├── graph.py
│   ├── state_machine.py
│   ├── transitions.py
│   ├── approvals.py
│   ├── promotion.py
│   └── backtrack.py
├── qbd/
│   ├── cqa/{mapper.py, validator.py}
│   ├── fmea/{engine.py, hypothesis.py, scoring.py, factor_mapper.py}
│   ├── factors/{validator.py, evidence_gate.py}
│   ├── feasibility/{planner.py, evaluator.py}
│   ├── doe/{selector.py, generator.py, coding.py, validator.py, importer.py}
│   ├── analysis/{candidate_models.py, fitter.py, selector.py, diagnostics.py}
│   ├── design_space/{domain.py, engine.py, uncertainty.py, visualization.py}
│   └── verification/{planner.py, evaluator.py}
├── experiments/
│   ├── protocol_compiler.py
│   ├── ingestion.py
│   ├── result_quality.py
│   └── repository.py
└── agents/
    ├── fmea_hypothesis.py
    ├── explainer.py
    ├── diagnosis.py
    └── reflect.py

database/07_doe/
├── governance/
├── cqa/
├── fmea/
├── factors/
├── feasibility/
├── planning/
├── execution/
├── analysis/
├── region/
├── verification/
└── masters/
~~~

기존 저장소 변경 원칙:

1. 기존 formula/orchestrator/graph.py의 후보발견 그래프를 직접 비대하게 만들지 않는다.
2. consensus 이후 연구자가 후보를 선택하면 새 ExperimentalDevelopmentGraph를 시작한다.
3. 기존 RulebookRegistry와 restricted condition evaluator는 재사용하되 DoE용 typed context를 별도로 둔다.
4. 기존 formula/feedback/labloop.py는 자연어 parser와 확인시험 추천기로 재사용하되 후보별 CQA 규격·시험법·시점과 연결하도록 확장한다.
5. wetlab_feedback_rules.csv의 전역 고정 임계값을 사용하지 말고 CQASpec 기준을 읽는다.
6. 통계 core는 LLM/LangGraph 없이 단위 테스트 가능해야 한다.

### 11.1 권장 기술 스택

- API: FastAPI + Pydantic
- 상태: 명시적 state machine 또는 LangGraph checkpoint
- DB: PostgreSQL; 데모는 SQLite 허용
- 파일: S3 호환 object storage
- 행렬: NumPy/Pandas + pyDOE3 adapter 또는 내부 generator
- 회귀·진단: statsmodels/scipy
- 정적 그림: Matplotlib + mpl_toolkits.mplot3d.Axes3D
- 웹 상호작용: Plotly를 선택적으로 추가하되 계산 결과는 동일 backend에서 받음
- Frontend: 기존 웹 UI에 wizard route 추가

의존성 버전을 lock하고 Python/NumPy 호환 CI를 둔다. 특히 구형 pyDOE import 실패가 다시 발생하지 않도록 금지 dependency test를 추가한다.

---

## 12. CBD ODT 문헌 재현 데모

기준 논문:

> Monton C. et al. Quality by Design–Driven Formulation Development of Cannabidiol Orally Disintegrating Tablets. Scientifica. 2026;2026:3553253. DOI: 10.1155/sci5/3553253.

### 12.1 Handoff reference formulation

| 성분 | mg/tablet | %w/w | 역할 |
|---|---:|---:|---|
| CBD | 10 | 4.0 | API |
| Spray-dried mannitol | 127 | 50.8 | filler |
| MCC | 100 | 40.0 | filler/binder |
| CCS | 7.5 | 3.0 | superdisintegrant |
| Fumed silica | 2.5 | 1.0 | glidant |
| Sucralose | 0.5 | 0.2 | sweetener |
| MgSt | 2.5 | 1.0 | lubricant |
| Total | 250 | 100 | — |

모든 값의 value_role은 REFERENCE_PROTOTYPE이다.

### 12.2 선택 반응과 요인

DoE response:

- Hardness: 4–6 kgf
- Disintegration time: ≤30 s
- Friability: ≤1.0%

요인:

| 요인 | low | center | high |
|---|---:|---:|---:|
| Compression force | 1250 psi | 1500 psi | 1750 psi |
| MCC | 30% | 40% | 50% |
| CCS | 1% | 3% | 5% |

이 논문에서는 prototype의 MCC 40%와 CCS 3%가 BBD center와 일치한다. 아키텍처는 이 사례를 일반 규칙으로 학습하거나 자동 적용하면 안 된다.

### 12.3 선행근거 상태

논문은 수준을 preliminary study와 초기위험평가에 기반했다고 보고하지만 선행시험 원자료는 공개하지 않았다.

~~~yaml
prior_study_status: REPORTED_NO_RAW_DATA
source_type: PUBLISHED_ARTICLE
source_locator: Methods 2.2.2
raw_data_available: false
independently_verified: false
use_reported_ranges: true
usage_scope: LITERATURE_REPLAY_ONLY
~~~

사용자가 이 문장을 직접 입력하게 하지 않는다. 문헌 fixture metadata를 읽어 UI가 자동 표시한다.

### 12.4 데모 실행

1. 위 3개 요인으로 BBD 17-run matrix를 생성한다.
2. 논문 Table 9의 관찰값을 LITERATURE_DIRECT fixture로 import한다.
3. 시스템이 논문 회귀식을 복사하지 않고 원자료에서 모형을 다시 적합한다.
4. 자동 모델 선택과 논문 보고식의 차이를 비교한다.
5. Axes3D로 hardness, DT, friability 곡면을 생성한다.
6. 세 기준의 교집합을 PROVISIONAL_DESIGN_SPACE로 표시한다.
7. 논문의 최적점 1400 psi / MCC 35% / CCS 1%와 3개 독립 lot 결과를 verification fixture로 별도 입력한다.
8. verification 결과가 잠긴 기준과 예측구간을 통과할 때만 replay study를 VERIFIED_OPERATING_REGION으로 표시한다.

문헌의 식·표·중심점 예측값이 서로 맞지 않으면 ingestion audit가 PUBLISHED_REPORT_INCONSISTENCY를 생성한다. 시스템은 식을 임의로 고치지 않고 원자료 재적합 결과와 출판 보고값을 병렬로 보여준다.

### 12.5 데모에서 주장하면 안 되는 것

- CBD가 신약 API라는 주장
- 공개되지 않은 preliminary batch를 Formula 1이 재현했다는 주장
- CBD 문헌 범위가 다른 API에도 적합하다는 주장
- 논문의 control space를 Formula 1 관리전략으로 구현했다는 주장

---

## 13. 신규 API 실제 사용 시나리오

~~~mermaid
flowchart TD
    A["후보처방 reference"] --> B{"요인범위 근거?"}
    B -->|"충분"| C["RSM 계획"]
    B -->|"부족"| D["NEEDS_FEASIBILITY"]
    D --> E["5 또는 7개 범위확인 조건"]
    E -->|"경계 가능"| C
    E -->|"경계 실패"| F["범위 축소·이동"]
    E -->|"중심 실패"| G["prototype 재설계"]
    F --> D
    G --> A
~~~

예시:

1. 상류 에이전트가 MCC 42%, CCS 2%, 압축력 미정인 후보를 만든다.
2. 이 숫자들은 reference_value이며 center가 아니다.
3. FMEA가 MCC, CCS, 압축력을 우선 변수로 제안한다.
4. 연구자가 30/40/50%, 1/3/5%, 1200/1500/1800 psi를 제안한다.
5. 동일 API·설비의 범위근거가 없으므로 NEEDS_FEASIBILITY다.
6. 7조건 axial micro-study를 수행한다.
7. 1800 psi에서 capping이 발생하면 high를 낮추고 경계를 재확인한다.
8. 범위가 확인된 뒤 17-run BBD를 생성한다.

시스템은 4단계의 제안값을 “문헌상 흔한 값”이라는 이유로 바로 실행범위로 승인하면 안 된다.

---

## 14. 인수 테스트

### 14.1 Handoff/CQA

- 동일 후보 버전은 동일 fingerprint를 만든다.
- 상류 처방값은 REFERENCE_PROTOTYPE으로 저장된다.
- reference_value와 center가 다른 factor가 정상 처리된다.
- CQA 전체 수는 4개를 초과할 수 있지만 DOE_RESPONSE는 4개를 초과할 수 없다.
- 절대 criterion 또는 시험법이 없는 DOE_RESPONSE는 승인되지 않는다.

### 14.2 FMEA/Range/Feasibility

- Occurrence 근거가 없으면 UNKNOWN이다.
- 고심각도 항목이 낮은 RPN만으로 자동 삭제되지 않는다.
- 선택 RSM 요인은 3개를 초과할 수 없다.
- range basis가 UNVERIFIED_PROPOSAL뿐이면 신규 API study는 NEEDS_FEASIBILITY다.
- 2요인은 5개, 3요인은 7개 feasibility 조건을 만든다.
- 중심점 실패는 PROTOTYPE_REVISION_REQUIRED로 간다.
- 경계 실패는 RANGE_REVISION_REQUIRED로 간다.

### 14.3 DoE/Model

- 2요인 FCCD는 기본 13 runs, 3요인 BBD는 기본 17 runs이다.
- 같은 factor contract와 seed는 같은 matrix/order를 만든다.
- coded↔actual 변환이 round-trip tolerance 안에서 일치한다.
- 모든 조성점의 합계와 balance가 유효해야 한다.
- hierarchy를 위반하는 모형은 후보군에 들어가지 않는다.
- 자동 선택을 반복하면 같은 모델과 selection history가 나온다.
- rank deficient 또는 잔차 자유도 부족 모형은 탈락한다.
- best available model이 MODEL_INADEQUATE이면 영역이 생성되지 않는다.

### 14.4 Region/Verification

- feasible point는 supported domain 밖에 존재하지 않는다.
- 3요인 plot은 고정한 제3요인 값을 명시한다.
- verification result는 fitting set에 들어가지 않는다.
- 같은 blend의 하위 정제는 독립 lot으로 세지 않는다.
- 확인계획이 첫 결과 제출 전에 잠기지 않으면 승격되지 않는다.
- REFERENCE_EXISTING만으로는 승격되지 않는다.
- 확인 실패 시 기존 provisional region은 INVALIDATED 또는 새 버전 대기 상태가 된다.

### 14.5 Lab-in-the-loop/Governance

- 자연어에서 추출한 값은 사용자 확인 전 분석되지 않는다.
- LLM이 마스터에 없는 확인시험을 생성할 수 없다.
- LLM directive가 DB를 직접 수정할 수 없다.
- production은 승인된 rulebook release만 사용한다.
- 관리전략 상태·API·DB 객체가 존재하지 않는다.

### 14.6 CBD 골든 테스트

- 17개 BBD 행과 Table 9 fixture가 정확히 연결된다.
- 논문 식을 입력하지 않아도 원자료에서 모델이 적합된다.
- 논문 보고식과 재적합식 차이가 비교 artifact로 남는다.
- 1400 psi / 35% MCC / 1% CCS verification lot 3개는 fitting set과 분리된다.
- 재실행 시 model, grid, plot checksum이 허용 tolerance 안에서 재현된다.

---

## 15. 구현 순서

| 단계 | 산출물 | 완료 조건 |
|---|---|---|
| 0 | v7 contracts, enums, state/reason registry | schema·전이 CI 통과 |
| 1 | DoE generator/validator + auto model selector | FCCD/BBD와 synthetic golden tests 통과 |
| 2 | CQA/FMEA/factor 3수준 wizard | 4-response/3-factor 제약과 승인 흐름 동작 |
| 3 | range evidence gate + feasibility planner | 신규 API 5/7조건 분기 동작 |
| 4 | protocol/result ingestion + quality gate | 구조화·자연어 확인 흐름 동작 |
| 5 | region engine + Axes3D/contour | domain mask·다중 CQA 교집합 재현 |
| 6 | verification + Lab-in-the-loop backtrack | 성공·실패 전이와 독립성 gate 통과 |
| 7 | CBD literature replay | 17 runs, 모델, plot, 3 lot verification end-to-end |

개발 우선순위는 UI보다 통계 core와 데이터 계약이다. 통계 엔진은 mock LLM 없이 독립적으로 CI에서 재현되어야 한다.

---

## 16. 완료 기준

다음 trace가 UI와 API에서 모두 재현되면 MVP가 완료된 것이다.

> 선택 후보 → immutable handoff → CQA 최대 4개 반응 선택 → FMEA 기반 요인 최대 3개 선택 → 3수준 근거 gate → 필요 시 feasibility → FCCD/BBD → 연구자 승인 프로토콜 → 결과 품질 gate → 자동 계층적 모델 → Axes3D/contour → provisional 영역 → 독립 확인실험 → verified operating region

모든 화면에서 다음 lineage가 추적되어야 한다.

~~~text
candidate_id@version
handoff_id
study_id@state_version
cqa_id@version
fmea_id@version
factor_id@version
feasibility_plan_id@version
doe_plan_id@version
run_id / batch_id / result_id
response_model_id@version
design_space_id@version
verification_plan_id@locked_hash
rulebook_release_id
decision_id / approval_id / override_id
~~~

---

## 17. 근거와 구현상 주의

- ICH Q8(R2), Pharmaceutical Development: QTPP, CQA, risk-based development와 Design Space 개념의 상위 근거.
- ICH Q9(R1), Quality Risk Management: 위험평가가 의사결정을 지원하되 형식적 RPN 숫자만으로 결정하지 않도록 설계.
- NIST/SEMATECH Engineering Statistics Handbook: DoE, response surface, 회귀진단 참고.
- Monton C. et al. Quality by Design–Driven Formulation Development of Cannabidiol Orally Disintegrating Tablets. Scientifica. 2026;2026:3553253. https://doi.org/10.1155/sci5/3553253
- 기존 Formula 1 v6.1 명세의 typed rule context, 독립 확인배치, supported domain, versioned artifact 원칙은 유지한다.

이 시스템의 경쟁력은 LLM이 그럴듯한 곡면을 그리는 데 있지 않다. 근거 없는 후보 수치를 중심점으로 굳히지 않고, 필요한 경우 feasibility 실험으로 전환하며, 결과가 나쁜 모델에서는 영역 생성을 멈추고, 독립 확인결과까지 하나의 추적 가능한 개발 루프로 연결하는 것이 핵심이다.
