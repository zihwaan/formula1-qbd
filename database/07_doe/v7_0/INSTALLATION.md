# Formula 1 DoE Rulebooks v7.0 설치·이관 가이드

> 대상 저장소: `https://github.com/zihwaan/formula1-qbd/`  
> 대상 패키지: `formula1_07_doe_rulebooks_v7.0.zip`  
> 문서 대상: AI/백엔드 개발자, 제형 연구자, 통계 검토자  
> 문서 기준일: 2026-09-27 (KST)

---

## 1. 결론부터

압축을 푼 v7.0 패키지는 저장소의 다음 위치에 설치한다.

```text
database/07_doe/v7_0/
```

기존 `database/07_doe/` 아래에 있던 v6.1 폴더는 첫 설치 PR에서 삭제하거나 이동하지 않는다.

```text
database/07_doe/
├── analysis/             # 기존 v6.1 — 유지
├── execution/            # 기존 v6.1 — 유지
├── governance/           # 기존 v6.1 — 유지
├── masters/              # 기존 v6.1 — 유지
├── planning/             # 기존 v6.1 — 유지
├── qbd_risk/             # 기존 v6.1 — 유지
├── readiness/            # 기존 v6.1 — 유지
├── verification/         # 기존 v6.1 — 유지
└── v7_0/                 # 신규 설치
    ├── config/
    ├── rulebooks/
    ├── masters/
    ├── sources/
    ├── docs/
    ├── scripts/
    ├── reports/
    ├── catalog/
    ├── manifest.yaml
    ├── README.md
    ├── INSTALLATION.md
    └── SHA256SUMS
```

v7.0은 기존 v6.1 파일을 전부 1:1로 대체한 패키지가 아니다. 일부 규칙은 이전·재구성됐지만,
스크리닝·증강설계·무작위화·승인권한·provenance 등 일부 자산은 기존 폴더에만 남아 있다.
따라서 v7 실행경로와 회귀시험이 완성되기 전에 기존 폴더를 삭제하면 안 된다.

---

## 2. 패키지의 성격

이 ZIP은 실행 애플리케이션이 아니라 **룰북·참조 마스터·검증자료 데이터 패키지**다.

- RB00: 전역 개발정책 config. 18개 룰북 수에는 포함하지 않는다.
- RB01–RB18: 실행 룰북 18개
- M01–M07: 참조 마스터 7개
- M06: 기존 66개 시험과 제형·공정 확인시험 24개를 합친 90개 확인시험 registry
- M07: 상태 전이에 사용하는 reason-code 단일 registry
- `manifest.yaml`: 패키지 파일 목록과 레코드 수
- `scripts/validate_package.py`: 정적 무결성 검증기
- `SHA256SUMS`: 파일 해시

모든 규칙은 다음 상태로 배포된다.

```yaml
validation_status: DRAFT_EXPERT_REVIEW_REQUIRED
enforcement_enabled: false
```

따라서 설치만으로 기존 Formula 1 실행 결과가 바뀌면 안 된다. 활성화는 별도 코드와 승인 절차를
통해서만 수행한다.

---

## 3. 설치 전 금지사항

첫 PR에서는 다음 작업을 하지 않는다.

1. 기존 `database/07_doe/{analysis,...,verification}` 폴더 삭제
2. 기존 `config/rulebook_manifest.yaml`을 v7 `manifest.yaml`로 교체
3. 기존 `database/reference/confirmation_test_master.csv`를 M06으로 덮어쓰기
4. v7의 `enforcement_enabled`를 `true`로 일괄 변경
5. DRAFT 행을 전문가 검토 없이 production rule로 승격
6. ZIP 파일만 저장소에 커밋하고 압축 내부 파일은 설치하지 않는 방식
7. 상류 후보처방의 mg/% 값을 DoE factor center로 자동 복사하는 코드

---

## 4. 요구 환경

- Git
- Python 3.11 이상 권장
- `PyYAML`
- 현재 저장소의 테스트 의존성
- macOS 또는 Linux shell 예시를 기준으로 작성

검증기가 `yaml` 모듈을 찾지 못하면 현재 프로젝트 환경에 다음 의존성을 추가한다.

```bash
python -m pip install PyYAML
```

프로젝트가 `uv`를 사용한다면 해당 프로젝트의 의존성 관리 방식으로 추가한다.

```bash
uv add PyYAML
```

---

## 5. 권장 설치 절차

### 5.1 작업 브랜치 생성

```bash
git clone https://github.com/zihwaan/formula1-qbd.git
cd formula1-qbd
git checkout -b feature/doe-v7-data
```

이미 clone한 저장소라면 최신 기준 브랜치에서 작업 브랜치만 만든다. 작업 중인 변경사항이 있으면
먼저 별도 commit 또는 stash 정책을 팀과 확인한다.

### 5.2 ZIP 압축 해제

다운로드 경로는 환경에 맞게 바꾼다.

```bash
mkdir -p /tmp/formula1_doe_v7_install

unzip ~/Downloads/formula1_07_doe_rulebooks_v7.0.zip \
  -d /tmp/formula1_doe_v7_install
```

### 5.3 v7.0 전용 경로에 복사

```bash
mkdir -p database/07_doe/v7_0

cp -R \
  /tmp/formula1_doe_v7_install/formula1_07_doe_rulebooks_v7.0/. \
  database/07_doe/v7_0/
```

설치 후 다음 파일이 보여야 한다.

```bash
test -f database/07_doe/v7_0/manifest.yaml
test -f database/07_doe/v7_0/config/development_policy.yaml
test -f database/07_doe/v7_0/rulebooks/18_labloop_backtrack_rules.csv
test -f database/07_doe/v7_0/masters/07_reason_code_catalog.csv
```

### 5.4 패키지 validator 실행

```bash
python database/07_doe/v7_0/scripts/validate_package.py \
  database/07_doe/v7_0
```

정상 결과:

```text
Rulebooks: 18/18
Reference masters: 7/7
Confirmation tests: 90/90
Registered sources: 32
Registered reason codes: 167
Warnings: 0
Errors: 0
RESULT: PASS
```

### 5.5 파일 해시 확인

```bash
cd database/07_doe/v7_0
sha256sum -c SHA256SUMS
cd ../../..
```

macOS 기본 환경에서 `sha256sum`이 없다면 다음 중 팀 표준 도구를 사용한다.

```bash
brew install coreutils
gsha256sum -c database/07_doe/v7_0/SHA256SUMS
```

### 5.6 데이터 전용 PR 생성

```bash
git add database/07_doe/v7_0
git commit -m "Add DoE rulebooks and reference masters v7.0"
git push -u origin feature/doe-v7-data
```

첫 PR은 **데이터 추가만** 다룬다. loader 구현·기존 파일 이동·UI 연결을 같은 commit에 섞지 않는 것이
검토와 rollback에 유리하다.

---

## 6. 기존 v6.1 폴더 처리

### 6.1 첫 PR의 처리

모두 그대로 유지한다.

```text
analysis/
execution/
governance/
masters/
planning/
qbd_risk/
readiness/
verification/
```

### 6.2 바로 삭제할 수 없는 이유

v7.0으로 완전히 이전되지 않았거나 별도 판단이 필요한 대표 파일은 다음과 같다.

```text
analysis/screening_analysis_rules.csv
planning/doe_augmentation_rules.csv
planning/doe_randomization_blocking_rules.csv
planning/statistical_policy_constants.csv
governance/approval_authority_rules.csv
governance/provenance_versioning_rules.csv
masters/cqa_templates.csv
masters/process_unit_operation_master.csv
```

기존 파일별로 다음 상태 중 하나를 부여한 migration matrix가 필요하다.

- `MIGRATED`
- `PARTIALLY_MIGRATED`
- `NOT_MIGRATED`
- `REPLACED`
- `DEPRECATED_AFTER_VALIDATION`

권장 파일명:

```text
database/07_doe/V6_TO_V7_MIGRATION_MATRIX.csv
```

권장 컬럼:

```text
legacy_file
v7_target
migration_status
runtime_reference
current_action
deletion_gate
owner
notes
```

### 6.3 기존 경로 참조 검색

archive 또는 삭제를 검토하기 전에 다음을 실행한다.

```bash
rg -n \
  "database/07_doe|screening_analysis_rules|doe_augmentation_rules|statistical_policy_constants|provenance_versioning_rules" \
  formula config scripts tests web
```

동적 path 조합도 있으므로 문자열 검색만으로 삭제를 확정하지 않는다. loader 테스트와 end-to-end 테스트를
함께 확인해야 한다.

### 6.4 archive 시점

다음 조건을 모두 만족한 뒤 별도 PR에서 기존 파일을 archive할 수 있다.

1. v7 전용 loader가 구현됨
2. 18개 룰북과 7개 마스터가 모두 로드됨
3. 기존 파일과 v7 파일의 migration matrix 검토 완료
4. 기존 unit/integration tests 통과
5. CBD ODT literature replay golden test 통과
6. 신규 API `NEEDS_FEASIBILITY` 시나리오 통과
7. 기존 경로의 runtime 참조가 제거되거나 명시적으로 유지됨
8. 제형·통계·QA reviewer 승인

archive 권장 경로:

```text
database/07_doe/archive/v6_1/
```

처음부터 `git rm`으로 삭제하지 않는다. archive 후 한 릴리스 이상 관찰하고 최종 삭제 여부를 결정한다.

---

## 7. 기존 Formula 1 룰북과의 경계

현재 저장소의 기존 실행경로는 다음 manifest를 사용한다.

```text
config/rulebook_manifest.yaml
```

이 manifest는 `formula.checkers.registry.RulebookRegistry`가 읽으며 각 항목에 다음과 같은 필드를 요구한다.

```text
id
file
layer
owner_agent
eval_type
severity
applies_when
strategy
schema
```

반면 v7 패키지의 `manifest.yaml`은 패키지 inventory이며 다음 목적을 갖는다.

```text
id
file
purpose
records
package version
validation status
```

두 manifest의 계약은 다르다. 따라서 v7 `manifest.yaml`을 기존 `RulebookRegistry`에 직접 넣으면 안 된다.

권장 경계:

```text
formula/
└── doe/
    ├── __init__.py
    ├── contracts.py
    ├── loader.py
    ├── state_machine.py
    ├── orchestrator.py
    ├── feasibility.py
    ├── design_generator.py
    ├── design_validator.py
    ├── protocol_compiler.py
    ├── result_gate.py
    ├── model_selector.py
    ├── design_region.py
    └── verification.py
```

기존 후보처방 생성 graph와 신규 실험개발 graph는 immutable handoff로 연결하되 내부 state를 공유하지 않는다.

---

## 8. v7 전용 설정 권장안

다음과 같은 별도 설정 파일을 추가하는 것을 권장한다.

```text
config/doe_module.yaml
```

초기값 예시:

```yaml
module_version: 7.0.0
enabled: false
runtime_mode: VALIDATION_ONLY
rulebook_root: database/07_doe/v7_0
package_manifest: database/07_doe/v7_0/manifest.yaml
development_policy: database/07_doe/v7_0/config/development_policy.yaml
allow_draft_enforcement: false
legacy_07_doe_enabled: true
confirmation_test_master: database/07_doe/v7_0/masters/06_confirmation_test_master.csv
```

초기 loader는 다음을 강제해야 한다.

1. `architecture_version == 7.0.0`
2. manifest에 룰북 18개와 마스터 7개가 존재
3. 각 파일의 실제 행 수가 manifest와 일치
4. SHA-256 또는 배포 artifact hash 기록
5. DRAFT 규칙은 읽을 수 있지만 판정 집행은 불가
6. `enforcement_enabled=false`이면 state advance 금지
7. 중복 ID·미등록 source/test/reason code 차단
8. 금지 상태 `CONTROL_STRATEGY`, `PPQ_READY`, `COMMERCIAL_RELEASE` 차단

경로를 Python 코드 여러 곳에 하드코딩하지 않는다. 설정 객체 하나에서 읽고 dependency injection으로 전달한다.

---

## 9. 확인시험 마스터 호환성

### 9.1 기존 마스터

현재 Lab-in-the-loop 코드는 다음 파일을 직접 읽는다.

```text
database/reference/confirmation_test_master.csv
```

기존 코드는 66개 시험과 다음 컬럼을 전제로 한다.

```text
test_id
test_name
test_category
test_design
output_variable
acceptance_logic
unit
source_reference
source_url
```

### 9.2 v7 M06

신규 파일:

```text
database/07_doe/v7_0/masters/06_confirmation_test_master.csv
```

주요 차이:

- 90개 시험
- `test_name_en`, `test_name_ko` 분리
- `experimental_unit`, `nested_structure` 추가
- `allowed_for_agent` 추가
- version·validation 상태 추가

따라서 M06을 기존 경로에 복사해 덮어쓰면 `formula/feedback/labloop.py`의 `test_name` 접근에서 오류가
발생할 수 있다.

### 9.3 권장 연결 방법

첫 단계에서는 기존 Lab-in-the-loop와 신규 DoE Lab-loop를 분리한다.

```text
기존 formula/feedback/labloop.py
  → database/reference/confirmation_test_master.csv 유지

신규 formula/doe/*
  → database/07_doe/v7_0/masters/06_confirmation_test_master.csv 사용
```

공통화할 때는 adapter가 canonical contract를 반환하도록 한다.

```python
class ConfirmationTestRecord:
    test_id: str
    display_name: str
    test_category: str
    test_design: str
    output_variable: str
    acceptance_logic: str
    unit: str
    allowed_for_agent: str
    source_reference: str
    source_url: str
```

표시명 권장 규칙:

```python
display_name = test_name_ko or test_name_en
```

LLM은 `allowed_for_agent == "PROPOSE_ONLY"`인 시험을 제안만 할 수 있으며, 실행 승인·결과 판정은
결정론적 gate와 연구자가 담당한다.

---

## 10. 권장 개발 PR 순서

### PR 1 — 데이터 설치

- `database/07_doe/v7_0/` 추가
- validator 실행
- 기존 파일 변경 없음
- feature flag `false`

### PR 2 — loader와 contract

- `formula/doe/contracts.py`
- `formula/doe/loader.py`
- `config/doe_module.yaml`
- 18+7 load test
- ID·source·reason·test 참조 검증

### PR 3 — 상태기계와 핵심 결정론 서비스

- immutable handoff
- CQA/FMEA/factor/range gate
- feasibility routing
- FCCD/BBD generator와 validator
- result-quality gate
- hierarchical model selector
- provisional design region
- verification routing

### PR 4 — UI와 기존 Lab-in-the-loop adapter

- CQA 최대 4개 선택
- factor 최대 3개 선택
- low/center/high 입력과 evidence status
- M06 adapter
- Axes3D/contour 결과 표시

### PR 5 — v6.1 migration/archive 검토

- `V6_TO_V7_MIGRATION_MATRIX.csv` 확정
- 미이관 규칙 보강 또는 폐기 사유 승인
- 기존 경로 참조 제거 확인
- archive PR

---

## 11. 테스트 최소요건

### 11.1 정적 패키지 테스트

```bash
python database/07_doe/v7_0/scripts/validate_package.py \
  database/07_doe/v7_0
```

### 11.2 기존 프로젝트 회귀시험

프로젝트 표준 명령을 우선 사용한다. 현재 pytest 기반이라면 예시는 다음과 같다.

```bash
pytest -q
```

### 11.3 신규 loader 테스트

최소 확인 항목:

- RB01–RB18 정확히 18개 로드
- M01–M07 정확히 7개 로드
- M06 시험 90개 로드
- M07 reason code 중복 없음
- RB18의 모든 confirmation test ID가 M06에 존재
- 모든 `SRC_*`가 source registry에 존재
- DRAFT 규칙은 enforcement 불가
- prototype 값이 factor center로 자동 복사되지 않음

### 11.4 Golden tests

1. 2요인 연속형 → FCCD 13-run
2. 3요인 연속형 → BBD 17-run
3. 신규 API + 제안 범위만 존재 → `NEEDS_FEASIBILITY`
4. 2요인 feasibility → 5조건
5. 3요인 feasibility → 7조건
6. 중심점 실패 → `PROTOTYPE_REVISION_REQUIRED`
7. 경계 실패 → `RANGE_REVISION_REQUIRED`
8. 부적절한 모델 → `MODEL_INADEQUATE`, design region 미생성
9. 독립 verification 전 → `PROVISIONAL_DESIGN_SPACE` 유지
10. 금지 상태가 workflow에 생성되지 않음

---

## 12. 활성화 조건

데이터가 설치됐다는 이유만으로 실행 기능을 켜지 않는다. 다음 조건을 모두 만족해야 한다.

- [ ] 제형 연구자 검토
- [ ] 분석 연구자 검토
- [ ] 통계 검토
- [ ] QA/거버넌스 검토
- [ ] source locator 검토
- [ ] 룰북별 validation status 승인본 생성
- [ ] loader unit tests 통과
- [ ] 기존 회귀시험 통과
- [ ] CBD ODT literature replay 통과
- [ ] 신규 API feasibility 시나리오 통과
- [ ] rollback rehearsal 완료
- [ ] 활성화 승인 event 기록

승인 전 권장 설정:

```yaml
enabled: false
runtime_mode: VALIDATION_ONLY
allow_draft_enforcement: false
```

데모에서 화면만 연결할 경우에도 판정 결과에는 다음 표시를 유지한다.

```text
DRAFT / RESEARCH USE ONLY / NOT A GMP INSTRUCTION
```

---

## 13. 롤백

v7.0은 별도 경로와 feature flag로 설치하므로 rollback은 파일 삭제가 아니라 기능 비활성화로 수행한다.

```yaml
enabled: false
runtime_mode: VALIDATION_ONLY
legacy_07_doe_enabled: true
```

롤백 시 다음을 보존한다.

- 실패한 study의 event log
- 사용한 package hash
- rulebook/model/analysis-plan version
- 실패 reason code
- 생성한 artifact와 invalidation 상태

v7 경로를 즉시 삭제하지 않는다. 원인 분석과 재현이 끝난 뒤 후속 PR에서 처리한다.

---

## 14. 완료 기준

설치 작업은 다음 조건을 모두 충족했을 때 완료로 본다.

1. 파일 위치가 `database/07_doe/v7_0/`이다.
2. 기존 v6.1 폴더가 유지되어 있다.
3. package validator가 `RESULT: PASS`를 출력한다.
4. SHA-256 검사가 통과한다.
5. 기존 프로젝트 테스트가 통과한다.
6. 기존 `config/rulebook_manifest.yaml`이 v7 manifest로 덮어써지지 않았다.
7. 기존 66개 confirmation master가 덮어써지지 않았다.
8. 신규 module의 기본 feature flag가 꺼져 있다.
9. PR 설명에 패키지 버전·hash·검증 결과가 기록되어 있다.
10. 기존 폴더의 삭제·archive는 별도 migration PR로 분리되어 있다.

---

## 15. PR 설명 템플릿

```markdown
## 목적

Formula 1 실험개발/DoE v7.0 룰북 데이터 패키지를 병행 설치한다.

## 설치 경로

`database/07_doe/v7_0/`

## 포함 범위

- RB01–RB18: 18개
- M01–M07: 7개
- confirmation tests: 90개
- runtime enforcement: disabled

## 기존 자산

기존 `database/07_doe/{analysis,...,verification}`는 유지했다.
기존 `database/reference/confirmation_test_master.csv`는 변경하지 않았다.

## 검증

- package validator: PASS
- SHA256SUMS: PASS
- existing test suite: PASS/미실행 사유

## 활성화

이 PR은 데이터 설치 전용이며 v7 runtime은 활성화하지 않는다.

## 롤백

기능 flag를 끄고 기존 v6.1 경로를 유지한다.
```

---

## 16. 문의가 필요한 경우

다음 항목은 개발자가 임의로 결정하지 않고 제형·통계 담당자에게 요청한다.

- 특정 CQA의 규격·시험법·요약함수
- 신규 API factor range와 evidence status
- FMEA S/O/D 점수와 고심각도 제외 근거
- 설비별 운전범위와 분해능
- 시험법 반복구조와 experimental unit
- 모델 flag 허용 여부
- verification batch 수와 점 역할
- v6.1 규칙의 폐기 여부

LLM은 설명과 후보를 제안할 수 있지만 숫자, 규격, 시험, 상태승격 또는 룰북 내용을 임의로 확정할 수 없다.
