/* Formula 1 대시보드 — TraceEvent 스트림 하나만 소비해 화면 전체를 그린다. */

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";

/* 서브경로 배포(zihwan.com/formula1) 대응 — 서버가 index.html에 주입한다.
   단독 실행이면 빈 문자열이라 예전과 똑같이 /api/... 로 나간다. */
const BASE = window.__BASE__ || "";
const api = (path) => `${BASE}${path}`;

/* 화면에 들어오는 값은 전부 남이 만든 것이다 — LLM이 지은 성분명·심사 소견,
   약대생 팀이 채운 CSV 행, 사용자가 입력한 요구 문장. 이스케이프 없이 innerHTML에
   넣으면 그대로 실행된다. 문자열 보간에는 반드시 esc()를 통과시킨다. */
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[ch]));

/* 사용자에게 상태·오류를 알리는 단일 통로. aria-live라 스크린리더도 읽는다. */
let noticeTimer = null;
function notice(message, kind = "info", persist = false) {
  const box = $("notice");
  box.textContent = message;
  box.className = `notice ${kind}`;
  box.hidden = false;
  clearTimeout(noticeTimer);
  if (!persist) noticeTimer = setTimeout(() => { box.hidden = true; }, 7000);
}
function clearNotice() {
  clearTimeout(noticeTimer);
  $("notice").hidden = true;
}

let runId = null;
let source = null;
const candidates = new Map();   // candidate_id → {recipe, verdicts[], judges[], gate}

/* ── 고정 그래프 레이아웃 ────────────────────────────────────────────
   kind: det(결정론) | llm(LLM 판단) | jud(동적 심사관) */
const NODES = [
  { id: "intake",    x:  30, y: 30, w: 120, label: "intake",    sub: "요구 → 스펙",     kind: "llm" },
  { id: "route",     x: 180, y: 30, w: 120, label: "route",     sub: "유동성 → 공정",   kind: "det" },
  { id: "generate",  x: 330, y: 30, w: 130, label: "generate",  sub: "후보 병렬 설계",  kind: "llm" },
  { id: "gate",      x: 490, y: 30, w: 130, label: "gate",      sub: "룰북 판정",       kind: "det" },
  { id: "summon",    x: 650, y: 30, w: 120, label: "summon",    sub: "심사관 소집",     kind: "det" },
  { id: "consensus", x: 810, y: 30, w: 140, label: "consensus", sub: "가중 합의",       kind: "det" },
  { id: "reflect",   x: 490, y: 210, w: 130, label: "reflect",  sub: "재설계 지시",     kind: "llm" },
];
const EDGES = [
  ["intake", "route"], ["route", "generate"], ["generate", "gate"],
  ["gate", "summon"], ["summon", "consensus"],
];
const NODE_H = 46;

function buildGraph() {
  const svg = $("graph");
  // 화살촉 색은 CSS 토큰(.arrowhead)에 맡긴다 — 라이트/다크 전환에 따라 같이 바뀌어야 한다.
  svg.innerHTML = `<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" class="arrowhead"/></marker></defs>`;

  const byId = Object.fromEntries(NODES.map((n) => [n.id, n]));
  for (const [from, to] of EDGES) {
    const a = byId[from], b = byId[to];
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", `M ${a.x + a.w} ${a.y + NODE_H / 2} L ${b.x} ${b.y + NODE_H / 2}`);
    path.setAttribute("class", "edge");
    path.dataset.edge = `${from}->${to}`;
    svg.appendChild(path);
  }
  // 반성 루프: gate → reflect → generate
  for (const [d, key] of [
    [`M 555 76 L 555 210`, "gate->reflect"],
    [`M 490 233 L 395 233 L 395 76`, "reflect->generate"],
  ]) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("class", "edge loop");
    path.dataset.edge = key;
    svg.appendChild(path);
  }
  NODES.forEach((n) => svg.appendChild(nodeEl(n)));
}

function nodeEl(n) {
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("class", `node ${n.kind}`);
  g.id = `node-${n.id}`;
  const rect = document.createElementNS(SVG_NS, "rect");
  rect.setAttribute("x", n.x); rect.setAttribute("y", n.y);
  rect.setAttribute("width", n.w); rect.setAttribute("height", NODE_H);
  const label = document.createElementNS(SVG_NS, "text");
  label.setAttribute("x", n.x + n.w / 2); label.setAttribute("y", n.y + 20);
  label.setAttribute("text-anchor", "middle"); label.textContent = n.label;
  const sub = document.createElementNS(SVG_NS, "text");
  sub.setAttribute("x", n.x + n.w / 2); sub.setAttribute("y", n.y + 35);
  sub.setAttribute("text-anchor", "middle"); sub.setAttribute("class", "sub");
  sub.textContent = n.sub;
  g.append(rect, label, sub);
  return g;
}

/* 심사관 노드는 소집될 때 그 자리에서 만들어진다 — 자기조직형의 시각적 증거 */
const judgeNodes = new Map();
function addJudgeNode(reviewerId, persona) {
  if (judgeNodes.has(reviewerId)) return;
  const index = judgeNodes.size;
  const node = {
    id: `judge-${reviewerId}`, x: 650, y: 100 + index * 56, w: 150,
    label: reviewerId, sub: persona.slice(0, 14), kind: "jud",
  };
  judgeNodes.set(reviewerId, node);
  const svg = $("graph");
  const edge = document.createElementNS(SVG_NS, "path");
  edge.setAttribute("d", `M 710 76 L 710 ${node.y}`);
  edge.setAttribute("class", "edge loop");
  svg.appendChild(edge);
  svg.appendChild(nodeEl(node));
}

function setNode(id, state) {
  const el = $(`node-${id}`);
  if (!el) return;
  if (state === "active") el.classList.add("active");
  else { el.classList.remove("active"); el.classList.add("done"); }
}

function resetGraph() {
  judgeNodes.clear();
  buildGraph();
}

/* ── 트레이스 ───────────────────────────────────────────────────── */
function addTrace(seq, node, msg, cls = "", ruleId = null) {
  const row = document.createElement("div");
  row.className = `ev ${cls}` + (ruleId ? " clickable" : "");
  row.innerHTML = `<span class="seq">${esc(seq)}</span><span class="node">${esc(node)}</span>
                   <span class="msg"></span>`;
  row.querySelector(".msg").textContent = msg;
  if (ruleId) row.onclick = () => showRule(ruleId);
  const trace = $("trace");
  trace.appendChild(row);
  trace.scrollTop = trace.scrollHeight;
}

/* ── 이벤트 → 화면 ──────────────────────────────────────────────── */
function handle(kind, ev) {
  const p = ev.payload || {};
  narrateEvent(kind, ev, p);
  switch (kind) {
    case "run.start":
      addTrace(ev.seq, "run", `실행 시작 · ${p.request}`);
      break;

    case "node.enter": {
      const base = ev.node.split(":")[0];
      setNode(base === "generator" ? "generate" : base, "active");
      addTrace(ev.seq, ev.node, "시작");
      break;
    }
    case "node.exit": {
      const base = ev.node.split(":")[0];
      setNode(base === "generator" ? "generate" : base, "done");
      if (p.strategies) addTrace(ev.seq, ev.node, `전략 선정: ${p.strategies.join(", ")}`);
      else if (p.summoned) addTrace(ev.seq, ev.node, `심사관 ${p.summoned.length}명 소집`);
      break;
    }

    case "predictions": renderPredictions(p); break;
    case "literature": renderLiterature(p); break;
    case "chem.profile": renderChem(p);
      addTrace(ev.seq, "intake", `RDKit 계산 완료 · 플래그 ${(p.flags||[]).filter(f=>f.present).length}건`);
      break;

    case "candidate":
      candidates.set(p.candidate.candidate_id, { recipe: p.candidate, verdicts: [], judges: [] });
      addTrace(ev.seq, ev.node, `후보 생성 ${p.candidate.candidate_id} (${p.source})`);
      renderCandidates();
      break;

    case "rule.fired": {
      const entry = candidates.get(p.candidate_id);
      if (entry) entry.verdicts.push(p);
      addTrace(ev.seq, "gate",
        `${p.rulebook_id}/${p.rule_id} → ${p.status}${p.provisional ? " (잠정)" : ""} · ${p.reason}`,
        p.status, p.rule_id);
      renderCandidates();
      break;
    }
    case "verdict": {
      const entry = candidates.get(p.candidate_id);
      if (entry) entry.gate = p;
      addTrace(ev.seq, "gate",
        `${p.candidate_id}: ${p.passed ? "통과" : "반려"} (판정 ${p.total} · 위반 ${p.failures})`,
        p.passed ? "" : "hard_fail");
      renderCandidates();
      break;
    }

    case "judge.summoned":
      addJudgeNode(p.reviewer_id, p.persona);
      setNode(`judge-${p.reviewer_id}`, "active");
      addTrace(ev.seq, ev.node, `소집 — 조건: ${p.summon_condition} (가중치 ${p.weight})`);
      break;
    case "judge.token":
      streamToken(p.candidate_id, p.reviewer_id, p.delta);
      break;
    case "judge.verdict": {
      setNode(`judge-${p.reviewer_id}`, "done");
      const entry = candidates.get(p.rulebook_id);
      if (entry) {
        // 반성 루프로 같은 후보가 다시 심사되면 소견이 쌓인다 — 심사관당 최신 1건만 남긴다.
        const at = entry.judges.findIndex((j) => j.reviewer_id === p.reviewer_id);
        if (at >= 0) entry.judges[at] = p;
        else entry.judges.push(p);
      }
      addTrace(ev.seq, ev.node, `점수 ${p.score} — ${p.rationale.slice(0, 80)}`);
      renderCandidates();
      break;
    }

    case "consensus": renderConsensus(p);
      addTrace(ev.seq, "consensus", `선정: ${p.winner || "없음"} (보고 ${p.reported}건)`);
      break;

    case "reflect":
      addTrace(ev.seq, "reflect", `${p.root_cause} → ${p.directive}`, "warn");
      break;

    case "warning":
      addTrace(ev.seq, ev.node, p.reason + (p.fallback ? " → 규칙 기반 대체" : ""), "warn");
      if (p.fallback) degraded.add(ev.node);
      break;
    case "error":
      addTrace(ev.seq, ev.node, `오류: ${p.error}`, "hard_fail");
      notice(`실행 중 오류가 발생했습니다 — ${p.error}`, "error", true);
      break;
    case "wetlab": renderWetlab(p); break;
    case "run.end":
      addTrace(ev.seq, "run", `완료 · status=${p.status} · winner=${p.winner || "없음"}`);
      finishRun(p);
      break;
  }
}

/* ── 렌더러 ─────────────────────────────────────────────────────── */
function renderChem(p) {
  // SMARTS 검사가 별도 입력 없이 바로 쓸 수 있게 이번 실행의 분자를 기억한다.
  lastSmiles = p.parent_smiles || p.smiles || "";
  $("chem-empty").hidden = true;
  $("chem-body").hidden = false;
  $("mol-svg").innerHTML = p.svg || '<div class="empty">구조 없음</div>';
  $("mol-id").textContent = p.smiles
    ? `${p.api_name}\n${p.smiles}` + (p.is_salt ? `\nparent: ${p.parent_smiles}` : "")
    : `${p.api_name} — SMILES 미상`;

  $("mol-flags").innerHTML = (p.flags || []).map((f) =>
    `<span class="flag ${f.present ? "on" : ""}">${esc(f.flag_name)}</span>`).join("");

  $("mol-desc").innerHTML = Object.entries(p.descriptors || {}).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td>${Number(v).toFixed(2)}</td></tr>`).join("");

  $("mol-est").innerHTML = (p.estimates || []).map((e) =>
    `<div class="est"><b>${esc(e.property)}</b> = ${esc(e.value)}
     <span class="${e.confidence === "low" ? "lo" : ""}">[${esc(e.confidence)}]</span></div>`).join("");

  $("mol-warn").innerHTML = (p.warnings || []).length
    ? `<div class="warn">⚠ ${p.warnings.map(esc).join("<br>⚠ ")}</div>` : "";
}

function renderCandidates() {
  const box = $("cands");
  if (!candidates.size) return;
  $("cand-count").textContent = `${candidates.size}건`;
  box.innerHTML = "";
  for (const [id, entry] of candidates) {
    const gate = entry.gate;
    const card = document.createElement("div");
    card.className = "card " + (gate ? (gate.passed ? "pass" : "fail") : "");
    const ings = entry.recipe.ingredients
      .map((i) => `${esc(i.name)} ${esc(i.amount_mg ?? "-")}mg`).join(" · ");
    const chips = entry.verdicts.map((v) =>
      `<span class="chip ${esc(v.status)}" data-rule="${esc(v.rule_id)}">${esc(v.rule_id)}</span>`).join("");
    const judges = entry.judges.map((j) =>
      `<div class="judge-note ${j.source === "deterministic-fallback" ? "stand-in" : ""}"><b>${esc(j.persona)}</b> ${esc(j.score)}${j.source === "deterministic-fallback" ? ' <span class="stand-in-tag">규칙 기반 대체 점수 · LLM 미사용</span>' : ""} — ${esc(j.rationale)}</div>`).join("");
    card.innerHTML = `
      <h4>${esc(id)}<span class="tag">${esc(entry.recipe.strategy)} · ${esc(entry.recipe.process || "")}</span></h4>
      <div class="ing">${ings}</div>
      <div class="ing">포장: ${esc(entry.recipe.packaging || "-")}</div>
      <div class="chips">${chips}</div>${judges}`;
    card.querySelectorAll(".chip").forEach((chip) => {
      chip.onclick = () => showRule(chip.dataset.rule);
    });
    box.appendChild(card);
  }
}

function renderConsensus(p) {
  const el = $("consensus");
  el.hidden = false;
  const rows = (p.ranked || []).map((r) =>
    `<div>${r.rank ? `#${esc(r.rank)} ` : "— "}<b>${esc(r.candidate_id)}</b>
      점수 ${esc(r.weighted_score ?? "-")} · 분산 ${esc(r.variance ?? "-")} · 심사관 ${esc(r.reviewers)}
      ${r.low_confidence ? " <span class='tag'>저신뢰</span>" : ""}
      ${r.eligible ? "" : " <span class='tag'>반려</span>"}</div>`).join("");
  el.innerHTML = `<h3>합의 (${esc(p.model)})</h3>
    <div class="win">선정: ${esc(p.winner || "없음")}</div>${rows}
    <div class="tag" style="margin-top:6px">심사관 점수는 순위 결정 전용 — 반려 권한 없음</div>
    ${(p.rulebook_feedback || []).map((f) => `<div class="warn">${esc(f)}</div>`).join("")}`;
}

const tokenBuffers = new Map();
function streamToken(candidateId, reviewerId, delta) {
  const key = `${candidateId}/${reviewerId}`;
  if (!tokenBuffers.has(key)) {
    const row = document.createElement("div");
    row.className = "ev";
    row.innerHTML = `<span class="seq">…</span><span class="node">${esc(reviewerId)}</span>
                     <span class="msg tok"></span>`;
    $("trace").appendChild(row);
    tokenBuffers.set(key, row.querySelector(".msg"));
  }
  const target = tokenBuffers.get(key);
  target.textContent += delta;
  $("trace").scrollTop = $("trace").scrollHeight;
}

/* Lab-in-the-loop 결과 — 판독(LLM) → 판정(규칙) → 지시(LLM + 확인시험 마스터).
   세 단계를 화면에서도 분리해 보여준다: 무엇을 읽었는지 / 규칙이 뭘 잡았는지 / 다음에 뭘 할지. */
function renderWetlab(report) {
  const read = report.read || {};
  const directive = report.directive || {};
  const off = (report.findings || []).filter((f) => f.off_target);

  const measured = Object.entries(read.measurements || {});
  const readBlock = measured.length
    ? `<h4>1 · 판독한 측정값 <small>문장에 적힌 수치만</small></h4>
       <table class="ll-read">${measured.map(([k, v]) =>
         `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>
       ${(read.observations || []).length
         ? `<div class="ll-obs">관찰: ${(read.observations || []).map(esc).join(" · ")}</div>` : ""}
       ${(read.unreadable || []).length
         ? `<div class="warn">판독 못한 표현: ${(read.unreadable || []).map(esc).join(" / ")}</div>` : ""}`
    : "";

  const verdictBlock = `<h4>2 · 규격 판정 <small>결정론 · 같은 데이터면 같은 결과</small></h4>
    <div class="ll-summary ${off.length ? "off" : "ok"}">${esc(report.summary)}</div>
    ${off.map((f) => `<div class="ll-finding">
        <b>${esc(f.metric)}</b> ${esc(f.measured)} (목표 ${esc(f.operator)}${esc(f.target)})
        <div>${esc(f.interpretation)}</div>
        <div class="ll-fix">→ ${esc(f.suggested_revision)}</div>
      </div>`).join("")}`;

  const experiments = directive.experiments || [];
  const directiveBlock = experiments.length
    ? `<h4>3 · 다음 실험 지시 <small>확인시험 마스터 ${esc(directive.master_size || "")}종에서 선정</small></h4>
       ${directive.hypothesis ? `<div class="ll-hypo"><b>가설</b> ${esc(directive.hypothesis)}</div>` : ""}
       ${experiments.map((e, i) => `<div class="ll-exp">
          <div class="ll-exp-head"><span class="ll-order">${i + 1}</span>
            <b>${esc(e.test_name)}</b><code class="ll-id">${esc(e.test_id)}</code></div>
          <div class="ll-why">${esc(e.why)}</div>
          <div class="ll-spec">방법: ${esc(e.test_design)}</div>
          <div class="ll-spec">측정: ${esc(e.output_variable)}${e.unit ? ` (${esc(e.unit)})` : ""}
            · 판정: ${esc(e.acceptance_logic)}</div>
          ${e.source_reference ? `<div class="ll-src">근거 ${e.source_url
            ? `<a href="${esc(e.source_url)}" target="_blank" rel="noopener">${esc(e.source_reference)}</a>`
            : esc(e.source_reference)}</div>` : ""}
        </div>`).join("")}
       ${directive.source === "deterministic-fallback"
         ? '<div class="warn">이 지시는 LLM 없이 규칙으로 선정됐습니다 (카테고리 매칭).</div>' : ""}`
    : '<div class="warn">다음 실험을 특정하지 못했습니다.</div>';

  $("wl-out").innerHTML = readBlock + verdictBlock + directiveBlock;
}

/* ── 근거 드릴다운 ──────────────────────────────────────────────── */
let modalOpener = null;

async function showRule(ruleId) {
  if (!ruleId) return;
  modalOpener = document.activeElement;
  const res = await fetch(api(`/api/rules/${encodeURIComponent(ruleId)}`));
  const body = $("modal-body");
  if (!res.ok) {
    body.innerHTML = `<h3>${esc(ruleId)}</h3><div class="src">원본 행을 찾지 못했습니다.</div>`;
  } else {
    const d = await res.json();
    body.innerHTML = `<h3>${esc(d.rule_id)} · ${esc(d.rulebook_id)}</h3>
      <div class="src">${esc(d.file)} · 전략 ${esc(d.strategy)} · polarity ${esc(d.polarity)}
        ${d.sources_doc ? `<br>출처 문서: ${esc(d.sources_doc)}` : ""}</div>
      <table>${Object.entries(d.row).filter(([, v]) => v !== "")
        .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>`;
  }
  $("modal").hidden = false;
  document.body.style.overflow = "hidden";
  $("modal-close").focus();
}

function closeRule() {
  $("modal").hidden = true;
  document.body.style.overflow = "";
  if (modalOpener && document.contains(modalOpener)) modalOpener.focus();
  modalOpener = null;
}
$("modal-close").onclick = closeRule;
$("modal").onclick = (e) => { if (e.target.id === "modal") closeRule(); };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("modal").hidden) closeRule();
});

/* ── 실행 ───────────────────────────────────────────────────────── */
let running = false;
const degraded = new Set();   // 이번 실행에서 규칙 기반 대체로 내려간 노드

/* 스트림이 끊겨도 실행을 잃지 않는다.
   서버는 재구독하는 클라이언트에게 이벤트 이력을 처음부터 다시 흘려 주므로
   (`stream_run`의 bus.history 재생), 화면을 비우고 다시 붙으면 상태가 그대로 복원된다.
   실제로 라이브에서 네트워크 계층 오류(QUIC)로 스트림이 끊기는 것을 관측했다. */
const MAX_RECONNECT = 3;
let streamClosedCleanly = false;
let reconnects = 0;
let reconnectTimer = null;

function connect(path, { isReconnect = false } = {}) {
  if (source) source.close();
  clearTimeout(reconnectTimer);
  if (!isReconnect) { reconnects = 0; }
  streamClosedCleanly = false;

  source = new EventSource(path);
  const kinds = ["run.start", "run.end", "node.enter", "node.exit", "chem.profile",
    "spec.ready", "candidate", "rule.fired", "verdict", "judge.summoned", "judge.token",
    "judge.verdict", "consensus", "reflect", "warning", "error", "wetlab"];
  kinds.forEach((kind) => source.addEventListener(kind, (e) => {
    let payload;
    try {
      payload = JSON.parse(e.data);
    } catch (err) {
      return;   // 끊긴 연결에서 잘려 온 프레임 — 조용히 버린다(재연결이 복구한다)
    }
    handle(kind, payload);
  }));

  source.addEventListener("run.closed", () => {
    streamClosedCleanly = true;
    source.close();
    if (running) finishRun(null);        // run.end 없이 닫힌 경우에도 버튼을 되살린다
  });

  source.onerror = () => {
    source.close();
    if (streamClosedCleanly || !running) return;
    if (reconnects < MAX_RECONNECT) {
      reconnects += 1;
      runStatusNote = `연결이 끊겨 재연결 중… (${reconnects}/${MAX_RECONNECT}) · 실행은 서버에서 계속됩니다`;
      renderRunStatus();
      reconnectTimer = setTimeout(() => {
        resetView();                     // 이력이 처음부터 재생되므로 화면을 비우고 받는다
        connect(path, { isReconnect: true });
      }, 1500);
    } else {
      finishRun(null);
      notice("실시간 연결이 반복해서 끊겼습니다. 새로고침 후 다시 실행해 주세요.", "error", true);
    }
  };
}

/* 무료 티어 토큰 예산 때문에 한 번의 설계가 1분 안팎 걸린다. 그동안 화면이 멈춘 것처럼
   보이지 않도록 경과 시간을 계속 갱신한다(트레이스도 흐르지만 대기 구간이 있다).
   재연결 같은 부가 상태는 이 한 줄에 같이 실어 서로 덮어쓰지 않게 한다. */
let elapsedTimer = null;
let runStartedAt = 0;
let runStatusNote = "";

function renderRunStatus() {
  const s = Math.floor((Date.now() - runStartedAt) / 1000);
  const base = `설계 실행 중… ${s}초 · 에이전트가 순차로 판단하는 동안 트레이스가 흐릅니다`;
  notice(runStatusNote ? `${base}\n${runStatusNote}` : base,
    runStatusNote ? "warn" : "info", true);
}
function startElapsed() {
  runStartedAt = Date.now();
  runStatusNote = "";
  renderRunStatus();
  elapsedTimer = setInterval(renderRunStatus, 1000);
}
function stopElapsed() {
  clearInterval(elapsedTimer);
  elapsedTimer = null;
  runStatusNote = "";
}

function setRunning(on) {
  running = on;
  $("run").disabled = on;
  $("run").textContent = on ? "실행 중…" : "설계 실행";
  $("run").setAttribute("aria-busy", String(on));
  $("replay").disabled = on || !runId;
  if (on) startElapsed();
  else stopElapsed();
}

function finishRun(summary) {
  if (!running) return;
  setRunning(false);
  if (summary && summary.status === "error") {
    notice("실행이 오류로 끝났습니다. 트레이스를 확인해 주세요.", "error", true);
  } else if (degraded.size) {
    // 가짜 점수를 조용히 넘기지 않는다 — 무엇이 LLM 없이 계산됐는지 분명히 알린다.
    notice(`무료 티어 한도로 ${degraded.size}개 노드가 LLM 대신 규칙 기반 대체값을 썼습니다. `
      + "해당 심사 소견에는 표시가 붙어 있습니다.", "warn");
  } else {
    clearNotice();
  }
  continueScenario();
}

function resetView() {
  candidates.clear(); tokenBuffers.clear(); degraded.clear();
  resetNarration();
  $("trace").innerHTML = ""; $("cands").innerHTML = "";
  $("consensus").hidden = true;
  $("cand-count").textContent = "";
  $("pred-panel").hidden = true;
  $("lit-panel").hidden = true;
  resetGraph();
}

async function startRun() {
  if (running) return;
  const request = $("request").value.trim();
  if (!request) {
    notice("설계 요구를 입력해 주세요.", "warn");
    $("request").focus();
    return;
  }
  resetView();
  clearNotice();
  setRunning(true);
  try {
    const res = await fetch(api("/api/runs"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request,
        smiles: $("smiles").value.trim() || null,
        required_excipients: $("pinned").value.split(",").map((s) => s.trim()).filter(Boolean),
      }),
    });
    if (!res.ok) {
      // 429는 허브/파드의 동시 실행 제한. 사용자가 뭘 해야 하는지까지 말해 준다.
      const detail = await res.json().catch(() => ({}));
      throw new Error(res.status === 429
        ? (detail.detail || "지금 실행이 몰려 있습니다. 잠시 후 다시 시도해 주세요.")
        : `서버가 요청을 거부했습니다 (${res.status})`);
    }
    const data = await res.json();
    if (!data.run_id) throw new Error("서버 응답에 run_id가 없습니다");
    runId = data.run_id;
    connect(api(`/api/runs/${runId}/stream`));
  } catch (err) {
    setRunning(false);
    notice(err.message || "실행을 시작하지 못했습니다.", "error", true);
  }
}

$("run").onclick = () => { activeScenario = null; startRun(); };

$("replay").onclick = () => {
  if (!runId || running) return;
  resetView();
  setRunning(true);
  connect(api(`/api/runs/${runId}/replay`));
};

const WL_EXAMPLE = "30분 용출 62%로 목표에 못 미쳤다. 정제 경도는 38N, 마손도 1.2%. "
  + "6개월 가속 조건에서 총 불순물이 0.9%까지 올랐고 정제 표면이 약간 갈변했다.";

$("wl-example").onclick = () => {
  $("wl-notes").value = WL_EXAMPLE;
  $("wl-notes").focus();
};

$("wl-submit").onclick = async () => {
  if (!runId) {
    notice("먼저 설계를 실행한 뒤 실험 결과를 입력해 주세요.", "warn");
    return;
  }
  const notes = $("wl-notes").value.trim();
  if (!notes) {
    notice("수행한 실험 결과를 자연어로 적어 주세요.", "warn");
    $("wl-notes").focus();
    return;
  }
  const btn = $("wl-submit");
  btn.disabled = true;
  btn.textContent = "해석 중…";
  try {
    const res = await fetch(api(`/api/runs/${runId}/wetlab`), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `해석 요청이 실패했습니다 (${res.status})`);
    }
    renderWetlab(await res.json());
  } catch (err) {
    notice(err.message, "error", true);
  } finally {
    btn.disabled = false;
    btn.textContent = "결과 해석 + 다음 실험 지시";
  }
};

/* ── 아키텍처 해설 ───────────────────────────────────────────────────
   실행 이벤트를 받아 "지금 어느 계층이 무엇을 왜 하는지"를 순서대로 쌓는다.
   그래프 점등만으로는 구조가 안 읽히므로, 각 단계에 담당 계층과 그 계층이 존재하는
   이유(=이 구조의 장점)를 붙인다. 실행되는 동안 이 패널이 곧 아키텍처 설명이 된다. */
let narrationCount = 0;
const narrationSeen = new Set();

function narrate(key, { layer, kind, title, body, once = true }) {
  if (once) {
    if (narrationSeen.has(key)) return;
    narrationSeen.add(key);
  }
  const box = $("narration");
  if (!narrationCount) box.innerHTML = "";
  narrationCount += 1;

  const card = document.createElement("div");
  card.className = `nr ${kind || ""}`;
  card.innerHTML = `
    <div class="nr-head">
      <span class="nr-n">${narrationCount}</span>
      <b>${esc(title)}</b>
      <span class="nr-layer ${esc(kind || "")}">${esc(layer)}</span>
    </div>
    <div class="nr-body">${body}</div>`;
  box.appendChild(card);
  box.scrollTop = box.scrollHeight;
}

function resetNarration() {
  narrationCount = 0;
  narrationSeen.clear();
  $("narration").innerHTML =
    '<div class="empty">시나리오를 누르거나 설계를 실행하면 단계별 해설이 여기에 흐릅니다.</div>';
}

/* 이벤트 → 해설. 한 실행에서 각 단계는 한 번만 말한다(토큰 스트림처럼 반복되는 것 제외). */
function narrateEvent(kind, ev, p) {
  switch (kind) {
    case "chem.profile": {
      const on = (p.flags || []).filter((f) => f.present).map((f) => f.flag_name);
      narrate("chem", {
        layer: "입구 · RDKit 결정론", kind: "det",
        title: "분자식에서 시작한다",
        body: `<code>${esc(p.smiles || p.api_name)}</code> 에서 descriptor를 계산하고 구조 플래그를
          검출했습니다 — <b>${on.length ? esc(on.join(", ")) : "검출 없음"}</b>.
          <span class="nr-why">왜 중요한가: 유당이 위험한지는 “아민기가 있는가”에 달려 있습니다.
          이걸 사람이 손으로 적으면 틀립니다(이 프로젝트의 초기 데모가 실제로 그렇게 틀렸습니다).
          그래서 판정의 입력을 사람이 아니라 계산이 만듭니다.</span>`,
      });
      break;
    }
    case "node.exit":
      if (p.strategies) {
        narrate("route", {
          layer: "P1 · 결정론", kind: "det",
          title: "공정 경로를 먼저 좁힌다",
          body: `경쟁 전략: <b>${esc((p.strategies || []).join(", "))}</b>.
            <span class="nr-why">왜 중요한가: “직접타정 규칙”은 직접타정이 선택된 뒤에야 의미가
            있습니다. 앞 단계가 만든 값(유동성 등급)이 뒷 단계의 발동 조건으로 흘러가므로,
            검사에는 순서가 있습니다.</span>`,
        });
      } else if (p.summoned) {
        const ids = (p.summoned || []).map((s) => `${s.reviewer_id}(${s.summon_condition})`);
        narrate("summon", {
          layer: "P4 · 동적 소집", kind: "jud",
          title: `심사관 ${(p.summoned || []).length}명이 지금 만들어졌다`,
          body: `${ids.length ? ids.map(esc).map((t) => `<code>${t}</code>`).join(" ") : "조건 충족 없음"}
            <span class="nr-why">왜 중요한가: 심사위원단에 <b>고정 명단이 없습니다.</b> 조건에 맞는
            전문가만 그 자리에서 생성되고, 나머지는 아예 만들어지지 않습니다 — 같은 시스템인데
            요청마다 팀 구성이 달라집니다.</span>`,
        });
      }
      break;

    case "candidate":
      narrate("candidate", {
        layer: "P2 · 설계 LLM", kind: "llm",
        title: "후보를 하나만 만들지 않는다",
        body: `서로 다른 전략으로 후보를 동시에 만들어 경쟁시킵니다.
          <span class="nr-why">왜 중요한가: 조합 공간이 천문학적이라 “하나 뽑아 검사”가 아니라
          “여러 개 만들어 살아남는 것”을 택합니다. 이 상상은 규칙이 못 하는 일입니다.</span>`,
      });
      break;

    case "rule.fired":
      if (p.status === "hard_fail") {
        narrate("hardfail", {
          layer: "P3 · 룰북 결정론", kind: "fail",
          title: "규칙이 AI의 설계를 막았다",
          body: `<code>${esc(p.rule_id)}</code> ${esc(p.reason)}
            ${p.suggestion ? `<br>규칙표가 제시한 대안: <b>${esc(p.suggestion)}</b>` : ""}
            <span class="nr-why">왜 중요한가: <b>여기가 이 구조의 핵심입니다.</b> AI가 아무리
            그럴듯하게 설계해도 출처가 확인된 규칙이 막습니다. 판정에 AI의 추측이 없으므로
            같은 입력이면 백 번 돌려도 같은 결과입니다. 트레이스의 규칙 ID를 클릭하면
            원본 CSV 행과 출처 문헌이 열립니다.</span>`,
        });
      } else if (p.status === "soft_flag") {
        narrate("softflag", {
          layer: "P3 · 근거 정책", kind: "warn",
          title: "반려까지는 못 가는 지적",
          body: `<code>${esc(p.rule_id)}</code> ${esc(p.reason)}
            <span class="nr-why">왜 중요한가: 근거가 미검증인 규칙 행은 <b>반려를 만들 수
            없습니다.</b> 심사관 이관으로 강등되고, 출처를 못 찾은 행은 로딩 단계에서 아예
            빠집니다 — “근거 없는 규칙은 실행되지 않는다”가 코드로 강제됩니다.</span>`,
        });
      }
      break;

    case "reflect":
      narrate(`reflect-${narrationCount}`, {
        layer: "지휘 · 반성 LLM", kind: "llm", once: false,
        title: "반려 사유를 읽고 재설계를 지시한다",
        body: `${esc(p.root_cause || "")} → <b>${esc(p.directive || "")}</b>
          <span class="nr-why">왜 중요한가: 반려 사유에 담긴 대체 부형제가 그대로 다음 설계
          지시가 됩니다. 실험실에서 며칠 걸릴 “만들어 보고 실패하고 다시 설계”를 이 안에서
          끝냅니다.</span>`,
      });
      break;

    case "judge.verdict":
      narrate("judge", {
        layer: "P5 · 심사 LLM", kind: "jud",
        title: "심사관은 순위만 매긴다 (반려 권한 없음)",
        body: `${esc(p.persona)} → 점수 <b>${esc(p.score)}</b>
          <span class="nr-why">왜 중요한가: 안전·규제 판정은 이미 룰북이 끝냈습니다. 심사관
          점수는 통과한 후보들 사이의 순위 결정에만 쓰입니다 — LLM에게 안전 판정을 맡기지
          않겠다는 설계가 권한 분리로 구현돼 있습니다.</span>`,
      });
      break;

    case "consensus":
      narrate("consensus", {
        layer: "P6 · 합의 결정론", kind: "det",
        title: "합의로 최종 후보를 고른다",
        body: `선정 <b>${esc(p.winner || "없음")}</b> · 모델 ${esc(p.model || "")}
          <span class="nr-why">왜 중요한가: 결정론 하드페일과 심사 가중점수를 합쳐 판단합니다.
          가중치·임계값은 설정 CSV에서 오므로 이 단계도 재현됩니다.</span>`,
      });
      break;

    case "warning":
      if (ev.node === "infeasible") {
        narrate("infeasible", {
          layer: "종단 · 판정", kind: "fail",
          title: "“이 제약으로는 통과하는 처방이 없다”",
          body: `${esc(p.reason || "")}
            ${(p.blocking || []).slice(0, 2).map((b) =>
              `<br><code>${esc(b.rule_id)}</code> ${esc(b.reason)}${
                b.suggestion ? ` → 대안 <b>${esc(b.suggestion)}</b>` : ""}`).join("")}
            <span class="nr-why">왜 중요한가: 재설계로 풀리지 않는 충돌을 알아채고 루프를 돌리지
            않습니다. 연구원이 들어야 할 답은 “다시 설계했다”가 아니라 “제약 자체가 불가능하다,
            대신 이걸 쓰라”입니다.</span>`,
        });
      }
      break;
  }
}

/* ── 시연 시나리오 ───────────────────────────────────────────────────
   버튼을 누르면 곧바로 실행되고, 위 해설이 실행에 맞춰 흐른다.
   각 시나리오가 실제로 어떤 경로를 밟는지 측정해서 고른 조합이다. */
const SCENARIOS = [
  {
    id: "guardrail",
    title: "규칙이 AI를 막는 순간",
    proves: "검증 계층 · 근거 추적",
    request: "소아용 플루옥세틴 정제를 설계해줘",
    pinned: "Lactose monohydrate",
    duration: "약 1분",
    goal: `현장 제약으로 <b>유당을 반드시 쓰라</b>고 못 박았습니다. 설계 AI는 제약을 지키고,
      룰북이 <code>INC002</code>(2차 아민 + 유당 → Maillard 반응)로 막습니다.
      재설계로 풀리지 않는 충돌이라 시스템은 루프를 돌리지 않고
      <b>“이 제약으로는 통과가 없다”</b>는 결론과 대체 부형제를 냅니다.`,
  },
  {
    id: "team",
    title: "요청에 따라 팀이 바뀐다",
    proves: "자기조직형 멀티 에이전트",
    request: "소아용 바나나향 아세트아미노펜 정제를 설계해줘",
    pinned: "",
    duration: "약 2분",
    goal: `대상이 <b>소아</b>라서 소아 안전 심사관(REV001)이 그 자리에서 생성됩니다. 명단에 있는
      가용화·고령자·문헌조사 심사관은 조건에 맞지 않아 <b>아예 만들어지지 않습니다</b> —
      고정 명단이 없다는 증거입니다. 아세트아미노펜은 아미드라 유당 금기에 걸리지 않는 것도
      왼쪽 구조 플래그에서 함께 확인됩니다(<code>is_amide_not_amine</code>).
      접속이 몰리면 심사 점수가 규칙 기반으로 대체될 수 있고, 그때는 소견에 표시가 붙습니다.`,
  },
  {
    id: "labloop",
    title: "만든 뒤 다음 실험까지",
    proves: "Lab-in-the-loop",
    // 이 시나리오의 요점은 lab-loop이라 설계 단계는 가볍게 둔다 —
    // 심사관이 많이 소집되면 무료 티어 토큰이 설계에서 다 소모되고 지시가 규칙 기반으로 내려간다.
    request: "성인용 이부프로펜 정제를 설계해줘",
    pinned: "",
    duration: "약 2~3분",
    autoLab: true,
    goal: `설계를 한 바퀴 돌린 뒤 <b>실험 결과를 자연어로 자동 입력</b>해 lab-in-the-loop을 이어서 돕니다.
      AI가 문장에서 수치를 판독하고, 규칙이 규격 이탈을 판정한 뒤, 확인시험 마스터 66종에서
      <b>다음에 할 실험</b>을 골라 지시합니다 — 모든 지시에 ICH·FDA 출처가 붙습니다.`,
  },
];

let activeScenario = null;

function buildScenarios() {
  const box = $("scenarios");
  box.innerHTML = SCENARIOS.map((s, i) => `
    <button type="button" class="scenario" data-i="${i}">
      <span class="scenario-proves">${esc(s.proves)}</span>
      <span class="scenario-title">${esc(s.title)}</span>
      <span class="scenario-run">▶ 실행 · ${esc(s.duration)}</span>
    </button>`).join("");
  box.querySelectorAll(".scenario").forEach((btn) => {
    btn.onclick = () => {
      if (running) {
        notice("실행이 끝난 뒤에 다른 시나리오를 눌러 주세요.", "warn");
        return;
      }
      const scenario = SCENARIOS[Number(btn.dataset.i)];
      activeScenario = scenario;
      $("request").value = scenario.request;
      $("pinned").value = scenario.pinned;
      box.querySelectorAll(".scenario").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");

      const goal = $("scenario-goal");
      goal.hidden = false;
      goal.innerHTML = `<b>${esc(scenario.title)}</b> — 이 시나리오가 보여주는 것<br>${scenario.goal}`;
      startRun();
    };
  });
}

/* 시나리오가 lab-in-the-loop까지 이어질 때, 설계가 끝나면 자동으로 실험 결과를 넣는다. */
function continueScenario() {
  if (!activeScenario || !activeScenario.autoLab) return;
  narrate("labloop-start", {
    layer: "Lab-in-the-loop", kind: "llm",
    title: "이제 만든 뒤의 절반 — 실험 결과를 넣는다",
    body: `실험 노트를 자연어로 자동 입력합니다. AI가 판독 → 규칙이 판정 → AI가 다음 실험을 지시.
      <span class="nr-why">왜 중요한가: 사람이 판단의 병목이 아니라 벤치에서 실험을 수행하는
      쪽으로 들어옵니다. 지시의 후보는 실제 확인시험 마스터 66종으로 묶여 있어 AI가 시험을
      발명할 수 없습니다.</span>`,
  });
  $("labloop").open = true;
  $("wl-notes").value = WL_EXAMPLE;
  $("labloop").scrollIntoView({ behavior: "smooth", block: "nearest" });
  setTimeout(() => $("wl-submit").click(), 700);
}

/* 예측 계층 — 교차검증·불확실성·BCS. 값이 없으면 "미연결"을 그대로 보여준다. */
function renderPredictions(p) {
  const pred = p.predictions || {};
  const plan = p.test_plan || {};
  const logs = pred.logs || {}, bcs = pred.bcs || {};
  const box = $("pred-body");
  $("pred-panel").hidden = false;

  const chip = (s) => `<span class="pred-chip ${esc(s)}">${esc(s)}</span>`;
  const promo = (plan.promotions || []).map((x) =>
    `<div class="pred-promo"><b>${esc(x.test)}</b> ${esc(x.from)} → ${esc(x.to)}
       <div>${esc(x.why)}</div></div>`).join("");

  box.innerHTML = `
    <div class="pred-row"><span>용해도 LogS</span>${chip(logs.status || "미상")}</div>
    ${logs.note ? `<div class="pred-note">${esc(logs.note)}</div>` : ""}
    <div class="pred-row"><span>BCS 등급</span>
      <b>${esc(bcs.bcs_class || "미결정")}</b>${chip(bcs.status || "")}</div>
    ${bcs.note ? `<div class="pred-note">${esc(bcs.note)}</div>` : ""}
    <div class="pred-note">${esc(bcs.limitation || "")}</div>
    <h3>확인시험 계획 <small>필수 ${esc(plan.required_count || 0)}건</small></h3>
    ${(plan.tests || []).filter((t) => t.tier === "필수").map((t) =>
      `<div class="pred-test"><b>${esc(t.tier)}</b> ${esc(t.test)}</div>`).join("")}
    ${promo ? `<h3>구조·예측이 올린 시험</h3>${promo}` : ""}`;
}

/* 문헌 조사 — 실제 PubChem·Europe PMC 조회 결과 */
function renderLiterature(p) {
  const c = p.compound || {}, l = p.literature || {};
  $("lit-panel").hidden = false;
  $("lit-body").innerHTML = `
    <div class="pred-note">${esc(p.summary || "")}</div>
    ${c.found ? `<div class="lit-cid">PubChem
      <a href="${esc(c.url)}" target="_blank" rel="noopener">CID ${esc(c.cid)}</a></div>` : ""}
    ${(l.hits || []).map((h) => `<div class="lit-hit">
        <a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
        <div>${esc(h.journal)} ${esc(h.year)}</div></div>`).join("")
      || `<div class="pred-note">${esc(l.note || "문헌 없음")}</div>`}`;
}

/* ── SMARTS 직접 검사 ────────────────────────────────────────────────
   룰북의 배합금기 판정은 SMARTS 매칭에서 출발한다. 판정을 믿으려면 "그 패턴이 정말
   이 분자에 있는가"를 사람이 확인할 수 있어야 하므로, 그 계층을 화면에 그대로 노출한다.
   패턴 프리셋은 룰북이 실제로 쓰는 structural_flags_smarts.csv 에서 가져온다. */
let lastSmiles = "";

async function loadSmartsPresets() {
  try {
    const res = await fetch(api("/api/chem/smarts"));
    if (!res.ok) return;
    const { patterns } = await res.json();
    $("sm-presets").innerHTML = patterns.map((p, i) =>
      `<button type="button" class="sm-preset" data-i="${i}" title="${esc(p.risk_context)}">
         ${esc(p.flag_name)}</button>`).join("");
    $("sm-presets").querySelectorAll(".sm-preset").forEach((btn) => {
      btn.onclick = () => {
        const pattern = patterns[Number(btn.dataset.i)];
        $("sm-pattern").value = pattern.smarts;
        $("sm-out").innerHTML = `<div class="sm-note">
          <b>${esc(pattern.flag_id)} ${esc(pattern.flag_name)}</b>
          <div>발동 규칙: <code>${esc(pattern.triggers_rule || "-")}</code></div>
          <div>위험 맥락: ${esc(pattern.risk_context || "-")}</div>
          ${pattern.notes ? `<div class="sm-notes">${esc(pattern.notes)}</div>` : ""}
        </div>`;
      };
    });
  } catch (err) { /* 패턴 목록은 부가 기능 — 실패해도 화면은 돈다 */ }
}

$("sm-run").onclick = async () => {
  const smiles = $("sm-smiles").value.trim() || lastSmiles;
  const smarts = $("sm-pattern").value.trim();
  if (!smiles) {
    notice("검사할 SMILES를 입력하거나 먼저 설계를 실행해 주세요.", "warn");
    return;
  }
  if (!smarts) {
    notice("SMARTS 패턴을 입력하거나 아래 패턴 중 하나를 눌러 주세요.", "warn");
    return;
  }
  const btn = $("sm-run");
  btn.disabled = true;
  try {
    const res = await fetch(api("/api/chem/smarts"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ smiles, smarts }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `검사 실패 (${res.status})`);
    }
    const d = await res.json();
    const hit = d.parent_match_count > 0;
    $("sm-out").innerHTML = `
      <div class="sm-result ${hit ? "hit" : "miss"}">
        <b>${hit ? `✓ ${esc(d.parent_match_count)}곳 일치` : "✕ 해당 구조 없음"}</b>
        <div>${esc(d.message)}</div>
        ${d.is_salt ? `<div class="sm-notes">염 형태 — parent <code>${esc(d.parent_smiles)}</code> 로 매칭</div>` : ""}
      </div>
      ${d.svg ? `<div class="mol sm-mol">${d.svg}</div>` : ""}`;
  } catch (err) {
    notice(err.message, "error");
  } finally {
    btn.disabled = false;
  }
};

/* ── 테마 ───────────────────────────────────────────────────────────
   키는 머니메이트·브리핑과 공유('mm:theme'). 저장값이 없으면 시스템 설정을 따른다. */
$("btn-theme").onclick = () => {
  const root = document.documentElement;
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const current = root.dataset.theme || (systemDark ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  root.dataset.theme = next;
  try { localStorage.setItem("mm:theme", next); } catch (e) { /* 사생활 모드 — 무시 */ }
};

/* ── 초기화 ─────────────────────────────────────────────────────── */
(async function init() {
  buildGraph();
  buildScenarios();
  loadSmartsPresets();
  setRunning(false);
  try {
    const res = await fetch(api("/api/meta"));
    if (!res.ok) throw new Error(`상태 조회 실패 (${res.status})`);
    const meta = await res.json();
    const r = meta.rulebook;
    $("pill-rules").textContent =
      `룰북 ${r.total} (정량 ${r.quantitative} · 정성 ${r.qualitative} · 참조 ${r.reference})`;
    $("pill-rules").className = "pill ok";
    $("pill-llm").textContent = meta.llm_available
      ? `LLM ${meta.llm_model || "연결됨"}`
      : "LLM 미연결 — 규칙 기반 대체";
    $("pill-llm").className = "pill " + (meta.llm_available ? "ok" : "warn");
  } catch (err) {
    // 백엔드가 안 뜬 상태를 빈 화면으로 두지 않는다.
    $("pill-rules").textContent = "룰북 조회 실패";
    $("pill-rules").className = "pill warn";
    $("pill-llm").textContent = "상태 미상";
    $("pill-llm").className = "pill warn";
    notice("백엔드에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.", "error", true);
    $("run").disabled = true;
  }
})();
