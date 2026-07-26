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
.venv/bin/python scripts/feedback_demo.py         # wet-lab closed loop
.venv/bin/uvicorn web.server:app --port 8000      # dashboard at http://localhost:8000
.venv/bin/python scripts/import_rulebook.py       # re-import rulebook zips from 추가자료/
```

Everything runs **without an API key** — LLM nodes fall back to deterministic stand-ins so
demos never break. Set `ANTHROPIC_API_KEY` to enable the real Claude path.

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

- **`formula/chem/`** — RDKit input pipeline. `build_profile(api_name|smiles)` → `ApiProfile` (descriptors, SMARTS structural flags, advisory estimates, 2D SVG). Salts are stripped before SMARTS matching; `fr_*` counts cross-check every pattern. **Solubility/permeability estimates are `confidence=low` and must never set `bcs_class`** — the manifest gates `bcs_classification` behind measured values.
- **`formula/orchestrator/`** — LangGraph `StateGraph` (`graph.py`), shared state with a reset-aware `accumulate` reducer (`state.py`; return `None` to clear a fan-out list between reflection rounds), and the `TraceEvent` bus (`events.py`). Every node emits events; the web UI consumes only that stream.
- **`formula/agents/`** — Claude nodes. All use structured output (`messages.parse`) and **all have deterministic fallbacks**; `consensus.py` is pure Python driven by `severity_scoring_config.csv` (B model: judge scores rank, never block).
- **`web/`** — FastAPI + SSE + a no-build SPA. `/api/rules/{rule_id}` powers the evidence drill-down that shows the originating CSV row and its SOURCES document.

### Supporting pieces

- **`formula/contracts.py`** — all shared Pydantic models (the stable interface between the pharmacy-student data team and the backend). Key types: `FormulationSpec` (translated input: API, functional groups, BCS class, target patient, measured params, property flags), `Recipe` (candidate: ingredients with role/amount, process, packaging), `Verdict` (deterministic result: `PASS`/`HARD_FAIL`/`SOFT_FLAG`), `RulebookEntry`, `JudgeSpec`. If CSV columns change, fix the manifest `schema` — these contracts stay stable.
- **`formula/checkers/applies_when.py`** — evaluates `applies_when` / `row_filter` expressions via a **restricted `eval`** (`__builtins__` stripped, only a whitelisted context of spec fields + property flags exposed). These expressions are *trusted manifest-author input*, not user input. On expression error it fails closed (rule does not fire).
- **`formula/feedback/interpreter.py`** (`WetLabInterpreter`) — the **closed-loop** layer (human-in-the-loop). After a recipe passes verification and is actually made in the lab, a researcher re-inputs measured results (`WetLabResult`: dissolution, hardness, impurity, …). The interpreter compares each metric against target specs from `database/wetlab_feedback_rules.csv` and returns a `FeedbackReport` (per-metric off-target findings + cause interpretation + suggested revision, feeding the reflection/redesign loop). Same deterministic philosophy as the checkers: same experiment data → same interpretation. Each CSV row states an *off-target (failure) condition* (`metric <op> target`), mirroring the `threshold` strategy convention. Currently scope is interpretation only; protocol generation and the LLM reflection loop are not yet built. Demo: `scripts/feedback_demo.py`.
- **`docs/architecture_image_prompt.md`** — detailed prompts for AI-generating the full horizontal system architecture diagram (not code).

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
