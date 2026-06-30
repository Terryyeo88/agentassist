"""tests/test_tsource_selector_upload.py — POST /review/upload (source-selector backend).

FAILING-FIRST tests for the "source selector + empty state" feature. The locked backend
contract under test is a NEW route, ``POST /review/upload``:

  * raw-body upload (NOT multipart): query param ``filename`` + the file BYTES as the raw
    request body;
  * only ``.xlsx`` accepted — any other suffix (or an unreadable workbook) is a 422,
    never a 500;
  * on success returns a COVERAGE-ONLY view-model with EXACTLY the top-level keys
    ``{source_kind, validation_status, disclaimer, coverage_status}`` built from
    ``feeders.extract_reader.ExtractChainReader(...).coverage_status()`` projected via
    ``.as_dict()``;
  * it NEVER runs the engine: ``orchestrator.chain.run_chain`` / ``engine.review.review``
    are not invoked (engine execution is deferred to Collin's feeder→engine wiring).

The upload payload is built from the COMMITTED frozen fixture by reusing the synthetic
exporter, exactly as ``tests/test_t212a_extract_feeder.py`` does (importlib, since ``tests/``
is not a package). These tests must FAIL today (the route does not exist yet) and pass once
the route is built. SAP off, mock engine, no tokens.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_DIR = _REPO_ROOT / "api"
# The frozen raw-json surfaces (test_t212a_extract_feeder.py reads the same dir).
FROZEN_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"

# Load the synthetic exporter (tests/ is not a package — importlib, as test_t212a does).
_synth_spec = importlib.util.spec_from_file_location(
    "tsource_synth_export", Path(__file__).resolve().parent / "synth_extract_export.py"
)
synth = importlib.util.module_from_spec(_synth_spec)
_synth_spec.loader.exec_module(synth)

_COVERAGE_LEVELS = {"full", "degraded", "unavailable"}
_DOC_PREPASS = {
    "gst_amount_mismatch",
    "correct_period",
    "total_inconsistency",
    "reg11_supplier_gst_absent",
}
_KNOWN_CHECKS = {"DUP_CLAIM", "NO_GST_REG", "SEQ_GAP", "E1"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _frozen_dir_exists() -> None:
    assert FROZEN_DIR.is_dir(), f"frozen extract fixture dir missing: {FROZEN_DIR}"


def _xlsx_bytes(tmp_path) -> bytes:
    """A REAL .xlsx built from the committed frozen fixture via the synthetic exporter."""
    _frozen_dir_exists()
    out = tmp_path / "export.xlsx"
    synth.export_xlsx(FROZEN_DIR, out)
    return out.read_bytes()


# ── 1. coverage-only response shape ──────────────────────────────────────────────────

def test_upload_returns_coverage_only_shape(client: TestClient, tmp_path: Path):
    """200 + EXACTLY the coverage-only key set, with a well-formed coverage_status list."""
    resp = client.post(
        "/review/upload?filename=export.xlsx", content=_xlsx_bytes(tmp_path)
    )
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == {
        "source_kind", "validation_status", "disclaimer", "coverage_status"
    }
    assert body["source_kind"] == "extract_upload"
    assert body["validation_status"] == "unvalidated"
    assert "unvalidated" in body["disclaimer"].lower()
    assert body["disclaimer"].strip(), "disclaimer must be non-empty"

    rows = body["coverage_status"]
    assert isinstance(rows, list) and rows, "coverage_status must be a non-empty list"
    for row in rows:
        assert set(row.keys()) == {"check", "level", "reason"}, (
            f"coverage row keys drifted: {set(row.keys())}"
        )
        assert row["level"] in _COVERAGE_LEVELS
        # full ⇔ no reason; degraded/unavailable ⇔ a surfaced (non-empty) reason.
        assert (row["level"] == "full") == (row["reason"] == "")

    checks = {row["check"] for row in rows}
    # The document-pre-pass checks are UNAVAILABLE on an extract (no source-document PDFs).
    unavailable = {row["check"] for row in rows if row["level"] == "unavailable"}
    assert _DOC_PREPASS & unavailable, (
        "at least one document-pre-pass check must be 'unavailable' on an extract upload"
    )
    # The known check names are all present.
    assert _KNOWN_CHECKS <= checks, f"missing known checks: {_KNOWN_CHECKS - checks}"


# ── 2. the engine never runs on upload (deferral pin) ────────────────────────────────

def test_upload_never_runs_the_engine(client: TestClient, tmp_path: Path, monkeypatch):
    """Pins the deferral: ``POST /review/upload`` is COVERAGE-ONLY. Engine execution is
    deferred to Collin's feeder→engine wiring — neither ``engine.review.review`` nor
    ``orchestrator.chain.run_chain`` may be invoked by the upload path. We booby-trap both
    and prove the upload still returns 200 (so neither was called)."""

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("engine must not run on upload")

    monkeypatch.setattr("engine.review.review", boom)
    monkeypatch.setattr("orchestrator.chain.run_chain", boom)

    resp = client.post(
        "/review/upload?filename=export.xlsx", content=_xlsx_bytes(tmp_path)
    )
    assert resp.status_code == 200


# ── 3. + 4. rejections — a bad upload is a 422, never a 500 ───────────────────────────

def test_upload_rejects_non_xlsx(client: TestClient):
    resp = client.post("/review/upload?filename=export.txt", content=b"not a workbook")
    assert resp.status_code == 422


def test_upload_rejects_unreadable_xlsx(client: TestClient):
    resp = client.post("/review/upload?filename=export.xlsx", content=b"garbage")
    assert resp.status_code == 422


# ── 5. import-edge scan (the must-fix caveat — a NEW file, NOT an edit of test_t61) ───

def _imported_top_modules(py_file: Path) -> set:
    """Top-level (level-0) imported modules in ``py_file`` — local reimplementation of the
    AST walker in tests/test_t61_frontend_api.py (NOT imported; tests/ is not a package)."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    mods: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    return mods


def test_api_still_imports_no_anthropic():
    forbidden = {"anthropic", "claude_agent_sdk"}
    for py_file in _API_DIR.rglob("*.py"):
        leaked = _imported_top_modules(py_file) & forbidden
        assert not leaked, f"{py_file} imports forbidden module(s): {leaked}"


def test_api_feeders_edge_is_present_and_clean():
    """api/app.py grows a NEW api/→feeders/ edge — and that edge must be upward-clean.

    feeders/ is a pure leaf: it imports NONE of anthropic/agent/engine/orchestrator/
    reasoning/documents, so adding ``from feeders... import ...`` to api/app.py does not
    drag the SDK or the engine into the api import graph. (The anthropic runtime guard is
    test_api_import_does_not_load_anthropic below; api/ IS allowed to depend on agent/engine/
    orchestrator per Gate a — only anthropic is forbidden.)
    """
    app_mods = _imported_top_modules(_API_DIR / "app.py")
    assert "feeders" in app_mods, "api/app.py must import feeders (the new upload edge)"

    forbidden = {"anthropic", "agent", "engine", "orchestrator", "reasoning", "documents"}
    for rel in ("extract_reader.py", "coverage_status.py", "extract_schema.py"):
        leaf = _REPO_ROOT / "feeders" / rel
        leaked = _imported_top_modules(leaf) & forbidden
        assert not leaked, f"feeders/{rel} imports forbidden module(s): {leaked}"


def test_api_import_does_not_load_anthropic():
    """Importing api.app must not pull anthropic into sys.modules (mirrors the ui/ guard in
    test_t61_frontend_api.py). NOTE: api/ IS permitted to depend on agent/engine/orchestrator
    (Gate a), so those legitimately load — only anthropic must stay out."""
    for mod in list(sys.modules):
        if mod == "anthropic" or mod.startswith("anthropic."):
            pytest.skip("anthropic already imported by another test in this process")

    import api.app  # noqa: F401

    importlib.reload(api.app)
    assert "anthropic" not in sys.modules
