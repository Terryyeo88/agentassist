"""
report/enrich.py — aggregate classify + detect findings into one flat list.

enrich() accepts a CompileOutput dict (as loaded by report.contract.load_compile_output)
and returns one EnrichedFinding per (doc_num, error_code) pair, with per-line amounts
summed, template routing resolved, and Appendix 1 wording attached.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from report.routing import TemplateRef, appendix1_for, route

# Severity fallback for classify-only findings (no matching detect issue).
_CLASSIFY_SEVERITY: dict[str, str] = {
    "E1": "HIGH",
    "E2": "MEDIUM",
    "E3": "HIGH",
    "E4": "MEDIUM",
}


@dataclass
class EnrichedFinding:
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
    actively_makes_exempt: bool = False,
) -> list[EnrichedFinding]:
    """
    Build one EnrichedFinding per (doc_num, error_code) pair.

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
    all_keys = set(classify_agg.keys()) | set(detect_agg.keys())

    findings: list[EnrichedFinding] = []
    for key in sorted(
        all_keys,
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
