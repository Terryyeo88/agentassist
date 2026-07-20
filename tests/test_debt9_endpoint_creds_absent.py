"""tests/test_debt9_endpoint_creds_absent.py — DEBT-9 ENDPOINT-LEVEL regression PINS.

DEBT-9 (the ``sap_b1`` connection block + SAP credential env vars are optional for
non-SAP / file-import clients) is ALREADY FIXED on master (commit 8daf757; the loader
gate at config/loader.py:294-363 keys the requirement off ``source_system``). The
loader-level behaviour is pinned by tests/test_debt9_sap_decouple.py.

What NO existing test proves is the DEBT-9 fix END-TO-END at the HTTP boundary: that the
``POST /review/upload`` Xero-F5 engine path (which lazily calls
``load_client_config("xero_demo")`` inside ``_xero_f5_review_response``) runs to a 200
with the SAP credential env vars TRULY ABSENT from the process environment. Every existing
upload test hides this: tests/conftest.py:17-20 ``setdefault``s SAP_USERNAME/SAP_PASSWORD
session-wide, and tests/test_xero_engine_upload.py additionally ``monkeypatch.setenv``s
dummies via its ``hermetic_engine`` fixture. So the endpoint is only ever exercised WITH
creds present — the DEBT-9 promise ("a Xero client needs no SAP creds") is asserted at the
loader unit level but never at the wire.

HONEST STATUS — these are REGRESSION PINS of behaviour that ALREADY EXISTS on master, so
they are EXPECTED TO PASS IMMEDIATELY. They are still authored test-first per the SOP (the
gap is a missing pin, not a missing feature). They lock the endpoint-level DEBT-9 invariant
against a future re-introduction of a hard SAP-cred dependency on the Xero path, and pin the
direction (the SAP path is NOT weakened: it still raises loudly when creds are absent).

Test map:
  1  Xero-F5 upload → HTTP 200 with SAP_USERNAME/SAP_PASSWORD deleted from os.environ
     (delenv, then sanity-guard that the process env truly lacks both at call time); the
     locked xero_f5_upload response shape (5 keys, source_kind, findings queue present).
  2  DIRECTION PIN: the SAP-sourced config (sbodemosg) STILL raises ConfigError naming the
     missing env var(s) when the same creds are absent — DEBT-9 did not weaken the SAP path.
  3  self-contained loader check: with creds absent, the non-SAP xero_demo config LOADS and
     carries empty-string SAP connection fields (endpoint-adjacent mirror of decouple T1).

Pure stdlib + pytest + fastapi.testclient. No anthropic/reasoning/documents/agent import.
SAP off, no tokens, no network (check_connectivity=False everywhere), hermetic.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.viewmodel import QUEUE_ITEM_KEYS

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The identical committed real-FORMAT Xero IRAS-F5 export fixture (synthetic transactions)
# used by tests/test_xero_engine_upload.py — reuse the same path verbatim.
_XERO_FIXTURE = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_XERO_FILENAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

# The SAP credential env vars the SAP-sourced client (sbodemosg.yaml) references, and the
# only SAP creds any client config references. xero_demo.yaml carries NO sap_b1 block, so it
# references NO credential env var — deleting these two is the complete "SAP creds absent"
# state for both configs exercised here.
_SAP_CRED_VARS = ("SAP_USERNAME", "SAP_PASSWORD")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def no_sap_creds_hermetic_engine(tmp_path, monkeypatch):
    """DEBT-9 harness: DELETE the SAP creds (vs the existing fixture that SETS dummies) and
    redirect the engine's PDF dir + the audit bundle root to tmp so the full review() render
    never litters the worktree. NO SAP call is made on the Xero path (the reader short-circuits
    every read); this fixture proves the endpoint needs no SAP creds to complete."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    for var in _SAP_CRED_VARS:
        monkeypatch.delenv(var, raising=False)


# ── 1. endpoint completes with the SAP creds ABSENT from the environment ──

def test_xero_upload_succeeds_with_no_sap_creds_in_env(
    client: TestClient, no_sap_creds_hermetic_engine
):
    """POST the real Xero F5 fixture with SAP_USERNAME/SAP_PASSWORD deleted → HTTP 200 and the
    locked xero_f5_upload contract. Sanity-guards that the process env TRULY lacks both vars at
    call time (so the 200 is not a stale-env artifact)."""
    # Sanity guard: the delenv actually took effect on the real process environment.
    for var in _SAP_CRED_VARS:
        assert var not in os.environ, f"expected {var} absent from os.environ, present"

    assert _XERO_FIXTURE.is_file(), f"committed Xero fixture missing: {_XERO_FIXTURE}"

    resp = client.post(
        "/review/upload", files={"file": (_XERO_FILENAME, _XERO_FIXTURE.read_bytes())}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The locked xero_f5_upload response shape (mirrors test_xero_engine_upload.py test 1).
    assert set(body.keys()) == {
        "source_kind",
        "validation_status",
        "disclaimer",
        "coverage_status",
        "queue",
    }
    assert body["source_kind"] == "xero_f5_upload"
    assert body["validation_status"] == "unvalidated"

    # findings surfaced as a non-empty queue of locked-shape items — proof the engine ran to
    # completion with the SAP creds absent.
    queue = body["queue"]
    assert isinstance(queue, list) and queue, "expected a non-empty findings queue"
    for item in queue:
        assert set(item.keys()) == set(QUEUE_ITEM_KEYS), (
            f"queue item keys drifted: {set(item.keys())}"
        )

    # The creds were still absent at (and after) the call — no hidden re-provisioning.
    for var in _SAP_CRED_VARS:
        assert var not in os.environ, f"expected {var} still absent after call, present"


# ── 2. DIRECTION PIN: the SAP path is NOT weakened — it still raises when creds absent ──

def test_sap_sourced_config_still_requires_creds_when_absent(monkeypatch):
    """DEBT-9 gated the requirement on source_system; it did NOT drop it for SAP-sourced
    clients. With the SAP creds absent, load_client_config("sbodemosg") must still raise
    ConfigError whose message names the missing env var(s)."""
    from config.loader import ConfigError, load_client_config

    for var in _SAP_CRED_VARS:
        monkeypatch.delenv(var, raising=False)
    for var in _SAP_CRED_VARS:
        assert var not in os.environ, f"expected {var} absent from os.environ, present"

    with pytest.raises(ConfigError, match="SAP_USERNAME"):
        load_client_config("sbodemosg", check_connectivity=False)


# ── 3. self-contained: the non-SAP xero_demo config loads with empty SAP fields ──

def test_xero_demo_config_loads_with_empty_sap_fields_when_creds_absent(monkeypatch):
    """Endpoint-adjacent mirror of decouple T1: with the SAP creds absent, the file-import
    xero_demo config (the exact config the endpoint loads) LOADS and its SAP connection fields
    default to empty strings (never contacted)."""
    from config.loader import load_client_config

    for var in _SAP_CRED_VARS:
        monkeypatch.delenv(var, raising=False)

    cfg = load_client_config("xero_demo", check_connectivity=False)
    assert cfg.source_system == "xero"
    assert cfg.service_layer_url == "" and cfg.company_db == ""
    assert cfg.username == "" and cfg.password == ""
