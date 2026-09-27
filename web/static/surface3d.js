/* 반응 곡면 격자 — 반응(행, 검은 제목 막대) × 세 번째 요인 수준(열 (a)(b)(c)). 논문 Figure(Design-Expert 형식)와 같은 모양:
   무지개 색 곡면 + 메시선, 회색 바닥에 색 등고선 투영, 실험점과 곡면까지의 잔차 줄기(위 = 진한 빨강, 아래 = 연분홍).
   바닥 점선은 설계 지지 영역 경계(밖은 외삽). 데이터는 서버(/surfaces)가 모형으로 계산한 격자 — 여기서는 그리기만 한다.
   Plotly(strict 번들 — 허브 CSP에 unsafe-eval이 없다)는 처음 그릴 때 jsdelivr에서 불러오고, 실패하면 2D 색지도로 그린다.
   WebGL 컨텍스트는 브라우저당 약 16개라 한 번에 한 격자만 살려 둔다(다른 격자는 '다시 그리기' 버튼으로 바뀐다). */
(() => {
  const PLOTLY = "https://cdn.jsdelivr.net/npm/plotly.js-strict-dist-min@2.35.2/plotly-strict.min.js";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fx = (x, d = 2) => (x == null ? "—" : Number(x).toFixed(d).replace(/\.?0+$/, (m) => (m.startsWith(".") ? "" : m)));
  // Design-Expert 기본 색띠(파랑 → 청록 → 초록 → 노랑 → 주황 → 빨강)
  const RAMP = [[0, "#1b2a8a"], [0.12, "#1f4fcf"], [0.28, "#26a2de"], [0.42, "#35c3b0"], [0.55, "#5cc450"],
    [0.68, "#b5d43c"], [0.8, "#f2c42d"], [0.91, "#ee7c22"], [1, "#d81b1b"]];
  const LETTERS = "abcdefgh";
  let plotlyP = null;
  let active = null;          // { box, redraw, divs }

  function loadPlotly() {
    if (window.Plotly) return Promise.resolve(window.Plotly);
    if (!plotlyP) {
      plotlyP = new Promise((res, rej) => {
        const sc = document.createElement("script");
        sc.src = PLOTLY; sc.async = true;
        sc.onload = () => (window.Plotly ? res(window.Plotly) : rej(new Error("Plotly 없음")));
        sc.onerror = () => { plotlyP = null; rej(new Error("Plotly를 불러오지 못했습니다")); };
        document.head.appendChild(sc);
      });
    }
    return plotlyP;
  }

  function hex(h) { return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)); }
  function ramp(t) {
    t = Math.max(0, Math.min(1, t));
    for (let i = 1; i < RAMP.length; i++) {
      if (t <= RAMP[i][0]) {
        const [t0, c0] = RAMP[i - 1], [t1, c1] = RAMP[i];
        const u = (t - t0) / (t1 - t0 || 1), a = hex(c0), b = hex(c1);
        return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * u)).join(",")})`;
      }
    }
    return RAMP[RAMP.length - 1][1];
  }

  // marching squares — z[i][j]: y = ys[i], x = xs[j]. 칸마다 나온 선분을 끝점으로 이어 긴 선으로 만든다(조각이면 점선처럼 보인다).
  function isoline(z, xs, ys, lv) {
    const segs = [];
    const at = (za, zb, pa, pb) => pa + ((lv - za) / (zb - za)) * (pb - pa);
    for (let i = 0; i < ys.length - 1; i++) {
      for (let j = 0; j < xs.length - 1; j++) {
        const z00 = z[i][j], z10 = z[i][j + 1], z11 = z[i + 1][j + 1], z01 = z[i + 1][j];
        const p = [];
        if ((z00 - lv) * (z10 - lv) < 0) p.push([at(z00, z10, xs[j], xs[j + 1]), ys[i]]);
        if ((z10 - lv) * (z11 - lv) < 0) p.push([xs[j + 1], at(z10, z11, ys[i], ys[i + 1])]);
        if ((z01 - lv) * (z11 - lv) < 0) p.push([at(z01, z11, xs[j], xs[j + 1]), ys[i + 1]]);
        if ((z00 - lv) * (z01 - lv) < 0) p.push([xs[j], at(z00, z01, ys[i], ys[i + 1])]);
        for (let k = 0; k + 1 < p.length; k += 2) segs.push([p[k], p[k + 1]]);
      }
    }
    const key = (q) => `${q[0].toPrecision(9)},${q[1].toPrecision(9)}`;
    const ends = new Map();
    segs.forEach((sg, n) => sg.forEach((q) => { const k = key(q); (ends.get(k) || ends.set(k, []).get(k)).push(n); }));
    const used = new Array(segs.length).fill(false);
    const X = [], Y = [];
    const walk = (line, q) => {
      for (;;) {
        const nx = (ends.get(key(q)) || []).find((n) => !used[n]);
        if (nx == null) return;
        used[nx] = true;
        const [a, b] = segs[nx];
        q = key(a) === key(q) ? b : a;
        line.push(q);
      }
    };
    segs.forEach((sg, n) => {
      if (used[n]) return;
      used[n] = true;
      const fwd = [sg[1]], back = [];
      walk(fwd, sg[1]);
      walk(back, sg[0]);
      const line = [...back.reverse(), sg[0], ...fwd];
      line.forEach((q) => { X.push(q[0]); Y.push(q[1]); });
      X.push(null); Y.push(null);
    });
    return { X, Y };
  }

  function specText(r) {
    if (r.operator === "BETWEEN") return `${fx(r.lower)}–${fx(r.upper)}`;
    if (r.operator === "LE") return `≤ ${fx(r.upper)}`;
    if (r.operator === "GE") return `≥ ${fx(r.lower)}`;
    return "";
  }

  function css(name, dflt) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || dflt; }

  function traces(d, r, s) {
    const xs = d.axis.a.actual, ys = d.axis.b.actual;
    const [zlo, zhi] = r.zrange;
    const floor = zlo - 0.45 * (zhi - zlo);
    const onFloor = floor + 0.006 * (zhi - floor);      // 바닥면과 같은 높이면 깊이 겹침(z-fighting)으로 선이 점선처럼 끊긴다
    const span = (v) => (v[v.length - 1] - v[0]) / 20;
    const out = [{
      type: "surface", x: xs, y: ys, z: s.mean, cmin: zlo, cmax: zhi, colorscale: RAMP, showscale: false,
      lighting: { ambient: 0.75, diffuse: 0.6, specular: 0.15, roughness: 0.6 },
      contours: {
        x: { show: true, start: xs[0], end: xs[xs.length - 1], size: span(xs), color: "rgba(20,20,20,.35)", width: 1 },
        y: { show: true, start: ys[0], end: ys[ys.length - 1], size: span(ys), color: "rgba(20,20,20,.35)", width: 1 },
      },
      hovertemplate: `${esc(d.axis.a.id)} %{x:.4g}<br>${esc(d.axis.b.id)} %{y:.4g}<br>${esc(r.name)} %{z:.3g}<extra></extra>`,
    }];
    const flat = s.mean.flat();
    const mn = Math.min(...flat), mx = Math.max(...flat);
    for (let k = 1; k <= 6; k++) {
      const lv = mn + ((mx - mn) * k) / 7;
      const { X, Y } = isoline(s.mean, xs, ys, lv);
      if (!X.length) continue;
      out.push({ type: "scatter3d", mode: "lines", x: X, y: Y, z: X.map((v) => (v == null ? null : onFloor)),
        line: { color: ramp((lv - zlo) / (zhi - zlo || 1)), width: 4 }, hoverinfo: "skip" });
    }
    const ol = s.domain_outline;
    out.push({ type: "scatter3d", mode: "lines", x: ol.map((p) => p[0]), y: ol.map((p) => p[1]), z: ol.map(() => onFloor),
      line: { color: "#f2f2f2", width: 2, dash: "dash" }, hoverinfo: "skip", name: "설계 지지 영역" });
    if (s.points.length) {
      const SX = [], SY = [], SZ = [];
      s.points.forEach((p) => { SX.push(p.a, p.a, null); SY.push(p.b, p.b, null); SZ.push(p.y, p.pred, null); });
      out.push({ type: "scatter3d", mode: "lines", x: SX, y: SY, z: SZ, line: { color: "#3a0a0a", width: 3 }, hoverinfo: "skip" });
      for (const up of [true, false]) {
        const P = s.points.filter((p) => p.above === up);
        if (!P.length) continue;
        out.push({ type: "scatter3d", mode: "markers", x: P.map((p) => p.a), y: P.map((p) => p.b), z: P.map((p) => p.y),
          marker: { size: 4, color: up ? "#8b0000" : "#f7caca", line: { color: "#8b0000", width: 1 } },
          hovertemplate: `관측 %{z:.3g}<br>(${up ? "곡면 위" : "곡면 아래"})<extra></extra>` });
      }
    }
    return { traces: out, floor };
  }

  // 눈금은 데이터 범위 안에서만(바닥 여백에 음수 눈금이 생기지 않게)
  function ticks(lo, hi) {
    const raw = (hi - lo) / 5, mag = 10 ** Math.floor(Math.log10(raw || 1));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw) || mag * 10;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toPrecision(10)));
    return out;
  }

  function layout(d, r, floor) {
    const ink = css("--ink-1", "#222"), wall = css("--surface-1", "#fff"), grid = css("--grid", "#c8c8c8");
    const short = (t) => (String(t).length > 20 ? String(t).split(/\s+/).slice(-1)[0] : t);   // 3D 축 제목은 캔버스 경계에서 잘린다 — 긴 이름은 끝 단어만
    const ax = (f) => `${f.id}: ${short(f.name)}${f.unit ? ` (${f.unit})` : ""}`;
    const fa = d.factors.find((f) => f.id === d.axis.a.id), fb = d.factors.find((f) => f.id === d.axis.b.id);
    const base = { showbackground: true, backgroundcolor: wall, gridcolor: grid, zeroline: false, tickfont: { size: 10 }, showspikes: false };
    return {
      margin: { l: 0, r: 0, t: 0, b: 0 }, height: 360, paper_bgcolor: "rgba(0,0,0,0)", showlegend: false, font: { color: ink, size: 11 },
      scene: {
        xaxis: { ...base, title: { text: ax(fa), font: { size: 11 } }, range: [d.axis.a.actual[0], d.axis.a.actual[d.axis.a.actual.length - 1]] },
        yaxis: { ...base, title: { text: ax(fb), font: { size: 11 } }, range: [d.axis.b.actual[0], d.axis.b.actual[d.axis.b.actual.length - 1]] },
        zaxis: { ...base, backgroundcolor: "#5b5b5b", title: { text: `${short(r.name)}${r.unit ? ` (${r.unit})` : ""}`, font: { size: 11 } },
          range: [floor, r.zrange[1]], tickvals: ticks(r.zrange[0], r.zrange[1]) },
        domain: { x: [0.08, 0.98], y: [0.03, 1] },           // 축 제목이 칸 밖으로 잘리지 않게 여백
        aspectmode: "manual", aspectratio: { x: 1, y: 1, z: 0.95 },
        camera: { eye: { x: -1.62, y: -1.62, z: 1.08 }, center: { x: 0, y: 0, z: -0.12 } },
      },
    };
  }

  // 2D 대체 — Plotly가 없을 때 같은 격자를 색지도로
  function heat2d(d, r, s) {
    const n = s.mean.length, m = s.mean[0].length, W = 200, cw = W / m, ch = W / n;
    const [zlo, zhi] = r.zrange;
    const rects = [];
    s.mean.forEach((row, i) => row.forEach((v, j) => {
      rects.push(`<rect x="${(j * cw).toFixed(2)}" y="${(W - (i + 1) * ch).toFixed(2)}" width="${(cw + .3).toFixed(2)}" height="${(ch + .3).toFixed(2)}" fill="${ramp((v - zlo) / (zhi - zlo || 1))}" opacity="${s.domain[i][j] ? 1 : .45}"/>`);
    }));
    const xa = d.axis.a.actual, ya = d.axis.b.actual;
    const px = (v) => ((v - xa[0]) / (xa[xa.length - 1] - xa[0])) * W, py = (v) => W - ((v - ya[0]) / (ya[ya.length - 1] - ya[0])) * W;
    const dots = s.points.map((p) => `<circle cx="${px(p.a).toFixed(1)}" cy="${py(p.b).toFixed(1)}" r="3" fill="${p.above ? "#8b0000" : "#f7caca"}" stroke="#8b0000"/>`).join("");
    const ol = s.domain_outline.map((p) => `${px(p[0]).toFixed(1)},${py(p[1]).toFixed(1)}`).join(" ");
    return `<svg viewBox="0 0 ${W} ${W}" class="rsg-2d" role="img" aria-label="${esc(r.name)}">${rects.join("")}<polyline points="${ol}" fill="none" stroke="#fff" stroke-dasharray="4 3"/>${dots}</svg>`;
  }

  function purge() {
    if (!active) return;
    const { box, redraw, divs } = active;
    if (window.Plotly) divs.forEach((el) => { try { window.Plotly.purge(el); } catch (e) { /* 무시 */ } });
    if (box.isConnected) {
      box.innerHTML = `<button type="button" class="rsg-redraw">반응 곡면 다시 그리기</button>`;
      box.querySelector(".rsg-redraw").addEventListener("click", redraw);
    }
    active = null;
  }

  /* d = 서버 /surfaces 응답. opts: { sources: true면 모형 전환 버튼, onSource(src), title } */
  async function render(box, d, opts = {}) {
    if (active && active.box !== box) purge();
    if (active && active.box === box && window.Plotly) active.divs.forEach((el) => { try { window.Plotly.purge(el); } catch (e) { /* 무시 */ } });
    const redraw = () => render(box, d, opts);
    if (d.kind === "LINE") return renderLines(box, d, opts);
    const sf = d.slice_factor;
    const cols = d.responses[0]?.slices.length || 1;
    const lab = (s, i) => (sf ? `(${LETTERS[i]}) ${esc(sf.name)} ${fx(s.level_actual, 3)}${esc(sf.unit || "")}` : "");
    box.innerHTML = `<figure class="rsg" style="--rsg-cols:${cols}">
      ${opts.sources ? `<div class="rsg-tools" role="group" aria-label="곡면 모형">
        <button type="button" data-src="selected" class="${d.source === "selected" ? "on" : ""}">시스템 선택 모형</button>
        <button type="button" data-src="published" class="${d.source === "published" ? "on" : ""}">보고된 항 구성으로 재적합</button>` : `<div class="rsg-tools">`}
        ${sf && d.factor_choices && opts.onSlice ? `<label class="rsg-slice">열(단면) 요인 <select>${d.factor_choices.map((f) => `<option value="${esc(f.id)}" ${f.id === sf.id ? "selected" : ""}>${esc(f.id)} ${esc(f.name)}</option>`).join("")}</select></label>` : ""}</div>
      ${d.responses.map((r, ri) => `<div class="rsg-bar">${esc(r.name)}<small>${esc(r.unit || "")}${specText(r) ? ` · 규격 ${esc(specText(r))}` : ""} · ${esc(r.formula || "")}${r.status ? ` · ${esc(r.status)}` : ""}</small></div>
        <div class="rsg-row">${r.slices.map((s, si) => `<div class="rsg-cell"><div class="rsg-plot" id="rsg-${box.id}-${ri}-${si}"></div><div class="rsg-lab">${lab(s, si)}</div></div>`).join("")}</div>`).join("")}
      <figcaption>${esc(opts.title || "반응 곡면")}${sf ? ` — ${esc(sf.name)} ${d.responses[0].slices.map((s, i) => `(${LETTERS[i]}) ${fx(s.level_actual, 3)}${esc(sf.unit || "")}`).join(", ")}` : ""}.
        <span class="rsg-key"><i class="up"></i>관측값이 곡면 위 <i class="dn"></i>곡면 아래 · 세로줄 = 잔차 · 바닥 점선 = 설계 지지 영역(밖은 외삽)</span></figcaption>
    </figure>`;
    box.querySelectorAll(".rsg-tools button").forEach((b) => b.addEventListener("click", () => opts.onSource && opts.onSource(b.dataset.src)));
    const slc = box.querySelector(".rsg-slice select");
    if (slc) slc.addEventListener("change", () => opts.onSlice(slc.value));
    const divs = [];
    active = { box, redraw, divs };
    let P = null;
    try { P = await loadPlotly(); } catch (e) { P = null; }
    for (const [ri, r] of d.responses.entries()) {
      for (const [si, s] of r.slices.entries()) {
        const el = document.getElementById(`rsg-${box.id}-${ri}-${si}`);
        if (!el) return;
        if (!P) { el.innerHTML = heat2d(d, r, s); continue; }
        const t = traces(d, r, s);
        await P.newPlot(el, t.traces, layout(d, r, t.floor), { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["toImage", "resetCameraLastSave3d"] });
        divs.push(el);
      }
    }
    if (!P) box.querySelector("figcaption").insertAdjacentHTML("beforeend", ` <span class="d7-muted">(3D를 불러오지 못해 2D 색지도로 그렸습니다)</span>`);
  }

  // 요인 1개 — 반응마다 한 줄: 예측 곡선 + 실험점(잔차 세로줄) + 규격선(2D, WebGL 없음)
  async function renderLines(box, d, opts) {
    const f = d.factors[0];
    box.innerHTML = `<figure class="rsg" style="--rsg-cols:1">
      ${opts.sources && d.published_available ? `<div class="rsg-tools"><button type="button" data-src="selected" class="${d.source === "selected" ? "on" : ""}">시스템 선택 모형</button>
        <button type="button" data-src="published" class="${d.source === "published" ? "on" : ""}">보고된 항 구성으로 재적합</button></div>` : ""}
      ${d.responses.map((r, ri) => `<div class="rsg-bar">${esc(r.name)}<small>${esc(r.unit || "")}${specText(r) ? ` · 규격 ${esc(specText(r))}` : ""} · ${esc(r.formula || "")}${r.status ? ` · ${esc(r.status)}` : ""}</small></div>
        <div class="rsg-row"><div class="rsg-cell"><div class="rsg-plot rsg-line" id="rsg-${box.id}-${ri}-0"></div></div></div>`).join("")}
      <figcaption>${esc(d.note || "")} <span class="rsg-key"><i class="up"></i>관측값이 곡선 위 <i class="dn"></i>곡선 아래 · 세로줄 = 잔차 · 점선 = 규격</span></figcaption></figure>`;
    box.querySelectorAll(".rsg-tools button").forEach((b) => b.addEventListener("click", () => opts.onSource && opts.onSource(b.dataset.src)));
    let P = null;
    try { P = await loadPlotly(); } catch (e) { P = null; }
    const ink = css("--ink-1", "#222"), grid = css("--grid", "#ccc"), warn = css("--status-warn", "#b7791f");
    for (const [ri, r] of d.responses.entries()) {
      const el = document.getElementById(`rsg-${box.id}-${ri}-0`);
      if (!el) return;
      const xs = r.line.x;
      if (!P) {
        const W = 300, H = 160, [lo, hi] = r.zrange;
        const px = (v) => ((v - xs[0]) / (xs[xs.length - 1] - xs[0])) * W, py = (v) => H - ((v - lo) / (hi - lo || 1)) * H;
        el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="rsg-2d"><polyline fill="none" stroke="${ink}" stroke-width="2" points="${xs.map((x, i) => `${px(x).toFixed(1)},${py(r.line.y[i]).toFixed(1)}`).join(" ")}"/>
          ${r.points.map((p) => `<line x1="${px(p.a)}" x2="${px(p.a)}" y1="${py(p.y)}" y2="${py(p.pred)}" stroke="#3a0a0a"/><circle cx="${px(p.a)}" cy="${py(p.y)}" r="3" fill="${p.above ? "#8b0000" : "#f7caca"}" stroke="#8b0000"/>`).join("")}</svg>`;
        continue;
      }
      const tr = [{ type: "scatter", mode: "lines", x: xs, y: r.line.y, line: { color: ramp(0.3), width: 3 }, hovertemplate: "%{x:.4g} → %{y:.3g}<extra></extra>" }];
      const SX = [], SY = [];
      r.points.forEach((p) => { SX.push(p.a, p.a, null); SY.push(p.y, p.pred, null); });
      tr.push({ type: "scatter", mode: "lines", x: SX, y: SY, line: { color: "#3a0a0a", width: 1.5 }, hoverinfo: "skip" });
      for (const up of [true, false]) {
        const Pt = r.points.filter((p) => p.above === up);
        if (Pt.length) tr.push({ type: "scatter", mode: "markers", x: Pt.map((p) => p.a), y: Pt.map((p) => p.y),
          marker: { size: 8, color: up ? "#8b0000" : "#f7caca", line: { color: "#8b0000", width: 1 } }, hovertemplate: "관측 %{y:.3g}<extra></extra>" });
      }
      const shapes = [r.lower, r.upper].filter((v) => v != null && r.operator !== "TARGET_TOL").map((v) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: v, y1: v, line: { color: warn, dash: "dash", width: 1.5 } }));
      await P.newPlot(el, tr, { height: 260, margin: { l: 56, r: 12, t: 8, b: 44 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
        showlegend: false, font: { color: ink, size: 11 }, shapes,
        xaxis: { title: { text: `${f.id}: ${f.name}${f.unit ? ` (${f.unit})` : ""}` }, gridcolor: grid, zeroline: false },
        yaxis: { title: { text: `${r.name}${r.unit ? ` (${r.unit})` : ""}` }, gridcolor: grid, zeroline: false, range: r.zrange } },
        { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["toImage"] });
    }
  }

  window.F1Surfaces = { render, loadPlotly, purge };
})();
