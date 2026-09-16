// 시연 시나리오 3건이 각자의 goal 텍스트가 주장하는 경로를 실제로 밟는지 확인한다.
// 실제 Groq LLM을 태우므로(GROQ_API_KEY 필요) 전체 실행에 몇 분 걸린다. 키가 없으면 결정론
// 폴백으로 내려가 통과는 하지만 "진짜 LLM이 돌았는지"는 검증하지 못한다 — 배포 전에는 키를
// 넣고 한 번 돌려서 판정·심사·진단이 실제로 LLM에서 나오는지 확인할 것(2026-09-16, 죽은
// Groq 모델 ID가 항상 결정론 폴백으로 조용히 떨어지게 만든 사고가 바로 이 검증 부재 때문이었다).
import { chromium } from 'playwright-core';
const URL = process.argv[2] || 'http://localhost:8000/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const p = await b.newPage({ viewport: { width: 1600, height: 1100 } });
const errs = [];
p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
p.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
await p.addInitScript(() => localStorage.setItem('f1_guide_seen_v1', '1'));
await p.goto(URL, { waitUntil: 'networkidle' });

let fail = 0;
const ck = (n, ok, d = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${n}${d ? ' — ' + d : ''}`); if (!ok) fail++; };

async function waitDone(timeout = 240000) {
  await p.waitForFunction(() => document.getElementById('run').textContent.trim() === '설계 실행',
    null, { timeout });
}

// ── 시나리오 0: 규칙이 AI를 막는 순간 ──────────────────────────────
console.log('\n[시나리오 1 · 규칙이 AI를 막는 순간]');
await p.locator('.scenario').nth(0).click();
await waitDone();
await p.waitForTimeout(1000);
let trace = await p.locator('#trace').textContent();
ck('INC002 반려가 트레이스에 뜬다', trace.includes('INC002'), '');
ck('고정 제약 충돌 결론', /제약|충돌|통과가 없다/.test(trace), '');

// ── 시나리오 1: 요청에 따라 팀이 바뀐다 ────────────────────────────
console.log('\n[시나리오 2 · 요청에 따라 팀이 바뀐다]');
await p.locator('.scenario').nth(1).click();
await waitDone();
await p.waitForTimeout(1000);
trace = await p.locator('#trace').textContent();
ck('REV001(소아 안전) 소집', trace.includes('REV001'), '');
ck('REV002~006 중 무관한 심사관은 소집 안 됨(고령자 REV006 미소집)', !trace.includes('REV006'), '');

// ── 시나리오 2: 실행 전 근거 → 배치 → 다음 실험 (+ 장기 작업함) ──
console.log('\n[시나리오 3 · 실행 전 근거 → 배치 → 다음 실험]');
await p.locator('.scenario').nth(2).click();
await waitDone();
await p.waitForTimeout(1500);

// continueScenario()가 자동으로: 확인시험 제출 → 승인 → wetlab 제출을 순서대로 누른다.
// wetlab 결과가 뜰 때까지 기다린다.
await p.waitForFunction(() => {
  const el = document.getElementById('wl-out');
  return el && el.textContent.includes('다음 실험 지시');
}, null, { timeout: 60000 }).catch(() => {});
const wlText = await p.locator('#wl-out').textContent().catch(() => '');
ck('구 wetlab 패널에 다음 실험 지시가 나온다', wlText.includes('다음 실험 지시'), '');

// 신규 장기 실행 작업함 — 배치 등록 → 결과 제출 → 확인 → 진단(경쟁 가설)까지 백그라운드로 이어진다.
await p.waitForFunction(() => {
  const el = document.getElementById('wf-body');
  return el && (el.textContent.includes('경쟁 원인 가설') || el.textContent.includes('DIAGNOSING')
    || el.textContent.includes('실패 원인 진단 중'));
}, null, { timeout: 90000 }).catch(() => {});
const wfVisible = await p.evaluate(() => !document.getElementById('workflow').hidden);
ck('장기 실행 작업함 패널이 보인다', wfVisible);
const wfText = await p.locator('#wf-body').textContent().catch(() => '');
console.log('    wf-body 요약:', wfText.replace(/\s+/g, ' ').slice(0, 220));
const hasDiagnosis = wfText.includes('경쟁 원인 가설');
ck('경쟁 원인 가설 카드가 보인다(진단까지 도달)', hasDiagnosis);
if (hasDiagnosis) {
  const hypoBlocks = await p.locator('#wf-body .wf-action').count();
  ck('가설 카드가 1개 이상 렌더된다', hypoBlocks >= 1, `${hypoBlocks}개`);
}

console.log('\n[콘솔/페이지 오류]');
ck('오류 0건', errs.length === 0, errs.slice(0, 5).join(' | '));

await b.close();
console.log(`\n${fail === 0 ? '전부 통과' : fail + '건 실패'}`);
process.exit(fail === 0 ? 0 : 1);
