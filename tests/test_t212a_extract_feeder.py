"""T2.12a — Excel/CSV extract feeder: synthetic round-trip + count + coverage.

Proves slice A of the T2.12 adapter: ``feeders.ExtractChainReader`` reads a client
GST export and emits the SAME shaped surfaces the deterministic checking core consumes
from the live-SAP feeder. The round trip is:

    frozen ground truth → synthetic exporter → CSV/XLSX → ExtractChainReader → records

and we assert the reconstructed S1/S2/S3/S5 surfaces equal the canonical projection of the
frozen ground truth, field-for-field.

Scope guards (what this slice does NOT claim):
  * count() returns the export's TRUE row count and is asserted against the known count
    ONLY — never against the frozen S0 / oracle (which encode the dormant @odata.count → None
    bug; that comparison is gated on the re-freeze).
  * No full-chain run, no adapter-vs-oracle byte identity (gated), no accuracy claim (T2.11).
  * "synthetic-format-validated": the export column shape is this slice's guess at a client
    SAP B1 GST export, not a real client file.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from feeders.extract_reader import ExtractChainReader
from feeders import extract_schema as schema

_REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
EXPORT_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "extract-export-sbodemosg"

# Known true document counts in the frozen ground truth (NOT the dormant oracle null).
KNOWN_COUNTS = {
    "Invoices": 50,
    "PurchaseInvoices": 34,
    "CreditNotes": 1,
    "PurchaseCreditNotes": 1,
}

# Load the synthetic exporter (tests/ is not a package — importlib, as replay_shim does).
_synth_spec = importlib.util.spec_from_file_location(
    "t212a_synth_export", Path(__file__).resolve().parent / "synth_extract_export.py"
)
synth = importlib.util.module_from_spec(_synth_spec)
_synth_spec.loader.exec_module(synth)


# ---------------------------------------------------------------------------
# Expected canonical surfaces, projected directly from the frozen ground truth.
# ---------------------------------------------------------------------------


def _load_frozen(name: str):
    return json.loads((FROZEN_DIR / name).read_text(encoding="utf-8"))


def expected_invoices(filename: str, *, is_credit_note: bool = False) -> list:
    return [
        schema.project_document(d, is_credit_note=is_credit_note)
        for d in _load_frozen(filename)
    ]


def expected_listing() -> dict:
    listing = _load_frozen("listing-headers.json")
    out = {}
    for name, (_scope, _dt, projector) in schema.LISTING_BUCKETS.items():
        bucket = {
            "period_sales_headers": "period_sales_headers",
            "period_purch_headers": "period_purch_headers",
            "all_sales_headers": "all_sales_headers",
            "all_purch_headers": "all_purch_headers",
        }[name]
        out[name] = [projector(rec) for rec in listing[bucket]]
    return out


@pytest.fixture(scope="module")
def reader() -> ExtractChainReader:
    """Reader over the COMMITTED CSV export fixture."""
    return ExtractChainReader(EXPORT_FIXTURE_DIR)


# ---------------------------------------------------------------------------
# S1 — invoices
# ---------------------------------------------------------------------------


def test_roundtrip_sales_invoices(reader):
    assert reader.fetch_invoices("Invoices", "2024-07-01", "2024-09-30") == \
        expected_invoices("invoices.raw.json")


def test_roundtrip_purchase_invoices(reader):
    assert reader.fetch_invoices("PurchaseInvoices", "2024-07-01", "2024-09-30") == \
        expected_invoices("purchase-invoices.raw.json")


def test_invoice_lines_carry_canonical_fields(reader):
    inv = reader.fetch_invoices("Invoices", "2024-07-01", "2024-09-30")
    assert inv, "expected at least one invoice"
    line = inv[0]["DocumentLines"][0]
    assert set(line.keys()) == {"VatGroup", "LineTotal", "TaxTotal"}
    assert set(inv[0].keys()) == {
        "DocNum", "DocDate", "CardCode", "CardName", "DocCurrency", "DocTotal",
        "DocumentLines",
    }


# ---------------------------------------------------------------------------
# Gap A regression — doc-level DocTotal (the FX-conversion advisory figure).
#
# The recon found DocTotal silently dropped: calculate_f5_return reads
# doc-level doc.get("DocTotal") to build fx_invoices_requiring_conversion, but
# project_document / DOCUMENT_COLUMNS never carried it, so a feeder-fed run
# reported 0.00 for those FX totals. The original round-trip could not catch it
# because both sides use the SAME projector (symmetric blindness). These two
# tests break that symmetry by asserting against an INDEPENDENTLY-STATED value
# read straight from the frozen ground truth — not against the projector's own
# output.
#
# Anchor: frozen sales invoice DocNum=958 is a USD (FX) document whose frozen
# doc-level DocTotal is 1131.53.
# ---------------------------------------------------------------------------

_FX_DOC_NUM = 958
_FX_DOC_TOTAL = 1131.53  # independently read from invoices.raw.json (USD doc 958)


def test_document_projection_carries_doctotal():
    """project_document must surface the doc-level DocTotal (independent value)."""
    raw = next(
        d for d in _load_frozen("invoices.raw.json") if d.get("DocNum") == _FX_DOC_NUM
    )
    assert raw.get("DocCurrency") == "USD", "anchor doc must be the FX doc"
    projected = schema.project_document(raw)
    assert projected["DocTotal"] == _FX_DOC_TOTAL


def test_feeder_carries_doctotal_for_fx_doc(reader):
    """End-to-end through the export round-trip: the FX doc keeps its true total,
    asserted against the independently-stated frozen value (not the projector)."""
    inv = reader.fetch_invoices("Invoices", "2024-07-01", "2024-09-30")
    fx = next(d for d in inv if d["DocNum"] == _FX_DOC_NUM)
    assert fx["DocCurrency"] == "USD"
    assert fx["DocTotal"] == _FX_DOC_TOTAL


# ---------------------------------------------------------------------------
# S2 — credit notes (tagged is_credit_note=True)
# ---------------------------------------------------------------------------


def test_roundtrip_sales_credit_notes(reader):
    assert reader.fetch_credit_notes("sales", "2024-07-01", "2024-09-30") == \
        expected_invoices("credit-notes.raw.json", is_credit_note=True)


def test_roundtrip_purchase_credit_notes(reader):
    assert reader.fetch_credit_notes("purchases", "2024-07-01", "2024-09-30") == \
        expected_invoices("purchase-credit-notes.raw.json", is_credit_note=True)


def test_credit_notes_tagged_invoices_not(reader):
    for doc in reader.fetch_credit_notes("sales", "2024-07-01", "2024-09-30"):
        assert doc.get("is_credit_note") is True
    for doc in reader.fetch_invoices("Invoices", "2024-07-01", "2024-09-30"):
        assert "is_credit_note" not in doc


def test_per_call_freshness_no_tag_leak(reader):
    """Mutating a returned payload must not affect a later read (deepcopy-per-call)."""
    cns = reader.fetch_credit_notes("sales", "2024-07-01", "2024-09-30")
    cns[0]["DocumentLines"][0]["LineTotal"] = -999999.0
    cns[0]["is_credit_note"] = "MUTATED"
    again = reader.fetch_credit_notes("sales", "2024-07-01", "2024-09-30")
    assert again[0]["DocumentLines"][0]["LineTotal"] != -999999.0
    assert again[0]["is_credit_note"] is True


# ---------------------------------------------------------------------------
# S3 — business partner (FederalTaxID)
# ---------------------------------------------------------------------------


def test_roundtrip_business_partners(reader):
    raw = _load_frozen("business-partners.raw.json")
    for card_code, record in raw.items():
        assert reader.get_business_partner(card_code) == \
            schema.project_business_partner(record)


def test_business_partner_carries_federal_tax_id(reader):
    # V21000 is GST-registered in the frozen extract; V10000 is not.
    assert reader.get_business_partner("V21000")["FederalTaxID"] == "SK98467789"
    assert reader.get_business_partner("V10000")["FederalTaxID"] is None


def test_business_partner_absent_raises(reader):
    with pytest.raises(KeyError):
        reader.get_business_partner("NOT_A_CARD")


# ---------------------------------------------------------------------------
# S5 — listing (four buckets)
# ---------------------------------------------------------------------------


def test_roundtrip_listing_all_buckets(reader):
    got = reader.fetch_listing({"start": "2024-07-01", "end": "2024-09-30"})
    assert set(got.keys()) == {
        "period_sales_headers", "period_purch_headers",
        "all_sales_headers", "all_purch_headers",
    }
    assert got == expected_listing()


def test_listing_period_purch_carries_dup_claim_keys(reader):
    got = reader.fetch_listing({"start": "2024-07-01", "end": "2024-09-30"})
    rec = got["period_purch_headers"][0]
    assert set(rec.keys()) == {
        "DocNum", "Series", "Cancelled", "CardCode", "NumAtCard", "DocTotal"
    }
    # Sales / company-wide buckets stay header-minimal (no DUP_CLAIM key fields).
    assert set(got["all_sales_headers"][0].keys()) == {"DocNum", "Series", "Cancelled"}


# ---------------------------------------------------------------------------
# count() — the trap: TRUE count, never the dormant oracle null.
# ---------------------------------------------------------------------------


def test_count_returns_true_row_count(reader):
    for entity, expected in KNOWN_COUNTS.items():
        assert reader.count(entity, "2024-07-01", "2024-09-30") == expected


def test_count_matches_fetched_invoice_length(reader):
    for entity in ("Invoices", "PurchaseInvoices"):
        assert reader.count(entity, "2024-07-01", "2024-09-30") == \
            len(reader.fetch_invoices(entity, "2024-07-01", "2024-09-30"))


def test_count_is_real_int_not_dormant_none(reader):
    # The export counts honestly: count() is a real int, NOT the @odata.count → None
    # the live feeder/oracle reproduce. (We deliberately do NOT compare to the oracle.)
    val = reader.count("Invoices", "2024-07-01", "2024-09-30")
    assert isinstance(val, int) and val > 0


# ---------------------------------------------------------------------------
# Coverage seam (emission only).
# ---------------------------------------------------------------------------


def test_coverage_full_on_complete_export(reader):
    cov = reader.coverage()
    assert cov.is_full()
    assert cov.missing() == []
    assert set(cov.fields.keys()) == set(schema.COVERAGE_FIELDS.keys())


def test_coverage_flags_missing_column(tmp_path):
    """Drop a canonical column from the export → coverage declares it missing."""
    synth.export_csv(FROZEN_DIR, tmp_path)
    # Strip the FederalTaxID column from the BP sheet.
    bp_path = tmp_path / f"{schema.BUSINESS_PARTNERS_SHEET}.csv"
    import csv as _csv
    with bp_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(_csv.DictReader(fh))
    with bp_path.open("w", encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=["CardCode", "CardName"], lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({"CardCode": row["CardCode"], "CardName": row["CardName"]})
    cov = ExtractChainReader(tmp_path).coverage()
    assert not cov.is_full()
    assert "FederalTaxID" in cov.missing()


# ---------------------------------------------------------------------------
# Exporter determinism + .xlsx path.
# ---------------------------------------------------------------------------


def test_committed_csv_fixture_is_byte_stable(tmp_path):
    """Regenerating the export reproduces the committed fixture byte-for-byte (LF)."""
    synth.export_csv(FROZEN_DIR, tmp_path)
    for name, _cols, _builder in synth._SHEETS:
        regenerated = (tmp_path / f"{name}.csv").read_bytes()
        committed = (EXPORT_FIXTURE_DIR / f"{name}.csv").read_bytes()
        assert regenerated == committed, f"{name}.csv drifted from committed fixture"
        assert b"\r\n" not in regenerated, f"{name}.csv has CRLF (must be LF)"


def test_xlsx_roundtrip(tmp_path):
    """The .xlsx feeder path reconstructs the same canonical surfaces as CSV."""
    xlsx_path = tmp_path / "export.xlsx"
    synth.export_xlsx(FROZEN_DIR, xlsx_path)
    rdr = ExtractChainReader(xlsx_path)
    assert rdr.fetch_invoices("Invoices", "2024-07-01", "2024-09-30") == \
        expected_invoices("invoices.raw.json")
    assert rdr.fetch_credit_notes("purchases", "2024-07-01", "2024-09-30") == \
        expected_invoices("purchase-credit-notes.raw.json", is_credit_note=True)
    assert rdr.fetch_listing({"start": "x", "end": "y"}) == expected_listing()
    assert rdr.count("PurchaseInvoices", "x", "y") == KNOWN_COUNTS["PurchaseInvoices"]
    assert rdr.coverage().is_full()
