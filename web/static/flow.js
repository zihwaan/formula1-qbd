/* 대화 흐름 — 1단계 카드를 대화에 순서대로 놓는다(ChatGPT처럼 아래로 쌓이고, 지난 기록은 남는다).

   설계 실행 카드(에이전트 제안) ─ 밑에 '실험 데이터값을 입력하시겠습니까?' + 실험 데이터 입력 카드
   [설계 실행] ─ API 물리화학 카드(가로)
   설계 종료 ─ 심사위원단 카드(소집된 심사관마다 점수·근거) → 데이터 요청이 있으면 데이터 요청 카드 → [값 제출] 또는 [전부 건너뛰기] 뒤에 후보 처방 카드
              데이터 요청이 없으면 바로 후보 처방 카드 → 통과 후보가 있으면 근거 결손 게이트 카드(값은 여기서 한 번에)
   카드는 app.js가 채우는 살아 있는 요소를 옮겨 놓는다(아이디 그대로). 새 설계가 시작되면 앞 설계의 카드는
   그 자리에 사본(읽기 전용)으로 남기고 살아 있는 카드는 새 자리로 옮긴다.
   오른쪽 서랍: 에이전트 흐름 · 지금 무슨 일이 · 실행 트레이스 — 탭을 누르면 열리고 ⤢로 크게/작게. */
(() => {
  const $ = (id) => document.getElementById(id);
  const log = () => $("agent-log");
  let run = null;          // {id, drqShown, candsShown, wantCands}
  let manualRun = false;    // 직접 입력 폼의 [설계 실행]으로 시작했는가

  function sysMsg(label, node, extraClass = "") {
    if (window.F1Agent) window.F1Agent.dock();
    const row = document.createElement("div");
    row.className = `ad-msg sys ${extraClass}`;
    row.innerHTML = label ? `<div class="sys-label">${label}</div>` : "";
    if (node) row.append(node);
    log().append(row);
    return row;
  }

  // 지난 설계의 카드는 읽기 전용 사본으로 남긴다(기록)
  function freeze(node) {
    if (!node || !node.isConnected || node.closest("#stash")) return;
    const copy = node.cloneNode(true);
    copy.removeAttribute("id");
    copy.querySelectorAll("[id]").forEach((x) => x.removeAttribute("id"));
    copy.querySelectorAll("button, input, select, textarea").forEach((x) => { x.disabled = true; });
    copy.classList.add("frozen");
    node.replaceWith(copy);
  }

  function place(node, label, cls) {
    freeze(node);
    return sysMsg(label, node, cls);
  }

  // ── 설계 실행 카드 밑에 실험 데이터 입력 ─────────────────────────────────
  document.addEventListener("f1:proposal", (e) => {
    const card = $("card-inputs");
    const old = card.closest(".ad-msg.sys");
    const row = document.createElement("div");
    row.className = "ad-msg sys";
    row.innerHTML = `<div class="sys-label">실험 데이터값을 입력하시겠습니까? <small>선택 — 비워도 설계 실행을 누를 수 있습니다</small></div>`;
    row.append(card);
    e.detail.row.after(row);
    $("inputs").open = true;
    if (old && old !== row) old.remove();
  });

  // ── 설계 시작: API 물리화학 ─────────────────────────────────────────────
  document.addEventListener("f1:runstart", (e) => {
    const d = e.detail || {};
    // 시연 카드·직접 입력으로 시작한 설계는 요청을 사용자 말풍선으로 남긴다(에이전트 카드로 시작하면 이미 대화에 있다)
    if (d.scenario && window.F1Agent) {
      window.F1Agent.say("user", `시연 — ${d.scenario}: ${d.request}`);
      // 시연 카드도 대화형 흐름과 같게 — 요청 밑에 실험 데이터 입력 카드(시연 쿼리 카드의 값이 채워진 채)를 놓는다
      const card = $("card-inputs");
      const vals = [...card.querySelectorAll("#inputs-body input")].filter((i) => (i.type === "checkbox" ? i.checked : i.value !== ""));
      card.querySelectorAll(".filled").forEach((x) => x.classList.remove("filled"));
      vals.forEach((i) => i.closest("label")?.classList.add("filled"));
      $("inputs").open = true;
      place(card, `실험 데이터값 — ${vals.length ? `시연 쿼리 카드의 값 ${vals.length}개를 넣고 설계를 실행했습니다` : "넣은 값 없이 실행(값을 몰라도 후보부터)"}
        <small>실측은 추정보다 우선 · 비운 칸은 “모른다”로 보고 갈리는 지점에서만 데이터 요청</small>`);
    } else if (manualRun && window.F1Agent) window.F1Agent.say("user", `직접 입력 — ${d.request || "설계 실행"}`);
    manualRun = false;
    ["panel-jury", "drq", "panel-cands", "panel-evidence"].forEach((id) => { const n = $(id); if (n && !n.closest("#stash")) { freeze(n); $("stash").append(n); } });
    run = { id: d.runId, drqShown: false, candsShown: false, wantCands: false, evReady: false, evShown: false, juryShown: false };
    $("chem-empty").hidden = false;
    $("chem-body").hidden = true;
    const chemRow = place($("panel-chem"), "API 물리화학 — 구조에서 계산한 값과 경고", "wide");
    // 위쪽 시연 카드를 눌러도 새 설계가 보이게 — 요청 말풍선부터 화면에 올린다(부드러운 스크롤은 긴 대화에서 도중에 끊긴다)
    const bubble = chemRow.previousElementSibling && chemRow.previousElementSibling.classList.contains("user") ? chemRow.previousElementSibling : chemRow;
    requestAnimationFrame(() => bubble.scrollIntoView({ block: "start", behavior: "auto" }));
    $("drawer-toggle").classList.add("live");
  });

  function showCands() {
    if (!run || run.candsShown) return;
    run.candsShown = true;
    const row = place($("panel-cands"), "후보 처방 — 룰북 게이트 · 심사관 점수 · 다음 행동", "wide");
    requestAnimationFrame(() => row.scrollIntoView({ block: "start", behavior: "smooth" }));
    showEvidence();
    document.dispatchEvent(new CustomEvent("f1:flowready", { detail: { runId: run.id, phase: "cands" } }));
  }

  // 심사위원단 카드 — 설계가 끝나면 데이터 요청·후보 카드보다 먼저(소집된 심사관이 있을 때만)
  function showJury() {
    const D = window.F1Discovery;
    if (!run || run.juryShown || !D || !D.jurySize || !D.jurySize()) return;
    run.juryShown = true;
    const p = $("panel-jury");
    p.hidden = false;
    place(p, "심사위원단 — 소집된 심사관과 후보별 점수·근거", "wide");
  }

  // 근거 결손 게이트 카드 — 통과 후보가 있을 때 후보 카드 다음에 한 번 놓는다(재계산하면 그 자리에서 다시 그려진다)
  function showEvidence() {
    if (!run || run.evShown || !run.evReady || !run.candsShown) return;
    run.evShown = true;
    const p = $("panel-evidence");
    p.hidden = false;
    place(p, "근거 결손 게이트 — 통과 후보들의 선행 근거를 한 번에 입력", "wide");
  }
  document.addEventListener("f1:evidence", (e) => {
    if (!run || (e.detail && e.detail.runId !== run.id)) return;
    if (e.detail && e.detail.candidates > 0) run.evReady = true;
    showEvidence();
  });

  // 설계 종료·재계산·건너뛰기마다 app.js가 f1:run을 보낸다
  document.addEventListener("f1:run", () => {
    const D = window.F1Discovery;
    if (!run || !D || D.running()) return;
    const pending = D.pending();
    // 제약 불가능·설계 없음·목표 재검토로 끝나면 결론(후보 카드)을 먼저 — 데이터 요청으로 결론을 가리지 않는다
    const concluded = ["infeasible", "no_design", "qtpp_review", "error", "exhausted", "escalated"].includes(D.status && D.status());
    if (concluded) { showCands(); return; }
    showJury();
    if (!run.drqShown && pending > 0 && !run.candsShown) {
      run.drqShown = true;
      $("drq").hidden = false;
      const row = place($("drq"), "데이터 요청 — 판정이 갈리는 지점의 실측값", "wide");
      requestAnimationFrame(() => row.scrollIntoView({ block: "start", behavior: "smooth" }));
      document.dispatchEvent(new CustomEvent("f1:flowready", { detail: { runId: run.id, phase: "drq" } }));
      return;
    }
    if (!run.candsShown && (pending === 0 || run.wantCands)) showCands();
  });

  // [값 제출] · [전부 건너뛰기](또는 에이전트 제출) 뒤에 후보 처방 카드
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("#drq-submit, #drq-skip");
    if (b && run) run.wantCands = true;
  }, true);
  // 후보 카드가 이미 대화에 있을 때 측정값을 다시 넣으면(근거 결손 게이트 · 말로 입력) — 다시 판정한 결과를 대화 맨 아래로 옮긴다.
  // 지난 카드는 그 자리에 읽기 전용 기록으로 남는다. 재설계면 새 심사위원단부터.
  document.addEventListener("f1:recomputing", () => { if (run) run.recomputeFromShown = run.candsShown; });
  document.addEventListener("f1:recomputed", (e) => {
    if (!run || !run.recomputeFromShown) return;
    run.recomputeFromShown = false;
    const regen = !!(e.detail && e.detail.regenerated);
    let first = null;
    if (regen && run.juryShown) first = place($("panel-jury"), "심사위원단 — 다시 설계된 후보의 심사", "wide");
    const row = place($("panel-cands"), regen ? "후보 처방 — 전략이 바뀌어 다시 설계하고 다시 판정한 결과" : "후보 처방 — 측정값으로 다시 판정한 결과", "wide");
    if (run.evShown) place($("panel-evidence"), "근거 결손 게이트 — 다시 판정한 결과", "wide");
    const top = first || row;
    requestAnimationFrame(() => top.scrollIntoView({ block: "start", behavior: "smooth" }));
  });
  // 입력 에이전트로 제출한 경우 — 재계산 알림(f1:run)이 이 이벤트보다 먼저 오므로 여기서 바로 후보 카드를 놓는다
  document.addEventListener("f1:drqdone", () => { if (run) { run.wantCands = true; showCands(); } });


  // ── 오른쪽 서랍 ─────────────────────────────────────────────────────────
  const drawer = $("drawer");
  const TITLES = { flow: "에이전트 흐름", narr: "지금 무슨 일이 일어나고 있나", trace: "실행 트레이스" };
  // 넓은 화면은 처음부터 펼쳐 둔다(관측이 늘 보이게) — 좁은 화면은 접어 두고 탭·버튼으로 연다
  const wideScreen = () => window.innerWidth > 1180;
  function openPane(name) {
    drawer.querySelectorAll(".drawer-pane").forEach((p) => { p.hidden = p.dataset.pane !== name; });
    drawer.querySelectorAll(".rail-tab").forEach((t) => t.classList.toggle("on", t.dataset.pane === name));
    $("drawer-title").textContent = TITLES[name];
    if (drawer.dataset.size === "closed") drawer.dataset.size = "open";
    $("drawer-toggle").setAttribute("aria-expanded", "true");
    document.body.classList.add("drawer-open");
    try { localStorage.setItem("f1:drawer", "open"); } catch (e) { /* 무시 */ }
  }
  function closeDrawer() {
    drawer.dataset.size = "closed";
    drawer.querySelectorAll(".rail-tab").forEach((t) => t.classList.remove("on"));
    $("drawer-toggle").setAttribute("aria-expanded", "false");
    document.body.classList.remove("drawer-open", "drawer-wide");
    try { localStorage.setItem("f1:drawer", "closed"); } catch (e) { /* 무시 */ }
  }
  drawer.querySelectorAll(".rail-tab").forEach((t) => t.addEventListener("click", () => {
    if (t.classList.contains("on") && drawer.dataset.size !== "closed") closeDrawer(); else openPane(t.dataset.pane);
  }));
  let pref = null;
  try { pref = localStorage.getItem("f1:drawer"); } catch (e) { /* 무시 */ }
  if (wideScreen() && pref !== "closed") openPane("flow"); else closeDrawer();
  $("drawer-toggle").addEventListener("click", () => (drawer.dataset.size === "closed" ? openPane("flow") : closeDrawer()));
  $("drawer-close").addEventListener("click", closeDrawer);
  $("drawer-size").addEventListener("click", () => {
    const wide = drawer.dataset.size !== "wide";
    drawer.dataset.size = wide ? "wide" : "open";
    document.body.classList.toggle("drawer-wide", wide);
    $("drawer-size").setAttribute("aria-label", wide ? "작게 보기" : "크게 보기");
  });

  // ── 새 설계 · 2단계 기록 메뉴 · 직접 입력 ─────────────────────────────
  const menu = $("s2-menu");
  const closeSide = () => { if (menu) menu.open = false; };
  document.addEventListener("click", (e) => { if (menu && menu.open && !menu.contains(e.target)) menu.open = false; });
  $("new-chat").addEventListener("click", () => { location.href = location.pathname; });
  function openManual() {
    $("manual-slot").append($("manual"));
    $("manual").open = true;
    $("manual-sheet").hidden = false;
  }
  $("manual-open").addEventListener("click", openManual);
  $("manual-close").addEventListener("click", () => { $("manual-sheet").hidden = true; });
  $("run").addEventListener("click", () => { $("manual-sheet").hidden = true; manualRun = true; }, true);

  async function refreshS2() {
    try {
      const r = await fetch(api("/api/stage2/studies"));
      if (!r.ok) return;
      const d = await r.json();
      const ul = $("side-s2");
      if (!d.studies.length) return;
      if (!ul) return;
      ul.innerHTML = d.studies.map((s) => `<li><button type="button" data-s2="${esc(s.study_id)}"><b>${esc(s.title || s.study_id)}</b>
        <small>${esc(s.status === "done" ? "완료" : `진행 중 · ${s.status}`)}</small></button></li>`).join("");
      ul.querySelectorAll("[data-s2]").forEach((b) => b.addEventListener("click", () => { closeSide(); window.F1Stage2.open(b.dataset.s2); }));
    } catch (e) { /* 보조 */ }
  }
  document.addEventListener("f1:stage2", refreshS2);
  // 목록(휴대폰 시트)에서 시연을 누르면 시트를 닫고 대화로 돌아간다
  document.addEventListener("f1:runstart", closeSide);
  document.addEventListener("f1:stage2", closeSide);
  refreshS2();

  window.F1Flow = { openManual, sysMsg, freeze, openPane, closeDrawer };
})();
