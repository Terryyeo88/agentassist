# Pre-Merge Gate Protocol

**Updated:** 2026-06-09 (T2.9 gate-definition fix — see §Gate a below)

This document is the canonical definition of the pre-merge gate protocol for AgentAssist
branches. Run all four gates and report results before any merge to `master`. Stop if any
gate fails.

---

## Gate a — No Anthropic imports in `orchestrator/`

The invariant: `orchestrator/` is pure Python — no `anthropic` package dependency, no
`reasoning` or `documents` package import. This keeps the deterministic chain import-safe.

**Correct form (import-only grep; both must return nothing):**

```
# Check 1 — no anthropic import
grep -rnE "^[[:space:]]*(import[[:space:]]+anthropic|from[[:space:]]+anthropic[[:space:]]+import)" orchestrator/

# Check 2 — no reasoning/documents import
grep -rnE "^[[:space:]]*(import[[:space:]]+(reasoning|documents)|from[[:space:]]+(reasoning|documents)[[:space:]]+import)" orchestrator/
```

Both commands must return **nothing** (empty output, exit 1). A match on either is a gate
failure.

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

---

## Gate b — Full suite green

```
python -m pytest --tb=short -q
```

Report exact pass/skip/fail count. Stop if any test fails.

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
