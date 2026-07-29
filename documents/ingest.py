"""documents/ingest.py — Invoice PDF field extraction (T2.8).

Public API:
    ingest(pdf_path) -> ExtractedInvoice

Routing:
    1. Open the PDF with pdfplumber.
    2. If a usable text layer is present (born-digital PDF), extract all fields
       with pure-Python regexes — zero network calls, no anthropic import.
    3. If no text layer exists (scanned/image-only PDF), fall back to multimodal
       extraction via the Anthropic Messages API.  The `import anthropic` is
       deferred to _extract_multimodal() so that the born-digital path is always
       SDK-free.

Text patterns emitted by the T2.8 fixture generator
(tests/fixtures/documents/generate_invoices.py) and matched here:

    Line 0 : <Supplier Name>                         first non-empty line
    Line 1 : <supplier address>
    Line 2 : "GST Reg No: M12345678X"  or  "GST Reg No: "
    Line 4 : "TAX INVOICE"
    ...     : "Invoice No: INV-3001    Bill To:"
    ...     : "Invoice Date: 2024-07-15  <customer name>"
    ...     : "Subtotal (excl. GST):   5,000.00"
    ...     : "GST @ 7%:                 350.00"
    ...     : "TOTAL (incl. GST):      5,350.00"
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pdfplumber


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------

@dataclass
class ExtractedInvoice:
    supplier_name: str | None
    supplier_gst_regno: str | None
    invoice_number: str | None
    invoice_date: str | None       # normalised YYYY-MM-DD
    total_excl_gst: float | None
    gst_rate: str | None           # e.g. "7%"
    gst_amount: float | None
    total_incl_gst: float | None
    source: Literal["born_digital", "multimodal"]
    validation_status: str         # always "unvalidated"
    fields_present: dict[str, bool] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parse_money(s: str) -> float | None:
    """Parse a money string like '5,000.00' to float. Returns None on failure."""
    m = re.search(r'[\d,]+\.\d{2}', s)
    if m:
        return float(m.group().replace(',', ''))
    return None


# ---------------------------------------------------------------------------
# Text-layer detection and extraction (pdfplumber)
# ---------------------------------------------------------------------------

def _has_text_layer(pdf_path: Path) -> bool:
    """Return True if any page of the PDF has non-empty extractable text."""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            if (page.extract_text() or "").strip():
                return True
    return False


def _extract_text(pdf_path: Path) -> str:
    """Return all text from the PDF, pages joined with newlines."""
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


# ---------------------------------------------------------------------------
# Born-digital extraction — pure Python, no network
# ---------------------------------------------------------------------------

def _extract_born_digital(text: str) -> ExtractedInvoice:
    """Extract invoice fields from PDF text using regexes.

    Patterns match the layout emitted by generate_invoices.py and are designed
    to be robust to minor whitespace variation in pdfplumber's output.
    """
    # Supplier name: the first non-empty line (the SAP fixture layout renders the
    # supplier top-left, 14pt bold) — UNLESS that line is the bare "TAX INVOICE"
    # document-type header, in which case the supplier is the NEXT non-empty line.
    # Covers the 2026Q2 Xero corpus layout (e.g. BILL-3001.pdf, whose first line is
    # "TAX INVOICE" and second is "GoodVendor Pte Ltd"); the SAP fixtures put the
    # header at line 4, so their extraction is unchanged. Without this, every corpus
    # document extracted supplier_name="TAX INVOICE" — a WRONG value, worse than an
    # absent one.
    supplier_name: str | None = next(
        (ln.strip() for ln in text.splitlines()
         if ln.strip() and ln.strip().upper() != "TAX INVOICE"),
        None,
    )

    # GST registration number — Singapore format: letter + 8 digits + letter
    m = re.search(r'GST Reg No:\s*([A-Z0-9]{6,12})', text)
    gst_reg: str | None = m.group(1) if m else None

    # Invoice number. The "Invoice No:" label appears in BOTH corpora and is tried
    # FIRST: the bare INV-<digits> fallback (the original SAP-fitted pattern) grabbed
    # a vendor Reference ("INV-7742" on BILL-3005.pdf) as the invoice number — a
    # wrong value. On every SAP fixture the label yields the identical value (the
    # control-set test pins it), so label-first changes no SAP extraction. The bare
    # INV-<digits> form remains as the fallback for label-less documents.
    m = re.search(r'Invoice No:\s*([A-Za-z][A-Za-z0-9-]*\d)', text)
    if not m:
        m = re.search(r'(INV-\d+)', text)
    inv_num: str | None = m.group(1) if m else None

    # Invoice date as YYYY-MM-DD. The specific "Invoice Date:" label (SAP fixture
    # layout) runs first and unchanged; the bare "Date:" label (2026Q2 Xero corpus,
    # e.g. BILL-3002.pdf's "Invoice No: BILL-3002 Date: 2026-04-22") is a FALLBACK
    # reached only when the specific form is absent. Lookbehinds keep a due/payment/
    # statement date from ever being read as the invoice date ("Due:" is the corpus's
    # own other date label; "Due Date:" et al. are the guarded near-misses).
    m = re.search(r'Invoice Date:\s*(\d{4}-\d{2}-\d{2})', text)
    if not m:
        m = re.search(
            r'(?<!Due )(?<!Payment )(?<!Statement )\bDate:\s*(\d{4}-\d{2}-\d{2})', text
        )
    inv_date: str | None = m.group(1) if m else None

    # Subtotal excluding GST. Specific SAP-fixture label first; bare "Subtotal:"
    # (2026Q2 corpus, e.g. BILL-3001.pdf) as fallback — it cannot match the SAP form,
    # where the colon follows "(excl. GST)", not "Subtotal".
    m = re.search(r'Subtotal \(excl\. GST\):\s*([\d,]+\.\d{2})', text)
    if not m:
        m = re.search(r'Subtotal:\s*([\d,]+\.\d{2})', text)
    excl_gst: float | None = _parse_money(m.group(1)) if m else None

    # GST rate label (e.g. "7%") and GST amount on the same line
    m = re.search(r'GST @ (\d+%):\s*([\d,]+\.\d{2})', text)
    gst_rate: str | None = m.group(1) if m else None
    gst_amount: float | None = _parse_money(m.group(2)) if m else None

    # Total including GST. Specific SAP-fixture label first; bare "Total:" (2026Q2
    # corpus, e.g. BILL-3001.pdf) as fallback — \b plus the capital T keeps it off
    # "Subtotal:" ("Subtotal" is one word; there is no boundary before its "total").
    m = re.search(r'TOTAL \(incl\. GST\):\s*([\d,]+\.\d{2})', text)
    if not m:
        m = re.search(r'\bTotal:\s*([\d,]+\.\d{2})', text)
    total: float | None = _parse_money(m.group(1)) if m else None

    vals: dict[str, object] = {
        "supplier_name": supplier_name,
        "supplier_gst_regno": gst_reg,
        "invoice_number": inv_num,
        "invoice_date": inv_date,
        "total_excl_gst": excl_gst,
        "gst_rate": gst_rate,
        "gst_amount": gst_amount,
        "total_incl_gst": total,
    }

    return ExtractedInvoice(
        supplier_name=supplier_name,
        supplier_gst_regno=gst_reg,
        invoice_number=inv_num,
        invoice_date=inv_date,
        total_excl_gst=excl_gst,
        gst_rate=gst_rate,
        gst_amount=gst_amount,
        total_incl_gst=total,
        source="born_digital",
        validation_status="unvalidated",
        fields_present={k: v is not None for k, v in vals.items()},
    )


# ---------------------------------------------------------------------------
# Multimodal extraction — deferred anthropic import, only for scanned PDFs
# ---------------------------------------------------------------------------

_MULTIMODAL_PROMPT = (
    "Extract the following fields from this Singapore tax invoice PDF. "
    "Return ONLY a JSON object (no markdown fences, no explanation) with "
    "these exact keys: supplier_name, supplier_gst_regno (null if absent), "
    "invoice_number, invoice_date (YYYY-MM-DD string), total_excl_gst (number), "
    "gst_rate (string, e.g. '7%'), gst_amount (number), total_incl_gst (number). "
    "Set a field to null if it is not present or not legible on the invoice."
)


def _extract_multimodal(pdf_path: Path) -> ExtractedInvoice:
    """Extract invoice fields via Claude for image-only PDFs.

    The `import anthropic` is deferred here so that born-digital processing
    never touches the Anthropic SDK or requires ANTHROPIC_API_KEY to be set.
    """
    import anthropic  # noqa: PLC0415 — deferred intentionally; born-digital is SDK-free

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set — required for multimodal invoice ingestion."
        )

    pdf_b64 = base64.standard_b64encode(pdf_path.read_bytes()).decode()

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": _MULTIMODAL_PROMPT},
            ],
        }],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    data: dict = json.loads(raw)

    def _f(v: object) -> float | None:
        if v is None:
            return None
        try:
            return float(str(v).replace(',', ''))
        except (ValueError, TypeError):
            return None

    vals: dict[str, object] = {
        "supplier_name": data.get("supplier_name") or None,
        "supplier_gst_regno": data.get("supplier_gst_regno") or None,
        "invoice_number": data.get("invoice_number") or None,
        "invoice_date": data.get("invoice_date") or None,
        "total_excl_gst": _f(data.get("total_excl_gst")),
        "gst_rate": data.get("gst_rate") or None,
        "gst_amount": _f(data.get("gst_amount")),
        "total_incl_gst": _f(data.get("total_incl_gst")),
    }

    return ExtractedInvoice(
        **vals,  # type: ignore[arg-type]
        source="multimodal",
        validation_status="unvalidated",
        fields_present={k: v is not None for k, v in vals.items()},
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest(pdf_path: Path) -> ExtractedInvoice:
    """Extract structured fields from an invoice PDF.

    Born-digital path (text layer present): pure-Python regex extraction.
    Multimodal path (no text layer): Claude API call via deferred anthropic import.

    The anthropic SDK is the ONLY package import restricted to the multimodal path.
    orchestrator/, audit_bundle/, and boxes/gates/calculate paths are never imported.

    Args:
        pdf_path: Path to the invoice PDF file.

    Returns:
        ExtractedInvoice with all fields extracted and validation_status="unvalidated".
        fields_present indicates which fields were successfully extracted.
    """
    p = Path(pdf_path)
    if _has_text_layer(p):
        return _extract_born_digital(_extract_text(p))
    return _extract_multimodal(p)
