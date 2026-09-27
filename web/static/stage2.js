/* 2단계 — Design Space 도출. 1단계 후보(또는 CBD 논문 Table 1)를 프로토타입으로 받아 12단계를 대화에 차례로 쌓는다.

   1 프로토타입(Table 1) → 2 QTPP(Table 3) → 3 CQA(Table 4) → 4 원료 물성 위험평가(Table 6) → 5 정리(Table 5)
   → 6 제형·공정 변수 위험평가(Table 8) → 7 정리(Table 7) → 8 종합 정리 · DoE 변수 추천(위험평가 보고서 PDF)
   → 9 실험 설계 입력(Table 9) → 10 회귀식(Table 10) → 11 반응 곡면(Figure 1) → 12 ANOVA(Table 11) · 최종 보고서

   지금 단계만 고칠 수 있고, 승인한 단계는 접힌 카드로 남아 펼쳐 볼 수 있다(다시 열면 뒤 단계는 '다시 확인 필요').
   LLM 초안 · 논문 값 · 연구자 편집 모두 같은 저장 → 승인 길을 가고, 승인은 서버의 결정론 검사가 막는다.
   서버: /api/stage2/studies/* (formula/stage2/service.py). 모든 ${}는 esc()를 거친다. */
(() => {
  const $ = (id) => document.getElementById(id);
  const E = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 4) => (v == null || v === "" || !Number.isFinite(Number(v)) ? "—" : Math.abs(Number(v)) < 1e-12 ? "0" : Number(Number(v).toPrecision(d)).toString());
  const pfmt = (p) => (p == null ? "" : p < 0.0001 ? "< 0.0001" : Number(p).toFixed(4));
  const LEVELS = ["High", "Medium", "Low"];
  const BASIS = ["처방 자료", "약전·가이드라인", "일반 제제학 지식", "문헌(출처 기재)", "추정 — 확인 필요"];
  const SRC = { llm: "LLM 초안", paper: "논문 값", user: "연구자 입력", code: "코드 계산", upstream: "1단계 결과" };
  const FAMILY_KO = { Mean: "평균", Linear: "선형", "2FI": "2요인 교호작용", Quadratic: "2차" };
  const HINT = {
    prototype: "1단계가 넘긴 처방입니다. 성분·함량·기능을 확인하고 필요하면 고친 뒤 [실행]을 누르면 QTPP부터 시작합니다.",
    qtpp: "목표 제품 프로파일입니다. LLM이 프로토타입을 읽고 초안을 쓰며, 행을 더하거나 지우고 고친 뒤 승인합니다.",
    cqa: "품질특성마다 CQA인지와 그 논리적 근거를 적습니다. 위험평가에 넣을 CQA만 다음 단계의 열이 됩니다.",
    rm_just: "확정된 CQA마다 원료(API) 물성이 얼마나 위험한지와 그 기전을 적습니다. 같은 판단을 공유하는 CQA는 한 행으로 묶습니다.",
    rm_matrix: "4단계 근거에서 코드가 만든 위험 행렬입니다. 칸마다 그 칸을 덮은 근거의 등급이라 근거와 어긋날 수 없습니다.",
    fp_just: "처방의 모든 부형제와 조절 가능한 공정 파라미터(압축력 등)를 CQA마다 평가합니다.",
    fp_matrix: "6단계 근거에서 코드가 만든 위험 행렬입니다.",
    recommend: "두 위험 행렬을 합친 종합 정리입니다. High·Medium인 제형·공정 변수만 DoE 후보가 되고, 최대 4개를 고릅니다.",
    design: "실험을 실제로 한 표를 적습니다. 요인 1–3개, 반응 1–4개, 행은 필요한 만큼 — 엑셀에서 복사해 붙여 넣을 수도 있습니다.",
    regression: "반응마다 평균·선형·2요인 교호작용·2차 모형을 순차 F 검정과 예측 R²로 비교해 제안합니다. 다른 모형을 고를 수도 있습니다.",
    surface: "선택한 회귀식으로 그린 반응 곡면입니다. 점은 실험값, 세로줄은 잔차입니다. [확인]을 누르면 그림이 보고서에 들어갑니다.",
    anova: "선택 모형의 분산분석(부분 제곱합)입니다. 확인하면 모든 단계가 끝나고 최종 보고서를 받을 수 있습니다.",
  };

  let V = null;            // 지금 study의 view
  let sec = null;          // 대화 속 2단계 영역
  let busy = false;
  let surf = { slice: null };

  const note = (m, k = "info") => { const n = $("notice"); if (!n) return; n.hidden = false; n.className = `notice ${k}`; n.textContent = m; };
  const key = () => `s2-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

  async function req(path, opts = {}) {
    const res = await fetch(api(path), {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json", "Idempotency-Key": key(), "X-F1-LLM": (window.F1LLM && window.F1LLM.get()) || "groq", ...(opts.headers || {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const d = await res.json().catch(() => ({}));
    if (!res.ok) {
      const m = d.detail && (d.detail.message || (typeof d.detail === "string" ? d.detail : "")) || `요청 실패 (${res.status})`;
      throw new Error(m);
    }
    return d;
  }

  // ── 시작 ────────────────────────────────────────────────────────────────
  async function create(body, say) {
    if (window.F1Agent) window.F1Agent.dock();
    const v = await req("/api/stage2/studies", { method: "POST", body });
    if (window.F1Agent && say) window.F1Agent.say("agent", { reply: say, proposals: [], source: "context" });
    mount(v);
    document.dispatchEvent(new CustomEvent("f1:stage2", { detail: { id: v.study.study_id } }));
    return v;
  }
  async function startFromCandidate(runId, cid) {
    try {
      return await create({ source: "candidate", run_id: runId, candidate_id: cid },
        `후보 ${cid}를 프로토타입으로 받아 2단계를 시작합니다. 처방을 확인하고 [실행]을 누르면 QTPP → CQA → 위험평가 → DoE → 회귀식 → 반응 곡면 → ANOVA로 이어집니다.`);
    } catch (e) { note(e.message, "error"); throw e; }
  }
  async function startCbd() {
    if (window.F1Agent) window.F1Agent.say("user", "시연 — CBD 구강붕해정으로 2단계(QTPP부터 ANOVA까지) 진행");
    try {
      return await create({ source: "cbd_paper" },
        "Monton 2026(CBD 구강붕해정) Table 1의 처방을 프로토타입으로 2단계를 시작합니다. 단계마다 LLM 초안을 받거나 논문 값으로 채워 비교할 수 있습니다.");
    } catch (e) { note(e.message, "error"); }
  }
  async function open(id) {
    try {
      if (window.F1Agent) window.F1Agent.dock();
      mount(await req(`/api/stage2/studies/${encodeURIComponent(id)}`));
    } catch (e) { note(e.message, "error"); }
  }

  function mount(v) {
    V = v;
    surf = { slice: null };
    const id = v.study.study_id;
    // 같은 study가 이미 대화에 있으면 그 자리를 쓰고, 다른 study 영역은 읽기 전용 기록으로 얼린다
    if (sec && sec.dataset.study !== id) {
      window.F1Surfaces && window.F1Surfaces.purge();
      sec.querySelectorAll("button, input, select, textarea").forEach((x) => { x.disabled = true; });
      sec.classList.add("frozen");
      sec.removeAttribute("id");
      sec = null;
    }
    if (!sec) {
      sec = document.createElement("section");
      sec.className = "s2";
      sec.id = "s2";
      sec.dataset.study = id;
      window.F1Flow.sysMsg("2단계 · Design Space 도출", sec, "wide");
    }
    render(true);
  }

  // ── 그리기 ──────────────────────────────────────────────────────────────
  function render(scroll) {
    const st = V.study;
    const done = V.steps.filter((s) => s.status === "approved").length;
    sec.innerHTML = `<header class="s2-head">
        <div><b>${E(st.title)}</b><small>${E(st.study_id)}${st.reference ? ` · 논문 비교: ${E(V.reference_citation || "")}` : ""}</small></div>
        <div class="s2-prog" aria-label="진행 ${done}/12"><i style="width:${(done / 12) * 100}%"></i></div>
        <span class="s2-count">${V.done ? "완료" : `${done} / 12`}</span>
      </header>
      <ol class="s2-steps">${V.steps.filter((s) => s.status !== "empty" || s.key === V.current).map(stepCard).join("")}</ol>
      ${links()}`;
    wire();
    const cur = sec.querySelector(".s2-step.current");
    if (scroll && cur) cur.scrollIntoView({ behavior: "smooth", block: "start" });
    if (V.current === "surface" && !V.done) drawSurfaces();
  }

  function links() {
    const id = encodeURIComponent(V.study.study_id);
    const rec = V.study.steps.recommend.status === "approved";
    if (!rec) return "";
    return `<div class="s2-links">
      <a class="s2-file" href="${E(api(`/api/stage2/studies/${id}/risk-report.pdf`))}" target="_blank" rel="noopener">위험평가 보고서 PDF</a>
      ${V.done ? `<a class="s2-file primary" href="${E(api(`/api/stage2/studies/${id}/report.pdf`))}" target="_blank" rel="noopener">최종 보고서 PDF</a>` : ""}
    </div>`;
  }

  function stepCard(meta) {
    const s = V.study.steps[meta.key];
    const cur = meta.key === V.current && !V.done;
    const badge = s.status === "approved" ? `<span class="s2-badge ok">승인</span>`
      : s.status === "stale" ? `<span class="s2-badge warn">다시 확인 필요</span>` : cur ? `<span class="s2-badge now">진행 중</span>` : "";
    const src = s.source ? `<span class="s2-src">${E(s.source.split("+").map((x) => (x === "upstream" && (V.study.origin || {}).kind === "cbd_paper" ? "논문 Table 1" : SRC[x] || x)).join(" → "))}${s.llm && s.llm.provider ? ` · ${E(s.llm.provider)}` : ""}</span>` : "";
    const head = `<span class="s2-n">${meta.n}</span><span class="s2-ttl">${E(meta.title)}</span>${meta.table ? `<small class="s2-tab">${E(meta.table)}</small>` : ""}${badge}${src}`;
    if (!cur) {
      return `<li class="s2-step ${E(s.status)}" data-step="${E(meta.key)}"><details><summary>${head}</summary>
        <div class="s2-body">${s.data ? view(meta.key, s.data, true) : `<p class="s2-muted">내용 없음</p>`}
        ${s.status === "approved" && !busy ? `<div class="s2-actions"><button type="button" class="ghost" data-act="reopen" data-step="${E(meta.key)}">이 단계 다시 열기</button></div>` : ""}</div></details></li>`;
    }
    return `<li class="s2-step current" data-step="${E(meta.key)}"><div class="s2-card">
      <div class="s2-card-head">${head}</div>
      <p class="s2-hint">${E(HINT[meta.key] || "")}</p>
      <div class="s2-body" data-edit="${E(meta.key)}">${s.data ? view(meta.key, s.data, false) : empty(meta)}</div>
      ${checks(s.checks)}
      ${refBox(meta.key)}
      <div class="s2-actions">${actions(meta, s)}</div>
      <div class="s2-out" role="status"></div>
    </div></li>`;
  }

  function empty(meta) {
    return meta.llm ? `<p class="s2-empty">아직 초안이 없습니다 — <b>LLM 초안 받기</b>를 누르거나${V.study.reference ? " <b>논문 값으로 채우기</b>를 누르거나" : ""} 직접 행을 추가하세요.</p>${view(meta.key, blank(meta.key), false)}`
      : `<p class="s2-muted">계산할 내용이 없습니다.</p>`;
  }
  function blank(k) {
    if (k === "qtpp" || k === "cqa") return { items: [] };
    if (k === "rm_just" || k === "fp_just") return { variables: [], items: [] };
    return {};
  }

  function checks(list) {
    if (!list || !list.length) return "";
    return `<ul class="s2-checks">${list.map((c) => `<li class="${E(c.level)}"><b>${c.level === "blocking" ? "승인 불가" : "주의"}</b> ${E(c.message)} <code>${E(c.code)}</code></li>`).join("")}</ul>`;
  }

  function actions(meta, s) {
    const k = meta.key, b = [];
    const dis = busy ? "disabled" : "";
    if (k === "prototype") b.push(`<button type="button" class="primary" data-act="run" ${dis}>실행</button>`);
    if (meta.llm) b.push(`<button type="button" data-act="draft" ${dis}>${k === "recommend" ? "LLM 추천 받기" : s.data ? "LLM 초안 다시 받기" : "LLM 초안 받기"}</button>`);
    if (V.study.reference && ["qtpp", "cqa", "rm_just", "fp_just", "recommend", "design", "regression"].includes(k))
      b.push(`<button type="button" class="ghost" data-act="use_reference" ${dis}>논문 값으로 채우기</button>`);
    if (meta.editable && k !== "prototype") b.push(`<button type="button" class="ghost" data-act="save" ${dis}>저장</button>`);
    if (k !== "prototype") {
      const label = meta.derived ? (k === "anova" ? "확인 · 최종 보고서 만들기" : "확인") : k === "recommend" ? "승인 · 위험평가 보고서" : "승인";
      b.push(`<button type="button" class="primary" data-act="approve" ${dis}>${label}</button>`);
    }
    return b.join("");
  }

  // 논문(CBD) 값과 비교 — 논문으로 시작한 study에서만
  function refBox(k) {
    const R = V.reference;
    if (!R || !R[k] || ["prototype", "recommend", "regression", "design"].includes(k)) return "";
    return `<details class="s2-ref"><summary>논문 표와 비교 (${E(({ qtpp: "Table 3", cqa: "Table 4", rm_just: "Table 6", rm_matrix: "Table 5", fp_just: "Table 8", fp_matrix: "Table 7" })[k] || "")})</summary>
      <div class="s2-body">${view(k, R[k], true, true)}</div></details>`;
  }

  // ── 단계별 내용 — ro(읽기 전용)면 입력 대신 글 ──────────────────────────
  const inp = (v, a, ro, w = "") => ro ? `<span>${E(v ?? "")}</span>` : `<input ${a} value="${E(v ?? "")}" ${w}>`;
  const txt = (v, a, ro) => ro ? `<span class="s2-pre">${E(v ?? "")}</span>` : `<textarea ${a} rows="2">${E(v ?? "")}</textarea>`;
  const sel = (v, opts, a, ro, blankLabel = "—") => ro ? `<span>${E(v ?? "")}</span>`
    : `<select ${a}><option value="">${E(blankLabel)}</option>${opts.map((o) => `<option ${o === v ? "selected" : ""}>${E(o)}</option>`).join("")}</select>`;
  const chk = (v, a, ro) => ro ? (v ? "예" : "아니오") : `<input type="checkbox" ${a} ${v ? "checked" : ""}>`;
  const del = (ro) => ro ? "" : `<td class="s2-x"><button type="button" class="icon-btn" data-row-del aria-label="행 삭제">✕</button></td>`;
  const lv = (x) => x ? `<span class="lv lv-${E(String(x).toLowerCase())}">${E(x)}</span>` : `<span class="lv lv-none">—</span>`;

  function view(k, d, ro, isRef = false) {
    switch (k) {
      case "prototype": return vPrototype(d, ro);
      case "qtpp": return vQtpp(d, ro);
      case "cqa": return vCqa(d, ro);
      case "rm_just": case "fp_just": return vJust(k, d, ro, isRef);
      case "rm_matrix": case "fp_matrix": return vMatrix(d, isRef ? null : V.reference && V.reference[k]);
      case "recommend": return vRecommend(d, ro);
      case "design": return vDesign(d, ro);
      case "regression": return vRegression(d, ro);
      case "surface": return ro ? `<p class="s2-muted">반응 ${E((d.responses || []).join(", "))}의 곡면 — 보고서에 그림으로 들어갔습니다.</p>` : `<div class="s2-surf" id="s2-surf-box"><p class="s2-muted">곡면을 계산하는 중…</p></div>`;
      case "anova": return vAnova(d);
      default: return "";
    }
  }

  function vPrototype(d, ro) {
    const f = (label, name, v) => `<label class="s2-f"><span>${E(label)}</span>${inp(v, `data-f="${name}"`, ro)}</label>`;
    return `<div class="s2-grid">${f("주성분", "api", d.api)}${f("제형", "dosage_form", d.dosage_form)}${f("투여 경로", "route", d.route)}
        ${f("공정", "process", d.process)}${f("함량 (mg)", "strength_mg", d.strength_mg)}${f("1정 무게 (mg)", "unit_weight_mg", d.unit_weight_mg)}</div>
      <div class="s2-scroll"><table class="s2-t" data-rows="ingredients"><thead><tr><th>성분</th><th>mg / 정</th><th>%</th><th>기능</th><th>역할</th>${ro ? "" : "<th></th>"}</tr></thead>
      <tbody>${(d.ingredients || []).map((i) => `<tr>
        <td>${inp(i.name, 'data-k="name"', ro)}</td><td class="n">${inp(i.mg, 'data-k="mg" inputmode="decimal"', ro)}</td><td class="n">${inp(i.pct, 'data-k="pct" inputmode="decimal"', ro)}</td>
        <td>${inp(i.function, 'data-k="function"', ro)}</td><td>${inp(i.role, 'data-k="role" list="s2-roles"', ro)}</td>${del(ro)}</tr>`).join("")}
      </tbody>${ro ? "" : `<tfoot><tr><td colspan="6"><button type="button" class="ghost sm" data-row-add="ingredients">+ 성분</button></td></tr></tfoot>`}</table></div>
      ${(d.process_steps || []).length || !ro ? `<label class="s2-f wide"><span>공정 단계(줄마다 하나)</span>${ro ? `<span class="s2-pre">${E((d.process_steps || []).join(" → "))}</span>`
        : `<textarea data-f="process_steps" rows="2">${E((d.process_steps || []).join("\n"))}</textarea>`}</label>` : ""}
      <datalist id="s2-roles">${["api", "filler", "filler_binder", "binder", "disintegrant", "glidant", "lubricant", "sweetener", "flavor", "solubilizer", "surfactant", "coating"].map((r) => `<option value="${r}">`).join("")}</datalist>`;
  }

  function vQtpp(d, ro) {
    return `<div class="s2-scroll"><table class="s2-t" data-rows="items"><thead><tr><th>QTPP 요소</th><th>하위 항목</th><th>목표</th><th>근거</th><th>근거 유형</th>${ro ? "" : "<th></th>"}</tr></thead>
      <tbody>${(d.items || []).map((i) => `<tr><td>${inp(i.element, 'data-k="element"', ro)}</td><td>${inp(i.sub_element, 'data-k="sub_element"', ro)}</td>
        <td>${txt(i.target, 'data-k="target"', ro)}</td><td>${txt(i.justification, 'data-k="justification"', ro)}</td>
        <td>${sel(i.basis, BASIS, 'data-k="basis"', ro)}</td>${del(ro)}</tr>`).join("")}</tbody>
      ${ro ? "" : `<tfoot><tr><td colspan="6"><button type="button" class="ghost sm" data-row-add="items">+ 요소</button></td></tr></tfoot>`}</table></div>`;
  }

  function vCqa(d, ro) {
    return `<div class="s2-scroll"><table class="s2-t" data-rows="items"><thead><tr><th>분류</th><th>품질특성</th><th>짧은 이름</th><th>목표</th><th>CQA</th><th>근거</th><th>위험평가</th><th>제외 이유</th><th>근거 유형</th>${ro ? "" : "<th></th>"}</tr></thead>
      <tbody>${(d.items || []).map((i) => `<tr class="${i.in_risk_assessment ? "in" : ""}"><td>${inp(i.category, 'data-k="category"', ro)}</td><td>${inp(i.attribute, 'data-k="attribute"', ro)}</td>
        <td>${inp(i.short, 'data-k="short"', ro)}</td><td>${txt(i.target, 'data-k="target"', ro)}</td><td class="c">${chk(i.is_cqa, 'data-k="is_cqa"', ro)}</td>
        <td>${txt(i.justification, 'data-k="justification"', ro)}</td><td class="c">${chk(i.in_risk_assessment, 'data-k="in_risk_assessment"', ro)}</td>
        <td>${txt(i.exclusion_reason, 'data-k="exclusion_reason"', ro)}</td><td>${sel(i.basis, BASIS, 'data-k="basis"', ro)}</td>${del(ro)}</tr>`).join("")}</tbody>
      ${ro ? "" : `<tfoot><tr><td colspan="10"><button type="button" class="ghost sm" data-row-add="items">+ 품질특성</button></td></tr></tfoot>`}</table></div>`;
  }

  function riskCqas() {
    return ((V.study.steps.cqa.data || {}).items || []).filter((c) => c.in_risk_assessment).map((c) => c.short);
  }

  function vJust(k, d, ro, isRef) {
    const cqas = isRef ? [...new Set((d.items || []).flatMap((i) => i.cqas))] : riskCqas();
    const kinds = k === "rm_just" ? ["material"] : ["formulation", "process"];
    const KIND = { material: "원료 물성", formulation: "제형 변수", process: "공정 변수" };
    const vars = d.variables || [];
    const names = vars.map((v) => v.name);
    const varBox = ro ? (vars.length ? `<p class="s2-vars">${vars.map((v) => `<span class="chip">${E(v.name)}<small>${E(KIND[v.kind] || v.kind || "")}</small></span>`).join("")}</p>` : "")
      : `<div class="s2-vars edit" data-vars>${vars.map((v) => `<span class="chip" data-var><input data-k="name" value="${E(v.name)}" aria-label="변수 이름">
          ${kinds.length > 1 ? `<select data-k="kind">${kinds.map((x) => `<option value="${x}" ${x === v.kind ? "selected" : ""}>${KIND[x]}</option>`).join("")}</select>` : `<input type="hidden" data-k="kind" value="${kinds[0]}">`}
          <button type="button" class="icon-btn" data-var-del aria-label="변수 삭제">✕</button></span>`).join("")}
          <button type="button" class="ghost sm" data-var-add>+ 변수</button></div>`;
    const rows = (d.items || []).map((i) => `<tr><td>${ro ? `<b>${E(i.variable)}</b>` : sel(i.variable, names, 'data-k="variable"', false, "변수")}</td>
      <td>${ro ? E((i.cqas || []).join(", ")) : `<div class="s2-cq">${cqas.map((c) => `<label><input type="checkbox" data-cqa="${E(c)}" ${(i.cqas || []).includes(c) ? "checked" : ""}>${E(c)}</label>`).join("")}</div>`}</td>
      <td class="c">${ro ? lv(i.level) : sel(i.level, LEVELS, 'data-k="level"', false, "등급")}</td>
      <td>${txt(i.text, 'data-k="text"', ro)}</td><td>${sel(i.basis, BASIS, 'data-k="basis"', ro)}</td>${del(ro)}</tr>`).join("");
    return `${varBox}<div class="s2-scroll"><table class="s2-t just" data-rows="items"><thead><tr><th>변수</th><th>CQA</th><th>위험</th><th>근거(기전)</th><th>근거 유형</th>${ro ? "" : "<th></th>"}</tr></thead>
      <tbody>${rows}</tbody>${ro ? "" : `<tfoot><tr><td colspan="6"><button type="button" class="ghost sm" data-row-add="items">+ 근거 행</button>
        <button type="button" class="ghost sm" data-fill-missing>빈 칸(변수 × CQA) 행 만들기</button></td></tr></tfoot>`}</table></div>`;
  }

  function vMatrix(d, ref) {
    const refCell = (c, v) => {
      if (!ref) return undefined;
      const i = ref.cqas.indexOf(c), j = ref.variables.findIndex((x) => x.name === v);
      return i < 0 || j < 0 ? null : ref.levels[i][j];
    };
    let diff = 0;
    const body = d.cqas.map((c, i) => `<tr><th>${E(c)}</th>${d.variables.map((v, j) => {
      const r = refCell(c, v.name), x = d.levels[i][j];
      const off = r !== undefined && r !== null && r !== x;
      if (off) diff += 1;
      return `<td class="c${off ? " off" : ""}" ${off ? `title="논문: ${E(r)}"` : ""}>${lv(x)}${off ? `<small>논문 ${E(r)}</small>` : ""}</td>`;
    }).join("")}</tr>`).join("");
    return `<div class="s2-scroll"><table class="s2-t matrix"><thead><tr><th>CQA \\ 변수</th>${d.variables.map((v) => `<th>${E(v.name)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>
      ${ref ? `<p class="s2-cmp">${diff ? `논문 표와 다른 칸 ${diff}개(테두리 표시)` : "논문 표와 모든 칸이 같습니다."}</p>` : ""}`;
  }

  function vRecommend(d, ro) {
    const rm = V.study.steps.rm_matrix.data, fp = V.study.steps.fp_matrix.data;
    const cq = (fp || rm || { cqas: [] }).cqas;
    const cell = (m, c, j) => { const i = m.cqas.indexOf(c); return i < 0 ? null : m.levels[i][j]; };
    const merged = rm && fp ? `<div class="s2-scroll"><table class="s2-t matrix merged"><thead>
        <tr><th rowspan="2">CQA</th><th colspan="${rm.variables.length}" class="grp">원료 물성</th><th colspan="${fp.variables.length}" class="grp">제형 · 공정 변수</th></tr>
        <tr>${rm.variables.map((v) => `<th>${E(v.name)}</th>`).join("")}${fp.variables.map((v) => `<th>${E(v.name)}</th>`).join("")}</tr></thead>
      <tbody>${cq.map((c) => `<tr><th>${E(c)}</th>${rm.variables.map((_, j) => `<td class="c">${lv(cell(rm, c, j))}</td>`).join("")}${fp.variables.map((_, j) => `<td class="c">${lv(cell(fp, c, j))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "";
    const recBy = Object.fromEntries((d.recommended || []).map((r) => [r.variable, r.reason]));
    const selSet = new Set(d.selected || []);
    const cands = (d.candidates || []).map((c) => `<li class="${selSet.has(c.variable) ? "on" : ""}"><label>
        ${ro ? (selSet.has(c.variable) ? "✓" : "") : `<input type="checkbox" data-pick="${E(c.variable)}" ${selSet.has(c.variable) ? "checked" : ""}>`}
        <b>${E(c.variable)}</b> <small>${E(c.kind === "process" ? "공정" : "제형")}</small>
        ${c.high.length ? `<span class="lv lv-high">High</span> ${E(c.high.join(", "))}` : ""} ${c.medium.length ? `<span class="lv lv-medium">Medium</span> ${E(c.medium.join(", "))}` : ""}</label>
        ${recBy[c.variable] ? `<p class="s2-why">${d.rec_source === "paper" ? "논문" : "추천"} — ${E(recBy[c.variable])}</p>` : ""}</li>`).join("");
    const mc = (d.material_controls || []).filter((c) => c.high.length);
    return `<h4 class="s2-h">종합 위험평가 (Table 5 + Table 7)</h4>${merged}
      <h4 class="s2-h">DoE 변수 후보 <small>High·Medium인 제형·공정 변수 · 최대 4개 선택 · 선택 ${selSet.size}개</small></h4>
      <p class="s2-muted">규칙 순위(High 개수 순): ${E((d.rule_rank || []).join(" › ") || "—")}</p>
      <ul class="s2-cands">${cands || `<li class="s2-muted">후보가 없습니다 — 6단계의 등급을 확인하세요.</li>`}</ul>
      ${d.note ? `<p class="s2-note">${E(d.note)}</p>` : ""}
      ${mc.length ? `<p class="s2-muted">원료 물성 중 High — DoE 대신 원료 규격으로 관리: ${E(mc.map((c) => `${c.variable}(${c.high.join(", ")})`).join(" · "))}</p>` : ""}`;
  }

  function vDesign(d, ro) {
    const F = d.factors || [], R = d.responses || [];
    const colHead = (x, kind, i) => ro ? `<th class="${kind}">${E(x.name)}${x.unit ? `<small>${E(x.unit)}</small>` : ""}</th>`
      : `<th class="${kind}"><div class="s2-colh"><input data-col="${kind}" data-i="${i}" data-k="name" value="${E(x.name)}" placeholder="${kind === "f" ? "요인" : "반응"} 이름" aria-label="${kind === "f" ? "요인" : "반응"} ${i + 1} 이름">
        <button type="button" class="icon-btn" data-col-del="${kind}" data-i="${i}" aria-label="열 삭제" ${(kind === "f" ? F : R).length <= 1 ? "disabled" : ""}>✕</button>
        <input data-col="${kind}" data-i="${i}" data-k="unit" value="${E(x.unit)}" placeholder="단위" class="unit" aria-label="단위"></div></th>`;
    const cellI = (v, a) => ro ? `<td class="n">${E(v ?? "")}</td>` : `<td class="n"><input ${a} value="${E(v ?? "")}" inputmode="decimal"></td>`;
    return `<div class="s2-scroll"><table class="s2-t design" data-rows="rows"><thead>
        <tr><th rowspan="2">Std</th><th rowspan="2">Run</th><th colspan="${F.length + (ro ? 0 : 1)}" class="grp">요인 (Factors)</th><th colspan="${R.length + (ro ? 0 : 1)}" class="grp">반응 (Responses)</th>${ro ? "" : "<th rowspan=\"2\"></th>"}</tr>
        <tr>${F.map((x, i) => colHead(x, "f", i)).join("")}${ro ? "" : `<th class="add"><button type="button" class="ghost sm" data-col-add="f" ${F.length >= 3 ? "disabled" : ""} aria-label="요인 추가">+</button></th>`}
          ${R.map((x, i) => colHead(x, "r", i)).join("")}${ro ? "" : `<th class="add"><button type="button" class="ghost sm" data-col-add="r" ${R.length >= 4 ? "disabled" : ""} aria-label="반응 추가">+</button></th>`}</tr></thead>
      <tbody>${(d.rows || []).map((r) => `<tr>${cellI(r.std, 'data-k="std"')}${cellI(r.run, 'data-k="run"')}
        ${F.map((_, i) => cellI((r.x || [])[i], `data-x="${i}"`)).join("")}${ro ? "" : "<td></td>"}
        ${R.map((_, i) => cellI((r.y || [])[i], `data-y="${i}"`)).join("")}${ro ? "" : "<td></td>"}${del(ro)}</tr>`).join("")}</tbody>
      ${ro ? "" : `<tfoot><tr><td colspan="${F.length + R.length + 5}"><button type="button" class="ghost sm" data-row-add="rows">+ 행</button>
        <button type="button" class="ghost sm" data-rows-add5>+ 5행</button></td></tr></tfoot>`}</table></div>
      ${ro ? "" : `<details class="s2-paste"><summary>엑셀에서 붙여넣기</summary>
        <p class="s2-muted">열 순서: Std · Run · 요인 ${F.length}개 · 반응 ${R.length}개 (탭 또는 쉼표로 구분, 머리글 행은 건너뜀). 지금 표의 행을 바꿉니다.</p>
        <textarea data-paste rows="5" placeholder="1&#9;5&#9;..."></textarea><button type="button" class="ghost sm" data-paste-apply>표에 넣기</button></details>`}
      ${d.note ? `<p class="s2-note">${E(d.note)}</p>` : ""}`;
  }

  function vRegression(d, ro) {
    return (d.responses || []).map((r) => {
      const fams = r.summary.rows.filter((x) => x.model !== "Mean" && !x.aliased).map((x) => x.model);
      return `<div class="s2-reg" data-resp="${E(r.response)}"><div class="s2-reg-head"><b>${E(r.response)}</b>${r.unit ? `<small>${E(r.unit)}</small>` : ""}
          <span class="s2-muted">n = ${E(r.n)}</span>
          <label>모형 ${ro ? `<b>${E(FAMILY_KO[r.family] || r.family)}</b>` : `<select data-family>${fams.map((f) => `<option value="${E(f)}" ${f === r.family ? "selected" : ""}>${E(FAMILY_KO[f] || f)}${f === r.suggested ? " (제안)" : ""}</option>`).join("")}</select>`}</label></div>
        <div class="s2-scroll"><table class="s2-t fit"><thead><tr><th>모형</th><th>순차 p</th><th>적합결여 p</th><th>R²</th><th>수정 R²</th><th>예측 R²</th><th></th></tr></thead>
          <tbody>${r.summary.rows.map((x) => `<tr class="${x.model === r.family ? "chosen" : ""}"><td>${E(FAMILY_KO[x.model] || x.model)}</td>
            ${x.aliased ? `<td colspan="5" class="s2-muted">추정 불가(항 수 ≥ run 수)</td>` : `<td class="n">${E(pfmt(x.seq_p))}</td><td class="n">${E(pfmt(x.lof_p))}</td>
            <td class="n">${E(num(x.r2))}</td><td class="n">${E(num(x.adj_r2))}</td><td class="n">${E(num(x.pred_r2))}</td>`}
            <td>${x.suggested ? "제안" : ""}</td></tr>`).join("")}</tbody></table></div>
        <p class="s2-muted">${E(r.reason)}</p>
        ${r.aliased ? `<p class="s2-warn">이 모형은 이 설계로 추정할 수 없습니다 — 더 낮은 차수를 고르세요.</p>` : `<dl class="s2-eq"><dt>Coded</dt><dd><code>${E(r.coded_eq)}</code></dd>
          <dt>Actual</dt><dd><code>${E(r.actual_eq)}</code></dd><dt>적합</dt><dd>R² ${E(num(r.r2))} · 수정 R² ${E(num(r.adj_r2))} · 예측 R² ${E(num(r.pred_r2))}</dd></dl>`}
        ${V.reference && V.reference.regression && V.reference.regression.families[r.response] ? `<p class="s2-cmp">논문 모형: ${E(FAMILY_KO[V.reference.regression.families[r.response]] || V.reference.regression.families[r.response])}</p>` : ""}
      </div>`;
    }).join("") + `<p class="s2-muted">요인 기호: ${(d.factors || []).map((f, i) => `X${i + 1} = ${E(f.name)}${f.unit ? ` (${E(f.unit)})` : ""} [${E(num(f.low))} – ${E(num(f.high))}]`).join(" · ")}</p>`;
  }

  function vAnova(d) {
    return (d.responses || []).map((r) => r.aliased ? `<p class="s2-warn">${E(r.response)}: 모형을 추정할 수 없습니다.</p>` : `<div class="s2-reg"><div class="s2-reg-head"><b>${E(r.response)}</b>
        <span class="s2-muted">${E(FAMILY_KO[r.family] || r.family)} 모형</span></div>
      <div class="s2-scroll"><table class="s2-t anova"><thead><tr><th>Source</th><th>Sum of squares</th><th>df</th><th>Mean square</th><th>F</th><th>p</th></tr></thead>
        <tbody>${r.rows.map((x) => `<tr class="lvl${x.level}${x.p != null && x.p < 0.05 ? " sig" : ""}"><td>${E(x.source)}</td><td class="n">${E(num(x.ss))}</td><td class="n">${E(x.df)}</td>
          <td class="n">${E(x.ms != null ? num(x.ms) : "")}</td><td class="n">${E(x.f != null ? num(x.f) : "")}</td><td class="n">${E(pfmt(x.p))}</td></tr>`).join("")}</tbody></table></div>
      <p class="s2-muted">R² ${E(num(r.r2))} · 수정 R² ${E(num(r.adj_r2))} · 예측 R² ${E(num(r.pred_r2))} · 표준편차 ${E(num(r.std_dev))} · 평균 ${E(num(r.mean))} · CV ${E(num(r.cv_pct, 3))}% — p &lt; 0.05 굵게</p></div>`).join("");
  }

  // ── 편집 → 데이터 ───────────────────────────────────────────────────────
  function collect(k, box) {
    const q = (s) => [...box.querySelectorAll(s)];
    const val = (el) => (el.type === "checkbox" ? el.checked : el.value);
    const rowObjs = (tbl) => q(`table[data-rows="${tbl}"] tbody tr`).map((tr) => {
      const o = {};
      tr.querySelectorAll("[data-k]").forEach((el) => { o[el.dataset.k] = val(el); });
      return { o, tr };
    });
    if (k === "prototype") {
      const o = {};
      q("[data-f]").forEach((el) => { o[el.dataset.f] = el.value; });
      o.process_steps = (o.process_steps || "").split("\n").map((s) => s.trim()).filter(Boolean);
      o.ingredients = rowObjs("ingredients").map((r) => r.o);
      o.source = (V.study.steps.prototype.data || {}).source;
      return o;
    }
    if (k === "qtpp" || k === "cqa") return { items: rowObjs("items").map((r) => r.o) };
    if (k === "rm_just" || k === "fp_just") {
      const variables = q("[data-var]").map((c) => ({ name: c.querySelector('[data-k="name"]').value.trim(), kind: c.querySelector('[data-k="kind"]').value }));
      const items = rowObjs("items").map(({ o, tr }) => ({ ...o, cqas: [...tr.querySelectorAll("[data-cqa]:checked")].map((x) => x.dataset.cqa) }));
      return { variables, items };
    }
    if (k === "recommend") return { selected: q("[data-pick]:checked").map((x) => x.dataset.pick) };
    if (k === "design") return collectDesign(box);
    if (k === "regression") return { chosen: Object.fromEntries(q(".s2-reg").map((r) => [r.dataset.resp, r.querySelector("[data-family]").value])) };
    return {};
  }

  function collectDesign(box) {
    const col = (kind) => {
      const out = [];
      box.querySelectorAll(`[data-col="${kind}"]`).forEach((el) => {
        const i = Number(el.dataset.i);
        out[i] = out[i] || { name: "", unit: "" };
        out[i][el.dataset.k] = el.value;
      });
      return out;
    };
    const factors = col("f"), responses = col("r");
    const rows = [...box.querySelectorAll('table[data-rows="rows"] tbody tr')].map((tr) => ({
      std: tr.querySelector('[data-k="std"]').value, run: tr.querySelector('[data-k="run"]').value,
      x: factors.map((_, i) => tr.querySelector(`[data-x="${i}"]`).value),
      y: responses.map((_, i) => tr.querySelector(`[data-y="${i}"]`).value),
    }));
    return { factors, responses, rows };
  }

  // 표 모양을 바꾸는 편집(열·행 추가/삭제, 붙여넣기)은 모아 둔 값으로 다시 그린다 — 저장 전까지는 화면에만 있다
  function redrawEdit(k, data) {
    const box = sec.querySelector(`[data-edit="${k}"]`);
    box.innerHTML = view(k, data, false);
    box.dataset.dirty = "1";
    wireEdit(k, box);
  }

  function wireEdit(k, box) {
    box.addEventListener("input", () => { box.dataset.dirty = "1"; }, { once: false });
    box.addEventListener("change", () => { box.dataset.dirty = "1"; });
    box.querySelectorAll("[data-row-del]").forEach((b) => { b.onclick = () => { b.closest("tr").remove(); box.dataset.dirty = "1"; }; });
    box.querySelectorAll("[data-row-add]").forEach((b) => {
      b.onclick = () => {
        const d = collect(k, box);
        if (k === "prototype") d.ingredients.push({ name: "", mg: "", pct: "", function: "", role: "" });
        else if (k === "design") d.rows.push(newRow(d, 1));
        else if (k === "rm_just" || k === "fp_just") d.items.push({ variable: "", cqas: [], level: "", text: "", basis: "" });
        else d.items.push({});
        redrawEdit(k, d);
      };
    });
    const add5 = box.querySelector("[data-rows-add5]");
    if (add5) add5.onclick = () => { const d = collect(k, box); for (let i = 0; i < 5; i++) d.rows.push(newRow(d, i + 1)); redrawEdit(k, d); };
    box.querySelectorAll("[data-var-add]").forEach((b) => {
      b.onclick = () => { const d = collect(k, box); d.variables.push({ name: "", kind: k === "rm_just" ? "material" : "formulation" }); redrawEdit(k, d); };
    });
    box.querySelectorAll("[data-var-del]").forEach((b) => {
      b.onclick = () => {
        const chip = b.closest("[data-var]");
        const name = chip.querySelector('[data-k="name"]').value.trim();
        chip.remove();
        const d = collect(k, box);
        d.items = d.items.filter((i) => i.variable !== name);
        redrawEdit(k, d);
      };
    });
    const fill = box.querySelector("[data-fill-missing]");
    if (fill) fill.onclick = () => {
      const d = collect(k, box);
      const cq = riskCqas();
      const have = new Set(d.items.flatMap((i) => i.cqas.map((c) => `${i.variable}\u0000${c}`)));
      let added = 0;
      d.variables.filter((v) => v.name).forEach((v) => {
        const miss = cq.filter((c) => !have.has(`${v.name}\u0000${c}`));
        if (miss.length) { d.items.push({ variable: v.name, cqas: miss, level: "", text: "", basis: "" }); added += 1; }
      });
      redrawEdit(k, d);
      out(added ? `빈 칸을 덮는 행 ${added}개를 만들었습니다 — 등급과 근거를 적고, 판단이 다른 CQA는 체크를 풀어 다른 행으로 나누세요.` : "빈 칸이 없습니다.");
    };
    box.querySelectorAll("[data-col-add]").forEach((b) => {
      b.onclick = () => {
        const d = collectDesign(box);
        if (b.dataset.colAdd === "f") { d.factors.push({ name: "", unit: "" }); d.rows.forEach((r) => r.x.push("")); }
        else { d.responses.push({ name: "", unit: "" }); d.rows.forEach((r) => r.y.push("")); }
        redrawEdit(k, d);
      };
    });
    box.querySelectorAll("[data-col-del]").forEach((b) => {
      b.onclick = () => {
        const d = collectDesign(box), i = Number(b.dataset.i);
        if (b.dataset.colDel === "f") { d.factors.splice(i, 1); d.rows.forEach((r) => r.x.splice(i, 1)); }
        else { d.responses.splice(i, 1); d.rows.forEach((r) => r.y.splice(i, 1)); }
        redrawEdit(k, d);
      };
    });
    const pa = box.querySelector("[data-paste-apply]");
    if (pa) pa.onclick = () => {
      const d = collectDesign(box);
      const w = 2 + d.factors.length + d.responses.length;
      const lines = box.querySelector("[data-paste]").value.split(/\r?\n/).map((l) => l.split(/\t|,/).map((c) => c.trim())).filter((c) => c.length >= w - 1 && c.some(Boolean));
      const rows = lines.filter((c) => Number.isFinite(Number(c[0])) && c[0] !== "").map((c) => ({
        std: c[0], run: c[1], x: d.factors.map((_, i) => c[2 + i] ?? ""), y: d.responses.map((_, i) => c[2 + d.factors.length + i] ?? ""),
      }));
      if (!rows.length) { out(`열 ${w}개(Std · Run · 요인 · 반응)인 숫자 행을 찾지 못했습니다.`, "warn"); return; }
      d.rows = rows;
      redrawEdit(k, d);
      out(`${rows.length}개 행을 넣었습니다 — 저장하면 서버가 검사합니다.`);
    };
    box.querySelectorAll("[data-pick]").forEach((c) => {
      c.onchange = () => {
        const n = box.querySelectorAll("[data-pick]:checked").length;
        if (n > 4) { c.checked = false; out("DoE 변수는 최대 4개입니다.", "warn"); }
      };
    });
  }

  function newRow(d, add) {
    const n = d.rows.length + add;
    return { std: n, run: n, x: d.factors.map(() => ""), y: d.responses.map(() => "") };
  }

  // ── 행동 ────────────────────────────────────────────────────────────────
  function out(msg, kind = "") {
    const o = sec && sec.querySelector(".s2-step.current .s2-out");
    if (o) { o.className = `s2-out ${kind}`; o.textContent = msg; }
  }

  function wire() {
    const cur = sec.querySelector(".s2-step.current");
    if (cur) {
      const box = cur.querySelector("[data-edit]");
      if (box) wireEdit(V.current, box);
    }
    sec.querySelectorAll("[data-act]").forEach((b) => { b.onclick = () => act(b.dataset.act, b); });
  }

  async function post(action, payload) {
    return req(`/api/stage2/studies/${encodeURIComponent(V.study.study_id)}/actions/${action}`, {
      method: "POST", body: { payload }, headers: { "Expected-State-Version": String(V.study.state_version) },
    });
  }

  const BUSY = { draft: "LLM이 초안을 쓰는 중… (위험평가는 1분 이상 걸릴 수 있습니다)", approve: "검사하고 다음 단계를 준비하는 중…", run: "시작하는 중…",
    use_reference: "논문 값을 채우는 중…", save: "저장하는 중…", reopen: "다시 여는 중…" };

  async function act(action, btn) {
    if (busy) return;
    const k = action === "reopen" ? btn.dataset.step : V.current;
    const box = sec.querySelector(`[data-edit="${k}"]`);
    busy = true;
    sec.querySelectorAll("[data-act]").forEach((b) => { b.disabled = true; });
    const label = btn.textContent;
    btn.textContent = "…";
    out(BUSY[action] || "처리 중…");
    try {
      let v;
      if (action === "reopen") {
        v = await post("reopen", { step: k, reason: "연구자가 다시 열기" });
      } else if (action === "save" || ((action === "approve" || action === "run") && box && box.dataset.dirty && V.steps.find((s) => s.key === k).editable)) {
        v = await post("save", { step: k, data: collect(k, box) });
        V = v;
        if (action !== "save") {
          const blk = v.action_result && v.action_result.blocking;
          if (blk && blk.length) { busy = false; render(false); out("저장했지만 승인할 수 없습니다 — 위의 '승인 불가' 항목을 고쳐 주세요.", "warn"); return; }
          if (action === "approve" && k === "surface") await attachImages();
          v = await post(action, { step: k });
        }
      } else {
        if (action === "approve" && k === "surface") await attachImages();
        v = await post(action, { step: k });
      }
      V = v;
      busy = false;
      const r = v.action_result || {};
      render(action === "approve" || action === "run" || action === "reopen");
      if (r.blocked && r.blocked.length) out(`승인할 수 없습니다 — ${r.blocked.join(", ")}. 위의 '승인 불가' 항목을 고쳐 주세요.`, "warn");
      else if (action === "draft") out(`${r.provider ? `${r.provider}로 ` : ""}초안을 만들었습니다 — 확인하고 고친 뒤 승인하세요.${r.blocking && r.blocking.length ? " (승인 전에 고칠 항목이 있습니다)" : ""}`);
      else if (action === "save") out("저장했습니다.");
      else if (action === "use_reference") out("논문 값으로 채웠습니다.");
      if (V.done) done();
      document.dispatchEvent(new CustomEvent("f1:stage2", { detail: { id: V.study.study_id, step: V.current } }));
    } catch (e) {
      busy = false;
      sec.querySelectorAll("[data-act]").forEach((b) => { b.disabled = false; });
      btn.textContent = label;
      out(e.message, "warn");
    }
  }

  function done() {
    if (window.F1Agent) window.F1Agent.say("agent", { reply: "12단계를 모두 마쳤습니다. 위험평가 보고서와 최종 보고서(실험 설계 · 회귀식 · 반응 곡면 · ANOVA)를 PDF로 받을 수 있습니다.", proposals: [], source: "context" });
  }

  // ── 11 반응 곡면 ────────────────────────────────────────────────────────
  async function drawSurfaces() {
    const box = $("s2-surf-box");
    if (!box || !window.F1Surfaces) return;
    try {
      const q = surf.slice != null ? `?slice=${encodeURIComponent(surf.slice)}` : "";
      const d = await req(`/api/stage2/studies/${encodeURIComponent(V.study.study_id)}/surfaces${q}`);
      await window.F1Surfaces.render(box, d, { title: "반응 곡면 — 선택한 회귀식", onSlice: (id) => { surf.slice = Number(id); drawSurfaces(); } });
    } catch (e) { box.innerHTML = `<p class="s2-warn">${E(e.message)}</p>`; }
  }

  async function attachImages() {
    const box = $("s2-surf-box");
    const P = window.Plotly;
    if (!box || !P) return;
    const images = {};
    const plots = [...box.querySelectorAll(".rsg-plot")].filter((el) => el.data);
    for (const [i, el] of plots.slice(0, 12).entries()) {
      try {
        const bar = el.closest(".rsg-row").previousElementSibling;
        const name = (bar && bar.firstChild && bar.firstChild.textContent || `r${i}`).trim();
        const lab = (el.parentElement.querySelector(".rsg-lab") || {}).textContent || "";
        images[`${String(i + 1).padStart(2, "0")} ${name} ${lab}`.slice(0, 40)] = await P.toImage(el, { format: "png", width: 520, height: 440 });
      } catch (e) { /* 한 장 실패는 건너뛴다 */ }
    }
    if (Object.keys(images).length) V = await post("attach_images", { step: "surface", images });
  }

  window.F1Stage2 = { startFromCandidate, startCbd, open, view: () => V };
})();
