// Formula 1 프론트 전수 검증 — 실제 브라우저에서 클릭·키보드·테마·모바일까지.
import { chromium } from 'playwright-core';

const URL = process.argv[2] || 'http://localhost:8102/';
const browser = await chromium.launch({ executablePath: process.env.CHROME, headless: true });

let failed = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) failed++;
};

// position:fixed 요소는 offsetParent가 항상 null이라 그걸로 판정하면 안 된다.
const shown = (page, id) => page.evaluate(
  (i) => {
    const el = document.getElementById(i);
    if (!el) return false;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  }, id);

const topAt = (page, sel) => page.evaluate((s) => {
  const el = document.querySelector(s);
  if (!el) return 'missing';
  const r = el.getBoundingClientRect();
  const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return top === el || el.contains(top) ? 'ok' : `blocked by ${top?.tagName}#${top?.id}`;
}, sel);

const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 } });
const page = await ctx.newPage();
const errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
await page.goto(URL, { waitUntil: 'networkidle' });

console.log('\n[1] 첫 방문 — 설명 오버레이 자동 노출');
check('가이드가 보인다', await shown(page, 'guide'));
check('규칙 모달은 숨겨져 있다', !(await shown(page, 'modal')));

console.log('\n[2] 가이드 내비게이션');
await page.click('#guide-next');
check('다음 → 2단계', (await page.textContent('.guide-kicker')).trim() === '함정');
await page.keyboard.press('ArrowRight');
check('→ 키로 3단계', (await page.textContent('.guide-kicker')).trim() === '설계 원칙');
await page.keyboard.press('ArrowLeft');
check('← 키로 2단계', (await page.textContent('.guide-kicker')).trim() === '함정');
await page.click('#guide-nav li:nth-child(7)');
check('목차 클릭 → 7단계', (await page.textContent('.guide-kicker')).trim() === '동작 예시');
check('현재 항목 하이라이트', await page.evaluate(
  () => document.querySelectorAll('#guide-nav li')[6].classList.contains('on')));

console.log('\n[2b] 가이드 레이아웃 — 셸 밖으로 삐져나가지 않고 내부 스크롤이 산다');
for (const step of [1, 4, 6, 7, 8]) {
  const r = await page.evaluate((s) => {
    document.querySelectorAll('#guide-nav li')[s - 1].click();
    const shell = document.querySelector('.guide-shell').getBoundingClientRect();
    const rail = document.querySelector('.guide-rail').getBoundingClientRect();
    const main = document.querySelector('.guide-main').getBoundingClientRect();
    const body = document.getElementById('guide-body');
    const foot = document.querySelector('.guide-foot').getBoundingClientRect();
    return {
      railInside: rail.top >= shell.top - 1 && rail.bottom <= shell.bottom + 1,
      mainInside: main.top >= shell.top - 1 && main.bottom <= shell.bottom + 1,
      footVisible: foot.bottom <= shell.bottom + 1 && foot.top >= shell.top,
      scrollable: body.scrollHeight <= body.clientHeight + 1 || getComputedStyle(body).overflowY === 'auto',
      navVisible: document.querySelector('#guide-nav li').getBoundingClientRect().top >= shell.top,
    };
  }, step);
  check(`${step}단계 레이아웃`, r.railInside && r.mainInside && r.footVisible && r.scrollable && r.navVisible,
    JSON.stringify(r));
}

console.log('\n[3] 가이드 닫기 (핵심 회귀)');
await page.click('#guide-close');
await page.waitForTimeout(200);
check('닫기 버튼으로 사라진다', !(await shown(page, 'guide')));
check('대시보드 클릭 가능', (await topAt(page, '#run')) === 'ok', await topAt(page, '#run'));

console.log('\n[4] 다시 열기 / ESC / 배경 클릭');
await page.click('#guide-open');
check('상단 버튼으로 재노출', await shown(page, 'guide'));
await page.keyboard.press('Escape');
await page.waitForTimeout(150);
check('ESC로 닫힌다', !(await shown(page, 'guide')));
await page.click('#guide-open');
await page.mouse.click(12, 12);           // 오버레이 배경
await page.waitForTimeout(150);
check('배경 클릭으로 닫힌다', !(await shown(page, 'guide')));
check('닫은 뒤 body 스크롤 복구',
  await page.evaluate(() => document.body.style.overflow === ''));

console.log('\n[5] 설계 실행 → 규칙 모달');
await page.fill('#request', '소아용 플루옥세틴 정제를 설계해줘');
await page.click('#run');
await page.waitForSelector('.chip', { timeout: 240000 });
check('후보 카드에 규칙 칩이 생긴다', (await page.locator('.chip').count()) > 0);
await page.locator('.chip').first().click();
await page.waitForTimeout(900);
check('규칙 모달이 열린다', await shown(page, 'modal'));
check('원본 CSV 행이 보인다', (await page.locator('#modal-body table tr').count()) > 0);
await page.keyboard.press('Escape');
await page.waitForTimeout(200);
check('ESC로 규칙 모달이 닫힌다', !(await shown(page, 'modal')));
await page.locator('.chip').first().click();
await page.waitForTimeout(700);
await page.click('#modal-close');
await page.waitForTimeout(200);
check('✕ 로 규칙 모달이 닫힌다', !(await shown(page, 'modal')));

console.log('\n[6] 실행 결과 렌더링');
check('분자 구조 SVG', await page.evaluate(() => !!document.querySelector('#mol-svg svg')));
check('그래프 노드 점등', await page.evaluate(
  () => document.querySelectorAll('#graph .node.done, #graph .node.active').length > 0));
check('트레이스 이벤트', (await page.locator('.ev').count()) > 5);
await page.waitForSelector('#consensus:not([hidden])', { timeout: 240000 }).catch(() => {});
check('합의 결과', await shown(page, 'consensus'));

console.log('\n[7] 테마 전환');
const before = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
await page.click('#btn-theme');
await page.waitForTimeout(250);
const after = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
check('배경색이 바뀐다', before !== after, `${before} → ${after}`);
check('mm:theme 저장', await page.evaluate(() => !!localStorage.getItem('mm:theme')));
await page.reload({ waitUntil: 'networkidle' });
const persisted = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
check('새로고침 후 유지', persisted === after, `${persisted}`);

console.log('\n[8] 가로 스크롤 / 모바일');
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
check('데스크톱 가로 오버플로 없음', overflow <= 0, `${overflow}px`);
const m = await browser.newPage({ viewport: { width: 390, height: 844 } });
await m.goto(URL, { waitUntil: 'networkidle' });
check('모바일에서 가이드 표시', await shown(m, 'guide'));
await m.click('#guide-next');
await m.click('#guide-close');
await m.waitForTimeout(200);
check('모바일에서 가이드 닫힘', !(await shown(m, 'guide')));
const mo = await m.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
check('모바일 가로 오버플로 없음', mo <= 1, `${mo}px`);
check('모바일에서 실행 버튼 클릭 가능', (await topAt(m, '#run')) === 'ok', await topAt(m, '#run'));

console.log('\n[9] 콘솔 오류');
check('오류 없음', errors.length === 0, errors.join(' | '));

console.log(`\n${failed === 0 ? '전체 통과' : `실패 ${failed}건`}`);
await browser.close();
process.exit(failed === 0 ? 0 : 1);
