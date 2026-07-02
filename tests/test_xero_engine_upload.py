"""tests/test_xero_engine_upload.py — PR-B failing-first tests: thread a reader through the
engine and flip the POST /review/upload Xero branch to a REAL review.

These tests are written BEFORE the implementation exists (failing-first SOP) and MUST fail
today for the RIGHT reason — the feature is absent, not a typo:

  * ``engine.review.ReviewInputs`` has no ``reader`` field yet (test 2 + the route);
  * ``engine.review.review`` does not forward ``reader`` to ``run_chain`` yet (test 3);
  * ``POST /review/upload`` is COVERAGE-ONLY today — it never runs the engine and has no
    ``findings`` key, and the workbook-format routing that sends a Xero F5 export down the
    engine path does not exist yet (test 1). Test 4 is the ADDITIVE lock that adding that
    routing leaves the synthetic extract path byte-unchanged (still coverage-only).

HONEST STATUS (the three caveats this surface carries):
  * real-Xero-FORMAT findings over SYNTHETIC data — candidates, never verdicts. The committed
    fixture mirrors a genuine Xero IRAS-F5 export LAYOUT but carries hand-authored synthetic
    transactions; it asserts NO GST/accuracy verdict.
  * the tax-rate → VatGroup mapping is PROPOSED / UNVALIDATED (DEBT-1: IRAS Annex E citations
    deferred).
  * NOT accuracy-validated (T2.11 is the binding validation gate) — validation_status stays
    "unvalidated".
  * dummy-SAP-creds runtime dependency (DEBT-9): the config loader hard-requires SAP creds even
    though no SAP call is made on this path, so the tests set dummy creds.

Pure stdlib + pytest + fastapi.testclient. No anthropic import. SAP off, no tokens, hermetic.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import app
import engine.review as engine_review

from api.viewmodel import QUEUE_ITEM_KEYS

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The COMMITTED real-FORMAT Xero IRAS-F5 export fixture (synthetic transactions).
_XERO_FIXTURE = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_XERO_FILENAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

# The frozen synthetic-extract surfaces (for test 4's coverage-only path, mirrors
# tests/test_tsource_selector_upload.py — NOT imported; tests/ is not a package).
_FROZEN_EXTRACT_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"

# The LOCKED findings projection on the committed Xero fixture (real-FORMAT, synthetic data).
# E1 and the DUP_CLAIM/NO_GST_REG/SEQ_GAP checks are dark on this path — surfaced only in
# coverage_status, never as findings.
_EXPECTED_FINDINGS = {("E2", "INV-2003"), ("E3", "INV-2002"), ("E4", "BILL-3002")}

_COVERAGE_LEVELS = {"full", "degraded", "unavailable"}


# ── synth exporter (test 4) — local importlib load, NOT an import of the existing test ──

_synth_spec = importlib.util.spec_from_file_location(
    "xero_engine_synth_export", Path(__file__).resolve().parent / "synth_extract_export.py"
)
_synth = importlib.util.module_from_spec(_synth_spec)
_synth_spec.loader.exec_module(_synth)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic_engine(tmp_path, monkeypatch):
    """Redirect the engine's PDF dir + the bundle's audit root to tmp, and set dummy SAP creds.

    The Xero branch runs the FULL ``review()`` (renders a PDF + seals an audit bundle); without
    these redirects it would litter the worktree. The dummy SAP creds satisfy the loader's hard
    requirement (DEBT-9) — NO SAP call is made on this path.
    """
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")


def _coverage_level(rows: list, check: str) -> str:
    for row in rows:
        if row["check"] == check:
            return row["level"]
    raise AssertionError(f"coverage check {check!r} not present in {[r['check'] for r in rows]}")


# ── 1. end-to-end: the reader threads into the engine and the route returns findings ──

def test_xero_upload_runs_engine_and_returns_findings(client: TestClient, hermetic_engine):
    """The full locked Xero-branch contract — proof the reader threaded into the engine.

    HTTP 200 + EXACTLY 5 top-level keys; source_kind=="xero_f5_upload"; frozen
    validation_status; a non-empty disclaimer that says "unvalidated"; NO ai_candidates in the
    body; the three dark coverage levels (NO_GST_REG unavailable, DUP_CLAIM/SEQ_GAP degraded);
    and queue reducing to EXACTLY the 3-set (no E1, no DUP_CLAIM/NO_GST_REG/SEQ_GAP).
    """
    assert _XERO_FIXTURE.is_file(), f"committed Xero fixture missing: {_XERO_FIXTURE}"

    resp = client.post(
        f"/review/upload?filename={_XERO_FILENAME}", content=_XERO_FIXTURE.read_bytes()
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # EXACTLY the 5 top-level keys.
    assert set(body.keys()) == {
        "source_kind",
        "validation_status",
        "disclaimer",
        "coverage_status",
        "queue",
    }
    assert body["source_kind"] == "xero_f5_upload"

    # Frozen flags + honest framing.
    assert body["validation_status"] == "unvalidated"
    assert isinstance(body["disclaimer"], str) and body["disclaimer"].strip()
    assert "unvalidated" in body["disclaimer"].lower()

    # Candidates-not-verdicts: no AI candidates leak onto this surface.
    assert "ai_candidates" not in body

    # coverage_status: the dark checks are surfaced here (never as findings).
    rows = body["coverage_status"]
    assert isinstance(rows, list) and rows
    for row in rows:
        assert set(row.keys()) == {"check", "level", "reason"}, (
            f"coverage row keys drifted: {set(row.keys())}"
        )
        assert row["level"] in _COVERAGE_LEVELS
    assert _coverage_level(rows, "NO_GST_REG") == "unavailable"
    assert _coverage_level(rows, "DUP_CLAIM") == "degraded"
    assert _coverage_level(rows, "SEQ_GAP") == "degraded"

    # findings: a list of dicts each with EXACTLY the 9 locked keys.
    queue = body["queue"]
    assert isinstance(queue, list) and queue, "expected a non-empty queue"
    for item in queue:
        assert set(item.keys()) == set(QUEUE_ITEM_KEYS), f"queue item keys drifted: {set(item.keys())}"

    # The locked projection on the committed fixture — AUDIT ANCHOR carried over verbatim;
    # only the READ PATH changes (findings rows → queue items via error_code + doc_num).
    assert {(item["error_code"], item["doc_num"]) for item in queue} == _EXPECTED_FINDINGS


# ── 2. ReviewInputs gains an optional reader field (no-reader callers unaffected) ──

def test_review_inputs_reader_defaults_none():
    """``ReviewInputs`` constructed with ONLY ``line_source`` has ``reader is None`` (existing
    callers stay byte-compatible), and a supplied reader is stored verbatim."""
    inputs = engine_review.ReviewInputs(line_source=lambda: [])
    assert inputs.reader is None

    sentinel = object()
    with_reader = engine_review.ReviewInputs(line_source=lambda: [], reader=sentinel)
    assert with_reader.reader is sentinel


# ── 3. review() forwards inputs.reader into run_chain (None on the default path) ──

class _SpyStop(Exception):
    """Short-circuit sentinel: stop review() at the run_chain call (no PDF/bundle). review()
    catches only GateFailure, so this propagates cleanly."""


def test_review_threads_reader_into_run_chain(monkeypatch):
    """review() must pass inputs.reader through to run_chain — and the default (no reader)
    forwards reader=None (the SAP byte-identity guarantee)."""
    captured: dict = {}

    def spy_run_chain(*args, **kwargs):
        captured.clear()
        captured.update(kwargs)
        raise _SpyStop()

    monkeypatch.setattr("engine.review.run_chain", spy_run_chain)

    fake_cfg = SimpleNamespace(client_id="xero_demo")
    period = {"start": "2026-04-01", "end": "2026-06-30"}

    # (a) an injected reader is forwarded verbatim.
    sentinel_reader = object()
    inputs = engine_review.ReviewInputs(line_source=lambda: [], reader=sentinel_reader)
    with pytest.raises(_SpyStop):
        engine_review.review(fake_cfg, period, inputs)
    assert captured.get("reader", "MISSING") is sentinel_reader

    # (b) the default (no reader) forwards reader=None — byte-identical to today's SAP path.
    default_inputs = engine_review.ReviewInputs(line_source=lambda: [])
    with pytest.raises(_SpyStop):
        engine_review.review(fake_cfg, period, default_inputs)
    assert captured.get("reader", "MISSING") is None


# ── 4. ADDITIVE lock: format-routing leaves the synthetic extract path coverage-only ──

def test_synthetic_upload_stays_coverage_only_under_routing(client: TestClient, tmp_path: Path):
    """A synthetic documents/business_partners/listing .xlsx (NOT a Xero F5 workbook) still
    lands on the UNCHANGED ExtractChainReader coverage-only path: EXACTLY the 4-key coverage
    set, source_kind=="extract_upload", and NO findings key."""
    assert _FROZEN_EXTRACT_DIR.is_dir(), f"frozen extract fixture dir missing: {_FROZEN_EXTRACT_DIR}"
    out = tmp_path / "synthetic_export.xlsx"
    _synth.export_xlsx(_FROZEN_EXTRACT_DIR, out)

    resp = client.post(
        "/review/upload?filename=synthetic_export.xlsx", content=out.read_bytes()
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert set(body.keys()) == {
        "source_kind",
        "validation_status",
        "disclaimer",
        "coverage_status",
    }
    assert body["source_kind"] == "extract_upload"
    assert "findings" not in body
