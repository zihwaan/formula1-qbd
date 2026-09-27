/* DoE v7.0 실험개발 마법사 — 저장형 study(샌드박스)를 연구자가 단계마다 입력·승인한다(HITL).
   서버 /api/doe-v7/studies/* 가 상태기계다. 이 파일은 지금 상태의 질문 카드(폼 + 행동 버튼)와 단계별 결과만 그린다.
   - 행동 버튼 = 서버 행동 하나. 승인 지점(RB00)은 버튼에 표시한다. 막히면 서버 판정(rule ID)을 그대로 보여 준다.
   - "입력 채우기"는 문헌 재현 study에서만, 논문 표 값으로 폼만 채운다. 제출은 연구자가 누른다.
   - 반응 곡면은 surface3d.js(반응 × 세 번째 요인 수준 3D 격자, 논문 Figure 형식). */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const api = (p) => ((window.__BASE__ || "") + p);
  const fx = (x, d = 3) => (x == null || Number.isNaN(Number(x)) ? "—" : Number(x).toFixed(d).replace(/\.?0+$/, (m) => (m.startsWith(".") ? "" : m)));
  const LABEL = {
    handoff_data: "빠진 값 저장", handoff_confirm: "후보 확인", cqa_edit: "CQA 저장", cqa_approve: "CQA 승인",
    fmea_edit: "FMEA 저장", fmea_approve: "FMEA 승인", factor_select: "요인 확정", range_submit: "범위 제출", range_approve: "범위 승인",
    feasibility_plan_approve: "feasibility 계획 승인", feasibility_results_submit: "feasibility 결과 제출", revise: "재검토 시작",
    design_import: "설계 행렬 가져오기", plan_approve: "실험표·프로토콜 승인", plan_reject: "실험표 반려", results_submit: "결과 제출",
    results_confirm: "원자료와 대조 확인", plan_import: "실행 행렬 가져오기", results_revise: "다시 입력", model_accept_flags: "플래그 승인", vplan_lock: "확인 계획 잠금",
    verification_submit: "확인 결과 제출", final_approve: "최종 승인",
  };
  const POINT_KO = { CQA_SELECTION: "CQA 선택", FMEA_REVIEW: "FMEA 검토", FACTOR_AND_RANGE_SELECTION: "요인·범위", FEASIBILITY_PLAN: "feasibility 계획",
    DOE_PLAN: "DoE 계획", EXECUTION_PROTOCOL: "실행 프로토콜", MODEL_ACCEPTANCE_WITH_FLAGS: "플래그 모델 수용", VERIFICATION_PLAN: "확인 계획",
    VERIFIED_OPERATING_REGION: "확인 영역" };
  // 폼이 있는 행동 → 같은 폼을 읽는 짝 행동(저장 후 승인)
  const SAVE_BEFORE = { cqa_approve: "cqa_edit", fmea_approve: "fmea_edit", range_approve: "range_submit", handoff_confirm: "handoff_data" };
  const FORM_OF = { HANDOFF_RECEIVED: "handoff_data", CQA_REVIEW: "cqa_edit", FMEA_REVIEW: "fmea_edit", FACTOR_SELECTION: "factor_select",
    RANGE_EVIDENCE_CHECK: "range_submit", RANGE_REVISION_REQUIRED: "range_submit", WAITING_FEASIBILITY_RESULTS: "feasibility_results_submit",
    DOE_PLAN_REVIEW: "plan_approve", WAITING_FOR_RESULTS: "results_submit", MODEL_FIT: "model_accept_flags", PROVISIONAL_DESIGN_SPACE: "vplan_lock",
    WAITING_VERIFICATION_RESULTS: "verification_submit", PROTOTYPE_REVISION_REQUIRED: "revise", MODEL_INADEQUATE: "revise",
    REGION_REVISION_REQUIRED: "revise", ADVANCED_DESIGN_REQUIRED: "design_import" };
  const ROLES = ["DOE_RESPONSE", "MONITOR_ONLY", "NOT_APPLICABLE"];
  const OPS = ["", "LE", "GE", "BETWEEN", "TARGET_TOL", "PASS_FAIL"];
  const KINDS = ["", "mass", "time", "force", "pressure", "fraction_mass", "temperature"];
  const RANGE_EV = ["", "MEASURED_PRIOR_BATCH", "VERIFIED_EXTERNAL_DATA", "REPORTED_NO_RAW_DATA", "EXPERT_PROPOSAL", "UNVERIFIED_PROPOSAL"];
  const RESULT_EV = ["MEASURED_IN_STUDY", "LITERATURE_DIRECT", "VERIFIED_EXTERNAL_DATA", "MEASURED_PRIOR_BATCH", "LITERATURE_DIGITIZED", "SYNTHETIC_DEMO"];
  const VER_EV = ["VERIFICATION_BATCH", "LITERATURE_DIRECT", "MEASURED_IN_STUDY", "SYNTHETIC_DEMO"];
  const DISP = ["DOE_CANDIDATE", "FIXED", "EXCLUDED", "CONTROL_SOP", "MONITOR", "MATERIAL_SPEC", "REQUEST_DATA", "CONFIRMATION_REQUIRED"];

  let cur = null;           // 서버 view
  let draft = {};           // 행동 → 채우기 값
  let dirty = false;
  let busy = false;
  let surf = { source: null, slice: null };
  let skipRestore = false;   // 후보에서 새 study를 여는 중이면 지난 study를 다시 불러오지 않는다

  // ── 통신 ──────────────────────────────────────────────────────────────
  async function req(path, opt = {}) {
    const r = await fetch(api(path), opt);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      const det = d.detail;
      const e = new Error(typeof det === "string" ? det : (det?.message || `${path} ${r.status}`) + (det?.errors ? ` — ${det.errors.join(" / ")}` : ""));
      e.status = r.status;
      throw e;
    }
    return d;
  }
  const key = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
  function note(msg, bad) {
    const n = $("d7w-msg");
    if (!n) return;
    n.hidden = !msg;
    n.textContent = msg || "";
    n.classList.toggle("bad", !!bad);
  }

  async function load(sid) {
    cur = await req(`/api/doe-v7/studies/${encodeURIComponent(sid)}`);
    draft = {}; dirty = false; surf.source = null; surf.slice = null;
    try { localStorage.setItem("f1:d7study", sid); } catch (e) { /* 무시 */ }
    render();
    refreshList();
  }

  async function create(body) {
    note("study를 만드는 중…");
    cur = await req("/api/doe-v7/studies", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key() }, body: JSON.stringify(body) });
    draft = {}; dirty = false; surf.source = null; surf.slice = null;
    try { localStorage.setItem("f1:d7study", cur.study.study_id); } catch (e) { /* 무시 */ }
    note("");
    render();
    refreshList();
  }

  async function act(action, payload) {
    const s = cur.study;
    return req(`/api/doe-v7/studies/${encodeURIComponent(s.study_id)}/actions/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": key(), "Expected-State-Version": String(s.state_version) },
      body: JSON.stringify({ payload }),
    });
  }

  async function doAction(action) {
    if (busy || !cur) return;
    busy = true;
    lock(true);
    note(`${LABEL[action] || action} 처리 중…`);
    try {
      const form = FORM_OF[cur.study.status];
      const save = SAVE_BEFORE[action];
      if (save && save === form && dirty) {
        cur = await act(save, collect(save));
        dirty = false;
        if (cur.action_result?.blocked?.length && save !== "handoff_data") { finish(save); return; }
      }
      let payload = action === form || ["plan_reject", "final_approve"].includes(action) ? collect(action) : {};
      if (action === "plan_import") {
        payload = collect("plan_import");
        if (!payload.runs.length && cur.study.dataset) {
          const r = await req(`/api/doe-v7/studies/${encodeURIComponent(cur.study.study_id)}/fill/plan_import`);
          payload = { runs: r.payload.runs, source: r.payload.source };
        }
        if (!payload.runs.length) throw new Error("가져올 실행 행렬이 없습니다 — CSV(첫 줄 = 요인 ID)를 붙여 넣으세요.");
      }
      cur = await act(action, payload);
      finish(action);
    } catch (e) {
      note(e.status === 409 && /state_version|먼저 바뀌었/.test(e.message) ? "다른 곳에서 먼저 바뀌었습니다 — 새로 불러옵니다." : e.message, true);
      if (e.status === 409) { try { await load(cur.study.study_id); } catch (x) { /* 무시 */ } }
    } finally {
      busy = false;
      lock(false);
    }
  }

  function finish(action) {
    const r = cur.action_result || {};
    draft = {}; dirty = false;
    render();
    if (r.blocked?.length) note(`${LABEL[action] || action}: 막혔습니다 — ${r.blocked.join(", ")} (아래 판정 참고)`, true);
    else note(`${LABEL[action] || action} 완료 → ${cur.study.status}`);
    refreshList();
  }

  function lock(on) { document.querySelectorAll("#d7w-ask button").forEach((b) => { b.disabled = on; }); }

  async function fill() {
    const action = FORM_OF[cur.study.status];
    if (!action) return;
    const r = await req(`/api/doe-v7/studies/${encodeURIComponent(cur.study.study_id)}/fill/${action}`);
    if (!r.payload) { note("이 study에는 채울 문헌 값이 없습니다 — 연구자가 직접 입력합니다.", true); return; }
    draft[action] = r.payload;
    dirty = true;
    renderAsk();
    note(r.payload.note ? `채웠습니다 — ${r.payload.note} 확인 후 버튼을 누르세요.` : "채웠습니다 — 확인 후 버튼을 누르세요.");
  }

  async function csvFill() {
    const text = ($("d7w-csv")?.value || "").trim();
    if (!text) { note("CSV를 붙여 넣으세요.", true); return; }
    const r = await req(`/api/doe-v7/studies/${encodeURIComponent(cur.study.study_id)}/results-csv`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ csv: text }) });
    const prev = draft.results_submit?.rows || [];
    const merged = Object.fromEntries(prev.map((x) => [x.run_id, x]));
    r.rows.forEach((x) => { merged[x.run_id] = { ...(merged[x.run_id] || {}), ...x, values: { ...(merged[x.run_id]?.values || {}), ...x.values } }; });
    draft.results_submit = { rows: Object.values(merged) };
    dirty = true;
    renderAsk();
    note(`${r.note} 표를 확인하고 결과 제출을 누르세요.`, !!(r.unmatched_csv_rows?.length));
  }

  // ── 데이터셋으로 시작 — run 단위 실험 데이터(JSON 공통 형식) ───────────────────────────
  function datasetPanel() {
    const box = $("d7w-ds");
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `<p class="d7-muted">run 단위 실험 데이터를 가진 DoE를 공통 형식(JSON)으로 넣으면 같은 6단계 study가 됩니다 — 요인(1–3, FMEA 후보 요인 key) ·
      반응(1–4, CQA ID·판정 기준) · run(요인 실제값 · 반응값) · 출처는 필수, 처방·공정·설비·보고 모형·확인점은 선택입니다. 빠진 값은 만들지 않고 단계별 규칙이 요청합니다.
      <a href="${api("/api/doe-v7/datasets/schema")}" target="_blank" rel="noopener">형식 설명</a> ·
      <a href="${api("/api/doe-v7/datasets/cbd_odt")}" target="_blank" rel="noopener">실데이터 예(Monton 2026 CBD)</a></p>
      <textarea id="d7w-ds-text" rows="8" spellcheck="false" placeholder='{"title": …, "source": {"citation": …}, "factors": […], "responses": […], "runs": […]}'></textarea>
      <div class="d7w-acts"><label class="ghost d7w-file">JSON 파일 <input type="file" id="d7w-ds-file" accept=".json,application/json"></label>
        <button type="button" class="ghost" id="d7w-ds-check">형식 검사</button><button type="button" class="primary" id="d7w-ds-go">이 데이터셋으로 study 시작</button></div>
      <div id="d7w-ds-out" class="d7-muted"></div>`;
    const parse = () => { try { return JSON.parse($("d7w-ds-text").value); } catch (e) { throw new Error(`JSON을 읽지 못했습니다: ${e.message}`); } };
    const show = (html, bad) => { const o = $("d7w-ds-out"); o.innerHTML = html; o.classList.toggle("bad", !!bad); };
    $("d7w-ds-file").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) $("d7w-ds-text").value = await f.text(); });
    $("d7w-ds-check").addEventListener("click", async () => {
      try {
        const r = await req("/api/doe-v7/datasets/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataset: parse() }) });
        show(r.ok ? `형식 통과 — ${esc(r.summary.title)} · 요인 ${r.summary.factors} · 반응 ${r.summary.responses} · run ${r.summary.runs} · ${esc(r.summary.study_type)}`
          : `<b>형식 오류</b><ul class="d7-list">${r.errors.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`, !r.ok);
      } catch (e) { show(esc(e.message), true); }
    });
    $("d7w-ds-go").addEventListener("click", async () => {
      try {
        await create({ source: "dataset", dataset: parse() });
        box.hidden = true;
      } catch (e) {
        show(esc(e.message), true);
      }
    });
  }

  async function refreshList() {
    try {
      const d = await req("/api/doe-v7/studies");
      const sel = $("d7w-list");
      if (!sel) return;
      const id = cur?.study?.study_id;
      sel.innerHTML = `<option value="">— 열린 study 선택 —</option>` + d.studies.map((s) =>
        `<option value="${esc(s.study_id)}" ${s.study_id === id ? "selected" : ""}>${esc(s.title || s.candidate_ref)} · ${esc(s.status)}</option>`).join("");
    } catch (e) { /* 목록은 보조 */ }
  }

  // ── 공용 조각 ──────────────────────────────────────────────────────────
  const badge = (cls, t) => `<span class="d7-badge ${cls}">${esc(t)}</span>`;
  const effCls = (e) => (e === "BLOCK_STAGE" || e === "INVALIDATE" ? "bad" : e === "REQUEST_DATA" || e === "WARNING" ? "warn" : e === "PASS" ? "ok" : "");
  const decision = (d) => `<div class="d7-decision">${badge(effCls(d.gate_effect), d.gate_effect)} <code>${esc(d.rule_id)}</code> <b>${esc(d.result_code)}</b>
    <span class="d7-muted">${esc(d.message_ko)}${d.factor ? ` · ${esc(d.factor)}` : ""}${d.cqa ? ` · ${esc(d.cqa)}` : ""}${d.run ? ` · ${esc(d.run)}` : ""}${d.role ? ` · ${esc(d.role)}` : ""}${d.response ? ` · ${esc(d.response)}` : ""}${d.detail ? ` · ${esc(d.detail)}` : ""}</span></div>`;
  const decisions = (ev) => (ev && ev.decisions?.length ? `<div class="d7w-decs">${ev.decisions.map(decision).join("")}</div>` : "");
  const opt = (vals, v, labels = {}) => vals.map((x) => `<option value="${esc(x)}" ${String(x) === String(v ?? "") ? "selected" : ""}>${esc(labels[x] ?? (x === "" ? "—" : x))}</option>`).join("");
  const inp = (name, v, attrs = "") => `<input data-f="${esc(name)}" value="${esc(v ?? "")}" ${attrs}>`;
  const num = (name, v) => inp(name, v, `inputmode="decimal" class="d7w-num"`);
  const sel = (name, vals, v, labels) => `<select data-f="${esc(name)}">${opt(vals, v, labels)}</select>`;
  const val = (root, name) => { const el = root.querySelector(`[data-f="${name}"]`); return el ? (el.type === "checkbox" ? el.checked : el.value.trim()) : undefined; };
  const nval = (root, name) => { const v = val(root, name); if (v === "" || v == null) return null; const n = Number(v); return Number.isFinite(n) ? n : v; };
  const tbl = (head, rows) => `<div class="table-wrap"><table class="matrix d7w-tbl"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  const factorName = (st, fid) => { const f = st.factors[fid]; return f ? `${fid} ${f.name}` : fid; };

  // ── 폼(상태 → HTML, 행동 → 수집) ─────────────────────────────────────────
  const FORMS = {
    handoff_data(st, d) {
      const h = st.handoff;
      const crit = h.ingredients.filter((i) => i.is_critical);
      return `<div class="d7w-grid">
        <label>설비 ID ${inp("equipment_id", d.equipment_id ?? h.equipment_id ?? "")}</label>
        <label>배치 규모(정 수) ${num("batch_units", d.batch_scale?.units ?? h.batch_scale?.units ?? h.batch_scale?.tablets ?? "")}</label>
        ${crit.map((i) => `<label>${esc(i.material_id)} 등급 <input data-grade="${esc(i.material_id)}" value="${esc(i.material_grade || "")}"></label>`).join("")}
      </div>`;
    },
    cqa_edit(st, d) {
      const by = Object.fromEntries((d.edits || []).map((e) => [e.cqa_id, e]));
      const rows = Object.values(st.cqas).map((c0) => {
        const c = { ...c0, ...(by[c0.cqa_id] || {}) };
        return `<tr data-cqa="${esc(c.cqa_id)}" data-rkey="${esc(c.response_key || "")}"><td><b>${esc(c.name)}</b><div class="d7-muted mono">${esc(c.cqa_id)}</div></td>
          <td>${sel("analysis_role", ROLES, c.analysis_role)}</td><td>${sel("acceptance_operator", OPS, c.acceptance_operator)}</td>
          <td>${num("lower", c.lower)}</td><td>${num("upper", c.upper)}</td><td>${inp("unit", c.unit, 'class="d7w-s"')}</td>
          <td>${inp("test_method_id", c.test_method_id)}</td><td>${inp("test_method_version", c.test_method_version)}</td>
          <td>${inp("summary_definition", c.summary_definition, 'class="d7w-s"')}</td><td>${inp("replicate_policy", c.replicate_policy)}</td>
          <td>${inp("criterion_source", c.criterion_source, 'class="d7w-s"')}</td><td>${inp("refs", (c.evidence_refs || []).join("; "))}</td>
          <td>${inp("rationale", c.rationale)}</td></tr>`;
      });
      return `<p class="d7-muted">DOE_RESPONSE ≤ 4 · 규격값은 시스템이 만들지 않습니다(출처와 함께 입력). is_cqa와 모델링 역할은 별개입니다.</p>
        ${tbl(["CQA", "역할", "판정", "하한", "상한", "단위", "시험법", "버전", "요약", "반복", "기준 출처", "근거", "사유"], rows)}`;
    },
    fmea_edit(st) {
      const rows = st.fmea.rows.map((r) => `<tr data-row="${esc(r.row_id)}"><td class="mono">${esc(r.row_id)}</td>
        <td>${esc(r.cause)}<div class="d7-muted">→ ${esc(r.failure_mode)}</div></td><td class="d7-small">${esc(r.cqa_effect_ids.join(", "))}</td>
        <td>${sel("severity", ["", 1, 2, 3, 4, 5], r.severity)}</td><td>${sel("occurrence", ["UNKNOWN", 1, 3, 5], r.occurrence)}</td>
        <td>${sel("detectability", ["", 1, 3, 5], r.detectability)}</td><td>${r.rpn ?? "—"}</td><td>${sel("disposition", DISP, r.disposition)}</td>
        <td>${inp("rationale", r.rationale)}</td><td>${inp("alternative_control", r.alternative_control)}</td>
        <td>${inp("detection_method_id", r.detection_method_id, 'class="d7w-s"')}</td></tr>`);
      return `<p class="d7-muted">발생도 근거가 없으면 UNKNOWN(RPN 계산 안 함). 심각도 4 이상은 대체 관리·사유 없이 제외할 수 없습니다(RB05).</p>
        ${tbl(["ID", "원인 → 실패모드", "CQA", "S", "O", "D", "RPN", "처분", "사유", "대체 관리", "검출 시험법"], rows)}`;
    },
    factor_select(st, d) {
      const chosen = Object.fromEntries((d.selected || []).map((x) => [x.key, x]));
      const ings = st.handoff.ingredients.map((i) => i.material_id);
      const cands = [...st.factor_candidates].sort((a, b) => (b.doe_candidate - a.doe_candidate) || (b.high_risk - a.high_risk));
      const rows = cands.map((c) => {
        const x = chosen[c.key];
        return `<tr data-key="${esc(c.key)}"><td><input type="checkbox" data-f="pick" ${x ? "checked" : ""}></td>
          <td><b>${esc(c.key)}</b>${c.doe_candidate ? badge("", "DoE 후보") : ""}${c.high_risk ? badge("warn", "고위험") : ""}</td>
          <td class="d7-small">${esc(c.linked_cqa_ids.join(", ") || "—")}</td><td class="mono d7-small">${esc(c.fmea_refs.join(", "))}</td>
          <td>${inp("name", x?.name ?? "")}</td><td>${sel("kind", ["CPP", "CMA"], x?.kind ?? c.kind ?? "CMA")}</td>
          <td>${sel("material_id", ["", ...ings], x?.material_id ?? "")}</td>
          <td>${c.high_risk ? inp("fixed_value", "") : ""}</td><td>${c.high_risk ? inp("fixed_rationale", "") : ""}</td></tr>`;
      });
      return `<p class="d7-muted">최대 3개. 조성 요인(%w/w)은 성분을 고르면 run sheet에서 balance 성분으로 100%를 맞춥니다. 고르지 않은 고위험 요인은 고정값·사유가 필요합니다(FS015).</p>
        ${tbl(["선택", "후보", "연결 CQA", "FMEA", "요인 이름", "종류", "성분(%w/w)", "고정값", "고정 사유"], rows)}`;
    },
    range_submit(st, d) {
      const by = Object.fromEntries((d.factors || []).map((f) => [f.factor_id, f]));
      const rows = Object.entries(st.factors).sort().map(([fid, f0]) => {
        const f = { ...f0, ...(by[fid] || {}) };
        const ev = f.evidence_status || {};
        return `<tr data-fid="${esc(fid)}"><td><b>${esc(fid)}</b> ${esc(f.name)}<div class="d7-muted">기준 처방값 ${f.reference_value ?? "—"} (표시만 · center 아님)</div></td>
          <td>${inp("unit", f.unit, 'class="d7w-s"')}</td><td>${sel("quantity_kind", KINDS, f.quantity_kind)}</td>
          <td>${num("low", f.low)}</td><td>${num("center", f.center)}</td><td>${num("high", f.high)}</td>
          <td>${sel("ev_low", RANGE_EV, ev.low)}</td><td>${sel("ev_center", RANGE_EV, ev.center)}</td><td>${sel("ev_high", RANGE_EV, ev.high)}</td>
          <td>${inp("refs", (f.range_evidence_refs || []).join("; "))}</td>
          <td><input type="checkbox" data-f="applicability_confirmed" ${f.applicability_confirmed ? "checked" : ""}></td></tr>`;
      });
      return `<p class="d7-muted">근거 등급은 경계마다 고릅니다. FEASIBILITY_CONFIRMED는 feasibility 결과로만 생기며 직접 고를 수 없습니다.</p>
        ${tbl(["요인", "단위", "물리량(M04)", "low", "center", "high", "근거 low", "근거 center", "근거 high", "출처(위치)", "외부자료 적용성 확인"], rows)}`;
    },
    feasibility_results_submit(st, d) {
      const res = d.results || {};
      const yn = (name, v) => sel(name, ["", "true", "false"], v == null ? "" : String(v), { "": "—", true: "예", false: "아니오" });
      const rows = st.feasibility.plan.conditions.map((c) => {
        const r = res[c.condition_id] || {};
        return `<tr data-cid="${esc(c.condition_id)}"><td class="mono">${esc(c.condition_id)}</td><td>${esc(c.role)}</td>
          <td class="d7-small">${Object.entries(c.settings).map(([k, v]) => `${esc(k)}=${fx(v)}`).join(" · ")}</td>
          <td>${yn("manufacturable", r.manufacturable)}</td><td>${yn("measurable", r.measurable)}</td><td>${yn("critical_incompatibility", r.critical_incompatibility)}</td>
          <td>${inp("batch_id", r.batch_id)}</td><td>${inp("note", r.note)}</td></tr>`;
      });
      return `<p class="d7-muted">feasibility는 경계가 제조·측정 가능한지 보는 시험입니다(최적화 아님). 결과는 모델 적합에 넣지 않습니다(FD009).</p>
        ${tbl(["조건", "역할", "설정", "제조 가능", "측정 가능", "치명 비호환", "batch", "메모"], rows)}`;
    },
    plan_approve(st, d) {
      const bal = d.balance_material ?? st.run_sheet?.balance_material ?? "";
      const ings = st.handoff.ingredients.filter((i) => !i.is_critical).map((i) => i.material_id);
      return `<div class="d7w-grid">
        <label>샘플링 계획 <textarea data-f="sampling_plan" rows="2">${esc(d.sampling_plan ?? st.protocol?.sampling_plan ?? "")}</textarea></label>
        <label>중단 기준 <textarea data-f="stop_criteria" rows="2">${esc(d.stop_criteria ?? st.protocol?.stop_criteria ?? "")}</textarea></label>
        ${st.run_sheet?.balance_material != null ? `<label>balance 성분 ${sel("balance_material", ings, bal)}</label>` : ""}
        <label>반려 사유(반려할 때만) ${inp("reason", "")}</label></div>
        <details class="d7w-import"${st.dataset ? " open" : ""}><summary>이미 실행한 설계 행렬 쓰기(선행 batch · 외부 원자료 · 문헌)</summary>
          <p class="d7-muted">${st.dataset ? "데이터셋의 실행 행렬을 쓰려면 비워 두고 <b>실행 행렬 가져오기</b>를 누르세요. " : ""}CSV 첫 줄은 요인 ID(${esc(Object.keys(st.factors).sort().join(", "))}), 한 줄이 한 run(실제값)입니다. 같은 Validator로 다시 검사하고, 설계점이 표준 설계와 같으면 그 지지 영역을 씁니다.</p>
          <textarea data-f="import_csv" rows="4" placeholder="${esc(Object.keys(st.factors).sort().join(","))}"></textarea></details>`;
    },
    results_submit(st, d) {
      const plan = st.plans[st.active_plan];
      const keys = Object.values(st.cqas).filter((c) => c.analysis_role === "DOE_RESPONSE").map((c) => c.response_key || c.cqa_id);
      const by = Object.fromEntries((d.rows || []).map((r) => [r.run_id, r]));
      const rows = [...plan.runs].sort((a, b) => a.run_order - b.run_order).map((r0) => {
        const r = by[r0.run_id] || st.results[r0.run_id] || {};
        return `<tr data-run="${esc(r0.run_id)}"><td class="mono">${esc(r0.run_id)}</td>
          <td class="d7-small">${Object.entries(r0.actual).map(([k, v]) => `${esc(k)}=${fx(v)}`).join(" · ")}</td>
          <td>${inp("batch_id", r.batch_id)}</td><td>${inp("parent_blend_id", r.parent_blend_id)}</td><td>${inp("test_method_version", r.test_method_version, 'class="d7w-s"')}</td>
          <td>${sel("replicate_independence", ["UNKNOWN", "INDEPENDENT_BATCH", "WITHIN_BATCH"], r.replicate_independence || "UNKNOWN")}</td>
          <td>${sel("evidence_status", RESULT_EV, r.evidence_status || "MEASURED_IN_STUDY")}</td>
          ${keys.map((k) => `<td>${num(`v:${k}`, r.values?.[k])}</td>`).join("")}</tr>`;
      });
      return `<details class="d7w-import"><summary>CSV로 붙여 넣기(엑셀에서 복사해도 됩니다)</summary>
          <p class="d7-muted">머리행: <code>run_id</code> 또는 요인 열(${esc(Object.keys(st.factors).sort().map((f) => `${f}/${st.factors[f].name}`).join(", "))}) + 반응 열(${keys.map(esc).join(", ")}) + 선택 열 batch_id · blend_id · test_method_version · replicate_independence · evidence_status. run_id가 없으면 요인 실제값으로 계획 run에 짝짓습니다. 표만 채우고 제출하지 않습니다.</p>
          <textarea id="d7w-csv" rows="5"></textarea><button type="button" class="ghost" id="d7w-csv-go">CSV를 표에 채우기</button></details>
        <p class="d7-muted">run 순서대로 · batch마다 새 ID. 같은 blend를 다른 run으로 세면 가짜 반복입니다(RQ009).</p>
        ${tbl(["run", "설정(실제값)", "batch", "blend", "시험법 버전", "독립성", "근거 등급", ...keys.map(esc)], rows)}`;
    },
    model_accept_flags(st, d) {
      return `<label class="d7w-full">플래그를 받아들이는 사유 <textarea data-f="rationale" rows="2">${esc(d.rationale ?? "")}</textarea></label>`;
    },
    vplan_lock(st, d) {
      const pts = d.points || st.region?.proposal || [];
      const ids = Object.keys(st.factors).sort();
      const rows = pts.map((p, i) => `<tr data-i="${i}"><td>${sel("role", ["SETPOINT", "BOUNDARY", "ROBUSTNESS"], p.role)}</td>
        ${ids.map((fid) => `<td>${num(`c:${fid}`, p.coded?.[fid] != null ? Number(p.coded[fid]).toFixed(3) : "")}<div class="d7-muted">${p.actual ? fx(p.actual[fid]) : ""} ${esc(st.factors[fid].unit || "")}</div></td>`).join("")}
        <td>${fx(p.joint_p)}</td></tr>`);
      return `<p class="d7-muted">결과를 보기 전에 잠급니다(VR002). 세 역할이 모두 필요합니다(VR001). 제안점은 고칠 수 있습니다(coded −1…1).</p>
        ${tbl(["역할", ...ids.map((f) => esc(factorName(st, f)) + " (coded)"), "공동 통과확률"], rows)}`;
    },
    verification_submit(st, d) {
      const pts = st.verification.plan.points;
      const by = Object.fromEntries((d.points || []).map((p) => [p.role, p]));
      const keys = Object.keys(pts[0]?.prediction_intervals || {});
      const rows = pts.map((p) => {
        const r = by[p.role] || {};
        return `<tr data-role="${esc(p.role)}"><td><b>${esc(p.role)}</b></td><td>${inp("batch_id", r.batch_id)}</td><td>${inp("parent_blend_id", r.parent_blend_id)}</td>
          <td>${sel("evidence_status", VER_EV, r.evidence_status || "VERIFICATION_BATCH")}</td>
          ${keys.map((k) => `<td>${inp(`v:${k}`, (r.values?.[k] || []).join(", "), 'placeholder="lot 값, 쉼표"')}<div class="d7-muted">PI ${fx(p.prediction_intervals[k].pi[0], 2)}–${fx(p.prediction_intervals[k].pi[1], 2)}</div></td>`).join("")}</tr>`;
      });
      return `<p class="d7-muted">확인점마다 새 batch. 모델 적합에 쓴 batch·blend, 다른 점과 같은 batch는 독립 확인이 아닙니다(VR003·VR013·RQ009).</p>
        ${tbl(["역할", "batch", "blend", "근거 등급", ...keys.map(esc)], rows)}
        <label class="d7w-full">최종 승인 사유(모두 통과했을 때) <textarea data-f="rationale" rows="2"></textarea></label>`;
    },
    revise(st, d) {
      const lb = st.labloop.current;
      const pick = new Set(d.tests || []);
      return `${lb ? `<div class="d7w-lab"><b>${esc(lb.pattern_id)} · ${esc(lb.observed_pattern)}</b>
        <div class="d7-muted">가능한 원인: ${esc(lb.candidate_causes.join(" · "))}</div>
        ${lb.tests.map((t) => `<label class="d7w-check"><input type="checkbox" data-test="${esc(t.test_id)}" ${pick.has(t.test_id) ? "checked" : ""}> <b>${esc(t.display_name)}</b>
          <span class="d7-muted">${esc(t.test_category)} · ${esc(t.output_variable)} · ${esc(t.acceptance_logic)} · ${esc(t.allowed_for_agent)}</span></label>`).join("")}</div>` : ""}
        <label class="d7w-full">재검토 사유 <textarea data-f="reason" rows="2">${esc(d.reason ?? "")}</textarea></label>`;
    },
    design_import() {
      return `<label class="d7w-full">설계 행렬(실제값 CSV, 첫 줄 = 요인 ID) <textarea data-f="csv" rows="6" placeholder="X1,X2&#10;…"></textarea></label>
        <label>출처 ${inp("source", "")}</label>`;
    },
  };

  const COLLECT = {
    handoff_data(root) {
      const grades = {};
      root.querySelectorAll("[data-grade]").forEach((el) => { if (el.value.trim()) grades[el.dataset.grade] = el.value.trim(); });
      const units = nval(root, "batch_units");
      return { equipment_id: val(root, "equipment_id") || null, batch_scale: units ? { units } : null, material_grades: grades };
    },
    cqa_edit(root) {
      return { edits: [...root.querySelectorAll("tr[data-cqa]")].map((tr) => ({
        cqa_id: tr.dataset.cqa, response_key: tr.dataset.rkey || undefined, analysis_role: val(tr, "analysis_role"),
        acceptance_operator: val(tr, "acceptance_operator") || null, lower: nval(tr, "lower"), upper: nval(tr, "upper"), unit: val(tr, "unit") || null,
        test_method_id: val(tr, "test_method_id") || null, test_method_version: val(tr, "test_method_version") || null,
        summary_definition: val(tr, "summary_definition") || null, replicate_policy: val(tr, "replicate_policy") || null,
        criterion_source: val(tr, "criterion_source") || null, rationale: val(tr, "rationale") || "",
        evidence_refs: (val(tr, "refs") || "").split(";").map((x) => x.trim()).filter(Boolean),
      })) };
    },
    fmea_edit(root) {
      return { rows: [...root.querySelectorAll("tr[data-row]")].map((tr) => ({
        row_id: tr.dataset.row, severity: val(tr, "severity") || null, occurrence: val(tr, "occurrence"), detectability: val(tr, "detectability") || null,
        disposition: val(tr, "disposition"), rationale: val(tr, "rationale"), alternative_control: val(tr, "alternative_control"),
        detection_method_id: val(tr, "detection_method_id"),
      })) };
    },
    factor_select(root) {
      const trs = [...root.querySelectorAll("tr[data-key]")];
      const pref = (draft.factor_select?.selected || []).map((x) => x.key);      // 채운 순서(데이터셋 요인 순서)를 유지 → X1·X2·X3이 데이터셋과 같다
      const rank = (k) => (pref.includes(k) ? pref.indexOf(k) : 99);
      return {
        selected: trs.filter((tr) => val(tr, "pick")).sort((a, b) => rank(a.dataset.key) - rank(b.dataset.key)).map((tr) => ({ key: tr.dataset.key, name: val(tr, "name") || tr.dataset.key, kind: val(tr, "kind"),
          material_id: val(tr, "material_id") || null })),
        fixed: trs.filter((tr) => !val(tr, "pick") && tr.querySelector('[data-f="fixed_value"]')).map((tr) => ({
          key: tr.dataset.key, fixed_value: val(tr, "fixed_value") || null, fixed_rationale: val(tr, "fixed_rationale") || null })),
      };
    },
    range_submit(root) {
      return { factors: [...root.querySelectorAll("tr[data-fid]")].map((tr) => ({
        factor_id: tr.dataset.fid, unit: val(tr, "unit") || null, quantity_kind: val(tr, "quantity_kind") || null,
        low: nval(tr, "low"), center: nval(tr, "center"), high: nval(tr, "high"),
        evidence_status: { low: val(tr, "ev_low") || null, center: val(tr, "ev_center") || null, high: val(tr, "ev_high") || null },
        range_evidence_refs: (val(tr, "refs") || "").split(";").map((x) => x.trim()).filter(Boolean),
        applicability_confirmed: val(tr, "applicability_confirmed"),
      })) };
    },
    feasibility_results_submit(root) {
      const b = (v) => (v === "" ? null : v === "true");
      const results = {};
      root.querySelectorAll("tr[data-cid]").forEach((tr) => {
        results[tr.dataset.cid] = { manufacturable: b(val(tr, "manufacturable")), measurable: b(val(tr, "measurable")),
          critical_incompatibility: b(val(tr, "critical_incompatibility")), batch_id: val(tr, "batch_id") || null, note: val(tr, "note") || null };
      });
      return { results };
    },
    plan_approve(root) {
      return { sampling_plan: val(root, "sampling_plan"), stop_criteria: val(root, "stop_criteria"), balance_material: val(root, "balance_material") || undefined };
    },
    plan_reject(root) { return { reason: val(root, "reason") }; },
    plan_import(root) {
      const lines = (val(root, "import_csv") || "").split(/\n/).map((l) => l.trim()).filter(Boolean);
      if (!lines.length) return { runs: [] };
      const head = lines.shift().split(/[,\t]/).map((x) => x.trim());
      return { source: "연구자 입력 CSV", runs: lines.map((l) => { const c = l.split(/[,\t]/); return { actual: Object.fromEntries(head.map((h, i) => [h, Number(c[i])])) }; }) };
    },
    results_submit(root) {
      return { rows: [...root.querySelectorAll("tr[data-run]")].map((tr) => {
        const values = {};
        tr.querySelectorAll('[data-f^="v:"]').forEach((el) => { values[el.dataset.f.slice(2)] = el.value.trim() === "" ? null : Number(el.value); });
        return { run_id: tr.dataset.run, batch_id: val(tr, "batch_id") || null, parent_blend_id: val(tr, "parent_blend_id") || null,
          test_method_version: val(tr, "test_method_version") || null, replicate_independence: val(tr, "replicate_independence"),
          evidence_status: val(tr, "evidence_status"), values };
      }) };
    },
    model_accept_flags(root) { return { rationale: val(root, "rationale") }; },
    vplan_lock(root) {
      return { points: [...root.querySelectorAll("tr[data-i]")].map((tr) => {
        const coded = {};
        tr.querySelectorAll('[data-f^="c:"]').forEach((el) => { coded[el.dataset.f.slice(2)] = el.value.trim() === "" ? null : Number(el.value); });
        return { role: val(tr, "role"), coded };
      }) };
    },
    verification_submit(root) {
      return { points: [...root.querySelectorAll("tr[data-role]")].map((tr) => {
        const values = {};
        tr.querySelectorAll('[data-f^="v:"]').forEach((el) => { values[el.dataset.f.slice(2)] = el.value.split(",").map((x) => x.trim()).filter(Boolean).map(Number); });
        return { role: tr.dataset.role, batch_id: val(tr, "batch_id") || null, parent_blend_id: val(tr, "parent_blend_id") || null,
          evidence_status: val(tr, "evidence_status"), values };
      }) };
    },
    final_approve(root) { return { rationale: val(root, "rationale") }; },
    revise(root) {
      return { reason: val(root, "reason"), tests: [...root.querySelectorAll("[data-test]")].filter((el) => el.checked).map((el) => el.dataset.test) };
    },
    design_import(root) {
      const lines = (val(root, "csv") || "").split(/\n/).map((l) => l.trim()).filter(Boolean);
      const head = (lines.shift() || "").split(",").map((x) => x.trim());
      return { source: val(root, "source"), runs: lines.map((l) => { const c = l.split(","); return { actual: Object.fromEntries(head.map((h, i) => [h, Number(c[i])])) }; }) };
    },
  };
  function collect(action) { const root = $("d7w-form"); return root && COLLECT[action] ? COLLECT[action](root) : {}; }

  // ── 그리기 ─────────────────────────────────────────────────────────────
  function render() {
    const box = $("d7-wizard");
    if (!box) return;
    if (!cur) {
      box.querySelector("#d7w-main").innerHTML = `<section class="d7-card"><h3>실험개발 study</h3>
        <p class="d7-muted">① 후보 탐색의 통과 후보 카드에서 <b>v7 실험개발로 시작</b>을 누르거나, 위의 <b>CBD 문헌 재현으로 시작</b>으로 논문 데이터 study를 여세요.
        단계마다 연구자가 입력하고 승인해야 다음으로 넘어갑니다.</p></section>`;
      return;
    }
    const s = cur.study;
    const step = cur.step || 0;
    box.querySelector("#d7w-main").innerHTML = `
      <div class="d7w-head"><b>${esc(s.title || s.candidate_ref)}</b> ${badge("draft", s.execution_mode)} ${badge(s.study_type === "LITERATURE_REPLAY" ? "warn" : "", s.study_type === "LITERATURE_REPLAY" ? "문헌 재현 — 독립 검증 아님" : "신규 API")}
        <span class="d7-muted mono">${esc(s.study_id)} · v${s.state_version}</span></div>
      <ol class="d7w-steps">${cur.steps.map((x) => `<li class="${x.n < step ? "done" : x.n === step ? "on" : ""}"><span>${x.n}</span>${esc(x.name)}</li>`).join("")}</ol>
      <section class="d7-card d7w-ask" id="d7w-ask"></section>
      <div id="d7w-body" class="d7w-body"></div>`;
    renderAsk();
    renderBody();
  }

  function renderAsk() {
    const s = cur.study;
    const p = cur.prompt;
    const form = FORM_OF[s.status];
    const lb = p.labloop;
    const acts = p.actions.map((a) => `<button type="button" class="${a.action === form || a.approval_points.length ? "primary" : "ghost"}" data-act="${esc(a.action)}">${esc(LABEL[a.action] || a.action)}${a.approval_points.length ? ` <small>승인 · ${esc(a.approval_points.map((x) => POINT_KO[x] || x).join("·"))}</small>` : ""}</button>`).join("");
    $("d7w-ask").innerHTML = `
      <h3><span class="d7-badge">${esc(s.status)}</span> ${esc(p.question_ko)}</h3>
      ${p.blocking?.length ? `<div class="d7w-block"><b>막힌 판정</b>${p.blocking.map(decision).join("")}</div>` : ""}
      ${lb && form !== "revise" ? `<div class="d7w-lab"><b>RB18 ${esc(lb.pattern_id)}</b> ${esc(lb.observed_pattern)} → 판별시험 ${esc(lb.tests.map((t) => t.display_name).join(", "))}</div>` : ""}
      ${p.flagged?.length ? `<div class="d7-muted">플래그: ${esc(p.flagged.join(", "))}</div>` : ""}
      ${form && FORMS[form] ? `<div id="d7w-form" class="d7w-form">${FORMS[form](s, draft[form] || {})}</div>` : ""}
      <div class="d7w-acts">${s.demo && form ? `<button type="button" class="ghost" id="d7w-fill">입력 채우기(데이터셋 값)</button>` : ""}${acts}</div>
      <p class="d7-muted d7-small">${esc(cur.banner || "")} — 규칙은 모두 DRAFT(전문가 검토 전)이며 이 study는 샌드박스입니다.</p>`;
    $("d7w-ask").querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () => doAction(b.dataset.act)));
    const fb = $("d7w-fill");
    if (fb) fb.addEventListener("click", () => fill().catch((e) => note(e.message, true)));
    const fm = $("d7w-form");
    if (fm) fm.addEventListener("input", () => { dirty = true; });
    const cg = $("d7w-csv-go");
    if (cg) cg.addEventListener("click", () => csvFill().catch((e) => note(e.message, true)));
  }

  function section(title, inner, open = false) {
    return `<details class="d7-card d7w-sec" ${open ? "open" : ""}><summary><h3>${title}</h3></summary>${inner}</details>`;
  }

  function renderBody() {
    const s = cur.study;
    const out = [];
    const h = s.handoff;
    const status = s.status;
    const step = cur.step || 0;
    out.push(section(`후보 · 기준 처방 ${badge("", "REFERENCE_PROTOTYPE")}`, `
      <p class="d7-muted">${esc(h.source?.citation || h.source?.run_id || "")} · ${esc(h.handoff_id)} · fingerprint <span class="mono">${esc(String(h.formulation_fingerprint).slice(0, 12))}</span></p>
      ${tbl(["성분", "등급", "기능", "%w/w", "mg", "값 역할"], h.ingredients.map((i) => `<tr><td>${esc(i.material_id)}${i.is_critical ? " " + badge("", "주성분") : ""}</td><td class="d7-small">${esc(i.material_grade || "—")}</td><td>${esc(i.function)}</td><td>${fx(i.percent_w_w)}</td><td>${fx(i.amount_mg)}</td><td class="mono d7-small">${esc(i.value_role)}</td></tr>`))}
      <p class="d7-small">공정 ${esc(h.process_route_id)} · ${esc(h.process_steps.map((x) => x.text).join(" → ") || "—")}<br>설비 ${esc(h.equipment_id || "—")} · 배치 ${esc(JSON.stringify(h.batch_scale) || "—")}
      ${h.fixed_parameters?.length ? `<br>고정값 ${h.fixed_parameters.map((f) => `${esc(f.name)} ${esc(f.value)} ${esc(f.unit || "")}`).join(" · ")}` : ""}</p>
      ${decisions(s.evaluations.handoff)}`, step === 1 && status === "HANDOFF_RECEIVED"));
    if (Object.keys(s.cqas).length && status !== "CQA_REVIEW") {
      const doe = Object.values(s.cqas).filter((c) => c.analysis_role === "DOE_RESPONSE");
      out.push(section(`CQA — DoE 반응 ${doe.length}개`, `${tbl(["CQA", "역할", "기준", "단위", "시험법", "버전"], Object.values(s.cqas).map((c) =>
        `<tr><td>${esc(c.name)}</td><td>${esc(c.analysis_role)}</td><td>${esc(c.acceptance_operator || "—")} ${c.lower ?? ""}${c.upper != null ? "–" + c.upper : ""}</td><td>${esc(c.unit || "")}</td><td class="mono d7-small">${esc(c.test_method_id || "")}</td><td class="d7-small">${esc(c.test_method_version || "")}</td></tr>`))}
        ${decisions(s.evaluations.cqa)}`));
    }
    if (s.fmea.rows.length && !["FMEA_REVIEW", "CQA_REVIEW"].includes(status)) {
      out.push(section(`FMEA v${s.fmea.version} ${s.fmea.approved ? badge("ok", "승인") : ""}`, tbl(["ID", "원인 → 실패모드", "S", "O", "D", "RPN", "처분"], s.fmea.rows.map((r) =>
        `<tr><td class="mono">${esc(r.row_id)}</td><td>${esc(r.cause)} → ${esc(r.failure_mode)}</td><td>${r.severity ?? "—"}</td><td>${esc(r.occurrence)}</td><td>${r.detectability ?? "—"}</td><td>${r.rpn ?? "—"}</td><td>${esc(r.disposition)}</td></tr>`))));
    }
    if (Object.keys(s.factors).length && !["FACTOR_SELECTION", "RANGE_EVIDENCE_CHECK", "RANGE_REVISION_REQUIRED"].includes(status)) {
      out.push(section("요인 · 범위 · 근거", tbl(["요인", "단위", "low", "center", "high", "근거(low/center/high)", "기준 처방값"], Object.entries(s.factors).sort().map(([fid, f]) =>
        `<tr><td><b>${esc(fid)}</b> ${esc(f.name)}</td><td>${esc(f.unit || "")}</td><td>${fx(f.low)}</td><td>${fx(f.center)}</td><td>${fx(f.high)}</td><td class="d7-small">${esc(["low", "center", "high"].map((b) => (f.evidence_status || {})[b] || "—").join(" / "))}</td><td>${fx(f.reference_value)}</td></tr>`))
        + decisions(s.evaluations.range)));
    } else if (s.range_gate) {
      out.push(section("범위 판정(RB07)", decisions(s.evaluations.range), true));
    }
    if (s.feasibility) {
      const fz = s.feasibility;
      out.push(section(`feasibility — ${esc(fz.plan.design_type)} ${fz.plan.condition_count}조건 (round ${fz.round})`,
        tbl(["조건", "역할", "설정"], fz.plan.conditions.map((c) => `<tr><td class="mono">${esc(c.condition_id)}</td><td>${esc(c.role)}</td><td class="d7-small">${Object.entries(c.settings).map(([k, v]) => `${esc(k)}=${fx(v)}`).join(" · ")}</td></tr>`))
        + (fz.history || []).map((x) => `<div class="d7-small">round ${x.round}: ${esc(x.route)}</div>`).join("") + decisions(s.evaluations.feasibility),
        ["NEEDS_FEASIBILITY", "WAITING_FEASIBILITY_RESULTS"].includes(status)));
    }
    const plan = s.active_plan != null ? s.plans[s.active_plan] : null;
    if (plan) {
      const ids = plan.factors;
      const rs = Object.fromEntries((s.run_sheet?.runs || []).map((r) => [r.run_id, r]));
      out.push(section(`실험표 — ${esc(plan.design_type)} ${plan.runs.length} run ${plan.validation.ok ? badge("ok", "Validator 통과") : badge("bad", "Validator 실패")} ${plan.locked_hash ? badge("", "잠김") : ""}`, `
        <p class="d7-muted">seed ${esc(plan.random_seed)} · 중심점 ${plan.center_points} · ${plan.validation.checks.map((c) => `${c.ok ? "✓" : "✗"} ${esc(c.check)}`).join(" · ")}</p>
        ${tbl(["순서", "run", ...ids.map((f) => esc(factorName(s, f))), "coded", "run sheet(바뀐 성분)"], [...plan.runs].sort((a, b) => a.run_order - b.run_order).map((r) =>
          `<tr><td>${r.run_order}</td><td class="mono">${esc(r.run_id)}</td>${ids.map((f) => `<td>${fx(r.actual[f])}</td>`).join("")}<td class="mono d7-small">${ids.map((f) => fx(r.coded[f], 2)).join(", ")}</td>
          <td class="d7-small">${(rs[r.run_id]?.ingredients || []).filter((i) => i.changed).map((i) => `${esc(i.material_id)} ${fx(i.pct_w_w, 2)}%${i.mg_per_unit != null ? ` (${fx(i.mg_per_unit, 2)} mg)` : ""}`).join(" · ")}</td></tr>`))}
        ${s.run_sheet ? `<p class="d7-muted">${esc(s.run_sheet.note)}${s.run_sheet.balance_material ? ` · balance ${esc(s.run_sheet.balance_material)}` : ""}</p>` : ""}
        ${decisions(s.evaluations.design)}`, status === "DOE_PLAN_REVIEW"));
    }
    if (Object.keys(s.results).length && status !== "WAITING_FOR_RESULTS") {
      const keys = Object.keys(Object.values(s.results)[0].values);
      out.push(section(`결과 ${Object.keys(s.results).length} run`, tbl(["run", "batch", "근거", "확인", ...keys.map(esc)], Object.values(s.results).map((r) =>
        `<tr><td class="mono">${esc(r.run_id)}</td><td class="d7-small">${esc(r.batch_id || "—")}</td><td class="d7-small">${esc(r.evidence_status)}</td><td>${r.human_verification_status === "CONFIRMED" ? badge("ok", "확인") : badge("warn", "미확인")}</td>${keys.map((k) => `<td>${fx(r.values[k])}</td>`).join("")}</tr>`))
        + decisions(s.evaluations.results), status === "RESULT_QUALITY_REVIEW"));
    }
    if (Object.keys(s.models).length) {
      out.push(section("모델 — 자동 계층적 선택(LOOCV 1-SE → 최소 항 → AICc)", tbl(["반응", "선택 식(coded)", "R² · 수정 · 예측", "적합결여 p", "상태"], Object.entries(s.models).map(([k, m]) =>
        `<tr><td><b>${esc(s.cqas[k]?.name || k)}</b></td><td class="mono d7-small">${esc(m.selected ? Object.entries(m.selected.coef).map(([t, b]) => `${b >= 0 && t !== "1" ? "+" : ""}${Number(b).toFixed(3)}${t === "1" ? "" : "·" + t}`).join(" ") : "—")}
          <div class="d7-muted">후보 ${m.candidates} · 적합 가능 ${m.estimable} · 1-SE ${m.one_se_set?.length ?? 0}</div></td>
          <td>${m.selected ? `${fx(m.selected.r2, 2)} · ${fx(m.selected.adj_r2, 2)} · <b>${fx(m.selected.pred_r2, 2)}</b>` : "—"}</td>
          <td>${m.selected?.lack_of_fit?.p == null ? "계산 불가" : fx(m.selected.lack_of_fit.p, 3)}</td>
          <td>${badge(/INADEQUATE/.test(m.status) ? "bad" : /FLAGS/.test(m.status) ? "warn" : "ok", m.status)}${(m.gate?.flags || []).map((x) => `<div class="d7-muted">${esc(x.rule_id)} ${esc(x.detail)}</div>`).join("")}</td></tr>`))
        + decisions(s.evaluations.model) + (s.flags_accepted ? `<p class="d7-small">플래그 수용: ${esc(s.flags_accepted.by)} — ${esc(s.flags_accepted.rationale)}</p>` : "")
        + `<div id="d7w-rsg" class="rsg-box"></div><div id="d7w-joint" class="d7w-surf"></div>`, true));
    }
    if (s.region) {
      const r = s.region;
      const fsd = s.factors;
      out.push(section(`영역 ${badge(r.status === "EMPTY" ? "bad" : r.status === "VERIFIED" ? "ok" : "warn", r.status)}`, `
        <div class="d7-kpis"><div><span>공동 통과확률 최대</span><b>${fx(r.setpoint_joint_p, 3)}</b><small>잠근 기준 p ≥ ${fx(r.policy.p_min, 2)}</small></div>
          <div><span>영역 비율(격자)</span><b>${fx(100 * r.joint_ok_fraction, 1)}%</b><small>평균만 통과 ${fx(100 * r.mean_ok_fraction, 1)}%</small></div>
          <div><span>격자</span><b>${r.grid_points_in_domain}</b><small>/${r.grid_points_total} (domain 안)</small></div>
          <div><span>setpoint</span><b class="d7-small">${Object.entries(r.setpoint_coded).map(([k, v]) => `${esc(k)} ${fx(v, 2)}`).join(" · ")}</b><small>coded</small></div></div>
        <p class="d7-muted">반응 간 독립 가정(INDEPENDENT_APPROXIMATION) · ${esc(r.policy.uncertainty)} · 기준은 결과 전에 잠금(criteria ${esc(String(r.criteria_hash || "").slice(0, 10))})</p>
        ${decisions(s.evaluations.region)}${r.proposal ? `<p class="d7-small">확인점 제안: ${r.proposal.map((p) => `${esc(p.role)} (${Object.keys(fsd).sort().map((f) => `${f} ${fx(p.actual[f])}`).join(", ")}, p=${fx(p.joint_p)})`).join(" · ")}</p>` : ""}`, true));
    }
    if (s.verification) {
      const v = s.verification;
      out.push(section(`확인 — 잠금 ${esc(String(v.plan.locked_hash).slice(0, 10))}`, `
        ${tbl(["역할", "점(실제값)", "예측 · 95% PI"], v.plan.points.map((p) => `<tr><td><b>${esc(p.role)}</b></td><td class="d7-small">${Object.entries(p.actual).map(([k, x]) => `${esc(k)}=${fx(x)}`).join(" · ")}</td>
          <td class="d7-small">${Object.entries(p.prediction_intervals).map(([k, pi]) => `${esc(k)} ${fx(pi.predicted, 2)} [${fx(pi.pi[0], 2)}, ${fx(pi.pi[1], 2)}]`).join("<br>")}</td></tr>`))}
        ${v.verdict ? `<p><b>판정</b> ${badge(v.verdict.all_pass ? "ok" : "bad", v.verdict.route)} ${v.verdict.points.map((p) => `${esc(p.role)}: ${esc(p.route)}`).join(" · ")}</p>` : ""}
        ${decisions(s.evaluations.verification)}`, step === 6));
    }
    out.push(section(`이력 — 승인 ${s.approvals.length} · 전이 ${s.timeline.length}`, `
      <ul class="d7-list">${s.approvals.map((a) => `<li>${badge("ok", POINT_KO[a.point] || a.point)} ${esc(a.actor_id)} · ${esc(a.at)}${a.rationale ? ` — ${esc(a.rationale)}` : ""}</li>`).join("") || "<li>아직 승인 없음</li>"}</ul>
      <ul class="d7-list">${s.timeline.map((t) => `<li><code>${esc(t.from)}</code> → <code>${esc(t.to)}</code> ${esc(t.reason)} ${t.rule ? `<span class="d7-muted">${esc(t.rule)}</span>` : ""}</li>`).join("")}</ul>
      ${s.labloop.history.length ? `<p class="d7-small">재검토: ${s.labloop.history.map((x) => `${esc(x.pattern_id || "")} ${esc(x.reason)} (시험 ${esc(x.chosen_tests.join(", ") || "없음")})`).join(" · ")}</p>` : ""}`));
    $("d7w-body").innerHTML = out.join("");
    if ($("d7w-rsg")) drawSurface().catch((e) => { if ($("d7w-rsg")) $("d7w-rsg").innerHTML = `<p class="d7-muted">곡면을 그리지 못했습니다: ${esc(e.message)}</p>`; });
  }

  // ── 곡면 — 반응 × 세 번째 요인 수준 3D 격자(surface3d.js) + 공동 통과확률 단면 ─────────────
  async function drawSurface(src, slice) {
    const s = cur.study;
    surf.source = src || surf.source || "selected";
    if (slice) surf.slice = slice;
    const box = $("d7w-rsg");
    if (!box) return;
    box.innerHTML = `<p class="d7-muted">반응 곡면 계산 중…</p>`;
    const d = await req(`/api/doe-v7/studies/${encodeURIComponent(s.study_id)}/surfaces?source=${surf.source}${surf.slice ? `&slice=${encodeURIComponent(surf.slice)}` : ""}`);
    if (!$("d7w-rsg")) return;
    await window.F1Surfaces.render($("d7w-rsg"), d, {
      sources: d.published_available, onSource: (x) => drawSurface(x).catch((e) => note(e.message, true)),
      onSlice: (x) => drawSurface(null, x).catch((e) => note(e.message, true)),
      title: `반응 곡면 — ${d.source === "published" ? "보고된 모형 항 구성으로 같은 원자료를 재적합" : "자동 선택 모형"}`,
    });
    const jb = $("d7w-joint");
    const allFit = Object.values(s.models).every((m) => m.selected);
    if (!jb || !allFit || Object.keys(s.models).length < 2 || Object.keys(s.factors).length < 2) return;   // 요인 1개면 2D 확률 지도 대신 곡선만
    const levels = Object.keys(s.factors).length === 3 ? [-1, 0, 1] : [0];
    const maps = [];
    for (const lv of levels) {
      const g = await req(`/api/doe-v7/studies/${encodeURIComponent(s.study_id)}/surface?x3=${lv}&steps=31`);
      if (g.joint) maps.push(heat(g, "joint", `공동 통과확률${g.x3_factor ? ` · ${factorName(s, g.x3_factor)} ${fx(g.x3_actual)}${s.factors[g.x3_factor].unit || ""}` : ""} (≥ ${fx(g.p_min, 2)} 테두리)`));
    }
    if ($("d7w-joint")) $("d7w-joint").innerHTML = maps.length ? `<h4>공동 통과확률 단면 — 모든 반응 규격을 동시에 만족할 확률(잠근 기준)</h4><div class="d7w-2d">${maps.join("")}</div>` : "";
  }

  function heat(d, kind, title) {
    const g = d[kind];
    const n = g.length;
    const cell = 200 / n;
    let lo = Infinity, hi = -Infinity;
    g.forEach((row, i) => row.forEach((v, j) => { if (d.domain[i][j] && v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
    if (kind === "joint") { lo = 0; hi = 1; }
    const rects = [];
    g.forEach((row, i) => row.forEach((v, j) => {
      if (!d.domain[i][j] || v == null) return;
      const t = hi > lo ? (v - lo) / (hi - lo) : 0.5;
      const shade = Math.round(235 - t * 190);
      const ok = kind === "joint" && v >= d.p_min;
      rects.push(`<rect x="${(j * cell).toFixed(2)}" y="${((n - 1 - i) * cell).toFixed(2)}" width="${(cell + 0.3).toFixed(2)}" height="${(cell + 0.3).toFixed(2)}" fill="rgb(${shade},${shade},${shade})"${ok ? ' stroke="var(--status-good)" stroke-width="0.6"' : ""}/>`);
    }));
    const a0 = d.axes[d.factors[0]], a1 = d.axes[d.factors[1]];
    return `<figure class="d7-map"><svg viewBox="0 0 200 200" role="img" aria-label="${esc(title)}">${rects.join("")}</svg>
      <figcaption>${esc(title)} · 세로 ${esc(a0.name)} ${fx(a0.actual[0])}–${fx(a0.actual[n - 1])} · 가로 ${esc(a1.name)} ${fx(a1.actual[0])}–${fx(a1.actual[n - 1])} · 범위 ${fx(lo, 2)}–${fx(hi, 2)} · 빈칸 = domain 밖(외삽)</figcaption></figure>`;
  }

  // ── 시작 ──────────────────────────────────────────────────────────────
  async function startFromCandidate(runId, candidateId) {
    skipRestore = true;
    if (window.F1Studio) window.F1Studio.showTab("v7");
    if (window.F1Doe7) window.F1Doe7.open();
    try { await create({ source: "candidate", run_id: runId, candidate_id: candidateId, candidate_version: 1 }); }
    catch (e) { note(e.message, true); }
  }

  function mount() {
    const box = $("d7-wizard");
    if (!box || box.dataset.ready) return;
    box.dataset.ready = "1";
    box.innerHTML = `<div class="d7w-bar"><button type="button" id="d7w-cbd">CBD 문헌 재현으로 시작</button>
        <button type="button" id="d7w-dsbtn">데이터셋으로 시작</button>
        <select id="d7w-list" aria-label="열린 study"></select>
        <span class="d7-muted">① 통과 후보 카드의 <b>v7 실험개발로 시작</b> · run 단위 실험 데이터가 있으면 <b>데이터셋으로 시작</b>.</span></div>
      <section id="d7w-ds" class="d7-card d7w-ds" hidden></section>
      <div id="d7w-msg" class="d7w-msg" role="status" aria-live="polite" hidden></div>
      <div id="d7w-main"></div>`;
    $("d7w-cbd").addEventListener("click", () => create({ source: "cbd_replay" }).catch((e) => note(e.message, true)));
    $("d7w-dsbtn").addEventListener("click", datasetPanel);
    $("d7w-list").addEventListener("change", (e) => { if (e.target.value) load(e.target.value).catch((x) => note(x.message, true)); });
    render();
    refreshList();
    let last = null;
    try { last = localStorage.getItem("f1:d7study"); } catch (e) { /* 무시 */ }
    if (last && !skipRestore) load(last).catch(() => { try { localStorage.removeItem("f1:d7study"); } catch (e) { /* 무시 */ } });
  }

  document.addEventListener("f1:tab", (e) => { if (e.detail?.tab === "v7") mount(); });
  document.addEventListener("DOMContentLoaded", () => { if ($("view-v7") && !$("view-v7").hidden) mount(); });
  window.F1Doe7Wizard = { startFromCandidate, mount, current: () => cur, act: doAction, fill };
})();
