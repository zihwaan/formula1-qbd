# 물리화학 파이프라인 입구 — 출처 및 설계 문서 (3개 파일)

## 0. 이 파일들이 시스템의 입구다

에이전트 전체 흐름에서 이 세 파일의 위치:

```
[입력]  SMILES + 자연어 요구사항
           │
           ▼  RDKit 계산
  ① rdkit_descriptor_definitions.csv ── 무엇을 어떤 함수로 계산하는가 (결정론적)
           │
           ├──▼  구조 매칭
  ② structural_flags_smarts.csv ─────── 아민기/에스터 등 구조 플래그 (결정론적)
           │
           ▼  물성 추정
  ③ physchem_estimation_rules.csv ───── descriptor→물성 번역 (추정, 실측 우선)
           │
           ▼
  [API 프로파일]  has_primary_amine=T, solubility_hint=low, bcs_class=III? ...
           │
           ▼  이 프로파일이 하위 규칙 파일들의 입력 조건이 됨
  route_decision / incompatibility / bcs_classification / ...
```

원래 `api_physicochemical_thresholds.csv` 하나로 계획했으나, **RDKit이 실제로
할 수 있는 것과 없는 것을 섞으면 안 되기 때문에** 세 파일로 분리했습니다.
이 분리가 이 파일의 핵심입니다.

## 1. ⚠ 가장 중요한 원칙 — 계산과 추정을 구분한다

심사위원과 개발자가 가장 먼저 찌를 지점입니다. "RDKit으로 물성을 뽑는다"를
뭉뚱그리면 안 됩니다. 세 종류가 있습니다:

| 종류 | 예시 | RDKit | 신뢰도 | 파일 |
|---|---|---|---|---|
| **직접 계산** | MW, logP, TPSA, HBD/HBA, 회전결합 | 함수 있음 | 결정론적 | ① |
| **구조 매칭** | 1차 아민 존재, 에스터 존재 | SMARTS/fragment | 결정론적 | ② |
| **물성 추정** | 수용해도, 투과도, pKa | **함수 없음** | 낮음 | ③ |

RDKit 문서 확인 결과(2026.03 기준, 핵심 함수는 2025.03과 동일):
`MolWt`, `MolLogP`(Wildman-Crippen), `TPSA`(Ertl), `NumHDonors`,
`NumHAcceptors`, `NumRotatableBonds`, `NumAromaticRings`는 모두 존재하고 안정적입니다.
`CalcMolDescriptors()`로 전체를 한 번에 얻을 수도 있습니다.

**그러나 experimental solubility, pKa, permeability를 직접 주는 함수는 RDKit에 없습니다.**
이것들은 descriptor로부터 추정하거나 외부 모델·실측이 필요합니다.
③ 파일이 바로 이 "추정"을 담되, **추정임을 confidence 컬럼으로 명시**합니다.

만약 이 구분 없이 "logP > 3이면 저용해"를 확정 판정처럼 쓰면,
그것이 슬라이드 3에서 경계한 hallucination의 데이터 버전이 됩니다.
계산 가능한 척하지만 실제로는 추정인 값이기 때문입니다.

## 2. 파일 ① rdkit_descriptor_definitions.csv

RDKit이 **직접 계산**하는 descriptor 9종과 그 함수명·모듈·용도입니다.
전부 `deterministic=yes`. 같은 SMILES면 같은 값이 나옵니다.

주의점:
- **`MolLogP`는 실측 logP가 아니라 Wildman-Crippen 계산 추정값**입니다.
  값 자체는 결정론적이지만(같은 분자→같은 logP), 그것이 실측과 일치한다는 보장은 없습니다.
- `CalcCrippenDescriptors(mol)`는 (logP, MR) 2-tuple을 반환합니다(DSC008).
- 아민 검출(DSC009)은 `fr_NH2` 카운트와 SMARTS를 **병용**하도록 했습니다.
  단일 방법보다 교차검증이 안전합니다.

## 3. 파일 ② structural_flags_smarts.csv — SMARTS 단일 출처

이 파일이 중요한 이유: **SMARTS 패턴의 단일 출처(single source of truth)**입니다.
앞서 `incompatibility_1to1.csv`에 SMARTS를 넣었지만, 그건 참조일 뿐이고
실제 패턴 정의는 여기 모읍니다. SMARTS가 여러 파일에 흩어지면 반드시 어긋납니다.

배합금기 파일은 `has_primary_amine`이라는 **플래그 이름**만 참조하고,
그 플래그를 어떻게 판정하는지(SMARTS)는 이 파일이 소유합니다.

### ⚠ 전 패턴 `UNTESTED` — RDKit 실측 검증 필수

`validation_status`가 5행 모두 `UNTESTED`입니다. 제가 작성한 SMARTS이며
**RDKit으로 실행 테스트하지 않았습니다.** 개발자는 반드시 알려진 양성/음성
사례로 검증해야 합니다:

- FLG001(1차 아민) 양성: vigabatrin, aminophylline / 음성: acetaminophen
- FLG002(2차 아민) 양성: fluoxetine
- **FLG005(아미드, Maillard 비반응) 양성: acetaminophen**

### ⚠⚠ FLG005가 데모 오류를 막는 핵심

FLG005(`is_amide_not_amine`)를 별도로 둔 이유가 중요합니다.
지난 BCS·배합금기 작업에서 반복 지적한 **아세트아미노펜 오류**를 구조적으로 막는 장치입니다.

아세트아미노펜은 아미드(acetamido)이지 1차 아민이 아닙니다. 그런데 SMARTS를
허술하게 짜면 아미드 질소를 아민으로 오탐할 수 있습니다. FLG001의 패턴에
`!$(NC=O)`(아미드 제외)를 넣었고, FLG005로 아미드를 **양성 검출**하여
FLG001과 **상호배제 검증**하도록 했습니다.

즉 엔진은 "1차 아민 검출됨 AND 아미드 아님"을 함께 확인해야 하며,
아세트아미노펜은 FLG005=true, FLG001=false로 나와야 정상입니다.
이게 안 되면 데모에서 "아세트아미노펜이 Maillard 반응한다"는 오판이 재발합니다.

## 4. 파일 ③ physchem_estimation_rules.csv — 추정과 실측의 경계

descriptor를 물성으로 **번역**하되, 각 규칙에 `confidence`와
`override_by_experimental`을 붙였습니다.

| ID | 추정 물성 | confidence | 실측 우선 | 처리 |
|---|---|---|---|---|
| EST001 | 수용해도 등급 | **low** | yes | 저신뢰→실측 요구/에스컬레이션 |
| EST002 | 투과도 등급 | **low** | yes | RDKit로 신뢰성 없음→에스컬레이션 |
| EST003 | 용량:용해도比 | medium | yes | 용해도가 추정이면 이것도 추정 |
| EST004 | Lipinski | **high** | no | 계산 정의라 그대로 사용 |
| EST005 | Veber | **high** | no | 계산 정의라 그대로 사용 |

### 핵심 구분: confidence high vs low

- **EST004(Lipinski), EST005(Veber)는 confidence=high.** 이건 추정이 아니라
  **정의상 계산**이기 때문입니다. "MW≤500 & logP≤5 & HBD≤5 & HBA≤10"은
  descriptor만으로 확정됩니다. 단, 통과해도 경구흡수를 보장하진 않습니다(규칙일 뿐).
- **EST001(용해도), EST002(투과도)는 confidence=low.** logP·TPSA로 물성을
  근사할 뿐이고, 실측과 다를 수 있습니다. **실측값이 있으면 무조건 우선**하며,
  단독으로 BCS를 확정하면 안 됩니다.

### 투과도 처리 — BCS 파일에서 미뤄둔 문제의 해결 지점

BCS 작업 때 "투과도는 RDKit로 신뢰성 있게 안 나온다"고 지적했습니다.
그 처리를 EST002에 명시했습니다: **confidence=low, action_if_low_confidence=
ESCALATE_TO_HUMAN**. 즉 투과도가 분류를 좌우하는데 실측이 없으면,
시스템이 임의로 확정하지 않고 사람에게 넘깁니다. 아세트아미노펜처럼
경계선(BA 88%) 약물에서 특히 중요합니다.

### max_dose는 자연어에서 파싱해야 함 (EST003)

용량:용해도比 계산에는 최고 용량(mg)이 필요합니다. 이건 SMILES에 없고
**자연어 요구사항에서 파싱**해야 합니다("소아용 500 mg 정제" → max_dose=500).
자연어 파싱이 실패하거나 용량 미지정이면 이 계산도 못 하므로,
입력 요구사항 처리 단계에서 용량 추출이 선행되어야 합니다.

## 5. 자연어 요구사항과의 결합

이 시스템 입력은 SMILES(구조) + 자연어(요구사항) 두 갈래입니다.
이 세 파일은 **SMILES 쪽**을 처리합니다. 자연어 쪽(대상 연령, 향미, 용량,
제형 형태 등)은 별도 파싱이 필요하며, 그 결과가 이 물성 프로파일과 **합쳐져야**
비로소 하위 규칙의 입력이 완성됩니다. 예:

- SMILES → `has_primary_amine=true` (이 파일)
- 자연어 "소아용" → `target_population=pediatric` (자연어 파서)
- 두 개가 합쳐져야 → pediatric_safety + incompatibility 규칙이 제대로 발동

자연어 파싱 규칙은 이 CSV 체계 밖(에이전트 프롬프트/LLM 영역)이며,
개발자가 이 경계를 명확히 인지해야 합니다. **물성은 결정론적 계산,
요구사항 해석은 LLM 판단** — 슬라이드 4의 "숫자 판단 vs 맥락 판단" 분리가
입력 단계에서부터 적용됩니다.

## 6. 구현 시 유의점 정리

1. **계산/추정 구분 유지.** ①②는 결정론적, ③의 용해도·투과도는 저신뢰 추정.
2. **SMARTS 전량 검증 필요.** UNTESTED 상태. 양성/음성 사례로 테스트 후 사용.
3. **염 형태 전처리.** HCl salt 등은 parent 구조 추출 후 SMARTS 적용(fluoxetine HCl 사례).
4. **실측 우선.** solubility/permeability 실측값이 있으면 추정을 override.
5. **저신뢰→에스컬레이션.** 투과도 등 confidence=low가 분류를 좌우하면 사람에게.
6. **max_dose 자연어 파싱.** 용량:용해도比에 필요. SMILES에 없음.
7. **아미드 상호배제.** FLG001 ∧ ¬FLG005 검증으로 아세트아미노펜 오탐 방지.

## 7. 참고 문헌

1. **RDKit Documentation** — Getting Started / `rdkit.Chem.Descriptors` / `rdkit.Chem.rdMolDescriptors` 모듈. https://www.rdkit.org/docs/ — 파일 ①의 함수명·모듈·반환형. 2026-07-24 확인(핵심 함수는 2025.03과 동일, 안정적).
2. **Lipinski CA, et al. Experimental and computational approaches to estimate solubility and permeability in drug discovery and development settings.** Adv Drug Deliv Rev. 1997;23:3–25. — EST004 Rule of Five.
3. **Veber DF, et al. Molecular properties that influence the oral bioavailability of drug candidates.** J Med Chem. 2002;45:2615–23. — EST005 (RotB≤10, TPSA≤140).
4. **Wildman SA, Crippen GM. Prediction of physicochemical parameters by atomic contributions.** J Chem Inf Comput Sci. 1999;39:868–73. — MolLogP 계산 기반.
5. **Ertl P, et al. Fast calculation of molecular polar surface area.** J Med Chem. 2000;43:3714–7. — TPSA 계산 기반.
6. **ICH M9** (앞서 확보) — EST003의 250 mL 기준.

**주의:** SMARTS 패턴(파일 ②)은 문헌이 아니라 제가 작성한 것으로, 출처가 아니라
**검증 대상**입니다. 물성 추정 로직(파일 ③의 EST001/002)은 QSPR 일반 원리에
기반한 근사이며 특정 검증된 모델이 아닙니다. 정량 예측이 필요하면
전용 용해도/투과도 예측 모델(예: 별도 ML 모델) 도입을 검토하십시오.
