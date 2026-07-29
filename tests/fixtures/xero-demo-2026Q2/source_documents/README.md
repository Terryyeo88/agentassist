Source documents for the 2026 Q2 Xero demo company.

CANONICAL LAYOUT (D-2026-07-29, ruling on open item #51):
  - Flat. No nesting. Moved from Xero-imports/source_invoices/source_invoices/,
    which was doubly nested by accident.
  - FILENAME STEM IS THE REFERENCE. BILL-3002.pdf is the source document for
    the finding carrying doc_num "BILL-3002". Do NOT normalise to INV-<n>.pdf:
    the Xero reference is the document's own identity, printed on its face and
    carried by the finding. Forcing it into the SAP corpus's convention would
    recreate the namespace collision D-34 closed.
  - Lives beside the corpus it belongs to. Ground truth for these documents is
    ../fixture_manifest.csv.

COVERAGE IS PARTIAL, DELIBERATELY: 10 documents against 38 baits, all from
batch 1. Batch 2 has none. That is the realistic case — clients supply partial
document sets constantly — and it exercises the honest-degrade path better
than a complete corpus would.

Read by NO test today. T-E (source-document ingestion) is unbuilt; no upload
endpoint accepts documents.

BILL-3002.pdf is the ready-made gst_amount_mismatch bait: the invoice face
shows 9% / 360.00 while the ledger booked 8% / 320.00.
