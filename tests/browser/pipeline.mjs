// 발표 자료 10쪽 — 로르녹시캄 분산정 전체 파이프라인을 화면 클릭으로 끝까지(실제 LLM 사용).
// 시연 카드 ① → 설계(유동성 42° → 직접타정 유지) → 후보 카드 '이 후보로 개발 착수'(불변 Handoff) → 2단계 LLM 초안으로 1–7단계 → 8 종합 정리(위험평가 PDF) →
// 9단계 CSV(Almotairi 2022 Table 3 실측 15 run) → 10 모형 선택·검증 게이트(네 반응 축소 2차 통과) → 11 곡면 → 12 ANOVA →
// 13 목표 입력 → Overlay plot: control space · 최적 2.9 · 10분 · 7 % → 14 확인계획 잠금(참고: 논문 최적 3 · 11 · 6.23).
//   F1_LLM=dacon CHROME=<chrome> node tests/browser/pipeline.mjs http://localhost:8104/ [스크린샷 폴더]
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const URL = process.argv[2] || 'http://localhost:8104/';
const SHOTS = process.argv[3] || '';
const browser = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
let failed = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${name}${detail ? ' — ' + detail : ''}`); if (!ok) failed++; };
const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 } });
await ctx.addInitScript((v) => { try { localStorage.setItem('f1_guide_seen_v1', '1'); if (v) localStorage.setItem('f1:llm', v); } catch (e) { /* 무시 */ } }, process.env.F1_LLM || '');
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('console', (m) => { if (m.type() === 'error' && !/status of (409|422|503)/.test(m.text())) errors.push(m.text()); });
const shot = async (n) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/p10_${n}.png`, fullPage: false }); };
await page.goto(URL, { waitUntil: 'networkidle' });

const cur = () => page.evaluate(() => document.querySelector('#s2 .s2-step.current')?.dataset.step || null);
async function act(name, opts = {}) {
  const r = page.waitForResponse((x) => x.url().includes('/actions/') && x.request().method() === 'POST', { timeout: opts.timeout || 300000 });
  await page.locator(`#s2 .s2-step.current [data-act="${name}"]`).click();
  await r;
  await page.waitForFunction(() => !document.querySelector('#s2 [data-act]:disabled'), null, { timeout: 300000 }).catch(() => {});
  await page.waitForTimeout(300);
}
async function blocked() {
  return page.$$eval('#s2 .s2-step.current .s2-checks li.blocking', (l) => l.map((x) => x.textContent.trim().slice(0, 140)));
}

console.log('\n[1단계] 시연 카드 ① 로르녹시캄');
await page.locator('.scenario', { hasText: '로르녹시캄' }).click();
await page.waitForSelector('#agent-log #panel-chem', { timeout: 60000 });
const order = await page.evaluate(() => { const ids = [...document.querySelectorAll('#agent-log .ad-msg')].map((r) => r.querySelector('#card-inputs') ? 'inputs' : r.querySelector('#panel-chem') ? 'chem' : r.classList.contains('user') ? 'user' : ''); return ids.filter(Boolean).join('>'); });
check('시연 카드 → 요청 · 실험 데이터 입력 카드 · 물리화학 순서', /user>inputs>chem/.test(order), order);
const filled = await page.$$eval('#agent-log #card-inputs .inputs-field.filled input', (xs) => xs.map((x) => `${x.dataset.key}=${x.value}`));
check('실험 데이터 입력 카드에 시연 값(안식각 42 · Carr 22 · Hausner 1.28 · 용량 8)', ['angle_of_repose=42', 'dose_mg=8'].every((v) => filled.includes(v)), filled.join(' '));
check('입력칸 아래로 · 히어로와 시연 카드는 맨 위에 남음', await page.evaluate(() => !!document.querySelector('#dock-inner #agent-box') && !!document.querySelector('#hello .scenario')));
await page.waitForFunction(() => document.getElementById('run').textContent.trim() === '설계 실행' && (document.querySelector('#agent-log #drq:not([hidden])') || document.querySelector('#agent-log #panel-cands')), null, { timeout: 600000 });
await shot('01_stage1');
const trace = await page.locator('#trace').textContent();
check('유동성 실측으로 경로 판정(직접타정 유지)', /passable|DC/.test(trace), '');
if (await page.locator('#agent-log #drq:not([hidden])').count()) await page.click('#drq-skip');
await page.waitForSelector('#agent-log #panel-cands .dev-start', { timeout: 120000 });
await shot('02_cands');
check('후보 카드에 개발 착수 버튼', true);

console.log('\n[2단계] 개발 착수 → 1–7단계(LLM 초안) → 8 종합 정리');
const evHead = (await page.locator('#agent-log #panel-cands .ev-box .ev-head').first().textContent().catch(() => '')).replace(/\s+/g, ' ');
check('후보 카드에 근거 결손 게이트 판정(발표 ⑤)', /근거 (결손|충족|부적합)/.test(evHead), evHead.slice(0, 90));
await page.locator('#agent-log #panel-cands .dev-start').first().click();
const waive = page.locator('#agent-log #panel-cands .ev-waive:not([hidden])').first();
if (await waive.waitFor({ timeout: 5000 }).then(() => true).catch(() => false)) {
  const pre = await waive.locator('textarea').inputValue();
  check('결손 사유가 미리 채워짐(무엇이 비었는지 · 고칠 수 있음)', /선행 근거/.test(pre) && /T_[A-Z_]+/.test(pre), pre.slice(0, 80));
  await waive.locator('textarea').fill('');
  await waive.locator('.ev-waive-go').click();
  check('사유를 비우면 착수 안 됨(칸 안에 안내)', /사유를 적어/.test(await waive.locator('.ev-waive-msg').textContent()));
  await waive.locator('textarea').fill(pre);
  await waive.locator('.ev-waive-go').click();                       // 미리 채운 사유 그대로 — 한 번 누르면 2단계
}
await page.waitForSelector('#s2 .s2-step.current[data-step="prototype"]', { timeout: 60000 });
check('불변 Handoff(요청 맥락 · fingerprint) 표시', await page.locator('#s2 .s2-handoff code').count() >= 1);
const hoText = (await page.locator('#s2 .s2-handoff').textContent()).replace(/\s+/g, ' ');
check('Handoff에 근거 결손 판정(사유 포함)이 남음', /연구자 사유: 선행 근거/.test(hoText), (hoText.match(/근거 결손 게이트[^|]{0,80}/) || [''])[0]);
const loading = await page.locator('#s2 .s2-handoff').textContent();
const pct = Number((loading.replace(/\s+/g, ' ').match(/약물 함량\s*([\d.]+)/) || [])[1]);
check('Handoff에 약물 함량(저함량 < 5 %)', pct > 0 && pct < 5, `${pct} %`);
await shot('03_prototype');
await act('run');
for (const step of ['qtpp', 'cqa', 'rm_just']) {
  check(`${step} 단계`, await cur() === step, await cur());
  await act('draft');
  const b = await blocked();
  if (b.length) { check(`${step} LLM 초안이 검사 통과`, false, b.join(' | ')); break; }
  await act('approve');
}
if (await cur() === 'rm_matrix') await act('approve');
if (await cur() === 'fp_just') {
  await act('draft');
  const warns = await page.$$eval('#s2 .s2-step.current .s2-checks li', (l) => l.map((x) => x.textContent.trim()));
  check('제형·공정 초안에 혼합 공정 × 함량균일성 High(저함량 경고 없음)', !warns.some((w) => w.includes('RISK_LOW_DOSE')), warns.join(' | ').slice(0, 200));
  const b = await blocked();
  check('제형·공정 초안이 검사 통과', !b.length, b.join(' | '));
  await shot('04_fp_just');
  await act('approve');
}
if (await cur() === 'fp_matrix') await act('approve');
check('8단계 종합 정리(고르는 칸 없음)', await cur() === 'recommend' && await page.locator('#s2 .s2-step.current [data-pick]').count() === 0, await cur());
const riskA = page.locator('#s2 .s2-step.current .s2-risk-pdf a');
check('위험평가 보고서 PDF가 8단계 카드(DoE 변수 후보 아래)에 바로', await riskA.count() === 1);
const riskPdf = await page.request.get(new globalThis.URL(await riskA.getAttribute('href'), URL).href);
check('위험평가 보고서 PDF 내려받기', riskPdf.ok() && (await riskPdf.body()).slice(0, 4).toString() === '%PDF');
await shot('05_recommend');
await act('approve');

console.log('\n[2단계] 9 실험 설계 — CSV 불러오기');
check('실험 설계 단계', await cur() === 'design', await cur());
const paperBtns = await page.$$eval('#s2 .s2-step.current [data-act="use_paper"]', (b) => b.map((x) => x.dataset.paper));
check('논문 값 채우기 버튼 — 이 약물(로르녹시캄) 표가 맨 앞', paperBtns[0] === 'almotairi2022_t3', paperBtns.join(','));
const csvResp = await page.request.get(new globalThis.URL('static/data/almotairi2022_table3.csv', URL).href);
const tmp = path.join(os.tmpdir(), `almotairi2022_table3_${Date.now()}.csv`);
fs.writeFileSync(tmp, await csvResp.body());
await page.locator('#s2 .s2-step.current [data-csv-file]').setInputFiles(tmp);
await page.waitForSelector('#s2 .s2-step.current [data-map] tr[data-col]');
check('CSV 열 역할 자동 인식(X:/Y: 머리글)', await page.$$eval('#s2 .s2-step.current [data-map] [data-role]', (s) => s.map((x) => x.value).join(',')) === 'std,run,f,f,f,r,r,r,r');
await page.click('#s2 .s2-step.current [data-paste-apply]');
check('표 = 15 run · 요인 3 · 반응 4', await page.locator('#s2 [data-edit] table[data-rows="rows"] tbody tr').count() === 15);
await shot('06_design');
await act('approve');

console.log('\n[2단계] 10 회귀 · 11 곡면 · 12 ANOVA');
check('회귀식 단계', await cur() === 'regression', await cur());
const fams = await page.$$eval('#s2 .s2-step.current .s2-reg[data-resp]', (rs) => rs.map((r) => `${r.dataset.resp}:${r.querySelector('[data-family]').value}`).join(' '));
check('선택 모형 = 네 반응 모두 축소 2차(AICc 순위 → 검증 게이트)', fams === 'Dispersion time:Reduced quadratic Friability:Reduced quadratic DE30:Reduced quadratic AV:Reduced quadratic', fams);
const gh = (await page.locator('#s2 .s2-step.current .s2-gate-head').textContent()).replace(/\s+/g, ' ');
check('검증 게이트 통과 4 / 4 반응', /통과 4 \/ 4/.test(gh), gh.slice(0, 40));
await shot('07_regression');
await act('approve');
check('게이트 통과 → 반응 곡면', await cur() === 'surface', await cur());
await page.waitForFunction(() => document.querySelectorAll('#s2-surf-box .rsg-plot').length >= 3, null, { timeout: 120000 }).catch(() => {});
await page.waitForTimeout(2500);
await shot('08_surface');
await act('approve');
check('ANOVA 단계', await cur() === 'anova', await cur());
await act('approve');

console.log('\n[2단계] 13 Design Space');
check('Design Space 단계', await cur() === 'space', await cur());
const specs = { 'Dispersion time': ['LE', '', '180', '분산정 분산 3분 이내'], Friability: ['LE', '', '1', 'USP <1216>'],
  DE30: ['GE', '75', '', '프로젝트 목표(가정)'], AV: ['LE', '', '15', 'USP <905> L1'] };
for (const [resp, [op, lo, hi, basis]] of Object.entries(specs)) {
  const tr = page.locator(`#s2 .s2-step.current tr[data-resp="${resp}"]`);
  await tr.locator('[data-k="op"]').selectOption(op);
  await tr.locator('[data-k="lower"]').fill(lo);
  await tr.locator('[data-k="upper"]').fill(hi);
  await tr.locator('[data-k="basis"]').fill(basis);
}
await act('save');
await page.waitForSelector('#s2 .s2-step.current .s2-kpis', { timeout: 60000 });
const verdict = (await page.locator('#s2 .s2-step.current .s2-verdict').textContent()).replace(/\s+/g, ' ');
check('13단계 승인 가능 — 평균 기준 영역과 control space', /승인 가능/.test(verdict), verdict.slice(0, 80));
const spt = (await page.locator('#s2 .s2-step.current .s2-setpoint').textContent()).replace(/\s+/g, ' ');
check('control space MCC:Mannitol 1.1–3 × Crospovidone 4.6–9.2 @ 10분 · 최적 2.9 · 10 · 7', /1\.1–3/.test(spt) && /4\.6–9\.2/.test(spt) && /2\.9/.test(spt) && /Mixing time 10/.test(spt), spt.slice(0, 200));
await page.waitForFunction(() => { const i = document.querySelector('#s2 .s2-step.current .s2-overlay img'); return i && i.complete && i.naturalWidth > 300; }, null, { timeout: 60000 }).catch(() => {});
check('Overlay plot 그림', await page.evaluate(() => { const i = document.querySelector('#s2 .s2-step.current .s2-overlay img'); return !!i && i.naturalWidth > 300; }));
await page.locator('#s2 .s2-step.current').scrollIntoViewIfNeeded();
await shot('09_space');
await act('approve');

console.log('\n[2단계] 14 확인계획 잠금');
check('확인계획 단계', await cur() === 'vplan', await cur());
await page.fill('#s2 .s2-step.current [data-ref="label"]', '논문 최적 처방(Almotairi 2022)');
const refs = page.locator('#s2 .s2-step.current [data-ref-set]');
const vals = ['3', '11', '6.23'];
for (let i = 0; i < await refs.count(); i++) await refs.nth(i).fill(vals[i]);
await act('save');
const vtxt = (await page.locator('#s2 .s2-step.current table.vplan').textContent()).replace(/\s+/g, ' ');
check('확인점 3 + 참고 배치', ['설정점', '경계점', '강건성', '참고 배치'].every((w) => vtxt.includes(w)));
check('최적점 DE30 예측구간 75.3 – 89.4', /75\.3\s*–\s*89\.4/.test(vtxt), (vtxt.match(/DE30[^%]*/) || [''])[0].slice(0, 80));
await shot('10_vplan');
await act('approve');
check('잠금 → 15단계(확인배치)', await cur() === 'verify', await cur());
const fin = page.locator('#s2 .s2-links a', { hasText: '최종' });
const pdf = await page.request.get(new globalThis.URL(await fin.getAttribute('href'), URL).href);
const body = await pdf.body();
check('최종 보고서 PDF(Design Space · 확인계획 포함)', pdf.ok() && body.slice(0, 4).toString() === '%PDF', `${Math.round(body.length / 1024)} KB`);
await shot('11_verify');
check('콘솔 오류 없음', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
console.log(failed ? `\n실패 ${failed}건` : '\n모두 통과');
process.exit(failed ? 1 : 0);
