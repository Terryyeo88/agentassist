"""tests/test_document_route_namespace.py — D-34: GET /document/{doc_ref} namespace safety.

Run-proven defect (2026-07-29, HEAD e60ade2): GET /document/BILL-3002 returned 200 with
sha256 98d08a5e… = tests/fixtures/documents/INV-3002.pdf ("Office Essentials Pte Ltd,
INV-3002, 2024-08-20") — while the reference names the Xero corpus document BILL-3002.pdf
(sha 9107458253…, "OldRate Supplies Pte Ltd, BILL-3002, 2026-04-22"). The digits shim
(findall(r"\\d+") -> last run -> INV-<n>.pdf) erased the corpus namespace before the
provider resolved in a different one. Wrong-document-with-200 is the one state neither
the viewer nor the route can detect; the fix makes the route REFUSE rather than
substitute.

The predicate (M3, from the D-34 measurement): a reference is served ONLY when the full
reference string is the document's own identity — the bare doc_num form ("3005") or the
invoice-number form ("INV-3005", the fixture's filename stem and face value). Any
other-shaped reference (BILL-*, Q-*, MJ-*, #N, …) is refused with the SAME honest 404
body as an absent document — a refused reference and an absent one must be
indistinguishable to the client (T4).

T3's literals are authored from the M1 measurement table (all sixteen refs that resolve
correctly today, sha-verified against disk); they pin that D-34 loses none of them.

These tests run over the REAL committed corpus (no monkeypatch): the defect is a
cross-corpus property and the committed fixtures are the two corpora.
"""
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

import api.app as app_module

client = TestClient(app_module.app)

_REPO = Path(__file__).resolve().parent.parent
_SAP_INV_3002 = _REPO / "tests" / "fixtures" / "documents" / "INV-3002.pdf"

_HONEST_404_BODY = {"detail": "No source document on file"}

# M1/M2 "RESOLVES CORRECTLY" — every ref that serves its own document today, with the
# sha256 of the bytes served at measurement time (2026-07-29, HEAD e60ade2). D-34 must
# refuse NONE of these and change NO byte.
_RESOLVES_CORRECTLY: dict[str, str] = {
    "3001": "eb88ab82b261",
    "3002": "98d08a5e595d",
    "3003": "bd1eb26db0f5",
    "3004": "d88b5f3fdcf9",
    "3005": "3946364afe68",
    "3006": "e46ea2397e1a",
    "3007": "7c9691964978",
    "3008": "7514cb364410",
    "INV-3001": "eb88ab82b261",
    "INV-3002": "98d08a5e595d",
    "INV-3003": "bd1eb26db0f5",
    "INV-3004": "d88b5f3fdcf9",
    "INV-3005": "3946364afe68",
    "INV-3006": "e46ea2397e1a",
    "INV-3007": "7c9691964978",
    "INV-3008": "7514cb364410",
}


def test_t1_bill_3002_never_serves_the_sap_fixture_bytes():
    """T1: GET /document/BILL-3002 must NOT return tests/fixtures/documents/INV-3002.pdf.

    Asserted on the SHA, not the status: the defect is the CONTENT — a status-only pin
    would let a future digits shim reintroduce the substitution silently."""
    sap_sha = hashlib.sha256(_SAP_INV_3002.read_bytes()).hexdigest()
    resp = client.get("/document/BILL-3002")
    if resp.status_code == 200:
        served_sha = hashlib.sha256(resp.content).hexdigest()
        assert served_sha != sap_sha, (
            "GET /document/BILL-3002 served the SAP fixture INV-3002.pdf "
            f"(sha {sap_sha[:12]}) — a different corpus's document substituted "
            "for a Xero reference (the D-34 defect)"
        )


def test_t2_unresolvable_xero_ref_gets_the_same_honest_404():
    """T2: a Xero-shaped reference the SAP corpus cannot serve -> 404 with the SAME body
    every other unresolvable reference returns (body asserted, not just the code)."""
    resp = client.get("/document/BILL-3002")
    assert resp.status_code == 404
    assert resp.json() == _HONEST_404_BODY
    # And identical to a reference that never had any document anywhere:
    absent = client.get("/document/BILL-9999")
    assert absent.status_code == 404
    assert absent.json() == resp.json()


def test_t3_every_legitimately_resolving_ref_is_unchanged():
    """T3: all sixteen M2 RESOLVES-CORRECTLY refs still return 200 with the same sha256
    as the D-34 measurement run. Literals authored from M1's printed table."""
    for ref, sha12 in _RESOLVES_CORRECTLY.items():
        resp = client.get(f"/document/{ref}")
        assert resp.status_code == 200, f"{ref}: expected 200, got {resp.status_code}"
        served = hashlib.sha256(resp.content).hexdigest()[:12]
        assert served == sha12, f"{ref}: served sha {served}, measured {sha12}"


def test_t4_refusal_leaks_nothing():
    """T4: the 404 body contains no filename, no path, and no corpus name — a refusal
    must not disclose what it looked for."""
    for ref in ("BILL-3002", "BILL-9999", "NO-DIGITS-HERE"):
        resp = client.get(f"/document/{ref}")
        assert resp.status_code == 404, f"{ref}: expected 404"
        body_text = resp.text.lower()
        for leak in (".pdf", "inv-", "bill-", "fixtures", "documents/", "\\", "/", "tests"):
            assert leak not in body_text.replace("source document on file", ""), (
                f"{ref}: 404 body leaks {leak!r}: {resp.text}"
            )
