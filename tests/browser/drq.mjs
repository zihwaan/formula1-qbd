// 데이터 요청 패널 — 타입별 입력 칸 · 원본 첨부 · 첨부 해석 초안 → 입력 칸 → 제출 흐름(측정값 입력 개선 요청서 과제 1–4).
// 시나리오 3(이부프로펜 200 mg)으로 요청 패널을 띄운 뒤, DSC 카드에 기기 원자료(.xy)를 올리고 코드 해석 초안을 확정해 제출한다.
// .xy 곡선은 파서 동작만 확인하려고 이 테스트 안에서 만든 곡선이다(화면·보고서에 쓰는 자료가 아님).
import { chromium } from 'playwright-core';
const URL = process.argv[2] || 'http://localhost:8000/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const p = await b.newPage({ viewport: { width: 1600, height: 1100 } });
if (process.env.F1_LLM) await p.addInitScript((v) => { try { localStorage.setItem('f1:llm', v); } catch (e) {} }, process.env.F1_LLM);
const errs = [];
p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
p.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
await p.addInitScript(() => localStorage.setItem('f1_guide_seen_v1', '1'));
await p.goto(URL, { waitUntil: 'networkidle' });

let fail = 0;
const ck = (n, ok, d = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${n}${d ? ' — ' + d : ''}`); if (!ok) fail++; };

console.log('\n[1] 요청 패널의 입력 칸은 필드 정의의 타입을 따른다');
// 시연 쿼리 카드 3(VX-770 cold start — 구조식·용량만): Tm을 몰라 DSC(Tier 1) 요청이 뜨는 입력
await p.waitForFunction(() => window.F1Discovery, null, { timeout: 15000 });
await p.evaluate(() => window.F1Discovery.startRunWith({
  request: '신규 후보물질 VX-770의 성인용 경구 정제 제형 전략을 세워 줘. 1회 150 mg이고, 구조식만 있고 실측 자료는 거의 없어.',
  smiles: 'CC(C)(C)C1=CC(=C(C=C1NC(=O)C2=CNC3=CC=CC=C3C2=O)O)C(C)(C)C',
  measured_params: { dose_mg: 150 } }));
await p.waitForFunction(() => document.getElementById('run').textContent.trim() === '설계 실행', null, { timeout: 300000 });
await p.waitForTimeout(1500);
ck('데이터 요청 패널이 보인다', await p.evaluate(() => !document.getElementById('drq').hidden));
const types = await p.evaluate(() => [...document.querySelectorAll('#drq-body [data-key]')].map((e) => [e.dataset.key, e.dataset.type, e.tagName]));
ck('모든 입력 칸에 타입이 있다', types.length > 0 && types.every(([, t]) => t), JSON.stringify(types.slice(0, 8)));
ck('bool·enum 필드는 선택 목록으로 그린다', types.filter(([, t]) => t === 'bool' || t === 'enum').every(([, , tag]) => tag === 'SELECT'));
ck('number 필드는 숫자 칸', types.filter(([, t]) => t === 'number').every(([, , tag]) => tag === 'INPUT'));
const cards = await p.locator('#drq-body .drq-req').count();
const attaches = await p.locator('#drq-body .drq-attach input[type="file"]').count();
ck('요청 카드마다 원본 첨부 칸', cards > 0 && cards === attaches, `${cards} cards / ${attaches} file inputs`);

console.log('\n[2] DSC 원자료 첨부 → 코드 해석 초안 → 입력 칸 → 제출');
const dscInput = p.locator('#drq-body .drq-attach input[data-mid="M_DSC"]');
if (!(await dscInput.count())) {
  ck('DSC 요청 카드가 있다(이 시나리오의 전제)', false);
} else {
  // 25–250 °C, 1 °C 간격, 기준선 0 · 180 °C 부근 흡열(아래 방향) 하나
  let xy = 'Temperature(C)\tHeatFlow(mW)\n';
  for (let t = 25; t <= 250; t += 0.5) xy += `${t}\t${(-8 * Math.exp(-((t - 180) ** 2) / (2 * 2.5 ** 2))).toFixed(4)}\n`;
  await dscInput.setInputFiles({ name: 'dsc_run.xy', mimeType: 'text/plain', buffer: Buffer.from(xy) });
  await p.waitForSelector('#drq-body .drq-files[data-mid="M_DSC"] li', { timeout: 15000 });
  const fileText = await p.locator('#drq-body .drq-files[data-mid="M_DSC"] li').first().textContent();
  ck('첨부 목록에 파일명·sha256', fileText.includes('dsc_run.xy') && fileText.includes('sha256'));
  // 같은 파일을 다시 올려도 한 줄(내용 해시로 중복 제거)
  await dscInput.setInputFiles({ name: 'dsc_run.xy', mimeType: 'text/plain', buffer: Buffer.from(xy) });
  await p.waitForTimeout(1500);
  ck('같은 내용은 한 번만 보관', (await p.locator('#drq-body .drq-files[data-mid="M_DSC"] li').count()) === 1);

  await p.locator('#drq-body .drq-files[data-mid="M_DSC"] .drq-interpret').first().click();
  await p.waitForSelector('.interp-overlay', { timeout: 20000 });
  const status = await p.locator('.interp-overlay .interp-status').textContent();
  ck('초안은 "미확인"으로 뜬다', status.includes('미확인'));
  const tm = Number(await p.locator('.interp-overlay [data-key="tm_c"]').inputValue());
  ck('DSC onset 초안이 흡열 앞쪽(170–180 °C)', tm > 170 && tm < 180, String(tm));
  const why = await p.locator('.interp-overlay').textContent();
  ck('계산하지 않은 값은 이유를 단다(융해열)', why.includes('승온속도'));
  ck('흡열 방향 가정을 적는다', why.includes('가정'));
  await p.click('.interp-overlay .interp-apply');
  await p.waitForTimeout(300);
  ck('해석 창이 닫힌다', !(await p.locator('.interp-overlay').count()));
  const filled = await p.locator('#drq-body .drq-req[data-mid="M_DSC"] [data-key="tm_c"]').inputValue();
  ck('카드 입력 칸이 초안으로 채워진다', Number(filled) === tm, filled);
  ck('자동 제출하지 않는다', !(await p.locator('#drq-out').count()) || !(await p.locator('#drq-out').textContent()).includes('plan_signature'));

  const resp = p.waitForResponse((r) => r.url().includes('/measurements') && r.request().method() === 'POST', { timeout: 60000 });
  await p.click('#drq-submit');
  const r = await resp;
  const sent = JSON.parse(r.request().postData() || '{}');
  ck('제출 성공', r.ok(), String(r.status()));
  ck('제출 출처 = instrument_draft', sent.source === 'instrument_draft', sent.source);
  ck('제출에 첨부 id가 실린다', (sent.attachments?.M_DSC || []).length === 1);
  ck('tm_c는 숫자로 보낸다', typeof sent.measurements?.tm_c === 'number');
  await p.waitForTimeout(1500);
  const narr = await p.locator('#narration').textContent().catch(() => '');
  ck('해설에 원본 첨부 기록', narr.includes('dsc_run.xy'));
}

console.log('\n[3] 콘솔 오류(여기까지 — 다음 단계는 일부러 422를 받는다)');
ck('오류 없음', errs.length === 0, errs.slice(0, 3).join(' | '));

console.log('\n[4] 타입이 틀린 값은 서버가 받지 않는다');
const rid = await p.evaluate(() => window.F1Discovery.runId());
const status422 = await p.evaluate(async (id) => {
  const res = await fetch(`api/runs/${id}/measurements`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ measurements: { is_amorphous_halo: 1 }, grade: 'self_measured', source: 'form' }) });
  return res.status;
}, rid);
ck('bool 필드에 1 → 422', status422 === 422, String(status422));

await b.close();
console.log(fail ? `\n${fail}건 실패` : '\n전체 통과');
process.exit(fail ? 1 : 0);
