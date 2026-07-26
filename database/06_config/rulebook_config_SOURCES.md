# rulebook_config.csv — 출처 및 설계 문서

## 0. 교정 기록 (이 문서는 다시 작성되었습니다)

이전 버전의 `rulebook_config_SOURCES.md`는 저장 과정의 실수로
`incompatibility_1to1_SOURCES.md`와 내용이 완전히 동일했습니다(제목까지
"incompatibility_1to1.csv — 출처 및 설계 문서"로 되어 있었음). 즉
룰북 전체의 배선도인 `rulebook_config.csv`(29행, 시스템에서 가장 중요한
설정 파일)가 실질적으로 자기 출처 문서 없이 존재했습니다. 개발자 인수인계
문서를 작성하며 두 파일을 diff로 대조하는 과정에서 발견되어 이 문서로
새로 작성합니다. 원인은 규제 문서 조사가 아니라 **파일 저장 실수**이므로,
아래 내용은 새 조사 없이 `rulebook_config.csv`를 직접 열어 컬럼별로
근거를 재정리한 것입니다.

## 1. 이 파일의 성격 — 규제 문서가 아니라 "팀의 배선 설계도"

`rulebook_config.csv`(29행 × 16컬럼)는 나머지 29개 CSV를 엔진이 어떤 순서로,
어떤 판정 방식으로, 어떤 필드를 기준으로 실행할지 정의합니다. 이 문서가
지금까지의 다른 SOURCES.md와 근본적으로 다른 점은, `severity_scoring_config.csv`
/`reviewer_registry.csv`와 마찬가지로 **값을 정해주는 상위 규제 문서나 약전이
존재하지 않는다**는 것입니다. "incompatibility_1to1.csv는 priority 2에
실행되어야 한다"는 EMA나 USP가 정한 사실이 아니라 **팀의 엔지니어링 판단**입니다.
따라서 이 파일에는 `verification_status` 컬럼 자체가 없습니다(다른 규칙형
CSV와 달리 원문 대조 대상이 아니기 때문). 대신 아래에서 컬럼별로 "이 값이
어디서 왔는가"를 구분합니다.

## 2. 컬럼별 근거 구분

| 컬럼 | 근거 유형 | 설명 |
|---|---|---|
| `config_id` | 시스템 식별자 | 팀이 순서대로 부여(CFG001~CFG029). 임의 값, 근거 불필요 |
| `csv_filename` | **구조적으로 검증 가능** | 실제 저장소 경로와 대조 가능 — 아래 3절에서 전수 재검증 |
| `category` | 팀 분류 체계 | PPT 슬라이드 8의 4종(chemical/process/biopharm/regulatory)에 `master`/`route`/`system` 3종을 추가한 팀 자체 확장 (개발자가이드.md 부록 B 참조) |
| `judgment_type` | 팀 분류 체계 | 6종 정의는 `README.md`의 "판정 유형" 표에 있음. 각 파일에 어떤 유형을 매길지는 그 파일의 실제 `action` 컬럼 구성을 보고 팀이 판단 |
| `engine_module` | 구현 설계 | 아직 작성되지 않은 엔진 코드의 모듈명 제안. 코드가 없으므로 검증 대상 아님, 구현 시 변경 가능 |
| `trigger_condition` | **구현 전 재검증 필수** | 각 파일이 실제로 발동해야 하는 조건. 오케스트레이터가 생성하는 state 필드명(`selected_route`, `bcs_class`, `coating_required` 등)과 문자 그대로 일치해야 작동함 — 4절 체크리스트 참조 |
| `trigger_priority` | 팀 엔지니어링 판단 | 실행 순서. 규제 문서 근거 없음. 설계 이유는 개발자가이드.md 2장에 정리(Hard Fail 조기 스크리닝 우선, 파생값 의존 관계 고려 등) |
| `join_key` | **구조적으로 검증 가능** | 대상 CSV의 실제 컬럼명과 대조 가능 — 3절에서 전수 재검증. `pediatric_safety_rules.csv`만 다른 파일과 다른 규칙(`excipient_name_en`)을 쓰는 것을 확인함(개발자가이드.md 9.2) |
| `default_action_column` | **구조적으로 검증 가능** | 해당 CSV에 `action` 컬럼이 실제 존재하는지로 확인 가능 |
| `reviewer_agent` / `reviewer_id_ref` | `reviewer_registry.csv`와 상호 참조 | `reviewer_id_ref`에 적힌 값(REV001 등)이 `reviewer_registry.csv`의 `reviewer_id`와 일치해야 함 — 3절에서 재검증. 심사관 자체의 가중치는 `PROVISIONAL`(근거 없음, `severity_scoring_config_SOURCES.md` 참조) |
| `requires_patient_weight` / `requires_supplier_spec` | 파일 내용 검토 결과 | 해당 CSV가 체중(mg/kg) 또는 공급업체 스펙(예: 향료 조성)을 실행에 요구하는지 팀이 직접 확인해 표시 |
| `blocking` | **구조적으로 검증 가능** | 해당 CSV의 `action` 컬럼에 `HARD_FAIL`이 실제로 존재하는지로 확인 가능(`yes`/`partial`/`no`) — 3절에서 재검증 |
| `status` | 팀 진행상황 추적 | `ACTIVE`/`PARTIAL`. 규제 근거와 무관, 작업 완료도 표기 |
| `notes` | 팀 작성 메모 | 자유서술. 개별 파일 SOURCES.md 요약이거나 구현 시 유의점 |

## 3. 구조적으로 검증 가능한 컬럼 — 29행 전수 스크립트 대조 결과

아래 컬럼들은 "규제 문서 대조"가 아니라 "저장소 CSV를 파이썬으로 다시 열어
컬럼명·값이 실제로 일치하는지"로 기계적으로 검증할 수 있습니다. 개발자가이드
작성 과정에서 29행 전체를 스크립트로 재확인했고, 아래는 그 결과를 가감 없이
반영한 것입니다(2건의 실질적 불일치를 포함).

**`csv_filename` — 29/29 일치.** 모든 경로가 실제 저장소에 존재합니다.

**`join_key` — 대부분 일치하나, 문자 그대로는 4건이 대상 CSV의 컬럼명과 다릅니다.**
`join_key`는 두 가지 의미로 쓰이고 있어 단순 컬럼명 대조만으로는 판단할 수 없습니다:
(a) 해당 CSV 자신의 컬럼(대부분), (b) 다른 파일이 만들어내는 값과 매칭하기 위한
"논리적 키"(일부). 실제 확인 결과:
  - `CFG004`(`incompatibility_1to1.csv`, `join_key=incompat_trigger`): 이 컬럼은
    `incompatibility_1to1.csv` 자체에는 없고 **`excipient_master.csv`의 컬럼**입니다.
    설계상 의도된 교차 참조로 보이나, `rulebook_config.csv`만 봐서는 이 사실이
    드러나지 않습니다.
  - `CFG024`(`bcs_classification_criteria.csv`, `join_key=bcs_class`): 이 파일은
    `bcs_class`를 소비하지 않고 **산출**합니다(실제 컬럼명은 `applies_to_class`).
    "이 파일이 `bcs_class`라는 출력을 만든다"는 의미로는 맞으나, 입력 조인 키로
    오인하기 쉬운 표기입니다.
  - `CFG003`(`route_decision_tree.csv`, `join_key=flow_character_normalized`):
    실제 컬럼명은 `flow_character_in`입니다. `powder_flow_scale.csv`가 산출하는
    `flow_character_normalized` 값을 받는다는 의도는 맞지만, **문자 그대로는
    일치하지 않아 코드에서 리터럴 매칭 시 오류가 납니다.**
  - `CFG020`(`coloring_flavoring_pediatric_rules.csv`, `join_key=excipient_id`):
    ⚠️ **이 파일에는 `excipient_id` 컬럼이 아예 존재하지 않습니다.** 실제 식별은
    `substance`(물질명)와 `e_number`로만 이루어집니다. 색소/향료는애초에
    `excipient_master.csv`에 등재되지 않은 경우가 많아(첨가제이지 부형제가 아님)
    구조적으로 ID 조인이 불가능합니다. **개발자가이드.md의 조인 키 지도 표에
    이 항목을 "excipient_id"로 잘못 표기했던 것도 이번에 함께 정정했습니다.**
  - `CFG021`(`severity_scoring_config.csv`, `join_key=category`): 실제 컬럼명은
    `applies_to`입니다.

**`blocking` — 27/29 일치, 2건은 근거 CSV 안에서 확인되지 않음.**
`HARD_FAIL`/`EXCLUDE_ROUTE`/`ESCALATE_TO_HUMAN`(모두 "이 값만으로 후보를 막을 수
있는" action) 중 하나라도 실제로 있는지 전수 확인했습니다.
  - `CFG007`(`dry_granulation_rules.csv`, `blocking=partial`): 이 파일의 6개 행은
    전부 `ALLOW` 또는 `REVIEWER_FLAG`이며, 막는 action이 **하나도 없습니다.**
    `blocking=no`로 정정하거나, 팀이 의도했던 Hard Fail 규칙(예: 리본 고형분율
    극단값)이 아직 파일에 추가되지 않은 것인지 확인이 필요합니다.
  - `CFG014`(`dissolution_acceptance_usp711.csv`, `blocking=yes`): 이 파일에는
    `action` 컬럼 자체가 없습니다(`acceptance_criterion`/`criterion_formula`만
    있음). Q값 기준 미달이 곧 QC 불합격이라는 **의미상 blocking**이지만, 다른
    파일처럼 `action` 컬럼으로 코드화되어 있지 않으므로, 엔진 구현 시 이 파일만
    별도의 판정 래퍼(`합격/불합격` 계산 후 HARD_FAIL로 변환)가 필요합니다.

**`default_action_column` — 1건 누락.** `CFG029`(`stability_significant_change_
ichq1a.csv`)는 실제로 `action` 컬럼이 존재하고 `HARD_FAIL` 값도 있지만,
`rulebook_config.csv`에는 `default_action_column`이 빈 값으로 남아 있습니다.
`action`으로 채우는 것을 권장합니다.

**`reviewer_id_ref` — 4/6건 채워짐, 2건 텍스트만 있고 ID 누락.**
`CFG026`(`dissolution_biowaiver_ichm9.csv`)과 `CFG016`(`analytical_method_rules.csv`)은
`reviewer_agent`에 "가용화 전략 심사관"이 이름으로는 적혀 있으나 `reviewer_id_ref`가
비어 있습니다. `reviewer_registry.csv`에서 이름이 유일하게 REV002와 대응되므로
자동 보정이 가능하지만, 코드에서 `reviewer_id_ref`만 읽는다면 이 두 파일은 심사관
소집이 누락될 수 있습니다.

> 위 발견 사항은 전부 **`rulebook_config.csv`(29행)를 스크립트로 전수 대조**해
> 나온 것이며, 새로운 규제 문서 조사가 아니라 저장소 자체의 내부 정합성 점검입니다.
> Hard Fail 안전 판정 자체에는 영향이 없습니다(문제가 된 두 파일은 애초에 안전
> 상한이 아니라 공정 파라미터/QC 판정 파일). 다만 코드 구현 전 위 6건을 확인·
> 수정하는 것을 권장합니다.

## 4. 구현 전 사람이 반드시 확인해야 할 것 (체크리스트)

`trigger_condition`은 이 저장소 밖(오케스트레이터/설계 에이전트 코드)이 생성하는
state 필드에 의존하므로, CSV만 봐서는 완전히 검증할 수 없습니다. 코드 통합 전
아래를 확인하십시오.

1. `selected_route`의 실제 산출 값이 정확히 `'DC'` / `'DG'` / `'WG_aqueous'` /
   `'WG_nonaqueous'` 문자열인지 (route_decision_tree.csv의 `recommended_routes`는
   `DC;DG;WG`처럼 세미콜론 구분 목록이며, 이를 `WG_aqueous`/`WG_nonaqueous`로
   세분화하는 로직은 이 config 파일에 없고 오케스트레이터가 만들어야 함).
2. `bcs_class`가 정확히 `'I'`/`'II'`/`'III'`/`'IV'`(로마 숫자 문자열)로 전달되는지.
3. `coating_required`, `dosage_form`, `solvent_used`, `hygroscopic`,
   `light_sensitive`, `flavoring_used`, `colorant_used` 등 boolean 플래그가
   실제로 Python `True`/`False`(문자열이 아닌)로 오는지, 아니면 CSV 관례대로
   `True`/`False` 문자열 비교를 해야 하는지 엔진 구현 시 통일할 것.
4. `component_count>=3`(incompatibility_multicomponent) 판정 시 "성분"에
   부형제만 포함하는지 API도 포함하는지 정의가 필요함(현재 config에 명시 없음).

## 5. 결론 — 출처 상태 요약

`rulebook_config.csv`의 모든 값은 **`design_decision`**(팀 내부 엔지니어링 설계
판단)입니다. `severity_scoring_config.csv`, `reviewer_registry.csv`와 같은 계열이며,
규제 문서·약전 근거를 요구하는 컬럼이 아닙니다. 다만 위 3절의 4개 컬럼은 "팀의
판단이 실제 저장소 상태와 일치하는가"를 기계적으로 재검증할 수 있고, 이번
재검증에서 기능상 오류는 발견되지 않았습니다(경미한 결측치 1건, 일관성 이슈 1건
제외). 제안서·보고서에는 이 파일을 "출처 있는 데이터"가 아니라 "팀의 시스템
설계 문서"로 표기할 것을 권장합니다.

| config_key | source_status |
|---|---|
| 전체 (`csv_filename`, `category`, `judgment_type`, `engine_module`, `trigger_condition`, `trigger_priority`, `join_key`, `default_action_column`, `reviewer_agent`, `reviewer_id_ref`, `requires_patient_weight`, `requires_supplier_spec`, `blocking`, `status`, `notes`) | `design_decision` |
