"""documents — PDF invoice ingestion layer (T2.8).

Provides ingest(pdf_path) -> ExtractedInvoice with dual routing:
  born_digital  — pure-Python regex, no network, no anthropic SDK required.
  multimodal    — Claude API via a deferred import; only for image-only PDFs.

Dependency invariants (test-enforced):
  • orchestrator/ never imports documents/ or anthropic.
  • documents/ never imports orchestrator/, audit_bundle/, boxes, gates, calculate.
  • The anthropic SDK is imported *only* inside _extract_multimodal().
"""
