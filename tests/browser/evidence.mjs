// 근거 결손 게이트(발표 자료 ⑤) — 후보 카드 다음의 **근거 결손 게이트 카드 하나**에서 값을 넣는다(사용자 2026-09-30: 후보마다 따로 넣지 않는다 —
// 측정값은 스펙에 들어가 모든 후보를 함께 다시 판정한다). 후보 카드에는 상태 한 줄과 사유 칸만 남는다.
// 적합/부적합을 고르는 칸은 없다 — 값이 phase_gates부터 다시 계산된다.
// 두 입력 경로를 모두 탄다: 카드 폼(흡수율만 → 아직 결손) → 입력 에이전트에 말로(pH별 용해도 → 코드 환산 → BCS 근거 닫힘).
// 실제 LLM으로 시연 카드 ①을 돌린다(후보가 있어야 한다). F1_LLM=dacon 권장.
//   F1_LLM=dacon CHROME=<chrome> node tests/browser/evidence.mjs http://localhost:8104/
import { chromium } from 'playwright-core';

const URL = process.argv[2] || 'http://localhost:8000/';
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const ctx = await b.newContext({ viewport: { width: 1440, height: 950 } });
await ctx.addInitScript((v) => { try { localStorage.setItem('f1_guide_seen_v1', '1'); if (v) localStorage.setItem('f1:llm', v); } catch (e) {} }, process.env.F1_LLM || '');
const p = await ctx.newPage();
const errs = [];
p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
p.on('console', (m) => { if (m.type() === 'error' && !/status of (409|422)/.test(m.text())) errs.push('console: ' + m.text()); });
let fail = 0;
const ck = (n, ok, d = '') => { console.log(`${ok ? '  ✓' : '  ✗'} ${n}${d ? ' — ' + d : ''}`); if (!ok) fail++; };
await p.goto(URL, { waitUntil: 'networkidle' });

console.log('\n[시연 ① → 후보 카드 → 근거 결손 게이트 카드]');
await p.locator('.scenario', { hasText: '로르녹시캄' }).click();
await p.waitForFunction(() => document.getElementById('run').textContent.trim() === '설계 실행', null, { timeout: 600000 });
// 설계가 끝나면 데이터 요청보다 먼저 심사위원단 카드 — 소집된 심사관마다 카드 하나(후보별 점수 · 근거)
await p.waitForSelector('#agent-log #panel-jury:not([hidden]) .jury-card', { timeout: 60000 });
const juryN = await p.locator('#agent-log #panel-jury .jury-card').count();
ck('심사위원단 카드 — 소집된 심사관마다 하나', juryN >= 1, `${juryN}명`);
ck('심사위원단 카드가 데이터 요청 카드보다 먼저', await p.evaluate(() => {
  const j = document.querySelector('#agent-log #panel-jury'), d = document.querySelector('#agent-log #drq');
  return !d || !!(j.compareDocumentPosition(d) & Node.DOCUMENT_POSITION_FOLLOWING);
}));
const juryScores = await p.locator('#agent-log #panel-jury .jury-score').count();
if (process.env.SHOTS) await p.locator('#agent-log #panel-jury').screenshot({ path: `${process.env.SHOTS}/jury_1440.png` });
ck('심사관 카드마다 후보별 점수와 근거', juryScores > 0 && await p.locator('#agent-log #panel-jury .jury-why').count() === juryScores, `점수 ${juryScores}건`);
// 데이터 요청 카드보다 먼저 — 심사위원단 카드에서 통과 후보 하나를 골라 승인할 수 있다(에이전트 추천에서 바꿀 수 있음)
const pickOpts = await p.locator('#agent-log #panel-jury .jury-cand option').evaluateAll((os) => os.map((o) => o.value));
const passedNow = await p.evaluate(() => window.F1Discovery.passedIds());
ck('데이터 요청 전 심사위원단 카드에서 후보 선택 · 승인(통과 후보 전부 · 추천 표시)', pickOpts.length > 0 && pickOpts.length === passedNow.length
  && passedNow.every((id) => pickOpts.includes(id)) && /에이전트 추천/.test(await p.locator('#agent-log #panel-jury .jury-cand').textContent()), pickOpts.join(','));
if (pickOpts.length > 1) {
  await p.locator('#agent-log #panel-jury .jury-cand').selectOption(pickOpts[1]);
  ck('다른 후보를 고르면 “연구자가 고른 후보” · 결손이면 사유 칸', /연구자가 고른 후보/.test(await p.locator('#agent-log #panel-jury .jury-gap').textContent()));
}
if (await p.locator('#agent-log #drq:not([hidden])').count()) await p.click('#drq-skip');
await p.waitForSelector('#agent-log #panel-cands .card.pass .ev-box', { timeout: 120000 });
const passed = p.locator('#agent-log #panel-cands .card.pass');
ck('통과 후보마다 근거 상태 한 줄', await passed.count() === await p.locator('#agent-log #panel-cands .card.pass .ev-box').count(), `${await passed.count()}장`);
ck('반려 후보에는 근거 상태 없음', await p.locator('#agent-log #panel-cands .card.fail .ev-box').count() === 0);
ck('후보 카드마다 소집 심사관 · 점수 요약', await passed.count() === await p.locator('#agent-log #panel-cands .card.pass .jury-line').count()
  && /소집 심사관/.test(await p.locator('#agent-log #panel-cands .card.pass .jury-line').first().textContent()));
ck('후보 카드에는 입력 칸이 없다(값은 게이트 카드 하나에서)', await p.locator('#agent-log #panel-cands [data-key], #agent-log #panel-cands .ev-send').count() === 0);

const evg = p.locator('#agent-log #panel-evidence');
await p.waitForSelector('#agent-log #panel-evidence:not([hidden]) .evg-sum', { timeout: 60000 });
ck('근거 결손 게이트 카드는 대화에 하나 · 후보 카드 다음', await evg.count() === 1 && await p.evaluate(() => {
  const c = document.querySelector('#agent-log #panel-cands'), e = document.querySelector('#agent-log #panel-evidence');
  return !!(c.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING);
}));
const items = () => evg.locator('.ev-item').evaluateAll((ls) => ls.map((l) => ({ id: l.dataset.req, code: l.querySelector('b code')?.textContent || '',
  cands: [...l.querySelectorAll('.ev-cands code')].map((c) => c.textContent) })));
const its = await items();
ck('항목마다 확인시험 test_id와 해당 후보', its.length > 0 && its.every((i) => /^T_/.test(i.code) && i.cands.length > 0),
  its.map((i) => `${i.id}:${i.code}[${i.cands.join(',')}]`).join(' '));
ck('요구 항목은 한 번씩(후보마다 반복하지 않음)', new Set(its.map((i) => i.id)).size === its.length);
if (process.env.SHOTS) { await evg.scrollIntoViewIfNeeded(); await evg.screenshot({ path: `${process.env.SHOTS}/evg_1440.png` });
  await p.locator('#agent-log #panel-cands .card.pass').first().screenshot({ path: `${process.env.SHOTS}/cand_1440.png` }); }
ck('적합/부적합 선택 칸 없음 · 등급 선택과 제출 버튼은 하나', await evg.locator('.ev-out, .ev-note').count() === 0
  && await evg.locator('select.ev-grade').count() === 1 && await evg.locator('.ev-send').count() === 1);

const idx = await passed.evaluateAll((cs) => cs.findIndex((c) => c.querySelector('.ev-box.hold')));
if (idx < 0 || !its.some((i) => i.id === 'EVR005')) {
  ck('BCS 근거(EVR005) 결손 후보가 있음(없으면 이 실행에선 입력 경로를 확인할 수 없음)', false);
} else {
  const hold = passed.nth(idx);
  ck('결손 후보 카드에 승인 칸(기본 사유 · “사유 기록 · 승인하고 2단계로”, 점선)', /승인하고 2단계로/.test(await hold.locator('.dev-start').textContent())
    && await hold.locator('.dev-start.hold').count() === 1 && /선행 근거/.test(await hold.locator('.ev-waive textarea').inputValue()));
  await hold.locator('.ev-jump').click();
  await p.waitForTimeout(700);
  ck('후보 카드의 “입력 카드로” → 게이트 카드로 이동', await evg.evaluate((e) => { const r = e.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; }));
  // 승인은 후보마다(후보 카드의 승인 칸) — 게이트 카드에는 안내만
  ck('게이트 카드는 후보 카드의 승인 칸을 안내(사유 칸 중복 없음)', await evg.locator('.ev-waive').count() === 0 && /승인하고 2단계로/.test(await evg.textContent()));
  const holdId = await hold.getAttribute('data-cand');
  await hold.locator('.ev-waive textarea').fill('');
  await hold.locator('.ev-waive-go').click();
  ck('사유를 비우면 승인 안 됨(칸 안에 안내)', /사유를 적어/.test(await hold.locator('.ev-waive-msg').textContent()), holdId);

  // ① 카드 폼 — 흡수율만(용해도 부피가 없어 BCS 근거는 아직 결손)
  const fa = evg.locator('[data-key="fraction_absorbed"]');
  await fa.fill('95');
  let before = await p.locator('#trace .ev').count();
  let resp = p.waitForResponse((x) => x.url().includes('/measurements'), { timeout: 240000 }).catch(() => null);
  await evg.locator('.ev-send').click();
  let r = await resp;
  ck('카드 폼 → /measurements 200 (source evidence, 넣은 값만)', !!r && r.status() === 200 && r.request().postDataJSON().source === 'evidence'
    && JSON.stringify(r.request().postDataJSON().measurements) === '{"fraction_absorbed":95}', r ? JSON.stringify(r.request().postDataJSON().measurements) : '응답 없음');
  await p.waitForTimeout(800);
  let rows = await p.locator('#trace .ev').evaluateAll((es, n) => es.slice(n).map((e) => e.textContent.replace(/\s+/g, ' ')), before);
  ck('재계산이 트레이스에 phase_gates부터 남음', rows.some((t) => /phase_gates/.test(t)) && rows.some((t) => /gate/.test(t)), rows.slice(0, 3).join(' | ').slice(0, 120));
  ck('흡수율만으로는 BCS 근거가 닫히지 않음(용해도 부피 필요)', (await items()).some((i) => i.id === 'EVR005'));
  const narr1 = (await p.locator('#narration').textContent().catch(() => '')).replace(/\s+/g, ' ');
  ck('“지금 무슨 일이” 해설에 재계산 과정(페이즈 게이트 · 계획)', /재계산 1 · /.test(narr1) && /재계산 1 · 새 실측값으로 계획/.test(narr1),
    (narr1.match(/재계산 1 · [^.]{0,40}/g) || []).slice(0, 3).join(' | '));
  ck('재계산 뒤 후보 처방 카드가 대화 맨 아래에 다시(지난 카드는 기록으로)', await p.evaluate(() => {
    const live = document.querySelector('#agent-log #panel-cands'), old = document.querySelector('#agent-log .cands-card.frozen');
    const ev = document.querySelector('#agent-log #panel-evidence');
    return !!old && !!(old.compareDocumentPosition(live) & Node.DOCUMENT_POSITION_FOLLOWING) && !!(live.compareDocumentPosition(ev) & Node.DOCUMENT_POSITION_FOLLOWING);
  }));
  ck('제출한 칸은 비워짐', (await evg.locator('[data-key="fraction_absorbed"]').inputValue().catch(() => '')) === '');

  // ② 입력 에이전트에 말로 — pH별 용해도를 관측으로 읽고, 환산·pH 최저값·용량/용해도 부피는 서버 코드가 계산한다
  await evg.locator('.ev-item[data-req="EVR005"] .ev-talk').click();
  const pre = await p.locator('#agent-input').inputValue();
  ck('“말로 입력” → 입력칸에 항목 이름', /BCS/.test(pre), pre);
  // 설계 직후 에이전트가 먼저 거는 말(개발 착수 카드)과 섞이지 않게 — 이 턴의 응답과 그 제출 카드만 본다
  const turn = p.waitForResponse((x) => x.url().includes('/api/agent/turn'), { timeout: 180000 });
  await p.locator('#agent-input').fill(pre + '용해도는 pH 1.2, 4.5, 6.8에서 각각 6, 5.5, 5 mg/mL였어');
  await p.locator('#agent-input').press('Enter');
  const tj = await (await turn).json();
  console.log(`    (에이전트: ${tj.source} · ${(tj.reply || '').slice(0, 80)} · notes ${JSON.stringify(tj.notes || []).slice(0, 160)})`);
  await p.waitForTimeout(500);
  const ac = p.locator('#agent-log .ad-card', { hasText: '근거 결손 게이트 입력' }).last();
  const txt = (await ac.count()) ? (await ac.textContent()).replace(/\s+/g, ' ') : JSON.stringify(tj.proposals || []).slice(0, 200);
  ck('에이전트 카드 = 근거 결손 게이트 입력 · 코드 계산', /근거 결손 게이트 입력/.test(txt) && /코드 계산/.test(txt) && /dose_solubility_volume/.test(txt), txt.slice(0, 200));
  resp = p.waitForResponse((x) => x.url().includes('/measurements'), { timeout: 240000 }).catch(() => null);   // 전략이 바뀌면 후보를 다시 설계한다(LLM)
  await ac.locator('.ad-run').click();
  r = await resp;
  const sent = r ? r.request().postDataJSON() : {};
  ck('카드 실행 → /measurements 200 (source agent_evidence)', !!r && r.status() === 200 && sent.source === 'agent_evidence', r ? JSON.stringify(sent.measurements) : '응답 없음');
  const outJ = r ? await r.json().catch(() => ({})) : {};
  await p.waitForTimeout(1500);
  if (outJ.regenerated) {
    await p.waitForSelector('#agent-log #panel-cands .card.pass .ev-box', { timeout: 120000 });
    ck('실측 BCS로 전략 집합이 바뀌어 재설계 → 같은 게이트 카드가 새 후보로 다시 그려짐', await evg.count() === 1, outJ.plan_signature);
    const tr = (outJ.trace || []).map((e) => `${e.node.split(':')[0]}/${e.kind}`);
    ck('재설계된 후보도 심사 — 트레이스에 summon → judge → consensus', tr.includes('summon/node.exit') && tr.includes('judge/judge.verdict') && tr.includes('consensus/consensus'),
      [...new Set(tr)].filter((x) => /summon|judge|consensus/.test(x)).join(' '));
    const newIds = await p.locator('#agent-log #panel-cands .card.pass').evaluateAll((cs) => cs.map((c) => c.dataset.cand));
    const juryIds = await p.locator('#agent-log #panel-jury .jury-list code').evaluateAll((cs) => [...new Set(cs.map((c) => c.textContent))]);
    const narr2 = (await p.locator('#narration').textContent().catch(() => '')).replace(/\s+/g, ' ');
    ck('해설에 계획 변경 → 재설계 → 새 심사관 소집이 보임', /계획이 바뀌었다/.test(narr2) && /재계산 2 · 심사관 \d+명이 지금 만들어졌다/.test(narr2),
      (narr2.match(/재계산 2 · [^.]{0,40}/g) || []).slice(0, 4).join(' | '));
    ck('새 후보 카드에 심사관 점수 · 심사위원단 카드도 새 후보로', await p.locator('#agent-log #panel-cands .card.pass .judge-note').count() > 0
      && newIds.every((id) => juryIds.includes(id)), `${newIds.join(',')} / ${juryIds.join(',')}`);
  }
  ck('BCS 근거(EVR005)가 모든 후보에서 닫힘', !(await items()).some((i) => i.id === 'EVR005'));
  const narr = await p.locator('#narration').textContent().catch(() => '');
  ck('해설에 재판정 기록(카드 폼 · 말로 입력)', /근거를 다시 판정/.test(narr) && /말로 입력/.test(narr));

  const ok = p.locator('#agent-log #panel-cands .card.pass', { has: p.locator('.ev-box.ok') }).first();
  if (await ok.count()) {
    ck('근거 충족 후보의 버튼 = “이 후보로 개발 착수”', /이 후보로 개발 착수/.test(await ok.locator('.dev-start').textContent()));
    // 심사위원단 카드의 선택으로 승인 — 근거 충족 후보는 사유 칸 없이 바로
    const okId = await ok.getAttribute('data-cand');
    await p.locator('#agent-log #panel-jury .jury-cand').selectOption(okId);
    ck('심사위원단 카드에서 근거 충족 후보를 고르면 사유 칸 없이 승인', await p.locator('#agent-log #panel-jury .jury-reason').isHidden(), okId);
    await p.locator('#agent-log #panel-jury .jury-go').click();
    await p.waitForSelector('#s2 .s2-step.current[data-step="prototype"]', { timeout: 60000 });
    const ho = (await p.locator('#s2 .s2-handoff').textContent()).replace(/\s+/g, ' ');
    ck('사유 없이 2단계 착수 · Handoff에 근거 충족 기록 · 고른 후보', /근거 결손 게이트/.test(ho) && !/연구자 사유/.test(ho) && ho.includes(okId),
      (ho.match(/근거 결손 게이트[^·]{0,60}/) || [''])[0]);
  } else {
    const left = (await items()).map((i) => i.id).join(', ');
    ck('근거 충족 후보가 있음', false, `남은 결손: ${left}`);
  }
}

// 좁은 화면 — 게이트 카드가 가로로 넘치지 않는다
await p.setViewportSize({ width: 390, height: 844 });
await p.waitForTimeout(300);
if (process.env.SHOTS) {
  if (await p.locator('#drawer-close').isVisible().catch(() => false)) await p.click('#drawer-close');   // 좁은 화면에선 관측 서랍이 전체 화면
  await evg.scrollIntoViewIfNeeded(); await evg.screenshot({ path: `${process.env.SHOTS}/evg_390.png` });
}
ck('390px 가로 넘침 없음', await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
ck('콘솔 오류 0', errs.length === 0, errs.slice(0, 3).join(' | '));
await b.close();
console.log(fail ? `\n실패 ${fail}건` : '\n모두 통과');
process.exit(fail ? 1 : 0);
