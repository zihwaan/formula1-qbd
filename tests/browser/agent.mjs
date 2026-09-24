// 입력 에이전트 회귀 — 말 → 제안 카드 → [실행] → 기존 경로(startRun · submitMeasurements · F1Studio.runAction).
// 실제 LLM이 필요하다(서버에 GROQ_API_KEY). 사용: CHROME=<chrome 경로> node tests/browser/agent.mjs http://localhost:8104/
import { chromium } from 'playwright-core';

const URL = process.argv[2] || 'http://localhost:8104/';
const browser = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
let failed = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) failed++;
};

const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('console', (m) => { if (m.type() === 'error' && !/status of (409|422)/.test(m.text())) errors.push(m.text()); });
await page.addInitScript(() => { try { localStorage.setItem('f1_guide_seen_v1', '1'); localStorage.removeItem('f1:study'); localStorage.setItem('f1:tab', 'discovery'); } catch (e) {} });
await page.goto(URL, { waitUntil: 'networkidle' });

const lastAgent = () => page.$$eval('#agent-log .ad-msg.agent:not(.typing)', (m) => m.length ? m[m.length - 1].innerText : '');
const agentCount = () => page.$$eval('#agent-log .ad-msg.agent:not(.typing)', (m) => m.length);
async function ask(text, ms = 60000) {
  const before = await agentCount();
  await page.fill('#agent-input', text);
  await page.click('#agent-send');
  await page.waitForFunction((n) => document.querySelectorAll('#agent-log .ad-msg.agent:not(.typing)').length > n, before, { timeout: ms });
  return lastAgent();
}

check('런처가 보임', await page.isVisible('#agent-launcher'));
await page.click('#agent-launcher');
check('dock이 열림', await page.isVisible('#agent-dock'));

// 1) 용량이 없으면 실행 카드는 준비되지 않은 상태로 묻는다
await ask('성인용 이부프로펜 정제로 설계해 줘');
let card = page.locator('#agent-log .ad-card').last();
check('용량 없으면 카드가 미완성(점선)', await card.evaluate((c) => c.classList.contains('incomplete')));
check('실행 버튼이 잠김', await card.locator('.ad-run').isDisabled());
check('용량을 묻는다', (await lastAgent()).includes('용량'));

// 2) 이어서 용량을 말하면 앞 대화와 합쳐 준비된 카드가 된다
await ask('1회 200mg이야');
card = page.locator('#agent-log .ad-card').last();
check('준비된 카드', !(await card.evaluate((c) => c.classList.contains('incomplete'))));
check('구조 출처가 표시됨', /내장 구조 사전|PubChem/.test(await card.innerText()));
check('용량 200 mg', (await card.innerText()).includes('200 mg'));

// 3) [실행] → 폼이 채워지고 같은 startRun 경로로 설계 시작 → 끝나면 에이전트가 먼저 말을 건다
const before = await agentCount();
await card.locator('.ad-run').click();
await page.waitForFunction(() => document.getElementById('smiles').value.length > 0, null, { timeout: 5000 });
check('폼에 SMILES·용량이 채워짐', await page.evaluate(() =>
  document.querySelector('#inputs-body input[data-key="dose_mg"]').value === '200'));
await page.waitForFunction((n) => document.querySelectorAll('#agent-log .ad-msg.agent:not(.typing)').length > n + 0
  && /설계|후보|요청|전략/.test(document.querySelector('#agent-log .ad-msg.agent:last-child')?.innerText || ''), before, { timeout: 300000 });
const nudge = await lastAgent();
check('설계 종료 후 에이전트가 먼저 알림', nudge.length > 10, nudge.replace(/\s+/g, ' ').slice(0, 120));

// 4) 설명 요청 — 맥락에서 답한다
const why = await ask('결과 설명해 줘');
check('결과 설명', why.length > 10, why.replace(/\s+/g, ' ').slice(0, 120));

// 5) XSS — 사용자 글이 그대로 실행되지 않는다
await page.evaluate(() => { window.__x = 0; });
await ask('<img src=x onerror="window.__x=1"> 설명해 줘');
check('에이전트 로그에서 스크립트 미실행', (await page.evaluate(() => window.__x)) === 0);

// 6) 스튜디오 — 데모 study를 열면 맥락이 바뀌고, 말로 진입 자료를 정리한다
await page.click('#tab-studio');
await page.click('#studio-demo');
await page.waitForFunction(() => (document.querySelector('.ask-state')?.textContent || '').includes('진입 자료'), null, { timeout: 20000 });
await page.waitForFunction(() => /진입 자료/.test(document.querySelector('#agent-log .ad-msg.agent:last-child')?.innerText || ''), null, { timeout: 10000 });
check('스튜디오 상태에 맞춰 먼저 안내', true);
check('맥락 표시가 스튜디오', (await page.textContent('#agent-ctx')).includes('개발 스튜디오'));
await ask('압축력은 몰라요');
card = page.locator('#agent-log .ad-card').last();
const txt = await card.innerText().catch(() => '');
check('스튜디오 행동 카드(required_data)', txt.includes('required_data'), txt.replace(/\s+/g, ' ').slice(0, 100));
if (txt.includes('required_data')) {
  await card.locator('.ad-run').click();
  await card.locator('.ad-result').waitFor({ state: 'visible', timeout: 20000 }).catch(() => {});
  const res = await card.locator('.ad-result').innerText().catch(() => '');
  check('실행 결과가 카드에 표시(반영 또는 룰북 사유)', /반영했습니다|룰북이 막았습니다/.test(res) && !(await card.locator('.ad-result').evaluate((r) => r.hidden)), res.slice(0, 120));
}

// 7) 휴대폰 — 바닥 시트, 가로 넘침 없음
const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
await phone.addInitScript(() => { try { localStorage.setItem('f1_guide_seen_v1', '1'); } catch (e) {} });
await phone.goto(URL, { waitUntil: 'networkidle' });
await phone.click('#agent-launcher');
const geo = await phone.evaluate(() => {
  const r = document.getElementById('agent-dock').getBoundingClientRect();
  return { w: r.width, bottom: r.bottom, sw: document.documentElement.scrollWidth, vw: innerWidth, vh: innerHeight };
});
check('휴대폰: 바닥 시트 전체 폭', Math.abs(geo.w - geo.vw) < 2 && Math.abs(geo.bottom - geo.vh) < 2, JSON.stringify(geo));
check('휴대폰: 가로 넘침 없음', geo.sw <= geo.vw, JSON.stringify(geo));

check('페이지 오류 없음', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
console.log(failed ? `실패 ${failed}건` : 'ALL PASS');
process.exit(failed ? 1 : 0);
