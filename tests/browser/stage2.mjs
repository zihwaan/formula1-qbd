// 2단계(Design Space 도출) — CBD 논문 시연 카드로 15단계 중 13단계(Design Space)까지 클릭으로 걷는다. LLM 없이(논문 값) 돈다.
// CBD는 논문 규격(경도 4–6 kgf 등)에서 미래 배치 공동확률 ≥ 0.90인 영역이 없어 13단계에서 멈추는 것이 정답이다(규격을 완화하지 않는다).
// 편집(행·열 추가/삭제, 붙여넣기), 승인 차단, 다시 열기(stale), 위험평가·최종 보고서 PDF, 반응 곡면 그림 첨부,
// 데스크톱 1440과 휴대폰 390에서 가로 넘침 없음까지 본다.
//   node tests/browser/stage2.mjs http://localhost:8104/ [스크린샷 폴더]
import { chromium } from 'playwright-core';

const URL = process.argv[2] || 'http://localhost:8104/';
const SHOTS = process.argv[3] || '';
const browser = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
let failed = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) failed++;
};

async function open(width, height) {
  const ctx = await browser.newContext({ viewport: { width, height } });
  await ctx.addInitScript(() => { try { localStorage.setItem('f1_guide_seen_v1', '1'); } catch (e) { /* 무시 */ } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon|Failed to load resource: the server responded with a status of 409/.test(m.text())) errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  await page.goto(URL, { waitUntil: 'networkidle' });
  await page.evaluate(() => { const g = document.getElementById('guide'); if (g && !g.hidden) document.getElementById('guide-close').click(); });
  return { ctx, page, errors };
}

const current = (page) => page.evaluate(() => document.querySelector('#s2 .s2-step.current')?.dataset.step || (window.F1Stage2.view()?.done ? 'done' : null));
const overflow = (page) => page.evaluate(() => {
  const t = document.querySelector('.thread');
  return Math.max(document.documentElement.scrollWidth - innerWidth, t.scrollWidth - t.clientWidth);
});

async function act(page, name) {
  const btn = page.locator(`#s2 .s2-step.current [data-act="${name}"]`);
  const resp = page.waitForResponse((r) => r.url().includes('/api/stage2/studies/') && r.request().method() === 'POST' && r.url().includes(`/actions/`), { timeout: 60000 });
  await btn.click();
  const r = await resp;
  // 곡면 확인은 그림 첨부 → 승인 두 번 부른다
  if (name === 'approve') await page.waitForTimeout(400);
  await page.waitForFunction(() => !document.querySelector('#s2 .s2-step.current [data-act]:disabled'), null, { timeout: 60000 }).catch(() => {});
  return r.status();
}

async function walk(page, label, { edits }) {
  const shot = async (n) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/s2_${label}_${n}.png`, fullPage: false }); };
  await page.locator('.scenario', { hasText: 'CBD' }).click();
  await page.waitForSelector('#s2 .s2-step.current[data-step="prototype"]', { timeout: 20000 });
  check(`[${label}] CBD 시연 → 2단계 프로토타입 카드`, true);
  check(`[${label}] 프로토타입 표 = Table 1 (7성분)`, await page.locator('#s2 .s2-step.current [data-edit] table[data-rows="ingredients"] tbody tr').count() === 7);
  await shot('01_prototype');
  await act(page, 'run');
  check(`[${label}] 실행 → QTPP`, await current(page) === 'qtpp');

  if (edits) {
    const rows = () => page.locator('#s2 .s2-step.current [data-edit] table[data-rows="items"] tbody tr').count();
    await act(page, 'use_reference');
    const n0 = await rows();
    await page.click('#s2 .s2-step.current [data-row-add="items"]');
    check(`[${label}] QTPP 행 추가`, await rows() === n0 + 1);
    await page.locator('#s2 .s2-step.current [data-edit] table[data-rows="items"] tbody tr').last().locator('[data-row-del]').click();
    check(`[${label}] QTPP 행 삭제`, await rows() === n0);
    await page.locator('#s2 .s2-step.current [data-edit] table[data-rows="items"] tbody tr').first().locator('[data-k="target"]').fill('');
    await act(page, 'approve');
    check(`[${label}] 목표를 비우면 승인 막힘(QTPP_FIELD)`, await current(page) === 'qtpp'
      && await page.locator('#s2 .s2-step.current .s2-checks li.blocking', { hasText: 'QTPP_FIELD' }).count() > 0);
  }
  await act(page, 'use_reference');
  await act(page, 'approve');
  check(`[${label}] QTPP 승인 → CQA`, await current(page) === 'cqa');
  check(`[${label}] 승인한 QTPP는 접힌 카드`, await page.locator('#s2 .s2-step.approved[data-step="qtpp"] details').count() === 1);

  for (const [step, next] of [['cqa', 'rm_just'], ['rm_just', 'rm_matrix']]) {
    await act(page, 'use_reference');
    await act(page, 'approve');
    check(`[${label}] ${step} → ${next}`, await current(page) === next);
  }
  await shot('05_rm_matrix');
  check(`[${label}] 원료 행렬(Table 5) = 논문과 모든 칸 같음`, await page.locator('#s2 .s2-step.current .s2-cmp', { hasText: '모든 칸이 같습니다' }).count() === 1);
  await act(page, 'approve');
  if (edits) {
    await page.click('#s2 .s2-step.current [data-var-add]');
    check(`[${label}] 변수 추가 칩`, await page.locator('#s2 .s2-step.current [data-var]').count() === 1);
    await page.locator('#s2 .s2-step.current [data-var] input[data-k="name"]').fill('MCC');
    await page.click('#s2 .s2-step.current [data-fill-missing]');
    check(`[${label}] 빈 칸 행 만들기`, await page.locator('#s2 .s2-step.current [data-edit] table[data-rows="items"] tbody tr').count() === 1);
    await act(page, 'approve');
    check(`[${label}] 근거 없는 행은 승인 막힘`, await current(page) === 'fp_just'
      && await page.locator('#s2 .s2-step.current .s2-checks li.blocking').count() > 0);
  }
  await act(page, 'use_reference');
  await act(page, 'approve');
  check(`[${label}] fp_just → fp_matrix`, await current(page) === 'fp_matrix');
  check(`[${label}] 제형·공정 행렬(Table 7) = 논문과 같음`, await page.locator('#s2 .s2-step.current .s2-cmp', { hasText: '모든 칸이 같습니다' }).count() === 1);
  await act(page, 'approve');
  check(`[${label}] → 8단계 종합 정리`, await current(page) === 'recommend');
  check(`[${label}] 종합 행렬(원료 + 제형·공정)`, await page.locator('#s2 .s2-step.current table.merged').count() === 1);
  check(`[${label}] DoE 변수 후보는 목록만(고르는 칸·LLM 추천 없음)`, await page.locator('#s2 .s2-step.current [data-pick], #s2 .s2-step.current [data-act="draft"], #s2 .s2-step.current [data-act="use_reference"]').count() === 0
    && await page.locator('#s2 .s2-step.current .s2-cands li').count() >= 1);
  // 위험평가 보고서는 8단계에 들어오자마자 — DoE 변수 후보 목록 바로 아래
  const riskA = page.locator('#s2 .s2-step.current .s2-risk-pdf a', { hasText: '위험평가' });
  check(`[${label}] 위험평가 보고서 PDF가 8단계 카드(DoE 변수 후보 아래)에`, await riskA.count() === 1
    && await page.evaluate(() => { const l = document.querySelector('#s2 .s2-step.current .s2-cands'), a = document.querySelector('#s2 .s2-step.current .s2-risk-pdf');
      return !!(l && a && (l.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING)); }));
  const risk = await page.request.get(new globalThis.URL(await riskA.getAttribute('href'), URL).href);
  check(`[${label}] 위험평가 보고서 PDF(확인 전에 바로)`, risk.ok() && (await risk.body()).slice(0, 4).toString() === '%PDF');
  await shot('08_recommend');
  await act(page, 'approve');
  check(`[${label}] 확인만으로 → 실험 설계`, await current(page) === 'design');
  check(`[${label}] 8단계를 지나면 맨 아래 링크 모음에 위험평가 보고서`, await page.locator('#s2 > .s2-links a', { hasText: '위험평가' }).count() === 1);

  const heads = (k) => page.locator(`#s2 .s2-step.current th.${k} input[data-k="name"]`).count();
  if (edits) {
    const f0 = await heads('f');
    const n0 = await page.locator('#s2 .s2-step.current th.f input[data-k="name"]').first().inputValue();
    check(`[${label}] 설계 표 초안 = 빈 요인 열 1개(요인은 연구자가 정함)`, f0 === 1 && n0 === '', `요인 ${f0} · "${n0}"`);
    check(`[${label}] 요인 이름칸에 High 변수 제안 목록`, await page.locator('#s2-factor-hints option').count() >= 1);
    await page.click('#s2 .s2-step.current [data-col-add="f"]');
    await page.click('#s2 .s2-step.current [data-col-add="f"]');
    check(`[${label}] 요인 열 추가(최대 3)`, await heads('f') === 3);
    check(`[${label}] 요인 3개면 [+ 요인] 잠김`, await page.locator('#s2 .s2-step.current [data-col-add="f"]').isDisabled());
    await page.locator('#s2 .s2-step.current th.f [data-col-del]').last().click();
    check(`[${label}] 요인 열 삭제`, await heads('f') === 2);
    const r1 = await heads('r');
    await page.locator('#s2 .s2-step.current th.r [data-col-del]').last().click();
    await page.click('#s2 .s2-step.current [data-col-add="r"]');
    check(`[${label}] 반응 열 삭제·추가(최대 4)`, await heads('r') === r1, `반응 ${r1}`);
    await page.click('#s2 .s2-step.current [data-rows-add5]');
    check(`[${label}] 행 5개 추가`, await page.locator('#s2 .s2-step.current [data-edit] table[data-rows="rows"] tbody tr').count() >= 5);
    await act(page, 'save');
    check(`[${label}] 빈 표 저장 → 승인 불가 표시`, await page.locator('#s2 .s2-step.current .s2-checks li.blocking').count() > 0);
  }
  await act(page, 'use_reference');
  check(`[${label}] 논문 Table 9 = 17 run × 요인 3 × 반응 3`, await page.locator('#s2 .s2-step.current [data-edit] table[data-rows="rows"] tbody tr').count() === 17
    && await heads('f') === 3 && await heads('r') === 3);
  await shot('09_design');
  await act(page, 'approve');
  check(`[${label}] → 회귀식`, await current(page) === 'regression');
  const coded = await page.locator('#s2 .s2-step.current .s2-reg', { hasText: 'Hardness' }).locator('.s2-eq code').first().textContent();
  check(`[${label}] Hardness coded 식 = Table 10`, /6\.04\d* \+ 1\.00\d*X1 \+ 0\.558\d*X2 \+ 0\.156\d*X3/.test(coded.replace(/\s+/g, ' ')), coded);
  await act(page, 'use_reference');
  check(`[${label}] 논문 모형(DT 2차 · 마손도 2FI) → 과적합 의심 표시`, await page.locator('#s2 .s2-step.current .s2-flag').count() >= 2);
  await act(page, 'approve');
  check(`[${label}] 사유 없이 승인하면 막힘(REG_OVERFIT_REASON)`, await page.locator('#s2 .s2-step.current .s2-checks li.blocking', { hasText: 'REG_OVERFIT_REASON' }).count() === 1);
  await page.fill('#s2 .s2-step.current [data-note]', '논문이 보고한 모형 차수를 그대로 비교하려고 수용');
  await shot('10_regression');
  await act(page, 'approve');
  check(`[${label}] → 반응 곡면`, await current(page) === 'surface');
  await page.waitForFunction(() => document.querySelectorAll('#s2-surf-box .rsg-plot').length >= 3 && [...document.querySelectorAll('#s2-surf-box .rsg-plot')].every((d) => d.querySelector('canvas, svg')), null, { timeout: 60000 });
  const cells = await page.locator('#s2-surf-box .rsg-plot').count();
  check(`[${label}] 곡면 격자(반응 3 × 단면 3)`, cells === 9, `${cells}칸`);
  await shot('11_surface');
  await act(page, 'approve');
  await page.waitForFunction(() => document.querySelector('#s2 .s2-step.current')?.dataset.step === 'anova', null, { timeout: 60000 });
  check(`[${label}] 곡면 확인 → ANOVA`, true);
  const hard = page.locator('#s2 .s2-step.current .s2-reg', { hasText: 'Hardness' });
  const model = await hard.locator('tr', { hasText: 'Model' }).first().textContent();
  check(`[${label}] Hardness ANOVA Model SS 10.73 · p 0.0005`, /10\.73/.test(model) && /0\.0005/.test(model), model.replace(/\s+/g, ' '));
  await shot('12_anova');
  await act(page, 'approve');
  check(`[${label}] ANOVA 확인 → 13 Design Space`, await current(page) === 'space');
  await act(page, 'use_reference');
  const kpi = (await page.locator('#s2 .s2-kpis').textContent()).replace(/\s+/g, ' ');
  check(`[${label}] 논문 규격 → 평균 기준 영역은 있지만 공동확률 ≥ 0.9는 0 %`, /≥ 0\.9\s*0\.0%/.test(kpi) && /47\.9%/.test(kpi), kpi.slice(0, 120));
  await act(page, 'approve');
  check(`[${label}] 영역 없음 → 승인 막힘(SPACE_EMPTY) · 규격 완화 안 함`, await current(page) === 'space'
    && await page.locator('#s2 .s2-step.current .s2-checks li.blocking', { hasText: 'SPACE_EMPTY' }).count() === 1);
  await shot('13_space');
  const fin = await page.locator('#s2 .s2-links a', { hasText: '최종' }).getAttribute('href');
  const pdf = await page.request.get(new globalThis.URL(fin, URL).href);
  const body = await pdf.body();
  check(`[${label}] 최종 보고서 PDF(곡면 그림 · 영역 결과 포함)`, pdf.ok() && body.slice(0, 4).toString() === '%PDF' && body.length > 150000, `${Math.round(body.length / 1024)} KB`);
  check(`[${label}] 가로 넘침 없음`, await overflow(page) <= 1, `${await overflow(page)}px`);
}

console.log('\n[데스크톱 1440] CBD 1–13단계 + 편집·차단');
{
  const { ctx, page, errors } = await open(1440, 950);
  check('처음 화면 — 가운데 입력칸', await page.locator('#hello #agent-input').count() === 1);
  const ph = await page.getAttribute('#agent-input', 'placeholder');
  check('플레이스홀더 문구', ph.startsWith('무엇을 설계할까요? 약 이름(또는 SMILES), 대상 환자, 제형, 1회 용량을 말씀해 주시면'));
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/s2_desk_00_hello.png` });
  await walk(page, 'desk', { edits: true });
  // 다시 열기 → 뒤 단계는 stale
  await page.locator('#s2 .s2-step[data-step="design"] details summary').click();
  await page.locator('#s2 .s2-step[data-step="design"] [data-act="reopen"]').click();
  await page.waitForSelector('#s2 .s2-step.current[data-step="design"]');
  check('설계 표 다시 열기 → 뒤 단계 "다시 확인 필요"', await page.locator('#s2 .s2-step.stale').count() >= 2);
  await page.click('#s2-menu > summary');
  check('마스트헤드 "2단계 기록"에 study', await page.locator('#side-s2 [data-s2]').count() >= 1);
  await page.click('#s2-menu > summary');
  // 오른쪽 관측 칼럼 — 넓은 화면은 처음부터 펼쳐져 있다
  check('관측 칼럼 기본 펼침(에이전트 흐름)', await page.getAttribute('#drawer', 'data-size') === 'open');
  await page.click('.rail-tab[data-pane="trace"]');
  check('탭 전환 → 실행 트레이스', await page.locator('.drawer-pane[data-pane="trace"]:not([hidden])').count() === 1);
  await page.click('#drawer-size');
  check('서랍 크게', await page.getAttribute('#drawer', 'data-size') === 'wide');
  await page.click('#drawer-size');
  await page.click('#drawer-close');
  check('서랍 닫힘', await page.getAttribute('#drawer', 'data-size') === 'closed');
  check('콘솔 오류 없음', errors.length === 0, errors.slice(0, 3).join(' | '));
  await ctx.close();
}

console.log('\n[휴대폰 390] CBD 1–13단계');
{
  const { ctx, page, errors } = await open(390, 844);
  check('390 — 처음 화면 넘침 없음', await overflow(page) <= 1);
  await walk(page, 'phone', { edits: false });
  check('390 — 관측 칼럼은 접힌 채 시작', await page.getAttribute('#drawer', 'data-size') === 'closed');
  await page.click('#drawer-toggle');
  check('390 — 진행 과정 전체 화면', await page.evaluate(() => document.getElementById('drawer').getBoundingClientRect().width >= 389));
  await page.click('#drawer-close');
  check('390 — 콘솔 오류 없음', errors.length === 0, errors.slice(0, 3).join(' | '));
  await ctx.close();
}

await browser.close();
console.log(failed ? `\n실패 ${failed}건` : '\n모두 통과');
process.exit(failed ? 1 : 0);
