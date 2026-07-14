"""feeders/xero_sales_lines.py — Xero chain-docs → reasoning 9-key sales lines (Prompt E).

Projects the chain-shaped sales documents emitted by
``feeders.xero_sales_reader.XeroSalesInvoiceChainReader`` into the reasoning-layer
9-key line dicts that ``reasoning.exempt.run_exempt_pass`` consumes via
``ReviewInputs.sales_line_source`` — the Xero counterpart of
``reasoning.sap_lines.fetch_sales_lines``.

Contract notes (load-bearing):
- ``doc_num`` is the reader's InvoiceNumber STRING (e.g. "INV-2001"), carried
  VERBATIM — never coerced to int (STOP#2 ruling a-relax: the reasoning contract
  is type-preserving; traceability requires the client's real reference).
- ``vat_group`` is taken AS-IS from the reader line: the reader already resolved
  TaxType → canonical VatGroup via the client YAML at construction. The adapter
  must NOT re-normalize.
- ``doc_type``/``line_index`` are synthesized ("sales_invoice" / enumerate order,
  mirroring the reader's implicit first-seen line order).
- ``line_description`` is the Prompt-D passthrough, forwarded unchanged.

BOX-ISOLATION: this module feeds ONLY the reasoning sales_line_source path
(Phase 2b, beside the chain). It never enters run_chain or the F5 box loop —
boxes are byte-identical with or without it.

HONEST RUNG: real-FORMAT over synthetic Xero, NOT real-client-validated; exempt
skill now runs on Xero over synthetic data only.

Pure stdlib; imports nothing beyond typing (feeders stays a leaf; no anthropic,
no reasoning/, no engine/).
"""
from __future__ import annotations


def xero_sales_lines(reader, period_start: str, period_end: str) -> list[dict]:
    """Return reasoning 9-key sales line dicts projected from a Xero sales reader.

    Args:
        reader:       A constructed XeroSalesInvoiceChainReader (typed structurally
                      to keep this module import-free of the reader class).
        period_start: ISO date 'YYYY-MM-DD' (forwarded to the reader).
        period_end:   ISO date 'YYYY-MM-DD'.

    Returns:
        One dict per sales line with exactly the keys:
            doc_num (str — InvoiceNumber verbatim), doc_type ("sales_invoice"),
            doc_date (str, YYYY-MM-DD), card_name (str), line_index (int),
            vat_group (canonical str, as resolved by the reader), line_description
            (str, Prompt-D passthrough), line_total (float), tax_total (float).
    """
    lines: list[dict] = []
    for doc in reader.fetch_invoices("Invoices", period_start, period_end):
        for idx, line in enumerate(doc.get("DocumentLines", [])):
            lines.append({
                # InvoiceNumber string verbatim — a-relax keeps it traceable.
                "doc_num": str(doc.get("DocNum") or ""),
                "doc_type": "sales_invoice",
                "doc_date": str(doc.get("DocDate", ""))[:10],
                "card_name": str(doc.get("CardName", "")),
                "line_index": idx,
                # Already canonical (reader resolved TaxType via YAML) — no re-normalize.
                "vat_group": str(line.get("VatGroup") or ""),
                "line_description": str(line.get("line_description") or ""),
                "line_total": float(line.get("LineTotal") or 0),
                "tax_total": float(line.get("TaxTotal") or 0),
            })
    return lines
