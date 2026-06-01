from __future__ import annotations

from typing import Literal, TypedDict


class Period(TypedDict):
    start: str  # "YYYY-MM-DD"
    end: str    # "YYYY-MM-DD"


class InvoiceRecord(TypedDict):
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
    period: Period
    fetched_at: str               # ISO datetime, for audit trail (T1.5)
    records: list[InvoiceRecord]  # all four doc types, flat list
    doc_nums: set[int]            # O(1) lookup used by Gate 4
    sap_inline_count: int | None  # from OData $inlinecount; None if unavailable


class VatGroupEntry(TypedDict):
    gst_category: str
    side: Literal["sales", "purchase", "unknown"]
    lt_box: str | None
    tt_box: str | None
    doc_count: int
    known_to_mapping: bool


class ClassifyIssue(TypedDict):
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
    period: Period
    expected_rate: float          # 0.07 or 0.09
    vatgroup_inventory: dict[str, VatGroupEntry]
    issues: list[ClassifyIssue]
    summary: dict[str, int]       # keys: E1, E2, E3, E4, total


class FxInvoice(TypedDict):
    doc_num: int
    doc_date: str
    currency: str
    doc_total: float
    card_name: str
    type: Literal["sales", "purchase", "sales_credit_note", "purchase_credit_note"]


class E1Candidate(TypedDict):
    doc_num: int
    doc_date: str
    card_name: str
    doc_currency: str
    vat_group: Literal["SO", "DS"]


class CreditNoteApplied(TypedDict):
    doc_num: int
    doc_date: str
    card_name: str
    type: Literal["sales_credit_note", "purchase_credit_note"]
    vat_group: str
    line_total_applied: float     # negative
    tax_total_applied: float      # negative


class Anomaly(TypedDict):
    doc_num: int
    issue: str


class F5ReturnOutput(TypedDict):
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
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    error_code: Literal["E1", "E2", "E3", "E4", "NO_GST_REG", "COMPLETENESS"]
    doc_num: int | None           # None for COMPLETENESS
    doc_date: str | None
    card_name: str | None
    description: str
    recommendation: str


class DetectOutput(TypedDict):
    period: Period
    severity_counts: dict[str, int]  # HIGH, MEDIUM, LOW
    issues: list[DetectIssue]


class E1Reconciliation(TypedDict):
    calc_doc_nums: set[int]   # from F5ReturnOutput.e1_candidates
    detect_doc_nums: set[int] # from DetectOutput where error_code == "E1"
    matched: bool             # True iff sets are equal


class CompileOutput(TypedDict):
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
