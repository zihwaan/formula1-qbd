// ① 후보 탐색의 통과 후보 → "v7 실험개발로 시작" → 신규 API study(HANDOFF_RECEIVED). 실제 LLM 설계 실행 1회를 탄다(키 필요).
// 후보 처방에는 설비·배치 규모·주성분 등급이 없으므로 후보 확인은 RB01(RD003·RD005·RD006)로 막혀야 한다 — 값을 지어내지 않는다.
import { chromium } from 'playwright-core';
const URL = process.argv[2] || 'http://localhost:8000/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
let fail = 0;
const ck = (n, ok, d = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${n}${d ? ' — ' + d : ''}`); if (!ok) fail++; };
const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const errs = [];
p.on('pageerror', (e) => errs.push(e.message));
await p.addInitScript(() => { localStorage.setItem('f1_guide_seen_v1', '1'); localStorage.removeItem('f1:d7study'); });
await p.goto(URL, { waitUntil: 'networkidle' });
await p.evaluate(() => { document.getElementById('manual').open = true; });
await p.fill('#request', '성인용 이부프로펜 정제를 설계해줘');
await p.click('#run');
await p.waitForSelector('.dev-v7', { timeout: 240000 }).catch(() => {});
await p.waitForFunction(() => !document.getElementById('run').disabled, null, { timeout: 240000 }).catch(() => {});   // 실행이 끝나야 후보가 고정된다
const n = await p.locator('.dev-v7').count();
ck('통과 후보 카드에 v7 버튼', n > 0, `${n}개`);
if (n) {
  await p.locator('.dev-v7').first().click();
  await p.waitForFunction(() => document.querySelector('#d7w-ask h3 .d7-badge')?.textContent === 'HANDOFF_RECEIVED', null, { timeout: 30000 }).catch(() => {});
  if (!(await p.locator('#d7w-ask').count())) console.log('   msg:', await p.locator('#d7w-msg').textContent());
  ck('v7 탭으로 이동 · 신규 API study', !(await p.locator('#view-v7').isHidden()) && (await p.locator('#d7w-main').textContent()).includes('신규 API'));
  ck('입력 채우기 버튼 없음(문헌 값 없음)', (await p.locator('#d7w-fill').count()) === 0);
  await p.click('#d7w-ask [data-act="handoff_confirm"]');
  await p.waitForFunction(() => /막혔습니다/.test(document.getElementById('d7w-msg').textContent), null, { timeout: 30000 }).catch(() => {});
  const t = await p.locator('#d7w-ask').textContent();
  ck('RB01이 설비·배치·등급을 요청', ['RD003', 'RD005', 'RD006'].every((x) => t.includes(x)));
}
ck('페이지 오류 없음', errs.length === 0, errs.join(' | '));
await b.close();
console.log(fail ? `\n${fail}건 실패` : '\nALL PASS');
process.exit(fail ? 1 : 0);
