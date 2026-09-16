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
```

맥이면 `CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"` 를 그대로 쓰면 된다.

- `verify.mjs` — 상호작용 회귀 33건: 설명 오버레이 열기/닫기/ESC/배경클릭, 8단계 중 5개
  레이아웃이 셸 안에 들어오는지, 설계 실행 → 규칙 모달 열고 닫기, 분자·그래프·트레이스·합의
  렌더링, 테마 전환과 새로고침 유지, 모바일 뷰포트, 콘솔 오류 0건.
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

전부 실제 LLM 실행을 태우므로 한 번에 1~3분 걸린다.
