# 07_doe — ExperimentalDevelopmentGraph 룰북·마스터 (v6.1)

명세: `formula1-doe-agent-architecture-v6.1.md` §7–§9, §15  
상태: 모든 행 `validation_status = DRAFT_PENDING_REVIEW` → **production 모드에서는 어떤 규칙도 집행되지 않음**. demo(sandbox) 모드에서만 집행.

## 구성

룰북·설정 23종(manifest 1 + CSV 22) + 참조 마스터 7종 = 30종, 규칙 171개.

```
database/07_doe/
  governance/   rulebook_manifest.yaml (#1: 파일 목록 + context_schema + 함수 registry + backend capability + 집행 모드)
                evidence_governance_rules (#2), approval_authority_rules (#3), provenance_versioning_rules (#4)
  readiness/    development_readiness_rules (#5)
  qbd_risk/     qtpp_cqa_mapping (#6), cqa_response_definition (#7), fmea_failure_mode (#8),
                fmea_scoring_scale (#9), factor_eligibility (#10), factor_range_constraint (#11)
  planning/     statistical_policy_constants (#12), doe_design_selection (#13), doe_randomization_blocking (#14),
                doe_design_validation (#15), doe_augmentation (#16)
  execution/    run_sheet_compilation (#17), result_data_quality (#18)
  analysis/     screening_analysis (#19), model_validation (#20), design_space (#21)
  verification/ verification (#22), backtrack_routing (#23: (reason_code, from_state) → next_state 단일 registry)
  masters/      cqa_templates, process_unit_operation_master, test_method_registry, excipient_use_range_master,
                equipment_capability_master, confirmation_test_master, statistical_sources
tests/fixtures/ lornoxicam_table3.csv, rule_fixtures.json (48건)
tests/golden/   compute_lornoxicam_golden.py
scripts/        validate_07_doe.py
```

## 검증

```
python scripts/validate_07_doe.py database/07_doe tests/fixtures/rule_fixtures.json
→ files=29 rules=171 fixtures_pass=48 fixtures_fail=0 errors=0
```

정적 검사: YAML manifest ↔ 파일, 공통 스키마, rule_id 유일, enum, 차단 규칙 override 금지, stage 유효성,
조건식 AST 허용 노드·필드 경로·함수·인자 수·상수, 전이표 정합(예외 목록 없음), 출처 등록.  
실행 검사: fixture 입력으로 규칙을 실제 평가 (Python eval 미사용). 필드 오타·미등록 함수·override 위반·전이 누락을 주입하면 모두 오류로 잡힌다.

## 조건식 DSL

- 파이썬 문법 부분집합, AST 화이트리스트 평가기
- 루트·필드는 manifest `context_schema`에 정의된 것만 (서비스가 artifact → context 매핑)
- 컬렉션: generator expression `any(x.f == 1 for x in xs)`. 빈 컬렉션 `all` → True이므로 승격 판정은 `nonempty_all`
- `matrix_rank`(행렬 rank)와 `evidence_permits(status, use)`(근거 권한)는 별개 함수
- None과의 크기 비교·산술 → `missing_value_action` 적용 (미발화로 처리하지 않음)
- `const.X` = statistical_policy_constants
- 도메인 헬퍼 함수(`recompute_fingerprint`, `equipment_supports` 등) 구현은 서비스 코드 몫. fixture 평가기는 판정 핵심 함수만 구현

## 팀 검토 필요 (원문 대조 전 수치)

1. excipient_use_range_master: 전 범위값 (`range_type = TYPICAL_USE`, 한계 아님). HPE 판본·페이지 확인, 라이선스
2. cqa_templates: USP <905> AV ≤ 15, <1216> 1.0%, Ph. Eur. 분산정 3분·710 µm. 약전 판정 절차는 요약 기준과 별도
3. statistical_policy_constants: 0.90, 0.20, Bonferroni family α 0.05 등은 프로젝트 기본값. 팀 합의
4. statistical_sources: 서지 전체 `TO_VERIFY`
5. test_method_registry: 시험법 반복정밀도는 전부 비어 있음 (실험실 밸리데이션 값 입력 필요). v6의 Lornoxicam 중심점 SD는 배치 간 변동이라 제거함
6. equipment_capability_master: 능력값 UNKNOWN
7. FDA IID snapshot은 번들에 없음 (manifest `external_dependencies`)

## v6.1에서 아직 남은 것 (검토 보고서 기준)

B3 변환 응답 계약, B4 확인점 수 산정 근거, B7 다변량 공동확률, B8 가중회귀·조건수, D2 다중 verdict 원자 적용,
D3–D4 승인·이벤트 저장 구조, E 런타임 DB 스키마, 동시 승인 충돌 테스트.
