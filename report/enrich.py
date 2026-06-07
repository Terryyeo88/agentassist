"""
report/enrich.py — aggregate classify + detect findings into one flat list.

enrich() accepts a CompileOutput dict (as loaded by report.contract.load_compile_output)
and returns one EnrichedFinding per (doc_num, error_code) pair, with per-line amounts
summed, template routing resolved, and Appendix 1 wording attached.

The module sits between raw chain output and the report renderer.  Its job is
purely structural: collapse the many-rows-per-document output from classify and
detect into one canonical finding per document-plus-error-code pair, resolve
which ASK template section owns that finding, and attach the regulatory wording
that must appear in the report.  No SAP calls, no file I/O.

Design notes:
    * classify and detect are aggregated independently, then joined.  This keeps
      the accumulation logic simple and makes the join behaviour explicit (full
      outer join, with clear fallbacks for each half).
    * Classify data is authoritative for monetary amounts; detect data is
      authoritative for severity and recommendation.  When both exist for a key,
      each source contributes only what it owns.
    * Manifest data is a last resort: it backfills doc-level metadata (card_name,
      doc_date, doc_total) only for fields still None after the classify join.

Dependencies:
    report.routing — route() and appendix1_for() for template and wording lookup

Exports:
    EnrichedFinding — dataclass; one instance per (doc_num, error_code) pair
    enrich          — main aggregation function
"""
from __future__ import annotations

# from __future__ import annotations makes all annotations strings at parse time,
# enabling lowercase union syntax (int | None) and forward references on Python < 3.10.

from dataclasses import dataclass
from typing import Any

from report.routing import TemplateRef, appendix1_for, route

# Severity fallback for classify-only findings (no matching detect issue).
# Used when a classify error_code has no counterpart in detect["issues"],
# which can happen if detect ran against a different document set or was skipped.
_CLASSIFY_SEVERITY: dict[str, str] = {
    "E1": "HIGH",
    "E2": "MEDIUM",
    "E3": "HIGH",
    "E4": "MEDIUM",
}


@dataclass
class EnrichedFinding:
    """One collapsed, fully-attributed GST finding ready for report rendering.

    Represents the aggregation of all classify and detect issue rows that share
    the same (doc_num, error_code) pair.  Monetary amounts (line_total, tax_total)
    are summed across all contributing lines; invariant fields (card_name, vat_group,
    doc_date) are taken from the first occurrence and assumed stable within a group.

    Attributes:
        doc_num:           SAP B1 document number.  None for period-level findings
                           (e.g. COMPLETENESS) that are not tied to a single document.
        error_code:        Finding type: 'E1'–'E4', 'NO_GST_REG', 'COMPLETENESS', etc.
        severity:          'HIGH', 'MEDIUM', or 'LOW'.
        vat_group:         SAP VatGroup code for the finding's lines, e.g. 'SO', 'SI'.
                           None for detect-only findings that have no classify row.
        doc_currency:      Document currency code, e.g. 'SGD', 'USD'.  None for
                           detect-only findings before manifest backfill.
        card_name:         Business partner name from the document header.
        doc_date:          Document date as ISO string 'YYYY-MM-DD'.
        line_total:        Sum of LineTotal across all classify lines in this group.
                           None for detect-only findings (NO_GST_REG, COMPLETENESS).
        tax_total:         Sum of TaxTotal across all classify lines in this group.
                           None for detect-only findings.
        line_count:        Number of source document lines collapsed into this finding.
        description:       Human-readable description of the issue.  Taken from detect
                           when available (richer); falls back to classify description.
        recommendation:    Suggested corrective action from the detect step, or None
                           for classify-only findings.
        template_ref:      Resolved ASK template and step reference for report routing.
        appendix1_category: Verbatim Appendix 1 category string from IRAS ASK guide.
        doc_total:         Total document value from the fetch manifest InvoiceRecord.
                           None if the document has no manifest row.
    """
    doc_num: int | None
    error_code: str
    severity: str
    vat_group: str | None
    doc_currency: str | None
    card_name: str | None
    doc_date: str | None
    line_total: float | None     # sum of classify line totals; None for detect-only
    tax_total: float | None      # sum of classify tax totals; None for detect-only
    line_count: int              # number of source lines collapsed into this finding
    description: str
    recommendation: str | None
    template_ref: TemplateRef
    appendix1_category: str
    doc_total: float | None      # from FetchManifest InvoiceRecord; None if no manifest row


def enrich(
    compile_output: dict[str, Any],
    *,
    # Keyword-only to prevent silent positional mis-ordering in callers;
    # the flag changes Template 4 vs 5 routing for E2_EXEMPT findings.
    actively_makes_exempt: bool = False,
) -> list[EnrichedFinding]:
    """Build one EnrichedFinding per (doc_num, error_code) pair from chain output.

    Args:
        compile_output:       A CompileOutput dict as returned by
                              report.contract.load_compile_output.  Must contain
                              'classify', 'detect', and 'fetch_manifest' keys.
        actively_makes_exempt: Controls E2_EXEMPT template routing.  True routes
                              to Template 4 (business that actively makes exempt
                              supplies); False routes to Template 5 (general
                              business with incidental exempt supplies).
                              Keyword-only to prevent silent positional errors.

    Returns:
        list[EnrichedFinding]: One finding per distinct (doc_num, error_code) pair,
            sorted by error_code then doc_num (None doc_nums sort first within
            each error_code group).

    Raises:
        KeyError: If compile_output is missing 'classify', 'detect', or
            'fetch_manifest' keys, or if individual issue dicts are missing
            expected fields.  Use load_compile_output to pre-validate structure.

    Steps:
      1. Aggregate classify["issues"] by (doc_num, error_code): sum line_total /
         tax_total, count lines, keep invariant vat_group / doc_currency / card_name /
         doc_date (taken from the first occurrence within each group).
      2. Aggregate detect["issues"] by (doc_num, error_code): keep severity,
         description, recommendation (first occurrence), count lines.
      3. Full outer-join on (doc_num, error_code).
         - Combined: classify supplies amounts; detect supplies severity + recommendation.
         - Classify-only: severity fallback {E1:HIGH, E2:MEDIUM, E3:HIGH, E4:MEDIUM}.
         - Detect-only (NO_GST_REG, COMPLETENESS): line_total / tax_total = None.
      4. Left-join fetch_manifest["records"] by doc_num to populate doc_total and
         backfill vat_group / doc_currency / card_name / doc_date for detect-only
         findings that lack them. COMPLETENESS has doc_num=None and gets no manifest row.
      5. Resolve template_ref via route() and appendix1_category via appendix1_for().
    """
    classify_issues: list[dict] = compile_output["classify"]["issues"]
    detect_issues: list[dict] = compile_output["detect"]["issues"]
    manifest_records: list[dict] = compile_output["fetch_manifest"]["records"]

    # Build manifest lookup: doc_num -> first InvoiceRecord for that doc.
    # "First" is used because a document can generate multiple InvoiceRecord rows
    # (one per distinct VatGroup); doc-level fields like card_name and doc_date
    # are identical across all rows for the same document, so any row suffices.
    manifest_by_docnum: dict[int, dict] = {}
    for rec in manifest_records:
        dn = rec["doc_num"]
        if dn not in manifest_by_docnum:
            manifest_by_docnum[dn] = rec

    # ── 1. Aggregate classify issues ─────────────────────────────────────────
    classify_agg: dict[tuple, dict] = {}
    for issue in classify_issues:
        key = (issue["doc_num"], issue["error_code"])
        if key not in classify_agg:
            # Invariant fields taken from first occurrence; amounts start at zero
            # and are accumulated across all lines in the group below.
            classify_agg[key] = {
                "vat_group": issue["vat_group"],
                "doc_currency": issue["doc_currency"],
                "card_name": issue["card_name"],
                "doc_date": issue["doc_date"],
                "line_total": 0.0,
                "tax_total": 0.0,
                "line_count": 0,
                "description": issue["description"],
            }
        classify_agg[key]["line_total"] += issue["line_total"]
        classify_agg[key]["tax_total"] += issue["tax_total"]
        classify_agg[key]["line_count"] += 1

    # ── 2. Aggregate detect issues ────────────────────────────────────────────
    detect_agg: dict[tuple, dict] = {}
    for issue in detect_issues:
        key = (issue["doc_num"], issue["error_code"])
        if key not in detect_agg:
            # Severity, description, and recommendation taken from first occurrence;
            # detect issues for the same key are de-duplicated, not accumulated.
            detect_agg[key] = {
                "severity": issue["severity"],
                "description": issue["description"],
                "recommendation": issue.get("recommendation"),
                "card_name": issue.get("card_name"),
                "doc_date": issue.get("doc_date"),
                "line_count": 0,
            }
        detect_agg[key]["line_count"] += 1

    # ── 3. Full outer join ────────────────────────────────────────────────────
    # Set union produces every (doc_num, error_code) key that appears in either
    # or both aggregations — equivalent to a SQL FULL OUTER JOIN.
    all_keys = set(classify_agg.keys()) | set(detect_agg.keys())

    findings: list[EnrichedFinding] = []
    for key in sorted(
        all_keys,
        # Primary sort: error_code groups related findings together in the report.
        # Secondary sort: doc_num ascending; None (COMPLETENESS) maps to -1 so
        # period-level findings appear before any numbered document within each group.
        key=lambda k: (k[1], k[0] if k[0] is not None else -1),
    ):
        doc_num, error_code = key
        c = classify_agg.get(key)
        d = detect_agg.get(key)

        if c is not None:
            # Amounts and invariant fields from classify; severity/recommendation from detect.
            vat_group: str | None = c["vat_group"]
            doc_currency: str | None = c["doc_currency"]
            card_name: str | None = c["card_name"]
            doc_date: str | None = c["doc_date"]
            line_total: float | None = c["line_total"]
            tax_total: float | None = c["tax_total"]
            line_count: int = c["line_count"]
            description: str = d["description"] if d is not None else c["description"]
            recommendation: str | None = d["recommendation"] if d is not None else None
            severity: str = (
                d["severity"]
                if d is not None
                else _CLASSIFY_SEVERITY.get(error_code, "LOW")
            )
        else:
            # Detect-only (NO_GST_REG, COMPLETENESS): no classify row.
            # Assert is always safe here: key came from the union of both dicts,
            # and c is None, so d must exist.
            assert d is not None
            vat_group = None
            doc_currency = None
            card_name = d["card_name"]
            doc_date = d["doc_date"]
            line_total = None
            tax_total = None
            line_count = d["line_count"]
            description = d["description"]
            recommendation = d["recommendation"]
            severity = d["severity"]

        # ── 4. Left-join manifest ─────────────────────────────────────────────
        doc_total: float | None = None
        if doc_num is not None:
            mf = manifest_by_docnum.get(doc_num)
            if mf is not None:
                # Only backfill fields that classify did not already supply;
                # classify data is authoritative and must not be overwritten.
                if vat_group is None:
                    vat_group = mf["vat_group"]
                if doc_currency is None:
                    doc_currency = mf["doc_currency"]
                if card_name is None:
                    card_name = mf["card_name"]
                if doc_date is None:
                    doc_date = mf["doc_date"]
                doc_total = mf["doc_total"]

        # ── 5. Routing and Appendix 1 wording ────────────────────────────────
        template_ref = route(
            error_code, vat_group, actively_makes_exempt=actively_makes_exempt
        )
        appendix1_category = appendix1_for(error_code, vat_group)

        findings.append(EnrichedFinding(
            doc_num=doc_num,
            error_code=error_code,
            severity=severity,
            vat_group=vat_group,
            doc_currency=doc_currency,
            card_name=card_name,
            doc_date=doc_date,
            line_total=line_total,
            tax_total=tax_total,
            line_count=line_count,
            description=description,
            recommendation=recommendation,
            template_ref=template_ref,
            appendix1_category=appendix1_category,
            doc_total=doc_total,
        ))

    return findings
