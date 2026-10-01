# 브라우저 검증

pytest는 검사 엔진을 고정하고, 여기 두 스크립트는 **실제 브라우저에서 화면이 동작하는지**를
고정한다. 이 계층이 없어서 "모달이 안 닫히고 대시보드 전체가 클릭 불가"인 상태가
curl 검증만 통과한 채 배포된 적이 있다.

```bash
(cd tests/browser && npm i)      # 반드시 이 디렉토리 안에서. 위에서 실행하면 npm이
                                 # 상위로 올라가 ~/zihwan/package.json 을 고친다(실제로 겪음).
CHROME=<chrome 실행 파일 경로> node tests/browser/verify.mjs    http://localhost:8000/
CHROME=<chrome 실행 파일 경로> node tests/browser/audit.mjs     http://localhost:8000/
F1_LLM=dacon CHROME=<chrome 실행 파일 경로> node tests/browser/evidence.mjs  http://localhost:8000/
CHROME=<chrome 실행 파일 경로> node tests/browser/scenarios.mjs http://localhost:8000/
CHROME=<chrome 실행 파일 경로> node tests/browser/agent.mjs     http://localhost:8000/
CHROME=<chrome 실행 파일 경로> node tests/browser/stage2.mjs    http://localhost:8000/
```

화면은 대화 하나다 — 처음엔 가운데 입력칸(`#hello #agent-form`), 첫 메시지 뒤 아래로 내려간다. 1단계 카드(`#card-inputs` → `#panel-chem` →
`#drq` → `#panel-cands`)는 `flow.js`가 `#agent-log`에 순서대로 옮겨 놓으므로, 테스트는 `#agent-log #...`로 존재와 순서를 확인한다.
직접 입력 폼은 `#manual-open` → 시트(`#manual-sheet`), 그래프·해설·트레이스는 오른쪽 서랍(`.rail-tab[data-pane]`).
무료 Groq의 일일 토큰 한도가 바닥나면 후보가 비어 scenarios/agent가 실패한다 — `F1_LLM=dacon`(로컬 컨테이너에 대회 키)으로 같은 흐름을 확인한다.

맥이면 `CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"` 를 그대로 쓰면 된다.

- `verify.mjs` — 상호작용 회귀: 설명 오버레이 열기/닫기/ESC/배경클릭과 단계별 레이아웃, 직접 입력 시트 → 설계 실행 →
  대화에 요청 말풍선·물리화학 카드(가로)·데이터 요청(있으면 건너뛰기) → 후보 → 규칙 모달, 오른쪽 탭(흐름·해설·트레이스, 크게/닫기),
  테마 전환과 새로고침 유지, 모바일 뷰포트, 콘솔 오류 0건.
- `agent.mjs` — 가운데 입력칸 → 미완성 카드(용량 되묻기) → 완성 카드 밑 “실험 데이터값을 입력하시겠습니까?” + 입력 카드 →
  설계 실행 → 물리화학 → 데이터 요청 → 건너뛰기 → 후보 → 에이전트가 먼저 알림 → “1위 후보로 개발 착수” → (근거 결손이면 카드에 결손 · 승인 사유가 보이고 [실행] = 그 사유로 승인) →
  2단계 프로토타입 카드, XSS, 휴대폰.
- `evidence.mjs` — **근거 결손 게이트(발표 ⑤)**: 시연 카드 ① → 설계 종료 직후 데이터 요청보다 먼저 심사위원단 카드(심사관마다 후보별 점수·근거) →
  통과 후보마다 상태 한 줄과 소집 심사관 요약(반려 후보엔 없음, 입력 칸 없음) → 결손 후보 카드마다 승인 칸(기본 사유 · 비우면 막힘), 게이트 카드엔 안내만 → 후보 카드 다음에
  **게이트 카드 하나**(요구 항목별 한 번 · 확인시험 test_id · 해당 후보 · 등급 선택과 제출 버튼 하나, 적합/부적합 칸 없음) → 후보의 “입력 카드로”
  → 카드 폼에 흡수율만 → `/measurements`(source `evidence`) 재계산이 트레이스에 phase_gates부터 · BCS 근거는 아직 결손 · 칸 비워짐 ·
  후보 카드가 대화 맨 아래로 다시 →
  BCS 근거의 [말로 입력] → 에이전트에 pH별 용해도 문장 → 코드 계산이 보이는 제출 카드(source `agent_evidence`) → 실행 → 전략 집합이 바뀌면
  같은 게이트 카드가 새 후보로 다시 그려지고 새 후보도 심사(summon → judge → consensus, 카드·심사위원단에 점수) → EVR005 닫힘 · 해설 기록 → “이 후보로 개발 착수” → 사유 없이 2단계, Handoff에 근거 충족 기록,
  390px 넘침 0. `SHOTS=<dir>`이면 카드 스크린숏. 실제 LLM 필요(`F1_LLM=dacon`).
- `audit.mjs` — 상용 관점 점검: 6개 렌더 경로(트레이스·합의·후보·근거 상자·불가능 결론·물리화학)에 `<img onerror>` 주입(실행 0회여야 함),
  실행 중 이중 실행 차단, 규칙 기반 대체값 노출 여부, 원시 HTTP 오류 문구 노출,
  접근성 기본, 9개 화면폭 가로 오버플로.
- `scenarios.mjs` — 시연 카드를 누르면 요청 밑에 실험 데이터 입력 카드(시연 값 채워짐)가 놓이는지, 시연 카드 ②(암로디핀 + 유당 → INC001(·MC00x) → 후보 카드 맨 위에 제약 불가능 결론 · 대안 · 소집 예정 심사관 = 고령자 안전 + 공정 실현성)와 ③(VX-770 → DSC만 요청 → 입력칸의
  측정 문장을 보내면 제출 카드 → 재계산으로 ASD_SDD, 화면에 실명 없음)이 카드 문구대로 가는지. 실제 LLM이 필요하다 — 키 없이 돌리면
  "LLM 응답이 스키마를 만족하는지"를 검증하지 못한다. 요청 문자열이나 시나리오 흐름을 바꾸면 다시 돌려 주장하는 경로가 그대로인지 확인한다.
- `drq.mjs` — 데이터 요청 패널: 입력 칸이 필드 정의의 타입(숫자·예/아니오·선택지·목록)을 따르는지,
  VX-770 cold start에서 DSC 카드에 기기 원자료(.xy — 파서 확인용으로 테스트 안에서 만든 곡선)를
  올리면 내용 해시로 한 번만 보관되고, 코드 해석 초안이 "미확인"으로 떠서 확정해야 입력 칸에
  들어가며(자동 제출 없음), 제출이 `source=instrument_draft` + 첨부 id로 나가고 해설에 원본이
  남는지, 타입이 틀린 값(bool 칸에 1)은 422인지.

전부 실제 LLM 실행을 태우므로 한 번에 1~3분 걸린다.

## 2단계 (LLM 없음 — 논문 값으로 진행)

- `stage2.mjs` — CBD 시연 카드로 2단계 1–14단계를 클릭만으로: 프로토타입(Table 1) 실행 → QTPP 행 추가·삭제와 목표를 비운
  승인 차단(QTPP_FIELD) → 논문 값 채우기·승인 → 원료·제형 행렬이 논문 Table 5·7과 같음 → 변수 칩·빈 칸 행 만들기와 근거 없는 행 차단 →
  8단계 종합 정리(고르는 칸·LLM 추천 없음, 위험평가 PDF가 DoE 변수 후보 목록 바로 아래 · 확인만으로 다음) → 설계 표 빈 요인·반응 열(placeholder "요인 이름") + High 변수 · CQA 이름 제안 ·
  논문 값 채우기(표 위 — CBD Table 9 강조 · 로르녹시캄 Table 3) · 요인·반응 열 추가/삭제·행 추가·빈 표 저장 차단 → Table 9(17 run) → Hardness coded 식 = Table 10 →
  10단계 검증 게이트(경도만 통과 1/3 · DT·마손도 요인으로 설명되지 않음 · 경도를 2차로 바꾸면 전부 불합격 → REG_GATE_NONE 승인 불가) → 곡면(경도 1 × 단면 3) →
  ANOVA Model SS 10.73 · p 0.0005(설명되지 않는 반응은 문구) → 13단계 평균 기준 영역 없음(SPACE_NO_MEAN_REGION) 차단 → 논문 규격 → Overlay plot(서버 SVG) ·
  control space 1250–1425 × 30–44.5 @ CCS 3 · 최적 1312.5/35.5/3 · 공동확률 < 0.9는 경고만 → 14단계 → 최종 PDF → 설계 표 다시 열기(뒤 단계 stale), 2단계 기록 메뉴 · 오른쪽 관측 칼럼.
  1440과 390 두 폭, 가로 넘침 0, 콘솔 오류 0. `node tests/browser/stage2.mjs <url> [스크린샷 폴더]`.
- `pipeline.mjs` — **실제 LLM**(`F1_LLM=dacon` 권장): 발표 자료 10쪽 그대로. 시연 카드 ① 로르녹시캄 → 유동성 판정 → 후보 → 개발 착수(불변 Handoff ·
  저함량 · 근거 결손 게이트: 사유 없이 막힘 → 사유 기록) → LLM 초안으로 1–7단계 → 8단계 위험평가 PDF → 9단계 Almotairi Table 3 CSV 불러오기(열 역할 자동 인식) →
  10단계 네 반응 축소 2차 · 게이트 통과 4/4 → 곡면 · ANOVA → 목표 입력 → Overlay plot · control space 1.1–3 × 4.6–9.2 @ 10분 · 최적 2.9 · 10 · 7 →
  확인계획 잠금(최적점 DE30 예측구간 75.3–89.4, 참고: 논문 최적) → 최종 PDF. 약 5분.