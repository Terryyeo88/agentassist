# .claude/ — subagent dev infrastructure

For Collin (and future contributors). This directory holds the committed subagent definitions,
the append-only-test hook, and the settings that wire them in. Committing these files **is** the
shared invariant contract we both build against — the same rules, enforced the same way, on every
machine.

## The mental model (one paragraph)

Subagents run **inside your own Claude Code session**, not in separate terminals — they are
specialised roles your main agent hands a focused task to, with their own tool set and model.
You invoke one by name ("use the invariant-auditor on this diff") or just describe the task and
let **auto-delegation** fire based on each agent's `description`. The load-bearing one is the
**invariant-auditor**: it reads the *real* code and `git diff` from disk, not your summary of
them — so when it returns a **FLAG**, treat it as real and stop, don't argue with it.

## The subagents

| Subagent | What it does | Reach for it when… |
|---|---|---|
| **recon-explorer** | Read-only Phase-1 recon: maps the relevant files, data flow, and constraints; surfaces risks. | Starting any feature — before writing a line, to understand the target area. |
| **invariant-auditor** | Independent reviewer. Checks a recon plan OR a `git diff` against the nine invariants; returns PASS / PASS-WITH-CAVEATS / FLAG. Reads ground truth from disk. | Before a build proceeds, and again before a PR is opened. |
| **test-first-author** | Writes the FAILING tests first, before implementation. Creates new test files only; never weakens or deletes an existing one. | After recon passes the auditor — to lock behaviour in tests before building. |
| **regression-runner** | Runs the full suite + import-scan + scope-check. Returns ONLY failures and violations. | After building — the fast go/no-go gate. |
| **docs-sync-drafter** | Updates in-repo canonical docs with honest-status caveats (built ≠ validated) and corrected test counts. Repo docs only. | After the suite is green — to keep the docs honest. |
| **comprehension-explainer** | Produces a plain-English walkthrough of the diff for someone who didn't watch it being written. | At the end of every build, read at merge time. |

## The build loop

`recon-explorer → invariant-auditor → test-first-author → build → regression-runner →
invariant-auditor → docs-sync-drafter → comprehension-explainer`

Full detail, the invariants, and the exact suite/import-scan/lint/scope-check commands are in the
root **`CLAUDE.md`**.

## The append-only-test hook

`.claude/settings.json` wires a PreToolUse hook (`.claude/hooks/block_existing_test_edits.py`)
that blocks Edit/Write on any file that **already exists** under `tests/`, while allowing new
`test_*.py` files to be created. This stops any agent from quietly weakening a test to go green.
CI re-running the suite on the PR is the backstop. If you legitimately need to change an existing
test, do it yourself (the hook only governs agent tool calls) and say so in the PR.
