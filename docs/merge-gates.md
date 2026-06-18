# Pre-Merge Gate Protocol

**Updated:** 2026-06-12 (T5.1 engine-seam — Gate a Check 2 extended to cover `engine/`;
dependency direction is engine→orchestrator, never reverse)

This document is the canonical definition of the pre-merge gate protocol for AgentAssist
branches. Run all gates and report results before any merge to `master`. Stop if any gate
fails.

---

## Gate a — No forbidden imports in `orchestrator/`

The invariant: `orchestrator/` is pure Python — no `anthropic` package dependency, no
`reasoning`, `documents`, `agent`, or `engine` package import. This keeps the deterministic
chain import-safe AND prevents `orchestrator/` from transitively pulling the Claude Agent
SDK through `agent/`. The dependency direction is `engine/ → orchestrator/`, never reverse:
`engine/` calls into `orchestrator/`; `orchestrator/` must not import `engine/`.

**Correct form (import-only grep; all three must return nothing):**

```
# Check 1 — no anthropic import
grep -rnE "^[[:space:]]*(import[[:space:]]+anthropic|from[[:space:]]+anthropic[[:space:]]+import)" orchestrator/

# Check 2 — no reasoning/documents/agent/engine import
grep -rnE "^[[:space:]]*(import[[:space:]]+(reasoning|documents|agent|engine)|from[[:space:]]+(reasoning|documents|agent|engine)[[:space:]]+import)" orchestrator/
```

All commands must return **nothing** (empty output, exit 1). A match on either is a gate
failure.

**What IS allowed — do not re-add restrictions that don't belong here:**

`agent/` is **permitted** to import `anthropic` (lazily, via `claude-agent-sdk`), exactly
as `reasoning/` and `documents/` do. The boundary is at `orchestrator/`, not at `agent/`.
**Do NOT add a "no anthropic in agent/" rule** — it would be wrong and would be reverted.

The correct allowed/forbidden map:

| Package | May import `anthropic` | May import `agent/` | May import `engine/` | May import `orchestrator/` |
|---|---|---|---|---|
| `orchestrator/` | **NO** | **NO** | **NO** | — |
| `engine/` | NO | NO | — | YES |
| `reasoning/` | YES (lazy) | NO | NO | NO |
| `documents/` | YES (lazy, multimodal path) | NO | NO | NO |
| `agent/` | YES (lazy, SDK) | — | YES | NO |
| `run_agent.py` | NO (orchestrator glue) | YES | YES | YES |
| `ui/` (T5.8 demo) | **NO** (direct) | YES | YES | via `engine/` |
| `api/` (T6.1 seam) | **NO** | YES | YES | via `engine/` |
| `feeders/` (T2.12 extract) | **NO** | **NO** | **NO** | **NO** |

**`ui/` import posture (T5.8 demo showcase — documentation only, NOT a Gate-a grep):**
The `ui/` package is a new top-level consumer. It **may** import `agent/`, `engine/`, and `report/`
(it renders over the engine seam and the existing report path), but the Mock + Sign render path **must
not** import `anthropic`, the Claude Agent SDK, or `agent.loop` — the default demo stays hermetic
(MockEngine loads frozen artifacts; RealEngine defers its `engine.review` import to call time). This
posture is **enforced by a T5.8 guard test** (`tests/test_t58_mock_engine.py` — asserts those modules
are absent from `sys.modules` after the Mock+Sign path runs), **not** by Gate a's `orchestrator/`
import-scan grep, and **no CI gate is added for `ui/` in this docs-sync** (adding one is a code change,
out of scope here). *Consider promoting this to a grep gate later* (an import-scan over `ui/` for
`anthropic`/`claude_agent_sdk`) if `ui/` grows beyond the demo or the guard test proves insufficient.

**`feeders/` import posture (T2.12 extract feeder — documentation only, NOT a Gate-a grep):**
The `feeders/` package is a new top-level **leaf**: it holds alternate `ChainReader`
implementations (the T2.12 Excel/CSV extract feeder) that satisfy the seam **structurally**
(duck-typed — it neither imports nor widens the `ChainReader` Protocol in `sap_b1_server.py`).
It is **injected-only** (`run_chain(reader=ExtractChainReader(...))`); nothing in
`orchestrator/`/`engine/`/`agent/` imports it. It **must not** import `anthropic`, the
Claude Agent SDK, live-SAP machinery (`sap_b1_server`/`SAPB1Client`), or `orchestrator`/
`engine`/`agent` — it is pure stdlib (+ `openpyxl`, lazily, on the `.xlsx` path only). This
posture is currently verified by the T2.12a round-trip + a feeder-purity check in the
pre-merge run, **not** by a CI grep (adding one is a code change, out of scope for this
docs-sync). *Consider promoting to an import-scan grep over `feeders/` later* if the package
grows beyond the extract adapter.
**Re-checked at T5.8d (review-surface rebuild, 2026-06-17):** posture unchanged. The new
`ui/views/review.py` imports only `streamlit` + `agent.lint`/`agent.artifacts` view-models + `ui.sign`
(no `anthropic`/SDK); the two new `ui/artifacts.py` accessors add only `agent.registry` (anthropic-free),
keeping `artifacts.py` Streamlit-free and model-free; the new `.streamlit/config.toml` is theme config
only (no imports). The T5.8 guard test still passes, and an additional headless-import test
(`tests/test_t58d_review_surface.py::test_artifacts_import_is_headless`) asserts importing `ui.artifacts`
pulls no `streamlit`/`anthropic`/`engine.review`/`agent.loop`. `ui/` row above stays accurate.

**`agent/classifier_factory.py` note (T5.9e, 2026-06-18):** the env-gated classifier-backend factory lives
in `agent/`, so it is squarely inside the `agent/` row above — it **may** name/construct
`AnthropicClassifierBackend` and select the live backend lazily, but it does **not itself** import
`anthropic` (the SDK import stays confined to `agent/intent_classifier.py`'s call site; the factory only
NAMES the class, so *selecting* live does not load the SDK). The boundary stays at `orchestrator/`; **no new
grep rule is added** and none is needed. This is proven by the T5.9e AST import-scans
(`tests/test_t59e_classifier_factory.py`): the factory imports `anthropic` nowhere (not even deferred),
across `agent/` `intent_classifier.py` remains the only `anthropic` importer, and `orchestrator/` imports
neither the factory nor the classifier.
**`api/` import posture (T6.1 React-frontend seam — documentation only, NOT a Gate-a grep):**
The `api/` package is a new top-level **serve/presentation** consumer: a thin FastAPI layer that
serialises the FROZEN demo artifacts (via `ui.artifacts.load_demo_artifacts` / `ui.sign`) to JSON for
the React frontend under `frontend/`. Like `ui/`, it **may** import `agent/`, `engine/`, `report/`, and
the `ui/` view-models, but it **must not** import `anthropic` or the Claude Agent SDK — the boundary
stays at `orchestrator/`, never at `api/`. This posture is **enforced by an AST import-scan test**
(`tests/test_t61_frontend_api.py::test_api_imports_no_anthropic` over every `api/**/*.py`, plus a
`sys.modules` guard), **not** by a CI grep (adding one is a code change, out of scope here).
`orchestrator/` + `engine/` are untouched by T6.1. There is deliberately **no `/command`
classify+execute endpoint** in this slice (Lane C2, deferred). *Consider promoting to a grep gate over
`api/` later* if it grows beyond the demo seam.

**T6.2 update (`POST /command` landed — Lane C2):** the AST import-scan over `api/` **stays green**.
`api/app.py` now imports `agent.classifier_factory` / `agent.intent_classifier` / `agent.dispatch_exec`
/ `agent.intent_curated` and may **construct** the live classifier (`AnthropicClassifierBackend`) under
`AGENT_UI_CLASSIFIER=live` — but the `anthropic` SDK import stays **lazy/confined to that backend's
call site** (`agent/intent_classifier.py::AnthropicClassifierBackend._create`), so importing `api/`
triggers **no** `anthropic` import and `tests/test_t62_command.py::test_api_imports_no_anthropic`
(over every `api/**/*.py`) passes. **Live tokens are a runtime event only** under the env flag (live
**without** `ANTHROPIC_API_KEY` → loud `ClassifierConfigError` → 500, never a silent fallback); the
default path is scripted + token-free. The boundary stays at `orchestrator/` (untouched), never at
`api/`. No new CI grep is added.

**`agent/facets.py` note (T6.3 Slice 1, 2026-06-18):** the deterministic faceted-filter engine lives in
`agent/`, so it sits inside the `agent/` row above — but it is deliberately **stricter than the row
requires**: it is **pure stdlib**, importing no `anthropic`/SDK, no network, and **no `orchestrator/`,
`engine/`, `ui/`, or `api/`** (a view/projection layer with zero computation or surface coupling). It is
the source-agnostic engine under the "prompt me for details" filter feature (it facets the **canonical**
findings, narrowing the VIEW, never the computation). **No posture change and no new grep rule** — the
boundary stays at `orchestrator/`. This is proven by the T6.3 AST import-scan + clean-subprocess runtime
check (`tests/test_t63_facet_engine.py::TestHermeticPure`): `agent/facets.py` imports stdlib only,
importing it loads none of anthropic/SDK/streamlit/fastapi/orchestrator/engine, and `orchestrator/` does
not import `agent.facets`. NOT wired into any surface in this slice (engine only).

**`agent/dispatch_exec.py` imports `agent/facets.py` note (T6.3 Slice 2, 2026-06-18):** the dispatch-execution
layer now imports the pure `agent/facets.py` (and nothing else new) to attach the data-derived filter menu
(`available_facets`) and apply optional, surface-supplied, **view-only** findings filters over the canonical
findings (validated against the real domain, box-isolated, never silently empty). Both modules sit in the
`agent/` row above; `dispatch_exec.py` stays free of `anthropic`/SDK/network/`orchestrator/`/`ui/`/`fastapi`/SAP
exactly as before. **No posture change and no new grep rule** — the boundary stays at `orchestrator/`. Proven by
the extended AST import-scan in `tests/test_t59d_dispatch_exec.py` + `tests/test_t63s2_facet_dispatch.py`
(`dispatch_exec` imports `agent.facets` and no banned root; `orchestrator/` does not reach `dispatch_exec`).
Still NOT wired to UI (Slice 3) or NL (Slice 4); findings-only.

**`POST /command` threads a view-only `filters` param (T6.3 Slice 3a, 2026-06-18):** the React API
(`api/app.py`) now reads an optional `filters` field from the `POST /command` body and threads it to
`execute_intent(filters=...)`; the enriched response already serialised (Slice 2). **`api/` posture is
unchanged:** it adds **no domain logic** — Pydantic does shape validation only, and DOMAIN validation stays
the engine's job (the single source of truth), so an off-domain value flows through to a structured
`filter_rejection` in the 200 body, never a 4xx. `api/` already imports `agent`/`ui`/`report` view-models and
remains `anthropic`-free; **no new boundary, no posture change, no new grep rule** — the boundary stays at
`orchestrator/`. Proven by `tests/test_t63s3a_command_filters.py` (+ the existing `api/` AST import-scan in
`tests/test_t62_command.py`). NO frontend (Slice 3b), NO NL extraction (Slice 4); findings-only.

**CI / Node toolchain separation (T6.1):** repo CI is **pytest-only** (`.github/workflows/ci.yml`:
flake8 + the `orchestrator/` import-scan + `pytest -n auto`). T6.1 adds `fastapi`+`uvicorn` to
`requirements.txt` so `api/` imports cleanly in the existing Python job; **the Python suite is the merge
gate and does NOT depend on Node.** The frontend `vitest`/`vite build` is kept a **separate,
optional/local** job — **no Node job was added to `ci.yml`** in this slice (adding one is a deliberate
later step). Run the frontend tests locally with `cd frontend && npm install && npm test`.

**Why this exact form — not `grep -r "anthropic" orchestrator/`:**

The plain-string form produces false positives on comments and docstrings. On 2026-06-09
during the T2.9 merge, `orchestrator/check_declared_f5.py:44` contains the docstring line:

```
No SAP calls; no anthropic import.  Pure Python, import-safe from orchestrator/.
```

The word "anthropic" in a docstring documenting the *absence* of the import triggered a
false gate failure. The import-only regex correctly ignores comments and docstrings — only
actual `import` statements are violations.

The regex matches:
- `import anthropic` — top-level import
- `from anthropic import ...` — selective import
- Indented forms (deferred/conditional imports inside functions)
- Aliased forms (`import anthropic as ac`)

This gate is **automated in CI** (`.github/workflows/ci.yml` — "Import-scan" step). A local
pre-merge run is still required to catch violations before pushing.

---

## Gate b — Full suite green + flake8 clean

Run **both** commands. CI gates on both; your local pre-push check must mirror CI exactly.

```
# pytest — full suite
python -m pytest --tb=short -q

# flake8 — CI pass 1 (fail-fast: syntax errors + undefined names)
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

Report exact pass/skip/fail count from pytest. Confirm flake8 exits 0. Stop if either fails.

**Why flake8 must be run locally (lesson from t5.2b):**
PR `bb73de6` (`fix: remove vestigial nonlocal in T-3 spy test`) was needed because a
`nonlocal` declaration on a variable that was only *read* (never assigned) in the inner
scope triggered flake8 F824 (undefined `nonlocal`). The test passed pytest locally but
blocked CI. The local pre-push gate must run the same flake8 selectors CI uses
(`E9,F63,F7,F82`) — not just pytest. CI pass 2 (`--exit-zero`) is informational and never
fails the build; run it locally for awareness but it is not a merge blocker.

---

## Gate c — Isolation invariant intact

Two sub-checks:

**c1 — T2.9 declared-f5-off test passes (when T2.9 is in scope):**

```
python -m pytest tests/test_check_declared_f5.py::test_isolation_no_declared_f5_empty_findings -v
python -m pytest tests/test_check_declared_f5.py::test_isolation_computed_boxes_not_mutated -v
```

**c2 — Pre-existing `show_ai_candidates` Box 8 isolation tests still pass:**

```
python -m pytest -k "isolation" -v
```

---

## Gate d — Clean working tree

```
git status
git diff --stat
```

The only changes present must be those introduced by the intended branch. No stray edits,
no unintended staged files.

---

## Gate e — Agentic-cage invariants (T5.2+; required for any branch touching `agent/`)

The following invariants from the Tier-5 design are enforced — not just documented. Verify
each for any branch that adds or modifies `agent/` code.

**Invariant 1 — Triple existence: every autonomy rule stated + enforced + tested.**

A rule that exists only in a system prompt is not a rule. For each autonomy constraint,
confirm all three exist:
- Stated in the agent system prompt (or agent/ docstring / README).
- Enforced by a hook (PreToolUse or PostToolUse in `agent/hooks.py`).
- Proven by a test in `tests/test_t52b_hooks.py` or equivalent.

Verification: check that new constraints added to agent prompts have a corresponding
hook callback and a failing-case test that asserts the hook blocks or flags the violation.

**Invariant 2 — No write-capable credentials in the agent process.**

The agent holds no SAP write credentials and no git push credentials. Confirm that any
credential passing to `build_options()` or `harness.py` carries only read-scope tokens.
No `ClientConfig.password` or equivalent write credential appears in `agent/` imports or
`ClaudeAgentOptions` construction.

Verification:
```
grep -rn "password\|write_token\|push_token" agent/
```
Must return nothing.

**Invariant 3 — Atomicity: agent invokes the chain as one tool, never step-by-step.**

`run_review_chain` must remain a single entry in `REGISTRY` at Tier.ONE. The agent must
never have individual chain steps (fetch, calculate, classify, detect, compile) registered
as separate callable tools.

Verification:
```
python -c "from agent.registry import REGISTRY; print(list(REGISTRY.keys()))"
```
Confirm `run_review_chain` is present and no individual chain-step names appear.

**Invariant 7 — Agent-layer failure is non-blocking.**

If the agent errors, crashes, or hits its budget cap, the deterministic chain output and
sealed bundle must still complete. Confirm that any agent-layer code path that raises or
signals `BudgetExceededSignal` is caught above the seal call, not inside it.

Verification: the `test_agent_budget.py` tests confirm `BudgetExceededSignal` routing. For
any new exception type, add a test showing the chain seals normally when the agent fails.

---

## Merge commit message format

```
git merge --no-ff <branch> -m "Merge <branch>: <one-line summary>
(UNVALIDATED / flag-gated; validation_status unchanged)"
```

---

## History

- **2026-06-09:** Gate a definition corrected from plain-string `grep -r "anthropic" orchestrator/`
  to import-only regex (two greps). Plain-string form produced a false positive on
  `orchestrator/check_declared_f5.py:44` docstring during the T2.9 pre-merge gate run.
  See `exploration-notes/doc-audit/DOC-STALENESS-REPORT.md` §6 for full context.
- **2026-06-12:** Gate a extended — Check 2 now includes `agent/` in the forbidden-imports
  list for `orchestrator/` (prevents transitive SDK pull). Explicit "agent/ IS allowed the
  SDK" note added to prevent incorrect re-restriction. Gate b updated — flake8 (CI selectors
  E9,F63,F7,F82) added as a mandatory local pre-push check; lesson documented from t5.2b
  F824. Gate e added — agentic-cage invariants 1/2/3/7 graduated from
  `knowledge-base/AgentAssist-Technical-Roadmap-v5.md` §"New invariants" as enforced gates.
  CI import-scan step added to `.github/workflows/ci.yml` (CHANGE-2 of T5.2 post-cage sync).
- **2026-06-12:** T5.1 engine-seam — Gate a Check 2 extended to include `engine/` in the
  forbidden-imports list for `orchestrator/`. The `engine/` package wraps the full GST review
  pipeline (calling into `orchestrator/`); the dependency direction is engine→orchestrator,
  never reverse. The CI import-scan step updated accordingly.
- **2026-06-17:** T2.12 extract feeder (slice A) — `feeders/` added to the allowed/forbidden
  import map as a top-level leaf (imports nothing upward; injected-only `ChainReader` impls).
  Posture documented (mirrors the `ui/` note); **no CI grep added** (a code change, deferred).
