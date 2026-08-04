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
const assessments = new Map();  // candidate_id → 근거 충족 판정 (evidence 이벤트)
let winnerId = null;            // 합의가 고른 권고 후보
let lastApplied = {};           // 확인시험 결과가 실측값 자리에 꽂힌 내역

/* ── 고정 그래프 레이아웃 ────────────────────────────────────────────
   kind: det(결정론) | llm(LLM 판단) | jud(동적 심사관)
   게이트가 둘이라는 것이 이 그래프의 요지다: gate(금기가 있는가) → evidence(알고 있는가). */
const NODES = [
  { id: "intake",    x:  14, y: 30, w: 104, label: "intake",    sub: "요구 → 스펙",     kind: "llm" },
  { id: "route",     x: 138, y: 30, w: 104, label: "route",     sub: "유동성 → 공정",   kind: "det" },
  { id: "generate",  x: 262, y: 30, w: 112, label: "generate",  sub: "후보 병렬 설계",  kind: "llm" },
  { id: "gate",      x: 394, y: 30, w: 112, label: "gate",      sub: "룰북 판정",       kind: "det" },
  { id: "evidence",  x: 526, y: 30, w: 124, label: "evidence",  sub: "근거 충족 판정",  kind: "det" },
  { id: "summon",    x: 670, y: 30, w: 104, label: "summon",    sub: "심사관 소집",     kind: "det" },
  { id: "consensus", x: 794, y: 30, w: 118, label: "consensus", sub: "가중 합의",       kind: "det" },
  { id: "reflect",   x: 394, y: 210, w: 112, label: "reflect",  sub: "재설계 지시",     kind: "llm" },
];
const EDGES = [
  ["intake", "route"], ["route", "generate"], ["generate", "gate"],
  ["gate", "evidence"], ["evidence", "summon"], ["summon", "consensus"],
];
/* 되먹임은 두 개다 — 규칙 반려(설계로) 와 확인시험(입력·근거로). 배치 결과 루프는
   화면 아래 별도 패널이 담당하므로 그래프에는 실행 전 루프만 그린다. */
const LOOPS = [
  { d: "M 450 76 L 450 210", key: "gate->reflect" },
  { d: "M 394 233 L 318 233 L 318 76", key: "reflect->generate", label: "반려 → 재설계", lx: 330, ly: 227 },
  { d: "M 588 76 L 588 268 L 66 268 L 66 76", key: "evidence->intake",
    label: "근거 부족 → 확인시험 선행", lx: 300, ly: 262 },
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
  for (const loop of LOOPS) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", loop.d);
    path.setAttribute("class", "edge loop");
    path.dataset.edge = loop.key;
    svg.appendChild(path);
    if (!loop.label) continue;
    const text = document.createElementNS(SVG_NS, "text");
    text.setAttribute("x", loop.lx);
    text.setAttribute("y", loop.ly);
    text.setAttribute("class", "edge-label");
    text.textContent = loop.label;
    svg.appendChild(text);
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
    id: `judge-${reviewerId}`, x: 668, y: 100 + index * 56, w: 140,
    label: reviewerId, sub: persona.slice(0, 14), kind: "jud",
  };
  judgeNodes.set(reviewerId, node);
  const svg = $("graph");
  const edge = document.createElementNS(SVG_NS, "path");
  edge.setAttribute("d", `M 722 76 L 722 ${node.y}`);
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

    case "evidence": {
      assessments.set(p.candidate_id, p);
      const blocking = (p.gaps || []).filter((g) => isBlocking(g)).length;
      addTrace(ev.seq, "evidence",
        `${p.candidate_id}: ${READINESS[p.readiness]?.label || p.readiness}`
        + (blocking ? ` · 선행 확인시험 ${blocking}건 필요` : ""),
        p.readiness === "blocked" ? "warn" : "");
      renderCandidates();
      renderEvidence();
      break;
    }

    case "consensus": renderConsensus(p);
      winnerId = p.winner || null;
      renderEvidence();
      addTrace(ev.seq, "consensus", `권고 후보: ${p.winner || "없음"} (보고 ${p.reported}건)`);
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

/* 프로토콜 실행 상태 — 룰 통과와는 다른 축이다. 라벨을 한 곳에서만 관리한다. */
const READINESS = {
  blocked: { label: "실행 불가 초안", hint: "선행 근거 부족 — 확인시험이 먼저입니다" },
  ready_for_review: { label: "검토용 프로토콜", hint: "선행 근거 충족 — 연구자 승인 대기" },
  approved: { label: "실행 가능 프로토콜", hint: "연구자 승인 완료" },
};
const TIMING = {
  before_protocol: { label: "프로토콜 전 필수", note: "결과가 없으면 실행 가능한 프로토콜을 내지 않습니다" },
  parallel: { label: "병행 수행", note: "전략은 그대로 두고 함께 진행 — 중단/변경 기준을 같이 봅니다" },
  post_batch: { label: "배치 후 조건부", note: "첫 배치 결과를 본 뒤에 필요하면 수행합니다" },
};
const isBlocking = (gap) =>
  gap.status === "failed" || (gap.timing === "before_protocol" && gap.status !== "satisfied");

function renderCandidates() {
  const box = $("cands");
  if (!candidates.size) return;
  $("cand-count").textContent = `${candidates.size}건`;
  box.innerHTML = "";
  for (const [id, entry] of candidates) {
    const gate = entry.gate;
    const assessment = assessments.get(id);
    const card = document.createElement("div");
    card.className = "card " + (gate ? (gate.passed ? "pass" : "fail") : "");
    const ings = entry.recipe.ingredients
      .map((i) => `${esc(i.name)} ${esc(i.amount_mg ?? "-")}mg`).join(" · ");
    const chips = entry.verdicts.map((v) =>
      `<span class="chip ${esc(v.status)}" data-rule="${esc(v.rule_id)}">${esc(v.rule_id)}</span>`).join("");
    const judges = entry.judges.map((j) =>
      `<div class="judge-note ${j.source === "deterministic-fallback" ? "stand-in" : ""}"><b>${esc(j.persona)}</b> ${esc(j.score)}${j.source === "deterministic-fallback" ? ' <span class="stand-in-tag">규칙 기반 대체 점수 · LLM 미사용</span>' : ""} — ${esc(j.rationale)}</div>`).join("");
    // 룰 통과와 별개로 "실행해도 되는 상태인가"를 카드에서 바로 읽을 수 있어야 한다.
    const readiness = assessment
      ? `<div class="readiness ${esc(assessment.readiness)}">
           <b>${esc(READINESS[assessment.readiness]?.label || assessment.readiness)}</b>
           <span>${esc(READINESS[assessment.readiness]?.hint || "")}</span></div>`
      : "";
    card.innerHTML = `
      <h4>${esc(id)}<span class="tag">${esc(entry.recipe.strategy)} · ${esc(entry.recipe.process || "")}</span></h4>
      <div class="ing">${ings}</div>
      <div class="ing">포장: ${esc(entry.recipe.packaging || "-")}</div>
      ${readiness}
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
  // "최종 처방"이 아니라 **권고 후보**다 — 실행 여부는 근거 게이트와 연구자 승인이 정한다.
  el.innerHTML = `<h3>합의 · 권고 후보 처방 (${esc(p.model)})</h3>
    <div class="win">권고 후보: ${esc(p.winner || "없음")}</div>${rows}
    <div class="tag" style="margin-top:6px">심사관 점수는 순위 결정 전용 — 반려 권한 없음</div>
    <div class="tag">권고 후보 ≠ 실행 가능 프로토콜 — 아래 근거 충족 게이트에서 상태가 정해집니다</div>
    ${(p.rulebook_feedback || []).map((f) => `<div class="warn">${esc(f)}</div>`).join("")}`;
}

/* ── 근거 충족 게이트 (실험 전 루프) ────────────────────────────────────
   룰을 통과한 뒤에도 "실행할 만큼 아는가"를 따로 묻는다. 선행 근거가 비어 있으면
   실행 가능한 공정 프로토콜 대신 **확인시험 요청**을 내고, 그 결과를 여기서 되받는다. */
function renderEvidence() {
  const box = $("evidence");
  const id = (winnerId && assessments.has(winnerId)) ? winnerId : [...assessments.keys()][0];
  const a = id ? assessments.get(id) : null;
  if (!a) return;
  box.hidden = false;

  const state = READINESS[a.readiness] || { label: a.readiness, hint: "" };
  const groups = ["before_protocol", "parallel", "post_batch"].map((timing) => {
    const gaps = (a.gaps || []).filter((g) => g.timing === timing);
    if (!gaps.length) return "";
    const meta = TIMING[timing];
    return `<div class="ev-group">
      <h4>${esc(meta.label)} <small>${esc(meta.note)}</small></h4>
      ${gaps.map((g) => evidenceRow(g, timing === "before_protocol")).join("")}</div>`;
  }).join("");

  const blocking = (a.gaps || []).filter(isBlocking);
  const actions = `<div class="ev-actions">
      ${blocking.length ? `<button id="ev-submit" type="button">확인시험 결과 제출 → 근거 재평가</button>
        <button id="ev-example" class="ghost" type="button">예시 결과 넣기</button>`
      : `<button id="ev-approve" type="button">연구자 승인 → 실행 가능 프로토콜</button>`}
    </div>`;

  box.innerHTML = `
    <h3>근거 충족 게이트 <small>${esc(id)} · 룰 통과 ≠ 정보 충분</small></h3>
    <div class="ev-state ${esc(a.readiness)}"><b>${esc(state.label)}</b>
      <span>${esc(a.summary || state.hint)}</span></div>
    ${a.approved_by ? `<div class="ev-approved">승인: ${esc(a.approved_by)}</div>` : ""}
    ${Object.keys(lastApplied).length ? `<div class="ev-applied">입력 계층에 반영된 실측값:
      ${Object.entries(lastApplied).map(([k, v]) =>
        `<code>${esc(k)} = ${esc(v)}</code>`).join(" ")}</div>` : ""}
    ${groups}
    ${actions}
    <div id="ev-out"></div>`;

  if ($("ev-submit")) $("ev-submit").onclick = () => submitConfirmation(id);
  if ($("ev-example")) $("ev-example").onclick = () => fillConfirmationExample();
  if ($("ev-approve")) $("ev-approve").onclick = () => approveProtocol(id);
}

function evidenceRow(gap, withInput) {
  const done = gap.status === "satisfied";
  const failed = gap.status === "failed";
  const source = gap.source_url
    ? `<a href="${esc(gap.source_url)}" target="_blank" rel="noopener">${esc(gap.source_reference)}</a>`
    : esc(gap.source_reference);
  // 이 시험이 canonical 측정값을 내면 숫자 칸을 함께 준다 — 그 값은 요약 문구가 아니라
  // 스펙의 실측값 자리에 그대로 꽂혀서 다음 판정의 입력이 된다.
  const numeric = gap.result_key ? `
      <input type="number" step="any" class="ev-num" data-unit="${esc(gap.result_unit || "")}"
             placeholder="${esc(gap.result_key)}${gap.result_unit ? ` (${esc(gap.result_unit)})` : ""}">` : "";
  const input = (withInput && !done) ? `
    <div class="ev-input" data-req="${esc(gap.requirement_id)}">
      <select aria-label="${esc(gap.label)} 결과">
        <option value="pass">적합 — 근거 확보</option>
        <option value="fail">부적합 — 이 전략 배제</option>
      </select>
      ${numeric}
      <input type="text" maxlength="120" class="ev-text"
             placeholder="측정값·요약 (예: 25°C/75%RH 7일, 분해물 0.3%)">
    </div>` : "";
  return `<div class="ev-item ${done ? "done" : failed ? "failed" : "missing"}">
    <div class="ev-head"><b>${esc(gap.label)}</b>
      <code class="ll-id">${esc(gap.test_id)}</code>
      <span class="ev-status">${done ? "충족" : failed ? "부적합" : "미확보"}</span></div>
    <div class="ev-why">${esc(gap.why)}</div>
    ${gap.risk ? `<div class="ev-risk">근거 없이 진행하면: ${esc(gap.risk)}</div>` : ""}
    <div class="ll-spec">시험: ${esc(gap.test_name)} · 측정 ${esc(gap.output_variable)}
      ${gap.unit ? `(${esc(gap.unit)})` : ""} · 판정 ${esc(gap.acceptance_logic)}</div>
    ${gap.stop_criteria ? `<div class="ev-stop">중단/변경 기준: ${esc(gap.stop_criteria)}</div>` : ""}
    ${gap.source_reference ? `<div class="ll-src">근거 ${source}</div>` : ""}
    ${gap.result_note ? `<div class="ev-result">입력된 결과: ${esc(gap.result_note)}</div>` : ""}
    ${input}</div>`;
}

const EV_EXAMPLE = "37°C 수계 조건 7일, 총 분해물 0.4% (규격 이내)";

function fillConfirmationExample() {
  document.querySelectorAll("#evidence .ev-input .ev-text").forEach((el) => {
    if (!el.value) el.value = EV_EXAMPLE;
  });
}

async function submitConfirmation(candidateId) {
  const entries = [...document.querySelectorAll("#evidence .ev-input")].map((row) => {
    const num = row.querySelector(".ev-num");
    const value = row.querySelector(".ev-text").value.trim();
    const raw = num && num.value.trim() !== "" ? Number(num.value) : null;
    return {
      requirement_id: row.dataset.req,
      outcome: row.querySelector("select").value,
      value,
      value_num: Number.isFinite(raw) ? raw : null,
    };
  }).filter((e) => e.value || e.value_num !== null || e.outcome === "fail");

  if (!entries.length) {
    notice("확인시험 결과를 한 건 이상 적어 주세요 (부적합은 값 없이도 제출됩니다).", "warn");
    return;
  }
  const btn = $("ev-submit");
  btn.disabled = true;
  btn.textContent = "재평가 중…";
  try {
    const res = await fetch(api(`/api/runs/${runId}/confirmation`), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_id: candidateId, entries }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `근거 재평가에 실패했습니다 (${res.status})`);
    }
    const updated = await res.json();
    assessments.set(updated.candidate_id, updated);
    lastApplied = updated.applied_measurements || {};
    narrateEvidenceLoop(updated);
    renderCandidates();
    renderEvidence();
  } catch (err) {
    notice(err.message, "error", true);
    btn.disabled = false;
    btn.textContent = "확인시험 결과 제출 → 근거 재평가";
  }
}

async function approveProtocol(candidateId) {
  const btn = $("ev-approve");
  btn.disabled = true;
  btn.textContent = "승인 중…";
  try {
    const res = await fetch(api(`/api/runs/${runId}/approve`), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_id: candidateId }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `승인에 실패했습니다 (${res.status})`);
    }
    const updated = await res.json();
    assessments.set(updated.candidate_id, updated);
    narrate("approved", {
      layer: "연구자 승인", kind: "det",
      title: "이제서야 실행 가능한 프로토콜이 된다",
      body: `${esc(updated.candidate_id)} — ${esc(updated.summary)}
        <span class="nr-why">왜 중요한가: 근거가 충족돼도 시스템이 스스로 실행 가능으로
        올리지 않습니다. 사람이 승인해야 상태가 바뀌고, 승인 이력이 함께 남습니다.</span>`,
    });
    renderCandidates();
    renderEvidence();
  } catch (err) {
    notice(err.message, "error", true);
    btn.disabled = false;
    btn.textContent = "연구자 승인 → 실행 가능 프로토콜";
  }
}

function narrateEvidenceLoop(updated) {
  const failed = (updated.gaps || []).filter((g) => g.status === "failed");
  narrate(`confirm-${narrationCount}`, {
    layer: "실험 전 루프 · 결정론", kind: failed.length ? "fail" : "det", once: false,
    title: failed.length ? "확인시험이 전제를 부정했다" : "확인시험 결과로 근거가 채워졌다",
    body: `${esc(updated.summary)}
      <span class="nr-why">왜 중요한가: 확인시험 결과는 <b>입력·근거 계층으로</b> 돌아갑니다.
      배치 결과가 설계·프로토콜 개정으로 가는 것과 되먹임 지점이 다릅니다 — 그래서 입력창도
      둘로 나눠 둡니다.</span>`,
  });
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

  // 이 데이터가 어떤 상태의 프로토콜에서 나왔는지를 함께 남긴다 — 승인 전 배치의 결과를
  // 승인된 프로토콜의 결과와 같은 무게로 읽으면 안 된다.
  const stateBlock = report.protocol_state && report.protocol_state !== "unknown"
    ? `<div class="ll-state ${esc(report.protocol_state)}">이 배치의 프로토콜 상태:
        <b>${esc(READINESS[report.protocol_state]?.label || report.protocol_state)}</b></div>`
    : "";

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

  $("wl-out").innerHTML = stateBlock + readBlock + verdictBlock + directiveBlock;
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
    "spec.ready", "candidate", "rule.fired", "verdict", "evidence", "judge.summoned",
    "judge.token", "judge.verdict", "consensus", "reflect", "warning", "error",
    "confirmation", "approval", "wetlab"];
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
  candidates.clear(); tokenBuffers.clear(); degraded.clear(); assessments.clear();
  winnerId = null; lastApplied = {};
  resetNarration();
  $("trace").innerHTML = ""; $("cands").innerHTML = "";
  $("consensus").hidden = true;
  $("evidence").hidden = true;
  $("evidence").innerHTML = "";
  $("wl-out").innerHTML = "";
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
    const { measured, flags } = collectInputs();
    const res = await fetch(api("/api/runs"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request,
        smiles: $("smiles").value.trim() || null,
        required_excipients: $("pinned").value.split(",").map((s) => s.trim()).filter(Boolean),
        measured_params: measured,
        property_flags: flags,
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
    // 카탈로그에 없는 키는 서버가 버린다. 조용히 넘기면 "왜 안 먹었는지"를 알 수 없다.
    if ((data.rejected_inputs || []).length) {
      notice(`입력 중 ${data.rejected_inputs.length}건이 허용 목록에 없어 제외됐습니다: `
        + data.rejected_inputs.join(", "), "warn");
    }
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
          layer: "P5 · 동적 소집", kind: "jud",
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

    case "evidence": {
      const blocking = (p.gaps || []).filter(isBlocking);
      const tests = [...new Set(blocking.map((g) => g.test_id))].slice(0, 3);
      narrate("evidence", {
        layer: "P4 · 근거 충족 게이트", kind: blocking.length ? "warn" : "det",
        title: blocking.length
          ? "룰은 통과했지만, 실행할 만큼 알지는 못한다"
          : "선행 근거가 충족돼 검토용 프로토콜을 낼 수 있다",
        body: `${esc(p.summary || "")}
          ${tests.length ? `<br>선행 확인시험: ${tests.map((t) => `<code>${esc(t)}</code>`).join(" ")}` : ""}
          <span class="nr-why">왜 중요한가: 룰북 통과는 "금기를 발견하지 못했다"이지 "안전이
          확정됐다"가 아닙니다. 신약 API는 정보 자체가 없어서 위반이 안 잡히기도 합니다.
          그래서 <b>금기 판정과 근거 판정을 분리</b>하고, 근거가 비면 반려 대신
          <b>실행을 보류</b>하고 확인시험을 먼저 요청합니다.</span>`,
      });
      break;
    }

    case "judge.verdict":
      narrate("judge", {
        layer: "P6 · 심사 LLM", kind: "jud",
        title: "심사관은 순위만 매긴다 (반려 권한 없음)",
        body: `${esc(p.persona)} → 점수 <b>${esc(p.score)}</b>
          <span class="nr-why">왜 중요한가: 안전·규제 판정은 이미 룰북이 끝냈습니다. 심사관
          점수는 통과한 후보들 사이의 순위 결정에만 쓰입니다 — LLM에게 안전 판정을 맡기지
          않겠다는 설계가 권한 분리로 구현돼 있습니다.</span>`,
      });
      break;

    case "consensus":
      narrate("consensus", {
        layer: "P7 · 합의 결정론", kind: "det",
        title: "합의는 최종 처방이 아니라 권고 후보를 고른다",
        body: `권고 후보 <b>${esc(p.winner || "없음")}</b> · 모델 ${esc(p.model || "")}
          ${p.readiness ? `· 상태 <b>${esc(READINESS[p.readiness]?.label || p.readiness)}</b>` : ""}
          <span class="nr-why">왜 중요한가: 결정론 하드페일과 심사 가중점수를 합쳐 순위를
          정합니다. 다만 그 후보가 <b>실행 가능한 프로토콜인지는 근거 게이트가 따로</b>
          정하고, 마지막에 연구자가 승인해야 상태가 바뀝니다.</span>`,
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
    title: "실행 전 근거 → 배치 → 다음 실험",
    proves: "이중 루프 (근거 게이트 + Lab-in-the-loop)",
    // 이 시나리오의 요점은 두 루프라 설계 단계는 가볍게 둔다 —
    // 심사관이 많이 소집되면 무료 티어 토큰이 설계에서 다 소모되고 지시가 규칙 기반으로 내려간다.
    request: "성인용 이부프로펜 정제를 설계해줘",
    pinned: "",
    duration: "약 2~3분",
    autoLab: true,
    goal: `설계가 끝나면 먼저 <b>근거 충족 게이트</b>가 “이 전략을 실행할 만큼 아는가”를 묻습니다.
      선행 확인시험 결과를 자동 입력해 근거를 채우고 <b>연구자 승인</b>까지 진행한 뒤에야
      배치 결과를 넣습니다. AI가 문장에서 수치를 판독하고, 규칙이 규격 이탈을 판정한 뒤,
      확인시험 마스터 66종에서 <b>다음에 할 실험</b>을 골라 지시합니다 —
      두 루프의 결과가 서로 다른 계층으로 돌아가는 것이 이 구조의 요지입니다.`,
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

/* 시나리오가 두 루프까지 이어질 때, 설계가 끝나면 순서대로 자동 진행한다.
   실행 전 루프(확인시험 → 근거 재평가 → 승인)를 먼저 돌고, 그 다음에야 배치 결과를 넣는다 —
   순서 자체가 이 아키텍처의 주장이라 시연도 같은 순서로 흐른다. */
async function continueScenario() {
  if (!activeScenario || !activeScenario.autoLab) return;

  const id = (winnerId && assessments.has(winnerId)) ? winnerId : [...assessments.keys()][0];
  if (id) {
    narrate("evloop-start", {
      layer: "실험 전 루프", kind: "det",
      title: "먼저 “실행해도 되는가”를 해결한다",
      body: `선행 확인시험 결과를 자동 입력해 근거를 채우고, 연구자 승인까지 진행합니다.
        <span class="nr-why">왜 중요한가: 이 단계를 건너뛰면 수분·열 안정성도 모르는 API에
        습식과립 프로토콜을 그대로 내보내게 됩니다. 배치를 만든 뒤에는 되돌릴 수 없습니다.</span>`,
    });
    $("evidence").scrollIntoView({ behavior: "smooth", block: "nearest" });
    if ($("ev-example")) {
      fillConfirmationExample();
      await submitConfirmation(id);
      await new Promise((done) => setTimeout(done, 400));
    }
    if ($("ev-approve")) await approveProtocol(id);
  }

  narrate("labloop-start", {
    layer: "실험 후 루프", kind: "llm",
    title: "이제 만든 뒤의 절반 — 배치 결과를 넣는다",
    body: `배치 결과를 자연어로 자동 입력합니다. AI가 판독 → 규칙이 판정 → AI가 다음 실험을 지시.
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

/* ── 실험 데이터 입력 (선택) ─────────────────────────────────────────
   서버의 카탈로그(`/api/inputs`)를 그대로 그린다. 항목을 늘리는 일이 YAML 편집이지
   프런트 수정이 아니어야 하므로, 필드 목록을 여기에 복사해 두지 않는다.
   각 항목의 `unlocks`(무엇이 열리는가)를 같이 보여준다 — 그게 없으면 아무도 안 채운다. */
let inputCatalog = { groups: [] };

async function loadInputCatalog() {
  try {
    const res = await fetch(api("/api/inputs"));
    if (!res.ok) return;
    inputCatalog = await res.json();
  } catch (err) {
    return;   // 부가 입력이라 실패해도 실행은 된다
  }
  $("inputs-body").innerHTML = (inputCatalog.groups || []).map((g) => `
    <fieldset class="inputs-group">
      <legend>${esc(g.label)}</legend>
      <div class="inputs-note">${esc(g.note || "")}</div>
      ${(g.fields || []).map((f) => f.type === "bool"
        ? `<label class="inputs-check">
             <input type="checkbox" data-key="${esc(f.key)}" data-type="bool">
             <span><b>${esc(f.label)}</b><small>${esc(f.unlocks || "")}</small></span>
           </label>`
        : `<label class="inputs-field">
             <span class="inputs-label"><b>${esc(f.label)}</b>
               ${f.unit ? `<i>${esc(f.unit)}</i>` : ""}</span>
             <input type="number" step="any" data-key="${esc(f.key)}" data-type="number"
                    placeholder="${esc(f.placeholder || "")}">
             <small>${esc(f.unlocks || "")}</small>
           </label>`).join("")}
    </fieldset>`).join("");

  $("inputs-body").addEventListener("input", updateInputCount);
  $("inputs-clear").onclick = () => {
    $("inputs-body").querySelectorAll("input").forEach((el) => {
      if (el.type === "checkbox") el.checked = false; else el.value = "";
    });
    updateInputCount();
  };
}

function collectInputs() {
  const measured = {}, flags = {};
  $("inputs-body").querySelectorAll("input").forEach((el) => {
    const key = el.dataset.key;
    if (el.dataset.type === "bool") {
      if (el.checked) flags[key] = true;
    } else if (el.value.trim() !== "" && Number.isFinite(Number(el.value))) {
      measured[key] = Number(el.value);
    }
  });
  return { measured, flags };
}

function updateInputCount() {
  const { measured, flags } = collectInputs();
  const n = Object.keys(measured).length + Object.keys(flags).length;
  $("inputs-count").textContent = n ? `${n}개 입력됨 — 그만큼 선행 확인시험이 줄어듭니다` : "";
}

/* ── SMARTS 직접 검사 ────────────────────────────────────────────────
   룰북의 배합금기 판정은 SMARTS 매칭에서 출발한다. 판정을 믿으려면 "그 패턴이 정말
   이 분자에 있는가"를 사람이 확인할 수 있어야 하므로, 그 계층을 화면에 그대로 노출한다.
   패턴 프리셋은 룰북이 실제로 쓰는 structural_flags_smarts.csv 에서 가져온다. */
let lastSmiles = "";
let smartsPatterns = [];

async function loadSmartsPresets() {
  try {
    const res = await fetch(api("/api/chem/smarts"));
    if (!res.ok) return;
    const { patterns, count } = await res.json();
    smartsPatterns = patterns;

    // 82개를 버튼으로 깔면 사이드바가 못 쓰게 된다 — 기준서 절별로 묶어 고르게 한다.
    const SECTIONS = {
      "4": "질소·아민", "5": "니트로사민", "6": "산·염기", "7": "가수분해",
      "8": "산화", "9": "반응성", "10": "금속 결합", "11": "광분해", "12": "고체상",
    };
    const groups = {};
    patterns.forEach((p, i) => (groups[p.section] ||= []).push({ ...p, i }));
    $("sm-presets").innerHTML = `
      <select id="sm-pick" aria-label="구조 패턴 선택">
        <option value="">규칙표가 쓰는 패턴 ${esc(count)}종에서 고르기…</option>
        ${Object.keys(SECTIONS).filter((k) => groups[k]).map((k) =>
          `<optgroup label="${esc(SECTIONS[k])}">${groups[k].map((p) =>
            `<option value="${p.i}">${esc(p.flag_name)}</option>`).join("")}</optgroup>`).join("")}
      </select>`;
    $("sm-pick").onchange = (e) => {
      const pattern = smartsPatterns[Number(e.target.value)];
      if (!pattern) return;
      $("sm-pattern").value = pattern.smarts;
      $("sm-out").innerHTML = `<div class="sm-note">
        <b>${esc(pattern.flag_id)} ${esc(pattern.flag_name)}</b>
        <div>발동 규칙: <code>${esc(pattern.triggers_rule || "-")}</code>
          · 경고 등급 <b>${esc(pattern.alert_level)}</b> · 특이도 ${esc(pattern.specificity)}</div>
        <div>${esc(pattern.risk_context || "")}</div>
        ${pattern.confirmation_test ? `<div>확인시험: ${esc(pattern.confirmation_test)}</div>` : ""}
        ${pattern.notes ? `<div class="sm-notes">주의: ${esc(pattern.notes)}</div>` : ""}
      </div>`;
    };
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
  loadInputCatalog();
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
