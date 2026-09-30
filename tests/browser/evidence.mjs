// 근거 결손 게이트(발표 자료 ⑤) — 후보 카드 안에서: 결손 표시 → 측정값 입력 → phase_gates부터 재계산(트레이스) → 근거 재판정 → 개발 착수.
// 적합/부적합을 고르는 칸은 없다(사용자 2026-09-30) — 값이 규칙으로 다시 판정된다.
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

  ck('적합/부적합 선택 칸 없음', await card().locator('.ev-out, .ev-note').count() === 0);
  // 측정값 입력 — BCS I이 되는 값(용해도 부피 ≤ 250 mL · 흡수율 ≥ 85 %)으로 넣어 새 판정에서도 후보가 통과하게 한다
  const VAL = { dose_solubility_volume: '100', fraction_absorbed: '95', aqueous_stability_percent: '99', solubility_mg_per_ml: '5' };
  for (const r of reqs) {
    const li = card().locator(`.ev-list li[data-req="${r.id}"]`);
    if (!(await li.count()) || !(await li.locator('.ev-send').count())) continue;
    if (!(await li.isVisible())) await card().locator('.ev-box > summary').click();
    for (const inp of await li.locator('[data-key]').all()) {
      const key = await inp.getAttribute('data-key');
      if ((await inp.getAttribute('data-type')) === 'bool') await inp.check();
      else await inp.fill(VAL[key] || '1');
    }
    const before = await p.locator('#trace .ev').count();
    const resp = p.waitForResponse((x) => x.url().includes('/measurements'));
    await li.locator('.ev-send').click();
    ck(`측정값 입력 ${r.id} → /measurements 200`, (await resp).status() === 200);
    await p.waitForTimeout(600);
    const rows = await p.locator('#trace .ev').evaluateAll((es, n) => es.slice(n).map((e) => e.textContent.replace(/\s+/g, ' ')), before);
    ck(`${r.id} 재계산이 트레이스에 phase_gates부터 남음`, rows.some((t) => /phase_gates/.test(t)) && rows.some((t) => /gate/.test(t)), rows.slice(0, 3).join(' | ').slice(0, 120));
  }
  const head = (await card().locator('.ev-box > summary').textContent()).replace(/\s+/g, ' ');
  ck('재계산 → 근거 충족', /근거 충족/.test(head), head.slice(0, 80));
  ck('버튼이 “이 후보로 개발 착수”로 바뀜', /이 후보로 개발 착수/.test(await card().locator('.dev-start').textContent()));
  const narr = await p.locator('#narration').textContent().catch(() => '');
  ck('해설에 재판정 기록', /근거를 다시 판정/.test(narr));
  await card().locator('.dev-start').click();
  await p.waitForSelector('#s2 .s2-step.current[data-step="prototype"]', { timeout: 60000 });
  const ho = (await p.locator('#s2 .s2-handoff').textContent()).replace(/\s+/g, ' ');
  ck('사유 없이 2단계 착수 · Handoff에 근거 충족 기록', /근거 결손 게이트/.test(ho) && !/연구자 사유/.test(ho), (ho.match(/근거 결손 게이트[^·]{0,60}/) || [''])[0]);
}

// 좁은 화면 — 게이트 상자가 가로로 넘치지 않는다
await p.setViewportSize({ width: 390, height: 844 });
await p.waitForTimeout(300);
ck('390px 가로 넘침 없음', await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
ck('콘솔 오류 0', errs.length === 0, errs.slice(0, 3).join(' | '));
await b.close();
console.log(fail ? `\n실패 ${fail}건` : '\n모두 통과');
process.exit(fail ? 1 : 0);
