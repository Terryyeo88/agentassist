"""tests/test_ingest_label_tolerance_batch2.py — answer key for the batch-2 documents.

Option-1 discipline (Terry's ruling): the batch-1 answer key (test_ingest_label_tolerance.py)
is a FIXED list, so a new corpus document is silently untested until its hand-read key row
lands. These are the batch-2 rows — appended as a NEW file, the existing key untouched.

Values hand-read from the raw page text (pdfplumber print, 2026-07-29), never from a regex.

RULING ON RECORD (Terry, 2026-07-29): BILL-3009's invoice date 2026-03-28 sits OUTSIDE the
Q2 review period (2026-04-01..2026-06-30) and is a NATURAL correct_period BAIT — the date
is deliberate and must not be "fixed". NOTE: fixture_manifest.csv currently labels the row
"(clean control)"; Terry reconciles the manifest before T-E(2)'s corpus scoring treats a
correct_period fire on BILL-3009 as a false positive.
"""
from pathlib import Path

import pytest

from documents.ingest import ingest

_DOCS = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "xero-demo-2026Q2" / "source_documents"

_FIELDS = ("supplier_name", "supplier_gst_regno", "invoice_number", "invoice_date",
           "total_excl_gst", "gst_rate", "gst_amount", "total_incl_gst")

_BATCH2_KEY = {
    "BILL-3009": ("Bras Basah Print Pte Ltd", "201288888N", "BILL-3009", "2026-03-28", 900.0, "9%", 81.0, 981.0),
    "BILL-3010": ("Serangoon Facilities Pte Ltd", "201511111R", "BILL-3010", "2026-04-24", 1800.0, "9%", 162.0, 1998.0),
}


@pytest.mark.parametrize("stem", sorted(_BATCH2_KEY))
def test_batch2_extracts_the_answer_key(stem):
    e = ingest(_DOCS / f"{stem}.pdf")
    got = tuple(getattr(e, f) for f in _FIELDS)
    assert got == _BATCH2_KEY[stem], f"{stem}: {got} != hand-read key"
