# 브라우저 검증

pytest는 검사 엔진을 고정하고, 여기 두 스크립트는 **실제 브라우저에서 화면이 동작하는지**를
고정한다. 이 계층이 없어서 "모달이 안 닫히고 대시보드 전체가 클릭 불가"인 상태가
curl 검증만 통과한 채 배포된 적이 있다.

```bash
(cd tests/browser && npm i)      # 반드시 이 디렉토리 안에서. 위에서 실행하면 npm이
                                 # 상위로 올라가 ~/zihwan/package.json 을 고친다(실제로 겪음).
CHROME=<chrome 실행 파일 경로> node tests/browser/verify.mjs    http://localhost:8000/
CHROME=<chrome 실행 파일 경로> node tests/browser/audit.mjs     http://localhost:8000/
CHROME=<chrome 실행 파일 경로> node tests/browser/evidence.mjs  http://localhost:8000/
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
  설계 실행 → 물리화학 → 데이터 요청 → 건너뛰기 → 후보 → 에이전트가 먼저 알림 → “1위 후보로 개발 착수” → 2단계 프로토타입 카드, XSS, 휴대폰.
- `evidence.mjs` — **이중 루프 회귀 26건**: 실험 데이터 선택 입력(카탈로그 렌더·허용목록 거부),
  근거 게이트(실행 불가 초안 → 확인시험 → 승인 → 실행 가능), 확인시험 수치가 실측값 자리에
  반영되는지, 배치 결과 루프가 그대로 도는지, 4개 화면폭 가로 오버플로. 여기서 실제 결함
  두 건을 잡았다 — 실행 중 확인시험 제출이 404 나던 문제와, 긴 토큰이 좁은 화면에서 페이지를
  가로 스크롤시키던 문제.
- `audit.mjs` — 상용 관점 점검: 5개 렌더 경로에 `<img onerror>` 주입(실행 0회여야 함),
  실행 중 이중 실행 차단, 규칙 기반 대체값 노출 여부, 원시 HTTP 오류 문구 노출,
  접근성 기본, 9개 화면폭 가로 오버플로.
- `scenarios.mjs` — 시연 시나리오 카드 3건이 각자 화면에 적힌 `goal` 문구가 주장하는 경로를
  실제로 밟는지: ① INC002 반려 + 고정 제약 충돌 결론, ② REV001만 소집되고 REV006은 소집 안
  됨, ③ 근거 게이트 → 승인 → 배치 결과 → 구 wetlab 다음 실험 지시 → **신규 장기 실행
  작업함에서 경쟁 원인 가설 카드까지 도달**. `GROQ_API_KEY` 없이 돌리면 결정론 폴백으로도
  통과는 하지만 "실제 LLM 응답이 스키마를 satisfy하는지"는 검증하지 못한다 — 프롬프트나
  `GROQ_TPM`/모델 목록을 건드린 뒤에는 반드시 키를 넣고 한 번 돌릴 것. 요청 문자열이나
  시나리오 흐름을 바꾸면 재실행해서 주장하는 경로가 여전히 그대로 나오는지 확인한다(다른
  스크립트와 같은 원칙).

- `drq.mjs` — 데이터 요청 패널: 입력 칸이 필드 정의의 타입(숫자·예/아니오·선택지·목록)을 따르는지,
  VX-770 cold start에서 DSC 카드에 기기 원자료(.xy — 파서 확인용으로 테스트 안에서 만든 곡선)를
  올리면 내용 해시로 한 번만 보관되고, 코드 해석 초안이 "미확인"으로 떠서 확정해야 입력 칸에
  들어가며(자동 제출 없음), 제출이 `source=instrument_draft` + 첨부 id로 나가고 해설에 원본이
  남는지, 타입이 틀린 값(bool 칸에 1)은 422인지.

전부 실제 LLM 실행을 태우므로 한 번에 1~3분 걸린다.

## 2단계 (LLM 없음 — 논문 값으로 진행)

- `stage2.mjs` — CBD 시연 카드로 2단계 12단계를 클릭만으로 끝까지: 프로토타입(Table 1) 실행 → QTPP 행 추가·삭제와 목표를 비운
  승인 차단(QTPP_FIELD) → 논문 값 채우기·승인 → 원료·제형 행렬이 논문 Table 5·7과 같음 → 변수 칩·빈 칸 행 만들기와 근거 없는 행 차단 →
  DoE 변수 4개 제한 → 위험평가 PDF → 설계 표 요인·반응 열 추가/삭제·행 추가·빈 표 저장 차단 → Table 9(17 run) → Hardness coded 식 = Table 10 →
  곡면 격자 9칸 → 그림 첨부 → ANOVA Model SS 10.73 · p 0.0005 → 최종 PDF → 설계 표 다시 열기(뒤 단계 stale), 사이드바·오른쪽 서랍.
  1440과 390 두 폭, 가로 넘침 0, 콘솔 오류 0. `node tests/browser/stage2.mjs <url> [스크린샷 폴더]`.
