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
        "doc_num": int(doc.get("DocNum") or 0),
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
    entity: str, period_start: str, period_end: str
) -> tuple[list[dict], int | None]:
    """Fetch all records for one OData entity and probe for the SAP inline count.

    Performs two calls to the Service Layer:
        1. A count-only probe ($top=0, $inlinecount=allpages) to retrieve
           the total record count without fetching any document payloads.
        2. The full paginated fetch via sap_b1_server._fetch_invoices_paginated.

    Args:
        entity:       OData entity set name (e.g. "Invoices", "CreditNotes").
        period_start: Inclusive start date as YYYY-MM-DD.
        period_end:   Inclusive end date as YYYY-MM-DD.

    Returns:
        tuple[list[dict], int | None]: A two-element tuple:
            - records: List of raw OData document dicts for the entity.
            - inline_count: Total record count from SAP's odata.count field,
              or None if the Service Layer did not return the field.  A None
              here causes Gate 1 to emit a WARN_PASS rather than failing.
    """
    date_filter = f"DocDate ge '{period_start}' and DocDate le '{period_end}'"

    # Probe for total count using OData v3 $inlinecount=allpages.
    # SAP B1 Service Layer returns the total as "odata.count" (no @ prefix).
    inline_count: int | None = None
    try:
        count_resp = sap_b1_server.sap.get(f"/{entity}", params={
            "$filter": date_filter,
            # $top=0 returns only the metadata (including the inline count)
            # without fetching any actual document payloads — an efficient
            # count-only probe that avoids an extra full-page round trip.
            "$top": 0,
            "$inlinecount": "allpages",
        })
        raw = count_resp.get("odata.count")
        if raw is not None:
            inline_count = int(raw)
    except Exception as exc:
        log.warning(f"fetch: $inlinecount probe for {entity} failed ({exc}) — Gate 1 will warn")

    records = sap_b1_server._fetch_invoices_paginated(entity, period_start, period_end)
    return records, inline_count


# ---------------------------------------------------------------------------
# Step functions
# ---------------------------------------------------------------------------

def fetch(client_config: ClientConfig, period: Period) -> FetchManifest:
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

    Returns:
        FetchManifest: All four document types in a flat list with fetch
            metadata.  fetched_at is stamped at completion, not start, so
            it brackets the full SAP round-trip time.
    """
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
        docs, count = _fetch_entity(entity, period_start, period_end)
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


def calculate(client_config: ClientConfig, period: Period) -> F5ReturnOutput:
    """Step c — invoke calculate_f5_return and return as F5ReturnOutput.

    Delegates entirely to the sap_b1_server tool, which owns all F5 box
    logic and line-level currency handling.  The JSON string is parsed here
    and returned as-is; no field remapping is performed.

    Args:
        client_config: Validated ClientConfig (not used directly; present for
                       signature consistency across all step functions).
        period:        Audit date range with "start" and "end" YYYY-MM-DD keys.

    Returns:
        F5ReturnOutput: Parsed result from calculate_f5_return, containing
            F5 box values, E1 candidates, FX invoices, and anomalies.
            Box keys are the canonical Gate 2 keys — verified against
            sap_b1_server.py lines 441-449.  No remapping needed.
    """
    result_str = sap_b1_server.calculate_f5_return(period["start"], period["end"])
    result: dict = json.loads(result_str)
    # Box keys emitted by calculate_f5_return are the canonical Gate 2 keys —
    # verified against sap_b1_server.py lines 441-449. No remapping needed.
    return result  # type: ignore[return-value]


def classify(client_config: ClientConfig, period: Period) -> ClassifyOutput:
    """Step b — invoke validate_invoice_tax_codes and return as ClassifyOutput.

    Passes applicable_gst_rate from the client config so the tool applies the
    correct expected rate when checking each document's line-level tax codes.

    Args:
        client_config: Validated ClientConfig; applicable_gst_rate is forwarded
                       to the SAP tool as the expected GST rate.
        period:        Audit date range with "start" and "end" YYYY-MM-DD keys.

    Returns:
        ClassifyOutput: Parsed result from validate_invoice_tax_codes, containing
            the vatgroup_inventory, classification issues (E1–E4), and summary
            counts.
    """
    result_str = sap_b1_server.validate_invoice_tax_codes(
        period["start"],
        period["end"],
        expected_rate=client_config.applicable_gst_rate,
    )
    return json.loads(result_str)  # type: ignore[return-value]


def detect(client_config: ClientConfig, period: Period) -> DetectOutput:
    """Step d — invoke detect_gst_errors and return as DetectOutput.

    Passes applicable_gst_rate from the client config so the tool can
    evaluate rate-specific compliance rules (e.g. E2 rate mismatch).

    Args:
        client_config: Validated ClientConfig; applicable_gst_rate is forwarded
                       to the SAP tool as the expected GST rate.
        period:        Audit date range with "start" and "end" YYYY-MM-DD keys.

    Returns:
        DetectOutput: Parsed result from detect_gst_errors, containing
            severity-bucketed compliance issues (E1–E4, NO_GST_REG,
            COMPLETENESS) and per-severity counts.
    """
    result_str = sap_b1_server.detect_gst_errors(
        period["start"],
        period["end"],
        expected_rate=client_config.applicable_gst_rate,
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

    return {
        "period": manifest["period"],
        "fetch_manifest": manifest,
        "calculate": calc,
        "classify": cls,
        "detect": det,
        "deduplicated_anomalies": deduped,
        "e1_reconciliation": e1_recon,
        "surfaced_warnings": warnings,
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
