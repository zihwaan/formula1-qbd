// 시연 시나리오 3건이 각자의 goal 텍스트가 주장하는 경로를 실제로 밟는지 확인한다.
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

async function waitDone(timeout = 240000) {
  await p.waitForFunction(() => document.getElementById('run').textContent.trim() === '설계 실행',
    null, { timeout });
}

// ── 시나리오 0: 규칙이 AI를 막는 순간 ──────────────────────────────
console.log('\n[시나리오 1 · 규칙이 AI를 막는 순간]');
await p.locator('.scenario').nth(0).click();
await waitDone();
await p.waitForTimeout(1000);
let trace = await p.locator('#trace').textContent();
ck('INC002 반려가 트레이스에 뜬다', trace.includes('INC002'), '');
ck('고정 제약 충돌 결론', /제약|충돌|통과가 없다/.test(trace), '');

// ── 시나리오 1: 요청에 따라 팀이 바뀐다 ────────────────────────────
console.log('\n[시나리오 2 · 요청에 따라 팀이 바뀐다]');
await p.locator('.scenario').nth(1).click();
await waitDone();
await p.waitForTimeout(1000);
trace = await p.locator('#trace').textContent();
ck('REV001(소아 안전) 소집', trace.includes('REV001'), '');
ck('REV002~006 중 무관한 심사관은 소집 안 됨(고령자 REV006 미소집)', !trace.includes('REV006'), '');

// ── 시나리오 2: 값을 몰라도 후보부터, 갈리는 지점만 되묻는다(v3 데이터 요청) ──
console.log('\n[시나리오 3 · 값을 몰라도 후보부터, 갈리는 지점만 되묻는다]');
await p.locator('.scenario').nth(2).click();
await waitDone();
await p.waitForTimeout(1500);

// finishRun()이 renderDataRequests()로 #drq를 채우고, continueScenario()는 입력칸을 짚어 줄 뿐
// 값을 넣지 않는다(시스템은 측정값을 지어내지 않는다). 아래에서 **테스트가** 연구자 대신 값을 넣는다.
const drqVisible = await p.evaluate(() => !document.getElementById('drq').hidden);
ck('데이터 요청 패널이 보인다(후보는 이미 나온 채로)', drqVisible);
const reqCount = await p.locator('#drq-body .drq-req').count();
ck('대기 중인 데이터 요청이 1건 이상 렌더된다', reqCount >= 1, `${reqCount}건`);
const candsBeforeBadge = await p.locator('#cands .drq-badge').count();
ck('후보 카드에 신뢰도 배지(grounded/provisional)가 보인다', candsBeforeBadge >= 1, `${candsBeforeBadge}개`);

const autoFilled = await p.evaluate(() => [...document.querySelectorAll('#drq-body .drq-num input')].some((i) => i.value));
ck('시스템이 측정값을 대신 채우지 않는다', !autoFilled);
// 테스트 입력: 이부프로펜 녹는점 문헌값(약 76 °C) — 연구자가 가진 값을 넣는 동작을 흉내 낸다
const tmInput = p.locator('#drq-body .drq-num input[data-key="tm_c"]');
const firstNum = (await tmInput.count()) ? tmInput : p.locator('#drq-body .drq-num input').first();
await firstNum.fill((await tmInput.count()) ? '76' : '1');
await p.click('#drq-submit');
// 제출 완료를 기다린다 — #drq-out에 재계산 결과 문구가 뜬다.
await p.waitForFunction(() => {
  const el = document.getElementById('drq-out');
  return el && el.textContent.includes('plan_signature');
}, null, { timeout: 60000 }).catch(() => {});
const drqOutText = await p.locator('#drq-out').textContent().catch(() => '');
ck('값 제출 → 재계산 결과가 그 자리에 뜬다(그래프 재실행 없음)',
  drqOutText.includes('전략') && drqOutText.includes('plan_signature'), drqOutText.slice(0, 160));

console.log('\n[콘솔/페이지 오류]');
ck('오류 0건', errs.length === 0, errs.slice(0, 5).join(' | '));

await b.close();
console.log(`\n${fail === 0 ? '전부 통과' : fail + '건 실패'}`);
process.exit(fail === 0 ? 0 : 1);
