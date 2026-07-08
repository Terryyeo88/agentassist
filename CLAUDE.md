# CLAUDE.md — AgentAssist build contract

This file is the shared, committed contract that the human and any agent (Claude Code +
its subagents) build against. It states the architectural **invariants**, the per-feature
**Build SOP / loop**, the exact **commands** for the suite / import-scan / lint / scope-check,
and the hard **Boundaries** an agent must never cross.

The canonical pre-merge gate protocol lives in `docs/merge-gates.md` (Gates a–e); this file
is the agent-facing summary of the rules that matter most during a build, plus the subagent
loop. Where the two overlap, `docs/merge-gates.md` is authoritative for merge mechanics.

---

## Invariants

These are project rules, not suggestions. The `invariant-auditor` subagent checks a recon plan
or a `git diff` against them and returns PASS / PASS-WITH-CAVEATS / FLAG.

1. **Import isolation.** `orchestrator/`, `engine/`, `report/`, `config/`, `mcp-servers/`, and
   `run_agent.py` import NO `anthropic`, and do not depend on `reasoning/`, `documents/`, or
   `agent/`. Only `reasoning/` (and `documents/`, on its multimodal path) imports `anthropic`,
   lazily. The dependency direction is `engine/ → orchestrator/`, never reverse. (See the
   allowed/forbidden map in `docs/merge-gates.md` Gate a — `agent/` IS allowed the SDK; do not
   re-restrict it.)
2. **Surfaces-never-asserts.** Any new reasoning-layer output is a *candidate*, never a verdict,
   never an auto-correction, and never a write to client data.
3. **Box-isolation.** F5 boxes and gate results are byte-identical before and after any new
   findings stream. No recomputation of boxes outside the deterministic chain.
4. **Determinism.** The deterministic chain stays reproducible; the offline-replay oracle stays
   byte-identical.
5. **Frozen flags.** `validation_status="unvalidated"` and `show_ai_candidates=False` are
   unchanged unless the task EXPLICITLY says to change them.
6. **No secrets.** No secrets in the diff or any committed artifact.
7. **Three-times enforcement.** A new invariant or rule appears in **prompt, code, AND test** —
   not just one of the three.
8. **Honest status.** Docs reflect honest status (built ≠ validated); test counts are updated
   wherever a count is claimed.
9. **Branch is t-prefixed.** Feature branches start with `t` (CI triggers on `t*`).

---

## Build SOP / loop

Run this per-feature loop. The arrows are the order; each subagent is invoked by name (or fires
by auto-delegation from its description). Subagents run **inside your own session** — they are not
separate terminals.

**Step 0 — base-freshness guard (run first, before creating the worktree/branch).** Guards
against the stale-local-master trap (starting work on a base already behind `origin/master`,
which caused three merge-status mislabels + one rebase conflict). Run:

```
python scripts/preflight_base_check.py
```

It `git fetch`es `origin master` (updates the remote-tracking ref only — no merge, no checkout,
no local mutation) and checks `git merge-base --is-ancestor origin/master HEAD`: **PASS** (exit 0)
if HEAD contains `origin/master`, **REFUSE** (non-zero) if the base is behind — telling you to run
`git pull origin master`. It **refuses only**: it never auto-pulls, auto-rebases, or auto-checks-out
anything. If `origin` is unreachable (offline) it prints an honest `UNVERIFIED` notice and exits 0
(warn-and-allow) rather than bricking offline work. This is the default `--context=preflight`
(the no-flag behaviour is unchanged). Note: it catches a base that is stale **at start**; for a base
that goes stale **mid-build** (master advances while you work), run the companion **pre-PR-open**
check below (`--context=prepr`).

```
recon-explorer        → read-only Phase-1 recon: map files, data flow, constraints, risks
   ↓
invariant-auditor     → review the recon plan against the invariants BEFORE building
   ↓                     (PASS / PASS-WITH-CAVEATS / FLAG; a FLAG stops the build)
test-first-author     → write the FAILING tests first (new files only; enforce 3-times rule)
   ↓
build                 → implement until the new tests pass for the right reason
   ↓
regression-runner     → full suite + import-scan + scope-check; reports ONLY failures/violations
   ↓
invariant-auditor     → review the real `git diff` again BEFORE the PR is opened
   ↓
docs-sync-drafter     → update in-repo canonical docs with honest-status caveats + new test counts
   ↓
comprehension-explainer → plain-English walkthrough of the diff, read at merge time
```

`invariant-auditor` reads the ground truth from disk (recon notes / `git diff`), not the
builder's summary. Treat its FLAGs as real.

**Pre-PR-open — mid-flight staleness check (run right before `gh pr create`).** Master may have
advanced while you worked (this forced the PR #92 rebase). Run:

```
python scripts/preflight_base_check.py --context=prepr
```

Same freshness primitive as step-0, mid-flight remediation: **PASS** (exit 0) if master has not
advanced past your branch tip (safe to open the PR), **REBASE NEEDED** (non-zero) if it has —
telling you to `git rebase origin/master` first (rebase, not a merge-style pull, keeps the branch a
clean linear diff) and reporting how many commits master advanced. Offline → `UNVERIFIED`, exits 0
(warn-and-allow). Like step-0 it **tells only** — it never auto-rebases, auto-pulls, or mutates
anything, and it is advisory (no hook: skipping it doesn't block you).

---

## Commands (exact)

These are the literal invocations the `regression-runner` subagent uses. Run them from the repo
root (or the worktree root).

**Full test suite**
```
python -m pytest --tb=short -q
```

**Import-scan** — the two Gate-a greps over `orchestrator/`. Both must return **nothing**
(empty output); a match on either is a failure. Mirrors `.github/workflows/ci.yml` and
`docs/merge-gates.md` Gate a.
```
grep -rnE "^[[:space:]]*(import[[:space:]]+anthropic|from[[:space:]]+anthropic[[:space:]]+import)" orchestrator/
grep -rnE "^[[:space:]]*(import[[:space:]]+(reasoning|documents|agent|engine)|from[[:space:]]+(reasoning|documents|agent|engine)[[:space:]]+import)" orchestrator/
```

**Lint** (CI fail-fast selectors — must exit 0)
```
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

**Scope-check** — there is **no separate script**. The scope-check is the Gate-d clean-tree
check: confirm the diff contains only the intended-branch changes, nothing stray.
```
git status
git diff --stat
```

---

## Boundaries

An agent working in this repo must **never**:

- **merge** anything (no `git merge`, no PR merge);
- **push `master`** (push only the t-prefixed feature branch);
- **delete branches**;
- **edit existing test files** — it may CREATE new `test_*.py` files, but must never modify or
  delete a file that already exists under `tests/` (this includes `conftest.py`, `replay_shim.py`,
  and `synth_extract_export.py`). If a test seems wrong, FLAG it for the human;
- **touch out-of-repo / pedagogical docs** — only in-repo canonical docs are editable;
- leave its worktree behind — **clean the worktree after the PR is opened**.

### Append-only-test enforcement

The "never edit an existing test" boundary is enforced mechanically, not just documented:
`.claude/settings.json` registers a **PreToolUse hook**
(`.claude/hooks/block_existing_test_edits.py`) that BLOCKS any Edit/Write/MultiEdit/NotebookEdit
on a file that already exists under `tests/`, while ALLOWING creation of new `test_*.py` files
(a Write to a path that does not yet exist passes through). **CI re-running the full suite on the
PR is the backstop** — it catches any test removed out-of-band (e.g. an `rm` via Bash, which the
PreToolUse hook does not intercept).
