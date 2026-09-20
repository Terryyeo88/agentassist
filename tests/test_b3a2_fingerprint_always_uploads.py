"""tests/test_b3a2_fingerprint_always_uploads.py -- B3a-2 (Xero upload adjudication) FAILING-FIRST.

BUILD ID: t-b3a2-xero-adjudication. Written BEFORE the implementation; these MUST fail today
for the RIGHT reason -- ``api.viewmodel.serialize_xero_queue`` only stamps a fingerprint when a
NON-empty decision store is threaded in (``decision_entries`` truthy). An empty store leaves
every detect row's ``fingerprint`` at None, so the upload panel cannot POST a first-ever
decision keyed on the row's own fingerprint. B3a-2's "fingerprint-always" enabler makes
``serialize_xero_queue`` compute + emit ``compute_finding_fingerprint(issue)`` on EVERY detect
row unconditionally (store-independent), across all three upload ``source_kind``s
(xero_f5_upload / extract_review / xero_sales_upload). Ledger-recon rows
(``serialize_ledger_recon_queue``, finding_id ``ledger_recon:*``) originally kept fingerprint
None (no counterparty; #46 territory) -- SUPERSEDED by the Slice B amendment below.

RULE-AUTHOR AMENDMENT (t-fingerprint-v1, hand-authored -- separation of duties).
The fingerprint key WIDENED from (error_code, counterparty) to
(error_code, counterparty, doc_num) under D-2026-07-24-fingerprint-v1. The v0 pair was
DEGENERATE: two documents from one supplier carrying the same error hashed identically, so one
adjudication swept both. ``_assert_fingerprint_always`` -- the single recompute site in this
file, which every test below routes through -- now carries ``doc_num``. Nothing else in this
file changed at that time: the enabler property (fingerprint-always, store-independent) is
orthogonal to the key's composition.

RULE-AUTHOR AMENDMENT (Slice B, t-slice-b-adjudicable-rows, hand-authored by Terry
2026-09-20 -- separation of duties; PROPOSED D-id, Terry ratifies).
#46's premise -- "ledger-recon rows carry no counterparty, therefore cannot be fingerprinted"
-- is RETIRED. It assumed every fingerprint must key on a counterparty. Slice B introduces a
FAMILY -> identity-key map inside the one fingerprint function: the E-check family keeps
(error_code, counterparty, doc_num) byte-identical (no version bump, no stored decision
orphaned); ledger-recon Signal A keys on (error_code, side, period_start, period_end) so a
per-side divergence NEVER carries forward to another quarter's different divergence; Signal B
(NOT_INCLUDED) keys on (error_code, named-empty counterparty, journal reference). A Signal B
row with a BLANK reference must still carry None -- never a collapsed shared key -- and that
case is pinned in Slice B's own new test file, not here (this fixture's #14 carries a
reference). The A2 ledger loop below is INVERTED accordingly and strengthened with three
STRUCTURAL properties (non-null sha256; pairwise distinct among ledger rows; disjoint from
detect-row fingerprints). No golden literal is authored here -- values are hand-pinned later.

THREE-TIMES RULE (prompt + code + THIS test): the "every detect row carries its deterministic
fingerprint regardless of store contents" invariant is pinned in the panel prompt/spec, will be
enforced in ``serialize_xero_queue`` code, and is asserted here. The "no-silent-dead-buttons"
rule still holds in its general form -- a row is either adjudicable (non-null fingerprint) or
visibly non-adjudicable with a stated reason (FE half: frontend/src/test/NonAdjudicableRow.test.tsx).
After Slice B, ledger-recon rows on this fixture fall on the adjudicable side.

WHAT FAILS TODAY AND WHY (do NOT weaken any existing pin -- Terry's
tests/test_decision_reapply_upload.py stays the F5 red test; this file never duplicates its
exact assertions):
  * A1 F5 / A1 extract endpoints -- every detect row's fingerprint is None today; the
    ``== compute_finding_fingerprint(...)`` assertion fails.
  * A1 serialize (all source_kinds, incl. the SALES-branch function) -- with empty
    ``decision_entries`` the row carries fingerprint None today.
  * A2 mixed F5+ledger -- (historical, B3a-2) detect rows fingerprint None. (Slice B) the
    ledger-recon loop FAILS until family fingerprints land: ledger rows are None at 9d7ed1d.
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
    (flatten_finding_card lifts card_name -> vendor), exactly as Terry's file does.

    t-fingerprint-v1: ``doc_num`` joined the key, so it is recomputed here too. It is passed
    RAW -- the normaliser inside decision_ledger does the canonicalisation, and duplicating
    that here would hide a regression in the normaliser.
    """
    expected = compute_finding_fingerprint(
        {
            "error_code": row["error_code"],
            "card_name": row["vendor"],
            "doc_num": row["doc_num"],
        }
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


# -- A2 (endpoint) -- mixed queue: detect rows AND ledger-recon rows fingerprinted -----------
# AMENDED by Terry 2026-09-20 (Slice B): renamed from
# test_a2_mixed_f5_plus_ledger_detect_fingerprinted_ledger_none -- the old name would now
# describe the opposite of what is asserted.

def test_a2_mixed_f5_plus_ledger_detect_and_ledger_family_fingerprinted(client, hermetic):
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

    for row in detect:
        _assert_fingerprint_always(row)

    # AMENDED by Terry 2026-09-20 (Slice B; retires #46's premise -- see module docstring).
    # Ledger-recon rows are now fingerprinted by FAMILY keys (Signal A: side + period;
    # Signal B: journal reference), not by counterparty. On this fixture every ledger row has
    # the fields its family needs (#14 carries a reference), so every row must be adjudicable.
    # STRUCTURAL pins only -- no golden literal (values are hand-pinned separately):
    #   (1) each ledger row carries a sha256 fingerprint;
    #   (2) no two ledger rows share one (output / input / #14 never collapse together);
    #   (3) no ledger fingerprint equals any detect fingerprint (no cross-family collision).
    # FAILS at 9d7ed1d: ledger rows carry None until Slice B lands.
    for row in ledger:
        assert isinstance(row["fingerprint"], str) and row["fingerprint"].startswith("sha256:"), (
            "ledger-recon rows must carry a family-keyed fingerprint (Slice B)"
        )
    ledger_fps = [row["fingerprint"] for row in ledger]
    assert len(set(ledger_fps)) == len(ledger_fps), (
        "ledger-recon fingerprints must be pairwise distinct (no side/reference collapse)"
    )
    detect_fps = {row["fingerprint"] for row in detect}
    assert detect_fps.isdisjoint(ledger_fps), (
        "ledger-recon fingerprints must never collide with detect-row fingerprints"
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
