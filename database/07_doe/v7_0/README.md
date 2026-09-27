# Formula 1 Experimental Development Rulebooks v7.0

이 패키지는 `formula1-experimental-development-architecture-v7.0.md`를 구현하기 위한 **전문가 검토용 초기 데이터**입니다.

## 구성

- 전역 설정: RB00 `config/development_policy.yaml` (18개 룰북 수에 포함하지 않음)
- 실행 룰북: RB01–RB18, 정확히 18개
- 참조 마스터: M01–M07, 정확히 7개
- 추가 자료: source registry, schema, validation script/report, XLSX catalog

## 중요한 안전 설정

- 모든 규칙은 `DRAFT_EXPERT_REVIEW_REQUIRED` 상태이며 `enforcement_enabled=false`입니다.
- 상류 후보처방 mg/% 값은 `REFERENCE_PROTOTYPE`일 뿐 DoE 중심값이 아닙니다.
- 신규 API에서 범위근거가 제안·원자료 없는 문헌뿐이면 `NEEDS_FEASIBILITY`로 이동합니다.
- 2요인 feasibility는 5조건, 3요인은 7조건의 축점 micro-study입니다.
- 기본 RSM은 2요인 FCCD 13-run, 3요인 BBD 17-run입니다.
- LLM은 후보·설명·가설만 제시하며 수치, 통계판정, DB, 상태를 확정하지 않습니다.
- 이 패키지는 GMP SOP, PPQ, 상업출하 또는 규제 승인 design space를 주장하지 않습니다.

## 통합 순서

1. `manifest.yaml`의 파일·해시를 확인합니다.
2. `python scripts/validate_package.py .`를 실행합니다.
3. 과학·통계·QA·실험실 담당자가 각 레코드를 검토합니다.
4. 승인 레코드만 별도 릴리스 버전에서 활성화합니다. 이 초안의 원본을 덮어쓰지 않습니다.
5. 상태 전이는 M07 reason code만 사용하고 append-only event log에 남깁니다.

## 파일 수 기준

RB00은 시스템 정책/config이므로 “18개 룰북” 집계에서 제외했습니다. 따라서 사용자가 요청한 산출물은 **RB01–RB18 18개 + M01–M07 7개**입니다.
