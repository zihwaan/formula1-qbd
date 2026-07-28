// 정밀 감사 — 실제 결함을 재현 근거와 함께 수집한다.
import { chromium } from 'playwright-core';

const URL = process.argv[2] || 'https://zihwan.com/formula1/';
const browser = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const found = [];
const note = (sev, area, msg) => { found.push({ sev, area, msg }); console.log(`  [${sev}] ${area}: ${msg}`); };

const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 } });
const page = await ctx.newPage();
const consoleErrs = [], netFails = [], reqs = [];
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') consoleErrs.push(`${m.type()}: ${m.text()}`); });
page.on('pageerror', (e) => consoleErrs.push('pageerror: ' + e.message));
page.on('requestfailed', (r) => netFails.push(`${r.url()} — ${r.failure()?.errorText}`));
page.on('response', (r) => { if (r.status() >= 400) reqs.push(`${r.status()} ${r.url()}`); });

await page.addInitScript(() => localStorage.setItem('f1_guide_seen_v1', '1'));
await page.goto(URL, { waitUntil: 'networkidle' });

console.log('\n── A. 정적 로드');
if (netFails.length) note('HIGH', '네트워크', netFails.join(' | '));
if (reqs.length) note('HIGH', 'HTTP', reqs.join(' | '));
const fontOk = await page.evaluate(() => document.fonts.check('16px "Pretendard Variable"'));
if (!fontOk) note('MED', '폰트', 'Pretendard 미적용 — 시스템 폰트로 폴백');

console.log('\n── B. 실행 중 버튼/상태 (이중 실행 방지)');
await page.fill('#request', '소아용 플루옥세틴 정제를 설계해줘');
await page.click('#run');
await page.waitForTimeout(1200);
const runState = await page.evaluate(() => ({
  disabled: document.getElementById('run').disabled,
  label: document.getElementById('run').textContent.trim(),
  replay: document.getElementById('replay').disabled,
}));
if (!runState.disabled) note('HIGH', '이중 실행', `실행 중인데 '설계 실행' 버튼이 활성(${JSON.stringify(runState)}) — 중복 run 생성 가능`);

console.log('\n── C. 실행 완료까지');
await page.waitForSelector('#consensus:not([hidden])', { timeout: 300000 }).catch(() => note('HIGH', '실행', '합의까지 도달 실패'));
await page.waitForTimeout(1500);

const res = await page.evaluate(() => {
  const txt = (s) => [...document.querySelectorAll(s)].map((e) => e.textContent);
  return {
    fallbackNotes: txt('.judge-note').filter((t) => t.includes('결정론 폴백')).length,
    judgeNotes: document.querySelectorAll('.judge-note').length,
    warnRows: txt('.ev.warn .msg').filter((t) => t.includes('Groq') || t.includes('폴백')),
    traceRows: document.querySelectorAll('.ev').length,
    dupJudge: (() => {
      const seen = {};
      let dup = 0;
      document.querySelectorAll('.card').forEach((c) => {
        const id = c.querySelector('h4')?.textContent || '';
        const notes = [...c.querySelectorAll('.judge-note')].map((n) => n.textContent.slice(0, 40));
        const uniq = new Set(notes);
        if (notes.length !== uniq.size) dup++;
        seen[id] = notes.length;
      });
      return { dup, perCard: seen };
    })(),
    tokenRows: document.querySelectorAll('.msg.tok').length,
  };
});
if (res.fallbackNotes > 0) note('HIGH', '목업 노출', `심사 소견 ${res.judgeNotes}건 중 ${res.fallbackNotes}건이 "[결정론 폴백] LLM 미사용" 가짜 점수로 화면에 표시됨`);
if (res.warnRows.length) note('HIGH', '오류 노출', `원시 HTTP 오류 문구가 사용자 화면에 그대로 노출: ${res.warnRows[0].slice(0, 110)}`);
if (res.dupJudge.dup) note('MED', '중복 렌더', `같은 심사 소견 중복 표시 ${res.dupJudge.dup}건`);

console.log('\n── D. XSS — 실제 렌더 경로에 공격 문자열 주입');
const xss = await page.evaluate(() => {
  const P = '<img src=x onerror="window.__XSS__=(window.__XSS__||0)+1">';
  window.__XSS__ = 0;
  const hit = {};
  const probe = (name, fn) => {
    const before = window.__XSS__;
    try { fn(); } catch (e) { hit[name] = 'throw: ' + e.message; return; }
    if (window.__XSS__ > before || document.querySelector('img[src="x"]')) hit[name] = 'EXECUTED';
  };
  probe('addTrace', () => addTrace(P, P, P));
  probe('renderConsensus', () => renderConsensus({
    model: P, winner: P, reported: 1,
    ranked: [{ rank: 1, candidate_id: P, weighted_score: P, variance: P, reviewers: P }],
    rulebook_feedback: [P],
  }));
  probe('renderWetlab', () => renderWetlab({
    summary: P,
    findings: [{ off_target: true, metric: P, interpretation: P, suggested_revision: P }],
  }));
  probe('renderCandidates', () => {
    candidates.set('x', {
      recipe: { candidate_id: P, strategy: P, process: P, packaging: P,
                ingredients: [{ name: P, amount_mg: P }] },
      verdicts: [{ rule_id: P, status: P }],
      judges: [{ persona: P, score: P, rationale: P }],
    });
    renderCandidates();
  });
  probe('renderChem', () => renderChem({
    api_name: P, smiles: P, flags: [{ flag_name: P, present: true }],
    descriptors: {}, estimates: [{ property: P, value: P, confidence: P }], warnings: [P],
  }));
  return { executed: window.__XSS__, hit };
});
if (xss.executed > 0 || Object.keys(xss.hit).length) {
  note('HIGH', 'XSS', `주입 실행됨 ${xss.executed}회 — ${JSON.stringify(xss.hit)}`);
} else {
  console.log('   ✓ 5개 렌더 경로 모두 이스케이프됨 (실행 0회)');
}
await page.reload({ waitUntil: 'networkidle' });

console.log('\n── E. 오류 경로 (429 등 사용자 대면 처리)');
const errPath = await page.evaluate(async () => {
  const base = window.__BASE__ || '';
  // 잘못된 run id로 스트림 요청 → UI가 어떻게 반응하는지
  const r = await fetch(`${base}/api/runs/does-not-exist`);
  return { status: r.status, body: (await r.text()).slice(0, 80) };
});
console.log('   존재하지 않는 run 조회:', JSON.stringify(errPath));
const hasToast = await page.evaluate(() => !!document.querySelector('.toast, [role="alert"], [aria-live]'));
if (!hasToast) note('MED', '오류 UX', '오류를 알리는 토스트/aria-live 영역이 없음 — 실패가 조용히 사라짐');

console.log('\n── F. 접근성 기본');
const a11y = await page.evaluate(() => {
  const noName = [...document.querySelectorAll('button')].filter(
    (b) => !b.textContent.trim() && !b.getAttribute('aria-label')).length;
  const inputsNoLabel = [...document.querySelectorAll('input')].filter((i) => {
    const id = i.id;
    return !i.getAttribute('aria-label') && !document.querySelector(`label[for="${id}"]`) &&
      !i.closest('label') && !i.placeholder;
  }).length;
  const liveRegions = document.querySelectorAll('[aria-live]').length;
  return { noName, inputsNoLabel, liveRegions, lang: document.documentElement.lang };
});
if (a11y.noName) note('LOW', '접근성', `이름 없는 버튼 ${a11y.noName}개`);
if (a11y.inputsNoLabel) note('LOW', '접근성', `레이블 없는 입력 ${a11y.inputsNoLabel}개`);
if (!a11y.liveRegions) note('MED', '접근성', '실시간 트레이스에 aria-live 없음 — 스크린리더가 진행상황 못 읽음');

console.log('\n── G. 반응형 (여러 폭에서 깨짐/오버플로)');
for (const w of [1920, 1440, 1200, 1024, 834, 768, 430, 390, 360]) {
  const p2 = await ctx.newPage();
  await p2.setViewportSize({ width: w, height: 900 });
  await p2.goto(URL, { waitUntil: 'domcontentloaded' });
  await p2.waitForTimeout(500);
  const r = await p2.evaluate(() => {
    const de = document.documentElement;
    const over = de.scrollWidth - de.clientWidth;
    const bad = [...document.querySelectorAll('*')].filter((e) => {
      const b = e.getBoundingClientRect();
      return b.width > 0 && b.right > de.clientWidth + 2;
    }).map((e) => `${e.tagName}.${(e.className || '').toString().split(' ')[0]}`);
    return { over, bad: [...new Set(bad)].slice(0, 4) };
  });
  if (r.over > 1) note('MED', `반응형 ${w}px`, `가로 오버플로 ${r.over}px — ${r.bad.join(', ')}`);
  await p2.close();
}

console.log('\n── H. 콘솔');
if (consoleErrs.length) note('MED', '콘솔', consoleErrs.slice(0, 3).join(' | '));

console.log(`\n총 ${found.length}건`);
console.log(JSON.stringify(found.reduce((a, f) => { a[f.sev] = (a[f.sev] || 0) + 1; return a; }, {})));
await browser.close();
