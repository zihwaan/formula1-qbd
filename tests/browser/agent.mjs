// 입력 에이전트 회귀 — 가운데 입력칸 → 제안 카드 + 실험 데이터 입력 카드 → [설계 실행] → 물리화학 → 데이터 요청 → 후보 → 개발 착수(2단계).
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
// 모델 선택(기본 Groq). 무료 한도가 바닥났을 때 F1_LLM=dacon 으로 같은 흐름을 대회 API로 검증할 수 있다(로컬=full 권한).
if (process.env.F1_LLM) await page.addInitScript((v) => { try { localStorage.setItem('f1:llm', v); } catch (e) {} }, process.env.F1_LLM);
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('console', (m) => { if (m.type() === 'error' && !/status of (409|422)/.test(m.text())) errors.push(m.text()); });
await page.addInitScript(() => { try { localStorage.setItem('f1_guide_seen_v1', '1'); } catch (e) {} });
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

check('처음 화면: 가운데 입력칸 하나(폼은 숨은 보조 경로)', await page.evaluate(() => {
  const f = document.getElementById('agent-form').getBoundingClientRect();
  return !!document.querySelector('#hello #agent-form') && Math.abs((f.left + f.right) / 2 - (document.querySelector('.thread').getBoundingClientRect().left + document.querySelector('.thread').clientWidth / 2)) < 40
    && f.top > 150 && document.getElementById('manual-sheet').hidden;
}));
check('플레이스홀더', (await page.getAttribute('#agent-input', 'placeholder')).includes('설계가 끝나면 남은 데이터 요청과 다음 행동을 먼저 알려 드립니다.'));

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

check('첫 메시지 뒤 입력 에이전트가 아래로 내려가고, 히어로·시연 카드는 맨 위에 남음', await page.evaluate(() => !!document.querySelector('#dock-inner #agent-box #agent-form') && !!document.querySelector('#hello .scenario')));
check('설계 실행 카드 밑에 "실험 데이터값을 입력하시겠습니까?" + 실험 데이터 입력 카드', await page.evaluate(() => {
  const cards = [...document.querySelectorAll('#agent-log .ad-card')];
  const row = cards[cards.length - 1].closest('.ad-msg');
  const nx = row.nextElementSibling;
  return !!nx && nx.textContent.includes('실험 데이터값을 입력하시겠습니까?') && !!nx.querySelector('#card-inputs');
}));

// 3) [실행] → 폼이 채워지고 같은 startRun 경로로 설계 시작 → 끝나면 에이전트가 먼저 말을 건다
const before = await agentCount();
await card.locator('.ad-run').click();
await page.waitForFunction(() => document.getElementById('smiles').value.length > 0, null, { timeout: 5000 });
check('폼에 SMILES·용량이 채워짐', await page.evaluate(() =>
  document.querySelector('#inputs-body input[data-key="dose_mg"]').value === '200'));
await page.waitForSelector('#agent-log #panel-chem', { timeout: 20000 });
check('설계 실행 → API 물리화학 카드', true);
await page.waitForFunction(() => document.querySelector('#agent-log #drq:not([hidden])') || document.querySelector('#agent-log #panel-cands'), null, { timeout: 300000 });
const order = await page.evaluate(() => [...document.querySelectorAll('#agent-log > .ad-msg.sys')].map((m) => m.querySelector('#panel-chem') ? 'chem' : m.querySelector('#drq') ? 'drq' : m.querySelector('#panel-cands') ? 'cands' : m.querySelector('#card-inputs') ? 'inputs' : '?'));
check('카드 순서: 실험 데이터 → 물리화학 → 데이터 요청', order.join(',').startsWith('inputs,chem'), order.join(' → '));
if (order.includes('drq')) {
  check('데이터 요청이 있으면 후보 카드는 아직', !order.includes('cands'));
  await page.click('#drq-skip');
  await page.waitForSelector('#agent-log #panel-cands', { timeout: 30000 });
  check('전부 건너뛰기 → 후보 처방 카드', true);
}
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

// 6) 개발 착수 — 말로 요청하면 개발 착수 카드, [실행]은 후보 카드의 [이 후보로 개발 착수]와 같은 길로 2단계를 연다
await ask('1위 후보로 개발 착수해 줘');
card = page.locator('#agent-log .ad-card').last();
const txt = await card.innerText().catch(() => '');
check('개발 착수 카드', txt.includes('개발 착수'), txt.replace(/\s+/g, ' ').slice(0, 100));
if (txt.includes('개발 착수') && await card.locator('.ad-run').isEnabled()) {
  await card.locator('.ad-run').click();
  await page.waitForSelector('#s2 .s2-step.current[data-step="prototype"]', { timeout: 20000 }).catch(() => {});
  check('2단계 프로토타입 카드가 대화에 열림', await page.locator('#s2 .s2-step.current[data-step="prototype"]').count() === 1);
  check('프로토타입 = 후보 처방(API 행 포함)', await page.locator('#s2 [data-edit] input[data-k="role"][value="api"]').count() === 1);
}

// 7) 휴대폰 — 바닥 시트, 가로 넘침 없음
const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
await phone.addInitScript(() => { try { localStorage.setItem('f1_guide_seen_v1', '1'); } catch (e) {} });
await phone.goto(URL, { waitUntil: 'networkidle' });
const geo = await phone.evaluate(() => {
  const r = document.getElementById('agent-form').getBoundingClientRect();
  return { w: r.width, top: r.top, bottom: r.bottom, sw: document.documentElement.scrollWidth, vw: innerWidth, vh: innerHeight };
});
check('휴대폰: 입력칸이 첫 화면 안', geo.bottom < geo.vh && geo.w > geo.vw - 60, JSON.stringify(geo));
check('휴대폰: 가로 넘침 없음', geo.sw <= geo.vw, JSON.stringify(geo));
check('페이지 오류 없음', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
console.log(failed ? `실패 ${failed}건` : 'ALL PASS');
process.exit(failed ? 1 : 0);
