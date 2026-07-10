"""documents/doc_pass.py — Source-document cross-reference pre-pass (T2.8).

Public API:
    run_documents_pass(line_items, provider, period_start, period_end)
        -> list[DocumentCandidate]

This pre-pass runs alongside the Reg 26/27 reasoning pass — outside the gated
chain and outside report rendering.  For each SI line item it:
  1. Asks the provider for the matching invoice PDF.
  2. If available, ingests it via documents.ingest.ingest().
  3. Assesses legibility (T2.14) via documents.legibility.assess_legibility().
     An illegible document is routed to "manual review required" and is NOT fed
     to reconcile (so no confident-wrong candidate is surfaced from an unreadable
     PDF); when a legibility_rows list is supplied, one coverage-style row is
     appended to it for the ungated Deterministic Check Coverage surface.
  4. Otherwise reconciles it against the line-item record via
     documents.reconcile.reconcile().
  5. Collects all DocumentCandidate outputs.
  6. Silently skips doc_nums for which no PDF is available.

The caller (run_agent.py) forwards the resulting list to build_report() as
document_candidates.  When no provider is configured, document_candidates=None
and the unified report section notes "source documents: not examined."

Named doc_pass.py (not pass.py) to avoid conflict with Python's built-in
`pass` keyword, which would prevent normal import syntax.

Containment:
    No imports from orchestrator/, audit_bundle/, boxes, gates, or calculate.
    No module-level anthropic import — born-digital path is SDK-free; multimodal
    import is deferred inside documents.ingest._extract_multimodal().
"""
from __future__ import annotations

from documents.ingest import ingest
from documents.legibility import assess_legibility
from documents.provider import DocumentProvider
from documents.reconcile import DocumentCandidate, reconcile


def run_documents_pass(
    line_items: list[dict],
    provider: DocumentProvider,
    period_start: str,
    period_end: str,
    *,
    legibility_rows: list | None = None,
) -> list[DocumentCandidate]:
    """Run the source-document cross-reference pass over a list of SI line items.

    Args:
        line_items:   List of line-item dicts (shape from reasoning/sap_lines.py).
                      Each must have a 'doc_num' key.
        provider:     A DocumentProvider that locates the invoice PDF for a doc_num.
        period_start: Audit period start, YYYY-MM-DD inclusive.
        period_end:   Audit period end, YYYY-MM-DD inclusive.
        legibility_rows: Optional out-collection (T2.14). When a list is supplied,
                      each illegible document appends ONE coverage-style row
                      (``assess_legibility(...).as_coverage_row(doc_num)``) to it
                      for the ungated Deterministic Check Coverage surface. The
                      return type is unchanged so existing callers are unaffected;
                      an illegible document is skipped from reconcile either way
                      (the gate protects reconcile from unreliable fields).

    Returns:
        Flat list of DocumentCandidate items from all matched pairs whose source
        document is legible. Line items with no available PDF are silently skipped;
        illegible documents produce no candidate (routed to manual review instead).
        All candidates carry validation_status="unvalidated".
    """
    candidates: list[DocumentCandidate] = []
    for line_item in line_items:
        doc_num = int(line_item["doc_num"])
        pdf_path = provider.get_document(doc_num)
        if pdf_path is None:
            continue
        extracted = ingest(pdf_path)
        # T2.14 legibility gate: an unreadable/partial document is routed to
        # "manual review required" rather than fed to reconcile with unreliable
        # fields — surfaces a data-quality caveat, never a tax verdict.
        status = assess_legibility(extracted)
        if status.needs_manual_review:
            if legibility_rows is not None:
                legibility_rows.append(status.as_coverage_row(doc_num))
            continue
        candidates.extend(reconcile(extracted, line_item, period_start, period_end))
    return candidates
