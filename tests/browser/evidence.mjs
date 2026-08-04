// 이중 루프 브라우저 검증: 실험 데이터 선택 입력 → 근거 게이트 → 확인시험 → 승인 → 배치 결과
//
// 여기 두 검사는 실제 결함을 잡았다.
//   1. 화면은 evidence 이벤트 직후 확인시험 요청을 띄우는데 서버는 최종 state만 봐서
//      실행 중 제출이 404가 나던 문제 (→ Run.evidence_store)
//   2. 긴 토큰이 열 최소 너비를 밀어 좁은 화면에서 페이지가 가로 스크롤되던 문제
import { chromium } from 'playwright-core';

const URL = process.argv[2] || 'http://localhost:8000/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = [];
p.on('pageerror', (e) => errs.push(e.message));
p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
await p.addInitScript(() => localStorage.setItem('f1_guide_seen_v1', '1'));

let runId = null;
p.on('response', async (res) => {
  if (res.url().endsWith('/api/runs') && res.request().method() === 'POST') {
    try { runId = (await res.json()).run_id; } catch (e) { /* 본문 없음 */ }
  }
});
await p.goto(URL, { waitUntil: 'networkidle' });

let fail = 0;
const ck = (n, ok, d = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${n}${d ? ' — ' + d : ''}`); if (!ok) fail++; };

console.log('\n[그래프 — 게이트 둘, 되먹임 라벨]');
const nodes = await p.$$eval('#graph g.node', (els) => els.map((e) => e.id));
ck('evidence 노드가 그려진다', nodes.includes('node-evidence'), nodes.length + '개');
const labels = await p.$$eval('#graph text.edge-label', (els) => els.map((e) => e.textContent));
ck('되먹임 라벨 2개', labels.length === 2, labels.join(' / '));
const row = await p.$$eval('#graph g.node rect', (els) => els
  .map((r) => ({ x: +r.getAttribute('x'), w: +r.getAttribute('width'), y: +r.getAttribute('y') }))
  .filter((b2) => b2.y === 30).sort((a, c) => a.x - c.x));
ck('상단 노드가 겹치지 않는다', !row.some((b2, i) => i > 0 && row[i - 1].x + row[i - 1].w > b2.x));

console.log('\n[실험 데이터 선택 입력]');
await p.evaluate(() => { document.getElementById('inputs').open = true; });
const fields = await p.$$eval('#inputs-body input', (els) => els.map((e) => e.dataset.key));
ck('카탈로그에서 폼이 그려진다', fields.length >= 10, `${fields.length}개 필드`);
ck('유동성·BCS·용해도 키 포함',
  ['angle_of_repose', 'dose_solubility_volume', 'solubility_mg_per_ml'].every((k) => fields.includes(k)));
const unlocks = await p.$$eval('#inputs-body small', (els) => els.filter((e) => e.textContent.trim()).length);
ck('항목마다 "무엇이 열리는지" 표시', unlocks >= fields.length - 1, `${unlocks}건`);

await p.evaluate(() => {
  const set = (key, value) => {
    const el = document.querySelector(`#inputs-body input[data-key="${key}"]`);
    if (el.type === 'checkbox') el.checked = value; else el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  set('aqueous_stability_percent', '99.4');
  set('forced_degradation_done', true);
});
ck('입력 개수가 표시된다', (await p.textContent('#inputs-count')).includes('2개'));

console.log('\n[실행 → 근거 게이트]');
await p.click('#run');
await p.waitForFunction(() => !document.getElementById('evidence').hidden, null, { timeout: 300000 });
ck('실행 중에 근거 게이트가 뜬다', true);
await p.waitForFunction(() => !document.getElementById('run').disabled, null, { timeout: 300000 });

const state = await p.getAttribute('.ev-state', 'class');
ck('선행 근거가 없으면 실행 불가 초안', state.includes('blocked'), state);
const groups = await p.$$eval('.ev-group h4', (els) => els.map((e) => e.textContent.split('\n')[0].trim()));
ck('선행·병행·배치 후로 나뉜다', groups.length >= 2, groups.join(' / '));
ck('후보 카드에 프로토콜 상태 뱃지', (await p.locator('.card .readiness').count()) > 0);
ck('합의는 "권고 후보"로 표기', (await p.textContent('#consensus')).includes('권고 후보'));
ck('보류 중엔 승인 버튼이 없다', (await p.locator('#ev-approve').count()) === 0);

// 넣은 실측값이 실제로 요구를 닫았는지는 후보 전체에서 본다(화면은 권고 후보만 보여준다).
// 수계 공정 후보가 없으면 수계 안정성 요구 자체가 발동하지 않는 것이 정상이다.
const evidence = await p.evaluate(async (id) => (await fetch(`api/runs/${id}/evidence`)).json(), runId);
const cands = Object.values(evidence.candidates);
const aqueous = cands.flatMap((c) => c.gaps).filter((g) => g.evidence_key === 'aqueous_process_stability');
ck('입력한 수계 안정성이 해당 요구를 닫는다',
  aqueous.length === 0 || aqueous.every((g) => g.status === 'satisfied'),
  aqueous.length ? aqueous.map((g) => g.status).join(',') : '수계 공정 후보 없음(요구 미발동)');

console.log('\n[확인시험 결과 → 재평가 → 승인]');
const numeric = await p.$$eval('.ev-num', (els) => els.map((e) => e.placeholder));
ck('수치형 요구엔 숫자 입력칸', numeric.length === 0 || numeric.some((x) => x.includes('_')),
  numeric.join(' / ') || '수치형 요구 없음');
await p.$$eval('.ev-input .ev-num', (els) => els.forEach((e) => { e.value = '0.5'; }));
await p.click('#ev-example');
await p.click('#ev-submit');
await p.waitForFunction(() => document.querySelector('#ev-approve'), null, { timeout: 120000 });
ck('결과를 넣으면 검토용 프로토콜로 올라간다', true);
if (numeric.length) {
  ck('실측값 자리에 반영된 내역을 보여준다',
    (await p.textContent('#evidence')).includes('입력 계층에 반영된 실측값'));
}
await p.click('#ev-approve');
await p.waitForFunction(() => document.querySelector('.ev-state')?.className.includes('approved'),
  null, { timeout: 60000 });
ck('연구자 승인 → 실행 가능 프로토콜', (await p.textContent('.ev-state')).includes('실행 가능'));

console.log('\n[배치 결과 루프(실험 후)는 그대로 돈다]');
await p.evaluate(() => { document.getElementById('labloop').open = true; });
await p.click('#wl-example');
await p.click('#wl-submit');
await p.waitForSelector('#wl-out .ll-exp', { timeout: 180000 });
const wl = await p.textContent('#wl-out');
ck('배치 결과에 프로토콜 상태가 남는다', wl.includes('프로토콜 상태'));
ck('다음 실험 지시에 출처가 붙는다', wl.includes('근거'));

console.log('\n[허용목록 · 반응형 · 콘솔]');
const rejected = await p.evaluate(async () => {
  const res = await fetch('api/runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request: '허용목록 검사', measured_params: { is_pediatric: 1, angle_of_repose: 480 } }),
  });
  return res.ok ? (await res.json()).rejected_inputs : ['요청 실패 ' + res.status];
});
ck('카탈로그 밖 키·범위 밖 값은 거부', rejected.includes('is_pediatric') && rejected.includes('angle_of_repose'),
  rejected.join(','));

for (const width of [1440, 1024, 768, 390]) {
  await p.setViewportSize({ width, height: 900 });
  await p.waitForTimeout(700);
  const probe = await p.evaluate(() => {
    const bad = [];
    document.querySelectorAll('body *').forEach((el) => {
      const s = getComputedStyle(el);
      if (s.overflowX === 'auto' || s.overflowX === 'scroll' || el.classList.contains('sr-only')) return;
      if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) bad.push(el.className || el.tagName);
    });
    return { scroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
             bad: bad.slice(0, 3) };
  });
  ck(`가로 스크롤 없음 @${width}`, !probe.scroll, probe.bad.join(' | '));
}
ck('콘솔 오류 0건', errs.length === 0, errs.slice(0, 2).join(' | '));

await b.close();
console.log(fail ? `\n실패 ${fail}건` : '\n전부 통과');
process.exit(fail ? 1 : 0);
