// 시나리오 버튼 = 즉시 실행 + 해설 흐름 검증
import { chromium } from 'playwright-core';
const URL = process.argv[2] || 'http://localhost:8102/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const p = await b.newPage({ viewport: { width: 1500, height: 1050 } });
const errs = []; p.on('pageerror', e=>errs.push(e.message)); p.on('console', m=>{if(m.type()==='error')errs.push(m.text());});
await p.addInitScript(() => localStorage.setItem('f1_guide_seen_v1','1'));
await p.goto(URL, { waitUntil: 'networkidle' });
let fail=0; const ck=(n,ok,d='')=>{console.log(`${ok?'  ✓':'  ✗'} ${n}${d?' — '+d:''}`); if(!ok)fail++;};

console.log('\n[시나리오 카드]');
const cards = await p.locator('.scenario').count();
ck('카드 3개', cards === 3, `${cards}개`);
const titles = await p.locator('.scenario-title').allTextContents();
console.log('    ', titles.join(' / '));

console.log('\n[버튼 → 즉시 실행 + 해설]');
await p.locator('.scenario').first().click();
await p.waitForTimeout(1200);
ck('별도 실행 클릭 없이 시작됨', await p.evaluate(() => document.getElementById('run').disabled));
ck('시나리오 목표 설명 표시', await p.evaluate(() => !document.getElementById('scenario-goal').hidden));
await p.waitForFunction(() => document.querySelectorAll('#narration .nr').length >= 2, null, {timeout:120000});
await p.waitForFunction(() => document.getElementById('run').textContent.trim()==='설계 실행', null, {timeout:300000});
await p.waitForTimeout(800);
const nr = await p.evaluate(() => [...document.querySelectorAll('#narration .nr')].map(e => ({
  n: e.querySelector('.nr-n').textContent,
  title: e.querySelector('.nr-head b').textContent,
  layer: e.querySelector('.nr-layer').textContent,
  why: !!e.querySelector('.nr-why'),
})));
ck('해설 카드가 순서대로 쌓인다', nr.length >= 3, `${nr.length}장`);
ck('모든 카드에 담당 계층 표기', nr.every(x=>x.layer));
ck('모든 카드에 "왜 중요한가"', nr.every(x=>x.why));
nr.forEach(x=>console.log(`     ${x.n}. [${x.layer}] ${x.title}`));
ck('규칙이 막은 단계가 해설에 있다', nr.some(x=>/규칙이 AI의 설계를 막았다|통과하는 처방이 없다/.test(x.title)));

console.log('\n[콘솔]');
ck('오류 없음', errs.length===0, errs.slice(0,2).join(' | '));
console.log(fail===0 ? '\n전체 통과' : `\n실패 ${fail}건`);
await b.close(); process.exit(fail===0?0:1);
