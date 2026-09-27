/* DoE v7.0 탭 머리(패키지 요약)와 검증 비교 보기 — 저장 없는 계산 화면(명세 docs/doe_v7.0, 데이터 database/07_doe/v7_0).
   ① CBD 재현 요약(Monton 2026, Table 9 원자료 한 번에) ② 범위근거 gate 계산기(명세 §13 예시).
   단계별 승인으로 진행하는 저장형 study(마법사)는 doe7wizard.js. */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const api = (p) => ((window.__BASE__ || "") + p);
  const f = (x, d = 3) => (x == null ? "—" : Number(x).toFixed(d));
  const RESP_KO = { hardness_kgf: "경도", dt_s: "붕해시간", friability_pct: "마손도" };
  const EV = ["MEASURED_PRIOR_BATCH", "FEASIBILITY_CONFIRMED", "VERIFIED_EXTERNAL_DATA", "REPORTED_NO_RAW_DATA", "EXPERT_PROPOSAL", "UNVERIFIED_PROPOSAL"];
  const EV_KO = { MEASURED_PRIOR_BATCH: "같은 API·설비 실제 batch", FEASIBILITY_CONFIRMED: "feasibility로 확인", VERIFIED_EXTERNAL_DATA: "적용성 확인된 외부 원자료",
    REPORTED_NO_RAW_DATA: "논문 보고(원자료 없음)", EXPERT_PROPOSAL: "전문가 제안", UNVERIFIED_PROPOSAL: "근거 미검증 입력" };
  let loaded = false, accepted = false, x3 = -1;

  async function get(p) { const r = await fetch(api(p)); if (!r.ok) throw new Error(`${p} ${r.status}`); return r.json(); }
  async function post(p, body) {
    const r = await fetch(api(p), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `${p} ${r.status}`);
    return d;
  }
  const badge = (cls, t) => `<span class="d7-badge ${cls}">${esc(t)}</span>`;
  const stateBadge = (s) => badge(/VERIFIED/.test(s) ? "ok" : /INADEQUATE|REVISION|EMPTY/.test(s) ? "bad" : /WAITING|NEEDS|FEASIBILITY/.test(s) ? "warn" : "", s);
  const decision = (d) => d ? `<div class="d7-decision">${badge(d.gate_effect === "BLOCK_STAGE" ? "bad" : d.gate_effect === "ROUTE" ? "" : "warn", d.gate_effect)}
    <code>${esc(d.rule_id)}</code> <b>${esc(d.result_code)}</b> → ${stateBadge(d.next_state || "—")}
    <span class="d7-muted">${esc(d.message_ko)}</span> ${d.enforced ? "" : badge("draft", "권고 · 집행 안 함(DRAFT)")}</div>` : "";

  // ── 패키지 머리 ──
  async function header() {
    const p = await get("/api/doe-v7/package");
    $("d7-banner").textContent = p.banner;
    $("d7-pkg").innerHTML = `<span><b>${esc(p.package)}</b> · v${esc(p.architecture_version)}</span>
      <span>룰북 ${p.rulebooks} · 마스터 ${p.masters} · 확인시험 ${p.confirmation_tests} · reason code ${p.reason_codes} · 출처 ${p.sources}</span>
      <span>${badge("draft", p.validation_status)} ${badge("", `enabled=${p.enabled} · ${p.runtime_mode}`)} ${badge("", `집행 규칙 ${p.enforceable_rules}개`)}</span>
      <span class="d7-muted mono">package ${esc(p.package_hash.slice(0, 16))}…</span>`;
  }

  // ── ① CBD 문헌 재현 ──
  async function replay() {
    const box = $("d7-replay");
    box.innerHTML = `<div class="d7-muted">계산 중…</div>`;
    const r = await get(`/api/doe-v7/cbd-replay?accept_flags=${accepted}`);
    const fx = r.fixture;
    const models = Object.entries(r.models);
    const runs = fx.runs.slice().sort((a, b) => a.run_order - b.run_order);
    box.innerHTML = `
      <section class="d7-card">
        <h3>CBD 구강붕해정 — 문헌 재현 ${badge("warn", "문헌 재현 전용 · 독립 검증 아님")}</h3>
        <p class="d7-muted">${esc(r.source.citation)} DOI ${esc(r.source.doi)} · ${esc(r.source.pmcid)} — 논문 식을 입력하지 않고 Table 9 원자료 17 run에서 다시 적합한다.</p>
        <ol class="d7-steps">
          <li><b>후보 처방(Table 1)</b> — 모든 값은 <code>REFERENCE_PROTOTYPE</code>. 요인 중심점으로 자동 승계하지 않는다(RE003).</li>
          <li><b>반응 3개</b> — ${fx.responses.map((x) => `${esc(RESP_KO[x.id] || x.name)} ${x.operator === "BETWEEN" ? `${x.lower}–${x.upper}` : `≤ ${x.upper}`} ${esc(x.unit)}${x.is_cqa ? "" : " (논문상 CQA 아님 · 반응으로 모델링)"}`).join(" · ")}</li>
          <li><b>요인 3개 · 근거</b> — ${fx.factors.map((x) => `${esc(x.name)} ${x.low}/${x.center}/${x.high} ${esc(x.unit)}`).join(" · ")} · 근거 <code>${esc(fx.range_evidence.prior_study_status)}</code> (${esc(fx.range_evidence.source_locator)})</li>
        </ol>
        ${decision(r.range_gate.route)}
      </section>

      <section class="d7-card">
        <h3>설계 — Box–Behnken 17 run ${r.design.validation.ok ? badge("ok", "Validator 통과") : badge("bad", "Validator 실패")} ${r.design.fixture_linked ? badge("ok", "Table 9 17행 = 설계 17점") : badge("bad", "연결 실패")}</h3>
        <p class="d7-muted">${r.design.validation.checks.map((c) => `${c.ok ? "✓" : "✗"} ${esc(c.check)}${c.detail ? ` (${esc(c.detail)})` : ""}`).join(" · ")}</p>
        <details><summary>Table 9 원자료 17 run 보기</summary><div class="table-wrap"><table class="matrix"><thead><tr><th>run</th><th>압축력 psi</th><th>MCC %</th><th>CCS %</th><th>경도 kgf</th><th>붕해 s</th><th>마손도 %</th></tr></thead><tbody>
        ${runs.map((x) => `<tr><td>${x.run_order}</td><td>${x.force_psi}</td><td>${x.mcc_pct}</td><td>${x.ccs_pct}</td><td>${x.hardness_kgf.mean} ± ${x.hardness_kgf.sd}</td><td>${x.dt_s.mean} ± ${x.dt_s.sd}</td><td>${x.friability_pct.value}</td></tr>`).join("")}
        </tbody></table></div></details>
      </section>

      <section class="d7-card">
        <h3>자동 계층적 모델 선택 <span class="d7-muted">LOOCV RMSE · 1-SE 규칙 → 최소 항 → AICc — 사용자가 항을 고르지 않는다</span></h3>
        <div class="table-wrap"><table class="matrix"><thead><tr><th>반응</th><th>선택 식(coded)</th><th>R² · 수정 · 예측</th><th>적합결여 p</th><th>상태</th><th>논문(Table 10·11)</th></tr></thead><tbody>
        ${models.map(([k, m]) => `<tr><td><b>${esc(RESP_KO[k] || k)}</b></td>
          <td class="mono">${esc(Object.entries(m.coef).map(([t, b]) => `${b >= 0 && t !== "1" ? "+" : ""}${b.toFixed(3)}${t === "1" ? "" : "·" + t}`).join(" "))}<div class="d7-muted">후보 ${m.candidates} · 적합 가능 ${m.estimable} · 1-SE 집합 ${m.one_se_set.length}</div></td>
          <td>${f(m.r2, 2)} · ${f(m.adj_r2, 2)} · <b>${f(m.pred_r2, 2)}</b></td>
          <td>${m.lack_of_fit.p == null ? "계산 불가" : f(m.lack_of_fit.p, 3)}</td>
          <td>${stateBadge(m.status)}${m.gate.flags.map((x) => `<div class="d7-muted">${esc(x.rule_id)} ${esc(x.detail)}</div>`).join("")}</td>
          <td class="mono d7-small">${esc(m.published.coded || m.published.coded_as_printed || "")}<div class="d7-muted">모형 p = ${esc(m.published.model_p)}</div></td></tr>`).join("")}
        </tbody></table></div>
        ${r.audit.length ? `<h4>출판 보고 감사</h4><ul class="d7-list">${r.audit.map((a) => `<li>${badge(a.kind === "PUBLISHED_REPORT_INCONSISTENCY" ? "bad" : "", a.kind)} ${esc(RESP_KO[a.response] || a.response)} — ${esc(a.detail)}${a.reason_code_registered === false ? ` <span class="d7-muted">(M07 미등록 — 코드 대신 감사 기록, 카탈로그 보강 후보)</span>` : ""}</li>`).join("")}</ul>` : ""}
      </section>

      <section class="d7-card">
        <h3>영역 · 확인 ${stateBadge(r.final_state.state)} <span class="d7-muted">${esc(r.final_state.reason_code)} · ${esc(r.final_state.rule)}</span></h3>
        ${r.waiting_flag_approval ? `<div class="d7-wait"><p><b>연구자 승인 대기</b> — ${r.flagged_responses.map((k) => esc(RESP_KO[k] || k)).join(", ")} 모형에 경고 플래그가 있다. 플래그를 알고도 쓸지는 사람이 정한다(RB00 human_approval_required: MODEL_ACCEPTANCE_WITH_FLAGS).</p>
          <button type="button" class="primary" id="d7-accept">플래그를 확인했고 이 모형들로 영역을 계산한다</button></div>` : regionHtml(r)}
      </section>`;
    const acc = $("d7-accept");
    if (acc) acc.addEventListener("click", () => { accepted = true; replay().catch(showErr); });
    if (!r.waiting_flag_approval) { bindSlice(); await slice(); }
  }

  function regionHtml(r) {
    const g = r.region, v = r.verification;
    return `<p>잠근 정책: 공동 통과확률 ≥ <b>${g.policy.p_min}</b> · ${esc(g.policy.uncertainty)} · <code>${esc(g.policy.dependence_assumption)}</code> · 격자 ${g.policy.grid_steps}³ 중 domain 안 ${g.grid_points_in_domain}점</p>
      <div class="d7-kpis"><div><span>공동 통과 영역</span><b>${(g.joint_ok_fraction * 100).toFixed(1)}%</b><small>${g.status === "EMPTY" ? "비어 있음 → REGION_EMPTY" : "PROVISIONAL"}</small></div>
        <div><span>최대 공동 통과확률</span><b>${f(g.setpoint_joint_p, 3)}</b><small>기준 ${g.policy.p_min}</small></div>
        <div><span>참고: 평균만 보면</span><b>${(g.mean_ok_fraction * 100).toFixed(1)}%</b><small>불확실성 미반영 — 영역으로 쓸 수 없다(DR005)</small></div>
        <div><span>논문 최적점 공동 통과확률</span><b>${f(r.optimum_in_region?.joint_p, 3)}</b><small>1400 psi · MCC 35% · CCS 1%</small></div></div>
      <div class="d7-slicebar">CCS(X3) 고정: ${[[-1, "1%"], [0, "3%"], [1, "5%"]].map(([c, t]) => `<button type="button" class="d7-x3${c === x3 ? " on" : ""}" data-x3="${c}">${t}</button>`).join("")}
        <span class="d7-muted">X1 압축력(가로) × X2 MCC(세로). 회색 빗금 = 설계 domain 밖(외삽, 색칠 안 함)</span></div>
      <div class="d7-maps" id="d7-maps"></div>
      <h4>독립 확인 — 논문 Table 12의 3 lot (fitting set에 넣지 않음)</h4>
      <div class="table-wrap"><table class="matrix"><thead><tr><th>반응</th><th>잠근 예측 · 95% PI</th><th>lot 1</th><th>lot 2</th><th>lot 3</th></tr></thead><tbody>
      ${Object.entries(r.verification_plan.prediction_intervals).map(([k, p]) => `<tr><td>${esc(RESP_KO[k] || k)}</td><td>${f(p.predicted, 2)} [${f(p.pi[0], 2)}, ${f(p.pi[1], 2)}]</td>
        ${v.rows.filter((x) => x.response === k).map((x) => `<td>${x.value} ${x.spec_pass ? "규격 ✓" : "규격 ✗"} · ${x.inside_pi ? "PI 안" : "PI 밖"}</td>`).join("")}</tr>`).join("")}
      </tbody></table></div>
      <p class="d7-note">${v.route === "VERIFICATION_PASSED" ? "확인 lot은 모두 규격과 잠근 예측구간을 통과했다." : esc(v.route)}
        ${r.final_state.state !== "VERIFIED_OPERATING_REGION" ? " 그러나 잠근 기준에서 영역이 비어 있고 확인점도 그 기준을 넘지 못해 <b>승격하지 않는다</b> — 논문은 평균 예측으로 design space를 선언했지만, v7은 불확실성을 반영한 기준을 결과 뒤에 완화하지 않는다(DR011)." : ""}</p>`;
  }

  function bindSlice() {
    document.querySelectorAll(".d7-x3").forEach((b) => b.addEventListener("click", () => {
      x3 = Number(b.dataset.x3);
      document.querySelectorAll(".d7-x3").forEach((x) => x.classList.toggle("on", x === b));
      slice().catch(showErr);
    }));
  }

  async function slice() {
    const s = await get(`/api/doe-v7/cbd-replay/slice?x3=${x3}&steps=31`);
    const maps = $("d7-maps"); if (!maps) return;
    const n = s.steps, W = 200, cw = W / n;
    const cell = (i, j) => `x="${(i * cw).toFixed(2)}" y="${((n - 1 - j) * cw).toFixed(2)}" width="${(cw + 0.3).toFixed(2)}" height="${(cw + 0.3).toFixed(2)}"`;
    const hatch = `<defs><pattern id="d7h" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" stroke="var(--grid)" stroke-width="2"/></pattern></defs>`;
    const pts = (s.x3 === -1 ? [[1250, 40], [1750, 40], [1500, 30], [1500, 50]] : s.x3 === 1 ? [[1250, 40], [1750, 40], [1500, 30], [1500, 50]] : [[1250, 30], [1750, 30], [1250, 50], [1750, 50], [1500, 40]])
      .map(([a, b]) => [(a - 1500) / 250, (b - 40) / 10]);
    const dots = pts.map(([a, b]) => `<circle cx="${((a + 1) / 2 * (W - cw) + cw / 2).toFixed(1)}" cy="${((1 - (b + 1) / 2) * (W - cw) + cw / 2).toFixed(1)}" r="3" fill="var(--ink-1)" stroke="var(--surface-1)"/>`).join("");
    const opt = s.x3 === -1 ? (() => { const a = (1400 - 1500) / 250, b = (35 - 40) / 10; return `<circle cx="${((a + 1) / 2 * (W - cw) + cw / 2).toFixed(1)}" cy="${((1 - (b + 1) / 2) * (W - cw) + cw / 2).toFixed(1)}" r="5" fill="none" stroke="var(--status-critical)" stroke-width="2"/>`; })() : "";
    const map = (title, val, lo, hi, passGrid, pmin) => {
      let rects = "";
      for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
        if (!s.domain[i][j]) { rects += `<rect ${cell(i, j)} fill="url(#d7h)"/>`; continue; }
        const t = Math.max(0, Math.min(1, (val[i][j] - lo) / (hi - lo || 1)));
        const ok = passGrid ? passGrid[i][j] : (pmin != null && val[i][j] >= pmin);
        rects += `<rect ${cell(i, j)} fill="${ok ? `color-mix(in srgb, var(--status-good) ${20 + t * 45}%, var(--surface-1))` : `color-mix(in srgb, var(--ink-1) ${6 + t * 50}%, var(--surface-1))`}"/>`;
      }
      return `<figure class="d7-map"><svg viewBox="0 0 ${W} ${W}" role="img" aria-label="${esc(title)}">${hatch}${rects}${dots}${opt}</svg><figcaption>${title}</figcaption></figure>`;
    };
    const rng = (g) => { let lo = Infinity, hi = -Infinity; g.forEach((row, i) => row.forEach((v, j) => { if (s.domain[i][j]) { lo = Math.min(lo, v); hi = Math.max(hi, v); } })); return [lo, hi]; };
    let html = "";
    for (const [k, v] of Object.entries(s.responses)) {
      const [lo, hi] = rng(v.mean);
      html += map(`${esc(RESP_KO[k] || k)} 예측 평균 ${lo.toFixed(2)}–${hi.toFixed(2)} · 초록 = 평균이 규격 안`, v.mean, lo, hi, v.mean_pass, null);
    }
    const [jl, jh] = rng(s.joint);
    html += map(`공동 통과확률 ${jl.toFixed(2)}–${jh.toFixed(2)} · 초록 = ≥ ${s.p_min}(없으면 영역 없음)`, s.joint, 0, 1, null, s.p_min);
    maps.innerHTML = html + `<p class="d7-muted d7-small">● 설계점(이 단면) ${s.x3 === -1 ? "· 빨간 원 = 논문 최적점(1400 psi, MCC 35%)" : ""}</p>`;
  }

  // ── ② 신규 API 범위 gate 샌드박스 ──
  const SAMPLE = [   // 명세 §13 예시 — 상류 후보 MCC 42%·CCS 2%는 reference, 연구자 제안 3수준은 근거 미검증
    { factor_id: "X1", name: "압축력", unit: "psi", quantity_kind: "pressure", kind: "CPP", low: 1200, center: 1500, high: 1800, reference_value: null, evidence: "UNVERIFIED_PROPOSAL" },
    { factor_id: "X2", name: "MCC", unit: "%w/w", quantity_kind: "mass_fraction", kind: "CMA", low: 30, center: 40, high: 50, reference_value: 42, evidence: "EXPERT_PROPOSAL" },
    { factor_id: "X3", name: "CCS", unit: "%w/w", quantity_kind: "mass_fraction", kind: "CMA", low: 1, center: 3, high: 5, reference_value: 2, evidence: "UNVERIFIED_PROPOSAL" },
  ];
  let sb = { mode: "NEW_API", factors: SAMPLE.map((x) => ({ ...x })), results: null, out: null };

  function sandboxForm() {
    const rows = sb.factors.map((x, i) => `<tr data-i="${i}">
      <td><input data-k="name" value="${esc(x.name)}" aria-label="요인 이름"></td><td><input data-k="unit" value="${esc(x.unit)}" aria-label="단위"></td>
      <td><select data-k="kind">${["CMA", "CPP", "CATEGORICAL", "MIXTURE_COMPONENT", "HARD_TO_CHANGE"].map((k) => `<option${k === x.kind ? " selected" : ""}>${k}</option>`).join("")}</select></td>
      <td><input data-k="reference_value" type="number" step="any" value="${x.reference_value ?? ""}" aria-label="상류 기준값"></td>
      <td><input data-k="low" type="number" step="any" value="${x.low ?? ""}" aria-label="low"></td><td><input data-k="center" type="number" step="any" value="${x.center ?? ""}" aria-label="center"></td><td><input data-k="high" type="number" step="any" value="${x.high ?? ""}" aria-label="high"></td>
      <td><select data-k="evidence">${EV.map((e) => `<option value="${e}"${e === x.evidence ? " selected" : ""}>${esc(EV_KO[e])}</option>`).join("")}</select></td>
      <td><button type="button" class="ghost d7-del" aria-label="요인 삭제">✕</button></td></tr>`).join("");
    return `<section class="d7-card"><h3>신규 API — 요인 3수준과 근거 ${badge("", "명세 §13 예시로 채워 둠")}</h3>
      <p class="d7-muted">상류 후보의 값(기준값)과 DoE 중심점은 다른 칸이다. 근거가 '제안'뿐이면 RSM으로 바로 가지 않고 <b>2k+1 feasibility</b>로 경계부터 확인한다.</p>
      <div class="table-wrap"><table class="edit d7-sbt"><thead><tr><th>요인</th><th>단위</th><th>종류</th><th>상류 기준값</th><th>low</th><th>center</th><th>high</th><th>범위 근거</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="d7-row"><label>연구 유형 <select id="d7-mode"><option value="NEW_API"${sb.mode === "NEW_API" ? " selected" : ""}>신규 API</option><option value="LITERATURE_REPLAY"${sb.mode === "LITERATURE_REPLAY" ? " selected" : ""}>문헌 재현</option></select></label>
        <button type="button" class="ghost" id="d7-add"${sb.factors.length >= 4 ? " disabled" : ""}>요인 추가</button>
        <button type="button" class="primary" id="d7-run">범위근거 gate 실행</button></div></section><div id="d7-sbout"></div>`;
  }

  function readForm() {
    document.querySelectorAll(".d7-sbt tbody tr").forEach((tr) => {
      const x = sb.factors[Number(tr.dataset.i)];
      tr.querySelectorAll("[data-k]").forEach((inp) => {
        const k = inp.dataset.k;
        x[k] = ["low", "center", "high", "reference_value"].includes(k) ? (inp.value === "" ? null : Number(inp.value)) : inp.value;
      });
      x.quantity_kind = x.unit === "psi" || x.unit === "kN" ? "pressure" : "mass_fraction";
    });
    sb.mode = $("d7-mode").value;
  }

  function sandbox() {
    $("d7-sandbox").innerHTML = sandboxForm();
    $("d7-add").addEventListener("click", () => { readForm(); sb.factors.push({ factor_id: `X${sb.factors.length + 1}`, name: "새 요인", unit: "%w/w", kind: "CMA", low: null, center: null, high: null, reference_value: null, evidence: "UNVERIFIED_PROPOSAL" }); sandbox(); });
    document.querySelectorAll(".d7-del").forEach((b) => b.addEventListener("click", () => { readForm(); sb.factors.splice(Number(b.closest("tr").dataset.i), 1); sb.factors.forEach((x, i) => { x.factor_id = `X${i + 1}`; }); sandbox(); }));
    $("d7-run").addEventListener("click", () => { readForm(); sb.results = null; runGate().catch(showErr); });
    if (sb.out) renderGate();
  }

  async function runGate() {
    sb.out = await post("/api/doe-v7/range-check", { mode: sb.mode, factors: sb.factors, feasibility_results: sb.results });
    renderGate();
  }

  function renderGate() {
    const o = sb.out, box = $("d7-sbout");
    let h = `<section class="d7-card"><h3>판정</h3>${decision(o.range_gate.route)}
      ${Object.entries(o.range_gate.factors).flatMap(([k, ds]) => ds.map((d) => `<div class="d7-muted">${esc(k)}: ${decision(d)}</div>`)).join("")}</section>`;
    if (o.feasibility_plan) {
      const p = o.feasibility_plan;
      h += `<section class="d7-card"><h3>Feasibility micro-study — ${p.condition_count}조건 (2k+1 축점, 최적화 아님)</h3>
        <p class="d7-muted">중심 1 + 요인마다 low·high(나머지는 중심). 결과는 RSM 적합에 넣지 않는다(${esc(p.fitting_eligibility)}). 연구자가 실험한 결과를 체크한다.</p>
        <div class="table-wrap"><table class="matrix"><thead><tr><th>조건</th>${sb.factors.map((x) => `<th>${esc(x.name)} ${esc(x.unit)}</th>`).join("")}<th>제조 가능</th><th>측정 가능</th></tr></thead><tbody>
        ${p.conditions.map((c) => `<tr><td><b>${esc(c.condition_id)}</b> <span class="d7-muted">${esc(c.role)}</span></td>${sb.factors.map((x) => `<td>${esc(c.settings[x.factor_id])}</td>`).join("")}
          <td><input type="checkbox" class="d7-fr" data-c="${esc(c.condition_id)}" data-k="manufacturable" ${!sb.results || sb.results[c.condition_id]?.manufacturable ? "checked" : ""} aria-label="${esc(c.condition_id)} 제조 가능"></td>
          <td><input type="checkbox" class="d7-fr" data-c="${esc(c.condition_id)}" data-k="measurable" ${!sb.results || sb.results[c.condition_id]?.measurable ? "checked" : ""} aria-label="${esc(c.condition_id)} 측정 가능"></td></tr>`).join("")}
        </tbody></table></div>
        <div class="d7-row"><button type="button" class="primary" id="d7-feval">결과로 판정</button><span class="d7-muted">예: 1800 psi에서 capping → X1_HIGH의 '제조 가능'을 끈다</span></div>
        ${o.feasibility_result ? decision(o.feasibility_result.route) : ""}</section>`;
    }
    if (o.doe_plan) {
      const d = o.doe_plan;
      h += `<section class="d7-card"><h3>${esc(d.design_type)} ${d.runs.length} run ${d.validation.ok ? badge("ok", "Validator 통과") : badge("bad", "Validator 실패")} <span class="d7-muted">seed ${d.random_seed} · 중심점 ${d.center_points}</span></h3>
        ${decision(o.design_decision)}
        <div class="table-wrap"><table class="matrix"><thead><tr><th>순서</th><th>표준</th>${sb.factors.map((x) => `<th>${esc(x.name)}</th>`).join("")}</tr></thead><tbody>
        ${d.runs.map((r) => `<tr><td>${r.run_order}</td><td>${r.std_order}</td>${sb.factors.map((x) => `<td>${esc(r.actual[x.factor_id])} <span class="d7-muted">(${r.coded[x.factor_id]})</span></td>`).join("")}</tr>`).join("")}
        </tbody></table></div></section>`;
    } else if (o.design_decision) h += `<section class="d7-card">${decision(o.design_decision)}</section>`;
    box.innerHTML = h;
    const fe = $("d7-feval");
    if (fe) fe.addEventListener("click", () => {
      sb.results = {};
      document.querySelectorAll(".d7-fr").forEach((c) => { (sb.results[c.dataset.c] ||= {})[c.dataset.k] = c.checked; });
      runGate().catch(showErr);
    });
  }

  function showErr(e) { const n = $("notice"); if (n) { n.hidden = false; n.textContent = `v7 화면 오류: ${e.message}`; } }

  function subtab(v) {
    document.querySelectorAll(".d7-subtab").forEach((b) => { b.classList.toggle("on", b.dataset.v === v); b.setAttribute("aria-selected", String(b.dataset.v === v)); });
    $("d7-wizard").hidden = v !== "wizard";
    $("d7-replay").hidden = v !== "replay";
    $("d7-sandbox").hidden = v !== "sandbox";
    if (v === "sandbox" && !$("d7-sandbox").innerHTML) sandbox();
    if (v === "replay" && !$("d7-replay").innerHTML) replay().catch(showErr);
    if (v === "wizard" && window.F1Doe7Wizard) window.F1Doe7Wizard.mount();
  }

  async function open() {
    if (loaded) return;
    loaded = true;
    try { await header(); } catch (e) { loaded = false; showErr(e); }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".d7-subtab").forEach((b) => b.addEventListener("click", () => subtab(b.dataset.v)));
    if ($("view-v7") && !$("view-v7").hidden) open();
  });
  document.addEventListener("f1:tab", (e) => { if (e.detail?.tab === "v7") open(); });
  window.F1Doe7 = { open };
})();
