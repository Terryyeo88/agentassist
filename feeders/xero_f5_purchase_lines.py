"""feeders/xero_f5_purchase_lines.py — Xero F5 chain-docs → reasoning 9-key purchase lines.

D-2026-09-23-xero-purchase-lines (E2). The purchase-side counterpart of
``feeders.xero_sales_lines`` (Prompt E), projecting the chain-shaped purchase documents
emitted by ``feeders.xero_f5_reader.XeroF5ChainReader`` into the reasoning-layer 9-key line
dicts that ``reasoning.reg2627.run_reg2627_pass`` consumes — the Xero counterpart of
``reasoning.sap_lines.fetch_si_purchase_lines``.

WHY THIS EXISTS. The Reg 26/27 skill has been DARK on the Xero path since that path
existed: every Xero upload handed the pass a line source yielding nothing, so it
short-circuited to a clean ``ok`` with zero candidates and made no model call. Nothing on
the paper distinguished "examined and found nothing" from "never looked". This adapter is
the missing input.

CONTRACT NOTES (load-bearing, mirroring the sales precedent — no second shape is invented):
- ``doc_num`` is the reader's reference STRING carried VERBATIM ("BILL-3007"), never
  coerced to int (STOP#2 ruling a-relax: the reasoning contract is type-preserving, and
  traceability requires the client's real reference). An ``int()`` here is precisely the
  class of bug open item #34 records.
- ``vat_group`` is taken AS-IS from the reader line: the F5 reader already resolved the
  tax-rate name to a canonical VatGroup at construction. The adapter must NOT re-normalize.
- Only canonical ``TX`` lines are yielded. A line already coded BL (or any other
  disallowed/out-of-scope group) is not a Reg 26/27 question: the check asks whether input
  tax that WAS claimed should have been disallowed. The pass applies its own spec filter as
  well; this narrows at the source so the model never sees a line that is out of scope.
- ``line_index`` is the enumerate order within the document, mirroring the sales adapter.
  The Xero F5 export is ONE ROW PER LINE, so a multi-row reference yields multiple lines —
  never one merged line. That property is pinned by test, because every Box 5 bill in the
  committed corpus happens to be single-line and the assumption would otherwise be
  load-bearing and unexercised.

BOX-ISOLATION: this module feeds ONLY the reasoning ``purchase_line_source`` path (Phase
2b, beside the chain). It never enters ``run_chain`` or the F5 box loop — boxes are
byte-identical with or without it. The isolation is STRUCTURAL, exactly as the sales
adapter's is: ``run_chain`` takes no line-source parameter at all, so there is no code path
through which this could reach the box arithmetic.

HONEST RUNG: real-FORMAT over synthetic Xero, NOT real-client-validated, NOT
accuracy-validated. Making the pass RUNNABLE is not evidence that its judgements are right.

Pure stdlib; imports nothing (feeders stays a leaf: no anthropic, no reasoning/, no engine/).
"""
from __future__ import annotations

#: The canonical code this skill's subject is defined over — standard-rated purchases on
#: which input tax was claimed. Named rather than inlined so the filter reads as a rule.
_STANDARD_RATED_PURCHASE = "TX"


def xero_f5_purchase_lines(reader, period_start: str, period_end: str) -> list[dict]:
    """Return reasoning 9-key purchase line dicts projected from a Xero F5 reader.

    Args:
        reader:       A constructed XeroF5ChainReader (typed structurally to keep this
                      module import-free of the reader class).
        period_start: ISO date 'YYYY-MM-DD' (forwarded to the reader).
        period_end:   ISO date 'YYYY-MM-DD'.

    Returns:
        One dict per canonical-TX purchase line with exactly the keys:
            doc_num (str — the Xero reference verbatim), doc_type ("purchase_invoice"),
            doc_date (str, YYYY-MM-DD), card_name (str), line_index (int),
            vat_group (canonical str, as resolved by the reader), line_description (str),
            line_total (float), tax_total (float).
    """
    lines: list[dict] = []
    for doc in reader.fetch_invoices("PurchaseInvoices", period_start, period_end):
        for idx, line in enumerate(doc.get("DocumentLines", [])):
            if str(line.get("VatGroup") or "").strip() != _STANDARD_RATED_PURCHASE:
                continue
            lines.append({
                # The Xero reference verbatim — a-relax keeps it traceable.
                "doc_num": str(doc.get("DocNum") or ""),
                "doc_type": "purchase_invoice",
                "doc_date": str(doc.get("DocDate", ""))[:10],
                "card_name": str(doc.get("CardName", "")),
                "line_index": idx,
                # Already canonical (the reader resolved the tax-rate name) — no re-normalize.
                "vat_group": str(line.get("VatGroup") or ""),
                "line_description": str(line.get("line_description") or ""),
                "line_total": float(line.get("LineTotal") or 0),
                "tax_total": float(line.get("TaxTotal") or 0),
            })
    return lines
