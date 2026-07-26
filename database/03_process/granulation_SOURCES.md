# 과립화 3종 + 잔류용매 — 출처 및 설계 문서 (4개 파일)

## 1. 공정 3종의 관계 — route와 대칭

직접타정(DC)과 함께, 고형 경구제형의 4대 제조 경로를 이룹니다.
`route_decision_tree.csv`가 이 중 무엇을 시도할지 결정하고, 각 파일이 세부 판정합니다.

| 공정 | 파일 | 핵심 적응증 | 물/열 노출 |
|---|---|---|---|
| 직접타정 (DC) | direct_compression_rules | 유동성·압축성 양호 | 없음 |
| **건식과립 (DG)** | dry_granulation_rules | **수분/열 민감 + 유동성 개선 필요** | 없음 |
| **수계 습식과립 (WGA)** | wet_granulation_aqueous | 소수성·저용량, 수분/열 안정 | **물+열** |
| **비수계 습식과립 (WGN)** | wet_granulation_nonaqueous | 가수분해 민감하나 유기용매 안정 | 유기용매 |

### 공정 선택의 물성 분기 (route와 연동)

```
수분/열 민감?
  ├─ YES → DG (액체·열 없음) ◀── 주 적응증
  │         또는 WGN (물 대신 유기용매, 가수분해 회피)
  └─ NO  → 유동성/압축성 양호?
            ├─ YES → DC
            └─ NO  → WGA (유동성·함량균일성 개선)
```

각 파일의 `applicability_*` 규칙(DG001, WGA001, WGN001)이 이 분기를
`route_decision_tree.csv`의 RTE004/005(수분·열 민감 배제)와 연결합니다.

## 2. ⚠ 직접타정과 동일한 원칙 — 예측 vs 실험

과립화도 대부분 파라미터가 **실험을 해봐야** 나옵니다.
`requires_experiment=yes`가 대다수입니다.

- **설계 단계 예측 가능**: 공정 적응증(수분/열 민감 여부), 용매 ICH class
- **실험 필요**: 리본 고형분율, 결합액량, LOD, 잔류용매, 과립 유동성

에이전트가 "리본 고형분율 0.72 확보" 같은 걸 설계 단계에서 단언하면
hallucination입니다. 롤러컴팩션을 실제로 돌려야 나오는 값입니다.

## 3. 건식과립 (dry_granulation_rules.csv, 6행)

롤러컴팩션(roll compaction) 기준입니다.

### 핵심 — 리본 고형분율 (DG002)

**리본 고형분율(ribbon solid fraction)이 가장 중요한 중간 CQA**입니다.
전형값 0.65~0.80이며, 후속 과립의 입도분포(granule size distribution)에
직접 영향을 줍니다. 단 처방·장비 의존이라 범위는 전형값일 뿐, 실측 필요합니다.

주요 CPP: 롤압력(roll pressure/specific compaction force, DG003), 롤갭(DG004),
밀 스크린 크기(DG005). 롤압력 증가 시 리본밀도·과립크기가 증가합니다.

### DG의 존재 이유 (DG006)

과립화 목적 자체가 **유동성 개선**입니다. DG006에서 과립 후 유동성을
`powder_flow_scale.csv` 기준으로 재평가하며, 개선이 안 되면 WGA를 고려합니다.

## 4. 수계 습식과립 (wet_granulation_aqueous_rules.csv, 6행)

### ⚠ 핵심 — 결합액량은 "고유 엔드포인트가 없다" (WGA002)

이게 습식과립의 근본 특성입니다. **결합액량(binder liquid amount)은 가장
중요한 파라미터이지만 고유한 엔드포인트가 없습니다.** 최적 종점이 원료의
용해도·표면적·입자 형상·크기에 의존해서, 처방마다 실험으로 찾아야 합니다.
Leuenberger 등의 계산식이 있으나 실험 확인이 필수입니다.

이건 결정론적 규칙으로 만들 수 없는 대표 사례입니다. 그래서 임계값 없이
`REVIEWER_FLAG` + `requires_experiment=yes`로 두었습니다.

기타: LOD(건조 후 감량, WGA003, 통상 ≤2%), 건조온도(API 열안정성 이내, WGA004),
과립 입도분포(WGA005), 과립 유동성(WGA006).

### 배제 조건 (WGA001)

수계는 물+건조(열) 노출이라 **수분/열 민감 API에서 EXCLUDE_ROUTE**입니다.
route의 RTE004/005와 일치합니다.

## 5. 비수계 습식과립 (wet_granulation_nonaqueous_rules.csv, 5행)

가수분해 민감 API에 물 대신 유기용매(에탄올 등) 결합액을 씁니다(WGN001).
수계의 대안이지만 **잔류용매 관리가 필수로 따라붙습니다.**

### 잔류용매가 유일한 HARD_FAIL (WGN003)

비수계 과립화의 결정적 제약입니다. 잔류용매가 ICH Q3C 한계를 초과하면
`HARD_FAIL`입니다. 이건 규제 위반이라 명확합니다. 단 실측(HS-GC)이 필요하고,
`residual_solvent_ich_q3c_rules.csv`를 참조합니다.

용매 선택(WGN002)에서 ICH Q3C Class 3(에탄올 등)를 우선하고 Class 1을 회피하며,
건조 완전성(WGN005)이 잔류용매 규제와 직결됩니다.

## 6. 잔류용매 (residual_solvent_ich_q3c_rules.csv, 8행)

ICH Q3C(R8) 기준입니다. 비수계 과립화·코팅 시 발동합니다.

### Class 체계

| Class | 성격 | 한계 | 예시 | action |
|---|---|---|---|---|
| 1 | 발암성/환경유해 | **회피** | 벤젠, 사염화탄소 | HARD_FAIL |
| 2 | 제한 (PDE 기반) | 개별 PDE | 메탄올 3000ppm, DCM 600ppm | REVIEWER_FLAG |
| 3 | 저독성 | 5000ppm(0.5%) | 에탄올, IPA, 아세톤 | REVIEWER_FLAG |
| 미분류 | 자료 부족 | 사례별 | — | ESCALATE_TO_HUMAN |

**Class 3(에탄올 등)는 5000 ppm 이하면 정당화 불필요**하고, Class 3만 쓰면
LOD 시험으로 대체 가능합니다. 그래서 비수계 과립에 에탄올이 1순위입니다.
Class 2는 Option 1(10 g/day 가정 고정 ppm) 또는 Option 2(실제 용량 기반 계산)로
한계를 정합니다.

### action 논리

- Class 1은 `HARD_FAIL`(회피 대상)
- Class 2·3은 `REVIEWER_FLAG`(한계 이하 확인 필요하나 조정 가능)
- 미분류는 `ESCALATE_TO_HUMAN`(독성 자료 없어 사람 판단)

실제 잔류용매 판정(WGN003)은 이 표를 참조하되, 실측값이 있어야 합니다.

## 7. 다른 파일과의 연결

```
route_decision_tree.csv (공정 선택)
    ├──▶ direct_compression_rules.csv
    ├──▶ dry_granulation_rules.csv ─────────┐
    ├──▶ wet_granulation_aqueous_rules.csv   │ 과립 후 유동성 →
    └──▶ wet_granulation_nonaqueous_rules ───┤   powder_flow_scale.csv 재적용
              │                              │
              ▼ (유기용매 사용시)             │
         residual_solvent_ich_q3c_rules.csv ◀┘
              │
              ▼ (WGN003 Hard Fail 판정에 사용)
```

- 세 공정 모두 과립 후 유동성을 `powder_flow_scale.csv`로 재평가.
- WGN → residual_solvent로 필수 연결.
- 열민감 관련은 `structural_flags_smarts.csv`·`physchem_estimation_rules.csv`의
  API 플래그가 공정 적응증 판정의 입력이 됩니다.

## 8. 구현 시 유의점

1. **결합액량·리본SF 등은 실험 필요.** 설계 단계 예측만, 판정은 실측 후.
2. **결합액량은 고유 엔드포인트 없음.** 처방별 실험 결정. 계산식은 참고.
3. **WGN이면 residual_solvent 필수 발동.** 유기용매 사용 = 잔류용매 검사 의무.
4. **Class 1 용매 HARD_FAIL.** Class 3만 쓰면 LOD 대체 가능.
5. **잔류용매·건조온도는 API 안정성 의존.** 열/가수분해 민감 플래그와 연동.
6. **과립 후 유동성은 powder_flow_scale 재사용.** DC와 동일 기준.

## 9. 참고 문헌

1. **ICH. Q3C(R8) Impurities: Guideline for Residual Solvents.** Step 4, 2021-04-22. https://database.ich.org/sites/default/files/ICH_Q3C-R8_Guideline_Step4_2021_0422_1.pdf — 잔류용매 파일 전량. Class 분류, Option 1/2, Class 3 일반한계 5000 ppm. **2026-07-24 확인.** ※현재 최신은 R9(EMA 공개)이므로 본선 전 R9 대조 권장.
2. Reimer HL, Kleinebudde P. Hybrid modeling of roll compaction. Powder Technol. 2019 — 리본 고형분율, SCF(DG002~003).
3. Roll compaction/dry granulation 공정 파라미터 연구 (PMC7679258, PMC5261554) — 롤압력·갭·스크린(DG003~005).
4. Compression Density / Wet granulation endpoint 연구 (PMC9693446) — 결합액량 고유 엔드포인트 부재(WGA002), Leuenberger 식.
5. 제제 기술 문헌 (Bora CDMO, PharmaNow, European Pharmaceutical Manufacturer) — 롤러컴팩션 실무 파라미터. **업계 자료(VERIFIED_SECONDARY).**

**주의:** 과립화 수치 임계값(리본SF 0.65-0.80, LOD ≤2% 등)은 **처방·장비
의존성이 매우 커서 절대 기준이 아닙니다.** 전형값·출발점으로만 다뤄야 하며,
동료심사 문헌과 업계 자료가 혼재해 evidence_strength를 구분 표기했습니다.
ICH Q3C는 R9가 최신이므로 잔류용매 한계는 본선 전 재확인 권장(단 에탄올 등
Class 3 일반한계 5000 ppm은 오래 안정적).
