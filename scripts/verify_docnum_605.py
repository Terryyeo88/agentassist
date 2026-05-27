#!/usr/bin/env python3
"""
Verify the TaxTotal of DocNum 605 (VatGroup=BL purchase invoice) in SBODEMOSG.
Determines whether it qualifies as an E2 error for Test 3 scoring purposes.

Usage: python scripts/verify_docnum_605.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://35.186.145.230:55000/b1s/v2"
COMPANY_DB = "SBODEMOSG"
USERNAME = "manager"

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CREDS_FILE = PROJECT_ROOT / "keys" / "sap_credentials.json"


def load_password() -> str:
    if CREDS_FILE.exists():
        creds = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
        return creds["password"]
    import getpass
    return getpass.getpass("Enter SAP B1 manager password: ")


def safe_float(val) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


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

    def logout(self):
        try:
            self.s.post(f"{BASE_URL}/Logout")
            print("  Logged out.")
        except Exception as e:
            print(f"  Logout warning: {e}")


def main():
    print("=" * 60)
    print("SAP B1 — DocNum 605 TaxTotal Verification")
    print(f"Run date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    password = load_password()
    print("\nConnecting to SAP B1...")
    b1 = B1Session(password)

    # Query: filter PurchaseInvoices by DocNum eq 605
    # DocumentLines are returned inline by SAP B1 Service Layer without needing $expand
    query = "DocNum eq 605"
    print(f"\nQuery: GET /PurchaseInvoices?$filter={query}")
    print()

    data = b1.get("PurchaseInvoices", params={"$filter": query})
    docs = data.get("value", [])

    if not docs:
        print("ERROR: No PurchaseInvoice found with DocNum=605.")
        b1.logout()
        return

    doc = docs[0]

    # --- Header fields ---
    print("HEADER FIELDS")
    print("-" * 40)
    header_fields = [
        ("DocEntry",      doc.get("DocEntry")),
        ("DocNum",        doc.get("DocNum")),
        ("DocDate",       str(doc.get("DocDate", ""))[:10]),
        ("CardCode",      doc.get("CardCode")),
        ("CardName",      doc.get("CardName")),
        ("DocCurrency",   doc.get("DocCurrency")),
        ("DocTotal",      safe_float(doc.get("DocTotal"))),
        ("VatSum",        safe_float(doc.get("VatSum"))),      # header-level tax total
        ("DocTotalFc",    safe_float(doc.get("DocTotalFc"))),  # foreign-currency total if any
    ]
    for name, val in header_fields:
        print(f"  {name:20s}: {val}")

    # --- Document lines ---
    lines = doc.get("DocumentLines", [])
    print(f"\nDOCUMENT LINES ({len(lines)} line(s))")
    print("-" * 40)

    bl_lines_with_tax = 0
    for line in lines:
        vg       = (line.get("VatGroup") or "").strip()
        line_num = line.get("LineNum")
        item     = line.get("ItemCode", "(none)")
        desc     = line.get("ItemDescription", "")
        lt       = safe_float(line.get("LineTotal"))
        tt       = safe_float(line.get("TaxTotal"))
        vat_pct  = line.get("VatPercent") or line.get("TaxPercentagePerRow") or "?"

        print(f"  Line {line_num}:")
        print(f"    ItemCode       : {item}")
        print(f"    ItemDescription: {desc}")
        print(f"    VatGroup       : {vg}")
        print(f"    LineTotal      : {lt:.2f}")
        print(f"    TaxTotal       : {tt:.2f}")
        print(f"    VatPercent     : {vat_pct}")

        if vg == "BL" and tt > 0.01:
            bl_lines_with_tax += 1
            print(f"    *** E2 candidate: BL line with TaxTotal={tt:.2f} > 0 ***")
        print()

    # --- Summary ---
    e2_status = bl_lines_with_tax > 0
    print("SUMMARY")
    print("-" * 40)
    print(f"  DocNum 605 has {len(lines)} line(s).")
    print(f"  Lines with VatGroup=BL and TaxTotal>0.01: {bl_lines_with_tax}")
    print(f"  E2 status: {'TRUE' if e2_status else 'FALSE'}")
    print()

    b1.logout()
    print("\nDone.")

    return {
        "doc_entry":        doc.get("DocEntry"),
        "doc_num":          doc.get("DocNum"),
        "doc_date":         str(doc.get("DocDate", ""))[:10],
        "card_code":        doc.get("CardCode"),
        "card_name":        doc.get("CardName"),
        "doc_currency":     doc.get("DocCurrency"),
        "doc_total":        safe_float(doc.get("DocTotal")),
        "header_vat_sum":   safe_float(doc.get("VatSum")),
        "lines":            [
            {
                "line_num":    ln.get("LineNum"),
                "item_code":   ln.get("ItemCode"),
                "vat_group":   (ln.get("VatGroup") or "").strip(),
                "line_total":  safe_float(ln.get("LineTotal")),
                "tax_total":   safe_float(ln.get("TaxTotal")),
                "vat_percent": ln.get("VatPercent") or ln.get("TaxPercentagePerRow"),
            }
            for ln in lines
        ],
        "bl_lines_with_tax": bl_lines_with_tax,
        "e2_status":         e2_status,
    }


if __name__ == "__main__":
    main()
