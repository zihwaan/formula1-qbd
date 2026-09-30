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
let winnerId = null;            // 합의가 고른 권고 후보
let pendingRequests = [];       // v3 — 아직 안 풀린 데이터 요청(narrows_strategy)

/* ── 고정 그래프 레이아웃 ────────────────────────────────────────────
   kind: det(결정론) | llm(LLM 판단) | jud(동적 심사관)
   게이트가 둘이라는 것이 이 그래프의 요지다: gate(금기가 있는가) → evidence(알고 있는가). */
const NODES = [
  { id: "intake",      x:   8, y: 30, w: 96, label: "intake",      sub: "요구 → 스펙",   kind: "llm" },
  { id: "phase_gates", x: 116, y: 30, w: 96, label: "phase_gates", sub: "BCS/DCS·고체상", kind: "det" },
  { id: "drq_narrow",  x: 224, y: 30, w: 96, label: "drq_narrow",  sub: "좁히는 요청",   kind: "det" },
  { id: "plan",        x: 332, y: 30, w: 96, label: "plan",        sub: "전략 ≤3",       kind: "det" },
  { id: "generate",    x: 440, y: 30, w: 96, label: "generate",    sub: "후보 병렬 설계", kind: "llm" },
  { id: "gate",        x: 548, y: 30, w: 96, label: "gate",        sub: "룰북 판정",     kind: "det" },
  { id: "drq_refine",  x: 656, y: 30, w: 96, label: "drq_refine",  sub: "신뢰도 요청",   kind: "det" },
  { id: "summon",      x: 764, y: 30, w: 96, label: "summon",      sub: "심사관 소집",   kind: "det" },
  { id: "consensus",   x: 872, y: 30, w: 100, label: "consensus",  sub: "가중 합의",     kind: "det" },
  { id: "backtrack",   x: 548, y: 210, w: 96, label: "backtrack",  sub: "사유별 복귀",   kind: "det" },
  { id: "reflect",     x: 380, y: 210, w: 96, label: "reflect",    sub: "재설계 지시",   kind: "llm" },
];
const EDGES = [
  ["intake", "phase_gates"], ["phase_gates", "drq_narrow"], ["drq_narrow", "plan"], ["plan", "generate"],
  ["generate", "gate"], ["gate", "drq_refine"], ["drq_refine", "summon"], ["summon", "consensus"],
];
/* 되먹임은 규칙 반려 하나뿐이다 — 반려 사유가 복귀 지점을 정한다(backtrack_transitions.csv).
   데이터 요청(drq_*)은 그래프를 다시 돌지 않고 /api/runs/{id}/measurements가 결정론적으로 재계산한다. */
const LOOPS = [
  { d: "M 596 76 L 596 210", key: "gate->backtrack", label: "반려", lx: 602, ly: 150 },
  { d: "M 548 233 L 476 233", key: "backtrack->reflect" },
  { d: "M 440 210 L 440 160 L 488 160 L 488 76", key: "reflect->generate", label: "성분만 교체", lx: 494, ly: 156 },
  { d: "M 400 210 L 400 160 L 380 160 L 380 76", key: "reflect->plan", label: "전략·경로부터", lx: 300, ly: 156 },
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
    id: `judge-${reviewerId}`, x: 742, y: 100 + index * 56, w: 140,
    label: reviewerId, sub: persona.slice(0, 14), kind: "jud",
  };
  judgeNodes.set(reviewerId, node);
  const svg = $("graph");
  const edge = document.createElementNS(SVG_NS, "path");
  edge.setAttribute("d", `M 812 76 L 812 ${node.y}`);
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
      addTrace(ev.seq, "intake", `RDKit 계산 완료 · 플래그 ${(p.flags||[]).filter(f=>f.present).length}건`
        + ` · ${p.is_salt ? "parent " : ""}MW ${Number((p.descriptors || {}).molecular_weight || 0).toFixed(1)}`
        + (p.is_salt && p.salt_molecular_weight ? ` (염 ${Number(p.salt_molecular_weight).toFixed(1)} · 환산 ${p.salt_factor})` : ""));
      break;

    case "phase.gate":
      // phase_gates 노드가 BCS/DCS·고체상·가용화 신호마다 하나씩 낸다(candidate 생성 전).
      addTrace(ev.seq, "phase_gates",
        `${p.gate}/${p.rule_id} → ${fmtAssigned(p.assigned) || p.action}`
        + (p.inputs && Object.keys(p.inputs).length ? ` · 입력 ${fmtAssigned(p.inputs)}` : "")
        + (p.citation ? ` · ${p.citation}` : ""));
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
      if (p.score === null || p.score === undefined) {
        unavailable.judges += 1;
        addTrace(ev.seq, ev.node, `${p.persona}: 점수 없음 — LLM 응답 없음`, "warn");
      } else {
        addTrace(ev.seq, ev.node, `점수 ${p.score} — ${p.rationale.slice(0, 80)}`);
      }
      renderCandidates();
      break;
    }

    case "data.request": {
      // drq_refine이 후보별로 낸다(candidate_id 있음) — phase_gates의 narrows_strategy
      // 요청(candidate_id 없음)은 run.end의 pending_requests로 한 번에 렌더한다.
      if (p.candidate_id) {
        const entry = candidates.get(p.candidate_id);
        if (entry) {
          entry.recipe.confidence = p.confidence;
          entry.recipe.pending_refinements = (p.pending || []).map((r) => r.trigger_id);
          renderCandidates();
        }
        addTrace(ev.seq, "drq_refine", `${p.candidate_id}: ${p.confidence}`
          + ((p.pending || []).length ? ` · 남은 요청 ${p.pending.length}건` : ""));
      }
      break;
    }

    case "consensus": renderConsensus(p);
      winnerId = p.winner || null;
      addTrace(ev.seq, "consensus", `권고 후보: ${p.winner || "없음"} (보고 ${p.reported}건)`);
      break;

    case "reflect":
      addTrace(ev.seq, "reflect", `${p.root_cause} → ${p.directive}`, "warn");
      break;

    case "backtrack":
      addTrace(ev.seq, "backtrack",
        `${p.transition_id} → ${p.return_phase}${p.escalated_from ? ` (${p.escalated_from} 3회 초과 → 상향)` : ""}`
        + (Object.keys(p.patch || {}).length ? ` · 제약 ${Object.entries(p.patch).map(([k, v]) => `${k}=${v.join(",")}`).join(" · ")}` : ""), "warn");
      break;

    case "warning":
      addTrace(ev.seq, ev.node, p.message || (p.reason + (p.fallback ? " → 규칙 기반 처리(LLM 미사용)" : "")), "warn");
      if (ev.node === "infeasible") renderInfeasible(p);
      if (p.fallback) degraded.add(ev.node);
      if (p.no_candidate) unavailable.designs += 1;
      break;
    case "error":
      addTrace(ev.seq, ev.node, `오류: ${p.error}`, "hard_fail");
      notice(`실행 중 오류가 발생했습니다 — ${p.error}`, "error", true);
      break;
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

  // 검출된 구조 패턴만 먼저 — 검출 안 된 패턴(수십 개)은 접어 둔다(시연 화면이 칩으로 뒤덮이지 않게)
  const flags = p.flags || [];
  const on = flags.filter((f) => f.present), off = flags.filter((f) => !f.present);
  $("mol-flags").innerHTML = (on.length ? on.map((f) => `<span class="flag on">${esc(f.flag_name)}</span>`).join("")
      : `<span class="flags-none">검출된 구조 경고 없음</span>`)
    + (off.length ? `<details class="flags-more"><summary>검출 안 된 패턴 ${off.length}개</summary>
        <div class="flags">${off.map((f) => `<span class="flag">${esc(f.flag_name)}</span>`).join("")}</div></details>` : "");

  // 판단에 주로 쓰는 descriptor를 먼저, 나머지는 접는다
  const KEY_DESC = ["molecular_weight", "clogp", "tpsa", "hbond_donors", "hbond_acceptors", "rotatable_bonds", "aromatic_rings",
    "fraction_csp3", "qed", "lipinski_pass", "veber_pass", "heavy_atom_count"];
  const desc = Object.entries(p.descriptors || {});
  const fmt = (v) => (typeof v === "boolean" ? (v ? "예" : "아니오") : Number.isFinite(Number(v)) ? Number(v).toFixed(2) : esc(v));
  const keyRows = KEY_DESC.filter((k) => k in (p.descriptors || {})).map((k) => [k, p.descriptors[k]]);
  const rest = desc.filter(([k]) => !KEY_DESC.includes(k));
  const row = ([k, v]) => `<tr><td>${esc(k)}</td><td>${fmt(v)}</td></tr>`;
  $("mol-desc").innerHTML = `<tbody class="desc-key">${(keyRows.length ? keyRows : desc.slice(0, 12)).map(row).join("")}</tbody>`
    + (rest.length && keyRows.length ? `<tbody class="desc-rest" hidden>${rest.map(row).join("")}</tbody>
       <tfoot><tr><td colspan="2"><button type="button" class="linkish desc-toggle">전체 descriptor ${desc.length}개 보기</button></td></tr></tfoot>` : "");
  const dt = $("mol-desc").querySelector(".desc-toggle");
  if (dt) dt.onclick = () => {
    const r = $("mol-desc").querySelector(".desc-rest");
    r.hidden = !r.hidden;
    dt.textContent = r.hidden ? `전체 descriptor ${desc.length}개 보기` : "핵심 descriptor만 보기";
  };

  $("mol-est").innerHTML = (p.estimates || []).map((e) =>
    `<div class="est"><b>${esc(e.property)}</b> = ${esc(e.value)}
     <span class="${e.confidence === "low" ? "lo" : ""}">[${esc(e.confidence)}]</span></div>`).join("");

  $("mol-warn").innerHTML = (p.warnings || []).length
    ? `<div class="warn">⚠ ${p.warnings.map(esc).join("<br>⚠ ")}</div>` : "";
}

/* 프로토콜 실행 상태 — 룰 통과와는 다른 축이다. 라벨을 한 곳에서만 관리한다. */
const rankOf = new Map();   // candidate_id → 합의 순위

function citeLink(c) {
  const [kind, id] = String(c).split(" ");
  const url = kind === "DOI" ? `https://doi.org/${id}` : kind === "PMID" ? `https://pubmed.ncbi.nlm.nih.gov/${id}/`
    : kind === "PMC" ? `https://pmc.ncbi.nlm.nih.gov/articles/${id}/` : "";
  return url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(c)}</a>` : esc(c);
}

/* ── 근거 결손 게이트(발표 자료 ⑤) — 후보 목록은 그대로 두고, 결손이 남은 후보의 개발 착수만 보류한다 ──────── */
let evidence = {};              // candidate_id → 서버 판정(GET /api/runs/{id}/evidence)
async function loadEvidence() {
  if (!runId) return;
  try {
    const res = await fetch(api(`/api/runs/${runId}/evidence`));
    if (!res.ok) return;
    evidence = (await res.json()).candidates || {};
    renderCandidates();
  } catch (e) { /* 보조 — 실패해도 후보 목록은 그대로 */ }
}
function evidenceBox(id) {
  const ev = evidence[id];
  if (!ev) return "";
  const pr = ev.protocol || {};
  const before = pr.before_protocol || [], par = pr.parallel || [];
  const failed = (ev.failed || []).length, open = (ev.blocking || []).length - failed;
  const head = failed ? `<b class="ev-bad">근거 부적합 ${failed}건</b> — 전제가 부정됨, 개발로 넘기지 않음`
    : open ? `<b class="ev-hold">근거 결손 ${open}건 — 보류</b> · 측정값을 넣으면 phase_gates부터 다시 계산`
      : `<b class="ev-ok">근거 충족</b>${par.length ? ` · 병행 시험 ${par.length}건` : ""}`;
  const item = (g) => `<li data-req="${esc(g.requirement_id)}"><b>${esc(g.label)}</b> <code>${esc(g.test_id)}</code> ${esc(g.test_name || "")}
      <div class="ev-why">${esc(g.why || "")}${g.acceptance_logic ? ` · 판정: ${esc(g.acceptance_logic)}` : ""}${g.result_note ? ` · 결과: ${esc(g.result_note)}` : ""}</div>
      ${g.status === "missing" && (g.inputs || []).length ? `<div class="ev-form">${(g.inputs || []).map((f) => f.type === "bool"
          ? `<label class="ev-chk"><input type="checkbox" data-key="${esc(f.key)}" data-type="bool"> ${esc(f.label)} 수행</label>`
          : `<label class="ev-numl">${esc(f.label)}<input class="ev-num" data-key="${esc(f.key)}" data-type="number" inputmode="decimal"
              placeholder="값" title="${esc(f.key)}" aria-label="${esc(f.label)}${f.unit ? ` (${esc(f.unit)})` : ""}">${f.unit ? `<small>${esc(f.unit)}</small>` : ""}</label>`).join("")}
        <select class="ev-grade" aria-label="근거 등급">${Object.entries(GRADE_KO).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select>
        <button type="button" class="ev-send">값 입력 → 재계산</button>
        <button type="button" class="ev-talk ghost" data-label="${esc(g.label)}">말로 입력</button></div>` : ""}</li>`;
  return `<details class="ev-box ${failed ? "bad" : open ? "hold" : "ok"}"><summary>근거 결손 게이트 · ${head}</summary>
    ${before.length ? `<ul class="ev-list">${before.map(item).join("")}</ul>` : `<p class="ev-why">선행 확인시험 요구 없음</p>`}
    ${par.length ? `<p class="ev-why">병행(배치와 함께): ${par.map((g) => `${esc(g.label)} <code>${esc(g.test_id)}</code>`).join(" · ")}</p>` : ""}
    ${open ? `<p class="ev-why">값은 입력 에이전트에 말로 적어도 된다 — 용해도는 잰 pH와 함께, 투과도는 흡수율·절대 생체이용률·요중 회수율·Papp 중
      가진 자료를 쓰던 단위 그대로. 단위 환산과 pH별 최저값, 용량/용해도 부피는 코드가 계산해 제출 카드로 만든다.</p>` : ""}
    <p class="ev-why">요청 시험은 확인시험 마스터(66종)의 실제 행에서만 고른다 — 판정은 결정론, LLM 없음.</p></details>`;
}
function devButton(id) {
  const ev = evidence[id] || {};
  const failed = (ev.failed || []).length, open = (ev.blocking || []).length - failed;
  if (failed) return `<button type="button" class="dev-start" disabled title="확인시험 부적합 — 재설계가 필요합니다">개발 불가(근거 부적합)</button>`;
  return `<button type="button" class="dev-start${open ? " hold" : ""}" data-cand="${esc(id)}"
    title="이 처방을 프로토타입으로 받아 2단계(QTPP → 위험평가 → DoE → 회귀·ANOVA → Design Space)를 시작합니다">${open ? "결손을 기록하고 개발 착수 →" : "이 후보로 개발 착수 →"}</button>
    ${open ? `<div class="ev-waive" hidden><p class="ev-why">선행 근거 ${open}건이 비어 있습니다 — 아래 사유를 확인하고(고칠 수 있음) <b>사유 기록 · 개발 착수</b>를 누르면
      사유와 남은 결손이 2단계 기록·보고서에 남고 바로 2단계로 넘어갑니다. 확인시험 결과가 있으면 위 근거 상자에서 넣으면 됩니다.</p>
      <textarea rows="3" aria-label="근거 결손을 둔 채 진행하는 사유"></textarea>
      <button type="button" class="ev-waive-go">사유 기록 · 개발 착수 →</button><span class="ev-waive-msg" role="status"></span></div>` : ""}`;
}
// 결손 사유 기본 문구 — 무엇이 비었는지와 언제 확인할지만 적는다(수치를 만들지 않는다). 연구자가 고쳐 쓸 수 있다.
function waiverDefault(cid) {
  const ev = evidence[cid] || {};
  const gaps = ((ev.protocol || {}).before_protocol || []).filter((g) => g.status === "missing").map((g) => `${g.label}(${g.test_id})`);
  return `선행 근거 결과 없이 진행: ${gaps.join(", ") || "결손 항목"} — 개발 초기 배치와 병행해 확인하기로 함(연구자 판단).`;
}
const cardOf = (cid) => [...$("cands").querySelectorAll(".card")].find((c) => c.dataset.cand === cid) || null;
// 결과: "started"(2단계 열림) | "waiver"(결손 — 카드에 사유 칸을 열었음) | "error". 후보 카드 버튼과 입력 에이전트가 같은 길을 쓴다.
async function startDevelopment(cid, card, retried) {
  if (!evidence[cid] && runId && !running) await loadEvidence();     // 판정을 읽기 전에 눌렀으면 먼저 읽는다
  if (!card || !card.isConnected) card = cardOf(cid);                // loadEvidence가 카드를 다시 그린다
  if (!card && candidates.has(cid)) { renderCandidates(); card = cardOf(cid); }
  const ev = evidence[cid] || {};
  const open = ((ev.blocking || []).length - (ev.failed || []).length) > 0;
  if (open && !card) {          // 사유 칸을 열 카드가 없다 — 사유 없이 서버로 보내 409를 반복하지 않는다
    notice(`후보 ${cid}의 카드가 화면에 없습니다 — 후보 카드의 [결손을 기록하고 개발 착수]로 진행해 주세요.`, "warn");
    return "error";
  }
  if (open) {                   // 결손이 남았으면 사유를 받는다 — 연구자 결정으로 Handoff와 보고서에 남는다
    const w = card.querySelector(".ev-waive");
    const ta = w.querySelector("textarea"), msg = w.querySelector(".ev-waive-msg"), go = w.querySelector(".ev-waive-go");
    if (w.hidden) { w.hidden = false; if (!ta.value.trim()) ta.value = waiverDefault(cid); }
    w.scrollIntoView({ block: "center", behavior: "smooth" });   // 카드가 한 화면보다 길다 — 사유 칸 자체를 가운데로
    go.focus({ preventScroll: true });
    const submit = async () => {
      const reason = ta.value.trim();
      if (!reason) { msg.textContent = "사유를 적어 주세요 — 근거 결손을 둔 채 진행한 이유가 2단계 기록에 남습니다."; ta.focus(); return; }
      msg.textContent = "2단계를 여는 중…";
      go.disabled = true;
      try { await window.F1Stage2.startFromCandidate(runId, cid, reason); msg.textContent = "2단계를 열었습니다 — 아래로 이어집니다."; }
      catch (e) { msg.textContent = e.message || "2단계를 열지 못했습니다."; }
      finally { go.disabled = false; }
    };
    go.onclick = submit;
    ta.onkeydown = (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); } };
    return "waiver";
  }
  try {
    await window.F1Stage2.startFromCandidate(runId, cid);
    return "started";
  } catch (e) {
    if (e.code === "EVIDENCE_GAPS" && !retried) {   // 화면의 판정이 낡았다 — 다시 읽고 사유 칸을 연다
      await loadEvidence();
      return startDevelopment(cid, null, true);
    }
    if (e.code === "EVIDENCE_GAPS") notice(e.message, "warn");
    return "error";
  }
}
function wireEvidence(card, cid) {
  // 근거 결손 게이트의 입력 = 측정값 — phase_gates부터 다시 계산한다(같은 재계산 경로: POST /measurements). 적합/부적합은 묻지 않는다.
  // '말로 입력'은 입력 에이전트로 넘긴다 — 항목 이름만 채우고 값은 사용자가 쓴다(환산은 서버 코드가 한다)
  card.querySelectorAll(".ev-talk").forEach((b) => {
    b.onclick = () => { if (window.F1Agent) window.F1Agent.focus(`${b.dataset.label}: `); };
  });
  card.querySelectorAll(".ev-send").forEach((b) => {
    b.onclick = async () => {
      const li = b.closest("li");
      const measurements = {};
      let bad = "";
      li.querySelectorAll("[data-key]").forEach((el) => {
        if (el.dataset.type === "bool") { if (el.checked) measurements[el.dataset.key] = true; return; }
        const v = el.value.trim();
        if (v === "") return;
        const n = Number(v);
        if (!Number.isFinite(n)) bad = el.dataset.key; else measurements[el.dataset.key] = n;
      });
      if (bad) { notice(`${bad}: 숫자로 넣어 주세요.`, "warn"); return; }
      if (!Object.keys(measurements).length) { notice("측정값을 넣거나 수행 여부를 체크해 주세요.", "warn"); return; }
      b.disabled = true; b.textContent = "재계산 중…";
      // 재계산 · 근거 재판정 · 해설은 submitMeasurements가 한다(말로 입력한 값과 같은 길)
      const out = await submitMeasurements(measurements, li.querySelector(".ev-grade").value, "evidence");
      if (!out) { b.disabled = false; b.textContent = "값 입력 → 재계산"; }
    };
  });
}

// 심사관 서술은 세 줄로 접어 두고 필요할 때 펼친다(후보 카드가 한 화면을 넘지 않게)
$("cands").addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest(".jn-more");
  if (!b) return;
  const n = b.closest(".judge-note");
  n.classList.toggle("open");
  b.textContent = n.classList.contains("open") ? "접기" : "더 보기";
});

function renderCandidates() {
  const box = $("cands");
  if (!candidates.size) return;
  $("cand-count").textContent = `${candidates.size}건`;
  box.innerHTML = "";
  // 순위가 매겨졌으면 순위대로(#1 → #2 → #3), 순위 없는 후보는 뒤로
  const ordered = [...candidates.entries()].sort(([a], [b]) =>
    (rankOf.get(a) ?? 999) - (rankOf.get(b) ?? 999));
  for (const [id, entry] of ordered) {
    const gate = entry.gate;
    const card = document.createElement("div");
    card.className = "card " + (gate ? (gate.passed ? "pass" : "fail") : "");
    card.dataset.cand = id;
    const ings = entry.recipe.ingredients
      .map((i) => `${esc(i.name)} ${esc(i.amount_mg ?? "-")}mg`).join(" · ");
    const chips = entry.verdicts.map((v) =>
      `<span class="chip ${esc(v.status)}" data-rule="${esc(v.rule_id)}">${esc(v.rule_id)}</span>`).join("");
    const judges = entry.judges.map((j) =>
      j.score === null || j.score === undefined
        ? (j.source === "uncited"
          ? `<div class="judge-note unscored"><b>${esc(j.persona)}</b> 점수 무효 <span class="stand-in-tag">검증된 인용(DOI/PMID) 없음 — 제안 점수 ${esc(j.proposed_score ?? "-")}는 합의에 쓰지 않음</span></div>`
          : `<div class="judge-note unscored"><b>${esc(j.persona)}</b> 점수 없음 <span class="stand-in-tag">LLM 응답 없음 · 재시도 후에도 응답 없어 점수를 만들지 않음</span></div>`)
        : `<div class="judge-note clamp"><b>${esc(j.persona)}</b> ${esc(j.score)} — <span class="jn-text">${esc(j.rationale)}</span>
            ${(j.citations || []).length ? `<div class="cites">${j.citations.map(citeLink).join(" · ")}</div>` : ""}
            ${String(j.rationale || "").length > 140 || (j.citations || []).length > 2 ? `<button type="button" class="linkish jn-more">더 보기</button>` : ""}</div>`).join("");
    const readiness = gate && gate.passed ? evidenceBox(id) : "";
    // v3 — confidence는 pending_refinements가 비어 있는지로 정확히 정해진다(불변식 I-10).
    // LLM이 이 값을 직접 쓰지 않는다 — drq_refine이 매긴 값을 그대로 보여줄 뿐이다.
    // 게이트 판정이 먼저다 — 반려된 후보에는 신뢰도 배지를 붙이지 않는다(반려 + grounded는 모순으로 읽힌다)
    const gateBadge = gate ? `<span class="gate-badge ${gate.passed ? "pass" : "fail"}">${gate.passed ? "통과" : "반려"}</span>` : "";
    const rank = rankOf.get(id);
    const confidence = (rank ? `<span class="rank-badge">#${esc(rank)}</span>` : "") + gateBadge
      + (entry.recipe.confidence && (!gate || gate.passed)
        ? `<span class="drq-badge ${esc(entry.recipe.confidence)}">${esc(entry.recipe.confidence)}</span>` : "");
    // 반려된 후보의 신뢰도 요청은 의미가 없다(반려가 먼저) — 카드만 길어진다
    const refinements = (entry.recipe.pending_refinements || []).length && (!gate || gate.passed)
      ? `<div class="drq-refine">남은 신뢰도 요청: ${entry.recipe.pending_refinements.map(esc).join(", ")}</div>`
      : "";
    card.innerHTML = `
      <h4>${esc(id)}${confidence}<span class="tag">${esc(entry.recipe.strategy)} · ${esc(entry.recipe.process || "")}</span></h4>
      <div class="ing">${ings}</div>
      ${(entry.recipe.process_steps || []).length ? `<div class="ing">공정: ${entry.recipe.process_steps.map(esc).join(" → ")}</div>` : ""}
      ${readiness}${refinements}
      <div class="chips">${chips}</div>${judges}
      ${gate && gate.passed ? devButton(id) : ""}`;
    card.querySelectorAll(".chip").forEach((chip) => {
      chip.onclick = () => showRule(chip.dataset.rule);
    });
    // 후보 1위가 자동으로 개발에 들어가지 않는다(명세 v6.1 §0 경계 1) — 연구자가 고른 후보만 넘어간다.
    const dev = card.querySelector(".dev-start");
    if (dev) dev.onclick = () => startDevelopment(dev.dataset.cand, card);
    wireEvidence(card, id);
    box.appendChild(card);
  }
}

// 제약 불가능 종료 — 결론은 해설 칼럼(모바일에선 닫혀 있다)이 아니라 대화의 후보 카드 안에 둔다.
function renderInfeasible(p) {
  const el = $("consensus");
  el.hidden = false;
  el.classList.add("infeasible");
  $("cands").before(el);          // 결론부터 — 반려된 후보 카드는 그 아래 근거로
  const judges = p.planned_judges || [];
  el.innerHTML = `<h3>결론 · 이 제약으로는 통과하는 처방이 없음</h3>
    <div class="win">${esc(p.reason || "")}</div>
    ${(p.blocking || []).slice(0, 3).map((b) => `<div class="inf-rule"><code>${esc(b.rule_id)}</code> ${esc(b.reason)}${
      b.suggestion ? ` → 대안 <b>${esc(b.suggestion)}</b>` : ""}</div>`).join("")}
    ${(p.also_blocking || []).length ? `<div class="inf-rule">함께 걸린 반려 규칙: ${p.also_blocking.map((b) =>
      `<code title="${esc(b.reason || "")}">${esc(b.rule_id)}</code>`).join(" · ")}${
      p.also_blocking.some((b) => b.suggestion) ? ` → 대안 ${[...new Set(p.also_blocking.map((b) => b.suggestion).filter(Boolean))].slice(0, 2).map((x) => `<b>${esc(x)}</b>`).join(" · ")}` : ""}</div>` : ""}
    ${judges.length ? `<div class="tag" style="margin-top:6px">소집 예정이던 심사관: ${judges.map((j) => `<b>${esc(j.persona)}</b>`).join(" · ")}
      — 반려 원인이 고정 조건이라 심사·재설계 없이 종료(재설계 0회)</div>` : ""}`;
}

function renderConsensus(p) {
  const el = $("consensus");
  el.hidden = false;
  el.classList.remove("infeasible");
  $("cands").after(el);
  rankOf.clear();
  (p.ranked || []).forEach((r) => { if (r.rank) rankOf.set(r.candidate_id, r.rank); });
  const ranked = [...(p.ranked || [])].sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
  renderCandidates();
  const rows = ranked.map((r) =>
    `<div>${r.rank ? `#${esc(r.rank)} ` : "— "}<b>${esc(r.candidate_id)}</b>
      ${r.unscored ? "심사 점수 없음 — 순위 없음" : `점수 ${esc(r.weighted_score ?? "-")} · 분산 ${esc(r.variance ?? "-")} · 심사관 ${esc(r.reviewers)}`}
      ${r.low_confidence && !r.unscored ? " <span class='tag'>저신뢰</span>" : ""}
      ${r.eligible ? "" : " <span class='tag'>반려</span>"}</div>`).join("");
  // "최종 처방"이 아니라 **권고 후보**다 — 실행 여부는 근거 게이트와 연구자 승인이 정한다.
  el.innerHTML = `<h3>합의 · 권고 후보 처방 (${esc(p.model)})</h3>
    <div class="win">권고 후보: ${esc(p.winner || ((p.ranked || []).some((r) => r.unscored) ? "없음 — 심사 점수가 없어 순위를 매기지 않았습니다" : "없음"))}</div>${rows}
    <div class="tag" style="margin-top:6px">심사관 점수는 순위 결정 전용 — 반려 권한 없음</div>
    <div class="tag">권고 후보는 1위라도 자동으로 개발되지 않습니다 — 카드의 “이 후보로 개발 착수”로 선택합니다</div>
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
const degraded = new Set();   // 이번 실행에서 LLM 없이 규칙 기반으로 처리된 노드(요청 해석·반성)
// LLM이 응답하지 않아 비어 있는 결과 — 처방이나 점수를 대신 채우지 않고 개수만 알린다
const unavailable = { designs: 0, judges: 0 };

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
    "confirmation", "approval", "wetlab", "phase.gate", "data.request"];
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

let lastStatus = null;         // 마지막 설계의 종결 상태 — flow.js가 카드 순서를 정할 때 쓴다(제약 불가능이면 결론부터)
function finishRun(summary) {
  if (!running) return;
  lastStatus = summary ? summary.status : "error";
  setRunning(false);
  if (summary && summary.status === "error") {
    notice("실행이 오류로 끝났습니다. 트레이스를 확인해 주세요.", "error", true);
  } else if (summary && summary.status === "no_design") {
    notice("LLM이 응답하지 않아 후보 처방을 설계하지 못했습니다. 처방을 대신 채우지 않았습니다 — 잠시 후 다시 실행해 주세요.", "warn", true);
  } else if (unavailable.designs || unavailable.judges) {
    // 비어 있는 결과를 조용히 넘기지 않는다 — 무엇이 LLM 응답 없이 비었는지 분명히 알린다.
    const parts = [];
    if (unavailable.designs) parts.push(`설계 ${unavailable.designs}건`);
    if (unavailable.judges) parts.push(`심사 ${unavailable.judges}건`);
    notice(`무료 티어 한도로 LLM이 응답하지 않아 ${parts.join(" · ")}이 비어 있습니다. `
      + "점수나 처방을 대신 채우지 않았고, 순위는 실제로 매겨진 점수만으로 정했습니다.", "warn");
  } else if (degraded.size) {
    notice(`요청 해석·재설계 지시 ${degraded.size}건은 LLM 없이 규칙 기반으로 처리했습니다.`, "info");
  } else {
    clearNotice();
  }
  if (summary && summary.status === "qtpp_review") {
    notice("남은 전략이 없습니다 — 목표(QTPP) 재검토가 필요합니다. 용량·대상·제형이나 고정한 제약을 조정하세요.", "warn", true);
  }
  if (summary) renderDataRequests(summary.pending_requests || [], summary.plan_signature || "", summary.request_groups || []);
  announceRun();
  continueScenario();
}

// 입력 에이전트에게 "설계 상태가 바뀌었다"를 알린다 — 에이전트는 서버에서 맥락을 다시 읽는다.
// 측정값이 바뀌면 근거 판정도 바뀔 수 있어 근거 결손 게이트를 다시 읽는다.
function announceRun() {
  if (!running) loadEvidence();
  document.dispatchEvent(new CustomEvent("f1:run", { detail: { runId } }));
}

// 입력 에이전트가 제안한 설계 실행 — 폼을 실제로 채워 보여 준 뒤 같은 startRun() 경로로 보낸다.
function startRunWith(p) {
  if (running) return false;
  $("request").value = p.request || "";
  $("smiles").value = p.smiles || "";
  $("pinned").value = (p.required_excipients || []).join(", ");
  // 대화의 '실험 데이터 입력' 카드에 연구자가 넣은 값은 지우지 않는다 — 제안에 있는 키만 채운다
  $("inputs-body").querySelectorAll("input").forEach((el) => {
    const v = (p.measured_params || {})[el.dataset.key];
    if (v === undefined) return;
    if (el.dataset.type === "bool") el.checked = v === true;
    else el.value = String(v);
  });
  if (typeof updateInputCount === "function") updateInputCount();
  activeScenario = null;
  startRun();
  return true;
}
window.F1Discovery = { startRunWith, submitMeasurements: (m, g, src) => submitMeasurements(m, g || "user_statement", src || "agent"),
  develop: (cid) => startDevelopment(cid, null),
  runId: () => runId, running: () => running, pending: () => pendingRequests.length, status: () => lastStatus };

function resetView() {
  candidates.clear(); tokenBuffers.clear(); degraded.clear();
  unavailable.designs = 0; unavailable.judges = 0;
  winnerId = null; pendingRequests = []; rankOf.clear(); evidence = {};
  resetNarration();
  $("trace").innerHTML = ""; $("cands").innerHTML = "";
  $("consensus").hidden = true;
  $("drq").hidden = true;
  $("drq-body").innerHTML = "";
  $("cand-count").textContent = "";
  $("pred-panel").hidden = true;
  $("lit-panel").hidden = true;
  resetGraph();
}

async function startRun() {
  if (running) return;
  const request = $("request").value.trim();
  if (!request) {
    notice("설계 요구를 입력해 주세요 — 대화창에 말로 요청하거나 직접 입력 폼을 채우세요.", "warn");
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
        llm: llmChoice,
      }),
    });
    if (!res.ok) {
      // 429는 허브/파드의 동시 실행 제한, 400은 입력 오류(예: 못 읽는 SMILES).
      // 서버가 사유를 적어 보냈으면 그걸 그대로 보여준다 — 사용자가 고칠 수 있는 건
      // 상태 코드가 아니라 사유다.
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail
        || (res.status === 429
          ? "지금 실행이 몰려 있습니다. 잠시 후 다시 시도해 주세요."
          : `서버가 요청을 거부했습니다 (${res.status})`));
    }
    const data = await res.json();
    if (!data.run_id) throw new Error("서버 응답에 run_id가 없습니다");
    // 카탈로그에 없는 키는 서버가 버린다. 조용히 넘기면 "왜 안 먹었는지"를 알 수 없다.
    if ((data.rejected_inputs || []).length) {
      notice(`입력 중 ${data.rejected_inputs.length}건이 허용 목록에 없어 제외됐습니다: `
        + data.rejected_inputs.join(", "), "warn");
    }
    runId = data.run_id;
    document.dispatchEvent(new CustomEvent("f1:runstart", { detail: { runId, request, scenario: activeScenario && activeScenario.title } }));
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

/* ── 모델 선택 ─────────────────────────────────────────────────────
   기본은 무료 Groq. 대회 API는 비밀번호로 접속한 세션(access_role=full)에서만 고를 수 있다 —
   서버도 같은 규칙으로 다시 막으므로(403) 화면의 잠금은 안내일 뿐 권한 경계가 아니다.
   선택은 설계 실행·입력 에이전트·개발 스튜디오 호출에 함께 실린다. */
let llmChoice = "groq";
let llmMeta = { options: [], role: "guest", fallbackLabel: "" };

function llmUsable(o) { return o && o.available && o.allowed; }

function setLlm(id, { save = true } = {}) {
  const opt = llmMeta.options.find((o) => o.id === id);
  if (!llmUsable(opt)) return false;
  llmChoice = id;
  if (save) { try { localStorage.setItem("f1:llm", id); } catch (e) { /* 무시 */ } }
  $("pill-llm").textContent = `LLM ${opt.label}`;
  $("pill-llm").className = "pill ok";
  document.dispatchEvent(new CustomEvent("f1:llm", { detail: { id, options: llmMeta.options, role: llmMeta.role } }));
  return true;
}

function initLlm(meta) {
  llmMeta = { options: meta.llm_options || [], role: meta.access_role || "guest" };
  let saved = null;
  try { saved = localStorage.getItem("f1:llm"); } catch (e) { /* 무시 */ }
  const ok = setLlm(saved, { save: false }) || setLlm(meta.llm_default || "groq", { save: false })
    || llmMeta.options.some((o) => llmUsable(o) && setLlm(o.id, { save: false }));
  if (!ok) {
    $("pill-llm").textContent = "LLM 미연결 — 규칙 기반 대체";
    $("pill-llm").className = "pill warn";
    document.dispatchEvent(new CustomEvent("f1:llm", { detail: { id: null, options: llmMeta.options, role: llmMeta.role } }));
  }
}
window.F1LLM = { get: () => llmChoice, set: (id) => setLlm(id), meta: () => llmMeta };

/* ── v3 데이터 요청 (lab-in-the-loop, 비차단) ────────────────────────
   근거 충족 게이트·장기 실행 작업함·배치 결과 루프(WL_EXAMPLE 등)는 v3 출력 경계
   밖이라 뺐다 — index.html·web/server.py의 대응 주석과 세트다. 되돌릴 때는 git으로
   이 커밋 이전 버전을 참고할 것(주석으로 원문을 그대로 남기기엔 이 블록이 너무 크다).

   Tier가 낮은(적은 시료로 되는) 요청부터 보여주고, 값을 넣으면 그래프를 다시 돌리지
   않고 /api/runs/{id}/measurements가 그 자리에서 재계산한다. */
// 필드 타입별 입력 칸 — 참/거짓은 체크박스 대신 3상태(미입력·예·아니오): 안 체크가 "아니오"인지 "아직 안 넣음"인지 구분된다
function fieldInput(f) {
  const attrs = `data-key="${esc(f.key)}" data-type="${esc(f.type)}"`;
  if (f.type === "bool") return `<select ${attrs}><option value="">미입력</option>
      <option value="true">예</option><option value="false">아니오</option></select>`;
  if (f.type === "enum") return `<select ${attrs}><option value="">미입력</option>
      ${(f.enum || []).map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("")}</select>`;
  if (f.type === "json") return `<textarea ${attrs} rows="2" placeholder="${esc(f.help || "JSON")}"></textarea>`;
  if (f.type === "text") return `<input type="text" ${attrs} placeholder="${esc(f.help || "값")}">`;
  return `<input type="number" step="any" ${attrs} placeholder="값">`;
}

const attachmentsByMid = {};   // measurement_id → [attachment_id] (이번 제출에 실을 원본)
let draftSource = "form";      // 첨부 해석 창으로 채운 값이면 "vision_draft"

async function uploadAttachment(mid, file) {
  if (file.size > 20 * 1024 * 1024) { notice("20 MB를 넘는 파일은 올릴 수 없습니다.", "warn"); return null; }
  const fd = new FormData();
  fd.append("measurement_id", mid);
  fd.append("file", file);
  try {
    const res = await fetch(api(`/api/runs/${runId}/attachments`), { method: "POST", body: fd });
    const out = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof out.detail === "string" ? out.detail : `첨부 실패 (${res.status})`);
    return out;
  } catch (err) { notice(err.message, "error"); return null; }
}

function attachmentUrl(a) { return api(`/api/runs/${runId}/attachments/${a.attachment_id}`); }

function renderAttachList(root, mid, a) {
  const ul = root.querySelector(`.drq-files[data-mid="${mid}"]`);
  if (!ul || ul.querySelector(`[data-att="${a.attachment_id}"]`)) return;
  const li = document.createElement("li");
  li.dataset.att = a.attachment_id;
  const isImg = /\.(png|jpe?g)$/i.test(a.ext);
  li.innerHTML = `${isImg ? `<img src="${esc(attachmentUrl(a))}" alt="${esc(a.filename)}">` : ""}
    <a href="${esc(attachmentUrl(a))}" target="_blank" rel="noopener">${esc(a.filename)}</a>
    <small>${Math.ceil(a.size / 1024)} KB · sha256 ${esc(a.sha256.slice(0, 10))}…</small>
    <button type="button" class="ghost drq-interpret" data-att="${esc(a.attachment_id)}" data-mid="${esc(mid)}">에이전트 해석</button>`;
  ul.appendChild(li);
  li.querySelector(".drq-interpret").onclick = () => openInterpretation(mid, a);
}

// 첨부 해석 창 — 왼쪽 원본, 오른쪽 필드별 제안값(수정 가능)·근거·"미확인". 확정하면 카드 입력 칸만 채운다(자동 제출 없음)
async function openInterpretation(mid, a) {
  let out;
  try {
    const res = await fetch(api(`/api/runs/${runId}/attachments/${a.attachment_id}/interpret`), {
      method: "POST", headers: { "X-F1-LLM": (window.F1LLM && window.F1LLM.get()) || "groq" } });
    out = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof out.detail === "string" ? out.detail : `해석 실패 (${res.status})`);
  } catch (err) { notice(err.message, "warn", true); return; }
  const wrap = document.createElement("div");
  wrap.className = "interp-overlay";
  const specs = out.field_specs || [];   // 그 측정의 필드 전부 — 초안이 없는 칸은 비워 두고 이유(not_derived)를 단다
  const isImg = /\.(png|jpe?g)$/i.test(a.ext);
  wrap.innerHTML = `<div class="interp-card" role="dialog" aria-label="첨부 해석">
    <header><b>첨부 해석 초안</b> <span class="drq-kind">${out.method === "vision_draft" ? `이미지 · ${esc(out.model || "")}` : "기기 원자료 · 코드 계산"}</span>
      <span class="interp-status">미확인</span><button type="button" class="interp-close" aria-label="닫기">✕</button></header>
    <div class="interp-body">
      <div class="interp-src">${isImg ? `<img src="${esc(attachmentUrl(a))}" alt="${esc(a.filename)}">`
        : `<a href="${esc(attachmentUrl(a))}" target="_blank" rel="noopener">${esc(a.filename)}</a>
           <pre>${esc(JSON.stringify(out.evidence || {}, null, 1)).slice(0, 1200)}</pre>`}</div>
      <div class="interp-fields">${specs.map((f) => {
        const v = (out.fields || {})[f.key];
        const why = (out.rationale || {})[f.key] || (out.not_derived || {})[f.key] || "";
        return `<label class="drq-num">${esc(f.label)}${f.unit ? ` <small>${esc(f.unit)}</small>` : ""} ${fieldInput(f)}
          ${why ? `<small class="interp-why">${esc(why)}</small>` : ""}</label>`;
      }).join("")}
        ${out.notes ? `<p class="interp-why">${esc(out.notes)}</p>` : ""}
        ${out.evidence && out.evidence.assumption ? `<p class="interp-why">가정: ${esc(out.evidence.assumption)}</p>` : ""}
      </div>
    </div>
    <footer><button type="button" class="interp-apply primary">확정해서 입력 칸에 넣기</button>
      <small>입력 칸만 채웁니다 — 제출은 카드의 [값 제출]로 연구자가 합니다.</small></footer></div>`;
  document.body.appendChild(wrap);
  // 제안값 채우기
  for (const [k, v] of Object.entries(out.fields || {})) {
    const el = wrap.querySelector(`[data-key="${CSS.escape(k)}"]`);
    if (el) el.value = typeof v === "object" ? JSON.stringify(v) : String(v);
  }
  const close = () => wrap.remove();
  wrap.querySelector(".interp-close").onclick = close;
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  wrap.querySelector(".interp-apply").onclick = () => {
    const card = document.querySelector(`#drq-body .drq-req[data-mid="${CSS.escape(mid)}"]`);
    let filled = 0;
    wrap.querySelectorAll(".interp-fields [data-key]").forEach((src) => {
      if (src.value === "") return;
      const dst = (card || document).querySelector(`[data-key="${CSS.escape(src.dataset.key)}"]`);
      if (dst) { dst.value = src.value; filled += 1; }
    });
    draftSource = out.method === "vision_draft" ? "vision_draft" : "instrument_draft";
    notice(`첨부 해석 초안 ${filled}개 값을 입력 칸에 넣었습니다 — 확인 후 [값 제출]을 누르세요.`, "info");
    close();
  };
}

function renderDataRequests(requests, planSignature, groups) {
  pendingRequests = requests || [];
  const panel = $("drq");
  const body = $("drq-body");
  // 같은 시험을 가리키는 요청은 서버가 하나로 합치고(시료 적은 순 정렬) groups로 보낸다
  const list = groups || [];
  if (!pendingRequests.length || !list.length) {
    // 대화에 이미 놓인 카드는 사라지지 않게 — 요청이 모두 풀렸거나 건너뛰었다는 결과를 그 자리에 남긴다
    if (panel.closest("#agent-log") && body.innerHTML) {
      body.innerHTML = `<div class="drq-done">남은 데이터 요청이 없습니다 — 제출한 값으로 풀렸거나, 건너뛴 요청은 예측값으로 계속합니다(해당 후보는 provisional).</div><div id="drq-out"></div>`;
      return;
    }
    panel.hidden = true;
    body.innerHTML = "";
    return;
  }
  panel.hidden = false;
  const kindTag = (k) => k === "disagreement" ? "예측 간 불일치" : k === "low_or_unknown" ? "예측이 낮거나 모름" : k === "ph_dependent" ? "pH 의존(이온화)" : "";
  // 입력 칸의 타입은 서버가 필드 정의 파일(measurement_output_fields.csv)에서 실어 보낸다 — 이름으로 추측하지 않는다
  const fieldsOf = (g) => (g.fields && g.fields.length) ? g.fields
    : g.result_keys.map((k) => ({ key: k, type: "number", label: k, unit: "", enum: [], help: "" }));
  body.innerHTML = list.map((g) => `<div class="drq-req" data-mid="${esc(g.measurement_id)}">
      <b><span class="tier">Tier ${esc(g.tier)} · ~${esc(g.sample_mg)} mg</span>${esc(g.name)}</b>
      ${g.reasons.map((r) => `<div class="why">${kindTag(r.kind) ? `<span class="drq-kind">${esc(kindTag(r.kind))}</span> ` : ""}${esc(r.text)} <code>${esc(r.trigger_id)}</code></div>`).join("")}
      ${fieldsOf(g).length ? `<div class="measures">${fieldsOf(g).map((f) => `<label class="drq-num">${esc(f.label)}${f.unit ? ` <small>${esc(f.unit)}</small>` : ""}
        ${fieldInput(f)}</label>`).join("")}</div>` : ""}
      <div class="drq-attach">
        <label class="drq-file">원본 첨부(선택) <input type="file" accept=".png,.jpg,.jpeg,.pdf,.csv,.txt,.xy,.xlsx" data-mid="${esc(g.measurement_id)}"></label>
        <ul class="drq-files" data-mid="${esc(g.measurement_id)}"></ul>
      </div>
      <div class="drq-row-actions"><button type="button" class="ghost drq-decline" data-triggers="${esc(g.triggers.join(","))}">이 시험 건너뛰기</button>
        ${g.fallbacks.length ? `<span class="drq-fallback">건너뛰면: ${esc(g.fallbacks[0])}</span>` : ""}</div>
    </div>`).join("") + `
    <div class="drq-actions">
      <label class="drq-grade">근거 등급 <select id="drq-grade">
        <option value="self_measured">자체 실측</option><option value="literature">문헌</option>
        <option value="user_statement">사용자 진술</option></select></label>
      <button id="drq-submit" type="button">값 제출 → 재계산</button>
      <button id="drq-skip" class="ghost" type="button">전부 건너뛰기(예측값으로 계속)</button>
    </div>
    <div id="drq-out"></div>`;

  const decline = async (triggerIds) => {
    try {
      const res = await fetch(api(`/api/runs/${runId}/decline`), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger_ids: triggerIds }),
      });
      if (!res.ok) throw new Error(`건너뛰기 실패 (${res.status})`);
      const out = await res.json();
      renderDataRequests(out.pending_requests || [], out.plan_signature || "", out.request_groups || []);
      announceRun();
      notice("건너뛴 요청은 예측값으로 계속합니다 — 해당 후보는 provisional 태그를 유지합니다.", "info");
    } catch (err) { notice(err.message, "error"); }
  };
  body.querySelectorAll(".drq-decline").forEach((b) => {
    b.onclick = () => decline(b.dataset.triggers.split(",").filter(Boolean));
  });

  // 원본 첨부 — 고르는 즉시 올리고 attachment_id를 카드에 보관한다(판정에는 쓰지 않는 증거)
  body.querySelectorAll('.drq-attach input[type="file"]').forEach((inp) => {
    inp.onchange = async () => {
      const file = inp.files && inp.files[0];
      if (!file) return;
      const out = await uploadAttachment(inp.dataset.mid, file);
      inp.value = "";
      if (!out) return;
      attachmentsByMid[inp.dataset.mid] = [...new Set([...(attachmentsByMid[inp.dataset.mid] || []), out.attachment_id])];
      renderAttachList(body, inp.dataset.mid, out);
    };
  });

  $("drq-submit").onclick = async () => {
    const measurements = {};
    for (const el of body.querySelectorAll("[data-key]")) {
      const v = el.value.trim();
      if (v === "") continue;
      const t = el.dataset.type;
      if (t === "number") measurements[el.dataset.key] = Number(v);
      else if (t === "bool") measurements[el.dataset.key] = v === "true";
      else if (t === "json") {
        try { measurements[el.dataset.key] = JSON.parse(v); }
        catch (e) { notice(`${el.dataset.key}: JSON 형식이 아닙니다.`, "warn"); return; }
      } else measurements[el.dataset.key] = v;
    }
    if (!Object.keys(measurements).length) {
      notice("최소 한 항목에 값을 입력해 주세요.", "warn");
      return;
    }
    await submitMeasurements(measurements, $("drq-grade") ? $("drq-grade").value : "self_measured", "form",
      { ...attachmentsByMid }, draftSource);
  };
  $("drq-skip").onclick = () => decline(list.flatMap((g) => g.triggers));
}

// 측정값 제출 — 데이터 요청 패널과 입력 에이전트가 같은 경로를 쓴다
const GRADE_KO = { self_measured: "자체 실측", literature: "문헌", user_statement: "사용자 진술" };

// 판정 객체(예: {bcs_solubility_provisional: "low", bcs_source: "predicted"})를 사람이 읽는 문자열로
function fmtAssigned(a) {
  if (a === null || a === undefined || a === "") return "";
  if (typeof a !== "object") return String(a);
  return Object.entries(a).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("|") : v}`).join(" · ");
}

async function submitMeasurements(measurements, grade = "self_measured", source = "form", attachments = {}, draft = "form") {
  const btn = $("drq-submit");
  if (btn) { btn.disabled = true; btn.textContent = "재계산 중…"; }
  try {
    const res = await fetch(api(`/api/runs/${runId}/measurements`), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ measurements, grade, source: draft !== "form" ? draft : source, attachments }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `재계산 요청이 실패했습니다 (${res.status})`);
    }
    const out = await res.json();
    // 실행 뒤 재계산(phase_gates → plan → gate)도 트레이스·그래프에 같은 처리기로 남긴다(SSE는 run.end에서 닫혔다)
    (out.trace || []).forEach((ev) => { try { handle(ev.kind, ev); } catch (e) { /* 보조 */ } });
    const beforeCount = pendingRequests.length;
    const afterCount = (out.pending_requests || []).length;
    const bt = (out.backtrack || []).map((d) => `${d.transition_id}(${Object.entries(d.patch || {}).map(([k, v]) => `${k}=${v.join(",")}`).join(" ")})`);
    const resultMsg = out.qtpp_review
      ? "측정 결과로 남은 전략이 없어졌습니다 — 목표(QTPP) 재검토가 필요합니다."
      : out.regenerated
        ? "전략 집합이 바뀌어 새 후보를 다시 생성했습니다(LLM 호출)."
        : "전략 집합은 그대로라 신뢰도만 다시 계산했습니다(LLM 호출 없음).";
    narrate("drq-reassess", {
      layer: "데이터 요청 재계산", kind: "det", once: false,
      title: out.regenerated ? "전략이 바뀌어 후보를 다시 생성했다" : "같은 후보, 신뢰도만 다시 매겼다",
      body: `제출: <b>${esc(Object.entries(measurements).map(([k, v]) => `${k}=${v}`).join(", "))}</b>
        <span class="drq-kind">근거 등급 · ${esc(GRADE_KO[grade] || grade)}</span><br>
        남은 요청이 ${beforeCount}건에서 ${afterCount}건으로 바뀌었습니다${(out.submission || {}).closed_requests && out.submission.closed_requests.length
          ? ` — 닫힌 요청 <code>${esc(out.submission.closed_requests.join(", "))}</code>` : ""}.
        ${(out.phase_signals || []).length ? `<br>다시 판정한 게이트: ${out.phase_signals.slice(0, 6).map((g) => `<code>${esc(g.rule_id)}</code> ${esc(fmtAssigned(g.assigned))}`).join(" · ")}` : ""}
        <br><small>${esc((out.submission || {}).rerun_scope || "")}</small>
        ${bt.length ? `<br>측정 결과가 전제를 부정해 되돌림: <code>${esc(bt.join(" · "))}</code>` : ""}
        <span class="nr-why">왜 중요한가: 그래프를 처음부터 다시 돌리지 않았습니다 —
        결정론 계층만 재계산했으므로 몇 초 안에 끝납니다.</span>`,
    });
    Object.keys(attachmentsByMid).forEach((k) => delete attachmentsByMid[k]);
    draftSource = "form";
    const atts = Object.values((out.submission || {}).attachments || {}).flat();
    if (atts.length) {
      narrate("drq-attach", { layer: "증거 보관", kind: "det", once: false, title: "제출 기록에 원본을 붙였다",
        body: atts.map((a) => `<a href="${esc(attachmentUrl(a))}" target="_blank" rel="noopener">${esc(a.filename)}</a> <small>sha256 ${esc(a.sha256.slice(0, 12))}…</small>`).join("<br>")
          + `<span class="nr-why">왜 중요한가: 판정은 구조화된 값으로만 하되, 그 값의 원본을 나중에 다시 열어 확인할 수 있어야 합니다.</span>` });
    }
    const summary = out.summary || {};
    renderDataRequests(out.pending_requests || [], out.plan_signature || "", summary.request_groups || []);
    if (!$("drq-out")) {
      // 제출값이 남은 요청을 모두 풀었으면 패널을 닫지 않고 결과를 그 자리에 남긴다
      $("drq").hidden = false;
      $("drq-body").innerHTML = `<div class="drq-done">남은 데이터 요청이 없습니다 — 제출한 값으로 모두 해결됐습니다.</div><div id="drq-out"></div>`;
    }
    $("drq-out").innerHTML = `<div class="drq-refine">${resultMsg}
      근거 등급 ${esc(GRADE_KO[grade] || grade)} · plan_signature = <code>${esc(out.plan_signature)}</code></div>`;
    if (out.regenerated && Array.isArray(out.results)) {
      // 전략이 바뀌어 후보를 다시 만들었다 — 옛 카드를 새 후보로 바꾼다(옛 후보는 서버에 더 이상 없어 개발 착수가 안 된다)
      candidates.clear();
      rankOf.clear();
      evidence = {};
      for (const r of out.results) {
        candidates.set(r.candidate_id, { recipe: r.recipe, verdicts: r.verdicts || [], judges: [],
          gate: { passed: r.passed, total: (r.verdicts || []).length, failures: (r.verdicts || []).filter((v) => v.status === "hard_fail").length } });
      }
      (summary.ranked || []).forEach((x) => { if (x.rank) rankOf.set(x.candidate_id, x.rank); });
      $("consensus").hidden = true;
      renderCandidates();
    } else {
      // 같은 후보를 새 실측값으로 다시 판정했다 — 통과/반려와 순위를 고친다
      for (const r of out.results || []) {
        const entry = candidates.get(r.candidate_id);
        if (!entry) continue;
        entry.verdicts = r.verdicts || entry.verdicts;
        entry.gate = { ...(entry.gate || {}), passed: r.passed, total: (r.verdicts || []).length,
          failures: (r.verdicts || []).filter((v) => v.status === "hard_fail").length };
        entry.recipe.confidence = r.recipe.confidence;
        entry.recipe.pending_refinements = r.recipe.pending_refinements;
      }
      rankOf.clear();
      (summary.ranked || []).forEach((x) => { if (x.rank) rankOf.set(x.candidate_id, x.rank); });
      renderCandidates();
    }
    const sent = draft !== "form" ? draft : source;
    if (sent === "evidence" || sent === "agent_evidence") {
      // 근거 결손 게이트 입력(카드 폼 · 말로 입력) — 재계산 뒤 근거를 다시 읽고 무엇이 바뀌었는지 남긴다
      await loadEvidence();
      const rows = Object.entries(evidence).map(([cid, ev]) => `${esc(cid)} · ${esc(ev.summary || "")}`);
      narrate(`ev-recalc-${Date.now()}`, { layer: "근거 결손 게이트", kind: "det", once: false,
        title: "측정값으로 phase_gates부터 다시 계산하고 근거를 다시 판정했다",
        body: `${sent === "agent_evidence" ? "입력 에이전트(말로 입력) → 코드 환산 → " : ""}<code>${esc(Object.entries(measurements).map(([k, v]) => `${k}=${v}`).join(", "))}</code>
          <br>${rows.join("<br>") || "새 판정에서 통과한 후보가 없습니다."}
          <span class="nr-why">왜 중요한가: 근거는 “있다/없다”를 고르는 칸이 아니라 실측값입니다 — 값이 들어가면 페이즈 게이트·계획·규칙 게이트가
          같은 규칙으로 다시 판정하고, 그 결과로 근거 충족 여부가 정해집니다.</span>` });
    }
    announceRun();
    return out;
  } catch (err) {
    notice(err.message, "error", true);
    return null;
  } finally {
    const b = $("drq-submit");
    if (b) { b.disabled = false; b.textContent = "값 제출 → 재계산"; }
  }
}

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

// 이 약의 실제 구조 플래그로 쓰는 문장 — 약마다 다른 설명을 고정 문구로 두지 않는다
function aminesNote(flags) {
  const amines = flags.filter((f) => /amine/.test(f) && !/nitrosatable/.test(f));
  return amines.length
    ? `<br>아민 계열 <b>${esc(amines.join(", "))}</b> 검출 — 유당(환원당)과의 Maillard 금기를 룰북이 검사합니다.`
    : `<br>1·2차 아민이 검출되지 않아 유당 Maillard 금기(INC001·INC002)는 이 약에 해당하지 않습니다.`;
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
          ${aminesNote(on)}
          ${p.is_salt ? `<br>염 형태 입력 — 물성은 parent(<code>${esc(p.parent_smiles || "")}</code>)로 계산했습니다.` : ""}
          <span class="nr-why">왜 중요한가: 유당이 위험한지는 “아민기가 있는가”에 달려 있고, 그건 이름이
          아니라 구조로 판단해야 합니다. 그래서 판정의 입력을 사람이 아니라 계산이 만듭니다.</span>`,
      });
      break;
    }
    case "phase.gate":
      // G3A/G3B/G4/G4B 신호마다 뜨지만, 카드는 이 계층에서 딱 한 번만 말한다 — 개별 신호는
      // 트레이스 줄(phase_gates)에서 전부 볼 수 있다.
      narrate("phasegate", {
        layer: "P1 · BCS/DCS·고체상 게이트 결정론", kind: "det",
        title: "게이트가 남긴 첫 판정",
        body: `<code>${esc(p.gate)}/${esc(p.rule_id)}</code> → <b>${esc(fmtAssigned(p.assigned) || p.action)}</b>
          ${esc(p.rationale || "")}
          <span class="nr-why">왜 중요한가: 이 판정은 처방을 반려하지 않습니다. 다음 단계에서
          어떤 전략(예: 미분화·ASD)이 후보로 올라올지를 좁힐 뿐입니다 — 트레이스에서
          phase_gates 줄을 보면 이번 실행에서 어떤 신호가 몇 건 발동했는지 전부 보입니다.</span>`,
      });
      break;
    case "node.exit":
      if (ev.node === "phase_gates" && p.derived) {
        narrate("route", {
          layer: "P1 · 페이즈 게이트 결정론", kind: "det",
          title: "처방을 짜기 전에 이 약이 어떤 부류인지부터 정한다",
          body: `BCS 잠정 용해도 <b>${esc(p.derived.bcs_solubility_provisional ?? "미정")}</b> ·
            DCS <b>${esc(p.derived.dcs_subclass ?? "미정")}</b> · 고체상 <b>${esc(p.derived.solid_form_zone ?? "미정")}</b>
            ${p.derived.routes_provisional ? " · 유동성 자료가 없어 세 공정 경로를 모두 잠정 후보로 엶" : ""}
            <span class="nr-why">왜 중요한가: 계산값(RDKit) → 예측값(ESOL·GSE) → 실측값 중 있는 것까지만 씁니다.
            모르는 값은 기본값으로 채우지 않고 비워 두며, 판정이 안 갈리면 좁히지 않고 넓힙니다.</span>`,
        });
      } else if (ev.node === "plan") {
        narrate("plan", {
          layer: "P2 · 계획 결정론", kind: "det",
          title: p.strategies && p.strategies.length ? "전략을 채점해 상위 3개만 설계한다" : "남은 전략이 없다",
          body: `${(p.scores || []).map((x) => `<code>${esc(x.strategy)}</code> ${esc(x.score)}`).join(" · ") || "후보 전략 없음"}
            ${Object.keys(p.constraints || {}).length ? `<br>되돌림 제약: ${Object.entries(p.constraints).map(([k, v]) => `${esc(k)}=${esc(v.join(","))}`).join(" · ")}` : ""}
            <span class="nr-why">왜 중요한가: 어떤 전략을 쓸지는 AI가 아니라 전략 가족 표가 정합니다 —
            같은 입력이면 같은 계획(서명 <code>${esc(p.plan_signature || "-")}</code>)이고, 그 자체가 감사 기록입니다.</span>`,
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


    case "judge.verdict":
      narrate("judge", {
        layer: "P6 · 심사 LLM", kind: "jud",
        title: "심사관은 순위만 매긴다 (반려 권한 없음)",
        body: `${esc(p.persona)} → ${p.score === null || p.score === undefined ? "<b>점수 없음</b> (LLM 응답 없음 — 대신 채우지 않음)" : `점수 <b>${esc(p.score)}</b>`}
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
          <span class="nr-why">왜 중요한가: 결정론 하드페일과 심사 가중점수를 합쳐 순위를
          정합니다. 어떤 후보를 실제로 개발할지는 1위가 자동으로 정하지 않습니다 —
          연구자가 후보 카드의 <b>이 후보로 개발 착수</b>를 눌러 ② 개발 스튜디오로 넘깁니다.</span>`,
      });
      break;

    case "backtrack":
      narrate(`backtrack-${ev.seq}`, {
        layer: "P3′ · 되돌림 결정론", kind: "warn", once: false,
        title: p.return_phase === "GATE" ? "반려 사유가 첨가제 — 같은 전략으로 성분만 바꾼다" : `반려 사유에 따라 ${esc(p.return_phase)}부터 다시 한다`,
        body: `<code>${esc(p.transition_id)}</code> → <b>${esc(p.return_phase)}</b> · ${esc(p.directive_hint || "")}
          ${p.escalated_from ? `<br>${esc(p.escalated_from)}에서 3번 풀리지 않아 한 단계 위로 올렸습니다.` : ""}
          <span class="nr-why">왜 중요한가: 반려되면 무조건 처음부터가 아닙니다. 어디로 돌아갈지는 되돌림 표의
          한 줄이 정합니다(첨가제 → 성분 교체, 공정 규칙 → 공정 경로부터, 가용화 누락 → 전략 선택부터).</span>`,
      });
      break;

    case "warning":
      if (ev.node === "qtpp_review") {
        narrate("qtpp", {
          layer: "종단 · QTPP 재검토", kind: "fail",
          title: "남은 전략이 없다 — 목표를 다시 볼 차례",
          body: `${esc(p.reason || "")}
            <span class="nr-why">왜 중요한가: 전략이 하나도 남지 않으면 임의의 기본 전략을 지어내지 않습니다.
            용량·대상·제형이나 고정한 제약을 조정하거나, 전략을 가르는 실측을 넣어야 다시 열립니다.</span>`,
        });
      }
      if (ev.node === "infeasible") {
        narrate("infeasible", {
          layer: "종단 · 판정", kind: "fail",
          title: "“이 제약으로는 통과하는 처방이 없다”",
          body: `${esc(p.reason || "")}
            ${(p.blocking || []).slice(0, 2).map((b) =>
              `<br><code>${esc(b.rule_id)}</code> ${esc(b.reason)}${
                b.suggestion ? ` → 대안 <b>${esc(b.suggestion)}</b>` : ""}`).join("")}
            ${(p.planned_judges || []).length ? `<br>소집 예정이던 심사관: ${p.planned_judges.map((j) => esc(j.persona)).join(" · ")} — 심사 전에 종료` : ""}
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
  // 발표 자료의 시연 시나리오 ①②③ + 2단계 CBD. 요청 문장·값은 약학 담당의 시연 쿼리 카드 그대로이고,
  // 각 카드가 실제로 어떤 경로를 밟는지는 scripts/report/demo_cards.py(대회 API)와 tests/browser/scenarios.mjs가 확인한다.
  {
    id: "lornoxicam",
    title: "로르녹시캄 분산정 — 요청부터 Design Space까지",
    proves: "전체 파이프라인 · 시연 ①",
    request: "성인용 로르녹시캄 8 mg 분산정을 설계해 줘. 물에 분산시켜 복용하고, 직접타정으로 만들고 싶어. MCC, 만니톨, 크로스포비돈은 반드시 넣어 줘.",
    smiles: "CN1C(=C(C2=C(S1(=O)=O)C=C(S2)Cl)O)C(=O)NC3=CC=CC=N3",
    pinned: "Microcrystalline cellulose, Mannitol, Crospovidone",
    measuredParams: { dose_mg: 8, angle_of_repose: 42, compressibility_index: 22, hausner_ratio: 1.28 },
    duration: "약 3분",
    next: "lornoxicam",
    goal: `유동성 실측(안식각 42° · Carr 22 % · Hausner 1.28)으로 USP &lt;1174&gt; 흐름성을 판정해 <b>직접타정을 유지</b>합니다(48°면 직접타정 배제).
      후보가 나오면 연구자가 <b>이 후보로 개발 착수</b>를 눌러 2단계로 갑니다 — 저함량(8/250 mg ≈ 3.2 %)이라 혼합 시간 × 함량균일성 위험이 High로
      잡히고, 9단계에서 Almotairi 2022 Table 3(실측 15 run)을 불러오면 10단계 <b>검증 게이트</b>를 넘은 회귀식으로 13단계 <b>Overlay plot</b> — control space와 최적 처방(2.9 · 10분 · 7 %)이 나옵니다.`,
  },
  {
    id: "amlodipine",
    title: "고령자용 암로디핀 2.5 mg — 유당을 고정하면?",
    proves: "잘못된 처방 거르기 · 시연 ②",
    request: "고령자용 암로디핀 2.5 mg 정제를 설계해 줘. 원가 때문에 유당은 반드시 넣어야 해.",
    smiles: "CCOC(=O)C1=C(COCCN)NC(C)=C(C1c1ccccc1Cl)C(=O)OC.OS(=O)(=O)c1ccccc1",
    pinned: "Lactose monohydrate",
    measuredParams: { dose_mg: 2.5 },
    duration: "약 30초",
    goal: `베실산염을 벗긴 parent에서 <b>1차 아민</b>을 찾고, 유당(+ Mg stearate · 수분) 금기가 발동합니다. 반려 사유가 사용자가 고정한
      유당이라 재설계 루프를 돌지 않고 <b>“이 제약으로는 통과 처방 없음”</b>과 대체 부형제를 냅니다. 용량은 유리염기 2.5 mg으로 처리합니다.`,
  },
  {
    id: "vx770",
    title: "개발코드 VX-770 — 구조식만 있는 신규물질",
    proves: "Cold start · 시연 ③",
    request: "신규 후보물질 VX-770의 성인용 경구 정제 제형 전략을 세워 줘. 1회 150 mg이고, 구조식만 있고 실측 자료는 거의 없어.",
    smiles: "CC(C)(C)C1=CC(=C(C=C1NC(=O)C2=CNC3=CC=CC=C3C2=O)O)C(C)(C)C",
    pinned: "",
    measuredParams: { dose_mg: 150 },
    duration: "약 1분",
    autoLab: true,
    next: "vx770",
    // 시연 카드의 측정 문장(Biomedicines 2023;11(5):1281의 Tm · 용해도) — 입력칸에 넣어 두기만 하고, 보내기는 발표자가 누른다
    followUp: "DSC 측정 결과: Tm 317 도. 실험 용해도는 0.00005 mg/mL.",
    goal: `값이 거의 없어도 <b>후보부터</b> 냅니다(BCS는 ‘미확정’). Tm을 모르면 용융압출(HME)과 분무건조(SDD)를 가를 수 없어
      <b>DSC만</b> 요청합니다. 측정 문장을 보내면 그래프를 다시 돌리지 않고 재계산해 ASD · 분무건조가 계획에 들어옵니다. 출력에는 개발코드만 씁니다.`,
  },
  {
    id: "stage2",
    title: "2단계 — QTPP부터 Design Space까지(CBD 구강붕해정)",
    proves: "2단계 · 논문은 참고 자료로",
    duration: "단계마다 승인",
    stage2: true,
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
      // 2단계 시연 — 후보 탐색을 돌리지 않고 논문 프로토타입(Monton 2026 Table 1)으로 2단계를 연다
      if (scenario.stage2) {
        if (window.F1Stage2) window.F1Stage2.startCbd();
        return;
      }
      activeScenario = scenario;
      $("request").value = scenario.request;
      $("smiles").value = scenario.smiles || "";
      $("pinned").value = scenario.pinned;
      // phase_gates가 dose_mg 없이는 dose_solubility_volume 계열을 못 채워 narrows_strategy
      // 요청이 비어 버린다 — labloop 시나리오는 이 값이 있어야 데이터 요청 패널이 실제로 뜬다.
      $("inputs-body").querySelectorAll("input").forEach((el) => {
        if (el.type === "checkbox") el.checked = false; else el.value = "";
      });
      Object.entries(scenario.measuredParams || {}).forEach(([key, value]) => {
        const el = document.querySelector(`#inputs-body input[data-key="${key}"]`);
        if (el) el.value = value;
      });
      updateInputCount();
      box.querySelectorAll(".scenario").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");

      const goal = $("scenario-goal");
      goal.hidden = false;
      goal.innerHTML = `<b>${esc(scenario.title)}</b> — 이 시나리오가 보여주는 것<br>${scenario.goal}`;
      startRun();
    };
  });
}

/* 시나리오 3 마무리 — 설계가 끝나면 데이터 요청 패널로 안내한다. 값은 연구자가 넣는다. */
async function continueScenario() {
  if (activeScenario && activeScenario.next === "lornoxicam") {
    narrate("lx-next", {
      layer: "다음 단계 — 연구자 선택", kind: "det",
      title: "후보를 골라 2단계로 — 9단계에서 논문 실측 15 run을 불러온다",
      body: `후보 카드의 <b>이 후보로 개발 착수</b>를 누르면 조성·공정과 요청 맥락이 불변 Handoff로 넘어가 2단계가 열립니다(1위 자동 진입 없음).
        9단계 표 위의 <b>논문 실측값으로 채우기 — 로르녹시캄 분산정 · Almotairi 2022 Table 3</b>을 누르면(또는 CSV 불러오기) 10단계 검증 게이트를 거쳐 13단계 Overlay plot(control space · 최적 처방)이 계산됩니다.
        후보마다 <b>근거 결손 게이트</b>(예: BCS 근거 자료)가 걸려 있으면 [결손을 기록하고 개발 착수] → 미리 채워진 사유를 확인하고 [사유 기록 · 개발 착수]를 누르면 넘어갑니다.
        <span class="nr-why">왜 중요한가: 검증 게이트를 넘은 회귀식만 영역을 그리고, 운전 범위(control space)는 평균 예측이 모든 목표를 만족하는 곳 안에서 정합니다.</span>`,
    });
  }
  if (activeScenario && activeScenario.followUp && window.F1Agent) {
    const inp = document.getElementById("agent-input");
    if (inp && !inp.value) {
      inp.value = activeScenario.followUp;
      inp.dispatchEvent(new Event("input"));
      notice("시연 카드의 측정 문장을 입력칸에 넣어 두었습니다 — 보내면 측정값 제출 카드가 됩니다(값은 시연 쿼리 카드의 문헌값).", "info");
    }
  }
  if (!activeScenario || !activeScenario.autoLab) return;
  if (!pendingRequests.length) return;

  // 값은 시스템이 채우지 않는다 — 실측이 있어야 의미가 있으므로, 입력칸을 짚어 주고 연구자가 넣게 한다.
  narrate("drq-start", {
    layer: "데이터 요청 (비차단)", kind: "det",
    title: "값이 없어도 이미 후보가 나와 있다 — 이제 값을 넣어 볼 차례",
    body: `후보 처방은 이미 확정됐습니다. 가운데 <b>데이터 요청</b> 패널이 전략을 가르는 실측값만 묻습니다.
      가지고 있는 측정값을 넣고 제출하면, 그래프를 다시 돌리지 않고 그 자리에서 남은 요청과 후보 신뢰도가 다시 계산됩니다.
      <span class="nr-why">왜 중요한가: 요청은 절대 실행을 막지 않습니다 — 값을 넣기 전과
      후 모두 후보 목록은 그대로 존재합니다. 시스템은 측정값을 대신 지어내지 않습니다.</span>`,
  });
  $("drq").scrollIntoView({ behavior: "smooth", block: "nearest" });
  const firstInput = document.querySelector("#drq-body .drq-num input");
  if (firstInput) {
    firstInput.classList.add("prompted");
    firstInput.focus({ preventScroll: true });
  }
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
  // v3: 장기 실행 작업함을 뺐다 — 예전 배포에서 남은 localStorage 흔적이 있으면 지운다
  // (그대로 두면 loadWorkflow가 더 이상 없어서 죽은 참조만 남는다).
  try { localStorage.removeItem("f1:last_project"); } catch (e) { /* 무시 */ }
  try {
    const res = await fetch(api("/api/meta"));
    if (!res.ok) throw new Error(`상태 조회 실패 (${res.status})`);
    const meta = await res.json();
    const r = meta.rulebook;
    $("pill-rules").textContent =
      `룰북 ${r.total} (정량 ${r.quantitative} · 정성 ${r.qualitative} · 참조 ${r.reference})`;
    $("pill-rules").className = "pill ok";
    initLlm(meta);
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
