/* 입력 에이전트 — 사용자와 두 그래프 사이의 대화 창.

   - 말을 **제안 카드**로 바꾼다(설계 실행 · 측정값 제출 · 스튜디오 행동 · 개발 착수).
     카드의 [실행]을 눌러야 반영된다. 실행은 사람이 버튼을 누른 것과 같은 경로
     (startRun · submitMeasurements · F1Studio.runAction)로 간다.
   - 상태가 바뀌면(설계 종료 · 재계산 · 스튜디오 상태 전이 · 탭 이동) 먼저 말을 건다(nudge).
   - 맥락은 서버가 run/study에서 직접 읽는다. 여기서는 식별자만 보낸다.
   - 숫자·SMILES 가드레일은 서버 코드가 강제한다(formula/agents/input_agent.py). */
(() => {
  const el = (id) => document.getElementById(id);
  const history = [];          // {role, text} — 서버에 최근 12개만 보낸다
  let open = false;
  let busy = false;
  let unread = 0;
  let lastNudgeKey = "";

  const KIND_LABEL = {
    start_run: "설계 실행", submit_measurements: "측정값 제출", studio_action: "스튜디오 행동",
    develop_candidate: "개발 착수",
  };
  const SOURCE_LABEL = { llm: "LLM 해석", rules: "규칙 기반 해석", "llm+rules": "LLM + 규칙 해석", context: "맥락 요약" };
  const ACTION_LABEL = {
    required_data: "진입 자료 제출", cqa_edit: "CQA 변경", cqa_approve: "CQA 계약 승인", fmea_approve: "FMEA 승인",
    factor_data: "요인 범위·근거 제출", factor_approve: "요인·수준값 승인", plan_approve: "설계 승인",
    model_reduce: "모델 축소", model_accept: "과적합 flag 수용", model_approve: "모델 판단 완료",
    region_approve: "잠정 영역 승인", vplan_lock: "확인계획 잠금", finalize: "최종 승인",
    directive_approve: "진단 방향 승인",
  };

  function tab() { return window.F1Studio ? window.F1Studio.tab() : "discovery"; }
  function ids() {
    const cur = window.F1Studio && window.F1Studio.current();
    return {
      tab: tab(),
      run_id: window.F1Discovery ? window.F1Discovery.runId() : null,
      study_id: cur ? cur.studyId : null,
    };
  }

  // ── 뼈대 ──────────────────────────────────────────────────────────────
  function mount() {
    const launcher = document.createElement("button");
    launcher.id = "agent-launcher";
    launcher.type = "button";
    launcher.className = "agent-launcher";
    launcher.setAttribute("aria-controls", "agent-dock");
    launcher.setAttribute("aria-expanded", "false");
    launcher.innerHTML = `<span class="al-dot" aria-hidden="true"></span><span class="al-text">입력 에이전트</span><span class="al-badge" hidden></span>`;
    launcher.onclick = () => toggle(!open);

    const peek = document.createElement("div");
    peek.id = "agent-peek";
    peek.className = "agent-peek";
    peek.hidden = true;
    peek.onclick = () => toggle(true);

    const dock = document.createElement("aside");
    dock.id = "agent-dock";
    dock.className = "agent-dock";
    dock.hidden = true;
    dock.setAttribute("aria-label", "입력 에이전트");
    dock.innerHTML = `
      <header class="ad-head">
        <div><b>입력 에이전트</b><small id="agent-ctx">맥락: 후보 탐색</small></div>
        <button type="button" class="ad-close" aria-label="닫기">✕</button>
      </header>
      <p class="ad-intro">말로 요청하면 실행할 수 있는 입력으로 정리해 제안합니다. 판정은 룰북이 하고,
        실행은 카드의 [실행]을 눌러야 반영됩니다. 글에 없는 숫자나 구조식은 채우지 않습니다.</p>
      <div class="ad-log" id="agent-log" role="log" aria-live="polite"></div>
      <div class="ad-chips" id="agent-chips"></div>
      <form class="ad-form" id="agent-form">
        <label class="sr-only" for="agent-input">에이전트에게 말하기</label>
        <textarea id="agent-input" rows="2" maxlength="2000" placeholder="예: 소아용 현탁액으로 설계해 줘 · 녹는점 측정값 알려 줄게 · 왜 막혔어?"></textarea>
        <button type="submit" class="primary" id="agent-send">보내기</button>
      </form>`;
    document.body.append(launcher, peek, dock);
    dock.querySelector(".ad-close").onclick = () => toggle(false);
    el("agent-form").onsubmit = (e) => { e.preventDefault(); send(); };
    el("agent-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && open) toggle(false); });
    renderChips();
    say("agent", {
      reply: "약 이름(또는 SMILES), 대상 환자, 제형, 1회 용량을 말씀해 주시면 설계 실행을 준비합니다. "
        + "설계가 끝나면 남은 데이터 요청과 다음 행동을 먼저 알려 드립니다.",
      proposals: [], source: "context",
    }, { quiet: true });
  }

  function toggle(on) {
    open = on;
    el("agent-dock").hidden = !on;
    el("agent-launcher").setAttribute("aria-expanded", String(on));
    el("agent-launcher").classList.toggle("on", on);
    document.body.classList.toggle("agent-open", on);
    if (on) {
      unread = 0; badge(); el("agent-peek").hidden = true;
      updateCtx();
      setTimeout(() => el("agent-input").focus({ preventScroll: true }), 30);
      const log = el("agent-log"); log.scrollTop = log.scrollHeight;
    }
  }

  function badge() {
    const b = document.querySelector("#agent-launcher .al-badge");
    b.hidden = !unread;
    b.textContent = unread > 9 ? "9+" : String(unread);
  }

  function updateCtx() {
    const i = ids();
    const cur = window.F1Studio && window.F1Studio.current();
    el("agent-ctx").textContent = i.tab === "studio"
      ? `맥락: 개발 스튜디오${cur ? ` · ${cur.status}` : " · study 없음"}`
      : `맥락: 후보 탐색${i.run_id ? ` · ${i.run_id.slice(0, 8)}` : ""}`;
    renderChips();
  }

  function renderChips() {
    const box = el("agent-chips");
    if (!box) return;
    const i = ids();
    const chips = i.tab === "studio"
      ? ["지금 무엇을 해야 해?", "왜 막혔어?"]
      : i.run_id ? ["결과 설명해 줘", "다음에 뭘 하면 돼?"] : ["어떤 정보가 필요해?"];
    box.innerHTML = chips.map((c) => `<button type="button" class="ad-chip">${esc(c)}</button>`).join("");
    box.querySelectorAll(".ad-chip").forEach((b) => { b.onclick = () => { el("agent-input").value = b.textContent; send(); }; });
  }

  // ── 말하기 ────────────────────────────────────────────────────────────
  function say(role, data, opts = {}) {
    const log = el("agent-log");
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
      if (!open && !opts.quiet) {
        unread += 1; badge();
        const peek = el("agent-peek");
        peek.textContent = data.reply || "";
        peek.hidden = !data.reply;
      }
    }
    while (history.length > 12) history.shift();
    log.append(row);
    log.scrollTop = log.scrollHeight;
  }

  function pending(on) {
    busy = on;
    el("agent-send").disabled = on;
    el("agent-send").textContent = on ? "읽는 중…" : "보내기";
    let dots = el("agent-typing");
    if (on && !dots) {
      dots = document.createElement("div");
      dots.id = "agent-typing";
      dots.className = "ad-msg agent typing";
      dots.innerHTML = `<div class="bubble"><span></span><span></span><span></span></div>`;
      el("agent-log").append(dots);
      el("agent-log").scrollTop = el("agent-log").scrollHeight;
    } else if (!on && dots) dots.remove();
  }

  async function send() {
    const input = el("agent-input");
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    const prior = history.slice(-10);
    say("user", text);
    pending(true);
    try {
      const res = await fetch(api("/api/agent/turn"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: prior, ...ids() }),
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
    } else if (p.kind === "studio_action") {
      r.push(["행동", `${ACTION_LABEL[p.action] || p.action} (${p.action})`]);
      if (p.payload && Object.keys(p.payload).length) r.push(["내용", JSON.stringify(p.payload, null, 1)]);
      if (p.confirm_note) r.push(["주의", p.confirm_note]);
    } else if (p.kind === "develop_candidate") {
      r.push(["후보", p.candidate_id]);
      r.push(["다음", "불변 Handoff를 만들고 개발 스튜디오로 넘어갑니다"]);
    }
    return r;
  }

  function card(p) {
    const c = document.createElement("div");
    c.className = `ad-card${p.ready ? "" : " incomplete"}`;
    c.innerHTML = `<div class="ad-card-head"><span class="ad-kind">${esc(KIND_LABEL[p.kind] || p.kind)}</span>
        <b>${esc(p.title || "")}</b></div>
      <dl>${rows(p).map(([k, v, url]) => `<dt>${esc(k)}</dt><dd>${url
        ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(v)}</a>` : k === "내용" ? `<pre>${esc(v)}</pre>` : esc(v)}</dd>`).join("")}</dl>
      ${p.ready ? "" : `<p class="ad-missing">빠진 정보(${esc((p.missing || []).join(", "))})를 알려 주시면 실행할 수 있습니다.</p>`}
      <div class="ad-card-actions">
        <button type="button" class="primary ad-run" ${p.ready ? "" : "disabled"}>실행</button>
        ${p.kind === "start_run" ? `<button type="button" class="ad-fill">폼에만 채우기</button>` : ""}
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
    if (fill) fill.onclick = () => { fillForm(p); result("설계 폼에 채웠습니다 — 확인 후 [실행]을 누르세요."); };
    c.querySelector(".ad-run").onclick = async () => {
      const ok = await execute(p, result);
      if (ok) { lock(); c.classList.add("done"); }
    };
    return c;
  }

  function fillForm(p) {
    if (window.F1Studio) window.F1Studio.showTab("discovery");
    el("request").value = p.request || "";
    el("smiles").value = p.smiles || "";
    el("pinned").value = (p.required_excipients || []).join(", ");
    document.querySelectorAll("#inputs-body input").forEach((i) => {
      const v = (p.measured_params || {})[i.dataset.key];
      if (i.dataset.type === "bool") i.checked = v === true;
      else i.value = v === undefined ? "" : String(v);
    });
    if (typeof updateInputCount === "function") updateInputCount();
    el("request").scrollIntoView({ block: "center", behavior: "smooth" });
  }

  async function execute(p, result) {
    const D = window.F1Discovery, S = window.F1Studio;
    try {
      if (p.kind === "start_run") {
        if (D.running()) { result("다른 설계가 실행 중입니다 — 끝난 뒤 다시 눌러 주세요.", "warn"); return false; }
        S && S.showTab("discovery");
        D.startRunWith(p);
        result("설계를 시작했습니다 — 그래프와 해설이 진행을 보여 줍니다. 끝나면 다음 행동을 알려 드립니다.", "ok");
        if (window.matchMedia("(max-width: 760px)").matches) toggle(false);
        return true;
      }
      if (p.kind === "submit_measurements") {
        if (D.runId() !== p.run_id) { result("그 사이 다른 설계가 시작되어 이 제안은 더 이상 맞지 않습니다.", "warn"); return false; }
        S && S.showTab("discovery");
        const out = await D.submitMeasurements(p.measurements);
        if (!out) { result("제출이 거부되었습니다 — 화면 알림을 확인해 주세요.", "warn"); return false; }
        result(out.regenerated ? "전략이 바뀌어 후보를 다시 생성했습니다." : "재계산했습니다 — 전략 집합은 그대로입니다.", "ok");
        return true;
      }
      if (p.kind === "studio_action") {
        const cur = S.current();
        if (!cur || cur.studyId !== p.study_id || cur.version !== p.state_version) {
          result("스튜디오 상태가 그 사이 바뀌었습니다 — 지금 상태로 다시 물어봐 주세요.", "warn"); return false;
        }
        S.showTab("studio");
        const ok = await S.runAction(p.action, p.payload);
        if (!ok) {
          const err = S.lastError();
          result(`룰북이 막았습니다: ${err ? err.message : "사유 미상"}`, "warn");
          return false;
        }
        result("반영했습니다 — 질문 카드가 다음 단계로 바뀌었습니다.", "ok");
        return true;
      }
      if (p.kind === "develop_candidate") {
        await S.startFromCandidate(p.run_id, p.candidate_id);
        result("개발 스튜디오로 넘겼습니다.", "ok");
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
    updateCtx();
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

  document.addEventListener("f1:run", (e) => scheduleNudge(`run:${e.detail.runId}:${Date.now()}`));
  document.addEventListener("f1:study", (e) => { if (tab() === "studio") scheduleNudge(`study:${e.detail.studyId}:${e.detail.status}`); });
  document.addEventListener("f1:tab", () => updateCtx());

  mount();
  window.F1Agent = { open: () => toggle(true), close: () => toggle(false) };
})();
