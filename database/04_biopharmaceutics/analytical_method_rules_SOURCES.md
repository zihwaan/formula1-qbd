# analytical_method_rules.csv — 출처 및 설계 문서

## 1. ⚠ 이 파일은 "판정"이 아니라 "제안"입니다

지금까지의 규칙 파일과 근본적으로 성격이 다릅니다.
`incompatibility_1to1.csv`는 "이 조합은 위험하다"를 **판정**하고,
`pediatric_safety_rules.csv`는 "이 용량은 초과다"를 **판정**합니다.

그러나 용출 시험 조건은 **원칙적으로 약물별 monograph가 지정**합니다.
USP <711> 전체에 "given in the individual monograph"라는 문구가 반복됩니다.
그렇다면 이 파일의 "이런 물성이면 이 장치를 써라"는 규칙은 무엇인가?

→ **monograph가 아직 없는 신약(개발 초기 API)을 위한 시험법 개발 가이드**입니다.
완성된 규격이 아니라 출발점 제안입니다.

그래서 config에서 이 파일만 `judgment_type = advisory`로 분류했고,
13개 규칙 **전부 `REVIEWER_FLAG`**입니다. Hard Fail이 하나도 없습니다.
장치를 잘못 골랐다고 처방이 반려되지는 않기 때문입니다.

### 판정 유형 6종 정리 (개발자 필독)

이 파일에서 `advisory`가 처음 등장하므로, 현재까지의 전체 판정 유형을 정리합니다:

| judgment_type | 의미 | 반려 가능? | 예시 파일 |
|---|---|---|---|
| `deterministic` | 계산기식 판정. 같은 입력→같은 출력 | O (Hard Fail) | incompatibility_1to1, pediatric_safety |
| `hybrid` | 수치 판정 + 심사관 맥락 판단 | O | bcs_strategy, dissolution_biowaiver |
| `advisory` | **제안만. 판정 아님** | X | **analytical_method_rules (이 파일)** |
| `reference_table` | 조회용 참조표 | X | excipient_master, powder_flow_scale |
| `escalation` | 에이전트 판정 불가, 사람 필수 | X(사람이) | coloring_flavoring_pediatric |
| `config` | 시스템 설정 | X | severity_scoring_config |

**중요:** 개발자가 이 파일을 다른 규칙 파일처럼 "통과/반려" 로직에 넣으면 안 됩니다.
출력은 "권장 시험 조건 + 근거"이며, 연구자에게 제안으로 전달됩니다.

## 2. monograph 우선 원칙

엔진 로직은 이 순서여야 합니다:

```
1. 해당 API의 공식 monograph(USP-NF, KP, EP)가 있는가?
   YES → monograph 조건 사용. 이 파일은 참고만.
   NO  → 이 파일의 advisory 규칙으로 초기 조건 제안 → 연구자 확정
```

이 파일이 monograph를 덮어쓰면 안 됩니다. 규격이 있는 약물에
개발 가이드를 적용하는 것은 오류입니다.

## 3. 내용 요약 (USP <1092> 기반)

### 장치 선택 (ANA001–004)

| 상황 | 권장 장치 | 근거 |
|---|---|---|
| 고형 경구 즉시방출 (기본) | 장치 2 (Paddle) | 가장 널리 사용 |
| 캡슐·부유 정제 | 장치 1 (Basket) | 부유 방지 |
| 비드형 방출조절 | 장치 3 (왕복실린더) | pH 순차 노출 |
| 난용성/방출조절+저용해 | 장치 4 (플로우스루셀) | 싱크 조건 유지 |

USP <1092>: 고형 경구제형은 장치 1·2가 최다 사용. 부적절 시 다른 장치 사용.
장치 3은 비드형 방출조절에 특히 유용, 장치 4는 난용성 방출조절에 유리.
**장치 3·4는 일본약전(JP) 미채택**이므로 국제 대응 시 주의.

### 매질·pH (ANA007–009)

- 고용해 약물: 0.1 N HCl / pH 4.5 / pH 6.8 각 900 mL로 프로파일 (바이오웨이버 3매질과 정렬)
- 일반 pH 범위: 1.1–6.8, 용해도 사유로 높일 수 있으나 통상 8.0 초과 금지
- 완충액 pH 매핑: HCl(1.0–3.0), glycine(2.0–3.0), citrate(2.5–3.5), acetate(4.0–5.5), phosphate(6.0–8.0)

### 싱크 조건·계면활성제 (ANA010–011)

- **싱크 조건 정의**: 매질 부피 ≥ 최고 용량 포화 용해 필요 부피의 **3배**.
  Dose/Solubility Ratio로 계산. `bcs_classification_criteria.csv`의 250 mL 기준과 개념적으로 연결됩니다.
- **싱크 미충족 시**: 계면활성제 도입, **1순위는 SDS(=SLS)**. 최소 유효 농도를
  프로파일링으로 정당화.

### ⚠ SLS 교차 주의 (ANA011 note)

계면활성제 1순위가 SDS(sodium dodecyl sulfate = sodium lauryl sulfate = SLS)입니다.
그런데 SLS는 `pediatric_safety_rules.csv`에서 이미 다룬 성분입니다.

**혼동 주의:** 여기서 SLS는 **시험 매질**에 넣는 것이고,
소아 안전에서 문제되는 SLS는 **제품 처방**에 들어가는 것입니다. 둘은 별개입니다.
시험 매질의 SLS가 환자에게 투여되지는 않습니다. 그러나 개발자가
"SLS 관련 규칙"을 한 곳에서 처리하려다 이 둘을 섞으면 안 됩니다.
용도(시험 매질 vs 제품 성분)를 구분하는 것이 중요합니다.

### 회전속도·부피·탈기 (ANA005–006, 012–013)

- 패들 기본 50 rpm(불충분 시 75), 바스켓 50–100 rpm
- 부피 통상 900 mL(범위 500–1000 mL, 싱크 위해 2–4 L 가능)
- 계면활성제 미함유 매질은 탈기(USP <711> 방식). 계면활성제 함유 매질은
  발포 때문에 통상 탈기 안 함.

**mildest suitable conditions 원칙:** 과도한 교반·계면활성제·극단적 pH는
제형 간 차이를 가릴 수 있으므로, 판별력을 유지하는 가장 온화한 조건을 택합니다.

## 4. 다른 파일과의 연결

```
bcs_classification_criteria.csv ──▶ 이 파일 (장치·매질 제안)
    (BCS class가 장치 선택 힌트)         │
                                        ▼
dissolution_apparatus_usp711.csv ◀── 장치 사양 참조
    (선택된 장치의 상세 스펙)            │
                                        ▼
dissolution_biowaiver_ichm9.csv / dissolution_acceptance_usp711.csv
    (실제 용출 판정)
```

이 파일은 "어떤 조건으로 시험할지 제안"하고, 실제 "판정"은 dissolution 파일들이
합니다. 제안(advisory)과 판정(deterministic/hybrid)의 분리가 핵심입니다.

## 5. 구현 시 유의점

1. **advisory는 통과/반려 로직에 넣지 말 것.** 출력은 제안이며 연구자에게 전달.
2. **monograph 우선.** 규격 있는 약물엔 이 파일 미적용.
3. **SLS 용도 구분.** 시험 매질 SLS ≠ 제품 성분 SLS.
4. **싱크 조건 계산은 Dose/Solubility Ratio 필요.** API 최고 용량과 각 pH 용해도 입력 필수.
5. **VERIFIED_SECONDARY 5행**은 USP <1092> 원문과 method development 문헌을
   함께 근거로 함. 관행적 수치(900 mL, 50 rpm 등)는 챕터 본문보다 실무 문헌에
   더 명확히 서술되어 있어 secondary로 표기.

## 6. 참고 문헌

1. **USP. General Chapter <1092> The Dissolution Procedure: Development and Validation.** — 장치 선택 기준(ANA001–004), 싱크 조건 정의(ANA010), 계면활성제 SDS 우선(ANA011), 매질 pH 범위(ANA008). https://www.uspnf.com/sites/default/files/usp_pdf/EN/USPNF/gc_1092.pdf **2026-07-24 원문 대조.**
2. **USP. General Chapter <711> Dissolution.** — 탈기(ANA013), 장치 사양. 앞서 dissolution 파일에서 확보한 동일 문서.
3. Dissolution method development 실무 문헌 (Industrial Pharmacist; pharmacores.com 등) — 관행적 수치(900 mL, 패들 50 rpm, 완충액 pH 매핑, 고용해 약물 3매질 프로파일)의 근거. **동료심사 논문이 아닌 실무 자료이므로 VERIFIED_SECONDARY.** 본선 전 USP <1092> 원문 및 제제학 교과서로 보강 권장.

**주의:** 확보한 USP <1092>는 현행판 기준이나, 판번호·개정일을 원문에서 명확히
확인하지 못했습니다(`source_version`에 챕터명만 기재). 본선 전 정확한 판번호와
개정일을 확인해 `source_version`/`retrieved_on`을 갱신하십시오.
