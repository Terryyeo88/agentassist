# DIAGNOSTIC-REPORT.md

Generated: 2026-06-10 (read-only diagnostic run, master @ e0cab63)

No tracked files were modified. No commits were made. This file is untracked (gitignored by the
`memory/` rule does not apply; it is simply not in git ls-files and `*.md` is not gitignored).

---

## STEP 1 — The fixture generator

### Location

```
tests/fixtures/documents/generate_invoices.py
```

(Confirmed via `git ls-files | grep -i generate`; file is tracked.)

### CI-safety verdict: SAFE — fully local, no network, no credentials

**Imports (exact, from source lines 56–66):**

```python
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas
```

No SAP connector, no MCP, no httpx, no requests, no `.env` load, no anthropic. The module
docstring also explicitly states: `"No network, no SAP instance, no anthropic import required."`

### What it writes and where

- **8 PDFs** in the same directory as the script (`tests/fixtures/documents/`):
  `INV-3001.pdf` through `INV-3008.pdf` (filename pattern `INV-<doc_num>.pdf`).
- **1 JSON manifest** in the same directory:
  `tests/fixtures/documents/fixtures_manifest.json`

The manifest is written to `out / "fixtures_manifest.json"` (line 600–603).

### CLI args / default invocation

The `generate()` function accepts an optional `output_dir: Path | None` parameter that
defaults to `DOCS_DIR` (the script's own directory). The `__main__` guard calls `generate()`
with no arguments.

**Default no-arg invocation:**

```
python tests/fixtures/documents/generate_invoices.py
```

No CLI argument parsing (`argparse`, `sys.argv`) — the only supported invocation is the default.

### Determinism

**Fully deterministic.** `canvas.Canvas(..., invariant=1)` fixes ReportLab's internal
timestamps so re-runs produce byte-identical PDFs. All case data (supplier names, amounts,
dates, injected issues) is hardcoded in `CASES`; no `random` module is used. The `SEED=20260608`
constant is reserved for future parametric extension but is not currently used.

**Count and timing:** 8 PDFs + 1 JSON. Each PDF is a single-page A4; generation takes ~1–2 s
total on the reference machine.

---

## STEP 2 — How the failing tests find fixtures

### Modules holding the ~209 failing tests

Three test modules, all in `tests/`:

| Module | Tests collected | Failures without PDFs |
|--------|-----------------|-----------------------|
| `test_documents_unified_report.py` | 86 (parametrized → 86) | ~86 (all that call FixtureDocumentProvider or run_documents_pass) |
| `test_documents_ingest.py` | 21 (parametrized over 8 cases) | 21 (COLLECTION ERROR without pdfplumber; test failures without PDFs) |
| `test_documents_reconcile.py` | 29 (parametrized over 8 cases) | 29 (same) |

Total collected across the three files: **262** (confirmed via `--collect-only`). Of those, 53
tests do not require actual PDFs (reconcile unit logic, import invariant checks) and pass
regardless. **209 tests need the PDFs** and fail in a fresh worktree without them.

### How fixtures are located

Each of the three modules defines its own path constant at module level:

```python
# test_documents_unified_report.py:61–63
_DOCS_DIR = Path(__file__).parent / "fixtures" / "documents"
_MANIFEST_PATH = _DOCS_DIR / "fixtures_manifest.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))   # ← at import time
```

```python
# test_documents_ingest.py:36–37
DOCS_DIR  = Path(__file__).parent / "fixtures" / "documents"
MANIFEST_PATH = DOCS_DIR / "fixtures_manifest.json"
```

```python
# test_documents_reconcile.py:36–37
DOCS_DIR  = Path(__file__).parent / "fixtures" / "documents"
MANIFEST_PATH = DOCS_DIR / "fixtures_manifest.json"
```

- `fixtures_manifest.json` is **tracked by git** (in `git ls-files`) → present in fresh worktrees.
- `INV-3001.pdf` … `INV-3008.pdf` are **gitignored** (`.gitignore` line 35: `*.pdf`) → absent in
  fresh worktrees, must be generated.

`test_documents_unified_report.py` reads the manifest **at collection time** (line 63), so
collection succeeds in fresh worktrees (manifest is present). Test failures occur at execution
time when `FixtureDocumentProvider.get_document(3001)` returns `None` (PDF missing) or when
`ingest(pdf_path)` is called on a non-existent path.

### Existing conftest hook for documents

**None.** `tests/conftest.py` only stubs SAP credential env vars:

```python
def pytest_configure(config):
    os.environ.setdefault("SAP_USERNAME", "_test_stub_no_sap_")
    os.environ.setdefault("SAP_PASSWORD", "_test_stub_no_sap_")
    os.environ.setdefault("CLIENT_ID", "sbodemosg")
```

There is no session-scoped fixture that runs the generator.

### Exact seam for a self-provisioning hook

Add a session-scoped `autouse=True` fixture to `tests/conftest.py`:

```python
# proposed addition — NOT yet in the file
@pytest.fixture(scope="session", autouse=True)
def _provision_invoice_fixtures():
    """Generate PDF fixtures if absent (gitignored, not committed)."""
    docs_dir = Path(__file__).parent / "fixtures" / "documents"
    if not list(docs_dir.glob("INV-*.pdf")):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "generate_invoices", docs_dir / "generate_invoices.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.generate(docs_dir)
```

This calls the existing `generate()` function exactly as designed, writes only to the
gitignored path, and is a no-op when PDFs already exist.

---

## STEP 3 — Anthropic API usage in the suite

### Grep results for `anthropic` / `ANTHROPIC_API_KEY` in tests/

All hits fall into one of two buckets:

**Bucket A — Tests that ASSERT the code does NOT import anthropic at the module level**
(source-inspection tests verifying layer-separation invariants). These do not call the API
and do not need a key.

Relevant files: `test_build_specialist_queue.py:473–476`,
`test_check_listing.py:13`, `test_documents_ingest.py:161–219`,
`test_documents_reconcile.py:329–333`, `test_documents_unified_report.py:971–976`,
`test_document_fixtures.py:314–321`, `test_label_fixture.py:643–649`.

Example (test_documents_ingest.py:212–219):
```python
def test_orchestrator_does_not_import_anthropic(self) -> None:
    assert "import anthropic" not in src, (...)
    assert "from anthropic" not in src, (...)
```

**Bucket B — Tests that use `"ANTHROPIC_API_KEY not set"` as a canned fixture string**

`test_reasoning_reg2627.py:726` and `test_report_judgment_section.py:117` embed this string
inside hardcoded JSON dicts that represent a pre-errored artefact. They test how the *report
renderer* handles an errored artefact — they do not check or read `os.environ`.

```python
# test_reasoning_reg2627.py:721–736 — literal fixture dict, not an env check
{
    "status": "errored",
    "error": "LLM call failed: ANTHROPIC_API_KEY not set",
    ...
}
```

### Do any tests make real network calls to api.anthropic.com?

**No.** All tests that exercise functions which call `anthropic.Anthropic(...)` inject a mock
via `unittest.mock.patch` or `monkeypatch`. The source functions guard key absence:

```python
# reasoning/label_fixture.py:309–313
api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not api_key:
    raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
client = anthropic.Anthropic(api_key=api_key)
```

Same pattern in `reasoning/reg2627.py:158–162` and `documents/ingest.py:184–192`.

### Does any code require ANTHROPIC_API_KEY merely to be PRESENT at import/collection time?

**No.** The `anthropic` module is imported inside function bodies (deferred import pattern),
not at module level. `test_documents_ingest.py:245–250` specifically asserts this invariant:

```python
def test_documents_ingest_anthropic_import_is_deferred(self) -> None:
    module_level = re.findall(r'^(?:import anthropic|from anthropic)', src, re.MULTILINE)
    assert not module_level, (...)
```

### Is there already a dummy key set anywhere?

**No.** `tests/conftest.py` stubs only SAP credential env vars. No `ANTHROPIC_API_KEY` stub
exists anywhere in the test infrastructure.

### Which tests would fail if ANTHROPIC_API_KEY is unset? Which hit the network?

**Zero.** All LLM-exercising tests mock the client before the key-check guard is reached.
`ANTHROPIC_API_KEY` can be absent from the environment and all 1156 tests still pass (confirmed:
the main-worktree run shows 1156 passed with no key set). No test hits `api.anthropic.com`.

---

## STEP 4 — Other hidden prerequisites + failure categorization

### .gitignore — other generated artifacts

From `.gitignore`:

```
audit/                              # audit bundle output directory
exploration-notes/t1.4-reports/     # generated PDF reports
exploration-notes/t1.6-tool-outputs/*.json
*.pdf                               # ALL PDFs (including fixture PDFs)
*-specialist.json                   # specialist queue outputs
```

**Are any of these needed by the test suite?**

- `audit/` — used by `test_audit_seal_verify.py` which creates its own `tmp_path` and does
  not read a pre-existing `audit/` directory. No hidden prerequisite.
- `*.pdf` — the 8 fixture PDFs are the only suite-critical generated artifacts.
- No test reads from `exploration-notes/` or `*-specialist.json`.

No additional hidden prerequisites beyond the 8 fixture PDFs.

### Additional gap: `pdfplumber` missing from committed `requirements.txt`

`pdfplumber` is imported at module level by `documents/ingest.py` (transitively imported
by all three document test modules). The committed `requirements.txt` does NOT list it.
The current working tree has an **unstaged local change** adding `pdfplumber` to
`requirements.txt` (confirmed by `git diff requirements.txt`). This change predates this
diagnostic session.

On the development machine, `pdfplumber==0.11.9` is installed in the system Python
(Python 3.13.3), which is why the main-worktree run (which uses system Python directly)
succeeds. A fresh worktree's `.venv` built from `pip install -r requirements.txt` (committed
version) will **not** have pdfplumber, causing all three document test modules to fail at
collection with `ModuleNotFoundError: No module named 'pdfplumber'`.

### Full failure categorization

Run from the main worktree (`sap-b1-ai-agent`) using system Python 3.13.3 with pdfplumber
installed and PDF fixtures present:

```
1156 passed, 1 skipped in 48.81s
```

**The 1 skip:**

```
tests/test_audit_seal_verify.py::test_T8_config_json_readonly_after_seal_posix
```
Platform-skipped on Windows — `os.chmod` read-only is not enforced by the OS for normal users
on Windows (tamper evidence is provided by hash, not file permission). Not a prerequisite issue.

**The 209 failures in a fresh worktree (pdfplumber installed, PDFs absent):**

| Category | Count | Root cause |
|----------|-------|-----------|
| missing-document-fixture (PDF) | **209** | `INV-3001.pdf` … `INV-3008.pdf` gitignored and absent from fresh worktrees |
| missing-other-file | 0 | — |
| anthropic-key | 0 | — |
| anything-else | 0 | — |

**Before pdfplumber is installed in a fresh worktree's venv:**

| Category | Count | Root cause |
|----------|-------|-----------|
| collection error (ModuleNotFoundError) | 3 modules | `pdfplumber` absent from `requirements.txt` (committed version) |

All 209 failures are exclusively in the 3 document test modules. **Zero failures are caused by
missing ANTHROPIC_API_KEY, missing SAP credentials, or any other non-fixture prerequisite.**

---

## STEP 5 — Summary and recommended fixes

### Root cause (one sentence)

The 8 PDF fixture files are gitignored (`*.pdf` in `.gitignore`) and must be generated before
the test suite runs; no conftest hook auto-provisions them, and `pdfplumber` is absent from the
committed `requirements.txt`.

### Two-part fix (not implemented in this run)

**Fix 1 — Add pdfplumber to requirements.txt** (already staged as a local modification):

```
+pdfplumber
```

**Fix 2 — Add an autouse session-scoped conftest fixture** that generates the PDFs if absent
(see Step 2 seam above). This is the cleanest option: zero configuration, fully deterministic,
writes only to gitignored paths, no-op when PDFs already exist.

Alternative to Fix 2: document a `pytest --setup` step (`python tests/fixtures/documents/generate_invoices.py`)
in CLAUDE.md or a Makefile target. Simpler but requires manual action in each fresh worktree.

### No-edit confirmation

No tracked files were modified during this diagnostic run. `DIAGNOSTIC-REPORT.md` is the only
new file created; it is untracked. No commits, merges, or pushes were made.
