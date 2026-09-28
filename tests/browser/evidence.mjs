// 근거 결손 게이트(발표 자료 ⑤) — 후보 카드 안에서: 결손 표시 → 확인시험 결과 입력 → 재판정 → 개발 착수 / 부적합이면 막힘.
// 실제 LLM으로 시연 카드 ①을 돌린다(후보가 있어야 한다). F1_LLM=dacon 권장.
//   F1_LLM=dacon CHROME=<chrome> node tests/browser/evidence.mjs http://localhost:8104/
import { chromium } from 'playwright-core';

const URL = process.argv[2] || 'http://localhost:8000/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const ctx = await b.newContext({ viewport: { width: 1440, height: 950 } });
await ctx.addInitScript((v) => { try { localStorage.setItem('f1_guide_seen_v1', '1'); if (v) localStorage.setItem('f1:llm', v); } catch (e) {} }, process.env.F1_LLM || '');
const p = await ctx.newPage();
const errs = [];
p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
p.on('console', (m) => { if (m.type() === 'error' && !/status of (409|422)/.test(m.text())) errs.push('console: ' + m.text()); });
let fail = 0;
const ck = (n, ok, d = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${n}${d ? ' — ' + d : ''}`); if (!ok) fail++; };
await p.goto(URL, { waitUntil: 'networkidle' });

console.log('\n[시연 ① → 후보 카드]');
await p.locator('.scenario', { hasText: '로르녹시캄' }).click();
await p.waitForFunction(() => document.getElementById('run').textContent.trim() === '설계 실행', null, { timeout: 600000 });
if (await p.locator('#agent-log #drq:not([hidden])').count()) await p.click('#drq-skip');
await p.waitForSelector('#agent-log #panel-cands .card.pass .ev-box', { timeout: 120000 });
const passed = p.locator('#agent-log #panel-cands .card.pass');
ck('통과 후보마다 근거 결손 게이트 판정', await passed.count() === await p.locator('#agent-log #panel-cands .card.pass .ev-box').count(), `${await passed.count()}장`);
ck('반려 후보에는 게이트 상자 없음', await p.locator('#agent-log #panel-cands .card.fail .ev-box').count() === 0);

// 결손이 있는 첫 후보
const idx = await passed.evaluateAll((cs) => cs.findIndex((c) => c.querySelector('.ev-box.hold')));
if (idx < 0) {
  ck('결손 후보가 있음(없으면 이 실행에선 결손 경로를 확인할 수 없음)', false);
} else {
  const cid = await passed.nth(idx).getAttribute('data-cand');
  const card = () => p.locator(`#agent-log #panel-cands .card[data-cand="${cid}"]`);
  ck('결손 후보의 버튼 = “결손을 기록하고 개발 착수”(점선)', /결손을 기록하고/.test(await card().locator('.dev-start').textContent()) && await card().locator('.dev-start.hold').count() === 1);
  await card().locator('.ev-box > summary').click();
  const reqs = await card().locator('.ev-list li[data-req]').evaluateAll((ls) => ls.map((l) => ({ id: l.dataset.req, code: l.querySelector('code')?.textContent || '' })));
  ck('요청 시험은 확인시험 마스터의 test_id', reqs.length > 0 && reqs.every((r) => /^[A-Z]/.test(r.code)), reqs.map((r) => `${r.id}:${r.code}`).join(', '));

  // 결과 입력 — 적합으로 전부 닫는다(각 입력 뒤 카드가 다시 그려진다)
  for (const r of reqs) {
    const li = card().locator(`.ev-list li[data-req="${r.id}"]`);
    if (!(await li.locator('.ev-send').count())) continue;
    if (!(await li.isVisible())) await card().locator('.ev-box > summary').click();
    await li.locator('.ev-note').fill('사내 확인시험 적합(브라우저 테스트)');
    const num = li.locator('.ev-num');
    if (await num.count()) await num.fill('');
    const resp = p.waitForResponse((x) => x.url().includes('/confirmation'));
    await li.locator('.ev-send').click();
    ck(`결과 입력 ${r.id} → 200`, (await resp).status() === 200);
    await p.waitForTimeout(300);
  }
  const head = (await card().locator('.ev-box > summary').textContent()).replace(/\s+/g, ' ');
  ck('재판정 → 근거 충족(LLM 없이 즉시)', /근거 충족/.test(head), head.slice(0, 80));
  ck('버튼이 “이 후보로 개발 착수”로 바뀜', /이 후보로 개발 착수/.test(await card().locator('.dev-start').textContent()));
  const narr = await p.locator('#narration').textContent().catch(() => '');
  ck('해설에 재판정 기록', /근거를 다시 판정/.test(narr));
  await card().locator('.dev-start').click();
  await p.waitForSelector('#s2 .s2-step.current[data-step="prototype"]', { timeout: 60000 });
  const ho = (await p.locator('#s2 .s2-handoff').textContent()).replace(/\s+/g, ' ');
  ck('사유 없이 2단계 착수 · Handoff에 근거 충족 기록', /근거 결손 게이트/.test(ho) && !/연구자 사유/.test(ho), (ho.match(/근거 결손 게이트[^·]{0,60}/) || [''])[0]);
}

// 부적합 — 다른 결손 후보가 있으면 부적합 결과로 막히는지
const other = await passed.evaluateAll((cs) => cs.findIndex((c) => c.querySelector('.ev-box.hold')));
if (other >= 0) {
  const card = passed.nth(other);
  await card.locator('.ev-box > summary').click();
  const li = card.locator('.ev-list li[data-req]').first();
  await li.locator('.ev-out').selectOption('fail');
  await li.locator('.ev-note').fill('분해물 증가(브라우저 테스트)');
  await li.locator('.ev-send').click();
  await p.waitForTimeout(800);
  const c2 = p.locator('#agent-log #panel-cands .card.pass').nth(other);
  ck('부적합 → 개발 불가(버튼 비활성)', await c2.locator('.dev-start[disabled]').count() === 1 && /부적합/.test(await c2.locator('.ev-box > summary').textContent()));
} else {
  console.log('  · 결손 후보가 하나뿐이라 부적합 경로는 pytest(test_evidence_api.py)로만 확인');
}

// 좁은 화면 — 게이트 상자가 가로로 넘치지 않는다
await p.setViewportSize({ width: 390, height: 844 });
await p.waitForTimeout(300);
ck('390px 가로 넘침 없음', await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
ck('콘솔 오류 0', errs.length === 0, errs.slice(0, 3).join(' | '));
await b.close();
console.log(fail ? `\n실패 ${fail}건` : '\n모두 통과');
process.exit(fail ? 1 : 0);
