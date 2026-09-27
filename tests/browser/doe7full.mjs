// DoE v7.0 마법사의 모든 폼을 클릭으로 끝까지 — 근거가 약한 신규 API 데이터셋(테스트 전용 합성 값, 로컬 컨테이너에서만 실행)으로
// feasibility 계획 승인 → 경계 실패(RB18 LB002) → 범위 재제출 → feasibility 통과 → FCCD → 결과 → 모델 → 영역 →
// 확인 계획 잠금(제안점) → 문헌 등급 lot 거부(VR015) → 독립 확인 batch → 최종 승인 → VERIFIED_OPERATING_REGION.
// 합성 값이 화면·데모에 남지 않도록 운영 주소에는 돌리지 않는다.
import { chromium } from 'playwright-core';
const URL = process.argv[2] || 'http://localhost:8000/';
if (/zihwan\.com/.test(URL)) { console.log('운영 주소에서는 돌리지 않는다(합성 테스트 데이터)'); process.exit(2); }
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
let fail = 0;
const ck = (n, ok, d = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${n}${d ? ' — ' + d : ''}`); if (!ok) fail++; };
let seed = 7; const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed / 2147483647 - 0.5); };
const pts = [[-1, -1], [1, -1], [-1, 1], [1, 1], [-1, 0], [1, 0], [0, -1], [0, 1], [0, 0], [0, 0], [0, 0], [0, 0], [0, 0]];
const ds = {
  title: '테스트 전용 — 신규 API 전 과정', source: { citation: 'browser test fixture (synthetic)' }, study_type: 'NEW_API', result_evidence_status: 'MEASURED_IN_STUDY',
  formulation: { dosage_form: 'tablet', unit_weight_mg: 200, route: 'direct_compression', steps: ['blend', 'compress'], equipment: 'EQ-T', batch_scale: { units: 300 },
    fixed_parameters: [], ingredients: [{ material: 'API-T', function: 'API', mg: 10, pct: 5, grade: 'lot1', is_api: true }, { material: 'Mannitol', function: 'filler', mg: 124, pct: 62 },
      { material: 'MCC', function: 'binder', mg: 60, pct: 30 }, { material: 'MgSt', function: 'lubricant', mg: 6, pct: 3 }] },
  factors: [{ id: 'F', name: '압축력', key: 'compression_force', unit: 'N', quantity_kind: 'force', low: 7000, center: 10000, high: 13000, kind: 'CPP', evidence_status: 'EXPERT_PROPOSAL' },
    { id: 'M', name: 'MCC', key: 'filler_ratio', unit: '%w/w', quantity_kind: 'fraction_mass', material: 'MCC', low: 22, center: 30, high: 38, evidence_status: 'EXPERT_PROPOSAL' }],
  responses: [{ id: 'bf', name: '경도', cqa_id: 'CQA_BREAKING_FORCE', unit: 'N', operator: 'GE', lower: 55, test_method_id: 'TM_BREAK_USP1217', test_method_version: 'v1', summary: 'MEAN', replicate_policy: 'n=10' },
    { id: 'dt', name: '붕해', cqa_id: 'CQA_DISINTEGRATION', unit: 'min', operator: 'LE', upper: 8, test_method_id: 'TM_DISINT_USP701', test_method_version: 'v1', summary: 'MAX', replicate_policy: 'n=6' }],
  runs: pts.map(([a, m], n) => ({ label: `B${n + 1}`, batch_id: `B${n + 1}`, blend_id: `BL${n + 1}`, factors: { F: 10000 + 3000 * a, M: 30 + 8 * m },
    responses: { bf: +(70 + 9 * a - 4 * m - 3 * a * a + 1.4 * rnd()).toFixed(3), dt: +(5 + 1.2 * a + 0.9 * m + 0.5 * a * m + 0.25 * rnd()).toFixed(3) } })),
  protocol: { sampling_plan: 'n=10/6', stop_criteria: '외관 불량 시 중단' },
};
const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
const errs = [];
p.on('pageerror', (e) => errs.push(e.message));
await p.addInitScript(() => { localStorage.setItem('f1_guide_seen_v1', '1'); localStorage.removeItem('f1:d7study'); });
await p.goto(URL + '?v7', { waitUntil: 'networkidle' });
const status = () => p.locator('#d7w-ask h3 .d7-badge').first().textContent();
const waitStatus = async (x) => { await p.waitForFunction((v) => document.querySelector('#d7w-ask h3 .d7-badge')?.textContent === v, x, { timeout: 30000 }).catch(() => {}); return status(); };
const click = async (a) => { await p.click(`#d7w-ask [data-act="${a}"]`); await p.waitForFunction(() => ![...document.querySelectorAll('#d7w-ask button')].some((x) => x.disabled), null, { timeout: 60000 }); };
const fill = async () => { await p.click('#d7w-fill'); await p.waitForFunction(() => /채웠습니다/.test(document.getElementById('d7w-msg').textContent), null, { timeout: 15000 }); await p.evaluate(() => { document.getElementById('d7w-msg').textContent = ''; }); };
const feas = async (failCid) => {
  for (const tr of await p.locator('#d7w-form tr[data-cid]').all()) {
    const cid = await tr.getAttribute('data-cid');
    await tr.locator('[data-f="manufacturable"]').selectOption(cid === failCid ? 'false' : 'true');
    await tr.locator('[data-f="measurable"]').selectOption('true');
    await tr.locator('[data-f="critical_incompatibility"]').selectOption('false');
  }
};

await p.click('#d7w-dsbtn');
await p.fill('#d7w-ds-text', JSON.stringify(ds));
await p.click('#d7w-ds-go');
ck('데이터셋 study 생성', (await waitStatus('HANDOFF_RECEIVED')) === 'HANDOFF_RECEIVED');
await click('handoff_confirm'); await fill(); await click('cqa_approve'); await click('fmea_approve'); await fill(); await click('factor_select'); await fill();
await click('range_approve');
ck('제안 근거 → NEEDS_FEASIBILITY (5조건)', (await waitStatus('NEEDS_FEASIBILITY')) === 'NEEDS_FEASIBILITY' && /5조건/.test(await p.locator('#d7w-body').textContent()));
await click('feasibility_plan_approve');
ck('feasibility 계획 승인 → 결과 대기', (await waitStatus('WAITING_FEASIBILITY_RESULTS')) === 'WAITING_FEASIBILITY_RESULTS');
await feas('X1_HIGH');
await click('feasibility_results_submit');
ck('경계 실패 → RANGE_REVISION_REQUIRED + RB18 LB002', (await waitStatus('RANGE_REVISION_REQUIRED')) === 'RANGE_REVISION_REQUIRED' && /LB002/.test(await p.locator('#d7w-ask').textContent()));
await fill(); await click('range_submit');
ck('범위 재제출 → RANGE_EVIDENCE_CHECK', (await waitStatus('RANGE_EVIDENCE_CHECK')) === 'RANGE_EVIDENCE_CHECK');
await click('range_approve'); await click('feasibility_plan_approve'); await feas(null);
await click('feasibility_results_submit');
ck('feasibility 통과 → DOE_PLAN_REVIEW(FCCD 13)', (await waitStatus('DOE_PLAN_REVIEW')) === 'DOE_PLAN_REVIEW' && /FCCD 13 run/.test(await p.locator('#d7w-body').textContent()));
ck('근거가 FEASIBILITY_CONFIRMED로 바뀜(수동 상향 아님)', /FEASIBILITY_CONFIRMED/.test(await p.locator('#d7w-body').textContent()));
await fill(); await click('plan_approve');
ck('실험표 승인 → WAITING_FOR_RESULTS', (await waitStatus('WAITING_FOR_RESULTS')) === 'WAITING_FOR_RESULTS');
await fill(); await click('results_submit'); await click('results_confirm');
if ((await status()) === 'MODEL_FIT') { await fill(); await click('model_accept_flags'); }
ck('모델 → PROVISIONAL_DESIGN_SPACE', (await waitStatus('PROVISIONAL_DESIGN_SPACE')) === 'PROVISIONAL_DESIGN_SPACE', await status());
await p.waitForFunction(() => document.querySelectorAll('#d7w-rsg .rsg-plot .main-svg, #d7w-rsg .rsg-2d').length >= 2, null, { timeout: 60000 }).catch(() => {});
ck('2요인 곡면 — 반응 2 × 1칸', (await p.locator('#d7w-rsg .rsg-plot').count()) === 2);
ck('확인 계획 폼에 제안점 3개(SETPOINT·BOUNDARY·ROBUSTNESS)', (await p.locator('#d7w-form tr[data-i]').count()) === 3);
await click('vplan_lock');
ck('확인 계획 잠금 → WAITING_VERIFICATION_RESULTS', (await waitStatus('WAITING_VERIFICATION_RESULTS')) === 'WAITING_VERIFICATION_RESULTS');
const st = await p.evaluate(() => window.F1Doe7Wizard.current().study);
const put = async (ev) => {
  for (const [i, pt] of st.verification.plan.points.entries()) {
    const tr = p.locator(`#d7w-form tr[data-role="${pt.role}"]`);
    await tr.locator('[data-f="batch_id"]').fill(`V${i}`);
    await tr.locator('[data-f="parent_blend_id"]').fill(`VB${i}`);
    await tr.locator('[data-f="evidence_status"]').selectOption(ev);
    for (const [k, pi] of Object.entries(pt.prediction_intervals)) await tr.locator(`[data-f="v:${k}"]`).fill([0, 1, 2].map(() => pi.predicted.toFixed(3)).join(', '));
  }
};
await put('LITERATURE_DIRECT');
await click('verification_submit');
ck('문헌 등급 lot은 확인 근거 불가(VR015)', (await status()) === 'WAITING_VERIFICATION_RESULTS' && /VR015/.test(await p.locator('#d7w-ask').textContent()));
await put('VERIFICATION_BATCH');
await click('verification_submit');
ck('독립 확인 batch 통과 → 최종 승인 대기', /모두 통과|all|VERIFICATION_PASSED/.test(await p.locator('#d7w-body').textContent()));
await p.locator('#d7w-form [data-f="rationale"]').fill('세 확인점 모두 규격·잠근 예측구간 안');
await click('final_approve');
ck('최종 승인 → VERIFIED_OPERATING_REGION', (await waitStatus('VERIFIED_OPERATING_REGION')) === 'VERIFIED_OPERATING_REGION');
ck('승인 이력 9개 지점 모두', /승인 \d+/.test(await p.locator('#d7w-body').textContent()) && (await p.evaluate(() => new Set(window.F1Doe7Wizard.current().study.approvals.map((a) => a.point)).size)) === 9);
// 요인 1개 DoE — 곡면 대신 예측 곡선(2D)
const one = JSON.parse(JSON.stringify(ds));
one.title = '테스트 전용 — 1요인'; one.factors = [{ ...ds.factors[0], evidence_status: 'MEASURED_PRIOR_BATCH' }]; one.responses = [ds.responses[0]];
one.runs = [-1, -1, 0, 0, 0, 1, 1].map((a, n) => ({ label: `S${n + 1}`, batch_id: `S${n + 1}`, blend_id: `SB${n + 1}`, factors: { F: 10000 + 3000 * a },
  responses: { bf: +(70 + 9 * a - 3 * a * a + 1.0 * rnd()).toFixed(3) } }));
await p.click('#d7w-dsbtn');
await p.fill('#d7w-ds-text', JSON.stringify(one));
await p.click('#d7w-ds-go');
await waitStatus('HANDOFF_RECEIVED');
await click('handoff_confirm'); await fill(); await click('cqa_approve'); await click('fmea_approve'); await fill(); await click('factor_select'); await fill(); await click('range_approve');
ck('1요인 → 실험표(7 run, 설계 반복은 중복 아님)', (await waitStatus('DOE_PLAN_REVIEW')) === 'DOE_PLAN_REVIEW' && /ONE_FACTOR_QUADRATIC 7 run/.test(await p.locator('#d7w-body').textContent()));
await fill(); await click('plan_approve');
ck('1요인 실험표 승인됨(DV016 오판 없음)', (await waitStatus('WAITING_FOR_RESULTS')) === 'WAITING_FOR_RESULTS');
await fill(); await click('results_submit'); await click('results_confirm');
if ((await status()) === 'MODEL_FIT') { await fill(); await click('model_accept_flags'); }
await p.waitForSelector('#d7w-rsg .rsg-line .main-svg, #d7w-rsg .rsg-line svg', { timeout: 60000 }).catch(() => {});
ck('1요인 예측 곡선 + 실험점', (await p.locator('#d7w-rsg .rsg-line').count()) === 1 && (await p.locator('#d7w-rsg .rsg-line .main-svg, #d7w-rsg .rsg-line svg').count()) > 0);
ck('페이지 오류 없음', errs.length === 0, errs.join(' | '));
await b.close();
console.log(fail ? `\n${fail}건 실패` : '\nALL PASS');
process.exit(fail ? 1 : 0);
