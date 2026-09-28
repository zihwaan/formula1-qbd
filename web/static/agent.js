/* 입력 에이전트 — 대화창. 사용자의 말을 **제안 카드**(설계 실행 · 측정값 제출 · 개발 착수)로 바꾼다.
   카드의 [실행]을 눌러야 반영되고, 실행은 사람이 버튼을 누른 것과 같은 경로(startRunWith · submitMeasurements ·
   F1Stage2.startFromCandidate)로 간다. 맥락은 서버가 run에서 직접 읽는다(여기서는 식별자만 보낸다).
   숫자·SMILES 가드레일은 서버 코드가 강제한다(formula/agents/input_agent.py).

   화면: 처음에는 가운데 입력칸 하나(#hello-dock). 첫 메시지를 보내면 입력칸이 아래(#dock-inner)로 내려가고,
   대화와 단계 카드가 #agent-log(= 대화 전체)에 순서대로 쌓인다. 설계 실행 카드 밑에는 flow.js가 '실험 데이터 입력' 카드를 붙인다. */
(() => {
  const el = (id) => document.getElementById(id);
  const history = [];          // {role, text} — 서버에 최근 12개만 보낸다
  let busy = false;
  let lastNudgeKey = "";
  const PLACEHOLDER = "무엇을 설계할까요? 약 이름(또는 SMILES), 대상 환자, 제형, 1회 용량을 말씀해 주시면 설계 실행을 준비합니다. "
    + "설계가 끝나면 남은 데이터 요청과 다음 행동을 먼저 알려 드립니다.";

  const KIND_LABEL = { start_run: "설계 실행", submit_measurements: "측정값 제출", develop_candidate: "개발 착수" };
  const SOURCE_LABEL = { llm: "LLM 해석", rules: "규칙 기반 해석", "llm+rules": "LLM + 규칙 해석", context: "맥락 요약" };

  function ids() {
    return { tab: "discovery", run_id: window.F1Discovery ? window.F1Discovery.runId() : null, study_id: null };
  }
  const log = () => el("agent-log");

  // ── 뼈대 ────────────────────────────────────────────────────────────────
  function mount() {
    const form = document.createElement("form");
    form.className = "ad-form";
    form.id = "agent-form";
    form.innerHTML = `<label class="sr-only" for="agent-input">에이전트에게 말하기</label>
      <textarea id="agent-input" rows="3" maxlength="2000" placeholder="${esc(PLACEHOLDER)}"></textarea>
      <button type="submit" class="send" id="agent-send" aria-label="보내기" title="보내기 (Enter)">↑</button>`;
    el("agent-box").append(form);
    const chips = document.createElement("div");
    chips.className = "ad-chips";
    chips.id = "agent-chips";
    el("dock-inner").append(chips);
    const model = el("side-model");
    if (model) model.innerHTML = `<label for="llm-select">모델</label><select id="llm-select" aria-describedby="llm-note"></select><small id="llm-note"></small>`;
    form.onsubmit = (e) => { e.preventDefault(); send(); };
    const input = el("agent-input");
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    });
    input.addEventListener("input", () => autosize(input));
    renderChips();
  }

  function autosize(t) {
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight, 220)}px`;
  }

  // 첫 메시지 뒤에는 입력칸을 아래로 내린다(가운데 → 아래)
  function dock() {
    if (document.body.classList.contains("started")) return;
    document.body.classList.add("started");
    el("dock-inner").prepend(el("agent-box"));     // 입력 에이전트 상자만 아래로 — 히어로·시연 카드는 대화 맨 위에 남는다
    el("agent-input").rows = 1;
    el("agent-input").placeholder = "메시지를 입력하세요";
    autosize(el("agent-input"));
  }

  // 모델 선택 — 옵션·권한은 app.js가 /api/meta에서 읽어 f1:llm 이벤트로 알려 준다
  function renderModel(detail) {
    const sel = el("llm-select"), note = el("llm-note");
    if (!sel || !detail) return;
    sel.innerHTML = (detail.options || []).map((o) => {
      const why = !o.available ? " (키 없음)" : !o.allowed ? " (비밀번호 접속 필요)" : "";
      return `<option value="${esc(o.id)}" ${o.available && o.allowed ? "" : "disabled"} ${o.id === detail.id ? "selected" : ""}>${esc(o.label + why)}</option>`;
    }).join("");
    sel.disabled = !detail.id;
    note.innerHTML = detail.role === "full" ? ""
      : `게스트 · 무료 모델만 — <a href="/?locked=formula1&amp;next=%2Fformula1%2F">비밀번호로 접속</a>하면 대회 API를 고를 수 있습니다`;
    sel.onchange = () => {
      if (!window.F1LLM.set(sel.value)) sel.value = window.F1LLM.get();
      else if (document.body.classList.contains("started")) say("agent", { reply: `이제부터 ${sel.options[sel.selectedIndex].text} 모델로 설계·심사·대화를 진행합니다.`, proposals: [], source: "context" });
    };
  }
  document.addEventListener("f1:llm", (e) => renderModel(e.detail));

  function focusAgent() { el("agent-input").focus({ preventScroll: false }); }

  function renderChips() {
    const box = el("agent-chips");
    if (!box) return;
    const chips = ids().run_id ? ["결과 설명해 줘", "다음에 뭘 하면 돼?"] : ["어떤 정보가 필요해?", "성인용 이부프로펜 정제 설계해 줘"];
    box.innerHTML = chips.map((c) => `<button type="button" class="ad-chip">${esc(c)}</button>`).join("");
    box.querySelectorAll(".ad-chip").forEach((b) => { b.onclick = () => { el("agent-input").value = b.textContent; send(); }; });
  }

  // ── 말하기 ────────────────────────────────────────────────────────────
  function say(role, data) {
    dock();
    const row = document.createElement("div");
    row.className = `ad-msg ${role}`;
    if (role === "user") {
      row.innerHTML = `<div class="bubble">${esc(data)}</div>`;
      history.push({ role: "user", text: data });
    } else {
      const src = SOURCE_LABEL[data.source] || "";
      row.innerHTML = `<div class="bubble">${esc(data.reply || "")}
          ${src ? `<span class="ad-src">${esc(src)}</span>` : ""}</div>
        ${(data.asks || []).length ? `<ul class="ad-asks">${data.asks.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
        ${(data.notes || []).length ? `<ul class="ad-notes">${data.notes.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}`;
      (data.proposals || []).forEach((p) => row.append(card(p)));
      history.push({ role: "agent", text: data.reply || "" });
    }
    while (history.length > 12) history.shift();
    log().append(row);
    (data.proposals || []).filter((p) => p.kind === "start_run").slice(-1).forEach((p) =>
      document.dispatchEvent(new CustomEvent("f1:proposal", { detail: { kind: p.kind, row } })));
    row.scrollIntoView({ block: "end", behavior: "smooth" });
    return row;
  }

  function pending(on) {
    busy = on;
    el("agent-send").disabled = on;
    let dots = el("agent-typing");
    if (on && !dots) {
      dots = document.createElement("div");
      dots.id = "agent-typing";
      dots.className = "ad-msg agent typing";
      dots.innerHTML = `<div class="bubble"><span></span><span></span><span></span></div>`;
      log().append(dots);
      dots.scrollIntoView({ block: "end", behavior: "smooth" });
    } else if (!on && dots) dots.remove();
  }

  async function send() {
    const input = el("agent-input");
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    autosize(input);
    const prior = history.slice(-10);
    say("user", text);
    pending(true);
    try {
      const res = await fetch(api("/api/agent/turn"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: prior, llm: (window.F1LLM && window.F1LLM.get()) || "groq", ...ids() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `요청 실패 (${res.status})`);
      pending(false);
      say("agent", data);
    } catch (e) {
      pending(false);
      say("agent", { reply: `요청을 처리하지 못했습니다: ${e.message}`, proposals: [], source: "" });
    }
  }

  // ── 제안 카드 ─────────────────────────────────────────────────────────
  function rows(p) {
    const r = [];
    if (p.kind === "start_run") {
      r.push(["요청", p.request]);
      r.push(["SMILES", p.smiles ? `${p.smiles}` : "없음 — 알려 주세요"]);
      if (p.smiles_source && p.smiles_source.label) r.push(["구조 출처", p.smiles_source.label, p.smiles_source.url]);
      r.push(["1회 용량", p.measured_params && p.measured_params.dose_mg !== undefined ? `${p.measured_params.dose_mg} mg` : "없음 — 알려 주세요"]);
      Object.entries(p.measured_params || {}).filter(([k]) => k !== "dose_mg").forEach(([k, v]) => r.push([k, String(v)]));
      if ((p.required_excipients || []).length) r.push(["반드시 포함", p.required_excipients.join(", ")]);
      if ((p.rejected || []).length) r.push(["허용목록 밖(제외)", p.rejected.join(", ")]);
    } else if (p.kind === "submit_measurements") {
      Object.entries(p.measurements || {}).forEach(([k, v]) => r.push([k, String(v)]));
      r.push(["재평가 범위", "이 값에 의존하는 판정만 — 설계를 처음부터 다시 돌리지 않음"]);
    } else if (p.kind === "develop_candidate") {
      r.push(["후보", p.candidate_id]);
      r.push(["다음", "이 처방을 프로토타입으로 받아 2단계(QTPP → 위험평가 → DoE → 회귀·ANOVA → Design Space)를 시작합니다"]);
    }
    return r;
  }

  function card(p) {
    const c = document.createElement("div");
    c.className = `ad-card${p.ready ? "" : " incomplete"}`;
    if (p.run_id) c.dataset.run = p.run_id;   // 다른 설계가 시작되면 이 카드는 잠긴다
    p._cid = `c${Math.random().toString(36).slice(2, 9)}`;
    c.dataset.card = p._cid;
    c.innerHTML = `<div class="ad-card-head"><span class="ad-kind">${esc(KIND_LABEL[p.kind] || p.kind)}</span>
        <b>${esc(p.title || "")}</b></div>
      <dl>${rows(p).map(([k, v, url]) => `<dt>${esc(k)}</dt><dd>${url
        ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(v)}</a>` : esc(v)}</dd>`).join("")}</dl>
      ${p.ready ? "" : `<p class="ad-missing">빠진 정보(${esc((p.missing || []).join(", "))})를 알려 주시면 실행할 수 있습니다.</p>`}
      ${p.kind === "submit_measurements" ? `<label class="ad-grade">근거 등급
        <select class="ad-grade-sel"><option value="user_statement" selected>사용자 진술</option>
        <option value="self_measured">자체 실측</option><option value="literature">문헌</option></select></label>` : ""}
      <div class="ad-card-actions">
        <button type="button" class="primary ad-run" ${p.ready ? "" : "disabled"}>${p.kind === "start_run" ? "설계 실행" : "실행"}</button>
        ${p.kind === "start_run" ? `<button type="button" class="ad-fill">직접 입력 폼으로</button>` : ""}
        <button type="button" class="ghost ad-dismiss">닫기</button>
      </div>
      <div class="ad-result" hidden></div>`;
    const result = (text, kind = "") => {
      const r = c.querySelector(".ad-result");
      r.hidden = false; r.className = `ad-result ${kind}`; r.textContent = text;
    };
    const lock = () => c.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    c.querySelector(".ad-dismiss").onclick = () => c.remove();
    const fill = c.querySelector(".ad-fill");
    if (fill) fill.onclick = () => { fillForm(p); result("직접 입력 폼에 채웠습니다 — 확인 후 [설계 실행]을 누르세요."); };
    c.querySelector(".ad-run").onclick = async () => {
      const ok = await execute(p, result);
      if (ok) { lock(); c.classList.add("done"); }
    };
    return c;
  }

  function fillForm(p) {
    el("request").value = p.request || "";
    el("smiles").value = p.smiles || "";
    el("pinned").value = (p.required_excipients || []).join(", ");
    document.querySelectorAll("#inputs-body input").forEach((i) => {
      const v = (p.measured_params || {})[i.dataset.key];
      if (v === undefined) return;
      if (i.dataset.type === "bool") i.checked = v === true;
      else i.value = String(v);
    });
    if (typeof updateInputCount === "function") updateInputCount();
    if (window.F1Flow) window.F1Flow.openManual();
  }

  async function execute(p, result) {
    const D = window.F1Discovery;
    try {
      if (p.kind === "start_run") {
        if (D.running()) { result("다른 설계가 실행 중입니다 — 끝난 뒤 다시 눌러 주세요.", "warn"); return false; }
        D.startRunWith(p);
        result("설계를 시작했습니다 — 아래에 단계별 결과가 이어집니다. 진행 과정은 오른쪽 탭에서 볼 수 있습니다.", "ok");
        return true;
      }
      if (p.kind === "submit_measurements") {
        if (D.runId() !== p.run_id) { result("그 사이 다른 설계가 시작되어 이 제안은 더 이상 맞지 않습니다.", "warn"); return false; }
        const gradeSel = document.querySelector(`[data-card="${p._cid}"] .ad-grade-sel`);
        const out = await D.submitMeasurements(p.measurements, gradeSel ? gradeSel.value : "user_statement");
        if (!out) { result("제출이 거부되었습니다 — 알림을 확인해 주세요.", "warn"); return false; }
        document.dispatchEvent(new CustomEvent("f1:drqdone", { detail: { how: "agent" } }));
        result(out.regenerated ? "전략이 바뀌어 후보를 다시 생성했습니다." : "재계산했습니다 — 전략 집합은 그대로입니다.", "ok");
        return true;
      }
      if (p.kind === "develop_candidate") {
        if (D.runId() !== p.run_id) { result("이 카드는 이전 설계의 후보입니다 — 지금 설계의 후보로 다시 요청해 주세요.", "warn"); return false; }
        const r = await D.develop(p.candidate_id);   // 후보 카드의 '이 후보로 개발 착수'와 같은 길(근거 결손 게이트 포함)
        if (r === "waiver") {
          result("근거 결손이 남은 후보입니다 — 후보 카드에 사유 칸을 열었습니다. 사유를 적고 [사유 기록 · 개발 착수]를 누르거나, 확인시험 결과를 넣어 다시 판정하세요.", "warn");
          return true;
        }
        if (r !== "started") { result("2단계로 넘기지 못했습니다 — 알림을 확인해 주세요.", "warn"); return false; }
        result("2단계로 넘겼습니다 — 아래에 프로토타입 카드가 열렸습니다.", "ok");
        return true;
      }
    } catch (e) {
      result(e.message || "실행하지 못했습니다.", "warn");
    }
    return false;
  }

  // ── 먼저 말 걸기 ──────────────────────────────────────────────────────
  let nudgeTimer = null;
  function scheduleNudge(key) {
    clearTimeout(nudgeTimer);
    nudgeTimer = setTimeout(() => nudge(key), 400);
  }
  async function nudge(key) {
    renderChips();
    if (key && key === lastNudgeKey) return;
    try {
      const res = await fetch(api("/api/agent/nudge"), {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(ids()),
      });
      if (!res.ok) return;
      const data = await res.json();
      if (!data.reply) return;
      lastNudgeKey = key;
      say("agent", data);
    } catch (e) { /* 보조 기능 — 실패해도 화면은 돈다 */ }
  }

  // 설계가 끝났을 때만 먼저 말한다(데이터 요청·후보 카드가 먼저 놓인 뒤 — flow.js가 f1:flowready를 보낸다)
  document.addEventListener("f1:flowready", (e) => scheduleNudge(`run:${e.detail.runId}:${e.detail.phase}`));
  // 새 설계가 시작되면 이전 설계에 묶인 카드(측정값 제출·개발 착수)를 잠근다
  document.addEventListener("f1:runstart", (e) => {
    document.querySelectorAll("#agent-log .ad-card[data-run]").forEach((c) => {
      if (c.dataset.run !== e.detail.runId && !c.classList.contains("done")) {
        c.classList.add("stale");
        c.querySelectorAll("button:not(.ad-dismiss)").forEach((b) => { b.disabled = true; });
        const r = c.querySelector(".ad-result");
        if (r) { r.hidden = false; r.textContent = "이전 설계의 카드 — 새 설계가 시작되어 잠겼습니다."; }
      }
    });
    renderChips();
  });

  mount();
  window.F1Agent = { focus: focusAgent, say, dock };
})();
