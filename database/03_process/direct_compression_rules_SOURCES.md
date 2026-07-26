# direct_compression_rules.csv — 출처 및 설계 문서

## 1. route 파일에서 미뤄둔 숙제를 여기서 처리한다

`route_decision_tree.csv` 작성 시 "압축성(compressibility)을 정량 판정할 기준이
아직 없다"고 남겨두었습니다. `api_compressibility`를 `adequate`/`poor`로만
표시하고 심사관에게 넘겼었죠. 이 파일이 그 정량 기준을 채웁니다.

핵심 지표는 **tabletability(인장강도 vs 압축압력)**입니다.

## 2. ⚠ 가장 중요한 구분 — 예측 가능 vs 실험 필요

안정성 파일과 같은 문제가 여기서도 핵심입니다. 직접타정 파라미터는 두 종류입니다:

| 종류 | 예시 | 설계 단계 예측? | 컬럼 |
|---|---|---|---|
| **분체 물성** | 유동성(Carr's index, Hausner) | 가능 (측정/추정) | `predictable_at_design=yes` |
| **타정 결과** | 인장강도, 고형분율, 압출력, 마손도 | **불가 (타정 실험 필요)** | `requires_experiment=yes` |

10개 규칙 중 **7개가 `requires_experiment=yes`**입니다. 즉 설계 단계에서
SMILES와 처방만으로는 판정할 수 없고, 실제로 정제를 찍어봐야 나옵니다.

이 구분을 흐리면 안 됩니다. 에이전트가 "이 처방은 인장강도 2 MPa 확보"라고
설계 단계에서 단언하면, 타정도 안 하고 결과를 지어내는 hallucination입니다.
인장강도는 처방·압축압력·펀치형상에 복합적으로 의존해서 계산으로 안 나옵니다.

### 설계 단계에서 할 수 있는 것

- **DC001~002 (유동성)**: 분체 물성이라 측정/추정 가능. route와 연계해 스크리닝.
- **DC010 (적용가능성 게이트)**: 유동성 양호 + 압축성 예측 양호 여부로 1차 선별.
  단 `predictable_at_design=partial` — 압축성은 실험 전 불확실하므로 심사관 판단.

### 실험 후에만 판정 가능한 것

- **DC003~007**: 인장강도, 고형분율, 압축압력, 압출력 — 전부 타정 실험 결과.
- **DC008~009**: 마손도, 함량균일성 — 약전 시험(완제품).

## 3. 정량 기준 (문헌 근거)

### 인장강도 (Tensile Strength) — 핵심 지표

| 값 | 의미 | 근거 |
|---|---|---|
| **≥ 1.7 MPa** | 통상 충분 (제조·유통 견딤) | Pitt & Heasley 2013; 다수 문헌 합의 |
| **≥ 2.0 MPa** | 견고한 제품 목표 | 마손도 통과, 붕해/용출 비저해 |
| ~1.0 MPa | 소량 배치엔 가능 | 큰 기계적 스트레스 없을 때 |

계산식: **TS = 2F/(π·D·T)** (Fell-Newton, 원형 평면정). F=파괴력, D=직경, T=두께.
이 식 자체는 결정론적이지만, **입력 F(파괴력)는 타정 후 측정값**입니다.

### 압축 압력 (Compaction Pressure)

**80~120 MPa**가 최적 tabletability 범위입니다. <80 MPa면 정제가 제대로
형성되지 않고, >120 MPa면 과압축(캡핑/라미네이션)이 발생합니다.
단 저용량 API 정제는 100~200 MPa도 흔하므로 제형별로 다릅니다(DC005 note).

### 고형분율 (Solid Fraction)

**0.85 ± 0.05**가 최적. SF = 정제밀도/진밀도. 공기:고체 비율을 나타냅니다.

### 배출 전단응력 (Ejection Shear Stress)

**3 MPa 초과** 시 캡핑/라미네이션 결함 위험. 활택제로 개선.

## 4. action 배정 논리

- **DC008(마손도), DC009(함량균일성)은 HARD_FAIL** — 약전 규격 위반은 명확한 반려.
- **나머지는 REVIEWER_FLAG** — 인장강도·압축압력 등은 목표값이지 절대 컷오프가
  아니고, 처방·공정 조정으로 개선 가능하므로 맥락 판단이 맞습니다.

특히 인장강도를 Hard Fail로 두지 않은 이유: 1.7 MPa 미달이라도 압축압력을
높이거나 결합제를 조정해 개선할 수 있고, 소량 배치는 1.0 MPa로도 가능하기
때문입니다. 이분법 반려가 부적절합니다.

## 5. 다른 파일과의 연결

```
route_decision_tree.csv ──(DC 후보로 선택)──▶ direct_compression_rules.csv
    │ 유동성 판정                                 │
    ▼                                            ▼
powder_flow_scale.csv ◀──(DC001-002 참조)      DC003-007: 타정 실험 후 판정
                                                DC008-009: 약전 QC
                                                   │
                                                   ▼ (용출은)
                                        dissolution_acceptance_usp711.csv
```

- DC001~002(유동성)는 `powder_flow_scale.csv`(USP <1174>)를 참조합니다.
  route와 판정이 겹치므로, 엔진에서 중복 실행되지 않도록 주의(route가 먼저).
- 용출 관련은 `dissolution_acceptance_usp711.csv`로 이어집니다.

## 6. ⚠ route와의 중복 주의

DC001~002(유동성)는 `route_decision_tree.csv`의 RTE001~003과 판정 대상이
겹칩니다. 둘 다 유동성으로 직접타정 적합성을 봅니다. 차이는:

- **route**: "어떤 공정을 시도할지" 결정 (공정 선택)
- **direct_compression**: "직접타정을 선택했을 때 세부 기준" (공정 내 판정)

엔진에서 route가 먼저 실행되어 DC를 후보로 확정한 뒤, 이 파일이 세부 판정을
합니다. 유동성 판정이 두 번 실행되지 않도록, route 결과를 이 파일이
재사용하는 것이 좋습니다. `rulebook_config.csv`의 trigger_priority가
route(1) < process(4)로 순서를 보장합니다.

## 7. 구현 시 유의점

1. **requires_experiment=yes 규칙은 설계 단계에서 "예측"만.** 판정은 실측 후.
2. **인장강도 계산식의 F는 측정값.** 계산으로 안 나옴. 타정 필수.
3. **유동성은 route와 중복.** route 먼저 실행, 결과 재사용.
4. **HARD_FAIL은 약전 규격(마손도·함량균일성)만.** 인장강도 등은 REVIEWER_FLAG.
5. **압축압력 범위는 제형 의존.** 80-120은 일반값, 저용량 API는 100-200 흔함.
6. **DC010 게이트가 설계 단계 진입점.** 여기 통과해도 DC003-009는 실험 후 재검.

## 8. 참고 문헌

1. **Pitt KG, Heasley MG. Determination of the tensile strength of elongated tablets.** Powder Technol. 2013. — 인장강도 1.7 MPa 및 2 MPa 기준(DC003~004)의 핵심 근거. 여러 후속 문헌이 이를 인용.
2. **Fell JT, Newton JM.** 인장강도 계산식 TS=2F/(πDT)의 원 출처(원형 평면정).
3. Compression prediction accuracy from small scale compaction studies to production presses. Powder Technol. 2013 (ScienceDirect) — 고형분율 0.85±0.05(DC006), 배출 전단응력 3 MPa(DC007) 근거.
4. Natoli Engineering / Merlin PC. Tabletability whitepaper — 압축압력 80~120 MPa 범위(DC005). **업계 기술자료(VERIFIED_SECONDARY).**
5. Hancock BC, et al. The relative densities of pharmaceutical powders, blends, dry granulations and immediate-release tablets. Pharm Technol. — 고형분율.
6. USP <1216> Tablet Friability (DC008), USP <905> Uniformity of Dosage Units (DC009) — **원문 미대조**. 통상 기준으로 기재했으므로 본선 전 약전 원문 대조 필요.

**주의:** 인장강도·압축압력 임계값은 동료심사 문헌과 업계 자료가 혼재합니다.
1.7/2.0 MPa는 문헌 합의가 강하지만(strong), 압축압력 80-120이나 고형분율은
자료에 따라 편차가 있어 moderate/secondary로 표기했습니다. 또 이 값들은
**제형·API·부형제에 크게 의존**하므로, 절대 기준이 아니라 출발점으로
다뤄야 합니다. USP <1216>/<905>는 원문 대조가 필요합니다.
