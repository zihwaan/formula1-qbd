# Formula 1 DoE Agent — 개발 인계 문서 (v6.1)

작성일: 2026-09-23 · 대상: AI 개발 엔지니어  
기준 명세: `spec/formula1-doe-agent-architecture-v6.1.md` (이 문서와 충돌하면 명세가 우선)  
대상 저장소: `https://github.com/zihwaan/formula1-qbd`

---

## 1. 무엇을 만드는가

연구자가 선택한 후보처방 하나(`candidate_id@version`)를 받아 CQA → FMEA → 요인·수준 → DoE 설계 → 결과 입력 → 모델 → 불확실성 포함 design space → 독립 확인배치까지 진행하고, **VERIFIED 최종 영역 + 성립 조건(scope)** 을 내놓는 `ExperimentalDevelopmentGraph`다.

핵심 원칙 세 가지:

1. **숫자는 코드가, 설명은 LLM이.** 설계행렬, 회귀, 진단, 영역, 판정, 상태 승격은 결정론 코드. LLM은 FMEA 가설과 설명만.
2. **모든 판정은 룰북(CSV)이 결정.** 코드에 판정 로직을 하드코딩하지 않는다. 코드는 context를 만들고 룰을 평가한다.
3. **연구자가 승인한다.** 모든 `WAITING_*_APPROVAL` 상태에서 멈추고 재개한다. override는 허용 범위 안에서만, 전부 기록.

---

## 2. 패키지 구성

```
HANDOFF.md                         ← 이 문서
requirements-doe.txt               ← 추가 의존성
backlog/implementation_backlog.csv ← 작업 티켓 (스프린트·수락기준·의존관계)
spec/formula1-doe-agent-architecture-v6.1.md
database/07_doe/                   ← 룰북 23종 + 마스터 7종 (규칙 171개), README.md
tests/fixtures/lornoxicam_table3.csv
tests/fixtures/rule_fixtures.json  ← 규칙 실패 재현 48건
tests/golden/compute_lornoxicam_golden.py  ← 통계 엔진 기대값의 참조 구현
scripts/validate_07_doe.py         ← 룰북 정적 검사 + 참조 평가기 + fixture 실행
scripts/generators/                ← 룰북 CSV 생성 스크립트 (CSV 직접 편집 대신 여기서 수정)
```

설치 후 바로 확인:

```bash
pip install -r requirements-doe.txt
python scripts/validate_07_doe.py database/07_doe tests/fixtures/rule_fixtures.json
# files=29 rules=171 fixtures_pass=48 fixtures_fail=0 errors=0
python tests/golden/compute_lornoxicam_golden.py
# joint_P090_fraction_in_domain: 0.476, setpoint_P: 0.991 ...
```

---

## 3. 읽는 순서

| 순서 | 문서 | 분량 | 목적 |
|---|---|---|---|
| 1 | 명세 §0–§2 | 짧음 | 경계와 권한 |
| 2 | 명세 §5 | 중간 | 상태기계, 실행 서브사이클, 전이표 |
| 3 | 명세 §6 D0–D11 | 김 | 단계별 계약 (구현의 본체) |
| 4 | 명세 §7.3 + `database/07_doe/README.md` | 중간 | 조건식 DSL, 집행 모드, 백엔드 capability |
| 5 | 명세 §10 | 중간 | 데이터 계약 (Pydantic) |
| 6 | 명세 §14–§15 | 중간 | 불변조건, 인수 테스트, 골든 값 |
| 7 | 명세 §19 | 짧음 | 데모 시나리오 |

"v5 → v6", "v6 → v6.1" 변경 요약표는 배경 설명이다. 구현은 본문 기준으로 한다.

---

## 4. 확정된 결정 (다시 논의하지 않음)

| 결정 | 근거 |
|---|---|
| MVP 종료점 = VERIFIED 최종 영역 + scope. Control strategy, NOR 승인, 실행 프로토콜 확정, 스케일업은 범위 밖 | §1.2, §6 D11 |
| 직접타정 속방·분산 정제만. Screening ≤ 4요인, RSM ≤ 3요인 | §1.2 |
| 설계 백엔드: 부분요인, PB, BBD(연속 3요인), CCD·FCCD(연속 2–3요인). DSD·D-optimal·mixture·split-plot은 실행 차단 | §7.3 |
| 조건식은 AST 화이트리스트 평가기. Python `eval` 금지 | §7.3 |
| production 모드는 APPROVED 규칙만 집행, demo 모드는 sandbox | §7.3 |
| Supported domain = 설계점 convex hull, 영역 분모 = domain 내 격자점 | §6 D9 |
| 공동확률 기준 0.90, 반응 간 독립 가정(MVP 근사) | §6 D9, #12 |
| 확인 예측구간 = family(필수점 × DOE_RESPONSE) Bonferroni, family α 0.05 | §6 D10 |
| 필수 확인점 = SETPOINT, BOUNDARY, ROBUSTNESS 각 1배치 (데모 최소 정책) | §6 D10 |
| 모델 항 축소는 연구자 승인으로만. 자동 stepwise 금지 | §6 D8 |
| 룰북 30종은 신규 작성분 사용 (기존 저장소 룰북·마스터로 대체하지 않음) | 팀 결정 |
| 통계 엔진은 학습 데이터 불필요. 코드 + 룰북 #12 상수 | — |
| 실험 결과는 적재하지 않고 결과 제출 API로 입력 | §9.3 |

---

## 5. 기존 저장소와의 관계 (2026-09-23 main 확인)

| 항목 | 현재 상태 | 지시 |
|---|---|---|
| `formula/checkers/registry.py` `RulebookRegistry` | 존재 | 로더 구조는 참고 가능. 07_doe는 새 manifest 형식(YAML, context_schema 포함)을 읽도록 확장 또는 별도 로더 |
| `formula/checkers/applies_when.py` | **Python `eval`(제한 globals) 사용** | 07_doe에는 쓰지 말 것. `scripts/validate_07_doe.py`의 `ev()`가 참조 구현이며 이를 production 평가기로 승격 |
| `formula/lifecycle/` (WorkflowStatus에 DIAGNOSING, REFLECTING 등) | 존재 | **새 `development/`를 만들지 이것을 확장할지 결정 필요** (§11 미결 1). 결정 전까지 contracts·통계 엔진부터 착수 |
| `formula/protocol/templates/direct_compression.yaml` | 존재 | run sheet 컴파일(§3.7) 시 참고 |
| `requirements.txt` | statsmodels, scipy, pyDOE3, plotly 없음 | `requirements-doe.txt` 추가 |
| `formula1_statistical_rulebook_v0.1.xlsx` | main에 없음 | 사용하지 않음 |

---

## 6. 구현 순서와 완료 기준

상세 티켓은 `backlog/implementation_backlog.csv`. 요약:

| Sprint | 내용 | 완료 기준 |
|---|---|---|
| 0 | 데이터 계약(Pydantic, §10), 룰 평가기(AST), 룰북 로더 | 검증기 errors=0, fixture 48건을 **production 평가기로** 통과 |
| 1 | **통계 엔진**: 설계 생성·검증, 적합·진단·축소, 공동확률 영역(convex hull), setpoint, 확인점 제안, family PI, 2×2 gate | §15 골든 표 전 항목이 허용오차 안. `compute_lornoxicam_golden.py`와 동일 결과 |
| 2 | artifact → RuleContext 매핑 서비스, 룰 집행(모드, 우선순위, 전이표 라우팅) | 모든 규칙의 `required_inputs`가 매핑됨. 전이표 밖 전이 발생 시 `UNKNOWN` → human triage |
| 3 | 상태기계(§5.1·§5.2), 이벤트 저장, 승인·override 기록, 재개 | 모든 `WAITING_*_APPROVAL`에 승인·반려 전이. idempotency, optimistic lock |
| 4 | CQA mapper, FMEA engine + FMEA 가설 에이전트, RangeProposer | §15 CQA·FMEA·Factor 인수 테스트 |
| 5 | 설명 에이전트, 영역 단면 시각화, trace 화면 | §18 trace가 UI에서 재현 |
| 6 | screening 분석·증강, 진단·reflection 에이전트, run sheet, 설계 import | ⚪ 항목 |

**Sprint 1이 데모의 핵심 장면을 모두 만든다.** 시간이 부족하면 Sprint 3의 상태기계를 단순 순차 흐름으로 대체해도 되지만, 승인 지점과 override 기록은 유지한다.

---

## 7. 구현 시 반드시 지킬 기술 계약

### 7.1 룰 평가

- 입력은 manifest `context_schema`에 정의된 루트·필드만. 서비스가 artifact → context 매핑을 만들고 **매핑에 버전을 붙인다.**
- 빈 컬렉션: `any`→False, `all`→True, `nonempty_all`→False.
- `None`과의 크기 비교·산술 → 규칙 미발화가 아니라 해당 규칙의 `missing_value_action` 적용 (`RECORD_NOT_CHECKED`, `REQUEST_DATA`, `INCONCLUSIVE` 등).
- 여러 규칙이 동시에 발화하면 모든 verdict를 보존하고, 상태 전이는 가장 강한 effect 하나로 한다 (`INVALIDATE/BLOCK_STAGE > REQUEST_DATA > EXCLUDE_POINT/AUGMENT > ROUTE > WARNING > PASS`). 같은 강도면 `priority` 숫자가 작은 쪽 (명세에 없던 tie-break로, 이 인계에서 정함).
- 집행 조건 = `enforcement_enabled` AND 규칙 `validation_status` ≥ 모드 최소값. 현재 전 규칙이 DRAFT이므로 **production에서는 아무것도 집행되지 않는 것이 정상**이다.

### 7.2 통계 엔진

- 모든 계산에 도구 버전, seed, formula, 입력 데이터 hash를 저장한다.
- 예측분포: 반응별 t 분포 (평균 SE² + 잔차 분산), 자유도 = 잔차 자유도.
- 공동확률 = 반응별 통과확률의 곱. marginal 확률도 함께 저장한다.
- domain membership: BBD coded 기준 `|xᵢ| ≤ 1` 이고 `Σ|xᵢ| ≤ 2`. 다른 설계는 설계점 convex hull로 일반화한다.
- 확인 PI 개별 수준 = `1 − family_alpha / (필수점 수 × DOE_RESPONSE 수)`.
- 규격 판정은 `acceptance_operator` 기준으로 한다(LE, GE, BETWEEN, TARGET_TOL, PASS_FAIL). 확인점에서 규격은 MONITOR_ONLY를 포함한 모든 적용 CQA, PI는 DOE_RESPONSE만 판정한다.

### 7.3 LLM 에이전트

- 출력은 구조화 JSON. 수치 필드는 스키마에서 금지하거나 `evidence_status = LLM_HYPOTHESIS`로 강제한다.
- 근거 등급을 바꾸는 쓰기 권한을 주지 않는다 (AA005).
- 모델: Formula 1 기존 설정을 따른다.

---

## 8. 테스트와 수락 기준

| 층위 | 도구 | 기준 |
|---|---|---|
| 룰북 정적 | `scripts/validate_07_doe.py` | errors=0. CI에서 PR마다 실행 |
| 룰 실행 | `rule_fixtures.json` 48건 | production 평가기로 전부 통과. 새 규칙에는 발화/미발화/결측 fixture 3건 추가 |
| 통계 엔진 | 명세 §15 골든 표 | 전 항목 허용오차 안 |
| 회귀 정확도 | NIST StRD (Longley, Norris 등) | 인증 계수와 상대오차 < 1e-7 |
| 설계 생성 | 교과서 설계표 | 2⁴⁻¹ Res IV alias 구조, BBD 15 run, CCD α 일치 |
| 상태기계 | pytest | 모든 전이표 행, 모든 승인 상태의 반려, 전역 예외 복귀 |
| 서비스 | pytest | 동일 idempotency key 1회 적용, 동시 승인 2건 중 1건만 성공 (fixture로 다루지 않은 항목) |

골든 값 요약 (상세는 명세 §15):

| 항목 | 기대값 |
|---|---|
| 마손도 전체 이차 예측 R² | 0.251 → MODEL_FLAGGED |
| 마손도 선형 축소 예측 R² | 0.824 |
| DE30 R² / 예측 R² | 0.970 / 0.765 |
| 평균 기준 통과 (domain 분모 7,501점) | 0.772 |
| 공동확률 ≥ 0.90 | 0.476 |
| 권장 setpoint | MCC/Mannitol 2.7, 12.5분, crospovidone 6.8%, P = 0.991 |
| setpoint DE30 (family PI 99.58%) | 82.3 (71.9–92.8) |

---

## 9. 데모 요구사항 (본선)

명세 §19의 9개 장면을 UI에서 순서대로 재현한다. 데이터는 `tests/fixtures/lornoxicam_table3.csv`를 **결과 제출 API로 업로드**한다 (사전 적재 아님).

연구자 입력 가정 (데모 스크립트에 고정):

| 항목 | 값 |
|---|---|
| DE30 규격 | GE 75% (PROJECT_TARGET, 가정임을 UI에 표시) |
| 분산시간·마손도·AV | LE 180 s / LE 1.0% / LE 15 |
| 압축력 | UNKNOWN → scope 제한으로 표시 |
| 마손도 모델 | 연구자가 선형 축소 승인 |
| 논문 최적처방 배치 | REFERENCE_EXISTING (승격·무효화 근거 아님) |
| 실행 모드 | demo (sandbox) |

---

## 10. 데이터 상태와 주의사항

| 항목 | 상태 | 개발 영향 |
|---|---|---|
| 모든 룰·마스터 행 | DRAFT_PENDING_REVIEW | production 집행 없음. 데모는 demo 모드로 |
| 부형제 범위, 약전 수치, 서지 | 원문 대조 전 (TO_VERIFY) | 값이 바뀔 수 있으므로 하드코딩 금지 |
| 시험법 반복정밀도 | 전부 비어 있음 | `HIGH_PURE_ERROR`(SA008)과 범위 폭 검사(FR008)는 NOT_CHECKED로 동작해야 정상 |
| 설비 능력 | UNKNOWN | RS003 등은 REQUEST_DATA로 동작 |
| FDA IID | 번들 안 됨 | FR004는 `iid_reference_exists → False` |
| 예측구간 폭 | 잔차 자유도 5에서 DE30 약 ±10%p | 버그가 아님. UI에 한계로 표시 |

---

## 11. 미결 사항 (착수 전 확인)

1. `formula/lifecycle/` 확장 vs `development/` 신설 → 팀 리드 결정
2. 운영 DB: 데모는 SQLite, 운영은 PostgreSQL + object storage (명세 §12.1). 스키마는 §10 계약 기준으로 설계
3. 룰북 수정 흐름: `scripts/generators/` 수정 → 재생성 → 검증기 통과 → PR. 과학 수치 행의 `validation_status` 상향은 약학 담당 검토 후

## 12. 이번 범위에 넣지 않는 것

만들지 말 것 (요청이 와도 v6.1 범위 밖):

- Control strategy, PAT, NOR 승인, 스케일업
- mixture, split-plot, D-optimal, DSD 설계 생성
- 다변량 예측분포 기반 공동확률, 가중회귀
- 응답 변환(sqrt 등) 계약, 논문 회귀식 import, 문헌 표기 감사, 탐색용(EXPLORATORY) 산출물 유형
- 검토 보고서의 B3·B4·B7·B8, D2–D7, E 항목 (`database/07_doe/README.md` 하단 목록)

팀 노트북(TCB, Mirtazapine)이 수행하는 변환 검출이나 논문 식 기반 곡면은 위 범위 밖 항목에 해당한다. 시스템에 들어오면 CR004·CR006·DR005에 의해 차단되는 것이 v6.1의 의도된 동작이다.
