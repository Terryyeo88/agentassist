"""tests/test_decisions_read_route.py — C-6(b) backend, FAILING-FIRST.

BUILD ID: t-c6b-decision-read-route. Written BEFORE the implementation; MUST fail today for
the RIGHT reason — ``GET /decisions/{client_id}`` is not registered, so every request 404s.

WHY THIS ROUTE EXISTS. C-6(a) put ``reviewer`` + ``timestamp`` on the ``POST /decision``
RESPONSE, so a decision made in this browser could name who adjudicated it and when. It did
nothing for a decision made yesterday: ``load_decision_entries`` was called server-side at
eight sites (api/app.py) and every one of them folded entries into some OTHER artefact — a
re-applied queue key, a signed PDF's adjudication view, a superseded COUNT. Nothing returned
the entries themselves, so no surface could list prior decisions and the Xero Audit view was
empty on load BY NECESSITY (frontend/src/components/XeroAuditView.tsx). This route closes
that hole and nothing else: it is the READ half of a store that already had a write half.

SCOPE IS THE CLIENT, NOT A SESSION — and that is the store's decision, not a preference. The
store is laid out ``decisions/<client_id>/ledger.jsonl`` (agent/decision_store.py:11) and
``load_decision_entries`` accepts a ``client_id`` and nothing else. Entries carry no
``review_id``; there is no session index. A session-scoped read would need new indexing
inside ``agent/``, which this slice does not touch.

HARD INVARIANTS PINNED HERE (three-times rule — the api/app.py contract comment, the route
code, and THIS test):
  * EXACT KEY SET — the envelope is EXACTLY ``DECISIONS_READ_KEYS``.
  * FROZEN FLAGS — ``validation_status="unvalidated"`` and the SAME disclaimer constant the
    write half and the review payload use. Reading decisions is not a verdict either.
  * VERBATIM ENTRIES (§8, no fabricated values) — what the route returns is what is on disk,
    key for key, order for order. Not a projection, not a re-derivation, not a re-format.
  * SAME VALIDATION AS THE WRITE — a client_id that ``POST /decision`` refuses with 422 is
    refused by the read with 422. One rule, both directions; a store key is a directory name.
  * READ-ONLY — a GET creates nothing on disk, not even for a client that has no store, and
    the append-only chain still ``verify()``s afterwards.
  * NO ``finding_id`` IN A STORED ENTRY — pinned deliberately (see the test), because the
    later frontend slice must not assume a column the record cannot fill.

SAP off, no tokens, hermetic (decisions land only on tmp_path).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.decision_store import load_decision_entries, load_decision_ledger
from api.app import app
from api.viewmodel import DISCLAIMER

_FP = "sha256:" + "b" * 64
_CLIENT = "acme"

#: The single-source read envelope. Mirrors DECISIONS_READ_KEYS in api/app.py.
DECISIONS_READ_KEYS: tuple[str, ...] = (
    "client_id",
    "entries",
    "chain_length",
    "validation_status",
    "disclaimer",
)

#: Every key ``dataclasses.asdict(AdjudicationEntry)`` writes (agent/decision_ledger.py).
#: ``reviewer`` and ``timestamp`` are the two C-6(a) surfaced; they were ALWAYS stored — C-6(a)
#: only stopped hiding them on the write response, and this route stops hiding them on read.
STORED_ENTRY_KEYS: frozenset[str] = frozenset({
    "entry_id",
    "fingerprint",
    "disposition",
    "reviewer",
    "reason",
    "period",
    "timestamp",
    "prev_hash",
    "entry_hash",
    "fingerprint_version",
})


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def decisions_root(tmp_path, monkeypatch):
    """Redirect the durable decision store to tmp_path (mirrors the write-half's fixture)."""
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path)
    return tmp_path


def _post(client: TestClient, **overrides) -> dict:
    """Record one decision through the REAL write path — never a hand-built store file.

    The read route is only worth anything if it returns what the write route actually wrote,
    so the fixture data here is produced by POST /decision rather than asserted into place.
    """
    payload = {
        "client_id": _CLIENT,
        "finding_id": "detect:E2:INV-1",
        "fingerprint": _FP,
        "action": "Accept",
        "note": "",
        "reviewer_name": "Collin Tan",
    }
    payload.update(overrides)
    resp = client.post("/decision", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Empty store — 200 and an empty list, never a 404 ─────────────────────────────────

def test_empty_store_returns_200_and_empty_list(client, decisions_root):
    """No decisions yet is a FACT about the client, not a missing resource.

    ``load_decision_entries`` already returns ``[]`` for an absent file
    (agent/decision_store.py:77-78), so the empty case needs no special-casing — and a 404
    here would make "this client has decided nothing" indistinguishable from "this client
    does not exist", which is exactly the kind of ambiguity the surface must not inherit.
    """
    resp = client.get(f"/decisions/{_CLIENT}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entries"] == []
    assert body["chain_length"] == 0
    assert body["client_id"] == _CLIENT


# ── Envelope: exact key set + frozen flags ───────────────────────────────────────────

def test_envelope_is_exactly_the_pinned_key_set_with_frozen_flags(client, decisions_root):
    _post(client)
    body = client.get(f"/decisions/{_CLIENT}").json()

    assert set(body.keys()) == set(DECISIONS_READ_KEYS)
    assert body["validation_status"] == "unvalidated"
    assert body["disclaimer"] == DISCLAIMER


# ── The entries are the stored records, verbatim and in order ────────────────────────

def test_returns_stored_entries_verbatim_oldest_first(client, decisions_root):
    """Byte-for-byte the store's own records — no projection, no re-derivation.

    Two decisions over the same fingerprint (a change of mind is a NEW append, never a
    rewrite), so this also pins ORDER: the store is append-only and oldest-first
    (decision_store.py:75), and a read that reordered them would misrepresent which
    adjudication is current.
    """
    _post(client, action="Accept")
    _post(client, action="Decline", note="changed my mind")

    body = client.get(f"/decisions/{_CLIENT}").json()
    on_disk = load_decision_entries(_CLIENT, root=decisions_root)

    assert len(on_disk) == 2, "the write half must have appended twice"
    assert body["entries"] == on_disk, "the route must return the stored records verbatim"
    assert body["chain_length"] == 2

    # Oldest first, and the UI verb survives in each record's reason.
    assert body["entries"][0]["reason"].startswith("[Accept]")
    assert body["entries"][1]["reason"].startswith("[Decline]")
    # The chain links in the order returned — entry N+1 continues from entry N.
    assert body["entries"][1]["prev_hash"] == body["entries"][0]["entry_hash"]


def test_each_entry_carries_the_full_stored_key_set(client, decisions_root):
    _post(client)
    [entry] = client.get(f"/decisions/{_CLIENT}").json()["entries"]
    assert set(entry.keys()) == set(STORED_ENTRY_KEYS)


# ── C-6(a)'s two values survive the READ path, pinned to the persisted record ─────────

def test_reviewer_and_timestamp_are_the_persisted_ledger_values(client, decisions_root):
    """The point of the whole slice: WHO and WHEN, for a decision this browser never made.

    Pinned to the on-disk record character for character. A read that re-stamped
    ``timestamp`` with the read time, or substituted a caller-supplied reviewer, would be
    this endpoint's guess at what happened rather than the ledger's record of it — and both
    fields are hashed into the append-only chain, so the stored value is the tamper-evident
    one. Same rule C-6(a) pinned on the write response, now on the read.
    """
    written = _post(client, reviewer_name="Collin Tan")
    [entry] = client.get(f"/decisions/{_CLIENT}").json()["entries"]
    [on_disk] = load_decision_entries(_CLIENT, root=decisions_root)

    assert entry["reviewer"] == on_disk["reviewer"] == "Collin Tan"
    assert entry["timestamp"] == on_disk["timestamp"]
    # And they agree with what the write half reported for the SAME append (C-6a).
    assert entry["reviewer"] == written["reviewer"]
    assert entry["timestamp"] == written["timestamp"]
    assert entry["entry_hash"] == written["entry_hash"]


def test_stored_entry_carries_no_finding_id(client, decisions_root):
    """An honest gap, pinned so a later surface cannot assume it away.

    ``POST /decision`` accepts ``finding_id`` and echoes it back, but ``AdjudicationEntry``
    has no such field — the record is keyed on the deterministic ``fingerprint`` alone. So a
    prior-decision row read from this route can name the fingerprint and NOT the finding_id.
    The frontend slice must render that absence honestly rather than inventing a label; this
    assertion fails loudly if the stored shape ever changes underneath that decision.
    """
    _post(client, finding_id="detect:E2:INV-1")
    [entry] = client.get(f"/decisions/{_CLIENT}").json()["entries"]

    assert "finding_id" not in entry
    assert entry["fingerprint"] == _FP


# ── Same client_id rule as the write half ────────────────────────────────────────────

@pytest.mark.parametrize(
    "bad_client_id",
    [
        "Xero Demo",     # space + uppercase (the write half's pinned rejection)
        "XERO_DEMO",     # uppercase
        "xero-demo",     # hyphen is not in the alphabet
        "xero.demo",     # a dot is the traversal primitive — refused outright
        "xero..demo",    # ".." characters, routable form
        "xero%20demo",   # encoded space, decoded before routing
    ],
)
def test_malformed_client_id_is_refused_422(client, decisions_root, bad_client_id):
    """A store key is a DIRECTORY NAME, so the read validates exactly as the write does.

    ``POST /decision`` refuses ``../evil`` and ``Xero Demo`` with 422
    (tests/test_decision_endpoint_contract.py). The path-param form cannot carry a literal
    ``../evil`` — an HTTP client normalises the segment away before the request is sent — so
    the same RULE is pinned with routable values: the dot and slash characters that make a
    traversal possible are outside ``^[a-z0-9_]+$`` and are rejected before any path is built.
    """
    resp = client.get(f"/decisions/{bad_client_id}")
    assert resp.status_code == 422, resp.text


# ── Read-only, and the chain survives ────────────────────────────────────────────────

def test_read_creates_nothing_on_disk(client, decisions_root):
    """READ-NEVER-WRITE: a GET for a client with no store must not bring one into being.

    An empty directory (or an empty ledger file) left behind by a read would be this
    endpoint inventing state — and on the next read it would be indistinguishable from a
    client who had genuinely decided nothing.
    """
    resp = client.get("/decisions/never_seen_before")
    assert resp.status_code == 200, resp.text
    assert resp.json()["entries"] == []
    assert not (decisions_root / "never_seen_before").exists()
    assert list(decisions_root.iterdir()) == []


def test_chain_still_verifies_after_a_read(client, decisions_root):
    _post(client, action="Accept")
    _post(client, action="Mark known", note="standing treatment")

    assert client.get(f"/decisions/{_CLIENT}").status_code == 200
    # The read touched nothing: the append-only chain still verifies end to end.
    load_decision_ledger(_CLIENT, root=decisions_root).verify()
    assert len(load_decision_entries(_CLIENT, root=decisions_root)) == 2


# ── One client's decisions never leak into another's read ────────────────────────────

def test_clients_are_isolated(client, decisions_root):
    """The store is per-client by construction; the read must not merge across keys.

    (The known multi-tenant gap — several demo uploads sharing ONE config client_id,
    decision_store.py:26-30 — is unchanged by this route and is not what this pins. This
    pins that two DISTINCT keys stay distinct.)
    """
    _post(client, client_id="acme", reviewer_name="Collin Tan")
    _post(client, client_id="other_co", reviewer_name="Someone Else")

    acme = client.get("/decisions/acme").json()
    other = client.get("/decisions/other_co").json()

    assert acme["chain_length"] == 1
    assert other["chain_length"] == 1
    assert acme["entries"][0]["reviewer"] == "Collin Tan"
    assert other["entries"][0]["reviewer"] == "Someone Else"
    assert acme["entries"][0]["entry_id"] != other["entries"][0]["entry_id"]


# ── No SAP dependency (the write half's guarantee, held on the read) ─────────────────

def test_read_has_no_sap_dependency(client, decisions_root, monkeypatch):
    monkeypatch.delenv("SAP_USERNAME", raising=False)
    monkeypatch.delenv("SAP_PASSWORD", raising=False)
    _post(client)
    resp = client.get(f"/decisions/{_CLIENT}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["chain_length"] == 1
