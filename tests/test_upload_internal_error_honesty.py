"""tests/test_upload_internal_error_honesty.py — POST /review/upload error-honesty.

Failing-test-first for the ``except → 422`` mislabel fix (Option A — positional split).

THE BUG: the upload handler wrapped its engine-path calls in a broad ``except Exception →
422 "Could not read export"``, so an engine-INTERNAL failure (our bug, downstream of a
successfully-parsed file) was relabeled as a client-input error — blaming the user for our
breakage and hiding the real fault. Made live by Build 3 (#85).

THE FIX (Option A): only the PARSE/CONSTRUCTION step stays inside the 422 boundary
("couldn't read your file" — honest bad-input). Everything AFTER a reader is successfully
constructed (run_chain/review, serialize_xero_queue, compile_output access, coverage_status()
derivation) runs OUTSIDE it, so an engine-internal failure surfaces as an honest 500, NOT a 422.

  * (a) an INTERNAL failure (a helper downstream of the parse raises) → 500, NOT 422, and the
        detail does NOT read "Could not read export" (we do not blame the user's file).
  * (b) GUARDRAIL — the mirror risk: honest DEGRADATION must NOT be relabeled 500. Valid data
        that yields degraded/unavailable coverage still returns its 200 signal (degradation is
        surfaced as DATA, never raised as an error).

The bad-input-still-422 pins live in test_tsource_selector_upload.py
(test_upload_rejects_unreadable_xlsx / _non_xlsx) and test_extract_engine_upload.py (BT3);
this file adds only the two cases above. SAP off, hermetic engine, no tokens, no anthropic.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FROZEN_EXTRACT_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
_FLAG = "AGENTASSIST_EXTRACT_ENGINE"

# synth exporter — local importlib load (tests/ is not a package), as the sibling upload tests do.
_synth_spec = importlib.util.spec_from_file_location(
    "internal_error_synth_export", Path(__file__).resolve().parent / "synth_extract_export.py"
)
_synth = importlib.util.module_from_spec(_synth_spec)
_synth_spec.loader.exec_module(_synth)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic_engine(tmp_path, monkeypatch):
    """Redirect the engine's PDF dir + the bundle's audit root to tmp, set dummy SAP creds.
    Mirrors test_extract_engine_upload.py — the extract engine path runs the FULL review()."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")


def _valid_extract_bytes(tmp_path: Path) -> bytes:
    """A REAL, well-formed .xlsx built from the committed frozen fixture (parses cleanly)."""
    out = tmp_path / "valid_export.xlsx"
    _synth.export_xlsx(_FROZEN_EXTRACT_DIR, out)
    return out.read_bytes()


def _post(client: TestClient, content: bytes, filename: str = "export.xlsx",
          source: str | None = "extract"):
    """POST /review/upload; the extract branch requires an explicit source (Slice D).

    AMENDED (Slice D, D-2026-09-21-unmapped-codes). THE DEFAULT IS A PROPERTY OF THIS FILE,
    NOT OF THE ENDPOINT: every caller in this module uploads a general extract, so defaulting
    to "extract" keeps the amendment to one line instead of repeating it at each call site.

    A FUTURE XERO TEST IN THIS FILE MUST NOT RELY ON THIS DEFAULT. Pass the source
    per-call — `source="xero"`, or `source=None` to exercise the no-source refusal — because
    a Xero upload inheriting "extract" would be refused by the very routing guard this
    parameter exists to satisfy, and the failure would look like a routing bug rather than a
    test that forgot to say what it was uploading.
    """
    return client.post(
        "/review/upload", files={"file": (filename, content)},
        data={"source": source} if source else None,
    )


# ── (a) an engine-INTERNAL failure is an honest 500, never a mislabeled 422 ──────────────

def test_internal_engine_failure_is_500_not_422(client, hermetic_engine, tmp_path, monkeypatch):
    """A failure DOWNSTREAM of a cleanly-parsed file (here: serialize_xero_queue, which runs
    only after the reader is built and the chain has completed) is OUR bug, not the user's
    file. It must surface as a 500 with an honest 'this is our error' detail — NOT a 422
    'Could not read export' that blames the upload."""
    monkeypatch.delenv(_FLAG, raising=False)  # engine ON (default) → the extract_review path runs

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("engine-internal bug — NOT the user's file")

    # serialize_xero_queue runs AFTER the reader is constructed and run_chain has completed:
    # a raise here is unambiguously internal, never a parse/bad-input failure.
    monkeypatch.setattr("api.app.serialize_xero_queue", boom)

    resp = _post(client, _valid_extract_bytes(tmp_path))

    assert resp.status_code == 500, (
        f"an engine-internal failure must be a 500, got {resp.status_code}: {resp.text}"
    )
    assert resp.status_code != 422, "internal failure must NOT be relabeled a 422 bad-input error"
    detail = resp.json().get("detail", "")
    assert "Could not read export" not in detail, (
        "must not blame the user's file for our internal failure"
    )
    assert "internal" in detail.lower(), "the 500 detail must honestly name it an internal error"


# ── (b) GUARDRAIL — honest degradation stays a 200 signal, never relabeled 500 ───────────

def test_honest_degradation_still_returns_signal_not_500(client, tmp_path, monkeypatch):
    """The mirror of the bug we are fixing: coverage_status() derivation surfaces honest
    degradation as RETURNED data (degraded/unavailable rows on a 200), never as a raised
    error. Moving derivation outside the 422 boundary must NOT turn that into a 500. Valid
    data that yields degraded/unavailable coverage still returns its 200 signal."""
    monkeypatch.setenv(_FLAG, "0")  # coverage-only branch (engine OFF) — derivation-only path

    resp = _post(client, _valid_extract_bytes(tmp_path))

    assert resp.status_code == 200, (
        f"honest degradation must surface as a 200 data signal, got {resp.status_code}: {resp.text}"
    )
    rows = resp.json()["coverage_status"]
    levels = {row["level"] for row in rows}
    assert levels & {"degraded", "unavailable"}, (
        "the coverage-only path over this export must surface honest-degradation rows "
        "(degraded/unavailable) as DATA — proving derivation was not relabeled a 500"
    )
