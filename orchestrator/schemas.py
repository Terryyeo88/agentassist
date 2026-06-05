"""
orchestrator/schemas.py — TypedDict schema definitions for the GST audit chain.

Defines the structural contracts for every data object that flows between
chain steps, gates, and the audit bundle.  No logic lives here — only type
declarations.  All TypedDicts are total (all keys required) unless a field
is typed as Optional (e.g. `str | None`).

Data flow through the chain:

    Step         Produces            Key supporting types
    ─────────────────────────────────────────────────────────────────────
    fetch      → FetchManifest       InvoiceRecord
    calculate  → F5ReturnOutput      FxInvoice, E1Candidate,
                                     CreditNoteApplied, Anomaly
    classify   → ClassifyOutput      VatGroupEntry, ClassifyIssue
    detect     → DetectOutput        DetectIssue
    compile    → CompileOutput       E1Reconciliation
    ─────────────────────────────────────────────────────────────────────

Shared across steps:
    Period          — ISO-8601 date-range dict used by every step.
    Anomaly         — Minimal doc_num + issue-string pair shared by
                      calculate and compile.

Deprecated:
    ReportInput     — Superseded by CompileOutput in T1.4; retained for
                      potential future lightweight consumers only.
"""
from __future__ import annotations

from typing import Literal, TypedDict


class Period(TypedDict):
    """Inclusive date range for an audit run, shared by every step output.

    Both dates are ISO-8601 strings in YYYY-MM-DD format.  The range is
    always treated as fully inclusive (start and end dates are both within
    scope).
    """
    start: str  # "YYYY-MM-DD"
    end: str    # "YYYY-MM-DD"


class InvoiceRecord(TypedDict):
    """A single SAP B1 document as fetched and normalised by the fetch step.

    Covers all four document types that contribute to the GST F5 return.
    All monetary values are in the document's original currency — currency
    conversion (where needed) is handled by the calculate step.

    Attributes:
        doc_num:      SAP B1 document number, unique within a doc_type.
        doc_date:     Document posting date as YYYY-MM-DD.
        doc_type:     One of the four GST-relevant SAP document types.
        doc_currency: ISO 4217 currency code (e.g. "SGD", "USD").
        doc_total:    Document-level total in doc_currency (before tax).
        card_name:    Customer or vendor name from the SAP Business Partner.
        vat_group:    SAP B1 VatGroup code (e.g. "SO", "SI", "ZR").
    """
    doc_num: int
    doc_date: str  # "YYYY-MM-DD"
    doc_type: Literal[
        "sales_invoice", "purchase_invoice",
        "sales_credit_note", "purchase_credit_note"
    ]
    doc_currency: str
    doc_total: float
    card_name: str
    vat_group: str


class FetchManifest(TypedDict):
    """Complete output of the fetch step — raw document set plus fetch metadata.

    Attributes:
        period:           The audit date range these records cover.
        fetched_at:       UTC ISO-8601 timestamp of when the fetch completed,
                          used as the deterministic report timestamp (T1.5).
        records:          Flat list of all four document types, in fetch order.
        doc_nums:         Set of all doc_num values across records, maintained
                          as a set for O(1) membership lookup in Gate 4.
        sap_inline_count: Total record count from SAP's OData $inlinecount
                          header.  None when the Service Layer omits the header;
                          Gate 1 treats this as WARN_PASS rather than failing.
    """
    period: Period
    fetched_at: str               # ISO datetime, for audit trail (T1.5)
    records: list[InvoiceRecord]  # all four doc types, flat list
    doc_nums: set[int]            # O(1) lookup used by Gate 4
    sap_inline_count: int | None  # from OData $inlinecount; None if unavailable


class VatGroupEntry(TypedDict):
    """Inventory record for a single SAP B1 VatGroup code seen in the period.

    Built by the classify step as it processes documents.  Every VatGroup
    code encountered in the fetched records gets an entry here, including
    codes that are not present in the F5 box mapping (flagged via
    `known_to_mapping = False`).

    Attributes:
        gst_category:     Human-readable GST treatment label for this group
                          (e.g. "Standard Rated", "Zero Rated", "Exempt").
        side:             Which side of the F5 return this VatGroup belongs to:
                          "sales", "purchase", or "unknown" if not in mapping.
        lt_box:           F5 box assignment for local-transaction lines
                          (e.g. "box_1_standard_rated_sales").  None when the
                          VatGroup has no local-transaction mapping.
        tt_box:           F5 box assignment for tourist-tax / total-tax lines.
                          None when the VatGroup has no such mapping.
        doc_count:        Number of documents in the period that used this code.
        known_to_mapping: False when the VatGroup code is absent from
                          F5_BOX_MAPPING in sap_b1_server.py — signals a
                          configuration gap that should be surfaced as an anomaly.
    """
    gst_category: str
    side: Literal["sales", "purchase", "unknown"]
    lt_box: str | None
    tt_box: str | None
    doc_count: int
    known_to_mapping: bool


class ClassifyIssue(TypedDict):
    """A single document-level GST classification issue found by the classify step.

    Error codes:
        E1 — VatGroup is standard-rated (SO/DS) but the document may be
             zero-rated or exempt; cross-checked against calculate in Gate 5.
        E2 — GST rate on the document does not match applicable_gst_rate.
        E3 — Exempt supply incorrectly claiming input tax credit.
        E4 — Mixed VatGroup usage within a single document.

    Attributes:
        doc_num:      SAP B1 document number of the affected document.
        doc_date:     Posting date as YYYY-MM-DD.
        doc_currency: Document currency (may differ from SGD).
        card_name:    Business partner name for human review context.
        vat_group:    The VatGroup code that triggered the issue.
        line_total:   Line-level total (pre-tax) in doc_currency.
        tax_total:    Tax amount on the line in doc_currency.
        error_code:   Classification of the issue (E1–E4).
        description:  Human-readable explanation of why the issue was raised.
    """
    doc_num: int
    doc_date: str
    doc_currency: str
    card_name: str
    vat_group: str
    line_total: float
    tax_total: float
    error_code: Literal["E1", "E2", "E3", "E4"]
    description: str


class ClassifyOutput(TypedDict):
    """Complete output of the classify step.

    Attributes:
        period:              The audit date range.
        expected_rate:       GST rate used for classification checks, taken
                             from ClientConfig (e.g. 0.07 or 0.09).
        vatgroup_inventory:  One VatGroupEntry per unique VatGroup code seen
                             in the period, keyed by VatGroup code string.
        issues:              All classification issues found in the period.
        summary:             Issue counts by error code plus total;
                             keys: "E1", "E2", "E3", "E4", "total".
    """
    period: Period
    expected_rate: float          # 0.07 or 0.09
    vatgroup_inventory: dict[str, VatGroupEntry]
    issues: list[ClassifyIssue]
    summary: dict[str, int]       # keys: E1, E2, E3, E4, total


class FxInvoice(TypedDict):
    """A document denominated in a foreign currency, flagged for manual conversion.

    The calculate step identifies these and surfaces them so the operator knows
    which documents require a manual SGD conversion before the F5 values are
    considered final.

    Attributes:
        doc_num:   SAP B1 document number.
        doc_date:  Posting date as YYYY-MM-DD.
        currency:  The non-SGD ISO 4217 currency code.
        doc_total: Document total in the foreign currency.
        card_name: Business partner name.
        type:      Document type string (mirrors InvoiceRecord.doc_type).
    """
    doc_num: int
    doc_date: str
    currency: str
    doc_total: float
    card_name: str
    type: Literal["sales", "purchase", "sales_credit_note", "purchase_credit_note"]


class E1Candidate(TypedDict):
    """A document whose VatGroup is standard-rated (SO or DS) and warrants review.

    E1 candidates are identified independently by both the calculate and
    detect steps; Gate 5 enforces that both sets of doc_nums are identical.
    Only SO and DS are E1-eligible because they are the standard-rated sales
    VatGroups in the Singapore F5 mapping.

    Attributes:
        doc_num:      SAP B1 document number.
        doc_date:     Posting date as YYYY-MM-DD.
        card_name:    Business partner name.
        doc_currency: Document currency (may be non-SGD).
        vat_group:    Always "SO" or "DS" for E1 candidates.
    """
    doc_num: int
    doc_date: str
    card_name: str
    doc_currency: str
    vat_group: Literal["SO", "DS"]


class CreditNoteApplied(TypedDict):
    """A credit note that was applied during the period and affects box values.

    Monetary fields are negative by convention — credit notes reduce the
    corresponding box totals.

    Attributes:
        doc_num:             SAP B1 document number.
        doc_date:            Posting date as YYYY-MM-DD.
        card_name:           Business partner name.
        type:                Whether this is a sales or purchase credit note.
        vat_group:           VatGroup code on the credit note line.
        line_total_applied:  Line total contribution (negative value in SGD).
        tax_total_applied:   Tax total contribution (negative value in SGD).
    """
    doc_num: int
    doc_date: str
    card_name: str
    type: Literal["sales_credit_note", "purchase_credit_note"]
    vat_group: str
    line_total_applied: float     # negative
    tax_total_applied: float      # negative


class Anomaly(TypedDict):
    """A minimal document-level anomaly record shared by calculate and compile.

    Anomalies are non-halting observations (e.g. unknown VatGroup, unexpected
    value) that the compile step surfaces in the report's surfaced_warnings
    list.  They differ from ClassifyIssue and DetectIssue in that they carry
    no severity or recommendation — they are informational flags only.

    Attributes:
        doc_num: SAP B1 document number of the affected document.
        issue:   Human-readable description of the anomaly, used verbatim
                 in warnings output and parsed by Gate 5 for VatGroup
                 extraction (format: "unknown VatGroup 'XYZ' — not in mapping").
    """
    doc_num: int
    issue: str


class F5ReturnOutput(TypedDict):
    """Complete output of the calculate step — F5 box values and supporting data.

    All monetary values in `boxes` and `credit_notes_applied` are in SGD.
    Foreign-currency documents are listed in `fx_invoices_requiring_conversion`
    and excluded from box totals until manually converted.

    Attributes:
        period:                          The audit date range.
        currency:                        Always "SGD" — box values are SGD-only.
        boxes:                           F5 return box values keyed by canonical
                                         name (box_1 through box_8).
        fx_invoices_requiring_conversion: Documents in non-SGD currencies that
                                         need manual conversion before finalising
                                         the F5 return.
        e1_candidates:                   Documents with standard-rated VatGroups
                                         (SO/DS) flagged for E1 review.
        record_counts:                   Document counts by type used to verify
                                         fetch completeness.
        credit_note_counts:              Credit note counts by type.
        credit_notes_applied:            Individual credit note line contributions,
                                         all with negative monetary values.
        anomalies:                       Non-halting per-document observations,
                                         surfaced in the report as warnings.
    """
    period: Period
    currency: Literal["SGD"]
    boxes: dict[str, float]       # box_1 through box_8
    fx_invoices_requiring_conversion: list[FxInvoice]
    e1_candidates: list[E1Candidate]
    record_counts: dict[str, int]
    credit_note_counts: dict[str, int]
    credit_notes_applied: list[CreditNoteApplied]
    anomalies: list[Anomaly]


class DetectIssue(TypedDict):
    """A single GST compliance issue found by the detect step.

    Extends the E1–E4 codes from classify with two detect-only codes:
        NO_GST_REG   — A supplier with an input tax claim has no GST
                       registration number on record (HIGH severity).
        COMPLETENESS — The fetched record count falls below the completeness
                       threshold; doc_num is None for this code since it is
                       a dataset-level rather than document-level issue.

    Attributes:
        severity:       Risk level: "HIGH", "MEDIUM", or "LOW".
        error_code:     Classification code (E1–E4, NO_GST_REG, COMPLETENESS).
        doc_num:        Affected SAP B1 document number.  None for COMPLETENESS
                        issues, which apply to the dataset rather than one doc.
        doc_date:       Posting date as YYYY-MM-DD.  None for COMPLETENESS.
        card_name:      Business partner name.  None for COMPLETENESS.
        description:    Human-readable explanation of the issue.
        recommendation: Suggested remediation action for the reviewer.
    """
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    error_code: Literal["E1", "E2", "E3", "E4", "NO_GST_REG", "COMPLETENESS"]
    doc_num: int | None           # None for COMPLETENESS
    doc_date: str | None
    card_name: str | None
    description: str
    recommendation: str


class DetectOutput(TypedDict):
    """Complete output of the detect step.

    Attributes:
        period:          The audit date range.
        severity_counts: Issue counts by severity label; Gate 4 verifies
                         that the sum equals len(issues).
                         Keys: "HIGH", "MEDIUM", "LOW".
        issues:          All compliance issues detected in the period.
    """
    period: Period
    severity_counts: dict[str, int]  # HIGH, MEDIUM, LOW
    issues: list[DetectIssue]


class E1Reconciliation(TypedDict):
    """Cross-tool E1 consistency record, built by the compile step.

    Records whether the set of E1 doc_nums from calculate exactly matches
    the set from detect.  Gate 5 enforces this equality before compile runs;
    this type preserves the reconciliation evidence in the audit bundle.

    Attributes:
        calc_doc_nums:   E1 doc_nums from F5ReturnOutput.e1_candidates.
        detect_doc_nums: E1 doc_nums from DetectOutput where error_code == "E1".
        matched:         True iff calc_doc_nums == detect_doc_nums (set equality).
    """
    calc_doc_nums: set[int]   # from F5ReturnOutput.e1_candidates
    detect_doc_nums: set[int] # from DetectOutput where error_code == "E1"
    matched: bool             # True iff sets are equal


class CompileOutput(TypedDict):
    """Aggregated output of the compile step — the complete chain result.

    Contains the unmodified outputs of all four preceding steps plus the
    cross-tool reconciliation record and any warnings accumulated during
    gating.  This is the top-level object sealed into the audit bundle and
    consumed by the PDF report builder.

    Attributes:
        period:                 The audit date range.
        fetch_manifest:         Full fetch step output (records + metadata).
        calculate:              Full calculate step output (F5 boxes + details).
        classify:               Full classify step output (issues + inventory).
        detect:                 Full detect step output (issues + severity counts).
        deduplicated_anomalies: Union of calculate.anomalies and classify's
                                unknown-VatGroup entries, de-duplicated so each
                                doc_num + issue pair appears at most once.
        e1_reconciliation:      Evidence that Gate 5 E1 set equality was verified.
        surfaced_warnings:      Human-readable warning strings accumulated from
                                WARN_PASS gate outcomes; preserved verbatim in
                                the PDF report's warnings section.
    """
    period: Period
    fetch_manifest: FetchManifest
    calculate: F5ReturnOutput
    classify: ClassifyOutput
    detect: DetectOutput
    deduplicated_anomalies: list[Anomaly]  # union of calc anomalies + classify unknowns
    e1_reconciliation: E1Reconciliation
    surfaced_warnings: list[str]           # Gate-level warnings preserved for report


class ReportInput(TypedDict):
    """DEPRECATED as of T1.4.

    T1.4 consumes the full CompileOutput JSON (written to
    exploration-notes/t1.6-tool-outputs/) directly via report.contract.load_compile_output.
    ReportInput is retained as a possible lightweight summary for future consumers
    (e.g. a machine-readable summary API) and may be removed in a later milestone.
    Do not add new fields here; extend CompileOutput / the report package instead.
    """
    period: Period
    boxes: dict[str, float]
    issues: list[ClassifyIssue | DetectIssue]  # merged, sorted by severity then doc_num
    e1_candidates: list[E1Candidate]
    anomalies: list[Anomaly]
    warnings: list[str]
    items_examined: dict[str, int]  # doc-type → count, from FetchManifest
    generated_at: str               # ISO datetime
