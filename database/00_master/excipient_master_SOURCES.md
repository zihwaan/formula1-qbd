# excipient_master.csv — 출처 및 검증 대장 (v2, 100행)

## 1. 이 파일의 상태

100행 × 26컬럼. **컬럼별로 신뢰도가 다릅니다.** 일괄 취급하면 안 됩니다.

| 컬럼군 | 상태 | 출처 |
|---|---|---|
| `ema_annex_listed`, `ema_annex_threshold`, `ema_annex_concern` | **1차 출처 원문 대조 완료** (35행) | EMA/CHMP/302620/2017 corr.1 Annex 전문 |
| `functional_category`, `secondary_function`, `process_compatibility`, `reducing_sugar`, `hygroscopic`, `alkaline_surface_ph`, `incompat_trigger` | 제제학 표준 지식 기반 분류 — 구조적으로 타당하나 HPE 각조 대조 필요 | HPE (미대조) |
| `unii`, `cas_number`, `typical_use_pct_min/max`, `iid_max_potency_mg`, `iid_max_potency_source_date` | **전량 `TO_VERIFY` (600셀)** | 조회 불가 |

`TO_VERIFY`가 600셀인 것은 결함이 아니라 의도입니다. UNII/CAS/IID 수치는
질의형 DB에서만 나오며, 기억으로 생성한 식별자는 형식이 완벽해 보이지만
전혀 다른 물질을 가리킬 수 있고 육안 검수로 잡히지 않습니다.

## 2. 이번 작업에서 실제로 한 일 — EMA Annex 전문 확보

**EMA/CHMP/302620/2017 corr.1 Annex 전문을 직접 받아 대조했습니다.**
따라서 `ema_annex_*` 3개 컬럼의 35개 행은 추정이 아니라 원문 대조 결과입니다. 예:

- 아스파탐(E 951), 경구, threshold Zero — 페닐알라닌 공급원, PKU에서 유해.
  **생후 12주 미만 영아에 대한 비임상·임상 데이터 모두 없음**
- 아조계 색소 6종(E 102/110/122/123/124/151), 경구, threshold Zero — 알레르기 반응 가능
- 만니톨(E 421), 경구, **10 g** — 완하 작용
- 소르비톨(E 420), 경구 5 mg/kg/day 및 140 mg/kg/day — HFI, 위장관 불편·완하
- 시클로덱스트린류, 전 경로 20 mg/kg/day / 경구 200 mg/kg/day — **2세 미만 사용 제한**
- 벤조산염(E 211/212), 경구·비경구 Zero — **생후 4주 이하 신생아 황달 악화, 핵황달 위험**
- 프로필렌글리콜(E 1520), 1 / 50 / 500 mg/kg/day 3단 임계값 — 신생아·5세 미만 제한
- 나트륨, 1일 최대용량 중 **17 mmol(391 mg)** 초과 시 'high sodium'
- 밀전분, 경구 Zero — 완제품 20 ppm 미만일 때만 'gluten-free' 표기 가능

이 값들은 **연령 조건부 수치 규칙**이라 결정론적 Hard Fail로 바로 구현 가능합니다.
`pediatric_safety_rules.csv`의 1차 재료가 여기서 확보된 셈입니다.

## 3. ⚠ 가장 중요한 발견 — SLS 10 mg의 근거가 EMA Annex에 없습니다

Annex 전문을 확인한 결과:

> **Sodium laurilsulfate — Route of Administration: Cutaneous — Threshold: Zero**
> 국소 피부 반응(따끔거림·작열감) 경고. 피부 두께가 부위·연령에 따라 다르고,
> 아토피 피부염 등 피부 장벽이 손상된 환자가 더 민감하다는 comment.

즉 **EMA Annex의 SLS 항목은 경피(cutaneous) 경로 전용이며, 경구 소아 mg 상한은 존재하지 않습니다.**
(참고로 corr.1에서 SLS의 E 487 표기가 삭제되었습니다.)

중간발표 슬라이드 12와 시나리오 문서의 핵심 데모인 "소아 SLS 상한 10 mg 초과 → Hard Fail"은
**현재 근거 문서가 없는 상태**입니다. 본선에서 "그 10 mg의 출처가 무엇입니까"라는 질문에
답하지 못하면, 시스템의 핵심 주장인 '규제 근거 기반 결정론적 판정' 자체가 무너집니다.
심사위원이 규제 전문가라면 거의 확실히 물어볼 지점입니다.

### 권고 — 데모 시나리오를 아스파탐-PKU로 교체

Annex에 명시된 항목으로 바꾸면 근거를 원문 그대로 제시할 수 있습니다.
소아용 정제라는 서사도 그대로 유지되고, 오히려 **두 종류의 Hard Fail을 동시에 보여줄 수 있어
데모로서 더 강력**합니다:

| 반려 사유 | 규칙 유형 | 근거 |
|---|---|---|
| ① Lactose × 아민기 API → Maillard | 구조 매칭 (화학) | HPE 배합금기 |
| ② Aspartame + PKU 소아 → 금기 | 절대 금기 (규제) | EMA Annex, threshold Zero |
| ②' 또는 12주 미만 영아 → 데이터 부재 | 연령 조건부 | EMA Annex comment |

기존 SLS 시나리오를 유지하려면 EMA STEP DB 또는 1차 문헌에서 경구 소아 SLS 노출 자료를
찾아 출처와 함께 기입해야 합니다. 찾지 못하면 **그 규칙은 Hard Fail이 아니라
Reviewer 판단 항목으로 강등**해야 맞습니다.

## 4. ⚠ 버전 관리 경고 — 확보한 Annex는 "Superseded" 표기본

받은 PDF 전 페이지에 `Superseded` 워터마크가 있습니다. 2017년 10월 9일 corr.1 판이고,
2019년 11월 22일 Rev.1(에탄올 업데이트 포함)로 갱신된 이력이 확인됩니다.
현재 시점(2026년 7월) 기준 최신판은 추가로 개정되었을 가능성이 높습니다.

따라서 CSV에 **`ema_annex_version` 컬럼을 추가하고 조회일자를 기록**하시길 권합니다.
규제 데이터를 '한 번 채우고 끝'으로 다루면 시간이 지나며 조용히 틀려집니다.
슬라이드 8에서 "전문가가 직접 검수·추가 가능한 데이터 형태"를 강조하셨는데,
버전·조회일자 컬럼이 그 주장을 실제로 뒷받침하는 장치가 됩니다.

## 5. `UNVERIFIED_CRITICAL` 6행 — 규칙 엔진 투입 금지

| ID | 성분 | 사유 |
|---|---|---|
| EXC045 | Sodium lauryl sulfate | 경구 소아 상한 근거 없음 (위 3절) |
| EXC059 | Titanium dioxide (E 171) | 2017 Annex 미수록. EU 규제 지위가 변동되어 왔으므로 대상 시장별 확인 필수 |
| EXC089–091 | 바나나향·딸기향·페퍼민트향 | 향료는 **독점 조성 혼합물**. 구성 알레르겐은 공급사 사양서로만 확정 가능하며 추정 금지 |
| EXC097 | 대두레시틴 | Annex의 soya oil 금기 문구 적용 여부가 원료 유래에 따라 달라짐 |

향료 3종을 이렇게 표시한 이유가 중요합니다. 데모가 "바나나향 소아 정제"인데,
향료 조성을 모르면 그 안에 Annex 부록의 26종 향료 알레르겐(cinnamal, eugenol, linalool,
coumarin, citral 등)이 들어 있는지 판정할 수 없습니다.
**에이전트가 "향료 안전함"이라고 판정하면 그것이 곧 hallucination입니다.**
올바른 동작은 "공급사 사양서 필요 → 사람에게 에스컬레이션"이며,
이는 제안서 평가 기준의 "AI가 언제 사람에게 확인을 요청하는가"에 대한 좋은 실증 사례가 됩니다.

## 6. 규칙 엔진 구현 시 유의점

- `iid_max_potency_mg`를 **1일 상한으로 직접 쓰면 안 됩니다.** IID 값은 제형 단위당
  최고 함량이며, 1일 최대 용량이 1단위일 때만 MDI와 일치합니다. MDD 환산 로직 필요.
- **소아 수치는 IID에서 오면 안 됩니다.** FDA가 IID는 소아 안전성·연령별 노출 모델을
  제공하지 않는다고 명시합니다. STEP DB 또는 EMA Annex(본 파일에 반영됨)에서 가져오세요.
- `ema_annex_threshold`는 현재 **문자열**입니다(`"Zero; 5 g"`, `"1 mg/kg/day; 50 mg/kg/day"`).
  기계 판정을 위해서는 `threshold_value` / `threshold_unit` / `age_condition`로 정규화한
  파생 테이블이 필요합니다. 이 정규화 자체를 `pediatric_safety_rules.csv`로 분리하는 것을 권합니다.
- `verification_status != VERIFIED` 행이 Hard Fail 판정에 사용되면 엔진이 경고를
  발생시키도록 구현하세요. 미검증 데이터가 조용히 통과 판정에 쓰이는 것을 막는 안전장치입니다.
- `incompat_trigger`는 세미콜론 다중값이며 `incompatibility_1to1.csv`의 조인 키입니다.
  현재 정의된 트리거: `maillard_amine`(5행), `azo_dye`(6행), `sodium_load`(11행),
  `acid_labile_api`, `paraben_allergy`, `sulphite_hypersensitivity`, `neonate_jaundice`,
  `pku_contraindication`, `soya_allergy`, `flavor_composition_unknown`, `overblend_risk`

## 7. 참고 문헌

1. **EMA/CHMP. Annex to the European Commission guideline on 'Excipients in the labelling and package leaflet of medicinal products for human use' (SANTE-2017-11668).** EMA/CHMP/302620/2017 corr.1, 9 October 2017 (Corrigendum 19/11/2018). — 본 파일 `ema_annex_*` 컬럼 전량의 출처. **※ 확보본은 Superseded 표기이며 2019-11-22 Rev.1 이후 개정 확인 필요.**
2. FDA. *Using the Inactive Ingredient Database — Guidance for Industry (Draft)*, Docket FDA-2019-D-2397. https://www.fda.gov/media/128687/download — max potency와 MDI의 차이, 소아 정보 미제공 명시.
3. FDA. *Inactive Ingredient Database (IID)*. — `unii`, `iid_max_potency_mg` 조회처 (미조회).
4. EMA. STEP (Safety and Toxicity of Excipients for Paediatrics) Database. — SLS 등 소아 노출 자료 조회처 (미조회).
5. EMA. *Guideline on pharmaceutical development of medicines for paediatric use*, EMA/CHMP/QWP/805880/2012 Rev.2. — 소아 제제 개발 일반 원칙 (미조회).
6. Rowe, R.C., Sheskey, P.J., Quinn, M.E. (eds.). *Handbook of Pharmaceutical Excipients*. Pharmaceutical Press / APhA. — 기능 분류·사용 농도·물성 컬럼의 대조 대상 (**본 작업에서 원문 미대조**).
7. EDQM. *European Pharmacopoeia* / 식품의약품안전처. *대한민국약전*. — 각조 규격 (미대조).
