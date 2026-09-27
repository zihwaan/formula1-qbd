# DoE v7.0 실험개발 워크플로 — 구현 설계

> 기준 문서: `formula1-experimental-development-architecture-v7.0.md`(명세), `database/07_doe/v7_0/INSTALLATION.md`(설치 가이드),
> `database/07_doe/v7_0/**`(룰북 18 · 마스터 7). 명세와 룰북 데이터가 어긋나면 **룰북 데이터를 따르고** §8에 기록한다.
> 문서 기준일 2026-09-27.

## 0. 목적과 범위

v7.0 명세의 실험개발 흐름을 **연구자가 단계마다 선택·승인하는(HITL) 저장형 study**로 구현한다.

> 후보 확인 → CQA 선택(DOE 반응 ≤ 4) → FMEA 검토 → 요인 선택(≤ 3) → 3수준·근거 입력 → (필요 시 feasibility) → 실험표 승인
> → 결과 입력·확인 → 자동 모델 → (플래그 승인) → provisional 영역 → 확인계획 잠금 → 확인 결과 → 최종 승인

**실행 모드.** 룰북 18개가 모두 `DRAFT_EXPERT_REVIEW_REQUIRED · enforcement_enabled=false`이므로 study는 **샌드박스 모드**로만 만든다.
v6.1 개발 스튜디오와 같은 방식이다 — 규칙은 평가되고 study를 라우팅하지만, 모든 판정·화면에 `DRAFT / RESEARCH USE ONLY /
NOT A GMP INSTRUCTION`을 붙이고, production 모드 생성은 `DoePackage.can_enforce`가 참인 규칙이 생길 때까지(검토·승인 release)
거부한다(INSTALLATION §12). 설정 `config/doe_module.yaml`의 `enabled`는 "production 집행"을 뜻하고 계속 `false`다.

**범위 밖(명세 §2.3):** 관리전략·PAT·PPQ·상업 스케일업 객체/API/화면은 만들지 않는다. 금지 상태로의 전이는 코드와 로더가 막는다.

## 1. 설계 원칙

| 원칙 | 구현 |
|---|---|
| 판정은 룰북 행 | gate 함수는 조건을 계산하고, `result_code · gate_effect · next_state · message_ko`는 해당 rule 행에서 읽는다. 룰북에 없는 차단을 코드로 만들지 않는다 |
| 수치는 결정론 | 설계행렬·회귀·모델 선택·영역·확인 판정은 `formula/doe/*`(numpy/scipy). LLM 없음 |
| 사람 승인 | RB00 `human_approval_required` 9개 지점은 연구자 행동 없이는 넘어가지 않는다(§3 표) |
| 상류값 ≠ 중심점 | handoff 성분값은 `value_role=REFERENCE_PROTOTYPE`. 요인 입력 폼은 기준값과 center를 다른 칸으로 받고, 기준값을 center로 복사하는 코드는 없다(RE003) |
| 근거 등급은 올릴 수 없다 | 요인 근거·결과 근거는 M05 `evidence_permission_matrix`로 용도별 허용을 판정(`evidence_permits`). 연구자가 등급을 올리는 행동은 없다 — 새 근거 record(feasibility 결과 등)로만 바뀐다 |
| 이력 보존 | v6.1 `StudyStore` 재사용: Idempotency-Key · Expected-State-Version · Actor-ID, append-only 이벤트 + 결정 원장. 과거 artifact는 덮지 않고 version을 올린다 |
| 두 그래프 분리 | ① 후보 탐색과 state를 공유하지 않는다. 불변 handoff 하나로만 잇는다(명세 §2.1) |

## 2. 구성

```
formula/doe/
├── package.py      로더·무결성
├── contracts.py    상태·전이·근거 등급·상태별 행동/승인 지점 표·룰 next_state 별칭
├── gates.py        RB01·RB03·RB06·RB07·RB08·RB09·RB12 판정 + 단위(M04)·근거 권한(M05) — RB10·RB11·RB14·RB16·RB17은 service가 같은 _decide로 판정
├── design.py       설계 생성·검증
├── models.py       자동 계층적 모델 선택·RB14
├── region.py       영역·확인 판정
├── replay.py       CBD 픽스처 재현(검증 비교 보기)
├── demo.py         CBD study 폼 채우기(논문 표 → 폼, 요인은 FMEA 키로 대응)
├── handoff.py      후보 → v7 handoff(§7.1), fingerprint, value_role
├── cqa.py          RB02 매핑 + v6.1 cqa_templates(미이관) + M01 시험법 → CQA 표
├── fmea.py         RB04 실패모드 → FMEA 초안, RB05 점수 정책(UNKNOWN·고심각도 보호·RPN)
├── protocol.py     run sheet(칭량표·balance 성분·고정값) — RB11
├── labloop.py      M06 adapter(ConfirmationTestRecord) + RB18 패턴 → 판별시험 후보
└── service.py      DoeStudyService — create/act/view/trace, 상태기계 구동
web/server.py       /api/doe-v7/studies/* (명세 §10을 행동 엔드포인트 하나로 묶음 — v6.1과 같은 형태)
web/static/doe7wizard.js  6단계 마법사(질문 카드 + 단계별 결과), Plotly 3D 곡면(strict 번들 지연 로드)
web/static/doe7.js        탭 머리 + 검증 비교 보기(CBD 재현 요약 · 범위 gate 계산기)
database/07_doe/V6_TO_V7_MIGRATION_MATRIX.csv   v6.1 파일별 이관 상태(INSTALLATION §6.2)
```

저장소: `FORMULA1_DOE7_DB`(기본 `/tmp/formula1/doe7.db`) — v6.1 study와 섞지 않는다. 파드 재시작 시 사라지는 것은 v6.1과 같다(데모 범위).

## 3. 상태 · 행동 · 사람 승인

| 상태(명세 §5) | 연구자 행동(HITL) | 결정론 검사 | 다음 상태 |
|---|---|---|---|
| HANDOFF_RECEIVED | `handoff_confirm` — 후보·기준값 확인 | RB01(RD001–RD010·HR011·HR012) | CQA_REVIEW (차단 규칙이 있으면 머묾) |
| CQA_REVIEW | `cqa_edit`(역할·기준·시험법) → `cqa_approve` **[CQA_SELECTION]** | RB03(CR001–CR010·CE011·CE012) | FMEA_REVIEW |
| FMEA_REVIEW | `fmea_edit`(S/O/D·근거·처분) → `fmea_approve` **[FMEA_REVIEW]** | RB05 정책(O UNKNOWN이면 RPN 없음, S≥4 제외 금지) | FACTOR_SELECTION |
| FACTOR_SELECTION | `factor_select`(≤3, 비선택 고위험의 고정값·사유) | RB06(FS013–FS015·FE002) | RANGE_EVIDENCE_CHECK |
| RANGE_EVIDENCE_CHECK | `range_submit`(low/center/high·단위·근거·출처) → `range_approve` **[FACTOR_AND_RANGE_SELECTION]** | RB07 → RB09(혼합·범주형·HTC) | DOE_RANGE_READY · NEEDS_FEASIBILITY · ADVANCED_DESIGN_REQUIRED |
| NEEDS_FEASIBILITY | `feasibility_plan_approve` **[FEASIBILITY_PLAN]** | RB08(FD002–FD004) | WAITING_FEASIBILITY_RESULTS |
| WAITING_FEASIBILITY_RESULTS | `feasibility_results_submit`(조건별 제조·측정 가능·치명 비호환) | RB08(FD005–FD008) | DOE_RANGE_READY · RANGE_REVISION_REQUIRED · PROTOTYPE_REVISION_REQUIRED |
| RANGE_REVISION_REQUIRED | `range_submit`(새 범위) | — | RANGE_EVIDENCE_CHECK |
| PROTOTYPE_REVISION_REQUIRED · MODEL_INADEQUATE · REGION_REVISION_REQUIRED | `revise`(사유) — RB18 판별시험 후보를 보고 재검토 시작 | RB18 | FMEA_REVIEW |
| DOE_RANGE_READY | (자동) 설계 선택·행렬 생성 | RB09 · RB10(설계 Validator) · RB11(run sheet) | DOE_PLAN_REVIEW |
| DOE_PLAN_REVIEW | `plan_approve` **[DOE_PLAN · EXECUTION_PROTOCOL]** / `plan_reject` | RB10 차단이 있으면 승인 불가 | WAITING_FOR_RESULTS / RANGE_EVIDENCE_CHECK |
| WAITING_FOR_RESULTS | `results_submit`(run별 값·batch_id·근거 등급; CSV 또는 폼) | — | RESULT_QUALITY_REVIEW |
| RESULT_QUALITY_REVIEW | `results_confirm`(추출값 확인) / `results_revise` | RB12(RQ001–RQ013), M05 MODEL_FIT 허용 | MODEL_FIT / WAITING_FOR_RESULTS |
| MODEL_FIT | (자동) 자동 계층적 모델 선택 → 플래그 있으면 `model_accept_flags` **[MODEL_ACCEPTANCE_WITH_FLAGS]** | RB14, RB16(DR001·DR005·DR011·DR018) | PROVISIONAL_DESIGN_SPACE · MODEL_INADEQUATE |
| PROVISIONAL_DESIGN_SPACE | `vplan_lock`(SETPOINT·BOUNDARY·ROBUSTNESS 점, 결과 전 잠금) **[VERIFICATION_PLAN]** | RB17(VR001·VR002·VR018) | WAITING_VERIFICATION_RESULTS |
| WAITING_VERIFICATION_RESULTS | `verification_submit`(점별 새 batch 결과) → `final_approve` **[VERIFIED_OPERATING_REGION]** | RB17(VR003–VR020), M05 VERIFICATION 허용 | VERIFIED_OPERATING_REGION · REGION_REVISION_REQUIRED |
| ADVANCED_DESIGN_REQUIRED | `design_import`(검증된 외부 행렬) | 같은 Validator | DOE_PLAN_REVIEW |

**룰북 next_state ↔ 명세 상태 매핑.** 룰북 행의 `next_state`에는 v6.1 이름(`WAITING_FACTOR_DATA`, `WAITING_CQA_APPROVAL`,
`DOE_PLAN_DRAFT`, `DESIGN_REPLAN`, `WAITING_BATCH_RESULTS`, `WAITING_RESULT_CONFIRMATION`, `DOE_AUGMENTATION_REVIEW`, `STRATEGY_REVIEW` 등)이
섞여 있다. 이들은 **"현재 단계에 머문다(차단)" 또는 명세 상태로의 별칭**으로 다룬다 — `contracts.RULE_STATE_ALIAS`에 표로 둔다.
표에 없는 next_state가 나오면 study를 옮기지 않고 결정 원장에 `UNMAPPED_NEXT_STATE`를 남긴다(조용히 무시하지 않는다).

## 4. 단계별 계약

- **D0 handoff** (`handoff.py`) — 입력: ① 후보(recipe) 또는 CBD 픽스처. 성분 `amount_mg·percent_w_w`에 `value_role=REFERENCE_PROTOTYPE`.
  fingerprint = 후보@버전·성분·공정·고정값 해시(동일 후보 버전 → 동일 fingerprint, 명세 §14.1). 설비·배치 규모·등급은 모르면 None(RD005·RD006이 요청).
- **D1 CQA** (`cqa.py`) — RB02로 제형별 템플릿을 고르고(분산정은 정제 상속) v6.1 `cqa_templates`에서 이름·단위·기본 시험법을 채운다.
  기준값(lower/upper)은 템플릿에 비어 있으면 비워 둔다 — 연구자가 출처와 함께 입력(명세 §3.2: 규격 생성 불가). `is_cqa`와 `analysis_role`은 별도 축.
  DOE_RESPONSE ≤ 4(CE011), DOE_RESPONSE는 연산자·절대 기준·시험법·단위 필수(CR001–CR005·CE012).
- **D2 FMEA** (`fmea.py`) — RB04 실패모드 중 공정경로 일치 행 → FMEA 초안. `evidence_class`는 RB04 `evidence_type`에서(LLM 행은 `LLM_HYPOTHESIS`).
  O 근거 없으면 `UNKNOWN`·RPN 미계산, S≥4 행은 대체 관리·사유 없이 제외 불가(RB05). RPN은 정렬 보조값.
- **D3 요인** — FMEA 행의 `candidate_factor`를 후보로 모아 연결 CQA와 함께 보여 주고 연구자가 ≤ 3 선택. 각 요인은 CQA 1개 이상 연결(FS014),
  선택 안 한 고위험 요인은 고정값·사유 필요(FS015).
- **D4 범위** — 요인별 low/center/high·단위·quantity_kind·근거 등급·출처(locator). 기준값은 handoff에서 읽어 **표시만**. RB07 판정.
  문헌 재현 study의 근거는 픽스처 metadata에서 자동 표시(명세 §12.3 — 사용자가 직접 입력하지 않음).
- **D5 feasibility** — 2k+1 축점 계획(연구자 승인 후 실행) → 조건별 결과 → RB08 라우팅. feasibility 결과는 fitting set에서 제외(FD009).
  통과하면 해당 요인의 근거가 `FEASIBILITY_CONFIRMED`로 **새 record**가 된다(수동 상향 아님).
- **D6 설계** — RB09 선택, `design.generate`(seed = RB15 `random_seed`), RB10 Validator. BBD는 DV010 경고(domain 정책).
- **D7 run sheet** (`protocol.py`) — run별 실제값, 요인이 조성(%w/w)이면 **balance 성분**(기본: 가장 큰 충전제, 연구자 변경 가능)으로 100% 맞춤 → 음수면 RS002 차단.
  근거 없는 설비 설정값은 만들지 않는다(PC007 REQUEST_DATA). 출력은 연구자 검토용 프로토콜 — GMP 지시서 아님.
- **D8 결과** — run별 반응값·batch_id·parent_blend_id·시험법 버전·독립성·근거 등급. CSV 붙여넣기 또는 표. 자연어 입력은 이번 범위에서 제외(명세 §4 화면 5: 보조).
  RB12 + M05(MODEL_FIT). `human_verification_status=CONFIRMED`(연구자 확인) 전에는 적합하지 않는다(RQ006).
- **D9 모델** — `models.select_model`. 선택 이력·1-SE 집합·탈락 사유 저장. VALID_WITH_FLAGS는 연구자 승인 전 영역 계산 불가.
- **D10 영역** — 공동 통과확률(잠근 const 0.90·격자 21)로 계산. 평균만 쓰는 영역 금지(DR005), 결과 뒤 기준 완화 금지(DR011), 빈 영역 → DR018.
- **D11 확인** — 결과 전에 잠금(locked_hash). 점 역할 SETPOINT·BOUNDARY·ROBUSTNESS 필수(VR001). 제안점: SETPOINT = 공동 통과확률 최대점,
  BOUNDARY = 영역 경계의 지배 CQA 쪽 점, ROBUSTNESS = setpoint 주변 소폭 동시 변동점(연구자가 수정 가능). batch_id는 적합 set·다른 점과 겹치면 안 되고(VR003·VR013),
  같은 blend 하위 정제는 독립 lot이 아니다(RQ009 · parent_blend_id). 결과 근거가 M05 VERIFICATION 불허면 승격 불가(VR015). 전부 통과 + 연구자 승인 → VERIFIED(VR020).
- **D12 lab-loop** (`labloop.py`) — 실패 상태에서 RB18 패턴으로 판별시험 후보를 M06에서 찾아 보여 준다(`allowed_for_agent`). LLM은 쓰지 않는다 —
  이 단계의 LLM 가설은 다음 작업이다. 연구자가 시험을 고르고 `revise`로 FMEA 재검토에 들어간다.

## 5. study 상태 JSON(요지)

```
study_id, study_type(NEW_API|LITERATURE_REPLAY), execution_mode(SANDBOX), status, state_version,
handoff{...명세 §7.1, value_role}, cqas{id: CQASpec@version}, fmea{version, rows[]}, factors{id: FactorSpec@version},
feasibility{plan, results, route}, plans[DoEPlan@version], active_plan, run_sheet, results{run_id: TestResult},
models{response: {selected, history, gate, status}}, flags_accepted_by, region{DesignSpaceVersion},
verification{plan(locked_hash, points), results, verdict}, labloop{pattern, tests}, evaluations{stage: [Decision]},
timeline[], approvals[], package_hash, rulebook_release
```

## 6. API

| Method | Endpoint | 책임 |
|---|---|---|
| POST | `/api/doe-v7/studies` | `{source: candidate|cbd_replay, run_id?, candidate_id?}` → handoff 잠금 + study 생성 |
| GET | `/api/doe-v7/studies` · `/{id}` · `/{id}/trace` | 목록 · 상태+지금 묻는 것(prompt) · lineage·이벤트·결정 |
| POST | `/api/doe-v7/studies/{id}/actions/{action}` | §3의 행동 — 헤더 Idempotency-Key·Expected-State-Version·Actor-ID |
| GET | `/api/doe-v7/studies/{id}/surface?response=&x3=` | 반응 곡면·공동 통과확률 격자(3D·contour 공용) |

기존 읽기 전용 `/api/doe-v7/package · cbd-replay · range-check`는 유지(검증 모드 비교 화면).

## 7. 화면

- v7 탭 = 마법사. 위: study 선택/생성(① 후보에서 · CBD 문헌 재현 데모), 6단계 진행바(명세 §4 화면 1–6).
- 가운데 **질문 카드**: 현재 상태에서 연구자가 해야 할 일과 폼·버튼(v6.1 studio와 같은 상호작용). 판정은 rule ID·결과 코드·DRAFT 배지와 함께.
- 데모의 "입력 채우기"는 **폼만 채운다** — 제출 버튼은 연구자가 누른다. CBD 데모의 값은 전부 논문 표(픽스처)에서 온다.
- 결과 영역: 반응별 탭(선택 식 coded·actual, 지표, 선택 이력) + Plotly 3D 곡면(규격 경계면, 실험점) + 2D contour + 다중 CQA 중첩, 3요인은 X3 고정 값을 명시.
  Plotly는 v7 탭에서 곡면을 처음 열 때만 jsdelivr에서 불러오고, 실패하면 2D 단면만 보여 준다.
- ①의 통과 후보 카드에 "v7 실험개발로 시작" 버튼(v6.1 "개발 착수"와 나란히).

## 8. 명세 ↔ 룰북 데이터 불일치와 결정

| # | 불일치 | 결정 |
|---|---|---|
| 1 | 명세 §12.4-8: CBD replay는 확인 통과 시 VERIFIED로 표시 / M05: `LITERATURE_DIRECT` → VERIFICATION `DENY`, RB17 VR001: SETPOINT·BOUNDARY·ROBUSTNESS 모두 필요 | **룰북을 따른다** — 문헌 lot은 확인 판정을 보여 주되 VR015·VR001로 승격 불가. 약학·통계 검토 질문으로 남김 |
| 2 | 명세 §12.4: `PUBLISHED_REPORT_INCONSISTENCY` / M07에 없음 | 감사 기록(코드 아님). 카탈로그 보강 요청 |
| 3 | RB02가 참조하는 CQA 템플릿 본문이 v7에 없음(v6.1 `masters/cqa_templates.csv`) | v6.1 파일을 읽고 이관 대조표에 `NOT_MIGRATED · runtime_reference=yes` |
| 4 | RB14·RB16 `const.*`가 v6.1 `planning/statistical_policy_constants.csv`에만 있음 | 같음 |
| 5 | 룰북 next_state에 v6.1 상태 이름이 섞임 | §3 별칭 표 — 매핑 없는 값은 옮기지 않고 기록 |
| 6 | M02 설비 운전범위가 전부 `UNKNOWN` | 설비 검사(RS003·FE005)는 REQUEST_DATA로 "미검사" 표시, 통과로 읽지 않음 |
| 7 | CBD 요인 압축력은 psi(압력, M04 pressure) / M02 압축력은 kN(힘, M04 force) | 물리량이 달라 변환하지 않는다(M04 guard: 같은 quantity_kind 안에서만). 설비 대조는 미검사로 표시 |
| 8 | M05의 VERIFICATION 열이 **모든 등급에서 DENY** — 잠근 확인계획 아래 새로 만든 batch용 등급이 없어, 데이터 그대로면 어떤 study도 확인을 통과할 수 없다 | 확인 결과 전용 등급 `VERIFICATION_BATCH`(M05 밖)를 두고, RB17 독립성 조건(결과 전 잠금 VR002 · 적합 set과 batch 불중복 VR003·VR019 · 점 간 batch 불중복 VR013 · 같은 blend 아님 RQ009)을 **모두** 만족할 때만 VERIFICATION 허용으로 해석한다. 문헌·합성·제안 등급은 M05대로 거부. 약학·통계 검토 질문으로 남김 |
| 9 | M05에 study 안에서 새로 만든 DoE run 결과용 등급이 없다 | `MEASURED_IN_STUDY`를 두고 M05의 `MEASURED_PRIOR_BATCH` 행(MODEL_FIT = ALLOW_IF_PLAN)과 같은 권한으로 본다 — 잠긴 DoE 계획이 있을 때만 적합 허용 |
| 10 | M02 압축력은 kN / M04 `force`에는 N·kgf만 등록 | M04에 없는 단위는 변환하지 않는다(M04 guard "unknown unit → REQUEST_DATA, no fuzzy conversion") — kN으로 입력하면 RE009. N으로 입력하거나 M04에 kN 행 추가를 요청 |

## 9. 테스트 계획

- 서비스(pytest): CBD study 전 과정 walk(데모 입력 = 픽스처) → REGION_EMPTY에서 멈춤 · 확인 승격 불가(VR015) 경로도 별도 확인 /
  신규 API walk → NEEDS_FEASIBILITY → 경계 실패 → 범위 수정 → 통과 → BBD 계획 승인 → WAITING_FOR_RESULTS /
  HITL: 승인 없이 다음 단계 불가, 행동-상태 불일치 409 / DOE_RESPONSE 5개 거부 · 요인 4개 거부 · 기준값 center 자동 복사 없음 /
  idempotency 재요청 무변경 · 버전 충돌 / 확인계획 잠금 전 결과 거부 · 같은 blend batch 거부 / 금지 상태 없음 / trace lineage.
- 브라우저: 마법사를 클릭으로 CBD 끝까지(데스크톱·휴대폰, 넘침 0, 오류 0), 신규 API feasibility 분기, 기존 verify·studio·doe7 스위트 회귀.

## 10. 배포 · 롤백

formula1 이미지 재빌드 + rollout(o11y 점검 창). 롤백은 파일 삭제가 아니라 v7 탭 숨김(설정) — 저장소는 `/tmp`라 파드 재시작 시 비워진다.
