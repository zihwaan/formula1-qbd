# Schema notes

## 공통 CSV rule schema

대부분의 rule CSV는 `rule_id`, `rulebook_id`, `version`, `priority`, `scope`, `stage`,
`when_expression`, `required_inputs`, `missing_value_action`, `gate_effect`, `result_code`,
`next_state`, `message_ko`, `implementation_hint`, `human_override`, `source_ids`,
`validation_status`, `effective_from`, `enforcement_enabled`를 공유합니다.

`when_expression`은 실행 가능한 Python 코드가 아니라 제한된 DSL 문자열입니다. 파서가 허용한 연산자와
등록 함수만 평가해야 하며 `eval` 사용은 금지합니다.

## 결정권

- Rulebook/통계엔진: 수치검사, 설계생성, 모형계산, gate 결과
- LLM: 후보·설명·가설·사용자 친화 문구
- 연구자: CQA/FMEA/요인/범위/프로토콜/verification 승인

## 버전 원칙

레코드 수정 시 기존 행을 덮어쓰지 말고 새 version/effective_from을 가진 릴리스를 생성합니다.
룰북 해시와 모델·분석계획·seed를 각 artifact provenance에 저장합니다.
