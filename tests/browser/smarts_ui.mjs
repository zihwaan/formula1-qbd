import { chromium } from 'playwright-core';
const URL = process.argv[2] || 'https://zihwan.com/f/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const p = await b.newPage({ viewport: { width: 1500, height: 1050 } });
const errs=[]; p.on('pageerror',e=>errs.push(e.message)); p.on('console',m=>{if(m.type()==='error')errs.push(m.text());});
await p.addInitScript(() => localStorage.setItem('f1_guide_seen_v1','1'));
await p.goto(URL, { waitUntil: 'networkidle' });
let fail=0; const ck=(n,ok,d='')=>{console.log(`${ok?'  ✓':'  ✗'} ${n}${d?' — '+d:''}`); if(!ok)fail++;};

console.log('\n[SMARTS 검사]');
await p.click('#smarts > summary');
const opts = await p.locator('#sm-pick option').count();
const groups = await p.locator('#sm-pick optgroup').count();
ck('룰북 패턴 전량 노출', opts > 70 && groups >= 9, `${opts-1}종 · ${groups}개 절`);
await p.selectOption('#sm-pick', '0');
const note = await p.locator('#sm-out').textContent();
ck('패턴이 발동시키는 규칙 표시', /incompatibility|규칙/.test(note), note.replace(/\s+/g,' ').slice(0,80));

// 아세트아미노펜 × 1차 아민 = 없어야 함
await p.fill('#sm-smiles', 'CC(=O)Nc1ccc(O)cc1');
await p.click('#sm-run');
await p.waitForSelector('#sm-out .sm-result', { timeout: 30000 });
let r = await p.locator('#sm-out .sm-result').textContent();
ck('아세트아미노펜에 1차 아민 없음', /구조 없음/.test(r), r.replace(/\s+/g,' ').slice(0,60));

// 아미드 패턴 = 있어야 함 + 구조 강조
await p.fill('#sm-pattern', '[NX3][CX3](=[OX1])');
await p.click('#sm-run');
await p.waitForTimeout(1500);
r = await p.locator('#sm-out .sm-result').textContent();
const svg = await p.locator('#sm-out .sm-mol svg').count();
ck('아미드 패턴 일치 + 구조 강조', /일치/.test(r) && svg > 0, r.replace(/\s+/g,' ').slice(0,50));

// 잘못된 패턴 처리
await p.fill('#sm-pattern', '[[bad');
await p.click('#sm-run');
await p.waitForTimeout(1500);
r = await p.locator('#sm-out').textContent();
ck('잘못된 패턴 안내', /해석할 수 없/.test(r));

console.log('\n[시나리오 카드]');
ck('카드 3개', (await p.locator('.scenario').count()) === 3);
const durs = await p.locator('.scenario-run').allTextContents();
ck('소요시간 표기', durs.every(d=>/분/.test(d)), durs.join(' / '));

console.log('\n[콘솔]');
ck('오류 없음', errs.length===0, errs.slice(0,2).join(' | '));
console.log(fail===0 ? '\n전체 통과' : `\n실패 ${fail}건`);
await b.close(); process.exit(fail===0?0:1);
