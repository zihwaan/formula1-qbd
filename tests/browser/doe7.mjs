// DoE v7.0 검증 탭 — CBD 문헌 재현(플래그 승인 대기 → 승인 → 잠근 기준에서 REGION_EMPTY)과 신규 API 범위 gate
// (NEEDS_FEASIBILITY 7조건 → 경계 실패 RANGE_REVISION_REQUIRED → 모두 통과 BBD 17 run). LLM을 쓰지 않는다.
import { chromium } from 'playwright-core';
const URL = process.argv[2] || 'http://localhost:8000/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
let fail = 0;
const ck = (n, ok, d = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${n}${d ? ' — ' + d : ''}`); if (!ok) fail++; };
for (const [name, vp] of [['desktop', { width: 1440, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
  console.log(`\n[${name}]`);
  const p = await (await b.newContext({ viewport: vp })).newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message));
  await p.addInitScript(() => localStorage.setItem('f1_guide_seen_v1', '1'));
  await p.goto(URL + '?v7', { waitUntil: 'networkidle' });
  await p.waitForSelector('#d7-accept', { timeout: 30000 });
  ck('DRAFT 배너', (await p.locator('#d7-banner').textContent()).includes('DRAFT'));
  ck('집행 규칙 0개', (await p.locator('#d7-pkg').textContent()).includes('집행 규칙 0개'));
  ck('플래그 승인 전 WAITING_MODEL_APPROVAL', (await p.locator('#d7-replay').textContent()).includes('WAITING_MODEL_APPROVAL'));
  await p.click('#d7-accept');
  await p.waitForSelector('.d7-map svg', { timeout: 30000 });
  const t = await p.locator('#d7-replay').textContent();
  ck('승인 후 REGION_EMPTY(DR018)', t.includes('REGION_EMPTY') && t.includes('DR018'));
  ck('보고식 불일치 감사', t.includes('PUBLISHED_REPORT_INCONSISTENCY'));
  ck('곡면 지도 4개(반응 3 + 공동)', (await p.locator('.d7-map').count()) === 4);
  await p.click('.d7-x3[data-x3="1"]');
  await p.waitForTimeout(800);
  ck('X3 단면 전환', (await p.locator('.d7-x3.on').textContent()).includes('5%'));
  await p.click('.d7-subtab[data-v="sandbox"]');
  await p.click('#d7-run');
  await p.waitForSelector('#d7-feval');
  ck('신규 API 제안 범위 → NEEDS_FEASIBILITY · 7조건', (await p.locator('#d7-sbout').textContent()).includes('NEEDS_FEASIBILITY') && (await p.locator('.d7-fr[data-k="manufacturable"]').count()) === 7);
  await p.uncheck('.d7-fr[data-c="X1_HIGH"][data-k="manufacturable"]');
  await p.click('#d7-feval');
  await p.waitForFunction(() => document.getElementById('d7-sbout').textContent.includes('RANGE_REVISION_REQUIRED'), null, { timeout: 15000 }).catch(() => {});
  ck('경계 실패 → RANGE_REVISION_REQUIRED', (await p.locator('#d7-sbout').textContent()).includes('RANGE_REVISION_REQUIRED'));
  await p.check('.d7-fr[data-c="X1_HIGH"][data-k="manufacturable"]');
  await p.click('#d7-feval');
  await p.waitForFunction(() => document.getElementById('d7-sbout').textContent.includes('BBD'), null, { timeout: 15000 }).catch(() => {});
  ck('모두 통과 → BBD 17 run', (await p.locator('#d7-sbout table.matrix').last().locator('tbody tr').count()) === 17);
  ck('가로 넘침 없음', (await p.evaluate(() => document.documentElement.scrollWidth - innerWidth)) === 0);
  ck('페이지 오류 없음', errs.length === 0, errs.join(' | '));
}
await b.close();
console.log(fail ? `\n${fail}건 실패` : '\nALL PASS');
process.exit(fail ? 1 : 0);
