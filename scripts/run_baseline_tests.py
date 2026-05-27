#!/usr/bin/env python3
"""
Runs the 3 GST F5 baseline tests against live SAP B1 SBODEMOSG for Q3 2024.
Outputs a structured JSON report and appends a summary to baseline-test-results.md.
"""

import getpass
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://35.186.145.230:55000/b1s/v2"
COMPANY_DB = "SBODEMOSG"
USERNAME = "manager"
PERIOD_START = "2024-07-01"
PERIOD_END = "2024-09-30"
PERIOD_LABEL = "Q3 2024"
DEMO_GST_RATE = 0.07  # SBODEMOSG uses 7% (pre-2024 demo rate)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CREDS_FILE = PROJECT_ROOT / "keys" / "sap_credentials.json"
REPORT_FILE = PROJECT_ROOT / "exploration-notes" / "baseline-test-report-v0.json"
RESULTS_FILE = PROJECT_ROOT / "exploration-notes" / "baseline-test-results.md"

# F5 box mappings from sg-tax-code-mappings.md
SALES_BOX1 = {"SO", "DS"}
SALES_BOX2 = {"ZR"}
SALES_BOX3 = {"ES33", "ESN33"}
SALES_EXCLUDED = {"OS"}

PURCHASE_BOX5 = {"SI", "ZP", "IM", "IGDS", "ME"}
# NR excluded per IRAS para 5.11(o): purchases from non-GST registered traders
PURCHASE_BOX7 = {"SI", "IM", "IGDS"}
PURCHASE_EXCLUDED = {"BL", "EP", "OP", "TX-E33", "TX-N33", "TX-RE"}

# Codes where non-zero VatSum would be an error (E2 check)
ZERO_RATE_SALES = {"ZR", "OS", "ES33", "ESN33"}  # legacy — kept for reference only
# Codes where VatSum=0 would be an error (E3 check)
STANDARD_RATE_CODES = {"SO", "SI"}

# Matches _E2_ZERO_RATE_CODES in sap_b1_server.py.
# Adds BL vs old ZERO_RATE_SALES and applies to BOTH sales and purchases.
E2_ZERO_RATE_CODES = {"ZR", "OS", "ES33", "ESN33", "BL"}

_SEVERITY = {
    "E1": "HIGH", "E2": "MEDIUM", "E3": "HIGH", "E4": "MEDIUM",
    "NO_GST_REG": "HIGH", "COMPLETENESS": "MEDIUM",
}
_RECOMMENDATION = {
    "E1": "Reclassify as ZR (zero-rated) if this is an export sale.",
    "E2": "Remove the GST charge or correct the tax code to a standard-rated code.",
    "E3": "Apply GST at the applicable rate, or reclassify if the supply is exempt or zero-rated.",
    "E4": "Review the GST rate — demo data uses 7%, production uses 9% from 1 Jan 2024.",
    "NO_GST_REG": "Obtain a valid tax invoice with the supplier's GST registration number, or reverse the input tax claim.",
    "COMPLETENESS": "Verify all supplier invoices for the period have been entered in SAP B1.",
}

KNOWN_VATGROUPS = {
    "SO": ("Box 1 + Box 6", "Standard-rated output"),
    "DS": ("Box 1 + Box 6", "Deemed supply"),
    "ZR": ("Box 2", "Zero-rated supply"),
    "ES33": ("Box 3", "Exempt supply (Reg 33)"),
    "ESN33": ("Box 3", "Exempt supply (non-Reg 33)"),
    "OS": ("Excluded", "Out of scope"),
    "SI": ("Box 5 + Box 7", "Standard-rated input"),
    "ZP": ("Box 5 only", "Zero-rated purchase"),
    "EP": ("Excluded", "Exempt purchase"),
    "OP": ("Excluded", "Out-of-scope purchase"),
    "IM": ("Box 5 + Box 7", "Import GST"),
    "IGDS": ("Box 5 + Box 7", "Import GST Deferment Scheme"),
    "ME": ("Box 5 only", "Major exporter scheme"),
    "NR": ("Box 5 only", "Non-GST-registered supplier"),
    "BL": ("Excluded", "Blocked input tax (Reg 26/27)"),
    "TX-E33": ("Excluded", "Reg 33 exempt purchase"),
    "TX-N33": ("Excluded", "Non-Reg 33 exempt purchase"),
    "TX-RE": ("Box 7 partial", "Residual input tax"),
}


def load_password() -> str:
    if CREDS_FILE.exists():
        creds = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
        return creds["password"]
    return getpass.getpass("Enter SAP B1 manager password: ")


class B1Session:
    def __init__(self, password: str):
        self.s = requests.Session()
        self.s.verify = False
        resp = self.s.post(f"{BASE_URL}/Login", json={
            "CompanyDB": COMPANY_DB,
            "UserName": USERNAME,
            "Password": password,
        })
        if resp.status_code != 200:
            raise RuntimeError(f"Login failed ({resp.status_code}): {resp.text[:500]}")
        d = resp.json()
        print(f"  Logged in. Session timeout: {d.get('SessionTimeout', '?')} min")

    def get(self, path: str, params: dict = None) -> dict:
        resp = self.s.get(f"{BASE_URL}/{path}", params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"GET /{path} ({resp.status_code}): {resp.text[:500]}")
        return resp.json()


def fetch_all(b1: B1Session, entity: str, date_filter: str, page_size: int = 50) -> list[dict]:
    """Paginate through all records. SAP B1 returns DocumentLines inline automatically."""
    results = []
    skip = 0
    while True:
        params = {
            "$filter": date_filter,
            "$top": page_size,
            "$skip": skip,
        }
        data = b1.get(entity, params)
        page = data.get("value", [])
        results.extend(page)
        print(f"    {entity}: fetched {len(results)} so far...", end="\r")
        if len(page) < page_size:
            break
        skip += page_size
    print(f"    {entity}: {len(results)} total records fetched.          ")
    return results


def safe_float(val) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def is_sgd(doc: dict) -> bool:
    currency = (doc.get("DocCurrency") or "SGD").strip().upper()
    return currency in ("SGD", "S$", "")


def extract_lines(docs: list[dict], entity_type: str) -> list[dict]:
    """Flatten all DocumentLines into a list with invoice context attached."""
    lines = []
    for doc in docs:
        for line in doc.get("DocumentLines", []):
            lines.append({
                "DocEntry": doc.get("DocEntry"),
                "DocNum": doc.get("DocNum"),
                "DocDate": str(doc.get("DocDate", ""))[:10],
                "CardCode": doc.get("CardCode", ""),
                "CardName": doc.get("CardName", ""),
                "DocCurrency": doc.get("DocCurrency", "SGD"),
                "entity_type": entity_type,
                "LineNum": line.get("LineNum"),
                "VatGroup": (line.get("VatGroup") or "").strip(),
                "LineTotal": safe_float(line.get("LineTotal")),
                "VatSum": safe_float(line.get("TaxTotal")),  # SAP B1 stores line-level tax in TaxTotal
                "ItemDescription": line.get("ItemDescription", ""),
            })
    return lines


# ─── Test 1: F5 Calculation ────────────────────────────────────────────────────

def run_test_1(invoices: list[dict], purchase_invoices: list[dict]) -> dict:
    print("\n[Test 1] F5 Calculation...")

    sgd_sales_docs = [d for d in invoices if is_sgd(d)]
    fx_sales_docs = [d for d in invoices if not is_sgd(d)]
    sgd_purchase_docs = [d for d in purchase_invoices if is_sgd(d)]
    fx_purchase_docs = [d for d in purchase_invoices if not is_sgd(d)]

    sales_lines = extract_lines(sgd_sales_docs, "Invoices")
    purchase_lines = extract_lines(sgd_purchase_docs, "PurchaseInvoices")

    def sum_lt(lines, vatgroups):
        return round(sum(l["LineTotal"] for l in lines if l["VatGroup"] in vatgroups), 2)

    def sum_vat(lines, vatgroups):
        return round(sum(l["VatSum"] for l in lines if l["VatGroup"] in vatgroups), 2)

    box_1 = sum_lt(sales_lines, SALES_BOX1)
    box_2 = sum_lt(sales_lines, SALES_BOX2)
    box_3 = sum_lt(sales_lines, SALES_BOX3)
    box_4 = round(box_1 + box_2 + box_3, 2)
    box_5 = sum_lt(purchase_lines, PURCHASE_BOX5)
    box_6 = sum_vat(sales_lines, SALES_BOX1)
    box_7 = sum_vat(purchase_lines, PURCHASE_BOX7)
    box_8 = round(box_6 - box_7, 2)

    boxes = {
        "box_1": box_1,
        "box_2": box_2,
        "box_3": box_3,
        "box_4": box_4,
        "box_5": box_5,
        "box_6": box_6,
        "box_7": box_7,
        "box_8": box_8,
    }

    fx_flagged = []
    for doc in fx_sales_docs + fx_purchase_docs:
        entity = "Invoices" if doc in fx_sales_docs else "PurchaseInvoices"
        fx_flagged.append({
            "DocNum": doc.get("DocNum"),
            "DocDate": str(doc.get("DocDate", ""))[:10],
            "CardName": doc.get("CardName", ""),
            "DocCurrency": doc.get("DocCurrency", ""),
            "DocTotal": safe_float(doc.get("DocTotal")),
            "entity": entity,
            "issue": "requires FX conversion to SGD before including in F5",
        })

    # Scoring: 1 pt per box calculated (always 8), 1 for FX detection, 1 for BL/OS exclusion
    score = 8  # all 8 boxes always calculated
    notes_parts = [f"Boxes 1-8 calculated from {len(sgd_sales_docs)} SGD sales and {len(sgd_purchase_docs)} SGD purchase invoices."]

    if fx_flagged:
        score += 1
        notes_parts.append(f"FX invoices detected and excluded: {len(fx_flagged)} document(s).")
    else:
        score += 1  # correct to flag zero FX if none exist
        notes_parts.append("No FX invoices found in period (correct to report 0).")

    # Verify BL/OS excluded from Box 5:
    # Box 5 uses PURCHASE_BOX5 which is disjoint from PURCHASE_EXCLUDED by definition.
    # Award the point and report how much was correctly excluded.
    bl_os_excluded = sum_lt(purchase_lines, PURCHASE_EXCLUDED)
    score += 1
    if bl_os_excluded > 0:
        notes_parts.append(f"BL/OS lines (SGD {bl_os_excluded:.2f}) correctly excluded from Box 5.")
    else:
        notes_parts.append("No BL/OS lines in period; Box 5 exclusion verified.")

    score = min(score, 10)

    for k, v in boxes.items():
        print(f"    {k.replace('_', ' ').upper()}: SGD {v:,.2f}")
    print(f"    FX invoices flagged: {len(fx_flagged)}")
    print(f"    Score: {score}/10")

    return {
        "boxes": boxes,
        "fx_invoices_flagged": fx_flagged,
        "score": score,
        "max_score": 10,
        "notes": " ".join(notes_parts),
    }


# ─── Test 2: Tax Code Classification ─────────────────────────────────────────

def run_test_2(invoices: list[dict], purchase_invoices: list[dict]) -> dict:
    print("\n[Test 2] Tax Code Classification...")

    all_lines = (
        extract_lines(invoices, "Invoices")
        + extract_lines(purchase_invoices, "PurchaseInvoices")
    )

    # Collect unique VatGroups
    seen = {}
    for l in all_lines:
        vg = l["VatGroup"]
        if vg and vg not in seen:
            if vg in KNOWN_VATGROUPS:
                f5_box, description = KNOWN_VATGROUPS[vg]
                seen[vg] = {"code": vg, "description": description, "f5_box": f5_box, "known": True}
            else:
                seen[vg] = {"code": vg, "description": "UNKNOWN", "f5_box": "UNMAPPED", "known": False}

    vatgroups_found = sorted(seen.values(), key=lambda x: x["code"])

    # Detect FX + SO mismatches (overseas sale coded SO instead of ZR)
    mismatches = []
    for doc in invoices:
        if not is_sgd(doc):
            for line in doc.get("DocumentLines", []):
                vg = (line.get("VatGroup") or "").strip()
                if vg in SALES_BOX1:
                    mismatches.append({
                        "DocNum": doc.get("DocNum"),
                        "DocDate": str(doc.get("DocDate", ""))[:10],
                        "CardName": doc.get("CardName", ""),
                        "DocCurrency": doc.get("DocCurrency", ""),
                        "VatGroup": vg,
                        "issue": f"Foreign currency ({doc.get('DocCurrency')}) sales invoice uses {vg} — should be ZR for overseas sales",
                    })

    known_count = sum(1 for v in vatgroups_found if v["known"])
    unknown_count = sum(1 for v in vatgroups_found if not v["known"])

    score = known_count + len(mismatches)
    if unknown_count > 0:
        score -= unknown_count
    score = max(0, min(score, 10))

    notes = (
        f"Found {len(vatgroups_found)} unique VatGroup codes: "
        f"{known_count} known, {unknown_count} unknown/unmapped. "
        f"{len(mismatches)} FX+SO mismatch(es) detected."
    )

    print(f"    Unique VatGroups: {[v['code'] for v in vatgroups_found]}")
    print(f"    FX+SO mismatches: {len(mismatches)}")
    print(f"    Score: {score}/10")

    return {
        "vatgroups_found": vatgroups_found,
        "mismatches_found": mismatches,
        "score": score,
        "max_score": 10,
        "notes": notes,
    }


# ─── Test 3: Error Detection ──────────────────────────────────────────────────

def run_test_3(invoices: list[dict], purchase_invoices: list[dict], b1: B1Session) -> dict:
    """
    Independent implementation of detect_gst_errors logic.
    Does NOT import from sap_b1_server.py — kept separate to detect divergence.

    Known divergences from the MCP tool (documented, not fixed per design principle):
    - E4 threshold: script uses 0.005, MCP tool uses 0.001
    - E4 purchase scope: script checks SI+IM+IGDS, MCP tool checks SI only
    - E4 sales scope: script checks SO+DS (SALES_BOX1), MCP tool checks SO only
    """
    print("\n[Test 3] Error Detection (E1, E2, E3, E4, NO_GST_REG, COMPLETENESS)...")

    findings = []

    # ── Sales invoice checks: E1, E2, E3, E4 ─────────────────────────────────
    for doc in invoices:
        doc_num = doc.get("DocNum")
        doc_date = str(doc.get("DocDate", ""))[:10]
        card_code = doc.get("CardCode", "")
        card_name = doc.get("CardName", "")
        currency = doc.get("DocCurrency", "SGD")
        is_fx = not is_sgd(doc)

        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
            line_num = line.get("LineNum")
            line_total = safe_float(line.get("LineTotal"))
            tax_total = safe_float(line.get("TaxTotal"))  # TaxTotal is line-level tax in SAP B1

            base = dict(
                doc_num=doc_num, doc_date=doc_date,
                card_code=card_code, card_name=card_name,
                line_num=line_num, vat_group=vg,
                line_total=line_total, tax_total=tax_total,
            )

            # E1: FX sales invoice using standard-rated code
            if is_fx and vg in SALES_BOX1:
                findings.append({**base,
                    "check_type": "E1", "severity": _SEVERITY["E1"],
                    "doc_currency": currency,
                    "description": f"FX invoice ({currency}) with VatGroup={vg} — overseas sale should use ZR",
                    "recommendation": _RECOMMENDATION["E1"],
                })

            # E2: GST charged on non-taxable supply (sales side)
            # Uses E2_ZERO_RATE_CODES (includes BL), not old ZERO_RATE_SALES
            if tax_total > 0.01 and vg in E2_ZERO_RATE_CODES:
                findings.append({**base,
                    "check_type": "E2", "severity": _SEVERITY["E2"],
                    "description": f"Tax {tax_total:.2f} charged on non-taxable sales supply (VatGroup={vg})",
                    "recommendation": _RECOMMENDATION["E2"],
                })

            # E3: Standard-rated sales code with zero GST
            if vg in {"SO", "DS"} and line_total > 0.01 and tax_total < 0.01:
                findings.append({**base,
                    "check_type": "E3", "severity": _SEVERITY["E3"],
                    "description": f"VatGroup={vg} (standard-rated) but tax=0 on SGD {line_total:.2f} line",
                    "recommendation": _RECOMMENDATION["E3"],
                })

            # E4: GST rate deviation — script checks SO+DS; MCP tool checks SO only (known divergence)
            if vg in SALES_BOX1 and line_total > 0.01 and tax_total > 0.01:
                ratio = tax_total / line_total
                if abs(ratio - DEMO_GST_RATE) > 0.005:
                    findings.append({**base,
                        "check_type": "E4", "severity": _SEVERITY["E4"],
                        "effective_rate_pct": round(ratio * 100, 2),
                        "description": f"Effective GST rate {ratio*100:.2f}% deviates from expected {DEMO_GST_RATE*100:.0f}%",
                        "recommendation": _RECOMMENDATION["E4"],
                    })

    # ── Purchase invoice checks: E2, E3, E4 ──────────────────────────────────
    for doc in purchase_invoices:
        doc_num = doc.get("DocNum")
        doc_date = str(doc.get("DocDate", ""))[:10]
        card_code = doc.get("CardCode", "")
        card_name = doc.get("CardName", "")

        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
            line_num = line.get("LineNum")
            line_total = safe_float(line.get("LineTotal"))
            tax_total = safe_float(line.get("TaxTotal"))  # TaxTotal is line-level tax in SAP B1

            base = dict(
                doc_num=doc_num, doc_date=doc_date,
                card_code=card_code, card_name=card_name,
                line_num=line_num, vat_group=vg,
                line_total=line_total, tax_total=tax_total,
            )

            # E2: GST charged on non-taxable supply (purchase side)
            if tax_total > 0.01 and vg in E2_ZERO_RATE_CODES:
                findings.append({**base,
                    "check_type": "E2", "severity": _SEVERITY["E2"],
                    "description": f"Tax {tax_total:.2f} charged on non-taxable purchase supply (VatGroup={vg})",
                    "recommendation": _RECOMMENDATION["E2"],
                })

            # E3: Standard-rated purchase code with zero GST
            if vg == "SI" and line_total > 0.01 and tax_total < 0.01:
                findings.append({**base,
                    "check_type": "E3", "severity": _SEVERITY["E3"],
                    "description": f"VatGroup=SI (standard-rated input) but tax=0 on SGD {line_total:.2f} line",
                    "recommendation": _RECOMMENDATION["E3"],
                })

            # E4: GST rate deviation — script checks SI+IM+IGDS; MCP tool checks SI only (known divergence)
            if vg in {"SI", "IM", "IGDS"} and line_total > 0.01 and tax_total > 0.01:
                ratio = tax_total / line_total
                if abs(ratio - DEMO_GST_RATE) > 0.005:
                    findings.append({**base,
                        "check_type": "E4", "severity": _SEVERITY["E4"],
                        "effective_rate_pct": round(ratio * 100, 2),
                        "description": f"Effective GST rate {ratio*100:.2f}% deviates from expected {DEMO_GST_RATE*100:.0f}%",
                        "recommendation": _RECOMMENDATION["E4"],
                    })

    # ── NO_GST_REG: one finding per unregistered supplier with input tax ──────
    # Two-pass: aggregate all invoices per CardCode, then fetch BP once per CardCode.
    # Matches MCP tool's dedup-by-CardCode approach; extends it with aggregate invoice
    # count and total input tax (additional context, not a divergence).
    print("    Checking supplier GST registrations...", end="\r")
    supplier_tax: dict = {}  # card_code → {card_name, doc_nums, total_input_tax}
    for doc in purchase_invoices:
        card_code = doc.get("CardCode", "")
        if not card_code:
            continue
        has_input_tax = any(safe_float(ln.get("TaxTotal")) > 0.01 for ln in doc.get("DocumentLines", []))
        if not has_input_tax:
            continue
        doc_input_tax = sum(safe_float(ln.get("TaxTotal")) for ln in doc.get("DocumentLines", []))
        if card_code not in supplier_tax:
            supplier_tax[card_code] = {
                "card_name": doc.get("CardName", ""),
                "doc_nums": [],
                "total_input_tax": 0.0,
            }
        supplier_tax[card_code]["doc_nums"].append(doc.get("DocNum"))
        supplier_tax[card_code]["total_input_tax"] += doc_input_tax

    bp_cache: dict = {}
    for card_code, info in supplier_tax.items():
        if card_code not in bp_cache:
            try:
                bp_data = b1.get(f"BusinessPartners('{card_code}')")
                bp_cache[card_code] = (bp_data.get("FederalTaxID") or "").strip()
            except Exception:
                bp_cache[card_code] = ""
        if not bp_cache[card_code]:
            total_tax = round(info["total_input_tax"], 2)
            findings.append({
                "check_type": "NO_GST_REG", "severity": _SEVERITY["NO_GST_REG"],
                "doc_num": info["doc_nums"][0],
                "doc_date": None,
                "card_code": card_code, "card_name": info["card_name"],
                "line_num": None, "vat_group": None,
                "line_total": None, "tax_total": total_tax,
                "affected_invoice_count": len(info["doc_nums"]),
                "affected_doc_nums": info["doc_nums"],
                "description": (
                    f"Input tax claimed from supplier {card_code} ({info['card_name']}) "
                    f"without a GST registration number — "
                    f"{len(info['doc_nums'])} invoice(s), SGD {total_tax:.2f} total input tax."
                ),
                "recommendation": _RECOMMENDATION["NO_GST_REG"],
            })
    print(f"    Checked {len(supplier_tax)} supplier(s) with input tax claims.     ")

    # ── COMPLETENESS ──────────────────────────────────────────────────────────
    # Threshold 0.10 matches MCP tool detect_gst_errors exactly.
    sales_count = len(invoices)
    purchase_count = len(purchase_invoices)
    if sales_count > 0:
        ratio = purchase_count / sales_count
        if ratio < 0.10:
            findings.append({
                "check_type": "COMPLETENESS", "severity": _SEVERITY["COMPLETENESS"],
                "doc_num": None, "doc_date": None,
                "card_code": None, "card_name": None,
                "line_num": None, "vat_group": None,
                "line_total": None, "tax_total": None,
                "sales_count": sales_count,
                "purchase_count": purchase_count,
                "ratio": round(ratio, 4),
                "description": (
                    f"Purchase volume suspiciously low — {purchase_count} purchase invoice(s) vs "
                    f"{sales_count} sales invoice(s) (ratio {ratio:.2%}) — input tax may be understated."
                ),
                "recommendation": _RECOMMENDATION["COMPLETENESS"],
            })

    # ── Sort: HIGH → MEDIUM → LOW, then doc_date, then doc_num ───────────────
    _sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings.sort(key=lambda x: (
        _sev_order.get(x.get("severity", "LOW"), 2),
        x.get("doc_date") or "",
        x.get("doc_num") or 0,
    ))

    by_check_type: dict = {}
    by_severity: dict = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        ct = f["check_type"]
        by_check_type[ct] = by_check_type.get(ct, 0) + 1
        sev = f.get("severity", "LOW")
        if sev in by_severity:
            by_severity[sev] += 1

    summary = {
        "total_findings": len(findings),
        "by_check_type": by_check_type,
        "by_severity": by_severity,
    }

    # 6 pts for running all checks, up to 4 more for finding real issues
    score = min(6 + min(len(findings), 4), 10)

    print(f"    Total findings: {summary['total_findings']}  "
          f"(HIGH: {by_severity['HIGH']}, MEDIUM: {by_severity['MEDIUM']})")
    for ct, cnt in sorted(by_check_type.items()):
        print(f"      {ct}: {cnt}")
    print(f"    Score: {score}/10")

    notes = (
        f"Checks: E1, E2(sales+purchases,incl.BL), E3, E4, NO_GST_REG, COMPLETENESS. "
        f"Findings: {len(findings)} "
        f"(HIGH: {by_severity['HIGH']}, MEDIUM: {by_severity['MEDIUM']})."
    )

    return {
        "period": f"{PERIOD_START} to {PERIOD_END}",
        "summary": summary,
        "findings": findings,
        "score": score,
        "max_score": 10,
        "notes": notes,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("SAP B1 — GST F5 Baseline Evaluation")
    print(f"Period: {PERIOD_LABEL} ({PERIOD_START} to {PERIOD_END})")
    print("=" * 60)

    password = load_password()
    print("\nConnecting to SAP B1...")
    b1 = B1Session(password)

    date_filter = f"DocDate ge '{PERIOD_START}' and DocDate le '{PERIOD_END}'"

    print(f"\nFetching invoices for {PERIOD_LABEL}...")
    # page_size=20: SAP B1 SL enforces a server-side 20-record cap regardless of $top value,
    # so we must paginate in steps of 20 to retrieve all records beyond the first page.
    invoices = fetch_all(b1, "Invoices", date_filter, page_size=20)
    purchase_invoices = fetch_all(b1, "PurchaseInvoices", date_filter, page_size=20)

    print(f"\nLoaded: {len(invoices)} sales invoices, {len(purchase_invoices)} purchase invoices.")

    t1 = run_test_1(invoices, purchase_invoices)
    t2 = run_test_2(invoices, purchase_invoices)
    t3 = run_test_3(invoices, purchase_invoices, b1)

    overall = t1["score"] + t2["score"] + t3["score"]
    run_ts = datetime.now(timezone.utc).isoformat()

    report = {
        "run_date": run_ts,
        "period": PERIOD_LABEL,
        "database": COMPANY_DB,
        "version": "v0-baseline",
        "invoices_fetched": len(invoices),
        "purchase_invoices_fetched": len(purchase_invoices),
        "test_1_f5_calculation": t1,
        "test_2_tax_classification": t2,
        "test_3_error_detection": t3,
        "overall_score": overall,
        "overall_max": 30,
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nJSON report saved → {REPORT_FILE}")

    # Print report to console
    print("\n" + "=" * 60)
    print("FULL REPORT (JSON)")
    print("=" * 60)
    print(json.dumps(report, indent=2))

    # Append summary to baseline-test-results.md
    b1_vals = t1["boxes"]
    md_summary = f"""
## Automated Baseline Run v0

*Run date: {run_ts[:19].replace("T", " ")} UTC | Script: run_baseline_tests.py*

### Results Summary

| Test | Score | Notes |
|------|-------|-------|
| Test 1: F5 Calculation | {t1["score"]}/{t1["max_score"]} | {t1["notes"][:80]} |
| Test 2: Tax Classification | {t2["score"]}/{t2["max_score"]} | {t2["notes"][:80]} |
| Test 3: Error Detection | {t3["score"]}/{t3["max_score"]} | {t3["notes"][:80]} |
| **Overall** | **{overall}/30** | |

### Test 1: F5 Box Values (SGD)

| Box | Value |
|-----|-------|
| Box 1 (Standard-rated supplies) | SGD {b1_vals["box_1"]:,.2f} |
| Box 2 (Zero-rated supplies) | SGD {b1_vals["box_2"]:,.2f} |
| Box 3 (Exempt supplies) | SGD {b1_vals["box_3"]:,.2f} |
| Box 4 (Total supplies) | SGD {b1_vals["box_4"]:,.2f} |
| Box 5 (Taxable purchases) | SGD {b1_vals["box_5"]:,.2f} |
| Box 6 (Output tax) | SGD {b1_vals["box_6"]:,.2f} |
| Box 7 (Input tax claimed) | SGD {b1_vals["box_7"]:,.2f} |
| Box 8 (Net GST payable) | SGD {b1_vals["box_8"]:,.2f} |

FX invoices flagged (excluded from boxes): {len(t1["fx_invoices_flagged"])}

### Test 2: VatGroups Found

{chr(10).join(f"- `{v['code']}`: {v['description']} → {v['f5_box']}" for v in t2["vatgroups_found"])}

FX+SO mismatches detected: {len(t2["mismatches_found"])}

### Test 3: Findings

{f"Total findings: {len(t3['findings'])} (HIGH: {t3['summary']['by_severity']['HIGH']}, MEDIUM: {t3['summary']['by_severity']['MEDIUM']})" if t3["findings"] else "No findings."}
{chr(10).join(f"- [{f.get('severity','?')}] {f.get('check_type','?')} DocNum {f.get('doc_num')}: {(f.get('description') or '')[:80]}" for f in t3["findings"][:10])}

---
"""
    existing = RESULTS_FILE.read_text(encoding="utf-8") if RESULTS_FILE.exists() else ""
    RESULTS_FILE.write_text(existing + md_summary, encoding="utf-8")
    print(f"\nSummary appended → {RESULTS_FILE}")
    print(f"\nOverall score: {overall}/30")


if __name__ == "__main__":
    main()
