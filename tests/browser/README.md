# 브라우저 검증

pytest는 검사 엔진을 고정하고, 여기 두 스크립트는 **실제 브라우저에서 화면이 동작하는지**를
고정한다. 이 계층이 없어서 "모달이 안 닫히고 대시보드 전체가 클릭 불가"인 상태가
curl 검증만 통과한 채 배포된 적이 있다.

```bash
npm i playwright-core
CHROME=<chrome 실행 파일 경로> node tests/browser/verify.mjs http://localhost:8000/
CHROME=<chrome 실행 파일 경로> node tests/browser/audit.mjs  http://localhost:8000/
```

- `verify.mjs` — 상호작용 회귀 33건: 설명 오버레이 열기/닫기/ESC/배경클릭, 8단계 중 5개
  레이아웃이 셸 안에 들어오는지, 설계 실행 → 규칙 모달 열고 닫기, 분자·그래프·트레이스·합의
  렌더링, 테마 전환과 새로고침 유지, 모바일 뷰포트, 콘솔 오류 0건.
- `audit.mjs` — 상용 관점 점검: 5개 렌더 경로에 `<img onerror>` 주입(실행 0회여야 함),
  실행 중 이중 실행 차단, 규칙 기반 대체값 노출 여부, 원시 HTTP 오류 문구 노출,
  접근성 기본, 9개 화면폭 가로 오버플로.

둘 다 실제 LLM 실행을 태우므로 한 번에 1~2분 걸린다.
