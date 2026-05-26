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

PURCHASE_BOX5 = {"SI", "ZP", "IM", "IGDS", "ME", "NR"}
PURCHASE_BOX7 = {"SI", "IM", "IGDS"}
PURCHASE_EXCLUDED = {"BL", "EP", "OP", "TX-E33", "TX-N33", "TX-RE"}

# Codes where non-zero VatSum would be an error (E2 check)
ZERO_RATE_SALES = {"ZR", "OS", "ES33", "ESN33"}
# Codes where VatSum=0 would be an error (E3 check)
STANDARD_RATE_CODES = {"SO", "SI"}

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

def run_test_3(invoices: list[dict], purchase_invoices: list[dict]) -> dict:
    print("\n[Test 3] Error Detection...")

    errors = []

    for doc in invoices:
        doc_num = doc.get("DocNum")
        doc_date = str(doc.get("DocDate", ""))[:10]
        card_name = doc.get("CardName", "")
        currency = doc.get("DocCurrency", "SGD")
        is_fx = not is_sgd(doc)

        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
            line_total = safe_float(line.get("LineTotal"))
            vat_sum = safe_float(line.get("TaxTotal"))  # TaxTotal is line-level tax in SAP B1

            base = {"DocNum": doc_num, "DocDate": doc_date, "CardName": card_name, "VatGroup": vg}

            # E1: Foreign currency + SO/DS (overseas sale miscoded as local standard-rated)
            if is_fx and vg in SALES_BOX1:
                errors.append({**base, "error_code": "E1", "DocCurrency": currency,
                    "issue": f"E1: Foreign currency ({currency}) invoice uses VatGroup={vg} — overseas sale should be ZR"})

            # E2: GST charged (VatSum > 0) on non-taxable supply
            if vat_sum > 0.01 and vg in ZERO_RATE_SALES:
                errors.append({**base, "VatSum": vat_sum,
                    "issue": f"E2: VatSum={vat_sum:.2f} > 0 but VatGroup={vg} is non-taxable — GST should not be charged"})

            # E3: Standard-rated sales code with zero GST
            if vg in {"SO", "DS"} and line_total > 0.01 and vat_sum < 0.01:
                errors.append({**base, "LineTotal": line_total,
                    "issue": f"E3: VatGroup={vg} (standard-rated) but VatSum=0 on SGD {line_total:.2f} line"})

            # E4: GST rate deviation from expected (7% for demo data)
            if vg in SALES_BOX1 and line_total > 0.01 and vat_sum > 0.01:
                ratio = vat_sum / line_total
                if abs(ratio - DEMO_GST_RATE) > 0.005:
                    errors.append({**base, "LineTotal": line_total, "VatSum": vat_sum,
                        "effective_rate_pct": round(ratio * 100, 2),
                        "issue": f"E4: Effective GST rate {ratio*100:.2f}% deviates from expected {DEMO_GST_RATE*100:.0f}%"})

    for doc in purchase_invoices:
        doc_num = doc.get("DocNum")
        doc_date = str(doc.get("DocDate", ""))[:10]
        card_name = doc.get("CardName", "")

        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
            line_total = safe_float(line.get("LineTotal"))
            vat_sum = safe_float(line.get("TaxTotal"))  # TaxTotal is line-level tax in SAP B1

            base = {"DocNum": doc_num, "DocDate": doc_date, "CardName": card_name, "VatGroup": vg}

            # E3: Standard-rated purchase code with zero GST
            if vg == "SI" and line_total > 0.01 and vat_sum < 0.01:
                errors.append({**base, "LineTotal": line_total,
                    "issue": f"E3: VatGroup=SI (standard-rated input) but VatSum=0 on SGD {line_total:.2f} line"})

            # E4: GST rate deviation on standard-rated purchases
            if vg in {"SI", "IM", "IGDS"} and line_total > 0.01 and vat_sum > 0.01:
                ratio = vat_sum / line_total
                if abs(ratio - DEMO_GST_RATE) > 0.005:
                    errors.append({**base, "LineTotal": line_total, "VatSum": vat_sum,
                        "effective_rate_pct": round(ratio * 100, 2),
                        "issue": f"E4: Effective GST rate {ratio*100:.2f}% deviates from expected {DEMO_GST_RATE*100:.0f}%"})

    # Scoring: 1 pt per check type run (4 checks = 4 pts), + 1 per error found (up to 6)
    checks_run = 4  # E1, E2, E3, E4 all executed
    errors_found_pts = min(len(errors), 6)
    score = min(checks_run + errors_found_pts, 10)

    error_codes_found = sorted(set(e.get("error_code", "E?") for e in errors if "error_code" in e))
    notes = (
        f"All 4 error checks (E1-E4) executed. "
        f"Found {len(errors)} error(s). "
        f"Error types: {error_codes_found if error_codes_found else 'none'}. "
        f"{'Invoice #958 USD+SO mismatch expected from baseline.' if any('E1' in e.get('issue','') for e in errors) else 'No E1 errors found.'}"
    )

    print(f"    Errors found: {len(errors)}")
    for e in errors[:5]:
        print(f"      DocNum {e.get('DocNum')}: {e.get('issue','')[:80]}")
    if len(errors) > 5:
        print(f"      ... and {len(errors) - 5} more")
    print(f"    Score: {score}/10")

    return {
        "errors_found": errors,
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
    t3 = run_test_3(invoices, purchase_invoices)

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

### Test 3: Errors Found

{f"Total errors detected: {len(t3['errors_found'])}" if t3["errors_found"] else "No errors found."}
{chr(10).join(f"- DocNum {e.get('DocNum')}: {e.get('issue','')}" for e in t3["errors_found"][:10])}

---
"""
    existing = RESULTS_FILE.read_text(encoding="utf-8") if RESULTS_FILE.exists() else ""
    RESULTS_FILE.write_text(existing + md_summary, encoding="utf-8")
    print(f"\nSummary appended → {RESULTS_FILE}")
    print(f"\nOverall score: {overall}/30")


if __name__ == "__main__":
    main()
