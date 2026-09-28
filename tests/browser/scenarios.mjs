// 시연 카드(발표 자료 ②·③)가 각자의 goal 텍스트가 주장하는 경로를 실제로 밟는지 확인한다(①은 pipeline.mjs).
// 실제 Groq LLM을 태우므로(GROQ_API_KEY 필요) 전체 실행에 몇 분 걸린다. 키가 없으면 결정론
// 폴백으로 내려가 통과는 하지만 "진짜 LLM이 돌았는지"는 검증하지 못한다 — 배포 전에는 키를
// 넣고 한 번 돌려서 판정·심사·진단이 실제로 LLM에서 나오는지 확인할 것(2026-09-16, 죽은
// Groq 모델 ID가 항상 결정론 폴백으로 조용히 떨어지게 만든 사고가 바로 이 검증 부재 때문이었다).
import { chromium } from 'playwright-core';
const URL = process.argv[2] || 'http://localhost:8000/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const p = await b.newPage({ viewport: { width: 1600, height: 1100 } });
// 모델 선택(기본 Groq). 무료 한도가 바닥났을 때 F1_LLM=dacon 으로 같은 흐름을 대회 API로 검증할 수 있다(로컬=full 권한).
if (process.env.F1_LLM) await p.addInitScript((v) => {{ try {{ localStorage.setItem('f1:llm', v); }} catch (e) {{}} }}, process.env.F1_LLM);
const errs = [];
p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
p.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
await p.addInitScript(() => localStorage.setItem('f1_guide_seen_v1', '1'));
await p.goto(URL, { waitUntil: 'networkidle' });

let fail = 0;
const ck = (n, ok, d = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${n}${d ? ' — ' + d : ''}`); if (!ok) fail++; };

async function waitDone(timeout = 480000) {
  await p.waitForFunction(() => document.getElementById('run').textContent.trim() === '설계 실행',
    null, { timeout });
}

// 발표 자료의 시연 ②·③. 시연 ①(로르녹시캄 전체 파이프라인)은 2단계까지 이어지므로 pipeline.mjs가 따로 끝까지 걷는다.
ck('시연 카드 4장(①②③ + 2단계 CBD)', await p.locator('#scenarios .scenario').count() === 4);

// ── 시연 ② 고령자 암로디핀 + 유당 고정 ──────────────────────────────────
console.log('\n[시연 ② · 고령자용 암로디핀 2.5 mg — 유당을 고정하면?]');
await p.locator('.scenario', { hasText: '암로디핀' }).click();
await waitDone();
await p.waitForTimeout(1000);
let trace = await p.locator('#trace').textContent();
ck('1차 아민 × 유당 금기(INC001) 또는 다성분 금기(MC00x) 발동', /INC001|MC00\d/.test(trace), (trace.match(/INC001|MC00\d/g) || []).join(','));
ck('“이 제약으로는 통과 없음” 결론(재설계 루프 없이 종료)', /제약|통과가 없다|불가능/.test(trace));
ck('대화에 후보 카드가 놓인다(결론 포함)', await p.locator('#agent-log #panel-cands').count() === 1);
const concl = (await p.locator('#agent-log #consensus.infeasible').textContent().catch(() => '')).replace(/\s+/g, ' ');
ck('후보 카드 안에 결론 · 대안(모바일에서도 보임)', /통과하는 처방이 없음/.test(concl) && /대안/.test(concl), concl.slice(0, 120));
ck('소집 예정 심사관 = 고령자 안전 + 공정 실현성(발표 11쪽)', /고령자 안전 심사관/.test(concl) && /공정 실현성 심사관/.test(concl) && !/소아 안전/.test(concl),
  (concl.match(/소집 예정[^—]*/) || [''])[0]);

// ── 시연 ③ VX-770 cold start ─────────────────────────────────────────
console.log('\n[시연 ③ · 개발코드 VX-770 — 구조식만 있는 신규물질]');
await p.locator('.scenario', { hasText: 'VX-770' }).click();
await waitDone();
await p.waitForTimeout(1500);
ck('데이터 요청 카드가 대화에 놓인다(후보 카드는 그 뒤)', await p.evaluate(() => !!document.querySelector('#agent-log #drq:not([hidden])')));
const reqText = await p.locator('#drq-body').textContent();
ck('Tm을 가르는 DSC 측정 요청', /DSC|시차주사/.test(reqText), reqText.replace(/\s+/g, ' ').slice(0, 120));
const autoFilled = await p.evaluate(() => [...document.querySelectorAll('#drq-body .drq-num input')].some((i) => i.value));
ck('시스템이 측정값을 대신 채우지 않는다(요청 칸은 비어 있음)', !autoFilled);
const prefill = await p.inputValue('#agent-input');
ck('시연 카드의 측정 문장은 입력칸에만(보내기는 사람이)', prefill.includes('Tm 317'), prefill);
const before = await p.$$eval('#agent-log .ad-card', (c) => c.length);
await p.click('#agent-send');
await p.waitForFunction((n) => document.querySelectorAll('#agent-log .ad-card').length > n, before, { timeout: 120000 });
const card = p.locator('#agent-log .ad-card').last();
ck('측정값 제출 카드(Tm · 용해도)', /tm_c|317/.test(await card.innerText()), (await card.innerText()).replace(/\s+/g, ' ').slice(0, 120));
await card.locator('.ad-run').click();
await p.waitForFunction(() => (document.getElementById('drq-out') || {}).textContent?.includes('plan_signature'), null, { timeout: 120000 }).catch(() => {});
const drqOutText = await p.locator('#drq-out').textContent().catch(() => '');
ck('재계산 → 분무건조 ASD가 계획에(그래프 재실행 없음)', drqOutText.includes('ASD_SDD'), drqOutText.replace(/\s+/g, ' ').slice(0, 160));
ck('값 제출 뒤 후보 처방 카드가 대화에 이어진다', await p.locator('#agent-log #panel-cands').count() === 1);
const bodyText = await p.evaluate(() => document.body.innerText);
ck('화면에 실제 물질명이 없다(개발코드만)', !/ivacaftor|kalydeco|이바카프토|칼리데코/i.test(bodyText));
ck('시연 카드는 대화 시작 뒤에도 맨 위에 남는다', await p.locator('#hello .scenario').count() === 4);

console.log('\n[콘솔/페이지 오류]');
ck('오류 0건', errs.length === 0, errs.slice(0, 5).join(' | '));

await b.close();
console.log(`\n${fail === 0 ? '전부 통과' : fail + '건 실패'}`);
process.exit(fail === 0 ? 0 : 1);
