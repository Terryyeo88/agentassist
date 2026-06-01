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
    lines = doc.get("DocumentLines", [])
    # vat_group = first line's VatGroup. FetchManifest is header-granular; the
    # tools (calculate_f5_return, validate_invoice_tax_codes, detect_gst_errors)
    # own per-line truth. If a document has multiple distinct line VatGroups this
    # field reflects only the first — known simplification for Gate 4 traceability.
    first_vg = (lines[0].get("VatGroup") or "").strip() if lines else ""
    return {
        "doc_num": int(doc.get("DocNum") or 0),
        "doc_date": str(doc.get("DocDate", ""))[:10],
        "doc_type": doc_type,
        "doc_currency": (doc.get("DocCurrency") or "SGD").strip().upper(),
        "doc_total": float(doc.get("DocTotal") or 0),
        "card_name": doc.get("CardName", ""),
        "vat_group": first_vg,
    }


def _fetch_entity(
    entity: str, period_start: str, period_end: str
) -> tuple[list[dict], int | None]:
    """
    Fetch all records for an OData entity and probe for the SAP inline count.
    Returns (records, inline_count_or_none).
    inline_count is None when the Service Layer does not honour $inlinecount.
    """
    date_filter = f"DocDate ge '{period_start}' and DocDate le '{period_end}'"

    # Probe for total count using OData v3 $inlinecount=allpages.
    # SAP B1 Service Layer returns the total as "odata.count" (no @ prefix).
    inline_count: int | None = None
    try:
        count_resp = sap_b1_server.sap.get(f"/{entity}", params={
            "$filter": date_filter,
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
    """Step a — pull all four document types and build the fetch manifest."""
    period_start = period["start"]
    period_end = period["end"]

    _ENTITIES: list[tuple[str, str]] = [
        ("Invoices",            "sales_invoice"),
        ("PurchaseInvoices",    "purchase_invoice"),
        ("CreditNotes",         "sales_credit_note"),
        ("PurchaseCreditNotes", "purchase_credit_note"),
    ]

    all_records: list[InvoiceRecord] = []
    total_inline = 0
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

    doc_nums = {r["doc_num"] for r in all_records if r["doc_num"]}

    return {
        "period": period,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "records": all_records,
        "doc_nums": doc_nums,
        "sap_inline_count": total_inline if inline_available else None,
    }


def calculate(client_config: ClientConfig, period: Period) -> F5ReturnOutput:
    """Step c — invoke calculate_f5_return and return as F5ReturnOutput."""
    result_str = sap_b1_server.calculate_f5_return(period["start"], period["end"])
    result: dict = json.loads(result_str)
    # Box keys emitted by calculate_f5_return are the canonical Gate 2 keys —
    # verified against sap_b1_server.py lines 441-449. No remapping needed.
    return result  # type: ignore[return-value]


def classify(client_config: ClientConfig, period: Period) -> ClassifyOutput:
    """Step b — invoke validate_invoice_tax_codes and return as ClassifyOutput."""
    result_str = sap_b1_server.validate_invoice_tax_codes(
        period["start"],
        period["end"],
        expected_rate=client_config.applicable_gst_rate,
    )
    return json.loads(result_str)  # type: ignore[return-value]


def detect(client_config: ClientConfig, period: Period) -> DetectOutput:
    """Step d — invoke detect_gst_errors and return as DetectOutput."""
    result_str = sap_b1_server.detect_gst_errors(
        period["start"],
        period["end"],
        expected_rate=client_config.applicable_gst_rate,
    )
    return json.loads(result_str)  # type: ignore[return-value]


_SEV_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def compile(  # noqa: A001 — shadows builtin; intentional, chain.py does not use builtin compile
    manifest: FetchManifest,
    calc: F5ReturnOutput,
    cls: ClassifyOutput,
    det: DetectOutput,
) -> CompileOutput:
    """Step e — aggregate outputs from b/c/d into a single structured object."""
    # Deduplicated anomalies: calc anomalies union classify unknowns, deduped on issue string.
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
                deduped.append({"doc_num": -1, "issue": text})

    # E1 reconciliation across calculate and detect.
    calc_e1: set[int] = {c["doc_num"] for c in calc["e1_candidates"]}
    detect_e1: set[int] = {i["doc_num"] for i in det["issues"] if i["error_code"] == "E1"}
    e1_recon: E1Reconciliation = {
        "calc_doc_nums": calc_e1,
        "detect_doc_nums": detect_e1,
        "matched": calc_e1 == detect_e1,
    }

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
    """Step f — shape CompileOutput into the flat dict T1.4's PDF renderer consumes.

    Note for T1.4 integration: classify issues carry vat_group, line_total, tax_total
    which enable E2-by-VatGroup template routing (Document-2). Join to detect issues
    on (doc_num, error_code) at render time — deferred reconciliation, not done here.
    """
    issues = sorted(
        compiled["detect"]["issues"],
        key=lambda i: (
            _SEV_ORDER.get(i.get("severity", "LOW"), 2),
            i["doc_num"] if i["doc_num"] is not None else float("inf"),
        ),
    )
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
