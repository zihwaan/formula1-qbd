# Formula 1 Rulebook — 디렉토리 구조

각 CSV는 동일 폴더에 `*_SOURCES.md` 출처 문서를 동반합니다.
출처 문서 없는 CSV는 규칙 엔진에 투입하지 마십시오.

```
formula1_rulebook/
├── 00_master/
│   ├── excipient_master.csv            [100행] 부형제 마스터 (부분 검증)
│   ├── excipient_master_SOURCES.md
│   ├── rdkit_descriptor_definitions.csv [9행] RDKit 계산 정의 (결정론적)
│   ├── structural_flags_smarts.csv     [5행] SMARTS 구조플래그 단일출처 (미검증)
│   ├── physchem_estimation_rules.csv   [5행] 물성 추정 (실측 우선)
│   └── physchem_pipeline_SOURCES.md   (예정)
├── 01_route_decision/
│   ├── route_decision_tree.csv         [10행] 공정 분기 (검증강도 혼재)
│   ├── powder_flow_scale.csv           [21행] USP<1174> 유동성 등급 (전행 검증)
│   └── route_decision_tree_SOURCES.md
├── 02_incompatibility/
│   ├── incompatibility_1to1.csv        [15행] 배합금기 1:1 (검증강도 혼재)
│   ├── incompatibility_1to1_SOURCES.md
│   ├── incompatibility_multicomponent.csv [6행] 다성분 상호작용 (검증)
│   └── incompatibility_multicomponent_SOURCES.md (통합문서는 05에)
├── 03_process/
│   ├── direct_compression_rules.csv    [10행] 직접타정 (예측/실험 구분, 검증강도 혼재)
│   ├── direct_compression_rules_SOURCES.md
│   ├── dry_granulation_rules.csv       [7행] 건식과립/롤러컴팩션 (검증)
│   ├── wet_granulation_aqueous_rules.csv [6행] 습식과립 수계 (검증)
│   ├── wet_granulation_nonaqueous_rules.csv [5행] 습식과립 비수계 (검증)
│   ├── coating_rules.csv               [6행] 코팅 (장용성 위산맥락, 검증강도 혼재)
│   ├── capsule_filling_rules.csv       [6행] 캡슐충전 (젤라틴 가교주의)
│   ├── excipient_functional_ratio_rules.csv [10행] 부형제 배합비 범위
│   ├── coating_capsule_ratio_SOURCES.md
│   └── residual_solvent_ich_q3c_rules.csv   (예정)
├── 04_biopharmaceutics/
│   ├── bcs_classification_criteria.csv [10행] ICH M9 분류 경계값 (전행 검증)
│   ├── bcs_strategy_rules.csv          [4행] BCS class별 전략 (검증)
│   ├── bcs_strategy_rules_SOURCES.md
│   ├── dissolution_acceptance_usp711.csv [6행] USP<711> QC 판정 (전행 검증)
│   ├── dissolution_apparatus_usp711.csv [4행] USP<711> 장치 사양 (전행 검증)
│   ├── dissolution_biowaiver_ichm9.csv [3행] ICH M9 바이오웨이버 (전행 검증)
│   ├── dissolution_SOURCES.md

│   └── analytical_method_rules.csv          (예정)
├── 05_regulatory/
│   ├── pediatric_safety_rules.csv      [46행] 소아 안전 (전 컬럼 검증 완료)
│   ├── pediatric_safety_rules_SOURCES.md
│   ├── stability_storage_conditions_ichq1a.csv [11행] ICH Q1A 저장조건 (전행 검증)
│   ├── stability_significant_change_ichq1a.csv [7행] ICH Q1A 유의변화 (전행 검증)
│   ├── stability_SOURCES.md
│   ├── packaging_compatibility_rules.csv [5행] 포장 적합성 (검증)
│   ├── coloring_flavoring_pediatric_rules.csv [10행] 색소/향료/감미 (검증)
│   └── packaging_coloring_multicomponent_SOURCES.md
└── 06_config/
    ├── rulebook_config.csv             [23행] 룰북 배선도 (완료)
    ├── rulebook_config_SOURCES.md
    ├── reviewer_registry.csv           [6행] 심사관 정의·순위가중치 (B모델, 잠정값)
    ├── severity_scoring_config.csv     [10행] 합의 엔진 설정 (B모델)
    ├── severity_scoring_config_SOURCES.md
    └── severity_scoring_config.csv          (예정)
```

## 검증 상태 표기 규약

모든 규칙 CSV는 `verification_status` 컬럼을 가집니다.

| 값 | 의미 | 엔진 동작 |
|---|---|---|
| `VERIFIED` | 1차 출처 원문 대조 완료 | 사용 가능 |
| `SCHEMA_ONLY` | 분류·구조만 확정, 수치 미조회 | Hard Fail 사용 금지 |
| `UNVERIFIED_CRITICAL` | 안전성 직결이나 근거 미확보 | 사용 금지, 경고 발생 |
| `NO_SOURCE_FOUND` | 조사했으나 근거 없음 (기록용) | 실행 안 됨 |
| `ESCALATION_REQUIRED` | 에이전트 단독 판정 불가 | 사람에게 이관 |
| `PROVISIONAL` | 출처 없는 팀 내부 잠정값 (가중치 등) | 본선 자문 보정 예정 |

## 판정 유형(judgment_type) 6종

| 유형 | 반려 가능 | 설명 |
|---|---|---|
| deterministic | O | 계산기식 판정 (Hard Fail 가능) |
| hybrid | O | 수치 + 심사관 맥락 판단 |
| advisory | X | 제안만 (판정 아님) — 예: 시험법 개발 |
| reference_table | X | 조회용 참조표 |
| escalation | X(사람이) | 에이전트 판정 불가, 사람 필수 |
| config | X | 시스템 설정 |

## 규제 데이터 버전 관리 원칙

규제 문서는 개정됩니다. 모든 규제 유래 CSV는 다음 3컬럼을 필수로 가집니다.

- `source_version` — 문서 판번호 (예: EMA/CHMP/302620/2017 Rev.2)
- `source_updated_on` — 해당 항목의 개정일
- `retrieved_on` — 조회일

실제로 corr.1 → Rev.2 사이에 에탄올 임계값이 절대량(mg/dose)에서
체중당(mg/kg/dose)으로 전면 개편되었습니다. 버전 기록이 없으면
이런 변경이 조용히 잘못된 판정으로 이어집니다.
