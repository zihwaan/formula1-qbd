// 신규 기능 브라우저 검증: 프리셋 → 고정 제약 반려 → lab-in-the-loop 자연어 지시
import { chromium } from 'playwright-core';
const URL = process.argv[2] || 'http://localhost:8102/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const p = await b.newPage({ viewport: { width: 1500, height: 1000 } });
const errs = [];
p.on('pageerror', (e) => errs.push(e.message));
p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
await p.addInitScript(() => localStorage.setItem('f1_guide_seen_v1','1'));
await p.goto(URL, { waitUntil: 'networkidle' });

let fail = 0;
const ck = (n, ok, d='') => { console.log(`${ok?'  ✓':'  ✗'} ${n}${d?' — '+d:''}`); if(!ok) fail++; };

console.log('\n[프리셋]');
ck('버튼 4개', (await p.locator('.preset').count()) === 4);
await p.locator('.preset').first().click();
const filled = await p.evaluate(() => ({
  req: document.getElementById('request').value,
  pin: document.getElementById('pinned').value,
  note: document.getElementById('preset-note').textContent.length,
}));
ck('요청·고정성분·설명이 채워진다', filled.req.includes('플루옥세틴') && filled.pin.includes('Lactose') && filled.note > 50,
   JSON.stringify(filled).slice(0,90));

console.log('\n[고정 제약 → 규칙이 반려]');
await p.click('#run');
await p.waitForFunction(() => document.getElementById('run').textContent.trim() === '설계 실행',
  null, { timeout: 300000 });
await p.waitForTimeout(800);
const traceText = await p.locator('#trace').textContent();
ck('INC002 반려가 트레이스에 뜬다', traceText.includes('INC002'));
ck('제약 충돌 결론이 나온다', /제약|충돌|통과가 없다/.test(traceText), traceText.match(/고정 제약[^\n]{0,60}/)?.[0] || '');
const chipCount = await p.locator('.chip').count();
ck('규칙 칩 생성', chipCount > 0, `${chipCount}개`);

console.log('\n[Lab-in-the-loop]');
await p.click('#labloop > summary');
await p.click('#wl-example');
const notes = await p.inputValue('#wl-notes');
ck('예시 문장 삽입', notes.length > 40);
await p.click('#wl-submit');
await p.waitForSelector('#wl-out .ll-exp', { timeout: 240000 });
const ll = await p.evaluate(() => ({
  read: document.querySelectorAll('#wl-out table.ll-read tr').length,
  obs: !!document.querySelector('#wl-out .ll-obs'),
  findings: document.querySelectorAll('#wl-out .ll-finding').length,
  hypo: !!document.querySelector('#wl-out .ll-hypo'),
  exps: [...document.querySelectorAll('#wl-out .ll-exp')].map((e) => ({
    id: e.querySelector('.ll-id')?.textContent,
    src: e.querySelector('.ll-src a')?.textContent || e.querySelector('.ll-src')?.textContent,
    why: (e.querySelector('.ll-why')?.textContent || '').slice(0, 60),
  })),
}));
ck('자연어에서 측정값 판독', ll.read >= 3, `${ll.read}개 지표`);
ck('비정량 관찰 표시', ll.obs);
ck('규격 이탈 판정 표시', ll.findings >= 3, `${ll.findings}건`);
ck('AI 가설 표시', ll.hypo);
ck('다음 실험 지시 + 출처', ll.exps.length > 0 && ll.exps.every((e) => e.id && e.src),
   JSON.stringify(ll.exps.map((e) => `${e.id}/${e.src}`)));
ll.exps.forEach((e) => console.log(`     ${e.id} · ${e.src} · ${e.why}`));

console.log('\n[콘솔]');
ck('오류 없음', errs.length === 0, errs.slice(0,2).join(' | '));
console.log(fail === 0 ? '\n전체 통과' : `\n실패 ${fail}건`);
await b.close();
process.exit(fail === 0 ? 0 : 1);
