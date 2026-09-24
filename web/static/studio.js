/* ② 개발 스튜디오 — ExperimentalDevelopmentGraph 화면 (명세 v6.1).

   화면의 주인공은 **지금 시스템이 연구자에게 묻는 것**(가운데 질문 카드)이다.
   - 질문 카드: 서버가 정한 현재 상태(`study.status`)에 맞는 입력 폼 + 행동 버튼.
     규칙이 막으면 그 이유(rule_id·메시지)가 카드 안에 바로 뜬다 — 다음에 무엇을 넣어야 하는지가 곧 답이다.
   - 대화 기록: 시스템 판정과 연구자 결정이 번갈아 쌓인다(최신이 위).
   - 오른쪽: 결과(모델·영역·확인점)와 규칙 판정·lineage — 대화의 흐름을 따라 채워지는 참고 화면.

   숫자·판정은 전부 서버(결정론 엔진·룰북)가 낸다. 이 파일은 입력을 모아 보내고 받은 것을 그릴 뿐이다.
   모든 `${}`는 esc()를 거친다(CSV·LLM·사용자 입력이 섞여 들어온다).
   가이드 시연의 "이 장면 입력 채우기"는 폼을 **채우기만** 한다 — 제출은 항상 연구자 버튼이다. */

(function () {
  let study = null;
  let busy = false;
  let lastError = null;
  let sideTab = "results";
  let slice = { fixed: null, index: 10 };

  const STATE_KO = {
    WAITING_REQUIRED_DATA: "진입 자료 대기", WAITING_CQA_APPROVAL: "CQA 승인 대기", WAITING_FMEA_APPROVAL: "FMEA 승인 대기",
    WAITING_FACTOR_DATA: "요인 자료 대기", RANGE_FINDING_RUNS: "범위 확인 run", WAITING_FACTOR_APPROVAL: "요인 승인 대기",
    WAITING_RSM_APPROVAL: "RSM 설계 승인 대기", WAITING_SCREENING_APPROVAL: "Screening 설계 승인 대기",
    RSM_EXECUTION: "RSM 결과 대기", SCREENING_EXECUTION: "Screening 결과 대기",
    WAITING_MODEL_APPROVAL: "모델 판단 대기", WAITING_REGION_APPROVAL: "잠정 영역 검토",
    WAITING_VERIFICATION_PLAN_APPROVAL: "확인계획 잠금 대기", VERIFICATION_EXECUTION: "확인배치 결과 대기",
    VERIFICATION_GATE: "확인 판정 보류", WAITING_FINAL_APPROVAL: "최종 승인 대기", COMPLETED: "VERIFIED 완료",
    WAITING_DIRECTIVE_APPROVAL: "진단 방향 결정", DESIGN_REPLAN: "설계 재계획", STRATEGY_REVIEW: "전략 검토",
    WAITING_HUMAN_TRIAGE: "사람 판단 필요", WAITING_AUDIT_REVIEW: "lineage 검토", INELIGIBLE: "진입 불가",
    CLOSED_SUPERSEDED: "후보 개정으로 종료", HANDOFF_CREATED: "Handoff 생성", ENTRY_READINESS: "진입 판정",
    CQA_DRAFTING: "CQA 초안", FMEA_DRAFTING: "FMEA 초안", FACTOR_READINESS: "요인 준비", DESIGN_SELECTION: "설계 선택",
    SCREENING_PLANNING: "Screening 계획", RSM_PLANNING: "RSM 계획", RSM_AUGMENTATION: "RSM 보강", SCREENING_AUGMENTATION: "Screening 보강",
    SCREENING_ANALYSIS: "Screening 분석", MODEL_VALIDATION: "모델 검증", REGION_COMPUTATION: "영역 계산",
    VERIFICATION_PLANNING: "확인계획 수립", DIAGNOSING: "진단", REFLECTING: "개정안 작성", WAITING_DISCRIMINATING_TESTS: "판별시험 대기",
  };
  const EFFECT_CLS = { BLOCK_STAGE: "critical", INVALIDATE: "critical", REQUEST_DATA: "serious", ROUTE: "warn",
                       AUGMENT: "warn", EXCLUDE_POINT: "warn", WARNING: "warn", PASS: "good" };
  const EFFECT_KO = { BLOCK_STAGE: "차단", INVALIDATE: "무효화", REQUEST_DATA: "자료 요청", ROUTE: "경로 전환",
                      AUGMENT: "보강", EXCLUDE_POINT: "점 제외", WARNING: "경고", PASS: "통과" };
  const ROLE_KO = { DOE_RESPONSE: "DoE 반응", MONITOR_ONLY: "모니터링", NOT_APPLICABLE: "해당없음" };
  // 확인배치 결과의 근거 등급. 자체 실측(확인 전)만 확인 판정에 쓸 수 있고, 문헌값은 참고 평가용이다.
  const EVIDENCE = ["MEASURED_UNCONFIRMED", "LITERATURE_DIRECT", "LITERATURE_DIGITIZED"];
  const EVIDENCE_KO = { MEASURED_UNCONFIRMED: "자체 실측 (확인 전)", LITERATURE_DIRECT: "문헌 표 수치",
                        LITERATURE_DIGITIZED: "문헌 그림 디지타이징" };
  const OPS = ["", "LE", "GE", "BETWEEN", "TARGET_TOL", "PASS_FAIL"];
  const DISP = { DOE_CANDIDATE: "DoE 요인", FIXED: "고정 관리", REQUEST_DATA: "자료 요청", EXCLUDED: "제외" };

  const el = (id) => document.getElementById(id);
  const num = (v, d = 3) => (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) ? "—"
    : Number(v).toLocaleString("ko-KR", { maximumFractionDigits: d });
  const pct = (v, d = 1) => (v === null || v === undefined) ? "—" : `${(Number(v) * 100).toFixed(d)}%`;
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());

  // ── 서버 호출 ──────────────────────────────────────────────────────────
  async function req(method, path, body, headers = {}) {
    const res = await fetch(api(path), {
      method, headers: { "Content-Type": "application/json", "Actor-ID": "researcher", ...headers },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail || {};
      const err = new Error(typeof d === "string" ? d : (d.message || `요청 실패 (${res.status})`));
      err.verdicts = d.verdicts || [];
      err.status = res.status;
      throw err;
    }
    return data;
  }

  async function act(action, payload = {}) {
    if (!study || busy) return false;
    setBusy(true);
    lastError = null;
    const before = study.status;
    try {
      const next = await req("POST", `/api/development-studies/${study.study_id}/actions/${action}`, { payload },
        { "Idempotency-Key": uid(), "Expected-State-Version": String(study.state_version) });
      render(next);
      if (next.status !== before) bringAskIntoView();
      return true;
    } catch (e) {
      lastError = { message: e.message, verdicts: e.verdicts || [] };
      if (e.status === 409 && /먼저 바뀌었/.test(e.message)) await load(study.study_id);
      else { renderAsk(); renderGuide(); }
      bringAskIntoView();
      return false;
    } finally {
      setBusy(false);
    }
  }

  // 상태가 바뀌면 질문 카드가 화면 밖에 있을 수 있다(특히 휴대폰) — 카드 머리로 데려온다.
  function bringAskIntoView() {
    const a = el("studio-ask");
    if (!a) return;
    const r = a.getBoundingClientRect();
    if (r.top < 60 || r.top > window.innerHeight * 0.6) {
      const y = window.scrollY + r.top - 76;
      window.scrollTo({ top: Math.max(0, y), behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  }

  // 버튼 → 입력 수집 → 서버. 가이드 시연도 이 함수를 그대로 쓴다(사람이 누른 것과 같은 경로).
  async function doAction(btn) {
    if (!btn || busy) return false;
    const root = el("studio-ask");
    const collect = COLLECT[btn.dataset.act];
    let payload = {};
    try { payload = collect ? collect(root, btn) : {}; }
    catch (e) { lastError = { message: e.message }; renderAsk(); renderGuide(); return false; }
    if (payload === null) return false;
    const label = btn.textContent;
    btn.classList.add("working");
    btn.textContent = "처리 중…";
    const ok = await act(btn.dataset.act, payload);
    if (document.contains(btn)) { btn.textContent = label; btn.classList.remove("working"); }
    return ok;
  }

  async function load(id) {
    const s = await req("GET", `/api/development-studies/${id}`);
    render(s);
  }

  function setBusy(on) {
    busy = on;
    document.querySelectorAll("#studio-ask button").forEach((b) => { b.disabled = on; });
    const ask = el("studio-ask");
    if (ask) ask.classList.toggle("busy", on);
  }

  async function startDemo(opts = {}) {
    guide.on = true;
    guide.auto = false;
    guide.blockShown = false;
    setBusy(true);
    try {
      const s = await req("POST", "/api/development-studies/demo/lornoxicam", null, { "Idempotency-Key": uid() });
      showTab("studio");
      lastError = null;
      render(s);
      refreshList();
      bringAskIntoView();
      if (opts.auto) autoPlay();
    } catch (e) {
      notice(`데모 study를 만들지 못했습니다: ${e.message}`, "error");
    } finally {
      setBusy(false);
    }
  }

  async function startFromCandidate(runIdValue, candidateId) {
    try {
      showTab("studio");
      el("studio-ask") && (el("studio-ask").innerHTML = `<div class="ask-wait">Handoff를 만드는 중…</div>`);
      const s = await req("POST", `/api/candidates/${encodeURIComponent(candidateId)}/development-studies`,
        { run_id: runIdValue, candidate_version: 1, mode: "demo" }, { "Idempotency-Key": uid() });
      render(s);
      refreshList();
    } catch (e) {
      notice(`개발 study를 만들지 못했습니다: ${e.message}`, "error");
    }
  }

  async function refreshList() {
    try {
      const { studies } = await req("GET", "/api/development-studies");
      const sel = el("studio-list");
      sel.innerHTML = `<option value="">최근 study…</option>` + studies.map((s) =>
        `<option value="${esc(s.study_id)}">${esc(s.title || s.candidate_ref)} · ${esc(STATE_KO[s.status] || s.status)}</option>`).join("");
      if (study) sel.value = study.study_id;
    } catch (e) { /* 목록은 보조 기능 — 실패해도 화면은 돈다 */ }
  }

  // ── 탭 ─────────────────────────────────────────────────────────────────
  function showTab(which) {
    const studio = which === "studio";
    el("view-discovery").hidden = studio;
    el("view-studio").hidden = !studio;
    el("tab-discovery").classList.toggle("on", !studio);
    el("tab-studio").classList.toggle("on", studio);
    el("tab-discovery").setAttribute("aria-selected", String(!studio));
    el("tab-studio").setAttribute("aria-selected", String(studio));
    try { localStorage.setItem("f1:tab", which); } catch (e) { /* 무시 */ }
    if (studio) refreshList();
  }

  // ── 전체 그리기 ────────────────────────────────────────────────────────
  function render(s) {
    study = s;
    try { localStorage.setItem("f1:study", s.study_id); } catch (e) { /* 무시 */ }
    el("studio-empty").hidden = true;
    el("studio-grid").hidden = false;
    const assumptions = (s.assumptions || []).length
      ? `<span class="as-badge" title="${esc(s.assumptions.join("\n"))}">가정 ${s.assumptions.length}건</span>` : "";
    el("studio-id").innerHTML = `
      <b>${esc(s.title || s.candidate_ref)}</b>
      <span><code>${esc(s.candidate_ref)}</code> · Handoff <code>${esc(s.handoff.handoff_id)}</code> ·
        study <code>${esc(s.study_id)}</code> · v${esc(s.state_version)} ${assumptions}</span>`;
    renderPhases();
    renderAsk();
    renderGuide();
    renderLog();
    renderSide();
  }

  function renderPhases() {
    const s = study;
    const order = s.phases.map((p) => p.key);
    const cur = order.indexOf(s.phase);
    el("studio-phases").innerHTML = s.phases.map((p, i) => {
      const cls = s.phase === p.key ? "on" : (cur >= 0 && i < cur) || s.status === "COMPLETED" ? "done" : "";
      return `<li class="${cls}"><span class="ph-dot"></span>${esc(p.label)}</li>`;
    }).join("") + (s.phase === "side" ? `<li class="on side"><span class="ph-dot"></span>${esc(STATE_KO[s.status] || s.status)}</li>` : "");
    el("studio-mode").innerHTML = s.mode === "demo"
      ? `<b>demo · sandbox</b><span>DRAFT 규칙 ${esc(s.enforced_rule_count)}개 집행. 결과는 운영으로 승격되지 않습니다.</span>`
      : `<b>production</b><span>APPROVED 규칙만 집행 — 현재 ${esc(s.enforced_rule_count)}개. 전 규칙이 DRAFT라 아무것도 막지 않는 것이 정상입니다.</span>`;
  }

  function renderLog() {
    const msgs = (study.messages || []).slice().reverse();
    el("studio-log").innerHTML = msgs.map((m) => `
      <li class="lg ${esc(m.who)} ${esc(m.kind || "")}">
        <span class="lg-who">${m.who === "system" ? "시스템" : "연구자"}</span>
        <span class="lg-text">${esc(m.text)}</span>
        <span class="lg-meta">${esc(STATE_KO[m.state] || m.state || "")}</span>
      </li>`).join("");
  }

  // ── 질문 카드 ──────────────────────────────────────────────────────────
  function subjectVerdicts(key, subject) {
    const ev = (study.evaluations || {})[key];
    if (!ev) return [];
    return ev.verdicts.filter((v) => (subject === undefined || v.subject === subject) && v.enforced &&
      (v.status === "FIRES" || v.status === "MISSING") && v.effect);
  }

  function chips(vs) {
    return vs.map((v) => `<button type="button" class="vchip ${EFFECT_CLS[v.effect] || ""}${v.overridden ? " overridden" : ""}" data-rule="${esc(v.rule_id)}"
      title="${esc(v.message)}">${esc(v.rule_id)} · ${esc(EFFECT_KO[v.effect] || v.effect)}</button>`).join("");
  }

  function verdictList(vs, title) {
    if (!vs.length) return "";
    return `<div class="vlist"><div class="vlist-h">${esc(title)}</div>${vs.map((v) => `
      <div class="vrow ${EFFECT_CLS[v.effect] || ""}">
        <button type="button" class="vchip ${EFFECT_CLS[v.effect] || ""}" data-rule="${esc(v.rule_id)}">${esc(v.rule_id)}</button>
        <span>${esc(v.message)}${v.subject && !/전체|계획|영역|handoff|요인 구성/.test(v.subject) ? ` <em>(${esc(v.subject)})</em>` : ""}
        ${v.status === "MISSING" ? `<em class="miss">값이 없어 ${esc(v.effect === "REQUEST_DATA" ? "자료 요청" : "차단")}</em>` : ""}</span>
      </div>`).join("")}</div>`;
  }

  function renderAsk() {
    const s = study;
    const p = s.prompt || {};
    const renderer = ASK[s.status] || ASK._default;
    const err = lastError ? `
      <div class="ask-error" role="alert"><b>${esc(lastError.message)}</b>
        ${verdictList(lastError.verdicts || [], "막은 규칙")}</div>` : "";
    const demo = s.script && FILL[s.status] ? `<button type="button" class="ghost fill" id="ask-fill">이 장면 입력 채우기</button>` : "";
    el("studio-ask").innerHTML = `
      <header class="ask-head">
        <span class="ask-state">${esc(STATE_KO[s.status] || s.status)}</span>
        <h2>${esc(p.title || s.status)}</h2>
        <p>${esc(p.ask || "")}</p>
        ${demo}
      </header>
      ${err}
      <div class="ask-body">${renderer(s)}</div>`;
    wire();
  }

  function wire() {
    const root = el("studio-ask");
    root.querySelectorAll("[data-rule]").forEach((b) => { b.onclick = () => showRule(b.dataset.rule); });
    root.querySelectorAll("[data-act]").forEach((b) => { b.onclick = () => doAction(b); });
    const fill = el("ask-fill");
    if (fill) fill.onclick = () => FILL[study.status](root, study.script);
    (WIRE[study.status] || (() => {}))(root);
    el("studio-side-body").querySelectorAll("[data-rule]").forEach((b) => { b.onclick = () => showRule(b.dataset.rule); });
  }

  const reasonBox = (id = "ask-reason", ph = "사유 (기록에 남습니다)") =>
    `<label class="reason"><span>사유</span><input id="${id}" type="text" placeholder="${esc(ph)}"></label>`;
  const val = (root, sel) => { const x = root.querySelector(sel); return x ? x.value.trim() : ""; };
  const numOrNull = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

  // 상태별 질문 카드 본문 -------------------------------------------------------
  const ASK = {
    _default: (s) => {
      const vs = subjectVerdicts("verification_gate").concat(subjectVerdicts("region"));
      return `<div class="ask-wait">${esc(s.prompt.ask || "시스템이 다음 단계를 계산했습니다.")}</div>${verdictList(vs, "규칙 판정")}`;
    },

    WAITING_REQUIRED_DATA: (s) => {
      const reqs = (s.readiness || {}).requests || [];
      const fixed = s.handoff.fixed_parameters.filter((f) => f.status === "MISSING");
      const grades = s.handoff.ingredients.filter((i) => i.is_critical && !i.grade);
      return `${verdictList(reqs, "진입 Readiness 규칙이 요청한 것")}
        <div class="form">
          ${!s.handoff.batch_scale ? `<label><span>배치 규모</span><input id="rd-scale" placeholder="예: 1,000정"></label>` : ""}
          ${!s.handoff.equipment_id ? `<label><span>설비 ID</span><input id="rd-eq" placeholder="예: EQ_LX_MIXER;EQ_LX_PRESS"></label>` : ""}
          ${fixed.map((f) => `
            <div class="fx-row" data-fixed="${esc(f.name)}">
              <span class="fx-name">${esc(f.name)} <small>${esc(f.unit || "")}</small></span>
              <input class="fx-val" type="number" step="any" placeholder="값">
              <label class="chk"><input class="fx-unknown" type="checkbox"> UNKNOWN으로 기록</label>
              <input class="fx-reason" placeholder="근거·사유">
            </div>`).join("")}
          ${grades.map((g) => `<label><span>${esc(g.name)} 등급</span><input class="rd-grade" data-name="${esc(g.name)}" placeholder="예: USP"></label>`).join("")}
        </div>
        <div class="ask-actions"><button class="primary" data-act="required_data">자료 제출 → 다시 판정</button></div>`;
    },

    WAITING_CQA_APPROVAL: (s) => {
      const rows = Object.values(s.cqas).map((c) => {
        const vs = subjectVerdicts("cqa", c.cqa_id);
        return `<tr data-cqa="${esc(c.cqa_id)}" class="${vs.some((v) => v.effect === "BLOCK_STAGE" || v.effect === "REQUEST_DATA") ? "blocked" : ""}">
          <td><b>${esc(c.name)}</b><small class="sub">${esc(c.cqa_id)} · ${esc(c.requirement)}${c.assumption ? " · 가정" : ""}</small>
            <div class="rowchips">${chips(vs)}</div></td>
          <td data-label="역할"><select data-f="analysis_role">${Object.entries(ROLE_KO).map(([k, v]) => `<option value="${k}" ${c.analysis_role === k ? "selected" : ""}>${v}</option>`).join("")}</select></td>
          <td data-label="판정"><select data-f="acceptance_operator">${OPS.map((o) => `<option value="${o}" ${(c.acceptance_operator || "") === o ? "selected" : ""}>${o || "—"}</option>`).join("")}</select></td>
          <td data-label="하한"><input data-f="lower" type="number" step="any" value="${esc(c.lower ?? "")}"></td>
          <td data-label="상한"><input data-f="upper" type="number" step="any" value="${esc(c.upper ?? "")}"></td>
          <td data-label="단위"><input data-f="unit" value="${esc(c.unit ?? "")}"></td>
          <td data-label="δ (실질 효과)"><input data-f="practical_effect_threshold" type="number" step="any" value="${esc(c.practical_effect_threshold ?? "")}" placeholder="δ" title="실질 효과 기준 δ — 비우면 screening 판정이 INCONCLUSIVE(CR007)"></td>
          <td data-label="요약값"><input data-f="summary_definition" value="${esc(c.summary_definition ?? "")}" placeholder="요약값"></td>
          <td data-label="시험법"><input data-f="test_method_id" value="${esc(c.test_method_id ?? "")}"></td>
          <td data-label="규격 근거"><select data-f="criterion_source">${["PHARMACOPEIA", "PROJECT_TARGET", "REGULATORY", "OTHER"].map((o) => `<option ${c.criterion_source === o ? "selected" : ""}>${o}</option>`).join("")}</select></td>
        </tr>`;
      }).join("");
      const all = subjectVerdicts("cqa", "CQA 전체");
      return `<div class="table-wrap"><table class="edit cqa-table">
          <thead><tr><th>CQA</th><th>역할</th><th>판정</th><th>하한</th><th>상한</th><th>단위</th><th title="실질 효과 기준">δ</th><th>요약값</th><th>시험법</th><th>규격 근거</th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        ${verdictList(all, "계약 전체")}
        ${reasonBox()}
        <div class="ask-actions">
          <button data-act="cqa_edit">변경 저장 → 다시 판정</button>
          <button class="primary" data-act="cqa_approve">CQA 계약 승인</button>
          <button class="ghost" data-act="cqa_reject">초안으로 되돌리기</button>
        </div>`;
    },

    WAITING_FMEA_APPROVAL: (s) => {
      const by = s.fmea.hypotheses_generated_by || "";
      const rows = s.fmea.rows.filter((r) => !r.deleted).map((r) => {
        const vs = subjectVerdicts("fmea", r.row_id);
        const cq = r.cqa_effect.map((c) => (s.cqas[c] || {}).name || c).join(", ");
        return `<tr data-row="${esc(r.row_id)}" class="${r.evidence_status === "LLM_HYPOTHESIS" ? "hyp" : ""}">
          <td><b>${esc(r.row_id)}</b>${r.evidence_status === "LLM_HYPOTHESIS" ? `<span class="hyp-tag">LLM 가설</span>` : ""}
            <div class="rowchips">${chips(vs)}</div></td>
          <td data-label="원인 → 실패">${esc(r.cause)} → <b>${esc(r.failure_mode)}</b><small class="sub">${esc(r.local_effect)} → ${esc(cq)}</small>
            ${r.rationale ? `<small class="sub">근거: ${esc(r.rationale)}</small>` : ""}</td>
          <td class="c" data-label="S (심각도)">${esc(r.severity ?? "—")}</td>
          <td data-label="O (발생도)"><input data-f="occurrence" type="number" min="1" max="5" value="${esc(r.occurrence ?? "")}" placeholder="UNKNOWN"></td>
          <td data-label="O 근거"><input data-f="occurrence_evidence" value="${esc(r.occurrence_evidence ?? "")}" placeholder="O 근거"></td>
          <td class="c" data-label="D (검출)" title="${esc(r.detect_note || "")}">${esc(r.detectability ?? "—")}</td>
          <td class="c" data-label="RPN">${r.rpn === null || r.rpn === undefined ? `<span class="muted">미계산</span>` : esc(r.rpn)}</td>
          <td data-label="처리 방향"><select data-f="disposition">${Object.entries(DISP).map(([k, v]) => `<option value="${k}" ${r.disposition === k ? "selected" : ""}>${v}</option>`).join("")}</select></td>
          <td data-label="대체 관리"><input data-f="alternative_control" value="${esc(r.alternative_control ?? "")}" placeholder="대체 관리"></td>
        </tr>`;
      }).join("");
      return `<p class="hint">${by === "llm" ? "LLM 누락 가설 행이 포함돼 있습니다(태그 LLM_HYPOTHESIS)" : "LLM 응답이 없어 누락 가설 없이 seed 행만 있습니다"}.
          O를 비워 두면 UNKNOWN이고 그 행의 RPN은 계산하지 않습니다. 근거 없이 O를 넣으면 EXPERT_ASSUMPTION으로 표시됩니다.</p>
        <div class="table-wrap"><table class="edit fmea-table">
          <thead><tr><th>행</th><th>원인 → 실패모드 → CQA</th><th>S</th><th>O</th><th>O 근거</th><th>D</th><th>RPN</th><th>처리 방향</th><th>대체 관리</th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        ${reasonBox()}
        <div class="ask-actions">
          <button data-act="fmea_edit">변경 저장 → 다시 판정</button>
          <button class="primary" data-act="fmea_approve">FMEA 승인</button>
          <button class="ghost" data-act="fmea_reject">초안 다시</button>
        </div>`;
    },

    WAITING_FACTOR_DATA: (s) => factorForm(s, false),
    RANGE_FINDING_RUNS: (s) => factorForm(s, false),
    WAITING_FACTOR_APPROVAL: (s) => factorForm(s, true),
    STRATEGY_REVIEW: (s) => `${factorForm(s, false)}
      <div class="ask-actions"><button class="ghost" data-act="replan" data-target="CANDIDATE_REVISION">후보 개정 요청 (child candidate)</button></div>`,

    WAITING_RSM_APPROVAL: (s) => planView(s),
    WAITING_SCREENING_APPROVAL: (s) => planView(s),

    RSM_EXECUTION: (s) => resultsForm(s),
    SCREENING_EXECUTION: (s) => resultsForm(s),

    WAITING_MODEL_APPROVAL: (s) => {
      const rows = Object.entries(s.models).map(([cid, ms]) => {
        const m = ms[ms.length - 1];
        const f = m.fit_stats || {};
        const vs = subjectVerdicts("models", cid);
        const flagged = m.validation_status === "FLAGGED";
        const syms = Object.keys((s.plans.find((p) => p.doe_plan_id === s.active_plan) || {}).symbols || {});
        const terms = (m.intended_terms || []).filter((t) => t !== "1");
        return `<div class="model-card ${flagged ? "flagged" : ""}" data-cqa="${esc(cid)}">
          <div class="mc-head"><b>${esc(s.cqas[cid].name)}</b><span class="mstat ${esc(m.validation_status)}">${esc(m.validation_status)}</span></div>
          <div class="mc-stats">R² ${num(f.r2)} · 조정 R² ${num(f.adj_r2)} · <b>예측 R² ${num(f.pred_r2)}</b> · 잔차 df ${esc(f.df_resid)} · pure error df ${esc((f.pure_error || {}).df)}
            ${(m.influence_flags || []).length ? ` · 영향점 run ${m.influence_flags.map((x) => esc(x.source_row)).join(", ")} (삭제 안 함)` : ""}</div>
          <div class="rowchips">${chips(vs)}</div>
          ${flagged ? `
          <div class="mc-decide">
            <div class="terms">${syms.concat(terms.filter((t) => !syms.includes(t))).map((t) => `
              <label class="chk"><input type="checkbox" class="term" value="${esc(t)}" ${syms.includes(t) ? "checked" : ""}> ${esc(t)}</label>`).join("")}</div>
            <button data-act="model_reduce" data-cqa="${esc(cid)}">선택한 항으로 축소 (계층성 검사)</button>
            <input class="accept-reason" placeholder="flag를 알고 수용하는 사유">
            <button class="ghost" data-act="model_accept" data-cqa="${esc(cid)}">flag와 함께 수용</button>
          </div>` : ""}
        </div>`;
      }).join("");
      return `<p class="hint">항 축소는 연구자 승인으로만 합니다(자동 stepwise 없음). 축소 뒤 같은 자료로 계산한 예측 R²는 선택 과정을 반영한 독립 추정이 아닙니다 — 선택 이력이 보존됩니다.</p>
        ${rows}
        ${reasonBox()}
        <div class="ask-actions">
          <button class="primary" data-act="model_approve">판단 완료 → 다시 검증</button>
          <button class="ghost" data-act="model_augment">보강 실험 요청</button>
        </div>`;
    },

    WAITING_REGION_APPROVAL: (s) => {
      const r = s.region.summary;
      const facs = regionFactors(s);
      return `${regionStats(s)}
        <div class="region-inline" id="region-inline"></div>
        <div class="form">
          <label><span>허용 변동 (robustness, coded)</span><input id="rg-delta" type="number" step="0.05" value="0.2"></label>
          <label class="chk"><input id="rg-challenge" type="checkbox"> CHALLENGE 음성대조 점 포함 (선택)</label>
          <fieldset class="ref"><legend>계획 전부터 있던 배치 (REFERENCE_EXISTING, 선택 — 참고 평가만)</legend>
            ${facs.map((f) => `<label><span>${esc(f.name)}</span><input class="ref-v" data-fid="${esc(f.factor_id)}" type="number" step="any" placeholder="${esc(f.low.value)}–${esc(f.high.value)}"></label>`).join("")}
          </fieldset>
        </div>
        ${reasonBox()}
        <div class="ask-actions">
          <button class="primary" data-act="region_approve">PROVISIONAL 승인 → 확인계획</button>
          <button class="ghost" data-act="region_revise">다시 계산</button>
        </div>`;
    },

    WAITING_VERIFICATION_PLAN_APPROVAL: (s) => `${vplanTable(s)}
      ${verdictList(subjectVerdicts("verification_plan"), "확인계획 규칙")}
      ${reasonBox()}
      <div class="ask-actions">
        <button class="primary" data-act="vplan_lock">확인계획 잠금 (첫 결과 전)</button>
        <button class="ghost" data-act="vplan_reject">다시 제안</button>
      </div>`,

    VERIFICATION_EXECUTION: (s) => verificationForm(s),
    VERIFICATION_GATE: (s) => verificationForm(s),

    WAITING_FINAL_APPROVAL: (s) => {
      const ds = s.region.design_space;
      return `${gateTable(s)}
        <div class="form">
          <label class="wide"><span>검증 주장의 한계 (관리되지 않은 변수: ${esc(ds.scope.unmanaged.join(", ") || "없음")})</span>
            <textarea id="fn-lim" rows="2">${esc(ds.scope.limitations || "")}</textarea></label>
        </div>
        ${reasonBox()}
        <div class="ask-actions">
          <button class="primary" data-act="finalize">VERIFIED로 최종 승인</button>
          <button class="ghost" data-act="final_more">확인배치 추가</button>
        </div>`;
    },

    WAITING_DIRECTIVE_APPROVAL: (s) => {
      const d = s.diagnosis || {};
      return `<div class="diag">
          <p>실패 신호: <b>${esc((d.trigger || {}).reason_code)}</b> — ${esc((d.trigger || {}).message || "")}</p>
          ${d.generated_by === "llm" ? `<p class="hint">LLM 가설 · 태그 LLM_HYPOTHESIS (원인 확정에는 판별시험 데이터 필요)</p>` : ""}
          <ol>${(d.hypotheses || []).map((h) => `<li><b>${esc(h.statement)}</b><small class="sub">판별시험 ${esc(h.distinguishing_test)} · 예상 패턴: ${esc(h.expected_pattern)}</small></li>`).join("")}</ol>
        </div>
        ${(d.hypotheses || []).length ? "" : `<p class="hint">LLM 응답이 없어 가설과 방향 제안이 없습니다. 실패 신호를 보고 직접 방향을 고르세요.</p>`}
        <div class="form"><label><span>다음 방향</span><select id="dg-dir">
          <option value="">방향 선택…</option>
          ${[["DOE_AUGMENT", "모델 보강 실험"], ["FACTOR_RANGE_REVISION", "요인·범위 재설정"], ["METHOD_PROCESS_CONTROL", "시험법·공정 편차 개선"], ["CANDIDATE_REVISION", "후보 개정 (child candidate)"]].map(([x, t]) => `<option value="${x}" ${d.directive === x ? "selected" : ""}>${t}</option>`).join("")}
        </select></label></div>
        ${reasonBox()}
        <div class="ask-actions"><button class="primary" data-act="directive_approve">이 방향 승인</button>
          <button class="ghost" data-act="directive_reject">다시 진단</button></div>`;
    },

    DESIGN_REPLAN: (s) => `${verdictList(subjectVerdicts("planning"), "설계를 막은 규칙")}
      <div class="form"><label><span>설계 재선택</span><select id="rp-type">
        <option value="">룰북 권고</option><option>BOX_BEHNKEN</option><option>FACE_CENTERED_CCD</option><option>CCD</option>
        <option>FRACTIONAL_FACTORIAL</option><option>PLACKETT_BURMAN</option></select></label>
        <label class="chk"><input id="rp-prior" type="checkbox"> 사전근거 승인 (3요인 이하 RSM 직행)</label></div>
      ${reasonBox()}
      <div class="ask-actions"><button class="primary" data-act="replan" data-target="DESIGN_SELECTION">설계 선택으로</button>
        <button class="ghost" data-act="replan" data-target="FACTOR_READINESS">요인 범위로</button></div>`,

    WAITING_HUMAN_TRIAGE: (s) => `<p>복귀 지점: <b>${esc(s.return_point || "-")}</b></p>${reasonBox()}
      <div class="ask-actions"><button class="primary" data-act="triage_resolve">확인 — 복귀 지점에서 재개</button></div>`,
    WAITING_AUDIT_REVIEW: (s) => ASK.WAITING_HUMAN_TRIAGE(s),

    COMPLETED: (s) => finalCard(s),
    INELIGIBLE: (s) => verdictList(((s.readiness || {}).blocking) || [], "진입을 막은 규칙"),
    CLOSED_SUPERSEDED: () => `<p>child candidate 요청이 상류(① 후보 탐색)로 전달되었습니다. 기존 study는 종료되고, 새 후보는 새 Handoff로 시작합니다.</p>`,
  };

  function factorForm(s, approving) {
    const facs = Object.values(s.factors);
    const cards = facs.map((f) => {
      const vs = subjectVerdicts("factors", f.factor_id);
      return `<div class="factor" data-src="${esc(f.source_factor)}">
        <div class="fc-head"><b>${esc(f.name)}</b> <code>${esc(f.symbol)}</code> <small>${esc(f.unit || "")}${f.ingredient ? ` · ${esc(f.ingredient)}` : ""}</small>
          <select data-f="disposition">${["DOE_CANDIDATE", "FIXED", "EXCLUDED"].map((k) => `<option value="${k}" ${f.disposition === k ? "selected" : ""}>${DISP[k]}</option>`).join("")}</select></div>
        <div class="fc-range">
          <label><span>low</span><input data-f="low" type="number" step="any" value="${esc(f.low.value ?? "")}"></label>
          <div class="fc-center"><span>center (Handoff)</span><b>${esc(f.center.value ?? "—")}</b></div>
          <label><span>high</span><input data-f="high" type="number" step="any" value="${esc(f.high.value ?? "")}"></label>
        </div>
        <div class="fc-src">
          <label><span>경계 출처</span><input data-f="source_ref" value="${esc(f.low.source_ref ?? "")}" placeholder="예: 선행 연구 Table 1"></label>
          <label><span>근거 등급</span><select data-f="evidence_status">${["LITERATURE_DIRECT", "LITERATURE_DIGITIZED", "MEASURED_CONFIRMED", "EXPERT_ASSUMPTION"].map((e) => `<option ${f.low.evidence_status === e ? "selected" : ""}>${e}</option>`).join("")}</select></label>
          <label><span>끝점 제조 가능성 근거</span><input data-f="manufacturability_evidence" value="${esc(f.manufacturability_evidence ?? "")}" placeholder="없으면 범위 확인 run 제안"></label>
        </div>
        <ul class="fc-notes">${(f.proposal_notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
        <div class="rowchips">${chips(vs)}</div>
      </div>`;
    }).join("");
    const approval = approving ? `
      <div class="form approval">
        <label class="chk"><input id="fa-prior" type="checkbox"> 승인된 사전근거가 있다 (3요인 이하면 RSM 직행 — DS007)</label>
        <label class="chk"><input id="fa-corner" type="checkbox" checked> 극단 꼭짓점 조합이 위험하다 (Box–Behnken 권고 — DS008)</label>
        <label><span>설계 (비우면 룰북 권고)</span><select id="fa-type"><option value="">룰북 권고</option>
          <option>BOX_BEHNKEN</option><option>FACE_CENTERED_CCD</option><option>CCD</option><option>FRACTIONAL_FACTORIAL</option><option>PLACKETT_BURMAN</option></select></label>
      </div>` : "";
    const whole = subjectVerdicts("factors").filter((v) => !facs.some((f) => f.factor_id === v.subject));
    return `${verdictList(whole, "요인 구성 · 고정 변수")}<div class="factors">${cards}</div>${approval}
      ${reasonBox()}
      <div class="ask-actions">
        <button ${approving ? "" : 'class="primary"'} data-act="factor_data">범위·근거 제출 → 다시 판정</button>
        ${approving ? `<button class="primary" data-act="factor_approve">요인·수준값 승인</button>` : ""}
      </div>`;
  }

  function planView(s) {
    const plan = s.plans.find((p) => p.doe_plan_id === s.active_plan);
    if (!plan) return "";
    const d = plan.diagnostics || {};
    const syms = plan.symbols || {};
    const names = Object.fromEntries(Object.values(s.factors).map((f) => [f.factor_id, f.name]));
    const head = Object.entries(syms).map(([sym, fid]) => `<th>${esc(names[fid] || fid)} <code>${esc(sym)}</code></th>`).join("");
    const rows = plan.runs.map((r) => `<tr class="${r.center ? "center" : ""}"><td>${esc(r.doe_run_id)}</td><td class="c">${esc(r.std_order)}</td>
      ${Object.entries(syms).map(([sym, fid]) => `<td>${num(r.actual[fid], 3)} <small>(${num(r.coded[sym], 2)})</small></td>`).join("")}
      <td>${r.why ? esc(r.why) : r.center ? "중심점" : ""}</td></tr>`).join("");
    const alias = (plan.alias_structure.pairs || []).map((p) => p.join(" = ")).join(", ");
    return `<div class="plan-sum">
        <b>${esc(plan.design_type)}</b>${plan.design_type !== plan.recommended ? ` <span class="warn-tag">권고 ${esc(plan.recommended)}와 다름</span>` : ""}
        · ${esc(d.n_runs)} run · 중심점 ${esc(d.n_center_points)} · 모형 항 ${esc(d.n_terms)} (rank ${esc(d.matrix_rank)}) · 잔차 df ${esc(d.residual_df)}
        · seed ${esc(plan.random_seed)}${d.balance_min_pct !== null && d.balance_min_pct !== undefined ? ` · balance 최소 ${num(d.balance_min_pct, 2)}%` : ""}
        ${alias ? `<div class="hint">alias: ${esc(alias)}</div>` : ""}
      </div>
      ${verdictList(subjectVerdicts("planning"), "설계 검증 규칙")}
      <div class="table-wrap"><table class="matrix"><thead><tr><th>run</th><th>std</th>${head}<th></th></tr></thead><tbody>${rows}</tbody></table></div>
      ${reasonBox("ask-reason", "권고와 다른 설계면 사유 필수 (AA007)")}
      <div class="ask-actions">
        <button class="primary" data-act="plan_approve">설계 승인 → 실행</button>
        <select id="pl-type"><option value="">다른 설계로 다시…</option><option>BOX_BEHNKEN</option><option>FACE_CENTERED_CCD</option><option>CCD</option><option>FRACTIONAL_FACTORIAL</option><option>PLACKETT_BURMAN</option></select>
        <button class="ghost" data-act="plan_reject">반려 · 다시 계획</button>
      </div>`;
  }

  function targetsOf(s) {
    const plan = s.plans.find((p) => p.doe_plan_id === s.active_plan) || {};
    const out = [["", "무시"]];
    (plan.factor_ids || []).forEach((fid) => out.push([fid, `요인 · ${s.factors[fid].name}`]));
    Object.values(s.cqas).filter((c) => c.analysis_role !== "NOT_APPLICABLE").forEach((c) => out.push([c.cqa_id, `CQA · ${c.name}`]));
    return out;
  }

  function guess(col, s) {
    const lc = col.toLowerCase();
    const map = [["F_filler_ratio", ["ratio", "mcc", "filler"]], ["F_blend_time", ["mix", "blend"]],
      ["F_disintegrant_pct", ["crospovidone", "disint", "croscarmellose"]], ["CQA_DISPERSIBILITY", ["dispers"]],
      ["CQA_FRIABILITY", ["friab"]], ["CQA_DISSOLUTION", ["de30", "dissol"]], ["CQA_CU_AV", ["cu_av", "_av"]]];
    const valid = new Set(targetsOf(s).map((t) => t[0]));
    for (const [t, kws] of map) if (valid.has(t) && kws.some((k) => lc.includes(k))) return t;
    return "";
  }

  function resultsForm(s) {
    const plan = s.plans.find((p) => p.doe_plan_id === s.active_plan);
    const batch = s.result_batch;
    const got = Object.values(s.results).filter((r) => r.plan_id === plan.doe_plan_id);
    const passed = got.filter((r) => (r.quality || {}).status === "PASS").length;
    const held = (plan.run_sheets || {}).held || [];
    const status = `<div class="hint">결과 ${got.length}개 (품질 게이트 통과 ${passed}) · 필요 ${plan.runs.length} run × DoE 반응 ${plan.response_ids.length}개.
      ${held.length ? `run sheet 발행 보류 ${held.length}건 — ${esc((plan.run_sheets || {}).note || "")}` : ""}</div>`;
    if (batch && batch.ids && batch.ids.length) {
      const rows = batch.ids.map((id) => s.results[id]).map((r) => `<tr class="${r.matched ? "" : "blocked"}">
        <td>${esc(r.doe_run_id)}</td><td>${esc(r.batch_id || "—")}</td><td>${esc((s.cqas[r.response_id] || {}).name || r.response_id)}</td>
        <td class="c">${num(r.summary_statistic.value, 3)}</td><td>${esc(r.evidence_status)}</td><td>${esc(r.replicate_independence)}</td></tr>`).join("");
      return `${status}<p>업로드한 값을 시스템이 이렇게 읽었습니다. 맞으면 확인하세요 — <b>확인된 결과만 분석합니다</b>.</p>
        <div class="table-wrap"><table class="matrix"><thead><tr><th>run</th><th>batch</th><th>반응</th><th>값</th><th>근거 등급</th><th>반복 독립성</th></tr></thead><tbody>${rows}</tbody></table></div>
        ${batch.unmatched_runs && batch.unmatched_runs.length ? `<div class="warn-tag">설계 run 중 결과가 없는 것: ${esc(batch.unmatched_runs.join(", "))}</div>` : ""}
        <div class="ask-actions"><button class="primary" data-act="results_confirm" data-accept="1">읽은 값 확인 → 품질 게이트</button>
          <button class="ghost" data-act="results_confirm" data-accept="0">반려 · 다시 올리기</button></div>`;
    }
    return `${status}${verdictList(subjectVerdicts("result_quality"), "직전 품질 게이트")}
      <div class="form">
        <label class="wide"><span>결과 CSV (run별 요인 설정 + 반응 값, batch_id·replicate_independence·evidence_status 열 권장)</span>
          <textarea id="rs-csv" rows="6" placeholder="run,x1,x2,x3,y1,...,batch_id,replicate_independence,evidence_status"></textarea></label>
        <div class="row"><input id="rs-file" type="file" accept=".csv,text/csv">
          ${s.script ? `<button type="button" class="ghost" id="rs-demo">시연 CSV 불러오기 (Almotairi 2022 Table 3)</button>` : ""}</div>
        <div id="rs-map" class="colmap"></div>
      </div>
      <div class="ask-actions"><button class="primary" data-act="results_submit">결과 제출 → 읽은 값 확인</button></div>`;
  }

  function regionFactors(s) {
    return Object.values(s.region ? s.region.symbols : {}).map((fid) => s.factors[fid]).filter(Boolean);
  }

  function regionStats(s) {
    const r = s.region.summary;
    const sp = r.setpoint;
    const names = Object.fromEntries(Object.values(s.factors).map((f) => [f.factor_id, f.name]));
    const bind = Object.entries(r.binding_cqa_counts || {}).map(([c, n]) => `${esc((s.cqas[c] || {}).name || c)} ${num(n, 0)}`).join(" · ");
    return `<div class="stats">
      <div><span>supported domain 격자</span><b>${num(r.grid_points_in_domain, 0)}</b><small>/ ${num(r.grid_points_total, 0)}</small></div>
      <div><span>평균 기준 통과</span><b>${pct(r.mean_ok_fraction)}</b></div>
      <div class="hl"><span>공동확률 ≥ 0.90</span><b>${pct(r.feasible_fraction)}</b></div>
      <div><span>권장 setpoint 공동확률</span><b>${sp ? num(sp.joint_probability, 3) : "—"}</b></div>
    </div>
    ${sp ? `<p class="setpoint">권장 setpoint — ${Object.entries(sp.actual).map(([fid, v]) => `${esc(names[fid] || fid)} <b>${num(v, 2)}</b>`).join(" · ")}
      <small>(경계 거리 ${num(sp.edge_distance, 2)} coded)</small></p>` : ""}
    <p class="hint">미통과 격자의 경계 주도 CQA: ${bind || "없음"} · 평균이 규격 안이어도 미래 배치 예측분포로 보면 영역이 좁아집니다.</p>`;
  }

  function vplanTable(s) {
    const vp = s.verification.plan;
    const names = Object.fromEntries(Object.values(s.factors).map((f) => [f.factor_id, f.name]));
    const doe = Object.values(s.cqas).filter((c) => c.analysis_role === "DOE_RESPONSE");
    const rows = vp.points.map((p) => `<tr class="${p.role === "REFERENCE_EXISTING" ? "ref" : ""}">
      <td><b>${esc(p.role)}</b><small class="sub">${esc(p.rationale)}</small></td>
      <td>${Object.entries(p.settings).map(([fid, v]) => `${esc(names[fid] || fid)} ${num(v, 2)}`).join("<br>")}</td>
      <td class="c">${num(p.predicted.joint_probability, 3)}</td>
      ${doe.map((c) => { const x = p.predicted.cqa[c.cqa_id] || {}; return `<td>${num(x.mean, 1)}<small class="sub">${num(x.pi_lower, 1)}–${num(x.pi_upper, 1)}</small></td>`; }).join("")}
    </tr>`).join("");
    const pol = vp.pi_policy || {};
    return `<p class="hint">예측구간: family = 필수 확인점 ${esc(pol.n_required_points)} × DoE 반응 ${esc(pol.n_doe_responses)} = ${esc(pol.comparisons)}개 비교,
        Bonferroni family α ${esc(pol.family_alpha)} → 개별 ${pct(pol.per_comparison_level, 2)}. ${vp.locked_at ? `<b>잠금 ${esc(vp.locked_hash)}</b>` : "아직 잠기지 않음"}</p>
      <div class="table-wrap"><table class="matrix"><thead><tr><th>확인점</th><th>설정</th><th>공동확률</th>${doe.map((c) => `<th>${esc(c.name)}<small class="sub">평균 · family PI</small></th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function verificationForm(s) {
    const v = s.verification;
    const pts = v.plan.points;
    const appl = Object.values(s.cqas).filter((c) => c.analysis_role !== "NOT_APPLICABLE");
    const pending = Object.values(v.results || {}).some((r) => r.human_verification_status === "PENDING");
    const cards = pts.map((p) => {
      const r = (v.results || {})[p.point_id];
      return `<div class="vpoint ${p.role === "REFERENCE_EXISTING" ? "ref" : ""}" data-point="${esc(p.point_id)}">
        <div class="vp-head"><b>${esc(p.role)}</b> ${r ? `<span class="mstat ${esc(r.human_verification_status)}">${esc(r.human_verification_status)}</span>` : ""}
          <small>${p.role === "REFERENCE_EXISTING" ? "참고 평가만 · 승격·무효화 근거 아님" : "필수 — 독립 제조배치"}</small></div>
        <div class="vp-ids">
          <label><span>batch_id</span><input data-f="batch_id" value="${esc(r ? r.batch_id || "" : "")}"></label>
          <label><span>parent_blend_id</span><input data-f="parent_blend_id" value="${esc(r ? r.parent_blend_id || "" : "")}"></label>
          <label><span>근거 등급</span><select data-f="evidence_status">${EVIDENCE.map((e) => `<option value="${e}" ${(r ? r.evidence_status : (p.role === "REFERENCE_EXISTING" ? "LITERATURE_DIRECT" : "MEASURED_UNCONFIRMED")) === e ? "selected" : ""}>${EVIDENCE_KO[e]}</option>`).join("")}</select></label>
        </div>
        <div class="vp-vals">${appl.map((c) => {
          const pr = p.predicted.cqa[c.cqa_id];
          const cur = r ? r.values[c.cqa_id] : "";
          return `<label><span>${esc(c.name)} <small>${esc(c.unit || "")}</small></span>
            <input data-cqa="${esc(c.cqa_id)}" value="${esc(cur ?? "")}" placeholder="${pr ? `PI ${num(pr.pi_lower, 1)}–${num(pr.pi_upper, 1)}` : esc(c.acceptance_operator === "PASS_FAIL" ? "PASS/FAIL" : "")}"></label>`;
        }).join("")}</div>
      </div>`;
    }).join("");
    return `${v.gate ? gateTable(s) : ""}
      ${verdictList(subjectVerdicts("verification_gate"), "확인 판정 규칙")}
      <p class="hint">잠근 예측구간과 비교합니다. <b>승격 판정(2×2)은 필수 확인점 3개를 새로 만든 독립 배치의 자체 실측으로만</b> 합니다 —
        문헌값·미확인 결과는 확인 판정에 쓸 수 없습니다(VR015). 계획 전부터 있던 참고 배치는 잠근 예측과 비교만 합니다.</p>
      <div class="vpoints">${cards}</div>
      <div class="ask-actions">
        <button data-act="verification_submit">결과 제출</button>
        <button class="primary" data-act="verification_confirm" ${pending ? "" : "disabled"}>제출값 확인 → 2×2 판정</button>
      </div>`;
  }

  function gateTable(s) {
    const g = (s.verification || {}).gate;
    if (!g) return "";
    const rows = Object.entries(g.points).map(([pid, x]) => {
      const cell = x.judged === false && x.evidence_status ? `판정 제외 — ${x.evidence_status}은 확인 판정에 쓸 수 없음` :
        x.spec_pass_all_applicable === null || x.spec_pass_all_applicable === undefined ? "—" :
        `${x.spec_pass_all_applicable ? "규격 통과" : "규격 실패"} · ${x.within_family_pi_all_doe ? "PI 안" : "PI 밖"}`;
      const good = x.spec_pass_all_applicable && x.within_family_pi_all_doe;
      return `<tr><td>${esc(x.role)}</td><td class="${good ? "ok" : x.spec_pass_all_applicable === false ? "bad" : ""}">${esc(cell)}</td>
        <td>${esc(x.evidence_status || "—")}</td></tr>`;
    }).join("");
    const head = g.partial ? "참고 평가 (예측과 비교)" : "2×2 판정";
    return `<div class="table-wrap"><table class="matrix gate"><thead><tr><th>확인점</th><th>${head}</th><th>근거 등급</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function finalCard(s) {
    const ds = s.region.design_space;
    const sc = ds.scope;
    return `<div class="final ${esc(ds.status)}">
      <div class="final-badge">${esc(ds.status)}</div>
      <p><b>${esc(ds.design_space_id)}@${esc(ds.version)}</b> — ${esc(ds.domain_bounds.description)}</p>
      ${regionStats(s)}
      <h4>성립 조건 (scope)</h4>
      <ul>
        <li>관리되지 않음: ${esc(sc.unmanaged.join(", ") || "없음")}</li>
        <li>요인 효과 미평가(MONITOR_ONLY): ${esc(sc.not_evaluated.join(", ") || "없음")}</li>
        <li>설비: ${esc(sc.equipment || "—")} · 배치 규모: ${esc(sc.batch_scale || "—")}</li>
        <li>외삽 구역: ${esc(sc.extrapolation_zones.map((z) => z.zone).join(", ") || "없음")}</li>
        <li>한계: ${esc(sc.limitations || "—")}</li>
      </ul>
      <p class="hint">VERIFIED = 내부 사전계획 통과. 세 점 각 1배치는 세 위치의 확인이지 영역 전체의 증명이 아니며, 규제기관이 승인한 Design Space나 PPQ 완료를 뜻하지 않습니다.</p>
    </div>`;
  }

  // 행동별 입력 수집 ----------------------------------------------------------
  const COLLECT = {
    required_data: (root) => ({
      batch_scale: val(root, "#rd-scale") || undefined,
      equipment_id: val(root, "#rd-eq") || undefined,
      fixed_parameters: [...root.querySelectorAll("[data-fixed]")].map((row) => ({
        name: row.dataset.fixed,
        status: row.querySelector(".fx-unknown").checked ? "UNKNOWN" : "SET",
        value: row.querySelector(".fx-val").value, reason: row.querySelector(".fx-reason").value,
      })).filter((f) => f.status === "UNKNOWN" || f.value !== ""),
      grades: [...root.querySelectorAll(".rd-grade")].map((g) => ({ name: g.dataset.name, grade: g.value.trim() })).filter((g) => g.grade),
    }),
    cqa_edit: (root) => {
      const reason = val(root, "#ask-reason");
      const edits = [];
      root.querySelectorAll("tr[data-cqa]").forEach((tr) => {
        const c = study.cqas[tr.dataset.cqa];
        const changes = {};
        tr.querySelectorAll("[data-f]").forEach((inp) => {
          const f = inp.dataset.f;
          let v = inp.value.trim();
          const orig = c[f] === null || c[f] === undefined ? "" : String(c[f]);
          if (v !== orig) changes[f] = ["lower", "upper", "practical_effect_threshold"].includes(f) ? numOrNull(v) : (v === "" ? null : v);
        });
        if (tr.dataset.assumption === "1") changes.assumption = true;
        const evidence = tr.dataset.evidence || (changes.analysis_role === "NOT_APPLICABLE" ? reason : "") || undefined;
        if (Object.keys(changes).length) edits.push({ cqa_id: tr.dataset.cqa, changes, reason: tr.dataset.reason || reason, evidence_ref: evidence });
      });
      if (!edits.length) throw new Error("바꾼 값이 없습니다.");
      return { edits };
    },
    cqa_approve: (root) => ({ reason: val(root, "#ask-reason") }),
    cqa_reject: (root) => ({ reason: val(root, "#ask-reason") }),
    fmea_edit: (root) => {
      const reason = val(root, "#ask-reason");
      const edits = [];
      root.querySelectorAll("tr[data-row]").forEach((tr) => {
        const r = study.fmea.rows.find((x) => x.row_id === tr.dataset.row);
        const changes = {};
        tr.querySelectorAll("[data-f]").forEach((inp) => {
          const f = inp.dataset.f;
          const v = inp.value.trim();
          const orig = r[f] === null || r[f] === undefined ? "" : String(r[f]);
          if (v !== orig) changes[f] = f === "occurrence" ? numOrNull(v) : (v === "" ? null : v);
        });
        if (Object.keys(changes).length) edits.push({ row_id: r.row_id, changes, reason: tr.dataset.reason || reason,
          evidence_ref: tr.dataset.evidence || changes.occurrence_evidence || null });
      });
      if (!edits.length) throw new Error("바꾼 값이 없습니다.");
      return { edits };
    },
    fmea_approve: (root) => ({ reason: val(root, "#ask-reason") }),
    fmea_reject: (root) => ({ reason: val(root, "#ask-reason") }),
    factor_data: (root) => {
      const factors = {};
      root.querySelectorAll(".factor[data-src]").forEach((card) => {
        const g = (f) => { const x = card.querySelector(`[data-f="${f}"]`); return x ? x.value.trim() : ""; };
        factors[card.dataset.src] = { low: numOrNull(g("low")), high: numOrNull(g("high")), source_ref: g("source_ref") || null,
          evidence_status: g("evidence_status"), manufacturability_evidence: g("manufacturability_evidence") || null,
          disposition: g("disposition") };
      });
      return { factors, reason: val(root, "#ask-reason") };
    },
    factor_approve: (root) => ({ prior_evidence_approved: root.querySelector("#fa-prior").checked,
      extreme_corner_risk: root.querySelector("#fa-corner").checked, design_type: val(root, "#fa-type") || null,
      reason: val(root, "#ask-reason") }),
    plan_approve: (root) => ({ reason: val(root, "#ask-reason") }),
    plan_reject: (root) => ({ reason: val(root, "#ask-reason"), design_type: val(root, "#pl-type") || null }),
    results_submit: (root) => {
      const csv = val(root, "#rs-csv");
      if (!csv) throw new Error("CSV 내용이 비어 있습니다.");
      const column_map = {};
      root.querySelectorAll("#rs-map select").forEach((sel) => { if (sel.value) column_map[sel.dataset.col] = sel.value; });
      return { csv, column_map, source: root.querySelector("#rs-csv").dataset.source || "upload" };
    },
    results_confirm: (root, btn) => ({ accept: btn.dataset.accept === "1" }),
    model_reduce: (root, btn) => {
      const card = root.querySelector(`.model-card[data-cqa="${btn.dataset.cqa}"]`);
      return { cqa_id: btn.dataset.cqa, terms: ["1", ...[...card.querySelectorAll(".term:checked")].map((x) => x.value)],
        reason: val(root, "#ask-reason") || "과적합 flag — 계층성 유지 축소" };
    },
    model_accept: (root, btn) => {
      const card = root.querySelector(`.model-card[data-cqa="${btn.dataset.cqa}"]`);
      return { cqa_id: btn.dataset.cqa, reason: card.querySelector(".accept-reason").value.trim() };
    },
    model_approve: (root) => ({ reason: val(root, "#ask-reason") }),
    model_augment: (root) => ({ reason: val(root, "#ask-reason") }),
    region_approve: (root) => {
      const ref = {};
      root.querySelectorAll(".ref-v").forEach((i) => { if (i.value !== "") ref[i.dataset.fid] = Number(i.value); });
      const n = root.querySelectorAll(".ref-v").length;
      if (Object.keys(ref).length && Object.keys(ref).length !== n) throw new Error("참고 배치는 모든 요인 값을 넣거나 전부 비워 두세요.");
      return { robustness_delta: Number(val(root, "#rg-delta") || 0.2), include_challenge: root.querySelector("#rg-challenge").checked,
        reference: Object.keys(ref).length ? ref : null, reason: val(root, "#ask-reason") };
    },
    region_revise: (root) => ({ reason: val(root, "#ask-reason") }),
    vplan_lock: (root) => ({ reason: val(root, "#ask-reason") }),
    vplan_reject: (root) => ({ reason: val(root, "#ask-reason") }),
    verification_submit: (root) => {
      const points = {};
      root.querySelectorAll(".vpoint[data-point]").forEach((card) => {
        const values = {};
        let any = false;
        card.querySelectorAll("[data-cqa]").forEach((i) => {
          const v = i.value.trim();
          if (v !== "") { any = true; values[i.dataset.cqa] = /^[-+]?\d*\.?\d+(e[-+]?\d+)?$/i.test(v) ? Number(v) : v; }
        });
        if (!any) return;
        const g = (f) => card.querySelector(`[data-f="${f}"]`).value.trim();
        points[card.dataset.point] = { batch_id: g("batch_id"), parent_blend_id: g("parent_blend_id"),
          evidence_status: g("evidence_status"), values };
      });
      if (!Object.keys(points).length) throw new Error("입력한 확인배치 결과가 없습니다.");
      return { points };
    },
    verification_confirm: () => ({}),
    finalize: (root) => ({ limitations: val(root, "#fn-lim"), reason: val(root, "#ask-reason") }),
    final_more: (root) => ({ reason: val(root, "#ask-reason") }),
    directive_approve: (root) => ({ directive: val(root, "#dg-dir"), reason: val(root, "#ask-reason") }),
    directive_reject: (root) => ({ reason: val(root, "#ask-reason") }),
    replan: (root, btn) => ({ target: btn.dataset.target, design_type: val(root, "#rp-type") || null,
      prior_evidence_approved: root.querySelector("#rp-prior") ? root.querySelector("#rp-prior").checked : undefined,
      reason: val(root, "#ask-reason") }),
    triage_resolve: (root) => ({ reason: val(root, "#ask-reason") }),
  };

  // 데모 입력 채우기 — 폼만 채운다. 제출은 연구자가 누른다 ---------------------------
  const setv = (node, v) => { if (node && v !== undefined && v !== null) { node.value = v; node.classList.add("filled"); } };
  const FILL = {
    WAITING_REQUIRED_DATA: (root, sc) => {
      setv(root.querySelector("#rd-scale"), sc.required_data.batch_scale);
      sc.required_data.fixed_parameters.forEach((f) => {
        const row = root.querySelector(`[data-fixed="${f.name}"]`);
        if (!row) return;
        row.querySelector(".fx-unknown").checked = f.status === "UNKNOWN";
        setv(row.querySelector(".fx-reason"), f.reason);
      });
      (sc.required_data.grades || []).forEach((g) => setv(root.querySelector(`.rd-grade[data-name="${g.name}"]`), g.grade));
    },
    WAITING_CQA_APPROVAL: (root, sc) => {
      sc.cqa_edits.forEach((e) => {
        const tr = root.querySelector(`tr[data-cqa="${e.cqa_id}"]`);
        if (!tr) return;
        Object.entries(e.changes).forEach(([f, v]) => setv(tr.querySelector(`[data-f="${f}"]`), v));
        if (e.changes.assumption) tr.dataset.assumption = "1";
        if (e.evidence_ref) tr.dataset.evidence = e.evidence_ref;
        tr.dataset.reason = e.reason;
      });
    },
    WAITING_FMEA_APPROVAL: (root, sc) => {
      sc.fmea_edits.forEach((e) => {
        const tr = root.querySelector(`tr[data-row="${e.row_id}"]`);
        if (!tr) return;
        Object.entries(e.changes).forEach(([f, v]) => setv(tr.querySelector(`[data-f="${f}"]`), v));
        tr.dataset.reason = e.reason;
        if (e.evidence_ref) tr.dataset.evidence = e.evidence_ref;
      });
    },
    WAITING_FACTOR_DATA: (root, sc) => fillFactors(root, sc),
    RANGE_FINDING_RUNS: (root, sc) => fillFactors(root, sc),
    WAITING_FACTOR_APPROVAL: (root, sc) => {
      fillFactors(root, sc);
      root.querySelector("#fa-prior").checked = sc.factor_approval.prior_evidence_approved;
      root.querySelector("#fa-corner").checked = sc.factor_approval.extreme_corner_risk;
      setv(root.querySelector("#ask-reason"), sc.factor_approval.reason);
    },
    RSM_EXECUTION: async (root) => {
      const ta = root.querySelector("#rs-csv");
      if (!ta) return;
      const d = await req("GET", "/api/development-studies/demo/lornoxicam/csv");
      ta.value = d.csv;
      ta.dataset.source = d.source;
      ta.classList.add("filled");
      ta.dispatchEvent(new Event("input"));
    },
    WAITING_MODEL_APPROVAL: (root, sc) => {
      const red = sc.model_reduction;
      const card = root.querySelector(`.model-card[data-cqa="${red.cqa_id}"]`);
      if (card) card.querySelectorAll(".term").forEach((t) => { t.checked = red.terms.includes(t.value); });
      const acc = root.querySelector(`.model-card[data-cqa="${sc.model_accept.cqa_id}"] .accept-reason`);
      setv(acc, sc.model_accept.reason);
      setv(root.querySelector("#ask-reason"), red.reason);
    },
    WAITING_REGION_APPROVAL: (root, sc) => {
      Object.entries(sc.reference_existing).forEach(([fid, v]) => setv(root.querySelector(`.ref-v[data-fid="${fid}"]`), v));
    },
    VERIFICATION_EXECUTION: (root, sc) => {
      // 논문 최적처방 배치의 공개 관측값(Table 5·6)만 채운다 — 필수 확인점 칸은 비워 둔다(실측은 실험실의 몫)
      const ref = study.verification.plan.points.find((x) => x.role === "REFERENCE_EXISTING");
      const card = ref && root.querySelector(`.vpoint[data-point="${ref.point_id}"]`);
      if (!card) return;
      const rr = sc.reference_results;
      setv(card.querySelector('[data-f="batch_id"]'), rr.batch_id);
      setv(card.querySelector('[data-f="parent_blend_id"]'), rr.parent_blend_id);
      card.querySelector('[data-f="evidence_status"]').value = rr.evidence_status;
      Object.entries(rr.values).forEach(([cid, v]) => setv(card.querySelector(`[data-cqa="${cid}"]`), v));
    },
    WAITING_FINAL_APPROVAL: (root, sc) => setv(root.querySelector("#fn-lim"), sc.limitations),
  };

  function fillFactors(root, sc) {
    Object.entries(sc.factor_inputs).forEach(([src, v]) => {
      const card = root.querySelector(`.factor[data-src="${src}"]`);
      if (!card) return;
      Object.entries(v).forEach(([f, x]) => setv(card.querySelector(`[data-f="${f}"]`), x));
    });
  }

  // 상태별 추가 배선 ------------------------------------------------------------
  const WIRE = {
    RSM_EXECUTION: (root) => wireResults(root),
    SCREENING_EXECUTION: (root) => wireResults(root),
    WAITING_REGION_APPROVAL: () => drawRegion(el("region-inline"), true),
  };

  function wireResults(root) {
    const ta = root.querySelector("#rs-csv");
    if (!ta) return;
    const remap = () => {
      const header = (ta.value.split(/\r?\n/)[0] || "").split(",").map((x) => x.trim()).filter(Boolean);
      const box = root.querySelector("#rs-map");
      if (!header.length) { box.innerHTML = ""; return; }
      const opts = targetsOf(study);
      box.innerHTML = `<div class="vlist-h">열 → 요인·CQA 대응 (시스템 추정 — 확인하고 고치세요)</div>` + header.map((col) => {
        const g = guess(col, study);
        return `<label><span><code>${esc(col)}</code></span><select data-col="${esc(col)}">${opts.map(([v, t]) =>
          `<option value="${esc(v)}" ${g === v ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
      }).join("");
    };
    ta.addEventListener("input", remap);
    const file = root.querySelector("#rs-file");
    file.onchange = async () => {
      const f = file.files[0];
      if (!f) return;
      ta.value = await f.text();
      ta.dataset.source = f.name;
      remap();
    };
    const demo = root.querySelector("#rs-demo");
    if (demo) demo.onclick = async () => {
      const d = await req("GET", "/api/development-studies/demo/lornoxicam/csv");
      ta.value = d.csv;
      ta.dataset.source = d.source;
      ta.classList.add("filled");
      remap();
    };
    remap();
  }

  // ── 영역 단면 (SVG) ───────────────────────────────────────────────────
  async function drawRegion(box, compact) {
    if (!box || !study || !study.region) return;
    const syms = Object.keys(study.region.symbols);
    if (syms.length < 3) {
      box.innerHTML = `<p class="hint">2요인 영역 — 단면 없이 전체가 한 장입니다.</p>`;
    }
    if (!slice.fixed || !syms.includes(slice.fixed)) slice.fixed = syms[syms.length - 1];
    let d;
    try {
      d = await req("GET", `/api/development-studies/${study.study_id}/region-slice?fixed=${encodeURIComponent(slice.fixed)}&index=${slice.index}`);
    } catch (e) {
      box.innerHTML = `<p class="hint">영역 단면을 불러오지 못했습니다: ${esc(e.message)}</p>`;
      return;
    }
    const fid = (sym) => study.region.symbols[sym];
    const fac = (sym) => study.factors[fid(sym)];
    const actual = (sym, coded) => { const f = fac(sym); const lo = +f.low.value, hi = +f.high.value; return (lo + hi) / 2 + coded * (hi - lo) / 2; };
    const n = d.x_axis.length, m = d.y_axis.length;
    const W = compact ? 300 : 320, pad = 34, cell = (W - pad - 8) / n;
    const H = pad + m * cell + 8;
    let cells = "";
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < m; j++) {
        const inD = d.in_domain[i][j];
        const P = d.P[i][j];
        const x = pad + i * cell, y = 8 + (m - 1 - j) * cell;
        if (!inD) { cells += `<rect x="${x}" y="${y}" width="${cell}" height="${cell}" class="rg-out"/>`; continue; }
        const ok = P >= d.threshold;
        cells += `<rect x="${x}" y="${y}" width="${cell + 0.3}" height="${cell + 0.3}" class="${ok ? "rg-ok" : "rg-no"}" style="opacity:${ok ? (0.45 + 0.55 * (P - d.threshold) / (1 - d.threshold)).toFixed(2) : (0.12 + 0.5 * P).toFixed(2)}"><title>P=${P.toFixed(3)}${d.binding ? ` · 주도 ${(study.cqas[d.binding[i][j]] || {}).name || ""}` : ""}</title></rect>`;
      }
    }
    // setpoint가 이 단면에 있으면 표시
    const sp = study.region.summary.setpoint;
    let mark = "";
    if (sp && Math.abs(sp.coded[d.fixed] - d.fixed_value_coded) < 1e-6) {
      const xi = d.x_axis.findIndex((v) => Math.abs(v - sp.coded[d.x]) < 1e-6);
      const yj = d.y_axis.findIndex((v) => Math.abs(v - sp.coded[d.y]) < 1e-6);
      if (xi >= 0 && yj >= 0) mark = `<circle cx="${pad + (xi + 0.5) * cell}" cy="${8 + (m - 1 - yj + 0.5) * cell}" r="${Math.max(3, cell * 0.45)}" class="rg-sp"><title>권장 setpoint</title></circle>`;
    }
    const lab = (sym) => `${fac(sym).name}`;
    box.innerHTML = `
      <div class="rg-ctrl">
        <label><span>단면 고정 요인</span><select class="rg-fixed">${syms.map((s) => `<option value="${esc(s)}" ${s === d.fixed ? "selected" : ""}>${esc(lab(s))}</option>`).join("")}</select></label>
        <label class="rg-slide"><span>${esc(lab(d.fixed))} = <b>${num(actual(d.fixed, d.fixed_value_coded), 2)}</b></span>
          <input type="range" min="0" max="${n - 1}" value="${d.index}" class="rg-idx"></label>
      </div>
      <svg viewBox="0 0 ${W} ${H + 26}" class="rg-svg" role="img" aria-label="공동확률 영역 단면">
        ${cells}${mark}
        <text x="${pad + (n * cell) / 2}" y="${H + 16}" class="rg-ax" text-anchor="middle">${esc(lab(d.x))} ${num(actual(d.x, d.x_axis[0]), 1)}–${num(actual(d.x, d.x_axis[n - 1]), 1)}</text>
        <text x="12" y="${8 + (m * cell) / 2}" class="rg-ax" text-anchor="middle" transform="rotate(-90 12 ${8 + (m * cell) / 2})">${esc(lab(d.y))} ${num(actual(d.y, d.y_axis[0]), 1)}–${num(actual(d.y, d.y_axis[m - 1]), 1)}</text>
      </svg>
      <div class="rg-legend"><span><i class="rg-ok"></i>공동확률 ≥ ${d.threshold}</span><span><i class="rg-no"></i>미달</span><span><i class="rg-out"></i>supported domain 밖</span><span><i class="rg-spl"></i>setpoint</span></div>`;
    box.querySelector(".rg-fixed").onchange = (e) => { slice.fixed = e.target.value; slice.index = 10; drawRegion(box, compact); };
    box.querySelector(".rg-idx").onchange = (e) => { slice.index = Number(e.target.value); drawRegion(box, compact); };
  }

  // ── 오른쪽: 결과 · 규칙 · lineage ─────────────────────────────────────
  function renderSide() {
    document.querySelectorAll(".side-tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === sideTab));
    const body = el("studio-side-body");
    if (sideTab === "rules") return renderRules(body);
    if (sideTab === "trace") return renderTrace(body);
    const s = study;
    const blocks = [];
    if (s.status === "COMPLETED" || (s.region && s.region.design_space.status !== "PROVISIONAL")) blocks.push(finalCard(s));
    if (s.verification) blocks.push(`<h4>확인계획</h4>${vplanTable(s)}${gateTable(s)}`);
    if (s.region) blocks.push(`<h4>잠정 영역 <span class="mstat ${esc(s.region.design_space.status)}">${esc(s.region.design_space.status)}</span></h4>
      ${regionStats(s)}<div id="region-side"></div>`);
    const modelIds = Object.keys(s.models || {});
    if (modelIds.length) blocks.push(`<h4>반응 모델</h4><table class="mini"><thead><tr><th>CQA</th><th>R²</th><th>pred R²</th><th>상태</th></tr></thead><tbody>
      ${modelIds.map((c) => { const m = s.models[c][s.models[c].length - 1]; const f = m.fit_stats || {};
        return `<tr><td>${esc(s.cqas[c].name)}${m.reduced_from ? " <small>(축소)</small>" : ""}</td><td>${num(f.r2)}</td><td>${num(f.pred_r2)}</td><td><span class="mstat ${esc(m.validation_status)}">${esc(m.validation_status)}</span></td></tr>`; }).join("")}</tbody></table>`);
    const plan = (s.plans || []).find((p) => p.doe_plan_id === s.active_plan);
    if (plan) blocks.push(`<h4>설계</h4><p class="kv">${esc(plan.design_type)} · ${esc(plan.runs.length)} run · ${esc(plan.status)} · 결과 ${Object.values(s.results || {}).filter((r) => r.plan_id === plan.doe_plan_id && (r.quality || {}).status === "PASS").length}개 확정</p>`);
    const facs = Object.values(s.factors || {});
    if (facs.length) blocks.push(`<h4>요인·수준</h4><table class="mini"><tbody>${facs.map((f) => `<tr><td>${esc(f.name)}</td><td>${esc(f.low.value ?? "—")} · <b>${esc(f.center.value ?? "—")}</b> · ${esc(f.high.value ?? "—")}</td><td>${esc(DISP[f.disposition] || f.disposition)}</td></tr>`).join("")}</tbody></table>`);
    if ((s.fmea || {}).rows && s.fmea.rows.length) {
      const rows = s.fmea.rows.filter((r) => !r.deleted);
      const cnt = (d) => rows.filter((r) => r.disposition === d).length;
      blocks.push(`<h4>FMEA v${esc(s.fmea.version)}</h4><p class="kv">${rows.length}행 · DoE 요인 ${cnt("DOE_CANDIDATE")} · 고정 ${cnt("FIXED")} · 자료 요청 ${cnt("REQUEST_DATA")} · LLM 가설 ${rows.filter((r) => r.evidence_status === "LLM_HYPOTHESIS").length}</p>`);
    }
    const cqas = Object.values(s.cqas || {});
    if (cqas.length) blocks.push(`<h4>CQA 계약</h4><table class="mini cqa-mini"><tbody>${cqas.map((c) => `<tr><td>${esc(c.name)}${c.binding_status === "NON_BINDING" ? " <small>NON_BINDING</small>" : ""}</td><td>${esc(ROLE_KO[c.analysis_role])}</td><td>${esc(critText(c))}${c.assumption ? " <small>가정</small>" : ""}</td></tr>`).join("")}</tbody></table>`);
    const h = s.handoff;
    blocks.push(`<h4>Handoff (불변)</h4><p class="kv"><code>${esc(h.handoff_id)}</code> · fingerprint <code>${esc(h.formulation_fingerprint)}</code></p>
      <table class="mini"><tbody>${h.ingredients.map((i) => `<tr><td>${esc(i.name)}</td><td>${esc(i.role)}</td><td>${num(i.pct_w_w, 2)}%</td></tr>`).join("")}</tbody></table>
      <p class="kv">공정 ${esc(h.process_route_id)} (${esc(h.process_steps.length)}단계) · 배치 ${esc(h.batch_scale || "—")} · 고정 변수 ${h.fixed_parameters.map((p) => `${esc(p.name)}=${esc(p.status === "SET" ? p.value : p.status)}`).join(", ")}</p>
      ${(h.sources || []).length ? `<h4>출처</h4><ul class="as-list">${h.sources.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
      ${(s.assumptions || []).length ? `<h4>가정 (연구자 입력)</h4><ul class="as-list">${s.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}`);
    body.innerHTML = blocks.join("");
    if (s.region) drawRegion(el("region-side"), false);
  }

  function critText(c) {
    const u = c.unit || "";
    switch (c.acceptance_operator) {
      case "LE": return c.upper !== null ? `≤ ${c.upper} ${u}` : "상한 미정";
      case "GE": return c.lower !== null ? `≥ ${c.lower} ${u}` : "하한 미정";
      case "BETWEEN": return c.lower !== null && c.upper !== null ? `${c.lower}–${c.upper} ${u}` : "범위 미정";
      case "TARGET_TOL": return `${c.target} ± ${c.target_tolerance} ${u}`;
      case "PASS_FAIL": return "적합/부적합";
      default: return "미정";
    }
  }

  function renderRules(body) {
    const evs = study.evaluations || {};
    const order = Object.keys(evs).reverse();
    body.innerHTML = `<p class="hint">모든 판정은 <code>database/07_doe</code> 룰북(171개, AST 화이트리스트 평가기)이 냅니다. 발화하지 않은 규칙도 평가됩니다 — 여기에는 발화·결측만 보입니다.</p>` +
      order.map((k) => {
        const ev = evs[k];
        const vs = ev.verdicts.filter((v) => v.status !== "NOT_FIRES");
        const dec = ev.decisive;
        return `<div class="rule-block"><div class="rb-head"><b>${esc(k)}</b> <small>${esc(ev.stage)} · 평가 ${esc(ev.evaluated)}건</small>
          ${dec ? `<span class="vchip ${EFFECT_CLS[dec.effect] || ""}">결정: ${esc(dec.rule_id)} ${esc(EFFECT_KO[dec.effect] || dec.effect)}${ev.next_state ? ` → ${esc(ev.next_state)}` : ""}</span>` : ""}</div>
          ${vs.length ? vs.map((v) => `<div class="vrow ${v.status === "NOT_CHECKED" ? "muted" : EFFECT_CLS[v.effect] || ""}">
            <button type="button" class="vchip ${EFFECT_CLS[v.effect] || ""}" data-rule="${esc(v.rule_id)}">${esc(v.rule_id)}</button>
            <span>${esc(v.status === "NOT_CHECKED" ? "NOT_CHECKED (값 없음)" : EFFECT_KO[v.effect] || v.effect)} · ${esc(v.subject)} — ${esc(v.message)}${v.overridden ? " <em>(override)</em>" : ""}</span></div>`).join("") : `<div class="muted">발화 없음</div>`}
        </div>`;
      }).join("");
    body.querySelectorAll("[data-rule]").forEach((b) => { b.onclick = () => showRule(b.dataset.rule); });
  }

  async function renderTrace(body) {
    body.innerHTML = `<p class="hint">불러오는 중…</p>`;
    try {
      const t = await req("GET", `/api/development-studies/${study.study_id}/trace`);
      const ids = t.identifiers;
      body.innerHTML = `<h4>역추적 식별자 (§18)</h4>
        <table class="mini"><tbody>
          <tr><td>후보</td><td><code>${esc(ids.candidate)}</code></td></tr>
          <tr><td>Handoff</td><td><code>${esc(ids.handoff_id)}</code></td></tr>
          <tr><td>CQA</td><td>${ids.cqas.map((x) => `<code>${esc(x)}</code>`).join(" ")}</td></tr>
          <tr><td>FMEA</td><td>v${esc(ids.fmea_version)}</td></tr>
          <tr><td>요인</td><td>${ids.factors.map((x) => `<code>${esc(x)}</code>`).join(" ")}</td></tr>
          <tr><td>DoE plan</td><td>${ids.doe_plans.map((x) => `<code>${esc(x)}</code>`).join(" ")}</td></tr>
          <tr><td>결과</td><td>${esc(ids.test_results)}건</td></tr>
          <tr><td>모델</td><td>${ids.response_models.map((x) => `<code>${esc(x)}</code>`).join(" ")}</td></tr>
          <tr><td>영역</td><td><code>${esc(ids.design_space || "—")}</code></td></tr>
          <tr><td>확인계획</td><td><code>${esc(ids.verification_plan_id || "—")}</code></td></tr>
        </tbody></table>
        <h4>상태 전이 (${t.timeline.length})</h4>
        <ol class="tl">${t.timeline.map((x) => `<li><code>${esc(x.from)}</code> → <code>${esc(x.to)}</code> <small>${esc(x.reason)}</small></li>`).join("")}</ol>
        <h4>결정·override 원장 (${t.decisions.length})</h4>
        <ol class="tl">${t.decisions.map((d) => `<li><b>${esc(d.kind || "OVERRIDE")}</b> ${d.rule_id ? `<code>${esc(d.rule_id)}</code> ` : ""}<small>${esc(d.reason || d.researcher_decision || "")}</small></li>`).join("")}</ol>`;
    } catch (e) {
      body.innerHTML = `<p class="hint">lineage를 불러오지 못했습니다: ${esc(e.message)}</p>`;
    }
  }


  // ── 가이드 시연 (Lornoxicam 분산정) ───────────────────────────────────
  // 장면마다 "무엇을 보여 주는가"를 띄우고, 다음 단계를 사람이 누르듯 실행한다: 폼을 채워 보여 준 뒤
  // 연구자 버튼을 누른다(doAction — 수동 조작과 같은 경로). 판정·계산은 매번 서버가 새로 한다.
  const guide = { on: false, auto: false, blockShown: false, running: false, done: false };
  const SCENES = [
    { n: 1, states: ["WAITING_REQUIRED_DATA"], title: "진입 — 빠진 자료는 규칙이 짚어 요청한다",
      watch: "RD006(배치 규모)·RD007(압축력)이 자료를 요청합니다. 압축력은 모른다고 UNKNOWN으로 기록 — 최종 영역의 한계로 끝까지 따라갑니다." },
    { n: 2, states: ["WAITING_CQA_APPROVAL"], title: "CQA 계약 — 규격 없는 반응은 DoE에 못 들어간다",
      watch: "먼저 그대로 승인해 봅니다 → CR006·CR002가 막습니다. DE30 ≥ 75 %처럼 연구자가 넣은 기준은 '가정'으로 표시됩니다." },
    { n: 3, states: ["WAITING_FMEA_APPROVAL"], title: "FMEA — 처리 방향은 연구자가, 가설 태그는 그대로",
      watch: "O를 모르면 RPN을 계산하지 않습니다(미계산). 압축력은 고심각도·검출 불가, 활택은 고정. LLM 가설 행은 채택해도 LLM_HYPOTHESIS 태그가 남습니다." },
    { n: 4, states: ["FACTOR_READINESS", "WAITING_FACTOR_DATA", "RANGE_FINDING_RUNS", "WAITING_FACTOR_APPROVAL"],
      title: "요인·수준 — center는 후보 현재값, 경계는 근거가 있어야",
      watch: "근거 없는 경계는 만들지 않습니다(FR002). 크로스포비돈 2–10 %는 통상 범위 2–5 % 밖(FR003), balance 구조라 희석 교락 경고(FR007)." },
    { n: 5, states: ["DESIGN_SELECTION", "RSM_PLANNING", "WAITING_RSM_APPROVAL"], title: "설계 — 3요인 + 사전근거면 RSM 직행",
      watch: "Box–Behnken 15 run이 코드로 생성됩니다(rank 10/10, 잔차 자유도 5). 설계점 밖 꼭짓점 영역은 외삽 구역으로 빠집니다." },
    { n: 6, states: ["RSM_EXECUTION", "MODEL_VALIDATION", "WAITING_MODEL_APPROVAL"], title: "결과·모델 — 읽은 값을 확인해야 분석한다",
      watch: "논문 실측 CSV를 올리면 시스템이 읽은 60개 값을 연구자가 확인합니다. 마손도 예측 R² 0.25 → 선형 축소, 함량균일성 과적합 flag → 사유 달고 수용." },
    { n: 7, states: ["REGION_COMPUTATION", "WAITING_REGION_APPROVAL"], title: "잠정 영역 — 평균 77 %가 미래 배치로는 48 %",
      watch: "단면 지도의 초록이 공동 통과확률 ≥ 0.90 영역입니다. 권장 setpoint 2.7 / 12.5분 / 6.8 % (공동확률 0.991)." },
    { n: 8, states: ["VERIFICATION_PLANNING", "WAITING_VERIFICATION_PLAN_APPROVAL"], title: "확인계획 — 예측구간은 첫 결과 전에 잠근다",
      watch: "필수 3점 × 4반응 = 12개 비교 → Bonferroni 개별 99.58 %. 논문 최적처방 배치는 결과가 이미 공개돼 참고 평가만 합니다." },
    { n: 9, states: ["VERIFICATION_EXECUTION", "VERIFICATION_GATE", "WAITING_FINAL_APPROVAL", "COMPLETED"],
      title: "확인배치 — 승격은 새 독립 배치로만",
      watch: "논문 최적처방 배치(3:1 · 11분 · 6.23 %)의 공개 관측값(Table 5·6)을 참고점으로 넣어 잠근 예측구간과 비교합니다. 참고 평가는 승격·무효화 근거가 아닙니다 — VERIFIED에는 필수 확인점 3개의 새 독립 배치 실측이 필요합니다." },
  ];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const sceneOf = (status) => SCENES.find((x) => x.states.includes(status));

  async function fillNow() {
    const f = FILL[study.status];
    if (f) await f(el("studio-ask"), study.script);
    await sleep(guide.auto ? 900 : 450);
  }
  const press = (sel) => doAction(el("studio-ask").querySelector(sel));
  const lastModel = (cid) => { const ms = (study.models || {})[cid] || []; return ms[ms.length - 1] || {}; };

  function nextStep() {
    const s = study;
    switch (s.status) {
      case "WAITING_REQUIRED_DATA":
        return { label: "배치 규모 입력 · 압축력 UNKNOWN 기록 → 제출", run: async () => { await fillNow(); return press('[data-act="required_data"]'); } };
      case "WAITING_CQA_APPROVAL": {
        const d = s.cqas.CQA_DISSOLUTION || {};
        if (!d.summary_definition) {
          if (!guide.blockShown) {
            return { label: "규격을 비운 채 승인해 보기 — 규칙이 막는 장면", expectBlock: true,
                     run: async () => { await press('[data-act="cqa_approve"]'); guide.blockShown = true; return true; } };
          }
          return { label: "DE30 ≥ 75 % 등 규격 입력 → 저장·재판정", run: async () => { await fillNow(); return press('[data-act="cqa_edit"]'); } };
        }
        return { label: "CQA 계약 승인", run: () => press('[data-act="cqa_approve"]') };
      }
      case "WAITING_FMEA_APPROVAL": {
        const fm = (s.fmea.rows || []).find((r) => r.row_id === "FM008");
        if (fm && fm.disposition !== "FIXED") return { label: "처리 방향·발생도 근거 입력 → 저장", run: async () => { await fillNow(); return press('[data-act="fmea_edit"]'); } };
        return { label: "FMEA 승인", run: () => press('[data-act="fmea_approve"]') };
      }
      case "WAITING_FACTOR_DATA": case "RANGE_FINDING_RUNS":
        return { label: "연구 범위·출처 입력 → 재판정", run: async () => { await fillNow(); return press('[data-act="factor_data"]'); } };
      case "WAITING_FACTOR_APPROVAL":
        return { label: "사전근거 승인과 함께 요인 승인", run: async () => { await fillNow(); return press('[data-act="factor_approve"]'); } };
      case "WAITING_RSM_APPROVAL":
        return { label: "Box–Behnken 설계 승인", run: () => press('[data-act="plan_approve"]') };
      case "RSM_EXECUTION":
        if (s.result_batch && (s.result_batch.ids || []).length) {
          return { label: "읽은 값 확인 → 품질 게이트", run: () => press('[data-act="results_confirm"][data-accept="1"]') };
        }
        return { label: "논문 실측 CSV 불러오기 → 제출", run: async () => { await fillNow(); return press('[data-act="results_submit"]'); } };
      case "WAITING_MODEL_APPROVAL": {
        const fr = lastModel("CQA_FRIABILITY"), av = lastModel("CQA_CU_AV");
        if (fr.validation_status === "FLAGGED" && !fr._needs_fit) {
          return { label: "마손도 — 선형 항만 남겨 축소", run: async () => { await fillNow(); return press('.model-card[data-cqa="CQA_FRIABILITY"] [data-act="model_reduce"]'); } };
        }
        if (av.validation_status === "FLAGGED") {
          return { label: "함량균일성 — 사유 달고 flag 수용", run: async () => { await fillNow(); return press('.model-card[data-cqa="CQA_CU_AV"] [data-act="model_accept"]'); } };
        }
        return { label: "판단 완료 → 다시 검증", run: () => press('[data-act="model_approve"]') };
      }
      case "WAITING_REGION_APPROVAL":
        return { label: "참고 배치 포함 · PROVISIONAL 승인", run: async () => { await fillNow(); return press('[data-act="region_approve"]'); } };
      case "WAITING_VERIFICATION_PLAN_APPROVAL":
        return { label: "확인계획 잠금", run: () => press('[data-act="vplan_lock"]') };
      case "VERIFICATION_EXECUTION": {
        const v = s.verification || {};
        const ref = (v.plan.points || []).find((x) => x.role === "REFERENCE_EXISTING");
        const r = ref && (v.results || {})[ref.point_id];
        if (ref && !r) return { label: "논문 최적처방 배치의 공개 관측값 입력 → 제출", run: async () => { await fillNow(); return press('[data-act="verification_submit"]'); } };
        if (r && r.human_verification_status === "PENDING") return { label: "제출값 확인 → 참고 평가", run: () => press('[data-act="verification_confirm"]') };
        return null;
      }
      default:
        return null;
    }
  }

  async function guideStep() {
    if (guide.running || busy) return;
    const st = nextStep();
    if (!st) { guide.auto = false; renderGuide(); return; }
    guide.running = true;
    renderGuide();
    let ok = false;
    try { ok = await st.run(); } catch (e) { lastError = { message: e.message }; }
    guide.running = false;
    if (!ok && !st.expectBlock) guide.auto = false;
    renderGuide();
  }

  async function autoPlay() {
    guide.auto = true;
    renderGuide();
    while (guide.auto && nextStep()) {
      await guideStep();
      if (!guide.auto) break;
      await sleep(1700);
    }
    guide.auto = false;
    renderGuide();
  }

  function renderGuide() {
    const box = el("studio-guide");
    if (!box) return;
    if (!study || study.demo_script !== "lornoxicam" || !guide.on) { box.hidden = true; return; }
    box.hidden = false;
    const sc = sceneOf(study.status);
    const cur = sc ? sc.n : null;
    const nx = nextStep();
    const end = !nx;
    box.innerHTML = `
      <div class="gb-head">
        <b>가이드 시연 · Lornoxicam 분산정</b>
        <span class="gb-count">${cur ? `장면 ${cur} / ${SCENES.length}` : ""}</span>
        <button type="button" class="ghost gb-hide">가이드 숨기기</button>
      </div>
      <ol class="gb-scenes">${SCENES.map((x) => `<li class="${x.n === cur ? "on" : cur && x.n < cur ? "done" : ""}" title="${esc(x.title)}"><span>${x.n}</span></li>`).join("")}</ol>
      ${sc ? `<div class="gb-now"><h4>${esc(sc.title)}</h4><p>${esc(sc.watch)}</p></div>` : ""}
      ${end ? `<div class="gb-end"><b>시연은 여기까지입니다.</b> 여기부터는 실험실의 몫입니다 — 잠근 계획대로 필수 확인점 3개를
          새 독립 배치로 만들고, 그 실측값을 근거 등급 '자체 실측'으로 넣으면 2×2 판정 → 한계 기록 → VERIFIED로 이어집니다.
          아래 질문 카드의 확인점 칸에 직접 입력할 수 있습니다.</div>` : ""}
      <div class="gb-actions">
        ${end ? `<button type="button" class="primary gb-restart">처음부터 다시</button>` : `
          <span class="gb-next"><em>다음 단계</em>${esc(nx.label)}</span>
          <button type="button" class="primary gb-step" ${guide.running || guide.auto ? "disabled" : ""}>${guide.running && !guide.auto ? "진행 중…" : "▶ 이 단계 진행"}</button>
          ${guide.auto ? `<button type="button" class="gb-pause">❚❚ 멈춤</button>` : `<button type="button" class="gb-auto" ${guide.running ? "disabled" : ""}>▶▶ 끝까지 자동 진행</button>`}`}
      </div>`;
    box.querySelector(".gb-hide").onclick = () => { guide.on = false; guide.auto = false; renderGuide(); renderAsk(); };
    const q = (c) => box.querySelector(c);
    if (q(".gb-step")) q(".gb-step").onclick = () => guideStep();
    if (q(".gb-auto")) q(".gb-auto").onclick = () => autoPlay();
    if (q(".gb-pause")) q(".gb-pause").onclick = () => { guide.auto = false; renderGuide(); };
    if (q(".gb-restart")) q(".gb-restart").onclick = () => startDemo();
  }

  // ── 시작 ───────────────────────────────────────────────────────────────
  function init() {
    el("tab-discovery").onclick = () => showTab("discovery");
    el("tab-studio").onclick = () => showTab("studio");
    el("studio-list").onchange = (e) => { if (e.target.value) { guide.auto = false; load(e.target.value).catch((err) => notice(err.message, "error")); } };
    document.querySelectorAll(".side-tab").forEach((b) => { b.onclick = () => { sideTab = b.dataset.tab; if (study) { renderSide(); } }; });
    let tab = "discovery", last = null;
    try { tab = localStorage.getItem("f1:tab") || "discovery"; last = localStorage.getItem("f1:study"); } catch (e) { /* 무시 */ }
    if (new URLSearchParams(location.search).get("studio") !== null) tab = "studio";
    showTab(tab);
    if (last) load(last).then(() => { if (study && study.demo_script === "lornoxicam") { guide.on = true; renderGuide(); } })
      .catch(() => { try { localStorage.removeItem("f1:study"); } catch (e) { /* 무시 */ } });
  }

  window.F1Studio = { startFromCandidate, showTab, startDemo };
  el("studio-demo").onclick = () => startDemo();
  init();
})();
