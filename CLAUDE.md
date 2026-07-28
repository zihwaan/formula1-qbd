# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Formula 1 is a QbD (Quality-by-Design) validation engine for pharmaceutical **formulation** design. It checks whether a drug recipe (API + excipients + process + packaging) will fail before it's ever made in a lab. The design principle: **AI proposes recipes, deterministic rules verify them** — creative generation is LLM work, but safety/regulatory checks must be a calculator (same input → same verdict, 0% error).

The README.md (Korean) is the authoritative design doc. The LLM/agent orchestration layer (LangGraph generators, dynamic judges, RAG, Gradio dashboard) is **roadmap, not built** — what exists today is the deterministic checking core and a scripted demo.

## Commands

**Python 3.10+ required** (langgraph/fastapi/sse-starlette all need ≥3.10). The venv is 3.12.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/pytest                                  # 54 tests — run this first when changing the core
.venv/bin/python scripts/demo.py                  # golden scenario: reject → reflect → pass
.venv/bin/python scripts/verify_smarts.py         # SMARTS truth-table report (exit 1 on mismatch)
.venv/bin/python scripts/feedback_demo.py         # lab-in-the-loop (결과 해석)
.venv/bin/uvicorn web.server:app --port 8000      # dashboard at http://localhost:8000
.venv/bin/python scripts/import_rulebook.py       # re-import rulebook zips from 추가자료/
```

Everything runs **without an API key** — LLM nodes fall back to deterministic stand-ins so
demos never break. Set `GROQ_API_KEY` (free tier) or `ANTHROPIC_API_KEY` to enable a real LLM path.

## Deployment — this repo is served live at zihwan.com/formula1

This clone lives inside the home-server repo at `~/zihwan/formula1` but keeps **its own git
history** (origin is `github.com/zihwaan/formula1-qbd`); the hub repo does not track it.
It runs as an OrbStack k8s deployment. Editing a file changes nothing live until you rebuild:

```bash
cd ~/zihwan/formula1 && docker build -t formula1:latest . && kubectl rollout restart deployment/formula1
kubectl rollout status deployment/formula1 --timeout=180s
curl -s -o /dev/null -w '%{http_code}\n' https://zihwan.com/formula1/
```

FastAPI serves both the API and the no-build SPA, so one image covers front and back.
Full home-server context (proxy layout, secrets, traps) is in `~/zihwan/CLAUDE.md`.

Three hosting concerns are baked into `web/server.py` — don't undo them:

- **`BASE_PATH` env** (`/formula1` in k8s, empty locally). The hub proxy strips the prefix, so
  FastAPI routes stay rooted at `/`; the `/` handler injects `<base href>` + `window.__BASE__`
  and `app.js` builds every fetch/EventSource URL through `api()`. Local `uvicorn` on :8000 with
  no `BASE_PATH` behaves exactly as before.
- **Content-hashed asset URLs** (`_asset_version`). Filenames aren't hashed (no build step) and
  Cloudflare caches `.js`/`.css` for 4h when the origin sends no `Cache-Control` — without this,
  a redeploy keeps serving the old script.
- **Public-endpoint limits.** `MAX_ACTIVE_RUNS=3` (429 past that) and `MAX_STORED_RUNS=40`
  (oldest evicted). `RUNS` is an in-process dict, so this is what keeps a 24/7 public pod bounded;
  it's also why the image runs `--workers 1` (a second worker can't see another's run).

## LLM providers — `formula/agents/client.py` wraps both

`parse_structured` / `stream_text` are the only touchpoints; agents never know the provider.
`FORMULA1_LLM_PROVIDER` = `auto` (default) | `anthropic` | `groq` | `none`. The pod pins `groq`.

The Groq path differs from Anthropic in ways that caused real failures:

- **`max_tokens` counts against the per-minute token limit (TPM).** A 2-token prompt with
  `max_tokens: 8192` returns **413** on the 8,000-TPM tier. `_groq_payload` therefore shrinks
  `max_tokens` to fit `GROQ_TPM[model]` and trims the prompt's middle if even that won't fit.
- **`_TokenBudget` meters TPM client-side — this is what keeps stand-in scores off the screen.**
  LangGraph fans generators and judges out in parallel, so without metering they hit Groq at once,
  collect 429s, and every judge falls back to a fabricated score that still renders as an opinion.
  The budget makes callers *queue* for a model with headroom (buckets are per-model, ~26k TPM
  combined) instead of failing. Measured: 4/4 judges fake before, 0 after — including two
  concurrent runs. Cost is latency: a full run is ~60s, not 11s. **Don't "speed it up" by removing
  the wait** — that trades real judgements for fake ones.
- Reserved tokens are reconciled with `usage.total_tokens` (`settle`) so over-reservation doesn't
  starve the next call. `GROQ_WAIT_BUDGET` caps how long a caller waits before giving up.
- The judge's score-extraction call must not resend the whole evaluation prompt — that doubled
  token spend was the main reason the budget ran out mid-run.
- **Structured output is `json_object` + schema in the system prompt**, not strict `json_schema`
  (which rejects the `$ref`/`anyOf` shapes Pydantic emits), with a validation-error retry hint.
- **gpt-oss reasoning tokens come out of the completion budget** → `reasoning_effort` is pinned
  `low`, otherwise reasoning eats the cap and `content` arrives empty.

Deterministic stand-ins still exist for the no-key case, but they must never masquerade as real
judgements: the UI tags them (`.judge-note.stand-in` + "규칙 기반 대체 점수 · LLM 미사용") and the
run summary says how many nodes used them. Keep both signals if you touch that path.

## Architecture — the manifest is the linchpin

The whole system is **data-driven, not code-driven**. Rules live in CSVs; a single YAML manifest wires each CSV into the right kind of check. Adding a rule = editing data (`database/*.csv` + one manifest entry), *never* editing backend code. Understanding these three moving parts is the key to being productive:

1. **`config/rulebook_manifest.yaml`** — the rule catalog. Each entry is a `RulebookEntry` that self-declares how its CSV gets checked:
   - `eval_type: quantitative` → routed to a deterministic strategy function.
   - `eval_type: qualitative` → routed to a Judge agent spec (LLM judging; agent layer not yet implemented — `active_judges()` currently just returns the specs).
   - `applies_when` → a condition expression deciding whether this rule fires for a given input (e.g. `"is_pediatric"`, `"bcs_class in ['II','IV']"`). This is how "only run the checks that matter" works.
   - `row_filter` → selects rows within a mixed CSV (e.g. `process_failure_rules.csv` has both quantitative and qualitative rows, split by two manifest entries with opposite filters).
   - `schema` → maps this CSV's column names onto the generic strategy's expected keys.

2. **`formula/checkers/strategies.py`** — exactly **eight generic strategy functions**, reused across all rulebooks via `schema` column injection. You almost never add a strategy; you add a CSV + manifest entry that reuses one. All share the signature `(entry, rows, recipe, spec, ctx) -> List[Verdict]` and return a passing verdict if nothing fires (never empty):
   - `pairwise_membership` — excipient × API functional-group incompatibility (Lactose + secondary_amine → Maillard).
   - `subset_forbidden` — a forbidden ingredient *set* being a subset of the recipe, optionally gated on `required_conditions`.
   - `threshold` — `param <op> threshold`; operators accept symbol/word forms plus `between` (`"lo;hi"`) and non-numeric `==`. Value source: `measured_param` | `ingredient_mg` | `role_percent` | `property` | `state`.
   - `range` — value outside `[min, max]` from a min/max column pair.
   - `categorical_requirement` — when `class == X`, a role/ingredient is mandatory (BCS II/IV → solubilizer required).
   - `conditional_prohibition` — a property flag forbids an option (hygroscopic → high-MVTR packaging forbidden).
   - `band_lookup` — **produces** a derived value by band/predicate lookup (angle_of_repose 48° → `flow_character="Poor"`; BCS criteria intersection → `bcs_class`). Writes into `entry.provides`.
   - `decision_tree` — evaluates `condition_expression` rows to narrow process routes → `selected_route`.

   Three cross-cutting rules live here and are easy to get wrong:
   - **`polarity`** — `fail_when` (default) means the row describes a *failure* condition; `pass_when` means it describes a condition that must *hold*. The whole of `03_process/` is `pass_when`. Reading it the other way inverts every verdict.
   - **Per-row `action`** — severity comes from each CSV row's `action` column (7-value `RuleAction`), not from the manifest entry. The manifest `severity` is only a fallback.
   - **Evidence policy** — each row's `verification_status` decides whether it may produce a HARD_FAIL. `NO_SOURCE_FOUND`/`NOT_A_RULE`/`LEGACY` rows are dropped at load; `UNVERIFIED`/`SCHEMA_ONLY` get downgraded to REVIEWER_FLAG. See `VERIFICATION_POLICY` in `contracts.py`.

3. **`formula/checkers/registry.py`** (`RulebookRegistry`) — loads the manifest and runs the firing checks **in `trigger_priority` order, as stages**. Values produced by one stage (`flow_character` → `selected_route` → `bcs_class`) are injected into the next stage's `applies_when` scope. Never iterate rulebooks in folder order — pediatric safety lives in `05_regulatory/` but runs at priority 21.
   - `run(spec, recipe, ...)` → `GateResult` (verdicts + derived state + skipped-row count). `passed` requires no HARD_FAIL **and** no ESCALATE.
   - `run_deterministic_gate(spec, recipe)` → back-compat wrapper returning just `List[Verdict]`.
   - `active_judges(spec, derived)` → `JudgeSpec`s whose `summon_condition` in `reviewer_registry.csv` is true (the dynamic "jury").

### The other layers

- **`formula/chem/smarts_probe.py`** — exposes the SMARTS layer to the UI (`GET/POST /api/chem/smarts`). Incompatibility verdicts all start from a SMARTS match, so a user must be able to check "is that pattern really in this molecule?" themselves. Salts are stripped to the parent before matching, same convention as the judging layer, and both counts are reported when they differ. Pattern presets come from `structural_flags_smarts.csv` **together with each pattern's `triggers_rule`** — that link is the point, not the match count.
- **`formula/chem/`** — RDKit input pipeline. `build_profile(api_name|smiles)` → `ApiProfile` (descriptors, SMARTS structural flags, advisory estimates, 2D SVG). Salts are stripped before SMARTS matching; `fr_*` counts cross-check every pattern. **Solubility/permeability estimates are `confidence=low` and must never set `bcs_class`** — the manifest gates `bcs_classification` behind measured values.
- **`formula/orchestrator/`** — LangGraph `StateGraph` (`graph.py`), shared state with a reset-aware `accumulate` reducer (`state.py`; return `None` to clear a fan-out list between reflection rounds), and the `TraceEvent` bus (`events.py`). Every node emits events; the web UI consumes only that stream.
- **`formula/agents/`** — Claude nodes. All use structured output (`messages.parse`) and **all have deterministic fallbacks**; `consensus.py` is pure Python driven by `severity_scoring_config.csv` (B model: judge scores rank, never block).
- **`web/`** — FastAPI + SSE + a no-build SPA. `/api/rules/{rule_id}` powers the evidence drill-down that shows the originating CSV row and its SOURCES document. `static/explainer.{js,css}` is the 8-step visual walkthrough of the README (auto-opens on first visit, reopened from the masthead, deep-linkable via `?guide=N`); its content mirrors README.md chapters, so **update it when the design story changes** — it's what a first-time visitor reads instead of the README.

### Front-end rules (learned the hard way — don't regress these)

The dashboard follows the **zihwan.com design language**: grayscale chrome + Pretendard, tokens
mirroring `~/zihwan/wealthmate/frontend/src/tokens.css`, light/dark via `data-theme` with the
theme key **`mm:theme` shared across MoneyMate/브리핑** (switching in one service applies to all).

- **Colour is reserved for rule verdicts.** `--status-good/warn/serious/critical` mark
  통과/주의/이관/반려 only. Agent kinds (결정론/LLM/심사관) are categorical, so they're separated by
  grey level **plus line style** (solid/dashed/dotted) — that keeps them colour-blind safe and is
  why the graph and the explainer use the same three border styles.
- **`[hidden]` is force-declared `display:none !important` in `styles.css`.** Both overlays set
  `display:grid`, and an author `display` beats the UA `[hidden]` rule — so the guide *and* the
  rule modal were permanently on screen and the whole dashboard was unclickable. Never drop
  that rule, and never gate an overlay on a class alone.
- **`.guide-shell` pins `grid-template-rows: minmax(0, 100%)` and its children set `min-height: 0`.**
  Without it the implicit `auto` row grows past the shell, the rail gets clipped off-screen, and
  `.guide-body`'s internal scrolling stops working.
- Korean copy sets `word-break: keep-all`; the default breaks mid-word and strands single syllables.
- **Everything rendered is untrusted** — ingredient names and rationales come from an LLM, table
  rows from CSVs, the request from the user. `app.js` has an `esc()` helper and every `${}` inside
  an `innerHTML` template must go through it. A browser test injects `<img onerror>` through five
  render paths (`addTrace`, `renderConsensus`, `renderWetlab`, `renderCandidates`, `renderChem`)
  and asserts zero executions.
- **The run button is a lock, not decoration.** `setRunning()` owns button state, the elapsed
  counter, and replay availability; without it users fire overlapping runs and burn the token
  budget. Failures from `POST /api/runs` (429 from the hub limiter, 5xx) surface in `#notice`.
- **A dropped SSE stream must not lose the run.** `stream_run` replays `bus.history` to any new
  subscriber, so `connect()` retries up to 3 times, clearing the view first and letting the replay
  rebuild it. Observed live: a QUIC-layer disconnect used to strand the user on a half-finished run.
- Verify with a real browser, not curl: `scratchpad/verify.mjs` (33 interaction checks) and
  `scratchpad/audit.mjs` (XSS injection, double-run, stand-in exposure, a11y, 9 viewport widths).

### Supporting pieces

- **`formula/contracts.py`** — all shared Pydantic models (the stable interface between the pharmacy-student data team and the backend). Key types: `FormulationSpec` (translated input: API, functional groups, BCS class, target patient, measured params, property flags), `Recipe` (candidate: ingredients with role/amount, process, packaging), `Verdict` (deterministic result: `PASS`/`HARD_FAIL`/`SOFT_FLAG`), `RulebookEntry`, `JudgeSpec`. If CSV columns change, fix the manifest `schema` — these contracts stay stable.
- **`formula/checkers/applies_when.py`** — evaluates `applies_when` / `row_filter` expressions via a **restricted `eval`** (`__builtins__` stripped, only a whitelisted context of spec fields + property flags exposed). These expressions are *trusted manifest-author input*, not user input. On expression error it fails closed (rule does not fire).
- **`formula/feedback/`** — the **lab-in-the-loop** layer: AI reads the result data, the rulebook judges it, and AI **directs the next experiment**; the human runs that experiment at the bench and feeds results back (the paradigm FutureHouse/Oxford/Fordham's *Robin* put forward). Three stages with three different owners, mirroring the design loop's split:
  1. `labloop.read_notes()` — **LLM** turns a free-text lab note into measurements. It may only transcribe numbers that appear in the text; a regex reader takes over with no key.
  2. `interpreter.WetLabInterpreter` — **deterministic**, unchanged. Compares each metric to `database/legacy/wetlab_feedback_rules.csv` and returns a `FeedbackReport` (off-target findings + cause + suggested revision). Same data → same verdict.
  3. `labloop.direct_next()` — **LLM constrained by data.** Picks the next experiments *only from the 66 real rows of* `database/reference/confirmation_test_master.csv`, so every directive carries its ICH/USP citation. Any `test_id` outside that pool is discarded before it reaches the UI — the model cannot invent a test. This closes the roadmap item "확인시험 마스터(66종)를 wet-lab 루프에 연결".
  `POST /api/runs/{id}/wetlab` runs all three and returns `{findings, read, directive}`. Form-supplied `measurements` override the LLM's reading — a human-stated number always wins.
- **`docs/architecture_image_prompt.md`** — detailed prompts for AI-generating the full horizontal system architecture diagram (not code).

## Design-intent audit (2026-07-28) — gaps found by measuring, and what changed

Claims in README/this file were checked against what the code actually does. Numbers now measured:
**30 canonical CSVs** in `database/` (27 rule tables + 3 config) wired as **29 manifest entries**,
**exactly 8** strategy functions (all used), **6** layers, **25** distinct `trigger_priority` values.
README said "우선순위 8단계", which matched nothing — corrected to "13단계 그룹" (the levels its own
§5.4 diagram lists). Three defects were real and are fixed; keep them fixed:

- **Half the jury could never be summoned.** `reviewer_registry.csv` has 6 reviewers, but
  `target_population` was hardcoded to `"pediatric" if is_pediatric else "adult"`, so REV006
  (고령자, condition `target_population=='geriatric'`) was unreachable, and nothing anywhere
  produced `regulatory_narrative_needed` (REV004) or `novel_combination_not_in_rulebook` (REV005) —
  those expressions raised NameError and failed closed. Now `population_of()` derives the real
  population, and `_summon_signals()` computes the two flags from gate output plus the excipient
  master. Verified: "고령자용 메트포르민" now summons REV006.
- **The signature reject → reflect → pass story did not reproduce on the live LLM path.** Measured
  across five scenarios: zero hard-fails, zero reflection loops. The generator prompt tells the LLM
  to avoid known incompatibilities, so the rulebook had nothing to catch — the verification layer's
  value was invisible in exactly the demo it exists for. `FormulationSpec.required_excipients`
  (UI: "반드시 포함할 부형제") now pins field constraints the designer may not route around, which is
  also a real industrial constraint. With lactose pinned, INC002 fires.
- **An unsatisfiable constraint used to burn all 5 reflection loops and end with no winner.** The
  `infeasible` terminal node now detects that a rejection names a pinned ingredient and concludes
  immediately (4s instead of ~3min) with the blocking rule and the rulebook's alternative. That is
  the answer a researcher needs — "이 제약으로는 통과가 없다" — not a silent give-up.

## Demo scenarios and the narration panel

`app.js` holds two coupled pieces that exist so a viewer can *see the architecture* rather than
read about it. Keep them in sync with the graph — they are the demo.

- **`SCENARIOS`** — three cards that **run on click** (no separate 실행 press). Each one was
  executed and kept for the path it actually takes: `guardrail` (pinned lactose → INC002 →
  `infeasible` verdict, ~5s), `team` (pediatric → REV001 summoned, others not), `labloop`
  (light design run, then auto-fills the lab note and submits, chaining into lab-in-the-loop).
  If you change a request string, **re-run it** and confirm the claimed path still fires — a
  scenario that doesn't demonstrate what its card promises is worse than no scenario.
  `labloop`'s request is deliberately cheap (`성인용 이부프로펜`): its point is the wet-lab half, and
  a request that summons 3–4 judges spends the whole free-tier budget on the design phase
  (judges × candidates × 2 calls), which pushes the directive onto the rule-based path.
- **`narrateEvent()` → `narrate()`** — turns the event stream into ordered commentary. Every card
  carries the **owning layer** (`P3 · 룰북 결정론`, `P5 · 심사 LLM`, …) and a **`왜 중요한가`** line
  explaining why that layer exists. That pairing is the point: graph lighting alone doesn't tell
  anyone why a deterministic gate sits between two LLM stages. When you add a node to the graph,
  add its narration beat too.
- **Right-size `max_tokens` per call; do not raise the wait budget.** A reservation counts against
  the per-minute limit for a full 60s, so an oversized one starves later calls. Measured on the
  pediatric scenario (2 judges): raising `GROQ_WAIT_BUDGET` to 110s made it *worse* — 240s with
  4 stand-in scores. Reverting to 75s and instead capping the judge's calls to their real need
  (narration 600, score 400) plus settling streaming reservations against actual usage gave
  **123s with 0 stand-ins**. If stand-ins reappear, look for a call reserving more than it uses.

## Conventions specific to this repo

- **Never hardcode a rule in Python.** If a new check is needed, first ask whether one of the eight strategies plus a new CSV + manifest entry covers it. Only add a ninth strategy (and register it in the `STRATEGIES` dict) if the shape is genuinely new.
- **Don't let the generator do the checker's job.** The design agent's fallback deliberately reaches for lactose (the most common diluent) and lets the rulebook reject it. Pre-avoiding known incompatibilities hides what the verification layer catches — which is the entire point of the system.
- **Never assert chemistry the data doesn't support.** Acetaminophen is an amide, not an amine; the original demo hardcoded `["Primary Amine"]` and that was wrong. `tests/test_smarts.py` pins the truth table — if it fails, the chemistry changed, not just the code.
- Comments and docstrings are in Korean; match that style when editing existing files.
- `database/` is the canonical rulebook (이도영's 30 CSVs + 15 SOURCES.md), `database/reference/` holds 조하준's 5 lookup tables, `database/legacy/` holds the 1st-gen CSVs kept only for regression comparison (`config/legacy_manifest.yaml` still points at them). Stale top-level copies of `incompatibility_rules.csv`/`process_failure_rules.csv` remain in the repo root and are unused.
- **Known data issues to be resolved with the pharmacy team** (do not silently "fix" their CSVs):
  - `structural_flags_smarts.csv` is still `validation_status=UNTESTED` even though `scripts/verify_smarts.py` now passes 9/9. FLG002 over-detects guanidine and non-aromatic ring NH as secondary amines.
  - `rulebook_config.csv` has 6 join_key/blocking discrepancies documented in the 개발자 가이드 §9.7. The engine uses `config/rulebook_manifest.yaml` instead, so they're documentation-only.
  - `packaging_compatibility_rules.csv` names prohibited packaging in Korean prose ("고투습 포장"); `config/packaging_categories.yaml` bridges identifiers to those categories. New packaging goes in that YAML, not the CSV.
