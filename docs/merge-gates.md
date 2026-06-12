# Pre-Merge Gate Protocol

**Updated:** 2026-06-12 (T5.2 post-cage sync — Gate a extended to cover `agent/`; invariants
1/2/3/7 graduated from roadmap; Gate e flake8 added; explicit agent/-allowed note)

This document is the canonical definition of the pre-merge gate protocol for AgentAssist
branches. Run all gates and report results before any merge to `master`. Stop if any gate
fails.

---

## Gate a — No forbidden imports in `orchestrator/`

The invariant: `orchestrator/` is pure Python — no `anthropic` package dependency, no
`reasoning`, `documents`, or `agent` package import. This keeps the deterministic chain
import-safe AND prevents `orchestrator/` from transitively pulling the Claude Agent SDK
through `agent/`.

**Correct form (import-only grep; all three must return nothing):**

```
# Check 1 — no anthropic import
grep -rnE "^[[:space:]]*(import[[:space:]]+anthropic|from[[:space:]]+anthropic[[:space:]]+import)" orchestrator/

# Check 2 — no reasoning/documents/agent import
grep -rnE "^[[:space:]]*(import[[:space:]]+(reasoning|documents|agent)|from[[:space:]]+(reasoning|documents|agent)[[:space:]]+import)" orchestrator/
```

All commands must return **nothing** (empty output, exit 1). A match on either is a gate
failure.

**What IS allowed — do not re-add restrictions that don't belong here:**

`agent/` is **permitted** to import `anthropic` (lazily, via `claude-agent-sdk`), exactly
as `reasoning/` and `documents/` do. The boundary is at `orchestrator/`, not at `agent/`.
**Do NOT add a "no anthropic in agent/" rule** — it would be wrong and would be reverted.

The correct allowed/forbidden map:

| Package | May import `anthropic` | May import `agent/` | May import `orchestrator/` |
|---|---|---|---|
| `orchestrator/` | **NO** | **NO** | — |
| `reasoning/` | YES (lazy) | NO | NO |
| `documents/` | YES (lazy, multimodal path) | NO | NO |
| `agent/` | YES (lazy, SDK) | — | NO |
| `run_agent.py` | NO (orchestrator glue) | YES | YES |

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
