// ② 개발 스튜디오 회귀 — Lornoxicam 데모를 **화면 클릭만으로** 끝까지 걷는다(명세 v6.1 §19 장면 1–9).
// 각 단계: "데모 입력 채우기"로 폼을 채우고 → 연구자 버튼을 눌러 → 서버 상태가 기대대로 바뀌는지 본다.
// 사용: CHROME=<chrome 경로> node tests/browser/studio.mjs http://localhost:8102/ [스크린샷 폴더]
import { chromium } from 'playwright-core';

const URL = process.argv[2] || 'http://localhost:8102/';
const SHOTS = process.argv[3] || '';
const browser = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
let failed = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) failed++;
};

const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
// 409/422는 규칙이 막은 의도된 거절(장면 2 CR006 등) — 네트워크 로그로 찍힐 뿐 오류가 아니다
page.on('console', (m) => { if (m.type() === 'error' && !/status of (409|422)/.test(m.text())) errors.push(m.text()); });
await page.addInitScript(() => { try { localStorage.setItem('f1_guide_seen_v1', '1'); localStorage.removeItem('f1:study'); } catch (e) {} });
await page.goto(URL + '?studio', { waitUntil: 'networkidle' });

const state = () => page.$eval('.ask-state', (e) => e.textContent.trim()).catch(() => '');
const shot = async (name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); };
async function waitState(text, ms = 20000) {
  await page.waitForFunction((t) => (document.querySelector('.ask-state')?.textContent || '').includes(t), text, { timeout: ms });
}
async function step(label, action, expectAfter, { fill = true } = {}) {
  if (fill && await page.$('#ask-fill')) await page.click('#ask-fill');
  await page.waitForTimeout(150);
  await page.click(`#studio-ask [data-act="${action}"]`);
  try {
    await waitState(expectAfter);
    check(label, true, expectAfter);
  } catch (e) {
    const err = await page.$eval('.ask-error', (x) => x.textContent.replace(/\s+/g, ' ').slice(0, 200)).catch(() => '');
    check(label, false, `상태 ${await state()} ${err}`);
  }
}

check('스튜디오 탭이 열림', await page.$eval('#view-studio', (e) => !e.hidden));
await page.click('#studio-demo');
await waitState('진입 자료 대기');
check('장면 1: 진입 Readiness가 자료를 요청', (await page.$$eval('#studio-ask .vrow', (r) => r.length)) >= 2);
check('질문 카드가 화면의 주인공 (가장 넓은 칸)', await page.evaluate(() => {
  const a = document.getElementById('studio-ask').getBoundingClientRect().width;
  const s = document.querySelector('.studio-side').getBoundingClientRect().width;
  return a > s;
}));
await shot('01-required');
await step('장면 1: 압축력 UNKNOWN 기록 → CQA로', 'required_data', 'CQA 승인 대기');

// 장면 2: 채우지 않고 승인하면 규칙이 막는다
await page.click('#studio-ask [data-act="cqa_approve"]');
await page.waitForSelector('.ask-error');
check('장면 2: 용출 요약값 미정이면 CR006이 승인을 막음', (await page.$eval('.ask-error', (e) => e.textContent)).includes('CR006'));
await shot('02-cqa-blocked');
await step('장면 2: CQA 규격 입력(가정 표시)', 'cqa_edit', 'CQA 승인 대기');
await step('장면 2: CQA 계약 승인', 'cqa_approve', 'FMEA 승인 대기', { fill: false });
await shot('03-fmea');
check('장면 3: O가 UNKNOWN인 행은 RPN 미계산', (await page.$$eval('.fmea-table td .muted', (x) => x.length)) > 0);
await step('장면 3: FMEA 처리 방향 입력', 'fmea_edit', 'FMEA 승인 대기');
await step('장면 3: FMEA 승인', 'fmea_approve', '요인', { fill: false });
await shot('04-factors');
await step('장면 4: 요인 범위·근거 제출', 'factor_data', '요인 승인 대기');
check('장면 4: 희석 교락 경고(FR007)', (await page.$eval('#studio-ask', (e) => e.innerHTML)).includes('FR007'));
await step('장면 5: 요인 승인 → RSM 직행 BBD', 'factor_approve', 'RSM 설계 승인 대기');
check('장면 5: BBD 15 run', (await page.$$eval('table.matrix tbody tr', (r) => r.length)) === 15);
await shot('05-plan');
await step('장면 5: 설계 승인', 'plan_approve', 'RSM 결과 대기', { fill: false });
await page.click('#ask-fill');
await page.waitForFunction(() => document.querySelector('#rs-csv')?.value.includes('LX-F1'));
check('결과 CSV 열 대응 추정 7개', (await page.$$eval('#rs-map select', (s) => s.filter((x) => x.value).length)) === 7);
await shot('06-upload');
await step('장면 6: 결과 제출 → 읽은 값 확인', 'results_submit', 'RSM 결과 대기', { fill: false });
await page.waitForSelector('[data-act="results_confirm"]');
{ const n = await page.$$eval('#studio-ask table.matrix tbody tr', (r) => r.length); check('읽은 값 60개 미리보기', n === 60, String(n)); }
await page.click('#studio-ask [data-act="results_confirm"][data-accept="1"]');
await waitState('모델 판단 대기');
check('장면 6: 마손도 FLAGGED', (await page.$eval('.model-card[data-cqa="CQA_FRIABILITY"] .mstat', (e) => e.textContent)) === 'FLAGGED');
await shot('07-models');
await page.click('#ask-fill');
await page.click('.model-card[data-cqa="CQA_FRIABILITY"] [data-act="model_reduce"]');
await page.waitForFunction(() => !document.querySelector('.ask.busy'));
await page.waitForTimeout(300);
await page.click('#ask-fill');
await page.click('.model-card[data-cqa="CQA_CU_AV"] [data-act="model_accept"]');
await page.waitForFunction(() => !document.querySelector('.ask.busy'));
await page.waitForTimeout(300);
await step('장면 6: 축소·수용 후 재검증 → 영역', 'model_approve', '잠정 영역 검토', { fill: false });
await page.waitForSelector('#region-inline svg rect');
const stats = await page.$eval('.stats', (e) => e.textContent);
check('장면 7: 평균 77.2% → 공동확률 47.6%', stats.includes('77.2%') && stats.includes('47.6%'), stats.replace(/\s+/g, ' '));
await shot('08-region');
await step('장면 8: PROVISIONAL 승인(참고 배치 포함)', 'region_approve', '확인계획 잠금 대기');
check('장면 8: 확인점 4개(필수 3 + 참고)', (await page.$$eval('#studio-ask table.matrix tbody tr', (r) => r.length)) === 4);
await shot('09-vplan');
await step('장면 8: 확인계획 잠금', 'vplan_lock', '확인배치 결과 대기', { fill: false });
await page.click('#ask-fill');
check('장면 9: 필수 확인점 칸은 비워 둔다(값을 지어내지 않음)', await page.evaluate(() =>
  [...document.querySelectorAll('.vpoint:not(.ref) [data-cqa]')].every((i) => !i.value)));
await page.click('#studio-ask [data-act="verification_submit"]');
await page.waitForFunction(() => !document.querySelector('.ask.busy'));
await page.waitForTimeout(300);
await page.click('#studio-ask [data-act="verification_confirm"]');
await page.waitForFunction(() => (document.querySelector('#studio-ask')?.textContent || '').includes('참고 평가 (예측과 비교)'));
check('장면 9: 논문 최적처방 배치 — 참고 평가, 잠근 PI 안', (await page.$eval('#studio-ask', (e) => e.textContent)).includes('규격 통과 · PI 안'));
check('장면 9: 필수 확인점 없이는 판정하지 않음(상태 유지)', (await state()).includes('확인배치 결과 대기'));
await shot('10-reference');

// 사이드 탭
await page.click('.side-tab[data-tab="rules"]');
check('규칙 판정 탭', (await page.$$eval('.rule-block', (r) => r.length)) > 5);
await page.click('.side-tab[data-tab="trace"]');
await page.waitForSelector('.tl li');
check('lineage 탭 (§18 식별자)', (await page.$eval('#studio-side-body', (e) => e.textContent)).includes('HO-LX-DT-F2'));

// 모바일 폭 가로 넘침
for (const w of [390, 820]) {
  await page.setViewportSize({ width: w, height: 900 });
  await page.waitForTimeout(200);
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(`${w}px 가로 넘침 없음`, over <= 1, `+${over}px`);
}
// ── 가이드 시연 · 휴대폰 폭 ─────────────────────────────────────────
// ① 탭의 4번째 시나리오 카드 → 스튜디오 가이드 시연 → 장면별로 가로 넘침 없이 → 자동 진행으로 끝까지.
const m = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
m.on('pageerror', (e) => errors.push('mobile: ' + String(e)));
m.on('console', (x) => { if (x.type() === 'error' && !/status of (409|422)/.test(x.text())) errors.push('mobile: ' + x.text()); });
await m.addInitScript(() => { try { localStorage.setItem('f1_guide_seen_v1', '1'); localStorage.removeItem('f1:study'); localStorage.setItem('f1:tab', 'discovery'); } catch (e) {} });
await m.goto(URL, { waitUntil: 'networkidle' });
const cards = await m.$$('#scenarios .scenario');
check('① 탭에 시나리오 카드 4개', cards.length === 4, String(cards.length));
await cards[3].click();
await m.waitForSelector('#studio-guide:not([hidden]) .gb-step');
check('카드 4 → 스튜디오 가이드 시연 시작', await m.$eval('#view-studio', (e) => !e.hidden));
const mover = () => m.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
const scenesSeen = new Set();
const overflowAt = [];
// 장면 2까지 한 단계씩 — 편집 표가 카드로 바뀌는지 본다
for (let i = 0; i < 2; i++) {
  await m.click('.gb-step');
  await m.waitForFunction(() => !document.querySelector('.gb-step[disabled]'), null, { timeout: 30000 });
}
check('휴대폰: CQA 편집 표가 카드로(머리행 숨김)', await m.$eval('table.cqa-table thead', (e) => getComputedStyle(e).display === 'none'));
check('휴대폰: 규칙이 막은 이유가 카드에', (await m.$eval('#studio-ask', (e) => e.textContent)).includes('CR006'));
if (SHOTS) await m.screenshot({ path: `${SHOTS}/m-cqa.png`, fullPage: false });
await m.click('.gb-auto');
const t0 = Date.now();
while (Date.now() - t0 < 180000) {
  const n = await m.$eval('.gb-count', (e) => e.textContent).catch(() => '');
  if (n) scenesSeen.add(n);
  const o = await mover();
  if (o > 1) overflowAt.push(`${n}:+${o}`);
  if (await m.$('.gb-restart')) break;
  await m.waitForTimeout(700);
}
check('자동 진행이 끝까지 (장면 9 · 시연 종료)', !!(await m.$('.gb-restart')), [...scenesSeen].join(','));
check('장면 1–9를 모두 거침', scenesSeen.size >= 8, String(scenesSeen.size));
check('휴대폰: 모든 장면에서 가로 넘침 없음', overflowAt.length === 0, overflowAt.slice(0, 4).join(' '));
check('시연 끝: 참고 평가 표시 · 합성·예시값 없음', (await m.$eval('#studio-ask', (e) => e.textContent)).includes('참고 평가 (예측과 비교)')
  && !(await m.content()).includes('SYNTHETIC'));
if (SHOTS) await m.screenshot({ path: `${SHOTS}/m-end.png`, fullPage: false });
check('콘솔 오류 0건', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
console.log(failed ? `\n${failed} FAILED` : '\nALL PASS');
process.exit(failed ? 1 : 0);
