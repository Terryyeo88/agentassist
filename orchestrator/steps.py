"""
orchestrator/steps.py — The five step functions that form the GST audit chain.

Each step wraps one or more sap_b1_server tool calls, normalises the output
into a typed schema dict, and returns it to chain.py for gate validation.
Steps are pure in the sense that they do not mutate shared state beyond the
module-global SAP session (configured by chain.py before any step runs).

Execution order in chain.py:
    1. fetch      — pull all four SAP document types; build FetchManifest.
    2. calculate  — compute F5 box values via calculate_f5_return.
    3. classify   — validate VatGroup assignments via validate_invoice_tax_codes.
    4. detect     — find compliance issues via detect_gst_errors.
    5. compile    — aggregate steps 1–4 into a single CompileOutput.

Also exposes:
    report_input  — DEPRECATED (T1.4); converts CompileOutput to the legacy
                    ReportInput flat summary.  Retained for signature stability.

Private helpers:
    _doc_to_record   — Normalise a raw SAP document dict to InvoiceRecord.
    _fetch_entity    — Paginate one OData entity and probe for $inlinecount.

Dependencies:
    sap_b1_server   Custom MCP server (mcp-servers/custom/); must be
                    configured via sap_b1_server.configure_client() before
                    any step function is called.
    config.loader   ClientConfig (applicable_gst_rate).
    orchestrator.schemas  All TypedDict return types.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Put mcp-servers/custom on sys.path so sap_b1_server is importable.
# The directory name has a hyphen, so it cannot be a Python package — path insertion
# is the only clean import mechanism here.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_CUSTOM = _REPO_ROOT / "mcp-servers" / "custom"
if str(_MCP_CUSTOM) not in sys.path:
    sys.path.insert(0, str(_MCP_CUSTOM))
# Ensure repo root is on path for config.loader (sap_b1_server also adds it, but
# we may be imported before sap_b1_server is fully loaded).
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import sap_b1_server  # noqa: E402 — path manipulation above is intentional

from config.loader import ClientConfig  # noqa: E402

from .schemas import (  # noqa: E402
    Anomaly,
    ClassifyOutput,
    CompileOutput,
    DetectOutput,
    E1Reconciliation,
    F5ReturnOutput,
    FetchManifest,
    InvoiceRecord,
    Period,
    ReportInput,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coerce_doc_num(raw):
    """Coerce a raw DocNum to the chain's document-number value.

    SAP B1 DocNum is an integer document number, so the SAP path always yields an int —
    BYTE-IDENTICAL to the prior ``int(doc.get("DocNum") or 0)`` (numeric or numeric-string →
    int; None/"" → 0). The string fallback exists only for a NON-SAP feeder whose external
    reference is non-numeric (e.g. XeroF5ChainReader's "INV-2001"/"BILL-3002"): rather than
    crash the deterministic chain, the reference is carried through verbatim so it surfaces in
    findings. No SAP-path value changes — only a previously-unreachable input type is handled.
    """
    if raw is None or raw == "":
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return str(raw)


def _doc_to_record(doc: dict, doc_type: str) -> InvoiceRecord:
    """Normalise a raw SAP B1 OData document dict into an InvoiceRecord.

    Applies defensive coercions for fields that SAP may return as None,
    missing, or with extra whitespace.  This is the single place where
    raw OData field names (PascalCase) are mapped to the chain's snake_case
    schema field names.

    Known simplification: vat_group reflects only the first document line.
    FetchManifest is header-granular; the SAP tools (calculate_f5_return,
    validate_invoice_tax_codes, detect_gst_errors) own per-line truth.
    If a document has multiple distinct line VatGroups this field reflects
    only the first — known simplification for Gate 4 traceability.

    Args:
        doc:      Raw OData document dict as returned by the SAP B1 Service
                  Layer, with keys like "DocNum", "DocDate", "DocumentLines".
        doc_type: Canonical doc-type string to embed in the record
                  (e.g. "sales_invoice", "purchase_credit_note").

    Returns:
        InvoiceRecord: Normalised, typed record ready to be added to
            FetchManifest.records.
    """
    lines = doc.get("DocumentLines", [])
    # vat_group = first line's VatGroup. FetchManifest is header-granular; the
    # tools (calculate_f5_return, validate_invoice_tax_codes, detect_gst_errors)
    # own per-line truth. If a document has multiple distinct line VatGroups this
    # field reflects only the first — known simplification for Gate 4 traceability.
    first_vg = (lines[0].get("VatGroup") or "").strip() if lines else ""
    return {
        "doc_num": _coerce_doc_num(doc.get("DocNum")),
        # SAP sometimes returns a full datetime string "YYYY-MM-DDTHH:MM:SS";
        # slice to 10 chars to keep only the date portion.
        "doc_date": str(doc.get("DocDate", ""))[:10],
        "doc_type": doc_type,
        # Normalise currency to uppercase and default to "SGD" when absent or null.
        "doc_currency": (doc.get("DocCurrency") or "SGD").strip().upper(),
        # Coerce None → 0.0 so downstream arithmetic never encounters NoneType.
        "doc_total": float(doc.get("DocTotal") or 0),
        "card_name": doc.get("CardName", ""),
        "vat_group": first_vg,
    }


def _fetch_entity(
    entity: str, period_start: str, period_end: str, reader: "sap_b1_server.ChainReader"
) -> tuple[list[dict], int | None]:
    """Fetch all records for one OData entity and probe for the SAP inline count.

    Reads both surfaces through the injected ChainReader (T2.23 chain source seam):
        1. reader.count          — the S0 count-only probe ($top=0, $inlinecount).
        2. reader.fetch_invoices — the S1 full paginated line-level fetch.

    Args:
        entity:       OData entity set name (e.g. "Invoices", "CreditNotes").
        period_start: Inclusive start date as YYYY-MM-DD.
        period_end:   Inclusive end date as YYYY-MM-DD.
        reader:       ChainReader providing the S0/S1 reads.

    Returns:
        tuple[list[dict], int | None]: A two-element tuple:
            - records: List of raw OData document dicts for the entity.
            - inline_count: Total record count from SAP's odata.count field,
              or None if the Service Layer did not return the field.  A None
              here causes Gate 1 to emit a WARN_PASS rather than failing.
    """
    inline_count = reader.count(entity, period_start, period_end)
    records = reader.fetch_invoices(entity, period_start, period_end)
    return records, inline_count


# ---------------------------------------------------------------------------
# Step functions
# ---------------------------------------------------------------------------

def fetch(client_config: ClientConfig, period: Period,
          reader: "sap_b1_server.ChainReader | None" = None) -> FetchManifest:
    """Step a — pull all four document types from SAP and build the FetchManifest.

    Fetches Invoices, PurchaseInvoices, CreditNotes, and PurchaseCreditNotes
    in sequence, normalises each document to InvoiceRecord, and assembles them
    into a flat FetchManifest.  Also accumulates the per-entity $inlinecount
    values; if any entity fails to return a count the aggregate is set to None
    so Gate 1 can signal a WARN_PASS rather than a spurious mismatch.

    Args:
        client_config: Validated ClientConfig (not used directly here but
                       required for step-function signature consistency).
        period:        Audit date range with "start" and "end" YYYY-MM-DD keys.
        reader:        Optional ChainReader (T2.23). None -> default SAP-backed
                       reader. run_chain threads one shared reader through the run.

    Returns:
        FetchManifest: All four document types in a flat list with fetch
            metadata.  fetched_at is stamped at completion, not start, so
            it brackets the full SAP round-trip time.
    """
    reader = reader if reader is not None else sap_b1_server.SapChainReader()
    period_start = period["start"]
    period_end = period["end"]

    # Pairs of (SAP OData entity name, canonical doc_type string for InvoiceRecord).
    _ENTITIES: list[tuple[str, str]] = [
        ("Invoices",            "sales_invoice"),
        ("PurchaseInvoices",    "purchase_invoice"),
        ("CreditNotes",         "sales_credit_note"),
        ("PurchaseCreditNotes", "purchase_credit_note"),
    ]

    all_records: list[InvoiceRecord] = []
    total_inline = 0
    # Track whether every entity returned a count; a single missing count means
    # we cannot produce a meaningful aggregate and must fall back to None.
    inline_available = True

    for entity, doc_type in _ENTITIES:
        docs, count = _fetch_entity(entity, period_start, period_end, reader)
        for doc in docs:
            all_records.append(_doc_to_record(doc, doc_type))
        if count is not None:
            total_inline += count
        else:
            inline_available = False
        log.info(f"fetch: {entity} → {len(docs)} docs (inline_count={count})")

    # Exclude doc_num=0 — _doc_to_record emits 0 when DocNum is missing or null,
    # and 0 is not a valid SAP document number so it must not populate the lookup set.
    doc_nums = {r["doc_num"] for r in all_records if r["doc_num"]}

    return {
        "period": period,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "records": all_records,
        "doc_nums": doc_nums,
        # Expose the aggregate count only when all four entities supplied one;
        # a partial sum would give Gate 1 a misleadingly small expected total.
        "sap_inline_count": total_inline if inline_available else None,
    }


def fetch_listing_data(client_config: ClientConfig, period: Period,
                       reader: "sap_b1_server.ChainReader | None" = None) -> dict:
    """Fetch minimal header data for T2.10 SEQ_GAP and DUP_CLAIM listing checks.

    The four header-only OData queries (no DocumentLines) — two period-scoped and
    two company-wide — are the S5 read surface; T2.23 routes them through
    reader.fetch_listing (default = SAP-backed). The reader returns the same
    four-key dict this step has always returned:
      - period_sales_headers:  Invoices in the reviewed period (DocNum,Series,Cancelled)
      - period_purch_headers:  PurchaseInvoices in period (DocNum,Series,Cancelled,
                               CardCode,NumAtCard,DocTotal)
      - all_sales_headers:     ALL Invoices company-wide (DocNum,Series,Cancelled)
      - all_purch_headers:     ALL PurchaseInvoices company-wide (DocNum,Series,Cancelled)

    The company-wide queries (no date filter) are required by SEQ_GAP so it can
    distinguish "DocNum issued in another period" from "DocNum never issued anywhere".

    Args:
        client_config: Validated ClientConfig (not used directly; present for
                       step-function signature consistency).
        period:        Audit date range with "start" and "end" YYYY-MM-DD keys.
        reader:        Optional ChainReader (T2.23). None -> default SAP-backed reader.

    Returns:
        dict with keys: period_sales_headers, period_purch_headers,
                        all_sales_headers, all_purch_headers.
    """
    reader = reader if reader is not None else sap_b1_server.SapChainReader()
    result = reader.fetch_listing(period)

    log.info(
        f"fetch_listing_data: period_sales={len(result['period_sales_headers'])} "
        f"period_purch={len(result['period_purch_headers'])} "
        f"all_sales={len(result['all_sales_headers'])} "
        f"all_purch={len(result['all_purch_headers'])}"
    )
    return result


def calculate(client_config: ClientConfig, period: Period,
              reader: "sap_b1_server.ChainReader | None" = None) -> F5ReturnOutput:
    """Step c — invoke calculate_f5_return and return as F5ReturnOutput.

    Delegates entirely to the sap_b1_server tool, which owns all F5 box
    logic and line-level currency handling.  The JSON string is parsed here
    and returned as-is; no field remapping is performed.

    Args:
        client_config: Validated ClientConfig (not used directly; present for
                       signature consistency across all step functions).
        period:        Audit date range with "start" and "end" YYYY-MM-DD keys.
        reader:        Optional ChainReader (T2.23). None -> default SAP-backed reader.

    Returns:
        F5ReturnOutput: Parsed result from calculate_f5_return, containing
            F5 box values, E1 candidates, FX invoices, and anomalies.
            Box keys are the canonical Gate 2 keys — verified against
            sap_b1_server.py lines 441-449.  No remapping needed.
    """
    result_str = sap_b1_server.calculate_f5_return(period["start"], period["end"], reader=reader)
    result: dict = json.loads(result_str)
    # Box keys emitted by calculate_f5_return are the canonical Gate 2 keys —
    # verified against sap_b1_server.py lines 441-449. No remapping needed.
    return result  # type: ignore[return-value]


def classify(client_config: ClientConfig, period: Period,
             reader: "sap_b1_server.ChainReader | None" = None) -> ClassifyOutput:
    """Step b — invoke validate_invoice_tax_codes and return as ClassifyOutput.

    Passes applicable_gst_rate from the client config so the tool applies the
    correct expected rate when checking each document's line-level tax codes.

    Args:
        client_config: Validated ClientConfig; applicable_gst_rate is forwarded
                       to the SAP tool as the expected GST rate.
        period:        Audit date range with "start" and "end" YYYY-MM-DD keys.
        reader:        Optional ChainReader (T2.23). None -> default SAP-backed reader.

    Returns:
        ClassifyOutput: Parsed result from validate_invoice_tax_codes, containing
            the vatgroup_inventory, classification issues (E1–E4), and summary
            counts.
    """
    result_str = sap_b1_server.validate_invoice_tax_codes(
        period["start"],
        period["end"],
        expected_rate=client_config.applicable_gst_rate,
        reader=reader,
    )
    return json.loads(result_str)  # type: ignore[return-value]


def detect(client_config: ClientConfig, period: Period,
           reader: "sap_b1_server.ChainReader | None" = None) -> DetectOutput:
    """Step d — invoke detect_gst_errors and return as DetectOutput.

    Passes applicable_gst_rate from the client config so the tool can
    evaluate rate-specific compliance rules (e.g. E2 rate mismatch).

    Args:
        client_config: Validated ClientConfig; applicable_gst_rate is forwarded
                       to the SAP tool as the expected GST rate.
        period:        Audit date range with "start" and "end" YYYY-MM-DD keys.
        reader:        Optional ChainReader (T2.23). None -> default SAP-backed reader.

    Returns:
        DetectOutput: Parsed result from detect_gst_errors, containing
            severity-bucketed compliance issues (E1–E4, NO_GST_REG,
            COMPLETENESS) and per-severity counts.
    """
    result_str = sap_b1_server.detect_gst_errors(
        period["start"],
        period["end"],
        expected_rate=client_config.applicable_gst_rate,
        reader=reader,
    )
    return json.loads(result_str)  # type: ignore[return-value]


# Severity sort order for report_input() issue sorting; lower value = higher priority.
_SEV_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def compile(  # noqa: A001 — shadows builtin; intentional, chain.py does not use builtin compile
    manifest: FetchManifest,
    calc: F5ReturnOutput,
    cls: ClassifyOutput,
    det: DetectOutput,
) -> CompileOutput:
    """Step e — aggregate the four step outputs into a single CompileOutput.

    Performs three synthesis operations on top of a plain aggregation:
        1. Anomaly deduplication: merges calculate anomalies with classify's
           unknown-VatGroup entries into a single de-duplicated list.
        2. E1 reconciliation: records whether calculate and detect agree on
           the set of E1 doc_nums (Gate 5 enforces this; compile preserves
           the evidence in the bundle).
        3. Warning assembly: builds surfaced_warnings deterministically from
           the step outputs — no log scraping.

    Args:
        manifest: FetchManifest from the fetch step.
        calc:     F5ReturnOutput from the calculate step.
        cls:      ClassifyOutput from the classify step.
        det:      DetectOutput from the detect step.

    Returns:
        CompileOutput: Single aggregated dict ready for sealing into the
            audit bundle and consumption by the PDF report builder.
    """
    # --- Anomaly deduplication ---

    # Deduplicate on issue string (not doc_num) so the same textual observation
    # from two sources appears only once in the report's warnings section.
    seen: set[str] = set()
    deduped: list[Anomaly] = []
    for a in calc["anomalies"]:
        if a["issue"] not in seen:
            seen.add(a["issue"])
            deduped.append({"doc_num": a["doc_num"], "issue": a["issue"]})
    for vg, entry in cls["vatgroup_inventory"].items():
        if not entry["known_to_mapping"]:
            text = f"unknown VatGroup '{vg}' present in classify inventory"
            if text not in seen:
                seen.add(text)
                # doc_num = -1 signals that this anomaly is VatGroup-level (an
                # inventory observation), not tied to any single document.
                deduped.append({"doc_num": -1, "issue": text})

    # --- E1 reconciliation ---

    # E1 reconciliation across calculate and detect.
    calc_e1: set[int] = {c["doc_num"] for c in calc["e1_candidates"]}
    detect_e1: set[int] = {i["doc_num"] for i in det["issues"] if i["error_code"] == "E1"}
    e1_recon: E1Reconciliation = {
        "calc_doc_nums": calc_e1,
        "detect_doc_nums": detect_e1,
        "matched": calc_e1 == detect_e1,
    }

    # --- Warning assembly ---

    # Surfaced warnings built deterministically — no log scraping.
    warnings: list[str] = []
    if manifest["sap_inline_count"] is None:
        warnings.append(
            "Gate 1: SAP $inlinecount unavailable on this instance"
            " — pagination completeness not verified."
        )
    for a in calc["anomalies"]:
        warnings.append(f"Gate 2 anomaly: doc_num={a['doc_num']} — {a['issue']}")
    for vg, entry in cls["vatgroup_inventory"].items():
        if not entry["known_to_mapping"]:
            warnings.append(f"Gate 3: VatGroup '{vg}' not in mapping.")

    # --- R-2: unmapped codes must never SILENTLY reduce a box -------------------
    # D-2026-09-21-unmapped-codes. calculate excluded these lines from the box totals
    # (the `continue` in each accumulator). Record WHICH boxes can no longer be vouched
    # for, and surface a finding carrying the scale of the exclusion. Ruling Q3 option (a):
    # an unmapped code has NO F5_BOX_MAPPING entry, so its SIDE is genuinely unknowable —
    # inferring one from doc_type would be tax semantics by inference. Every value box is
    # therefore blanked, and the derived boxes follow their inputs. NO THRESHOLD: one
    # excluded line is enough. Emitted only when something was actually excluded, so a
    # clean run stays byte-identical and the replay oracle needs no re-freeze.
    box_completeness = None
    excluded = calc.get("unmapped_code_totals") or []
    if excluded:
        codes = ", ".join(f"'{e['code']}'" for e in excluded)
        lines = sum(e["line_count"] for e in excluded)
        box_completeness = {
            "status": "incomplete",
            "excluded_codes": excluded,
            "blanked_boxes": list(calc["boxes"]),
            "excluded_line_count": lines,
            "reason": (
                f"{lines} line(s) carrying unrecognised tax code(s) {codes} were excluded "
                "from the box totals, so no figure on this return can be vouched for."
            ),
        }
        det["issues"].append({
            "severity": "HIGH",
            "error_code": "UNMAPPED_TAX_CODE",
            # Not tied to one document: the exclusion is a property of the code across the
            # period. Gate 4 tolerates a None doc_num explicitly (no dangling reference).
            "doc_num": None,
            "doc_date": "",
            "card_name": "",
            "description": (
                f"Tax code(s) {codes} were not recognised, so {lines} line(s) were left out "
                "of every F5 box total. The affected figures are not shown: a partial box "
                "can be acted on, and would be more dangerous than a blank one. "
                + "; ".join(
                    f"{e['code']}: {e['line_count']} line(s), net {e['net_total']:,.2f}, "
                    f"GST {e['tax_total']:,.2f}"
                    for e in excluded
                )
                + "."
            ),
            "recommendation": (
                "A code listed here may be perfectly legitimate and simply undeclared — "
                "this is a candidate for review, not a verdict. Map each code to its "
                "canonical VatGroup in the client configuration, then re-run."
            ),
        })
        det["severity_counts"]["HIGH"] = det["severity_counts"].get("HIGH", 0) + 1

    return {
        "period": manifest["period"],
        "fetch_manifest": manifest,
        "calculate": calc,
        "classify": cls,
        "detect": det,
        "deduplicated_anomalies": deduped,
        **({"box_completeness": box_completeness} if box_completeness else {}),
        "e1_reconciliation": e1_recon,
        "surfaced_warnings": warnings,
        # T2.9: populated by run_chain() when declared_f5 is supplied;
        # always present as an empty list so the schema key is always defined.
        "declared_f5_findings": [],
        # T2.10: populated by run_chain() after listing fetch; always [] here.
        "listing_findings": [],
    }


def report_input(compiled: CompileOutput) -> ReportInput:
    """Step f — produce a lightweight ReportInput summary dict.

    DEPRECATED as of T1.4: the report package (report.contract.load_compile_output,
    report.report.build_report, report.render.render_pdf) consumes the full CompileOutput
    JSON written to disk by run_chain, not this flat summary. This step is retained so
    run_chain's return signature and callers remain unchanged; it may be removed in a
    later milestone.

    Note for T1.4 integration: classify issues carry vat_group, line_total, tax_total
    which enable E2-by-VatGroup template routing (Document-2). Join to detect issues
    on (doc_num, error_code) at render time — deferred reconciliation, not done here.

    Args:
        compiled: CompileOutput from the compile step — the full aggregated result.

    Returns:
        ReportInput: Flat summary dict with issues sorted by severity then doc_num,
            a doc-type frequency count in items_examined, and a fresh generated_at
            timestamp.
    """
    # Sort by severity priority first (HIGH=0, MEDIUM=1, LOW=2), then by doc_num
    # ascending.  COMPLETENESS issues have doc_num=None; float("inf") sorts them
    # to the end so document-level issues always appear before dataset-level ones.
    issues = sorted(
        compiled["detect"]["issues"],
        key=lambda i: (
            _SEV_ORDER.get(i.get("severity", "LOW"), 2),
            i["doc_num"] if i["doc_num"] is not None else float("inf"),
        ),
    )

    # Build a frequency count of processed documents by type for the report header.
    items_examined: dict[str, int] = {}
    for r in compiled["fetch_manifest"]["records"]:
        items_examined[r["doc_type"]] = items_examined.get(r["doc_type"], 0) + 1

    return {
        "period": compiled["period"],
        "boxes": compiled["calculate"]["boxes"],
        "issues": issues,  # type: ignore[typeddict-item]
        "e1_candidates": compiled["calculate"]["e1_candidates"],
        "anomalies": compiled["deduplicated_anomalies"],
        "warnings": compiled["surfaced_warnings"],
        "items_examined": items_examined,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
