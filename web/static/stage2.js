/* 2단계 — Design Space 도출. 1단계 후보(또는 CBD 논문 Table 1)를 프로토타입으로 받아 15단계를 대화에 차례로 쌓는다.

   1 프로토타입(Table 1) → 2 QTPP(Table 3) → 3 CQA(Table 4) → 4 원료 물성 위험평가(Table 6) → 5 정리(Table 5)
   → 6 제형·공정 변수 위험평가(Table 8) → 7 정리(Table 7) → 8 종합 정리 · DoE 변수 추천(위험평가 보고서 PDF)
   → 9 실험 설계 입력(Table 9) → 10 회귀식 · 모형 진단(Table 10) → 11 반응 곡면(Figure 1) → 12 ANOVA(Table 11)
   → 13 Design Space(미래 배치 공동 통과확률) → 14 확인계획 잠금(확인점 3 · 동시 예측구간) → 15 확인배치 2×2 판정

   지금 단계만 고칠 수 있고, 승인한 단계는 접힌 카드(요약 한 줄)로 남아 펼쳐 볼 수 있다(다시 열면 뒤 단계는 '다시 확인 필요').
   LLM 초안 · 논문 값 · 연구자 편집 모두 같은 저장 → 승인 길을 가고, 승인은 서버의 결정론 검사가 막는다.
   서버: /api/stage2/studies/* (formula/stage2/service.py · space.py). 모든 ${}는 E()를 거친다. */
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
    regression: "반응마다 평균·선형·2요인 교호작용·2차 모형을 순차 F 검정과 예측 R²로 비교해 제안합니다. 예측 R²가 수정 R²보다 0.2 넘게 낮으면 과적합 의심 — 차수를 낮추거나 사유를 적고 수용합니다.",
    surface: "선택한 회귀식으로 그린 반응 곡면입니다. 점은 실험값, 세로줄은 잔차입니다. [확인]을 누르면 그림이 보고서에 들어갑니다.",
    anova: "선택 모형의 분산분석(부분 제곱합)입니다. 확인하면 최종 보고서(실험 설계 · 회귀식 · 곡면 · ANOVA)를 받을 수 있습니다.",
    space: "반응마다 규격을 적으면 미래 배치의 예측분포로 '모든 규격을 동시에 통과할 확률'을 계산합니다. 평균 반응면만 보면 영역을 과대평가합니다 — 공동확률 ≥ 0.90인 곳이 Design Space입니다.",
    vplan: "영역에서 확인할 점 3개(설정점 · 경계점 · 강건성)와 예측구간을 결과를 보기 전에 잠급니다. 이미 있는 배치(예: 논문 최적)는 참고점으로만 비교합니다.",
    verify: "모형 적합에 쓰지 않은 새 배치를 확인점에서 만들어 측정한 값을 넣습니다. 규격 통과 × 예측구간 안(2×2)을 세 점 모두 만족해야 VERIFIED입니다.",
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
    if (window.F1Agent) window.F1Agent.say("user", "시연 — CBD 구강붕해정으로 2단계(QTPP부터 Design Space까지) 진행");
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
    const done = V.steps.filter((s) => s.status === "approved").length, n = V.steps.length;
    sec.innerHTML = `<header class="s2-head">
        <div><b>${E(st.title)}</b><small>${E(st.study_id)}${st.reference ? ` · 논문 비교: ${E(V.reference_citation || "")}` : ""}</small></div>
        <div class="s2-prog" aria-label="진행 ${done}/${n}"><i style="width:${(done / n) * 100}%"></i></div>
        <span class="s2-count">${V.done ? "완료" : `${done} / ${n}`}</span>
      </header>
      <ol class="s2-steps">${V.steps.filter((s) => s.status !== "empty" || s.key === V.current).map(stepCard).join("")}</ol>
      ${links()}`;
    wire();
    const cur = sec.querySelector(".s2-step.current");
    if (scroll && cur) cur.scrollIntoView({ behavior: "smooth", block: "start" });
    if (V.current === "surface" && !V.done) drawSurfaces();
    if (V.current === "space" && !V.done && (V.study.steps.space.data || {}).region) drawSpace();
  }

  function links() {
    const id = encodeURIComponent(V.study.study_id);
    const rec = V.study.steps.recommend.status === "approved";
    if (!rec) return "";
    return `<div class="s2-links">
      <a class="s2-file" href="${E(api(`/api/stage2/studies/${id}/risk-report.pdf`))}" target="_blank" rel="noopener">위험평가 보고서 PDF</a>
      ${V.study.steps.anova.status === "approved" ? `<a class="s2-file primary" href="${E(api(`/api/stage2/studies/${id}/report.pdf`))}" target="_blank" rel="noopener">최종 보고서 PDF</a>` : ""}
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
      const sum = s.data ? summary(meta.key, s.data) : "";
      return `<li class="s2-step ${E(s.status)}" data-step="${E(meta.key)}"><details><summary>${head}${sum ? `<span class="s2-sum">${E(sum)}</span>` : ""}</summary>
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

  // 접힌 단계에도 핵심 결과가 보이게 — 요약 한 줄
  function summary(k, d) {
    const c = (a) => (a || []).length;
    try {
      switch (k) {
        case "prototype": return `${d.api || ""} ${d.strength_mg ?? ""} mg · 성분 ${c(d.ingredients)}종 · ${d.process || ""}`;
        case "qtpp": return `QTPP 요소 ${c(d.items)}개`;
        case "cqa": return `품질특성 ${c(d.items)}개 · 위험평가 CQA ${d.items.filter((i) => i.in_risk_assessment).map((i) => i.short).join(", ")}`;
        case "rm_just": case "fp_just": return `변수 ${c(d.variables)}개 · 근거 ${c(d.items)}행`;
        case "rm_matrix": case "fp_matrix": return `High ${d.levels.flat().filter((x) => x === "High").length}칸 · Medium ${d.levels.flat().filter((x) => x === "Medium").length}칸 / ${d.levels.flat().length}칸`;
        case "recommend": return `DoE 변수 ${(d.selected || []).join(", ") || "—"}`;
        case "design": return `요인 ${d.factors.map((f) => f.name).join(" · ")} · 반응 ${c(d.responses)}개 · ${c(d.rows)} run`;
        case "regression": return d.responses.map((r) => `${r.response} ${FAMILY_KO[r.family] || r.family}${r.pred_r2 != null ? ` (예측 R² ${num(r.pred_r2, 3)})` : ""}`).join(" · ");
        case "surface": return `반응 ${(d.responses || []).join(", ")}`;
        case "anova": return d.responses.filter((r) => !r.aliased).map((r) => { const m = r.rows.find((x) => x.source === "Model"); return `${r.response} 모형 p ${pfmt(m && m.p)}`; }).join(" · ");
        case "space": {
          const r = d.region || {};
          if (!r.status) return "규격 입력 전";
          return r.status === "OK" ? `평균 기준 ${(100 * r.mean_ok_fraction).toFixed(1)}% → 공동확률 ≥ ${r.p_min} ${(100 * r.feasible_fraction).toFixed(1)}% · 설정점 ${Object.values(r.setpoint.actual).join(" / ")}`
            : `영역 없음 (최대 공동확률 ${num(r.max_joint, 3)})`;
        }
        case "vplan": return `확인점 ${c((d.plan || {}).points)}개${d.locked_at ? ` · ${d.locked_at.slice(0, 16).replace("T", " ")} UTC 잠금` : ""}`;
        case "verify": return ({ VERIFIED: "VERIFIED — 내부 사전계획 통과", INVALIDATED: "영역 무효화 — 진단 필요", INCOMPLETE: "실측값 미완" })[(d.judgement || {}).verdict] || "";
        default: return "";
      }
    } catch (e) { return ""; }
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
    if (V.study.reference && ["qtpp", "cqa", "rm_just", "fp_just", "recommend", "design", "regression", "space", "vplan"].includes(k))
      b.push(`<button type="button" class="ghost" data-act="use_reference" ${dis}>논문 값으로 채우기</button>`);
    if (meta.editable && k !== "prototype") b.push(`<button type="button" class="ghost" data-act="save" ${dis}>저장</button>`);
    if (k !== "prototype") {
      const label = meta.derived ? (k === "anova" ? "확인 · 최종 보고서 만들기" : "확인") : k === "recommend" ? "승인 · 위험평가 보고서"
        : k === "vplan" ? "확인계획 잠금" : k === "verify" ? "판정 기록" : k === "space" ? "영역 승인" : "승인";
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
      case "space": return vSpace(d, ro);
      case "vplan": return vVplan(d, ro);
      case "verify": return vVerify(d, ro);
      default: return "";
    }
  }

  // 1단계 → 2단계 불변 Handoff — 프로토타입은 고칠 수 있지만 넘어온 원본과 요청 맥락은 그대로 남는다
  function handoffBox() {
    const h = (V.study.source || {}).handoff;
    if (!h) return "";
    const row = (k, v) => (v == null || v === "" ? "" : `<dt>${E(k)}</dt><dd>${E(v)}</dd>`);
    return `<details class="s2-handoff" open><summary>1단계에서 넘어온 후보 (불변 Handoff) <code>${E(h.fingerprint)}</code></summary>
      <dl class="s2-eq">${row("후보", `${h.candidate_id} · ${h.strategy || ""}`)}${row("요청", h.request)}${row("대상 환자", h.target_population)}
        ${row("1회 용량", h.dose_mg != null ? `${h.dose_mg} mg` : "")}${row("요청 제형", h.dosage_form)}${row("약물 함량", h.drug_loading_pct != null ? `${h.drug_loading_pct} %` : "")}
        ${row("고정 부형제", (h.required_excipients || []).join(", "))}${row("원본 조성", (h.ingredients || []).map((i) => `${i.name} ${i.mg ?? "?"} mg`).join(" · "))}
        ${row("1단계 신호", (h.signals || []).map((g) => `${g.rule_id} — ${g.message}`).join(" / "))}</dl>
      <p class="s2-muted">QTPP·위험평가 초안은 이 맥락을 함께 읽습니다. 아래 프로토타입은 고칠 수 있지만 이 원본은 바뀌지 않습니다(fingerprint로 확인).</p></details>`;
  }

  function vPrototype(d, ro) {
    const f = (label, name, v) => `<label class="s2-f"><span>${E(label)}</span>${inp(v, `data-f="${name}"`, ro)}</label>`;
    return `${handoffBox()}<div class="s2-grid">${f("주성분", "api", d.api)}${f("제형", "dosage_form", d.dosage_form)}${f("투여 경로", "route", d.route)}
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
    const watch = d.watch || [];
    return `<h4 class="s2-h">종합 위험평가 (Table 5 + Table 7)</h4>${merged}
      <h4 class="s2-h">DoE 변수 후보 <small>High인 제형·공정 변수만 · 최대 4개 선택 · 선택 ${selSet.size}개</small></h4>
      <p class="s2-muted">규칙 순위(High 개수 순): ${E((d.rule_rank || []).join(" › ") || "—")}</p>
      <ul class="s2-cands">${cands || `<li class="s2-muted">후보가 없습니다 — 6단계의 등급을 확인하세요.</li>`}</ul>
      ${d.note ? `<p class="s2-note">${E(d.note)}</p>` : ""}
      ${watch.length ? `<p class="s2-muted">Medium만 있는 변수 — DoE 요인이 아니라 관리·모니터링 대상: ${E(watch.map((c) => `${c.variable}(${c.medium.join(", ")})`).join(" · "))}</p>` : ""}
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
      ${ro ? "" : `<details class="s2-paste" open><summary>CSV 파일 · 엑셀 붙여넣기로 채우기</summary>
        <p class="s2-muted">첫 줄은 머리글(Std · Run · 요인 · 반응). 머리글 앞에 <code>X:</code>(요인) · <code>Y:</code>(반응)를 붙이거나 아래에서 열마다 역할을 고릅니다.
          단위는 머리글 끝 괄호로 적습니다(예: <code>Y: Friability (%)</code>). <code>#</code>로 시작하는 줄은 설명으로 건너뜁니다. 표 전체(요인·반응·행)를 바꿉니다.</p>
        <div class="s2-import"><label class="s2-file-in">CSV 파일 고르기 <input type="file" accept=".csv,.tsv,.txt,text/csv" data-csv-file></label>
          <a class="s2-example" href="${E(api("/static/data/almotairi2022_table3.csv"))}" download>실데이터 예: Almotairi 2022 Table 3 (로르녹시캄 분산정 15 run)</a></div>
        <textarea data-paste rows="4" placeholder="Std,Run,X: 요인1 (단위),Y: 반응1 (단위)&#10;1,5,1500,4.97"></textarea>
        <div data-map></div>
        <button type="button" class="ghost sm" data-paste-read>열 읽기</button> <button type="button" class="primary sm" data-paste-apply hidden>표에 넣기</button></details>`}
      ${d.note ? `<p class="s2-note">${E(d.note)}</p>` : ""}`;
  }

  function vRegression(d, ro) {
    return (d.responses || []).map((r) => {
      const fams = r.summary.rows.filter((x) => x.model !== "Mean" && !x.aliased).map((x) => x.model);
      return `<div class="s2-reg" data-resp="${E(r.response)}"><div class="s2-reg-head"><b>${E(r.response)}</b>${r.unit ? `<small>${E(r.unit)}</small>` : ""}
          <span class="s2-muted">n = ${E(r.n)}</span>
          <label>모형 ${ro ? `<b>${E(FAMILY_KO[r.family] || r.family)}</b>` : `<select data-family>${fams.map((f) => `<option value="${E(f)}" ${f === r.family ? "selected" : ""}>${E(FAMILY_KO[f] || f)}${f === r.suggested ? " (제안)" : ""}</option>`).join("")}</select>`}</label></div>
        <div class="s2-scroll"><table class="s2-t fit"><thead><tr><th>모형</th><th>순차 p</th><th>적합결여 p</th><th>R²</th><th>수정 R²</th><th>예측 R²</th><th></th></tr></thead>
          <tbody>${r.summary.rows.map((x) => `<tr class="${x.model === r.family ? "chosen" : ""}"><td>${E(FAMILY_KO[x.model] || x.model)}${overfit(x) ? ` <span class="s2-flag">과적합 의심</span>` : ""}</td>
            ${x.aliased ? `<td colspan="5" class="s2-muted">추정 불가(항 수 ≥ run 수)</td>` : `<td class="n">${E(pfmt(x.seq_p))}</td><td class="n">${E(pfmt(x.lof_p))}</td>
            <td class="n">${E(num(x.r2))}</td><td class="n">${E(num(x.adj_r2))}</td><td class="n">${E(num(x.pred_r2))}</td>`}
            <td>${x.suggested ? "제안" : ""}</td></tr>`).join("")}</tbody></table></div>
        <p class="s2-muted">${E(r.reason)}</p>
        ${r.aliased ? `<p class="s2-warn">이 모형은 이 설계로 추정할 수 없습니다 — 더 낮은 차수를 고르세요.</p>` : `<dl class="s2-eq"><dt>Coded</dt><dd><code>${E(r.coded_eq)}</code></dd>
          <dt>Actual</dt><dd><code>${E(r.actual_eq)}</code></dd><dt>적합</dt><dd>R² ${E(num(r.r2))} · 수정 R² ${E(num(r.adj_r2))} · 예측 R² ${E(num(r.pred_r2))}</dd></dl>`}
        ${V.reference && V.reference.regression && V.reference.regression.families[r.response] ? `<p class="s2-cmp">논문 모형: ${E(FAMILY_KO[V.reference.regression.families[r.response]] || V.reference.regression.families[r.response])}</p>` : ""}
      </div>`;
    }).join("") + `<p class="s2-muted">요인 기호: ${(d.factors || []).map((f, i) => `X${i + 1} = ${E(f.name)}${f.unit ? ` (${E(f.unit)})` : ""} [${E(num(f.low))} – ${E(num(f.high))}]`).join(" · ")}</p>
      ${!ro && (d.responses || []).some((r) => !r.aliased && overfit(r)) ? `<label class="s2-f wide s2-reason"><span>과적합 의심 모형을 그대로 쓰는 사유(승인에 필요)</span>
        <textarea data-note rows="2" placeholder="예: 반응이 좁은 범위라 예측 R²가 낮음 — 확인배치로 검증 예정"></textarea></label>` : ""}`;
  }
  const overfit = (x) => x.adj_r2 != null && x.pred_r2 != null && (x.adj_r2 - x.pred_r2 > 0.2 || x.pred_r2 < 0);

  function vAnova(d) {
    return (d.responses || []).map((r) => r.aliased ? `<p class="s2-warn">${E(r.response)}: 모형을 추정할 수 없습니다.</p>` : `<div class="s2-reg"><div class="s2-reg-head"><b>${E(r.response)}</b>
        <span class="s2-muted">${E(FAMILY_KO[r.family] || r.family)} 모형</span></div>
      <div class="s2-scroll"><table class="s2-t anova"><thead><tr><th>Source</th><th>Sum of squares</th><th>df</th><th>Mean square</th><th>F</th><th>p</th></tr></thead>
        <tbody>${r.rows.map((x) => `<tr class="lvl${x.level}${x.p != null && x.p < 0.05 ? " sig" : ""}"><td>${E(x.source)}</td><td class="n">${E(num(x.ss))}</td><td class="n">${E(x.df)}</td>
          <td class="n">${E(x.ms != null ? num(x.ms) : "")}</td><td class="n">${E(x.f != null ? num(x.f) : "")}</td><td class="n">${E(pfmt(x.p))}</td></tr>`).join("")}</tbody></table></div>
      <p class="s2-muted">R² ${E(num(r.r2))} · 수정 R² ${E(num(r.adj_r2))} · 예측 R² ${E(num(r.pred_r2))} · 표준편차 ${E(num(r.std_dev))} · 평균 ${E(num(r.mean))} · CV ${E(num(r.cv_pct, 3))}% — p &lt; 0.05 굵게</p></div>`).join("");
  }

  // ── 13 Design Space ─────────────────────────────────────────────────────
  const OPS = [["", "규격 없음(제외)"], ["LE", "≤ 상한"], ["GE", "≥ 하한"], ["BETWEEN", "범위"]];
  const specText = (x) => ({ LE: `≤ ${x.upper}`, GE: `≥ ${x.lower}`, BETWEEN: `${x.lower}–${x.upper}` })[x.op] || "영역 계산 제외";
  function vSpace(d, ro) {
    const specs = d.specs || [], r = d.region;
    const rows = specs.map((x, i) => ro ? `<tr><td>${E(x.response)}${x.unit ? ` <small>${E(x.unit)}</small>` : ""}</td><td>${E(specText(x))}</td><td>${E(x.basis || "")}</td></tr>`
      : `<tr data-spec="${i}" data-resp="${E(x.response)}" data-unit="${E(x.unit)}"><td><b>${E(x.response)}</b>${x.unit ? ` <small>${E(x.unit)}</small>` : ""}</td>
        <td><select data-k="op">${OPS.map(([v, t]) => `<option value="${v}" ${v === (x.op || "") ? "selected" : ""}>${E(t)}</option>`).join("")}</select></td>
        <td class="n"><input data-k="lower" value="${E(x.lower ?? "")}" inputmode="decimal" placeholder="하한"></td>
        <td class="n"><input data-k="upper" value="${E(x.upper ?? "")}" inputmode="decimal" placeholder="상한"></td>
        <td><input data-k="basis" value="${E(x.basis || "")}" placeholder="근거(약전·목표·가정 — 제외하면 이유)"></td></tr>`).join("");
    const head = ro ? "<tr><th>반응</th><th>규격</th><th>근거</th></tr>" : "<tr><th>반응</th><th>규격</th><th>하한</th><th>상한</th><th>근거</th></tr>";
    let res = `<p class="s2-muted">규격을 적고 <b>저장</b>을 누르면 영역을 계산합니다.</p>`;
    if (r && r.status) {
      const sp = r.setpoint;
      res = `<div class="s2-kpis">
          <div><small>평균 예측이 모든 규격 안</small><b>${(100 * r.mean_ok_fraction).toFixed(1)}%</b></div>
          <div class="arrow">→</div>
          <div><small>미래 배치 공동확률 ≥ ${E(r.p_min)}</small><b>${(100 * r.feasible_fraction).toFixed(1)}%</b></div>
          <div><small>지지 영역 격자점</small><b>${E(r.grid_points_in_domain.toLocaleString())}</b><small>/ ${E(r.grid_points_total.toLocaleString())}</small></div>
          <div><small>${sp ? "권장 설정점 공동확률" : "최대 공동확률"}</small><b>${E(num(sp ? sp.joint : r.max_joint, 3))}</b></div></div>
        ${sp ? `<p class="s2-setpoint">권장 설정점 — ${Object.entries(sp.actual).map(([k, v]) => `<b>${E(k)}</b> ${E(num(v))}`).join(" · ")}</p>`
          : `<p class="s2-warn">공동 통과확률 ≥ ${E(r.p_min)}인 점이 없습니다 — 규격을 완화하지 않습니다. 모형·요인 범위·위험평가를 다시 보세요.</p>`}
        <p class="s2-muted">경계를 정하는 반응(미달 격자점 수): ${E(Object.entries(r.binding || {}).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(" · ") || "—")}
          ${(r.excluded || []).length ? ` · 제외: ${E(r.excluded.join(", "))}` : ""} · ${E(r.independence_note || "")}</p>
        ${ro ? "" : `<div class="s2-map" id="s2-map-box"><p class="s2-muted">단면을 그리는 중…</p></div>`}`;
    }
    return `<div class="s2-scroll"><table class="s2-t spec"><thead>${head}</thead><tbody>${rows}</tbody></table></div>${res}`;
  }

  // ── 14 확인계획 ─────────────────────────────────────────────────────────
  const ROLE_KO = { SETPOINT: "설정점", BOUNDARY: "경계점", ROBUSTNESS: "강건성(최악 변동)", REFERENCE: "참고 배치" };
  function vVplan(d, ro) {
    const plan = d.plan || {}, pts = plan.points || [];
    const fn = Object.keys((pts[0] || {}).settings || {}) .length ? Object.keys(pts[0].settings) : ((V.study.steps.design.data || {}).factors || []).map((f) => f.name);
    const ref = d.reference || {};
    const ctrl = ro ? "" : `<div class="s2-grid">
        <label class="s2-f"><span>허용 변동(coded, ± 설정점)</span><input data-f="delta" value="${E(d.delta ?? 0.2)}" inputmode="decimal"></label>
        <label class="s2-f wide"><span>참고 배치(선택 — 이미 있는 배치, 예: 논문 최적 처방)</span>
          <span class="s2-refrow"><input data-ref="label" value="${E(ref.label || "")}" placeholder="이름">${fn.map((n) => `<input data-ref-set="${E(n)}" value="${E((ref.settings || {})[n] ?? "")}" placeholder="${E(n)}" inputmode="decimal">`).join("")}</span></label></div>`;
    const pol = plan.pi_policy || {};
    const body = pts.map((p) => {
      const pr = Object.entries(p.predicted);
      return pr.map(([n, v], i) => `<tr class="${p.role === "REFERENCE" ? "ref" : ""}">${i ? "" : `<th rowspan="${pr.length}">${E(ROLE_KO[p.role] || p.role)}${p.label ? `<small>${E(p.label)}</small>` : ""}</th>
        <td rowspan="${pr.length}">${Object.entries(p.settings).map(([k, x]) => `${E(k)} ${E(num(x))}`).join("<br>")}</td><td rowspan="${pr.length}" class="n">${E(num(p.joint, 3))}</td>`}
        <td>${E(n)}</td><td>${E(v.spec)}</td><td class="n">${E(num(v.mean, 3))}</td><td class="n">${E(num(v.pi_lower, 3))} – ${E(num(v.pi_upper, 3))}${v.pi_truncated ? "*" : ""}</td></tr>`).join("");
    }).join("");
    return `${ctrl}${pts.length ? `<div class="s2-scroll"><table class="s2-t vplan"><thead><tr><th>확인점</th><th>설정</th><th>공동확률</th><th>반응</th><th>규격</th><th>예측 평균</th><th>예측구간</th></tr></thead><tbody>${body}</tbody></table></div>
      <p class="s2-muted">예측구간: ${E(pol.comparisons)}개 비교(필수 확인점 3 × 규격 반응)의 Bonferroni 동시구간 — 개별 ${E(num(100 * (pol.per_comparison_level || 0), 4))}%.
        * 하한이 음수라 0에서 자름. ${d.locked_at ? `<b>${E(d.locked_at.slice(0, 16).replace("T", " "))} UTC 잠금 · ${E(d.plan_hash)}</b>` : "승인하면 결과를 보기 전에 이 계획이 잠깁니다."}</p>`
      : `<p class="s2-warn">${E(plan.reason || "확인점을 만들 수 없습니다.")}</p>`}`;
  }

  // ── 15 확인배치 ─────────────────────────────────────────────────────────
  function vVerify(d, ro) {
    const plan = (V.study.steps.vplan.data || {}).plan || {};
    const obs = Object.fromEntries((d.observations || []).map((o) => [o.role, o.values || {}]));
    const j = d.judgement || {};
    const cellOf = Object.fromEntries((j.rows || []).map((x) => [`${x.role}|${x.response}`, x]));
    const CELL = { PASS_IN: ["통과 · 구간 안", "ok"], PASS_OUT: ["통과 · 구간 밖", "warn"], FAIL_IN: ["실패 · 구간 안", "bad"], FAIL_OUT: ["실패 · 구간 밖", "bad"] };
    const rows = (plan.points || []).map((p) => {
      const pr = Object.entries(p.predicted);
      return pr.map(([n, v], i) => {
        const c = cellOf[`${p.role}|${n}`] || {};
        const [lab, cls] = CELL[c.cell] || ["", ""];
        return `<tr class="${p.role === "REFERENCE" ? "ref" : ""}">${i ? "" : `<th rowspan="${pr.length}">${E(ROLE_KO[p.role] || p.role)}${p.role === "REFERENCE" ? "<small>참고 — 판정에 안 셈</small>" : ""}
          ${ro ? `<small>${E((d.batches || {})[p.role] || "")}</small>` : `<input data-batch="${E(p.role)}" value="${E((d.batches || {})[p.role] || "")}" placeholder="배치 ID">`}</th>`}
          <td>${E(n)}</td><td>${E(v.spec)}</td><td class="n">${E(num(v.pi_lower, 3))} – ${E(num(v.pi_upper, 3))}</td>
          <td class="n">${ro ? E(num((obs[p.role] || {})[n])) : `<input data-obs="${E(p.role)}" data-resp="${E(n)}" value="${E((obs[p.role] || {})[n] ?? "")}" inputmode="decimal">`}</td>
          <td>${lab ? `<span class="s2-cell ${cls}">${E(lab)}</span>` : ""}</td></tr>`;
      }).join("");
    }).join("");
    const V_KO = { VERIFIED: ["VERIFIED — 세 확인점 모두 규격 통과 · 예측구간 안(내부 사전계획 통과이며 규제 승인 설계공간은 아니다)", "ok"],
      INVALIDATED: ["영역 무효화 — 진단 필요", "bad"], INCOMPLETE: ["필수 확인점의 실측값을 모두 넣으면 판정합니다", ""] };
    const [vt, vc] = V_KO[j.verdict] || ["", ""];
    return `${ro ? "" : `<label class="s2-check"><input type="checkbox" data-f="independent" ${d.independent ? "checked" : ""}> 확인배치는 모형 적합에 쓰지 않은 새 독립 배치다</label>`}
      <div class="s2-scroll"><table class="s2-t verify"><thead><tr><th>확인점 · 배치</th><th>반응</th><th>규격</th><th>잠근 예측구간</th><th>실측</th><th>판정</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${vt ? `<p class="s2-verdict ${vc}">${E(vt)}</p>` : ""}${(j.advice || []).map((a) => `<p class="s2-note">${E(a)}</p>`).join("")}`;
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
    if (k === "regression") return { chosen: Object.fromEntries(q(".s2-reg[data-resp]").map((r) => [r.dataset.resp, r.querySelector("[data-family]").value])) };
    if (k === "space") return { specs: q("tr[data-spec]").map((tr) => ({ response: tr.dataset.resp, unit: tr.dataset.unit,
      op: tr.querySelector('[data-k="op"]').value, lower: tr.querySelector('[data-k="lower"]').value, upper: tr.querySelector('[data-k="upper"]').value,
      basis: tr.querySelector('[data-k="basis"]').value })) };
    if (k === "vplan") {
      const lab = box.querySelector('[data-ref="label"]');
      const settings = Object.fromEntries(q("[data-ref-set]").map((i) => [i.dataset.refSet, i.value]));
      return { delta: (box.querySelector('[data-f="delta"]') || {}).value, reference: Object.values(settings).some((v) => v !== "") ? { label: lab ? lab.value : "", settings } : null };
    }
    if (k === "verify") {
      const obs = {};
      q("[data-obs]").forEach((i) => { (obs[i.dataset.obs] = obs[i.dataset.obs] || {})[i.dataset.resp] = i.value; });
      return { independent: !!(box.querySelector('[data-f="independent"]') || {}).checked,
        batches: Object.fromEntries(q("[data-batch]").map((i) => [i.dataset.batch, i.value])),
        observations: Object.entries(obs).map(([role, values]) => ({ role, values })) };
    }
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
    markStale(box);
    wireEdit(k, box);
  }
  // 화면에서 고친 뒤에는 아래 검사 결과가 '저장된 판'의 것이다 — 흐리게 하고 알린다(저장하면 다시 검사)
  function markStale(box) {
    const ul = box.parentElement.querySelector(".s2-checks");
    if (ul && !ul.classList.contains("stale")) {
      ul.classList.add("stale");
      ul.insertAdjacentHTML("afterbegin", `<li class="s2-stale-note">아래는 저장된 판의 검사 결과입니다 — 고친 내용은 <b>저장</b>하면 다시 검사합니다.</li>`);
    }
  }

  function wireEdit(k, box) {
    if (!box.dataset.wired) {           // 다시 그려도 상자 자체는 같다 — 리스너는 한 번만
      box.dataset.wired = "1";
      const skip = (e) => e.target.closest("[data-space-fixed],[data-space-level],[data-note],[data-paste],[data-map],[data-csv-file]");
      box.addEventListener("input", (e) => { if (skip(e)) return; box.dataset.dirty = "1"; markStale(box); });
      box.addEventListener("change", (e) => { if (skip(e)) return; box.dataset.dirty = "1"; markStale(box); });
    }
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
    // CSV 파일 · 붙여넣기 → 열 역할(요인·반응·Std·Run·제외) → 표 전체 교체
    const ta = box.querySelector("[data-paste]");
    const fileIn = box.querySelector("[data-csv-file]");
    const mapBox = box.querySelector("[data-map]");
    const applyBtn = box.querySelector("[data-paste-apply]");
    let parsed = null;
    const readCols = () => {
      parsed = parseTable(ta.value);
      if (!parsed) { mapBox.innerHTML = ""; applyBtn.hidden = true; out("머리글과 숫자 행이 있는 표를 찾지 못했습니다.", "warn"); return; }
      const d = collectDesign(box);
      const roles = guessRoles(parsed.head, d);
      mapBox.innerHTML = `<div class="s2-scroll"><table class="s2-t map"><thead><tr><th>열</th><th>역할</th><th>이름</th><th>단위</th><th>예(첫 행)</th></tr></thead><tbody>
        ${parsed.head.map((h, i) => { const nm = splitHead(h); return `<tr data-col="${i}"><td>${E(h)}</td>
          <td><select data-role>${[["std", "Std"], ["run", "Run"], ["f", "요인"], ["r", "반응"], ["", "제외"]].map(([v, t]) => `<option value="${v}" ${roles[i] === v ? "selected" : ""}>${t}</option>`).join("")}</select></td>
          <td><input data-name value="${E(nm.name)}"></td><td><input data-unit value="${E(nm.unit)}" class="unit"></td><td class="n">${E(parsed.rows[0][i] ?? "")}</td></tr>`; }).join("")}
        </tbody></table></div><p class="s2-muted">${parsed.rows.length}개 행 · 요인 최대 3개 · 반응 최대 4개</p>`;
      applyBtn.hidden = false;
    };
    if (fileIn) fileIn.onchange = async () => {
      const f = fileIn.files && fileIn.files[0];
      if (!f) return;
      if (f.size > 2_000_000) { out("CSV는 2 MB까지 읽습니다.", "warn"); return; }
      ta.value = await f.text();
      fileIn.value = "";
      readCols();
    };
    const rd = box.querySelector("[data-paste-read]");
    if (rd) rd.onclick = readCols;
    if (applyBtn) applyBtn.onclick = () => {
      if (!parsed) return;
      const cols = [...mapBox.querySelectorAll("tr[data-col]")].map((tr) => ({ i: Number(tr.dataset.col), role: tr.querySelector("[data-role]").value,
        name: tr.querySelector("[data-name]").value.trim(), unit: tr.querySelector("[data-unit]").value.trim() }));
      const F = cols.filter((c) => c.role === "f"), R = cols.filter((c) => c.role === "r");
      const std = cols.find((c) => c.role === "std"), run = cols.find((c) => c.role === "run");
      if (!F.length || !R.length) { out("요인과 반응을 각각 하나 이상 고르세요.", "warn"); return; }
      if (F.length > 3 || R.length > 4) { out(`요인은 3개, 반응은 4개까지입니다(지금 요인 ${F.length} · 반응 ${R.length}).`, "warn"); return; }
      const d = { factors: F.map((c) => ({ name: c.name, unit: c.unit })), responses: R.map((c) => ({ name: c.name, unit: c.unit })),
        rows: parsed.rows.map((r, n) => ({ std: std ? r[std.i] : n + 1, run: run ? r[run.i] : (std ? r[std.i] : n + 1),
          x: F.map((c) => r[c.i] ?? ""), y: R.map((c) => r[c.i] ?? "") })) };
      redrawEdit(k, d);
      out(`${d.rows.length}개 행 · 요인 ${F.length} · 반응 ${R.length}을 표에 넣었습니다 — 저장하면 서버가 검사합니다.`);
    };
    const sp = box.querySelector("[data-space-fixed]");
    if (sp) sp.onchange = () => { spaceView.fixed = Number(sp.value); spaceView.level = null; drawSpace(); };
    box.querySelectorAll("[data-pick]").forEach((c) => {
      c.onchange = () => {
        const n = box.querySelectorAll("[data-pick]:checked").length;
        if (n > 4) { c.checked = false; out("DoE 변수는 최대 4개입니다.", "warn"); }
      };
    });
  }

  function parseTable(text) {
    const lines = String(text || "").split(/\r?\n/).filter((l) => l.trim() && !l.trim().startsWith("#"));
    if (lines.length < 2) return null;
    const first = lines[0];
    const sep = first.includes("\t") ? "\t" : (first.split(";").length > first.split(",").length ? ";" : ",");
    const cells = lines.map((l) => l.split(sep).map((c) => c.trim().replace(/^"(.*)"$/, "$1")));
    const isNum = (c) => c !== "" && Number.isFinite(Number(c));
    const hasHead = cells[0].some((c) => c && !isNum(c));
    const head = hasHead ? cells[0] : cells[0].map((_, i) => `열 ${i + 1}`);
    const rows = (hasHead ? cells.slice(1) : cells).filter((r) => r.some(isNum));
    return rows.length ? { head, rows } : null;
  }
  function splitHead(h) {
    let t = String(h || "").replace(/^\s*(x|y|요인|반응)\s*[:：]\s*/i, "");
    const m = t.match(/^(.*?)\s*[\(\[]([^()\[\]]*)[\)\]]\s*$/);
    return m ? { name: m[1].trim(), unit: m[2].trim() } : { name: t.trim(), unit: "" };
  }
  function guessRoles(head, d) {
    const fN = new Set((d.factors || []).map((f) => f.name.toLowerCase())), rN = new Set((d.responses || []).map((r) => r.name.toLowerCase()));
    const roles = head.map((h) => {
      const t = String(h).trim();
      if (/^\s*(x|요인)\s*[:：]/i.test(t)) return "f";
      if (/^\s*(y|반응)\s*[:：]/i.test(t)) return "r";
      if (/^(std|standard|std\.?\s*order|표준)/i.test(t)) return "std";
      if (/^(run|run\.?\s*order|실행|순서)/i.test(t)) return "run";
      const nm = splitHead(t).name.toLowerCase();
      if (fN.has(nm)) return "f";
      if (rN.has(nm)) return "r";
      return "?";
    });
    let nf = roles.filter((r) => r === "f").length;
    const wantF = Math.min(3, Math.max(1, (d.factors || []).length));
    return roles.map((r) => {
      if (r !== "?") return r;
      if (nf < wantF) { nf += 1; return "f"; }
      return "r";
    });
  }

  // ── 13 공동확률 단면 지도 — (a) 평균 예측이 모든 규격 안 (b) 미래 배치 공동 통과확률(≥ 기준 = 흰 점) ────
  const spaceView = { fixed: null, level: null };
  async function drawSpace() {
    const box = $("s2-map-box");
    if (!box) return;
    const r = (V.study.steps.space.data || {}).region || {};
    const k = (r.factors || []).length;
    if (k === 3 && spaceView.fixed == null) spaceView.fixed = 1;
    if (k === 3 && spaceView.level == null && r.setpoint) spaceView.level = r.setpoint.coded[spaceView.fixed];
    try {
      const q = k === 3 ? `?fixed=${spaceView.fixed}${spaceView.level != null ? `&level=${spaceView.level}` : ""}` : "";
      const d = await req(`/api/stage2/studies/${encodeURIComponent(V.study.study_id)}/space${q}`);
      box.innerHTML = d.kind === "LINE" ? lineSvg(d, r) : mapFigure(d, r, k);
      const fsel = box.querySelector("[data-space-fixed]"), lsel = box.querySelector("[data-space-level]");
      if (fsel) fsel.onchange = () => { spaceView.fixed = Number(fsel.value); spaceView.level = r.setpoint ? r.setpoint.coded[spaceView.fixed] : 0; drawSpace(); };
      if (lsel) lsel.onchange = () => { spaceView.level = Number(lsel.value); drawSpace(); };
    } catch (e) { box.innerHTML = `<p class="s2-warn">${E(e.message)}</p>`; }
  }
  function mapFigure(d, r, k) {
    const sp = r.setpoint;
    const onSlice = sp && (!d.fixed || Math.abs(sp.coded[d.fixed.index] - d.fixed.coded) < 1e-6);
    const idx = (vals, v) => vals.reduce((b, x, i) => (Math.abs(x - v) < Math.abs(vals[b] - v) ? i : b), 0);
    const names = (r.factors || []).map((f) => f.name);
    const spRC = onSlice ? [idx(d.rows.values, sp.actual[d.rows.name]), idx(d.cols.values, sp.actual[d.cols.name])] : null;
    const ctrl = d.fixed ? `<div class="s2-map-ctrl"><label>고정 요인 <select data-space-fixed>${names.map((n, i) => `<option value="${i}" ${i === d.fixed.index ? "selected" : ""}>${E(n)}</option>`).join("")}</select></label>
      <label>값 <select data-space-level>${d.fixed.levels.map((l) => `<option value="${l.coded}" ${Math.abs(l.coded - d.fixed.coded) < 1e-6 ? "selected" : ""}>${E(num(l.actual))}${E(d.fixed.unit ? " " + d.fixed.unit : "")}</option>`).join("")}</select></label></div>` : "";
    return `${ctrl}<div class="s2-maps">${mapSvg(d, "mean", spRC)}${mapSvg(d, "joint", spRC)}</div>
      <p class="s2-muted">${d.fixed ? `${E(d.fixed.name)} = ${E(num(d.fixed.actual))}${E(d.fixed.unit || "")} 단면. ` : ""}회색 바탕 = 설계점이 받치지 않는 곳(외삽 — 계산에서 뺌) · 둥근 테두리 = 권장 설정점${onSlice ? "" : "(이 단면에 없음)"}.</p>`;
  }
  function mapSvg(d, mode, spRC) {
    const nr = d.P.length, nc = d.P[0].length, cs = 11, L = 46, T = 20, W = L + nc * cs + 8, H = T + nr * cs + 34;
    let cells = "";
    for (let i = 0; i < nr; i++) {
      for (let j = 0; j < nc; j++) {
        const x = L + j * cs, y = T + (nr - 1 - i) * cs;
        if (!d.in[i][j]) { cells += `<rect x="${x}" y="${y}" width="${cs}" height="${cs}" class="m-out"/>`; continue; }
        if (mode === "mean") cells += `<rect x="${x}" y="${y}" width="${cs}" height="${cs}" class="${d.mean_ok[i][j] ? "m-ok" : "m-no"}"/>`;
        else {
          const p = d.P[i][j];
          cells += `<rect x="${x}" y="${y}" width="${cs}" height="${cs}" class="m-p" fill-opacity="${(0.08 + 0.85 * p).toFixed(3)}"/>`;
          if (p >= d.p_min) cells += `<circle cx="${x + cs / 2}" cy="${y + cs / 2}" r="2" class="m-dot"/>`;
        }
      }
    }
    const ring = spRC ? `<circle cx="${L + spRC[1] * cs + cs / 2}" cy="${T + (nr - 1 - spRC[0]) * cs + cs / 2}" r="${cs * 0.9}" class="m-sp"/>` : "";
    const ax = (vals) => [vals[0], vals[Math.floor(vals.length / 2)], vals[vals.length - 1]].map((v) => num(v, 3));
    const cx = ax(d.cols.values), rx = ax(d.rows.values);
    const title = mode === "mean" ? "(a) 평균 예측이 모든 규격 안" : `(b) 공동 통과확률 ≥ ${d.p_min} (흰 점)`;
    return `<figure class="s2-mapfig"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${E(title)}">
      <text x="${L}" y="12" class="m-t">${E(title)}</text>${cells}${ring}
      <text x="${L}" y="${T + nr * cs + 12}" class="m-a">${E(cx[0])}</text><text x="${L + nc * cs / 2}" y="${T + nr * cs + 12}" class="m-a" text-anchor="middle">${E(cx[1])}</text>
      <text x="${L + nc * cs}" y="${T + nr * cs + 12}" class="m-a" text-anchor="end">${E(cx[2])}</text>
      <text x="${L + nc * cs / 2}" y="${T + nr * cs + 27}" class="m-a" text-anchor="middle">${E(d.cols.name)}${d.cols.unit ? ` (${E(d.cols.unit)})` : ""}</text>
      <text x="${L - 4}" y="${T + nr * cs}" class="m-a" text-anchor="end">${E(rx[0])}</text><text x="${L - 4}" y="${T + 8}" class="m-a" text-anchor="end">${E(rx[2])}</text>
      <text x="10" y="${T + nr * cs / 2}" class="m-a" transform="rotate(-90 10 ${T + nr * cs / 2})" text-anchor="middle">${E(d.rows.name)}</text></svg></figure>`;
  }
  function lineSvg(d, r) {
    const n = d.P.length, W = 320, H = 150, L = 36, B = 120;
    const px = (i) => L + (i / (n - 1)) * (W - L - 10), py = (p) => B - p * 100;
    const pts = d.P.map((p, i) => `${px(i).toFixed(1)},${py(p).toFixed(1)}`).join(" ");
    return `<figure class="s2-mapfig"><svg viewBox="0 0 ${W} ${H}"><text x="${L}" y="12" class="m-t">공동 통과확률 — ${E(d.factor)}</text>
      <line x1="${L}" x2="${W - 10}" y1="${py(d.p_min)}" y2="${py(d.p_min)}" class="m-thr"/><polyline points="${pts}" class="m-line"/>
      <text x="${L}" y="${B + 16}" class="m-a">${E(num(d.x[0], 3))}</text><text x="${W - 10}" y="${B + 16}" class="m-a" text-anchor="end">${E(num(d.x[n - 1], 3))}</text></svg></figure>`;
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
          v = await post(action, { step: k, note: noteOf(box) });
        }
      } else {
        if (action === "approve" && k === "surface") await attachImages();
        v = await post(action, { step: k, note: action === "approve" ? noteOf(box) : undefined });
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

  function noteOf(box) {
    const n = box && box.querySelector("[data-note]");
    return n ? n.value.trim() : undefined;
  }

  function done() {
    const v = ((V.study.steps.verify.data || {}).judgement || {}).verdict;
    if (window.F1Agent) window.F1Agent.say("agent", { reply: `15단계를 모두 마쳤습니다${v === "VERIFIED" ? " — 확인배치가 세 점 모두 규격 통과 · 예측구간 안(VERIFIED)" : v === "INVALIDATED" ? " — 확인 실패로 영역을 무효화했습니다(진단 필요)" : ""}. 위험평가 보고서와 최종 보고서(실험 설계 · 회귀식 · 곡면 · ANOVA · Design Space · 확인계획 · 확인배치)를 PDF로 받을 수 있습니다.`, proposals: [], source: "context" });
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
