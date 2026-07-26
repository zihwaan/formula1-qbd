# incompatibility_1to1.csv — 출처 및 설계 문서

## 1. 이 파일의 상태

15행 × 20컬럼. **소아 안전 파일과 달리 검증 강도가 균일하지 않습니다.**
규제 문서(EMA Annex)는 단일 공식 문서에 임계값이 명시되지만,
배합금기는 개별 연구 논문에 흩어져 있어 성격이 다릅니다.

| verification_status | 행 수 | 의미 |
|---|---|---|
| `VERIFIED_PRIMARY` | 4 | 1차 문헌 원문(또는 동등 수준) 확인 |
| `VERIFIED_SECONDARY` | 8 | 동료심사 리뷰 논문에서 확인, 원논문 미대조 |
| `INFERRED` | 1 | 물질 계열로부터 추론, 개별 데이터 없음 |
| `UNVERIFIED` | 2 | 출처 미확보 (HPE 대조 필요) |

`evidence_strength`(strong/moderate/weak) 컬럼을 별도로 둔 이유는,
**`HARD_FAIL`은 weak 근거로 내릴 수 없다**는 제약을 데이터로 강제하기 위해서입니다.
빌드 시 검증했고, weak 근거의 HARD_FAIL은 0건입니다.

## 2. 조사 결과 설계가 바뀐 지점 3가지

### 2.1 ⚠ "1차 아민만 위험"은 틀렸습니다

중간발표 시나리오는 "Lactose–Amine group의 마이야르 반응"으로만 서술돼 있는데,
문헌 확인 결과 **2차 아민도 제약학적으로 유의한 조건에서 유당과 Maillard 반응을 일으킵니다.**
Fluoxetine HCl이 대표 사례이며, 해당 연구는 2차 아민 약물도 1차 아민과 마찬가지로
부형제 선택과 안정성 프로토콜에서 고려해야 한다고 결론짓습니다.

따라서 SMARTS 패턴을 1차 아민(`[NX3;H2;!$(NC=O)]`)만 잡도록 구현하면
**2차 아민 API를 통과시키는 위양성 통과(false pass)가 발생합니다.**
INC002로 2차 아민 규칙을 별도 추가했습니다.

### 2.2 ⚠ MCC를 "안전한 대체품"으로 단정하면 안 됩니다

MCC는 비환원성이라 유당의 표준 대체품으로 쓰이지만, 로트에 따라 **포도당 불순물**이
존재합니다. Vigabatrin 정제가 Avicel 유래 포도당 때문에 갈변한 사례,
그리고 어떤 MCC 로트에서 약 40 ppm의 포도당이 검출되어 캡슐 과립이 변색된 사례가 보고돼 있습니다.

이건 시스템 설계에 직접 영향을 줍니다. 반성 에이전트가 "유당 → MCC로 교체"를
자동 제안하고 그것을 통과시키면, 실제로는 여전히 Maillard 위험이 남습니다.
INC007을 `REVIEWER_FLAG`로 두어, MCC 교체 시에도 로트별 환원당 불순물 관리를
심사관이 확인하도록 했습니다. **시연에서 이 부분을 보여주면 "규칙이 단순 치환이 아니라
잔여 위험까지 추적한다"는 설득력 있는 근거가 됩니다.**

### 2.3 마그네슘 스테아레이트는 Hard Fail이 아니라 심사관 판단

기존 문서 초안에서는 "활택제 속 금속이온이 강산성 약물의 가수분해를 촉진"을
배합금기로 기술했는데, 문헌상 이 효과는 **농도 의존적**입니다.
마그네슘 스테아레이트가 microenvironmental pH를 높여 알칼리 조건을 만들고
아스피린 같은 수분 민감 약물의 가수분해를 가속하되, 그 속도는 배합 중 농도에 따라 달라집니다.
분해산물로 salicylic acid, salicylsalicylic acid, acetylsalicylsalicylic acid가 확인됩니다.

농도 의존적이면 이분법적 Hard Fail이 부적절합니다. `REVIEWER_FLAG`로 두고
대체품으로 **스테아르산**을 지정했는데, 동일 리뷰에서 스테아르산은 오히려
아스피린을 분해로부터 보호한다고 보고되기 때문입니다.

## 3. 구현 시 유의점

### 3.1 SMARTS 패턴은 검증이 필요합니다

`api_smarts` 컬럼의 패턴은 제가 작성한 것이며 **RDKit으로 실제 테스트하지 않았습니다.**
`[NX3;H2;!$(NC=O)]`는 아미드 질소를 제외한 1차 아민을 의도한 것이지만,
방향족 아민·양성자화된 아민염·zwitterion 처리는 별도 검토가 필요합니다.
특히 **염 형태(HCl salt 등)로 입력되는 API가 많으므로 중화/parent 구조 추출 전처리**가 필수입니다.
Fluoxetine HCl 사례가 정확히 이 경우입니다.

구현 시 반드시 알려진 양성/음성 사례로 테스트하십시오:
- 양성이어야 함: fluoxetine(2차), aminophylline(1차, ethylenediamine 부분), vigabatrin(1차)
- 음성이어야 함: acetaminophen(아미드 질소, Maillard 비반응성)

**중요:** 데모 시나리오의 acetaminophen은 아미드(acetamido)이지 1차 아민이 아닙니다.
기존 시나리오 문서에 "아세트아미노펜이 지닌 아민기가 유당과 만나면"이라고 서술돼 있는데,
이는 화학적으로 부정확합니다. 심사위원이 약제학 전공자라면 지적할 가능성이 높습니다.
데모 API를 실제 1차 아민 약물로 바꾸거나, 반려 사유를 아스파탐-PKU 쪽으로
옮기는 편이 안전합니다.

### 3.2 aggravating_factors는 현재 판정에 쓰이지 않습니다

`aggravating_factors` 컬럼(고온, 수분, 알칼리 pH, 낮은 drug loading)은
문헌에서 확인된 반응 촉진 인자를 기록한 것이지만, 현재 규칙 엔진은
이를 수치로 평가하지 않습니다. 향후 안정성 조건(ICH Q1A)과 연동하면
"가속시험 조건에서만 문제되는가"를 구분할 수 있습니다.

### 3.3 UNVERIFIED 2행은 사용 금지

INC010(인산수소칼슘), INC011(탄산수소나트륨)은 제제학 일반 지식으로 기술했으나
출처를 확보하지 못했습니다. HPE 각조에서 표면 pH와 배합금기를 확인한 뒤
`evidence_type`/`source_citation`을 갱신하기 전까지는 엔진에서 제외하십시오.

## 4. 참고 문헌

1. **Narang AS, Desai D, Badawy S. Impact of Excipient Interactions on Solid Dosage Form Stability / Reactive Impurities in Excipients: Profiling, Identification and Mitigation of Drug–Excipient Incompatibility.** AAPS PharmSciTech (2012). PMC3225520. — INC001, INC005, INC006, INC007의 근거. **원문 전문은 CAPTCHA로 접근하지 못했고 검색 스니펫 수준에서 확인했습니다.** 본선 전 원문 확보 권장.
2. **Wirth DD, Baertschi SW, Johnson RA, et al. Maillard reaction of lactose and fluoxetine hydrochloride, a secondary amine.** J Pharm Sci. 1998;87(1):31–9. — INC002의 근거. 2차 아민의 Maillard 반응성.
3. **Li J, Wu Y. Lubricants in Pharmaceutical Solid Dosage Forms.** Lubricants. 2014;2(1):21–43. doi:10.3390/lubricants2010021. — INC008, INC012, INC013, INC014의 근거. 오픈액세스로 원문 확인.
4. Janicki CA, Almond HR Jr. Reaction of haloperidol with 5-(hydroxymethyl)-2-furfuraldehyde, an impurity of anhydrous lactose. J Pharm Sci. 1974;63:41–3. — INC003. AAPS 리뷰의 참고문헌으로 확인, 원문 미대조.
5. Brownley CA, Lachman L. Browning of spray-processed lactose. J Pharm Sci. 1964;53:452–4. — INC004. 동일하게 참고문헌 수준 확인.
6. Rowe RC, Sheskey PJ, Quinn ME (eds.). *Handbook of Pharmaceutical Excipients*. Pharmaceutical Press/APhA. — INC010, INC011의 대조 대상. **미대조.**

---

# rulebook_config.csv — 설계 문서

## 1. 역할

문서 4.3절의 "규칙표가 들어올 때마다 알맞은 검사 방식에 자동 연결"을 구현하는 파일입니다.
21행으로 전체 룰북의 배선도 역할을 합니다.

## 2. judgment_type — 3+2 분류

| 값 | 행 수 | 의미 |
|---|---|---|
| `deterministic` | 15 | 계산기처럼 판정. AI 개입 없음 |
| `hybrid` | 3 | 수치 판정 + 심사관 맥락 판단 결합 |
| `escalation` | 1 | 에이전트 단독 판정 불가, 사람 필수 |
| `reference_table` | 1 | 판정 아님, 조회용 |
| `config` | 1 | 시스템 설정 |

`escalation`을 별도 타입으로 둔 것이 핵심입니다. 향료/색소 파일은
공급사 사양서 없이는 어떤 AI도 판정할 수 없으므로,
`requires_supplier_spec=yes`로 표시하고 아예 자동 판정 경로에서 제외합니다.

## 3. trigger_priority — 실행 순서

낮은 숫자가 먼저 실행됩니다.

- `0` 마스터 조회 (항상)
- `1` 공정 분기 결정 — 어떤 공정 규칙을 적용할지 먼저 정해져야 함
- `2` 배합금기 / 소아안전 / 향료 — **가장 비용이 낮고 치명적인 검사를 앞으로**
- `4~5` 공정 실패 검사
- `6~7` 생물약제학 / 규제 / 포장
- `99` 합의 도출

우선순위 2에 소아안전과 배합금기를 배치한 이유는, 이 둘이 Hard Fail 비중이 높고
계산 비용이 낮아 조기 반려로 하위 검사를 통째로 절약할 수 있기 때문입니다.
슬라이드 9의 "리소스 낭비 없이 빠른 평가"를 실제 실행 순서로 구현한 것입니다.

## 4. 중요 플래그 2개

- **`requires_patient_weight=yes`** — 소아안전 파일에만 해당. mg/kg 임계값이 있어
  환자 체중 없이는 판정 불가. 체중 미제공 시 `ESCALATE_TO_HUMAN` 폴백 필수.
- **`requires_supplier_spec=yes`** — 향료/색소 파일. 조성 미확인 시 자동 통과 금지.

## 5. 현재 상태

- `ACTIVE` 2건: `incompatibility_1to1.csv`, `pediatric_safety_rules.csv`
- `PARTIAL` 1건: `excipient_master.csv` (unii/iid 컬럼 미검증)
- `PLANNED` 18건: 미작성

예선 제안서에는 이 표를 그대로 넣고 "현재 2개 카테고리 실동작, 나머지는 스키마 확정"이라고
쓰는 편이 낫습니다. 320개 규칙을 다 채웠다고 주장하는 것보다,
**무엇이 검증됐고 무엇이 안 됐는지 구분해 제시하는 것이 기술적 실현 가능성 평가에서 유리합니다.**
