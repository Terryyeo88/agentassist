"""
report/constants.py — pure data; no logic, no imports.

Centralises every fixed string used by the report generator so that IRAS wording,
template labels, scope-boundary text, and the disclaimer can be updated in one
place without touching rendering or orchestration code.

APPENDIX1_WORDING source: IRAS "GST: Assisted Self-Help Kit (ASK) Annual Review
Guide", 16th Edition (30 Jan 2026), Appendix 1 "List of Errors and Areas where
Error may Occur", pp.72-73.

Label rule: verbatim category statement; trailing "(e.g., ...)" illustrative
clauses dropped; defining "(i.e., ...)" clauses kept; IRAS hyphen "-" used
(not en dash "–"); no ellipses ("…" / "...") in any value.

Routing keys for APPENDIX1_WORDING follow the pattern:
  <ERROR_CODE>              — for single-route findings (E1, NO_GST_REG, etc.)
  <ERROR_CODE>_<SUBTYPE>    — for findings that branch on VatGroup or supply side

The report generator must resolve the routing key before looking up wording.
E2 routing logic: inspect vat_group on the ClassifyIssue or DetectIssue —
  ZR / OS         → "E2_ZR"
  ES33 / ESN33    → "E2_EXEMPT"   (same wording for both Templates 4 and 5)
  BL              → "E2_BL"
  NR              → "E2_NR"
E3/E4 routing: inspect the issue's template assignment (sales vs purchase side).

Exports:
    APPENDIX1_WORDING   — routing-key → verbatim Appendix 1 category string
    TEMPLATE_INDEX      — ASK template number (1–7) → section heading string
    NOT_EXAMINED_ITEMS  — ordered list of out-of-scope areas for the report footer
    DISCLAIMER_TEXT     — verbatim disclaimer rendered in the report footer
"""
from __future__ import annotations

# from __future__ import annotations enables lowercase generic type hints
# (dict[str, str], list[str]) on Python < 3.9 without a runtime cost.


# ── Appendix 1 wording ────────────────────────────────────────────────────────
# Source: IRAS "GST: Assisted Self-Help Kit (ASK) Annual Review Guide", 16th
# Edition (30 Jan 2026), Appendix 1 "List of Errors and Areas where Error may
# Occur", pp.72-73.
# Label rule: verbatim category statement; trailing "(e.g., ...)" dropped;
# defining "(i.e., ...)" kept; hyphen "-" (not en dash); no ellipses.
# Keys are finding-routing keys; values are verbatim Appendix 1 category strings.
#
# Note: several error codes intentionally share the same Appendix 1 wording
# (E3_SALES / E3_PURCHASE, E4_SO / E4_SI, COMPLETENESS, F5_BOX_ERROR all map
# to "Over- / Under-reporting of value in GST return"). The distinct routing
# keys exist solely to steer each finding to the correct ASK template section —
# the wording lookup is a secondary step after template placement.

APPENDIX1_WORDING: dict[str, str] = {
    # E1 — FX sale coded as local standard-rated (SR / DS)
    # Template 2, Step 3A
    "E1": (
        "Wrong classification of supplies made"
    ),

    # E2 output-side — GST charged on zero-rated supply (ZR / OS)
    # Template 3, Step 3B
    "E2_ZR": (
        "Supplies previously treated as zero-rated supplies but cannot qualify for zero-rating"
    ),

    # E2 output-side — GST charged on exempt supply (ES33 / ESN33)
    # Templates 4 and 5, Step 3C.
    # The wording describes the error (wrong GST on exempt supply), not the
    # business type, so it is identical whether routed to Template 4 or 5.
    "E2_EXEMPT": (
        "Supplies previously treated as exempt supplies but cannot qualify for exemption "
        "(i.e., not relating to financial services and sale/ rental of residential properties)"
    ),

    # E2 input-side — GST carried on a blocked (Reg 26/27) expense (BL)
    # Template 6, Step 3D.1.1.h
    "E2_BL": (
        "Input tax to be disallowed - Not for business purposes and/or specific "
        "expenses disallowed under GST (General) Regulations 26 and 27"
    ),

    # E2 input-side — GST carried on a purchase from a non-GST-registered supplier (NR)
    # Template 6, Step 3D.1.1.h
    # NO_GST_REG shares this wording — both represent input tax on non-taxable supply.
    "E2_NR": (
        "Input tax to be disallowed - Purchases from non-GST registered suppliers "
        "and/or non-taxable purchases which do not attract GST"
    ),

    # E3 — standard-rated sales line (SR / DS) with zero output tax
    # Template 2, Step 3A.3.1.i
    "E3_SALES": (
        "Over- / Under-reporting of value in GST return"
    ),

    # E3 — standard-rated purchase line (TX) with zero input tax
    # Template 6, Step 3D source-doc checks
    "E3_PURCHASE": (
        "Over- / Under-reporting of value in GST return"
    ),

    # E4 — rate deviation on SR (sales side)
    # Template 2, Step 3A.3.1.i
    "E4_SO": (
        "Over- / Under-reporting of value in GST return"
    ),

    # E4 — rate deviation on TX (purchase side)
    # Template 6, Step 3D source-doc checks
    # Identical Appendix 1 wording to E4_SO; separate key for template routing.
    "E4_SI": (
        "Over- / Under-reporting of value in GST return"
    ),

    # NO_GST_REG — input tax claimed on purchase from supplier with blank GST reg no.
    # Template 6, Step 3D.1.1.h
    # Shares wording with E2_NR: both represent non-recoverable input tax.
    "NO_GST_REG": (
        "Input tax to be disallowed - Purchases from non-GST registered suppliers "
        "and/or non-taxable purchases which do not attract GST"
    ),

    # COMPLETENESS — purchase/sales ratio below threshold (possible omission)
    # Template 1, Steps 1.3a and 1.3d
    "COMPLETENESS": (
        "Over- / Under-reporting of value in GST return"
    ),

    # F5 box-level errors — computed box value != declared box value
    # Template 1, Steps 1.3b / 1.3c
    "F5_BOX_ERROR": (
        "Over- / Under-reporting of value in GST return"
    ),

    # FX invoices excluded / pending SGD conversion (informational)
    # Template 6 (purchases) / Template 2 (sales), Step 3A.3.1.iii / 3D B5
    "FX_EXCLUDED": (
        "Incorrect recording of value(s) from source document to listing "
        "and/or from listing to GST return"
    ),

    # Unknown-VatGroup anomalies (VatGroup absent from F5_BOX_MAPPING)
    # Template 1, Step 1 analytical review
    "UNKNOWN_VATGROUP": (
        "Wrong classification of supplies made"
    ),
}


# ── Template index ────────────────────────────────────────────────────────────
# Maps ASK template number to human label for report section headings.
# Keys 1–7 correspond to the seven ASK review templates; all must be present
# for a complete report — a missing key produces a gap in the section structure.

TEMPLATE_INDEX: dict[int, str] = {
    1: "Template 1 — Steps 1, 2 & 4: Declaration Review and Financial-Statement Reconciliation",
    2: "Template 2 — Step 3A: Standard-rated Supplies and Output Tax",
    3: "Template 3 — Step 3B: Zero-rated Supplies",
    4: "Template 4 — Step 3C-1: Exempt Supplies (business actively making exempt supplies)",
    5: "Template 5 — Step 3C-2: Exempt Supplies (general business with incidental exempt supplies)",
    6: "Template 6 — Step 3D: Input Tax and Refunds Claimed",
    7: "Template 7 — Step 3E: Imports with GST Suspended or Deferred",
}


# ── Coverage boundary — items not examined ────────────────────────────────────
# Ordered per Document 1 coverage gap analysis. These appear verbatim in the
# report's "Items not examined" section so the reviewer knows the scope boundary.
# Order is significant: items are rendered in list order, so place higher-risk
# exclusions (e.g. journal entries, partial exemption) before lower-risk ones.

NOT_EXAMINED_ITEMS: list[str] = [
    "Manual journal entries (Journal Entries entity not examined; GST-relevant "
    "journals are outside the scope of this review)",

    "Transactions coded to VatGroups outside the client configuration mapping "
    "(custom VatGroups are flagged as anomalies and excluded from all box totals; "
    "their full GST treatment is not verified)",

    "Partial-exemption apportionment (TX-RE and mixed standard-rated / exempt "
    "supply scenarios; apportionment formula and De Minimis test not computed)",

    "Scheme-specific imports with GST suspended or deferred (Boxes 9, 19, 21 "
    "not computed; MES / IGDS scheme approval status and import-permit verification "
    "not performed — ASK Step 3E)",

    "Source-document and export evidence verification (physical tax invoices, "
    "bills of lading, air waybills, and import permits not examined — "
    "ASK Steps 3A.3, 3B.3.2, 3D.3)",

    "Financial statement reconciliation (ASK Step 4: Total Supplies vs Sales / "
    "Turnover from management accounts not performed; financial statements not ingested)",

    "Declared-vs-computed F5 comparison (filed GST return not ingested; "
    "reconciliation of SAP-computed box figures against submitted declared values "
    "requires the filed return as a second input — ASK Steps 1.3b / 1.3c)",

    "Invoice sequence gap detection (running-sequence continuity not verified against "
    "company-wide DocNum history — ASK Annual Review Guide §10.1(c)(i))",

    "Duplicate input-tax claims (cross-vendor deduplication using supplier invoice "
    "reference not performed; requires NumAtCard population in SAP B1 — "
    "ASK Annual Review Guide §10.1(d)(i))",

    "Time-of-supply compliance (transaction payment-date ingestion not implemented; "
    "time-of-supply verification not performed)",

    "Reverse charge on imported services and Overseas Vendor Registration (OVR) "
    "output tax (Boxes 14–17 and reverse-charge accounting not implemented)",

    "Annual analytical review (TP/TS ratio and period-over-period box fluctuations "
    "not performed — supply --analytical-review flag to enable "
    "ASK Steps 1.3a and 1.3d checks)",

    "GST control-account ledger reconciliation (Xero 820 control-account postings "
    "not reconciled against the declared F5 return; supply the control-account "
    "'Account Transactions' export and the F5 workbook to enable — ASK Step 1.3e)",
]


# ── Disclaimer ────────────────────────────────────────────────────────────────
# Rendered verbatim in the report footer. Any change to this text should be
# reviewed against the approved legal language — do not paraphrase or shorten.

DISCLAIMER_TEXT: str = (
    "AgentAssist surfaces candidates based on automated analysis of SAP Business One "
    "transaction data and does not certify GST compliance or make filing determinations. "
    "All findings are candidates requiring review by the practitioner of record. "
    "The reviewer of record signs the final report and bears sole professional "
    "responsibility for the accuracy of the GST return and all filing decisions. "
    "This report is not a substitute for professional GST advice. "
    "AgentAssist is not an SCTP-accredited ATA (GST) or ATP (GST)."
)
