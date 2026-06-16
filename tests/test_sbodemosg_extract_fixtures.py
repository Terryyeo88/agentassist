"""Hermetic integrity smoke test for the T2.12a SBODEMOSG ground-truth freeze.

Validates that the frozen fixtures in tests/fixtures/sbodemosg-extract/ are intact
and structurally match capture-manifest.json — verbatim shapes, record counts, and
sha256 digests. This is an INTEGRITY test only; it touches no network and imports no
SAP code. The semantic offline-replay (chain off frozen raw == _replay-oracle) is a
separate follow-on prompt.

Counts/hashes are read from the manifest rather than hardcoded, so a legitimate
re-capture (which rewrites the manifest alongside the fixtures) keeps the test green.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sbodemosg-extract"
MANIFEST_PATH = FIXTURE_DIR / "capture-manifest.json"


def _sha256_file(path: Path) -> str:
    """Return 'sha256:<hex>' for a file — matches audit_bundle.canonical format."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _load(name: str):
    return json.load(open(FIXTURE_DIR / name, encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST_PATH.exists(), "capture-manifest.json missing — run scripts/capture_sbodemosg_extract.py"
    return json.load(open(MANIFEST_PATH, encoding="utf-8"))


def test_manifest_shape(manifest):
    for key in ("captured_at", "instance", "service_layer_version", "period", "fixtures"):
        assert key in manifest, f"manifest missing {key}"
    assert manifest["instance"] == "SBODEMOSG"
    assert manifest["period"] == {"start": "2024-07-01", "end": "2024-09-30"}
    assert len(manifest["fixtures"]) == 9  # 8 surfaces + replay oracle


def test_all_fixtures_exist_nonempty_and_hash_matches(manifest):
    """Every manifest fixture exists, is non-empty, and its sha256 still matches."""
    for fname, entry in manifest["fixtures"].items():
        path = FIXTURE_DIR / fname
        assert path.exists(), f"{fname} missing"
        assert path.stat().st_size > 0, f"{fname} is empty"
        assert _sha256_file(path) == entry["sha256"], f"{fname} sha256 drift — fixture edited out of band"


@pytest.mark.parametrize("fname", ["invoices.raw.json", "purchase-invoices.raw.json"])
def test_s1_invoices_verbatim(manifest, fname):
    docs = _load(fname)
    assert isinstance(docs, list)
    assert len(docs) == manifest["fixtures"][fname]["record_count"]
    head = docs[0]
    for k in ("DocNum", "DocDate", "DocCurrency", "DocTotal", "CardCode", "CardName", "DocumentLines"):
        assert k in head, f"{fname}: header missing {k}"
    # Verbatim full payload — recon recorded ~282 header / ~226 line keys.
    assert len(head) > 100, f"{fname}: header looks trimmed ({len(head)} keys)"
    line = head["DocumentLines"][0]
    for k in ("VatGroup", "LineTotal", "TaxTotal", "ItemDescription", "ItemCode"):
        assert k in line, f"{fname}: line missing {k}"
    assert len(line) > 100, f"{fname}: line looks trimmed ({len(line)} keys)"


@pytest.mark.parametrize("fname", ["credit-notes.raw.json", "purchase-credit-notes.raw.json"])
def test_s2_credit_notes_tagged(manifest, fname):
    docs = _load(fname)
    assert isinstance(docs, list)
    assert len(docs) == manifest["fixtures"][fname]["record_count"]
    # The credit-note helper tags every record; the freeze must preserve it.
    assert docs[0].get("is_credit_note") is True, f"{fname}: is_credit_note tag lost"
    assert "DocumentLines" in docs[0]


def test_s3_business_partners(manifest):
    bp = _load("business-partners.raw.json")
    entry = manifest["fixtures"]["business-partners.raw.json"]
    assert isinstance(bp, dict)
    assert len(bp) == entry["record_count"]
    assert sorted(bp.keys()) == sorted(entry["card_codes"])
    for code, record in bp.items():
        assert record.get("CardCode") == code
        assert "FederalTaxID" in record, f"{code}: FederalTaxID key absent (drives NO_GST_REG)"


def test_s4_si_lines_nine_key_shape(manifest):
    lines = _load("si-purchase-lines.json")
    assert isinstance(lines, list)
    assert len(lines) == manifest["fixtures"]["si-purchase-lines.json"]["record_count"]
    expected = {"doc_num", "doc_type", "doc_date", "card_name", "line_index",
                "vat_group", "line_description", "line_total", "tax_total"}
    for ln in lines:
        assert set(ln.keys()) == expected, "si line shape drifted from the 9-key contract"
        assert ln["vat_group"] == "SI"


def test_s5_listing_headers(manifest):
    listing = _load("listing-headers.json")
    counts = manifest["fixtures"]["listing-headers.json"]["counts"]
    assert set(listing.keys()) == {
        "period_sales_headers", "period_purch_headers",
        "all_sales_headers", "all_purch_headers",
    }
    for key, expected_n in counts.items():
        assert len(listing[key]) == expected_n, f"{key}: count drift"
    # Company-wide must exceed period-scoped (the SEQ_GAP basis recon flagged).
    assert len(listing["all_sales_headers"]) > len(listing["period_sales_headers"])
    for k in ("DocNum", "Series", "Cancelled"):
        assert k in listing["period_sales_headers"][0]
    for k in ("DocNum", "CardCode", "NumAtCard", "DocTotal"):
        assert k in listing["period_purch_headers"][0]


def test_s0_inline_counts_record_at_prefix_key(manifest):
    ic = _load("inline-counts.json")
    # The @-prefix key is the whole point — it documents the Gate-1 latent bug.
    assert ic["inlinecount_key"] == "@odata.count"
    assert ic["counts"] == manifest["fixtures"]["inline-counts.json"]["counts"]
    for entity, n in ic["counts"].items():
        assert isinstance(n, int), f"{entity}: count not an int"


def test_replay_oracle_present_and_shaped(manifest):
    oracle = _load("_replay-oracle.compiled.json")
    assert oracle["period"] == manifest["period"]
    co = oracle["compile_output"]
    for k in ("fetch_manifest", "calculate", "classify", "detect", "e1_reconciliation"):
        assert k in co, f"oracle compile_output missing {k}"
    gr = oracle["gate_results"]
    assert "all_passed" in gr and isinstance(gr["gates"], list)
    assert len(gr["gates"]) == 5, "expected five gate records in the oracle"
