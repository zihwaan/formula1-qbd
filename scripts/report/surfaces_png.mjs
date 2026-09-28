// 보고서 그림 — 2단계 11단계(반응 곡면) 화면을 그대로 PNG로. CBD 논문 값으로 study를 10단계(논문 모형 차수)까지 진행한 뒤 대화에 열어 찍는다.
// 사용: CHROME=<chrome> node scripts/report/surfaces_png.mjs http://localhost:8104/ docs/report/cbd_surfaces.png
import { chromium } from '../../tests/browser/node_modules/playwright-core/index.mjs';
const [URL = 'http://localhost:8000/', OUT = 'docs/report/cbd_surfaces.png'] = process.argv.slice(2);
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const p = await (await b.newContext({ viewport: { width: 1560, height: 1000 }, deviceScaleFactor: 2 })).newPage();
await p.addInitScript(() => { localStorage.setItem('f1_guide_seen_v1', '1'); localStorage.setItem('mm:theme', 'light'); });
await p.goto(URL, { waitUntil: 'networkidle' });
const sid = await p.evaluate(async () => {
  const post = async (path, body, ver) => {
    const r = await fetch(api(path), { method: 'POST', headers: { 'Content-Type': 'application/json', ...(ver != null ? { 'Expected-State-Version': String(ver) } : {}) }, body: JSON.stringify(body) });
    return r.json();
  };
  let v = await post('/api/stage2/studies', { source: 'cbd_paper' });
  const id = v.study.study_id;
  const act = async (a) => { v = await post(`/api/stage2/studies/${id}/actions/${a}`, { payload: a === 'approve' ? { note: '논문이 보고한 모형 차수를 그대로 비교' } : {} }, v.study.state_version); };
  await act('run');
  for (const s of ['qtpp', 'cqa', 'rm_just', 'rm_matrix', 'fp_just', 'fp_matrix', 'recommend', 'design', 'regression']) {
    if (!s.endsWith('matrix') && s !== 'recommend') await act('use_reference');   // 5·7·8단계는 코드가 만든 정리(확인만)
    await act('approve');
  }
  return id;
});
await p.evaluate((id) => window.F1Stage2.open(id), sid);
await p.waitForFunction(() => document.querySelectorAll('#s2-surf-box .rsg-plot .main-svg').length >= 9, null, { timeout: 120000 });
await p.waitForTimeout(4000);
await p.addStyleTag({ content: '.rsg-tools,.rsg figcaption,.modebar{display:none!important} .rsg{border-radius:0!important} .dock,.masthead,.topbar,.side,.drawer{display:none!important} body.chat-app,.app{height:auto!important;overflow:visible!important} .main,.thread{overflow:visible!important;min-height:0!important;flex:none!important}' });   // 캡션은 보고서에 따로 · 입력칸·스크롤 영역이 그림을 자르지 않게
await p.waitForTimeout(800);
await p.locator('#s2-surf-box figure').screenshot({ path: OUT });
console.log(OUT, sid);
await b.close();
