/* Formula 1 대시보드 — TraceEvent 스트림 하나만 소비해 화면 전체를 그린다. */

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";

/* 서브경로 배포(zihwan.com/formula1) 대응 — 서버가 index.html에 주입한다.
   단독 실행이면 빈 문자열이라 예전과 똑같이 /api/... 로 나간다. */
const BASE = window.__BASE__ || "";
const api = (path) => `${BASE}${path}`;

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
  row.innerHTML = `<span class="seq">${seq}</span><span class="node">${node}</span>
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
      if (entry) entry.judges.push(p);
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
      addTrace(ev.seq, ev.node, p.reason + (p.fallback ? " → 결정론 폴백" : ""), "warn");
      break;
    case "error":
      addTrace(ev.seq, ev.node, `오류: ${p.error}`, "hard_fail");
      break;
    case "wetlab": renderWetlab(p); break;
    case "run.end":
      addTrace(ev.seq, "run", `완료 · status=${p.status} · winner=${p.winner || "없음"}`);
      $("replay").disabled = false;
      break;
  }
}

/* ── 렌더러 ─────────────────────────────────────────────────────── */
function renderChem(p) {
  $("chem-empty").hidden = true;
  $("chem-body").hidden = false;
  $("mol-svg").innerHTML = p.svg || '<div class="empty">구조 없음</div>';
  $("mol-id").textContent = p.smiles
    ? `${p.api_name}\n${p.smiles}` + (p.is_salt ? `\nparent: ${p.parent_smiles}` : "")
    : `${p.api_name} — SMILES 미상`;

  $("mol-flags").innerHTML = (p.flags || []).map((f) =>
    `<span class="flag ${f.present ? "on" : ""}">${f.flag_name}</span>`).join("");

  $("mol-desc").innerHTML = Object.entries(p.descriptors || {}).map(([k, v]) =>
    `<tr><td>${k}</td><td>${Number(v).toFixed(2)}</td></tr>`).join("");

  $("mol-est").innerHTML = (p.estimates || []).map((e) =>
    `<div class="est"><b>${e.property}</b> = ${e.value}
     <span class="${e.confidence === "low" ? "lo" : ""}">[${e.confidence}]</span></div>`).join("");

  $("mol-warn").innerHTML = (p.warnings || []).length
    ? `<div class="warn">⚠ ${p.warnings.join("<br>⚠ ")}</div>` : "";
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
      .map((i) => `${i.name} ${i.amount_mg ?? "-"}mg`).join(" · ");
    const chips = entry.verdicts.map((v) =>
      `<span class="chip ${v.status}" data-rule="${v.rule_id}">${v.rule_id}</span>`).join("");
    const judges = entry.judges.map((j) =>
      `<div class="judge-note"><b>${j.persona}</b> ${j.score} — ${j.rationale}</div>`).join("");
    card.innerHTML = `
      <h4>${id}<span class="tag">${entry.recipe.strategy} · ${entry.recipe.process || ""}</span></h4>
      <div class="ing">${ings}</div>
      <div class="ing">포장: ${entry.recipe.packaging || "-"}</div>
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
    `<div>${r.rank ? `#${r.rank} ` : "— "}<b>${r.candidate_id}</b>
      점수 ${r.weighted_score ?? "-"} · 분산 ${r.variance ?? "-"} · 심사관 ${r.reviewers}
      ${r.low_confidence ? " <span class='tag'>저신뢰</span>" : ""}
      ${r.eligible ? "" : " <span class='tag'>반려</span>"}</div>`).join("");
  el.innerHTML = `<h3>합의 (${p.model})</h3>
    <div class="win">선정: ${p.winner || "없음"}</div>${rows}
    <div class="tag" style="margin-top:6px">심사관 점수는 순위 결정 전용 — 반려 권한 없음</div>
    ${(p.rulebook_feedback || []).map((f) => `<div class="warn">${f}</div>`).join("")}`;
}

const tokenBuffers = new Map();
function streamToken(candidateId, reviewerId, delta) {
  const key = `${candidateId}/${reviewerId}`;
  if (!tokenBuffers.has(key)) {
    const row = document.createElement("div");
    row.className = "ev";
    row.innerHTML = `<span class="seq">…</span><span class="node">${reviewerId}</span>
                     <span class="msg tok"></span>`;
    $("trace").appendChild(row);
    tokenBuffers.set(key, row.querySelector(".msg"));
  }
  const target = tokenBuffers.get(key);
  target.textContent += delta;
  $("trace").scrollTop = $("trace").scrollHeight;
}

function renderWetlab(report) {
  $("wl-out").innerHTML = `<b>${report.summary}</b>` +
    report.findings.filter((f) => f.off_target).map((f) =>
      `<div class="warn">${f.metric}: ${f.interpretation}<br>→ ${f.suggested_revision}</div>`).join("");
}

/* ── 근거 드릴다운 ──────────────────────────────────────────────── */
let modalOpener = null;

async function showRule(ruleId) {
  if (!ruleId) return;
  modalOpener = document.activeElement;
  const res = await fetch(api(`/api/rules/${encodeURIComponent(ruleId)}`));
  const body = $("modal-body");
  if (!res.ok) {
    body.innerHTML = `<h3>${ruleId}</h3><div class="src">원본 행을 찾지 못했습니다.</div>`;
  } else {
    const d = await res.json();
    body.innerHTML = `<h3>${d.rule_id} · ${d.rulebook_id}</h3>
      <div class="src">${d.file} · 전략 ${d.strategy} · polarity ${d.polarity}
        ${d.sources_doc ? `<br>출처 문서: ${d.sources_doc}` : ""}</div>
      <table>${Object.entries(d.row).filter(([, v]) => v !== "")
        .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>`;
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
function connect(path) {
  if (source) source.close();
  source = new EventSource(path);
  const kinds = ["run.start", "run.end", "node.enter", "node.exit", "chem.profile",
    "spec.ready", "candidate", "rule.fired", "verdict", "judge.summoned", "judge.token",
    "judge.verdict", "consensus", "reflect", "warning", "error", "wetlab"];
  kinds.forEach((kind) => source.addEventListener(kind, (e) => handle(kind, JSON.parse(e.data))));
  source.addEventListener("run.closed", () => source.close());
  source.onerror = () => source.close();
}

$("run").onclick = async () => {
  candidates.clear(); tokenBuffers.clear();
  $("trace").innerHTML = ""; $("cands").innerHTML = "";
  $("consensus").hidden = true; $("replay").disabled = true;
  resetGraph();
  $("run").disabled = true;
  const res = await fetch(api("/api/runs"), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request: $("request").value, smiles: $("smiles").value || null }),
  });
  runId = (await res.json()).run_id;
  connect(api(`/api/runs/${runId}/stream`));
  $("run").disabled = false;
};

$("replay").onclick = () => {
  if (!runId) return;
  candidates.clear(); tokenBuffers.clear();
  $("trace").innerHTML = ""; $("cands").innerHTML = "";
  $("consensus").hidden = true; resetGraph();
  connect(api(`/api/runs/${runId}/replay`));
};

$("wl-submit").onclick = async () => {
  if (!runId) return;
  const res = await fetch(api(`/api/runs/${runId}/wetlab`), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      measurements: {
        dissolution_30min_percent: Number($("wl-diss").value),
        tablet_hardness_N: Number($("wl-hard").value),
        impurity_total_percent: Number($("wl-imp").value),
      },
    }),
  });
  renderWetlab(await res.json());
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
  const meta = await (await fetch(api("/api/meta"))).json();
  const r = meta.rulebook;
  $("pill-rules").textContent =
    `룰북 ${r.total} (정량 ${r.quantitative} · 정성 ${r.qualitative} · 참조 ${r.reference})`;
  $("pill-rules").className = "pill ok";
  $("pill-llm").textContent = meta.llm_available
    ? `LLM ${meta.llm_model || "연결됨"}`
    : "LLM 미연결 — 결정론 폴백";
  $("pill-llm").className = "pill " + (meta.llm_available ? "ok" : "warn");
})();
