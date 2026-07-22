"""tests/test_b3a2_fingerprint_always_uploads.py -- B3a-2 (Xero upload adjudication) FAILING-FIRST.

BUILD ID: t-b3a2-xero-adjudication. Written BEFORE the implementation; these MUST fail today
for the RIGHT reason -- ``api.viewmodel.serialize_xero_queue`` only stamps a fingerprint when a
NON-empty decision store is threaded in (``decision_entries`` truthy). An empty store leaves
every detect row's ``fingerprint`` at None, so the upload panel cannot POST a first-ever
decision keyed on the row's own fingerprint. B3a-2's "fingerprint-always" enabler makes
``serialize_xero_queue`` compute + emit ``compute_finding_fingerprint(issue)`` on EVERY detect
row unconditionally (store-independent), across all three upload ``source_kind``s
(xero_f5_upload / extract_review / xero_sales_upload). Ledger-recon rows
(``serialize_ledger_recon_queue``, finding_id ``ledger_recon:*``) DELIBERATELY keep
fingerprint None -- no counterparty; #46 territory.

THREE-TIMES RULE (prompt + code + THIS test): the "every detect row carries its deterministic
fingerprint regardless of store contents" invariant is pinned in the panel prompt/spec, will be
enforced in ``serialize_xero_queue`` code, and is asserted here. Ledger-recon rows staying
un-fingerprinted is the backend half of the "no-silent-dead-buttons" rule (the FE half lives in
frontend/src/test/NonAdjudicableRow.test.tsx).

WHAT FAILS TODAY AND WHY (do NOT weaken any existing pin -- Terry's
tests/test_decision_reapply_upload.py stays the F5 red test; this file never duplicates its
exact assertions):
  * A1 F5 / A1 extract endpoints -- every detect row's fingerprint is None today; the
    ``== compute_finding_fingerprint(...)`` assertion fails.
  * A1 serialize (all source_kinds, incl. the SALES-branch function) -- with empty
    ``decision_entries`` the row carries fingerprint None today.
  * A2 mixed F5+ledger -- detect rows fingerprint None today (ledger rows None both today and
    after; asserted for the backend no-dead-button half).
  * A3 extract persist+reapply -- the row's fingerprint is None today, so POST /decision 422s on
    the ``sha256:`` prefix guard (api/app.py) and the re-apply never runs.

BLOCKING DISCOVERY (reported to the parent agent, NOT improvised around): the committed Xero
SALES fixture (tests/fixtures/xero-sales-export/*.xlsx) yields NO detect findings -- see
tests/test_xero_sales_upload.py ("the clean synthetic fixture yields no E-check findings"). An
endpoint-level A1/A3 assertion over sales detect rows would therefore be VACUOUS (nothing to
iterate). The sales-branch fingerprint-always property is pinned instead via the DIRECT
``serialize_xero_queue`` test below -- the exact function ``_xero_sales_review_response`` calls --
which fails today for the right reason without depending on the empty fixture. A sales endpoint
persist+reapply test is intentionally NOT written (no detect row to take from an empty queue).

Mirrors tests/test_decision_reapply_upload.py's hermetic pattern: engine PDF dir + audit root +
decision store all redirected to tmp, dummy SAP creds, and the per-upload fresh-audit-subdir
trick (seal.run_ts has seconds resolution -> two uploads in one second collide on one read-only
bundle dir; sidestepped per-call, never patched in the engine). SAP off, no tokens, hermetic.
"""
from __future__ import annotations

import importlib.util
import itertools
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from agent.decision_ledger import compute_finding_fingerprint
from api.app import app
from api.viewmodel import serialize_xero_queue

# Each upload gets its OWN audit subdir (see the module docstring / Terry's file).
_UPLOAD_SEQ = itertools.count()

_REPO_ROOT = Path(__file__).resolve().parents[1]

_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_F5_NAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

_SALES_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
    / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
)
_SALES_NAME = "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"

_RF_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-real-format"
_RF_F5 = _RF_DIR / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_RF_LEDGER = _RF_DIR / "AgentAssist_-_Account_Transactions.xlsx"

_FROZEN_EXTRACT_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Engine PDF dir + audit root + decision store all redirected to tmp; dummy SAP creds.

    Mirrors tests/test_decision_reapply_upload.py's ``hermetic`` fixture EXACTLY (incl. the
    ``agent.decision_store._DECISIONS_ROOT`` redirect) so first-ever decisions persist to a
    throwaway store, never the repo.
    """
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    return tmp_path


def _synth_extract_bytes(tmp_path: Path) -> bytes:
    """A synthetic (NON-Xero) extract .xlsx -- local importlib load of the committed exporter
    (tests/ is not a package). Mirrors test_extract_engine_upload.py / test_ledger_recon_upload_wiring.py."""
    spec = importlib.util.spec_from_file_location(
        "b3a2_synth_export", _REPO_ROOT / "tests" / "synth_extract_export.py"
    )
    synth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(synth)
    out = tmp_path / "synthetic_export.xlsx"
    synth.export_xlsx(_FROZEN_EXTRACT_DIR, out)
    return out.read_bytes()


def _post_upload(client: TestClient, files: dict) -> dict:
    """POST /review/upload with a fresh audit subdir (per-upload; see module docstring)."""
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"
    resp = client.post("/review/upload", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _detect_rows(queue: list[dict]) -> list[dict]:
    return [r for r in queue if str(r.get("finding_id", "")).startswith("detect:")]


def _ledger_rows(queue: list[dict]) -> list[dict]:
    return [r for r in queue if str(r.get("finding_id", "")).startswith("ledger_recon:")]


def _assert_fingerprint_always(row: dict) -> None:
    """The B3a-2 enabler, asserted on ONE detect row. Reads ``vendor`` as the counterparty
    (flatten_finding_card lifts card_name -> vendor), exactly as Terry's file does."""
    expected = compute_finding_fingerprint(
        {"error_code": row["error_code"], "card_name": row["vendor"]}
    )
    # FAILS TODAY: the row carries fingerprint None on an empty store (None != "sha256:...").
    assert row["fingerprint"] == expected, (
        "fingerprint-always: every detect row must carry its computed fingerprint regardless "
        "of decision-store contents (B3a-2 enabler)"
    )
    assert isinstance(row["fingerprint"], str) and row["fingerprint"].startswith("sha256:")
    assert row["demoted"] is False
    assert row["prior_dispositions"] == []


# -- A1 (endpoint) -- empty store, F5 branch: every detect row fingerprinted ---------------

def test_a1_empty_store_f5_fingerprints_every_detect_row(client, hermetic):
    assert _F5_FIXTURE.is_file(), f"committed Xero F5 fixture missing: {_F5_FIXTURE}"
    body = _post_upload(client, {"file": (_F5_NAME, _F5_FIXTURE.read_bytes())})

    assert body["source_kind"] == "xero_f5_upload"
    assert body["validation_status"] == "unvalidated"
    rows = _detect_rows(body["queue"])
    assert rows, "the F5 fixture must yield detect rows (E2/E3/E4)"
    for row in rows:
        _assert_fingerprint_always(row)


# -- A1 (endpoint) -- empty store, general-extract branch: every detect row fingerprinted ---

def test_a1_empty_store_extract_fingerprints_every_detect_row(client, hermetic, monkeypatch):
    monkeypatch.delenv("AGENTASSIST_EXTRACT_ENGINE", raising=False)  # default = ON
    body = _post_upload(client, {"file": ("export.xlsx", _synth_extract_bytes(hermetic))})

    assert body["source_kind"] == "extract_review"
    assert body["validation_status"] == "unvalidated"
    rows = _detect_rows(body["queue"])
    assert rows, "the synthetic extract must yield detect rows"
    for row in rows:
        _assert_fingerprint_always(row)


# -- A1 (direct serialize) -- the SHARED enabler across all three source_kinds --------------
# This is the SALES-branch pin (the committed sales fixture has no detect findings, so an
# endpoint assertion would be vacuous -- see the BLOCKING DISCOVERY note). serialize_xero_queue
# is the exact function _xero_sales_review_response / _xero_f5_review_response /
# _extract_review_response all call. With an EMPTY store (decision_entries falsy) the row must
# STILL carry its fingerprint. FAILS TODAY: the empty-store path leaves fingerprint None.

@pytest.mark.parametrize(
    "label, issue",
    [
        ("f5_like", {"error_code": "E4", "doc_num": "BILL-3002", "card_name": "OldRate Supplies Pte Ltd",
                     "description": "stale-rate", "doc_date": "2026-05-11"}),
        ("extract_like", {"error_code": "E3", "doc_num": "INV-2002", "card_name": "Local Trader Pte Ltd",
                          "description": "SR carrying no tax", "doc_date": "2026-05-02"}),
        ("sales_like", {"error_code": "E2", "doc_num": "INV-2003", "card_name": "Overseas Buyer Pte Ltd",
                        "description": "ZR carrying tax", "doc_date": "2026-05-03"}),
    ],
)
def test_a1_serialize_xero_queue_fingerprints_on_empty_store(label, issue):
    # Falsy decision_entries (None -> no store / empty store): today a STRUCTURAL no-op that
    # leaves the row un-fingerprinted. B3a-2 makes it fingerprint unconditionally.
    rows = serialize_xero_queue([issue], decision_entries=None)
    assert len(rows) == 1, "cardinality preserved -- one issue, one row"
    row = rows[0]
    _assert_fingerprint_always(row)


# -- A2 (endpoint) -- mixed queue: detect rows fingerprinted, ledger-recon rows None ---------

def test_a2_mixed_f5_plus_ledger_detect_fingerprinted_ledger_none(client, hermetic):
    assert _RF_F5.is_file() and _RF_LEDGER.is_file(), "committed xero-real-format fixtures missing"
    body = _post_upload(
        client,
        {
            "file": (_RF_F5.name, _RF_F5.read_bytes()),
            "ledger": (_RF_LEDGER.name, _RF_LEDGER.read_bytes()),
        },
    )
    assert body["source_kind"] == "xero_f5_upload"
    assert body["validation_status"] == "unvalidated"

    detect = _detect_rows(body["queue"])
    ledger = _ledger_rows(body["queue"])
    # Both groups non-empty (real-format F5 exercises E2/E3/E4; the ledger yields recon rows).
    assert detect, "expected detect rows in the mixed queue"
    assert ledger, "expected ledger-recon rows in the mixed queue"

    # FAILS TODAY on the detect loop (fingerprint None).
    for row in detect:
        _assert_fingerprint_always(row)

    # Backend half of no-silent-dead-buttons: ledger-recon rows are NOT persistable -> None.
    # (True both today and after B3a-2; asserted so a future widening cannot pass silently.)
    for row in ledger:
        assert row["fingerprint"] is None, (
            "ledger-recon rows carry no counterparty -> deliberately un-fingerprinted (#46)"
        )


# -- A3 (endpoint) -- extract: a persisted Mark known re-applies on re-upload ----------------
# The NON-F5 twin of Terry's F5 red test (does NOT duplicate its exact assertions). The
# fingerprint is READ FROM THE ROW (never recomputed): None today, so POST /decision 422s on
# the api/app.py ``sha256:`` prefix guard and the whole flow fails at the first assert.

def test_a3_extract_decision_persists_and_reapplies(client, hermetic, monkeypatch):
    monkeypatch.delenv("AGENTASSIST_EXTRACT_ENGINE", raising=False)  # default = ON
    content = _synth_extract_bytes(hermetic)

    base = _post_upload(client, {"file": ("export.xlsx", content)})
    assert base["source_kind"] == "extract_review"
    detect = _detect_rows(base["queue"])
    assert detect, "the synthetic extract must yield detect rows to adjudicate"
    target = detect[0]

    # READ the fingerprint from the row -- do NOT recompute it. None today -> the POST 422s.
    fp = target["fingerprint"]
    resp = client.post("/decision", json={
        "client_id": "extract_demo",  # the extract branch runs under the extract_demo config
        "finding_id": target["finding_id"],
        "fingerprint": fp,
        "action": "Mark known",
        "note": "Standing accepted treatment for this line.",
        "reviewer_name": "Collin Tan",
    })
    # FAILS TODAY: fp is None -> 422 on the fingerprint 'sha256:' prefix guard.
    assert resp.status_code == 200, resp.text

    re_body = _post_upload(client, {"file": ("export.xlsx", content)})
    re_detect = _detect_rows(re_body["queue"])
    matched = [r for r in re_detect if r["fingerprint"] == fp]
    assert matched, "the marked-known finding must carry its fingerprint after re-upload"
    for row in matched:
        assert row["demoted"] is True
        assert "KNOWN_ACCEPTED" in (row["prior_dispositions"] or [])

    # Never-suppress: cardinality preserved -- the demoted row is still present.
    assert len(re_body["queue"]) == len(base["queue"])
    assert any(r["finding_id"] == target["finding_id"] for r in re_detect)
