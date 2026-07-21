"""tests/test_sign_upload_endpoint.py — BUILD ID t-xero-signoff, FAILING-FIRST (Contract C).

``POST /sign/upload`` — the ONE place an uploaded Xero F5 review becomes a signed working
paper + a sealed audit bundle. Written BEFORE the implementation; MUST fail today for the
RIGHT reason — the endpoint does not exist (404) and the M2 persistence split is absent
(a plain ``POST /review/upload`` still seals a bundle + renders a PDF today).

HARD INVARIANTS PINNED HERE (three-times rule — prompt + code + THIS test):
  * SIGN_UPLOAD_KEYS — the /sign/upload response is EXACTLY
    {source_kind, reviewer_name, firm_name, working_paper_path, bundle_dir,
     validation_status, disclaimer}; source_kind == "xero_f5_signed";
    validation_status == "unvalidated" (candidates, not verdicts); reviewer_name echoes the
    submitted name; working_paper_path + bundle_dir are strings at EXISTING paths.
  * M2 PERSISTENCE SPLIT — a PLAIN POST /review/upload (same fixture) leaves BOTH
    monkeypatched roots EMPTY (no PDF under _REPORTS_DIR, no bundle under _AUDIT_ROOT); only
    POST /sign/upload produces BOTH. The plain-upload response shape is unchanged (the 5-key
    literal, pinned here as a NEW literal).
  * SYSTEM-NEVER-SIGNS — an empty/whitespace reviewer_name is refused (422); a non-Xero-F5
    file is refused (422).
  * SAP-CREDS-ABSENT — /sign/upload runs under the xero_demo config, which needs NO SAP
    creds: with SAP_USERNAME/SAP_PASSWORD unset it still returns 200.

Mirrors tests/test_xero_engine_upload.py (hermetic engine fixture: engine PDF dir + audit
root + decision store redirected to tmp; dummy SAP creds) and the per-call fresh _AUDIT_ROOT
counter from tests/test_decision_reapply_upload.py:35-41,71-73 (same-second seal collision on
Windows) — sidestepped per-call here, NEVER patched in the engine (box-isolation). SAP off,
no anthropic, no tokens, hermetic.
"""
from __future__ import annotations

import itertools
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from api.app import app

# Each engine-running request gets its OWN audit root (seal's run_ts is seconds-resolution;
# two seals in one second collide on one read-only bundle dir). Pre-existing engine property,
# sidestepped per-call — never patched in the engine.
_UPLOAD_SEQ = itertools.count()

_REPO_ROOT = Path(__file__).resolve().parents[1]
_XERO_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_XERO_FILENAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

# The exact /sign/upload response contract.
SIGN_UPLOAD_KEYS = {
    "source_kind", "reviewer_name", "firm_name", "working_paper_path",
    "bundle_dir", "validation_status", "disclaimer",
}
# The plain /review/upload Xero-branch top-level shape (pinned here as a NEW literal; the
# existing contract test's literal stays untouched).
XERO_UPLOAD_TOP_KEYS = {"source_kind", "validation_status", "disclaimer", "coverage_status", "queue"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Engine PDF dir + audit root + decision store redirected to tmp; dummy SAP creds."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    return tmp_path


def _bump_audit() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"


def _review_upload(client: TestClient, file_bytes: Optional[bytes] = None):
    _bump_audit()
    return client.post(
        "/review/upload",
        files={"file": (_XERO_FILENAME, file_bytes if file_bytes is not None else _XERO_FIXTURE.read_bytes())},
    )


def _sign_upload(
    client: TestClient,
    reviewer_name: str = "Collin",
    firm_name: Optional[str] = None,
    file_bytes: Optional[bytes] = None,
    filename: str = _XERO_FILENAME,
):
    _bump_audit()
    data = {"reviewer_name": reviewer_name}
    if firm_name is not None:
        data["firm_name"] = firm_name
    return client.post(
        "/sign/upload",
        data=data,
        files={"file": (filename, file_bytes if file_bytes is not None else _XERO_FIXTURE.read_bytes())},
    )


# ── C1. Happy path — 200, exact key set, real signed artefacts on disk ────────────────

def test_sign_upload_happy_path(client, hermetic):
    assert _XERO_FIXTURE.is_file(), f"committed Xero fixture missing: {_XERO_FIXTURE}"
    resp = _sign_upload(client, reviewer_name="Collin")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert set(body.keys()) == SIGN_UPLOAD_KEYS
    assert body["source_kind"] == "xero_f5_signed"
    assert body["validation_status"] == "unvalidated"
    assert body["reviewer_name"] == "Collin"
    assert body["firm_name"] == ""  # default when the optional form field is omitted

    wp = Path(body["working_paper_path"])
    assert wp.suffix.lower() == ".pdf"
    assert wp.is_file()

    bundle_dir = Path(body["bundle_dir"])
    assert bundle_dir.is_dir()
    assert (bundle_dir / "manifest.json").is_file()
    assert (bundle_dir / "compile-output.json").is_file()


# ── C2. System never signs — empty reviewer / non-Xero file are refused (422) ─────────

def test_sign_upload_rejects_empty_reviewer(client, hermetic):
    resp = _sign_upload(client, reviewer_name="   ")
    assert resp.status_code == 422, resp.text


def test_sign_upload_rejects_non_xero_file(client, hermetic):
    # A .xlsx-suffixed blob that is NOT a Xero F5 workbook (is_xero_f5_workbook self-guards
    # to False on an unreadable/off-format upload) is a client-input error, never a sign.
    resp = _sign_upload(client, reviewer_name="Collin", file_bytes=b"not a real workbook")
    assert resp.status_code == 422, resp.text


# ── C3. M2 persistence split — plain upload persists NOTHING; sign persists BOTH ──────

def test_plain_review_upload_persists_nothing_then_sign_persists_both(client, hermetic):
    tmp_path = hermetic

    # Plain review upload: M2 skip → no PDF, no bundle.
    plain = _review_upload(client)
    assert plain.status_code == 200, plain.text
    plain_body = plain.json()
    # Plain-upload response shape unchanged (NEW literal in this file).
    assert set(plain_body.keys()) == XERO_UPLOAD_TOP_KEYS
    assert plain_body["source_kind"] == "xero_f5_upload"
    assert plain_body["validation_status"] == "unvalidated"

    reports_dir = tmp_path / "reports"
    assert (not reports_dir.exists()) or not any(reports_dir.iterdir()), (
        "plain /review/upload must not render a PDF (M2 skip)"
    )
    # The audit subdir used by the plain call was never created (seal not called).
    assert not _seal._AUDIT_ROOT.exists(), "plain /review/upload must not seal a bundle (M2 skip)"

    # Sign upload: now BOTH artefacts exist.
    signed = _sign_upload(client, reviewer_name="Collin")
    assert signed.status_code == 200, signed.text
    signed_body = signed.json()
    assert Path(signed_body["working_paper_path"]).is_file()
    assert Path(signed_body["bundle_dir"]).is_dir()
    # A PDF now exists under the redirected reports dir.
    assert reports_dir.exists() and any(reports_dir.iterdir())


# ── C4. SAP creds absent — /sign/upload still 200 (xero_demo needs no creds) ──────────

def test_sign_upload_ok_without_sap_creds(client, hermetic, monkeypatch):
    monkeypatch.delenv("SAP_USERNAME", raising=False)
    monkeypatch.delenv("SAP_PASSWORD", raising=False)
    resp = _sign_upload(client, reviewer_name="Collin")
    assert resp.status_code == 200, resp.text
    assert resp.json()["source_kind"] == "xero_f5_signed"
