# 마지막 3개 파일 — 출처 요약

토큰 절약을 위해 3개를 한 문서로, 간략히 정리합니다.

## incompatibility_multicomponent.csv (02, 6행)

1:1로는 안 잡히는 **다성분(3+) 상호작용**. INC 시리즈와 상보적.

- **MC001 (핵심)**: amine'염' + 환원당 + 알칼리활택제. 아민염은 염 상태선 안정하나,
  Mg stearate가 유리염기를 방출시켜 Maillard 촉발. → HARD_FAIL. (Castello & Mattocks 1962)
- **MC002**: amlodipine besylate가 lactose+Mg stearate+water 다성분에서 불안정
  (glycosyl 분해물, HPLC-MS 확인). 이원 1:1은 안정. → HARD_FAIL. (Omari et al.)
- MC003~006: 흡습 매개 가수분해, 카복실산-폴리올 에스터화, Michael 부가, 술폰화. REVIEWER_FLAG.

검증: 전부 VERIFIED_SECONDARY (리뷰 논문 확인, 원논문 미대조).
**중요 함의**: 반성 에이전트가 "유당→만니톨" 치환해도, 활택제·수분이 남으면
다른 다성분 위험이 잔존. 1:1 통과 ≠ 다성분 안전.

## packaging_compatibility_rules.csv (05, 5행)

제품 물성 플래그 → 포장 요건. 전부 REVIEWER_FLAG.
흡습(PK001), 차광(PK002), 반투과 물손실(PK003), 산소민감(PK004), 소아CRC(PK005).
- PK003은 ICH Q1A(R2) 2.2.7.3 (stability_storage semi_permeable와 직결, VERIFIED).
- 나머지는 제제/규제 일반 (VERIFIED_SECONDARY).
- 입력: excipient_master.hygroscopic, structural_flags, physchem 플래그.

## coloring_flavoring_pediatric_rules.csv (05, 10행)

대부분 EMA Annex Rev.2 기존 확보자료 (pediatric_safety와 색소/향미 관점 중복 뷰).

- CF001~006: 아조색소 6종 → LABEL_REQUIRED (알레르기 경고).
- CF007: 이산화티타늄 → ESCALATE (EU 규제 변동, excipient_master EXC059와 동일).
- CF008: 아스파탐 → HARD_FAIL (PKU, PED001과 동일).
- **CF009 (핵심): 향료 알레르겐 → ESCALATE_TO_HUMAN.** 향료는 독점조성,
  26종 알레르겐 포함 여부를 공급사 사양서로만 확인 가능. 에이전트 단독판정 불가.
- CF010: 폴리올 감미제 완하작용.

검증: EMA Annex 유래는 VERIFIED, 이산화티타늄/향료는 미검증(별도 표기).

## 출처
- Castello RA, Mattocks AM. J Pharm Sci 1962 (아민염 무반응, MC001)
- Omari et al. amlodipine besylate 다성분 불안정 (MC002)
- Interactions and incompatibilities of pharmaceutical excipients review (MC003~006)
- ICH Q1A(R2) 2.2.7.3 (PK003), ICH Q1B (PK002)
- EMA/CHMP/302620/2017 Rev.2 (CF 시리즈)

주의: 다성분·포장 수치는 처방/지역 의존성이 크고 대부분 secondary 근거.
향료(CF009)는 반드시 사람 확인 경로 유지.
