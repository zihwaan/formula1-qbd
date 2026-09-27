// 보고서 그림 12 — CBD 재현 요약의 반응 곡면 격자(엔진 /cbd-replay/surfaces 계산값을 화면 렌더러 그대로)를 PNG로.
// 사용: node scripts/report/surfaces_png.mjs http://localhost:8105/ published docs/report/cbd_surfaces.png
import { chromium } from '../../tests/browser/node_modules/playwright-core/index.mjs';
const [URL = 'http://localhost:8000/', SRC = 'published', OUT = 'docs/report/cbd_surfaces.png'] = process.argv.slice(2);
const b = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
const p = await (await b.newContext({ viewport: { width: 1560, height: 1000 }, deviceScaleFactor: 2 })).newPage();
await p.addInitScript(() => { localStorage.setItem('f1_guide_seen_v1', '1'); localStorage.setItem('mm:theme', 'light'); });
await p.goto(URL + '?v7', { waitUntil: 'networkidle' });
await p.click('.d7-subtab[data-v="replay"]');
await p.waitForSelector('#d7-rsg .rsg-tools button');
if (SRC === 'selected') await p.click('#d7-rsg .rsg-tools [data-src="selected"]');
await p.waitForFunction(() => document.querySelectorAll('#d7-rsg .rsg-plot .main-svg').length >= 27, null, { timeout: 120000 });
await p.waitForTimeout(4000);
await p.addStyleTag({ content: '.rsg-tools,.rsg figcaption,.modebar{display:none!important}' });   // 보고서 캡션이 따로 있다
await p.evaluate(() => document.querySelectorAll('body *').forEach((e) => { const ps = getComputedStyle(e).position; if (ps === 'sticky' || ps === 'fixed') e.style.position = 'static'; }));   // 고정 머리글이 그림을 덮지 않게
await p.waitForTimeout(800);
await p.locator('#d7-rsg figure').screenshot({ path: OUT });
console.log(OUT);
await b.close();
