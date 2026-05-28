#!/usr/bin/env python3
"""
Creates synthetic test documents in SAP B1 SBODEMOSG for GST F5 baseline testing.
Invoices 1–7 (Q3 2024) were created in an earlier run; this script now also creates
Credit Notes A and B for T1.1 credit note support testing.
All documents tagged FreeText=BASELINE_TEST_DATA (at line level for credit notes).
"""

import copy
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

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CREDS_FILE = PROJECT_ROOT / "keys" / "sap_credentials.json"
REGISTRY_FILE = SCRIPT_DIR / "test_data_registry.json"

# Invoice definitions: entity + label are metadata stripped before POST
INVOICE_SPECS = [
    {
        "_entity": "Invoices",
        "_label": "Invoice 1 — Zero-rated sales (ZR)",
        "CardCode": "C26000",
        "DocDate": "2024-07-15",
        "FreeText": "BASELINE_TEST_DATA",
        "DocumentLines": [{
            "ItemDescription": "Export Sale - Hard Disk",
            "Quantity": 1,
            "UnitPrice": 5000.00,
            "LineTotal": 5000.00,
            "VatGroup": "ZR",
        }],
    },
    {
        "_entity": "Invoices",
        "_label": "Invoice 2 — Exempt sales (ES33)",
        "CardCode": "C26000",
        "DocDate": "2024-07-15",
        "FreeText": "BASELINE_TEST_DATA",
        "DocumentLines": [{
            "ItemDescription": "Financial Advisory Service",
            "Quantity": 1,
            "UnitPrice": 3000.00,
            "LineTotal": 3000.00,
            "VatGroup": "ES33",
        }],
    },
    {
        "_entity": "Invoices",
        "_label": "Invoice 3 — Out of scope (OS)",
        "CardCode": "C26000",
        "DocDate": "2024-07-15",
        "FreeText": "BASELINE_TEST_DATA",
        "DocumentLines": [{
            "ItemDescription": "Overseas Goods - Out of Scope",
            "Quantity": 1,
            "UnitPrice": 2000.00,
            "LineTotal": 2000.00,
            "VatGroup": "OS",
        }],
    },
    {
        "_entity": "PurchaseInvoices",
        "_label": "Invoice 4 — Blocked input tax (BL)",
        "CardCode": "V10000",
        "DocDate": "2024-07-15",
        "FreeText": "BASELINE_TEST_DATA",
        "DocumentLines": [{
            "ItemDescription": "Staff Club Membership",
            "Quantity": 1,
            "UnitPrice": 800.00,
            "LineTotal": 800.00,
            "VatGroup": "BL",
        }],
    },
    {
        "_entity": "PurchaseInvoices",
        "_label": "Invoice 5 — Import GST (IM)",
        "CardCode": "V10000",
        "DocDate": "2024-07-15",
        "FreeText": "BASELINE_TEST_DATA",
        "DocumentLines": [{
            "ItemDescription": "Imported Components",
            "Quantity": 1,
            "UnitPrice": 4500.00,
            "LineTotal": 4500.00,
            "VatGroup": "IM",
        }],
    },
    {
        "_entity": "PurchaseInvoices",
        "_label": "Invoice 6 — Zero-rated purchase (ZP)",
        "CardCode": "V10000",
        "DocDate": "2024-07-15",
        "FreeText": "BASELINE_TEST_DATA",
        "DocumentLines": [{
            "ItemDescription": "International Freight",
            "Quantity": 1,
            "UnitPrice": 1200.00,
            "LineTotal": 1200.00,
            "VatGroup": "ZP",
        }],
    },
    # Invoice 7 — Non-GST registered purchase (NR), non-zero TaxTotal
    # Purpose: tests that NR LineTotal is excluded from Box 5 after the T1.2 fix
    # Also an E2 candidate if SAP B1 preserves TaxTotal on NR lines (non-taxable
    # purchase carrying GST). If SAP zeroes TaxTotal on save, the E2 angle is moot
    # and this invoice tests Box 5 exclusion only.
    {
        "_entity": "PurchaseInvoices",
        "_label": "Invoice 7 — Non-GST registered purchase (NR)",
        "CardCode": "V10000",
        "DocDate": "2024-09-15",
        "DocDueDate": "2024-10-15",
        "FreeText": "BASELINE_TEST_DATA",
        "DocumentLines": [
            {
                "ItemCode": "Z00002",
                "Quantity": 1,
                "UnitPrice": 500.00,
                "VatGroup": "NR",
                "TaxTotal": 45.00,
            }
        ],
    },
]

# Credit note seeds for T1.1 — created separately from the original invoice seeds.
# FreeText tagging is at the line level (FreeText is a line-level field in SAP B1 SL).
# SAP B1 SBODEMOSG calculates TaxTotal from the VatGroup tax code at its demo rate (7%).
# Expected deltas vs pre-seed Q3 2024 F5:
#   Credit Note A: Box 1 -= 1000.00, Box 6 -= <SAP-calculated TaxTotal at 7% = 70.00>
#   Credit Note B: Box 5 -= 500.00,  Box 7 -= <SAP-calculated TaxTotal at 7% = 35.00>
CREDIT_NOTE_SPECS = [
    {
        "_entity": "CreditNotes",
        "_label": "Credit Note A — Standard-rated sales credit (SO)",
        "CardCode": "C26000",
        "DocDate": "2024-08-01",
        "DocumentLines": [{
            "ItemDescription": "Credit — Standard-Rated Sale Return",
            "Quantity": 1,
            "UnitPrice": 1000.00,
            "LineTotal": 1000.00,
            "VatGroup": "SO",
            "FreeText": "BASELINE_TEST_DATA",
        }],
    },
    {
        "_entity": "PurchaseCreditNotes",
        "_label": "Credit Note B — Standard-rated purchase credit (SI)",
        "CardCode": "V10000",
        "DocDate": "2024-08-01",
        "DocumentLines": [{
            "ItemDescription": "Credit — Standard-Rated Purchase Return",
            "Quantity": 1,
            "UnitPrice": 500.00,
            "LineTotal": 500.00,
            "VatGroup": "SI",
            "FreeText": "BASELINE_TEST_DATA",
        }],
    },
]


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

    def post(self, path: str, body: dict) -> dict:
        resp = self.s.post(f"{BASE_URL}/{path}", json=body)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"POST /{path} ({resp.status_code}): {resp.text[:1000]}")
        return resp.json()


def find_item_code(b1: B1Session) -> str:
    data = b1.get("Items", {"$top": 10, "$select": "ItemCode,ItemName,ItemType"})
    items = data.get("value", [])
    if not items:
        raise RuntimeError("No items found in SAP B1 — cannot create invoice lines")
    item = items[0]
    print(f"  Using ItemCode: {item['ItemCode']} ({item.get('ItemName', '?')})")
    return item["ItemCode"]


def main():
    print("=" * 60)
    print("SAP B1 - Seed Test Data (Credit Notes)")
    print("=" * 60)
    print()
    print("Seed amounts:")
    print("  Credit Note A (CreditNotes/SO):         LineTotal=1000.00")
    print("  Credit Note B (PurchaseCreditNotes/SI): LineTotal= 500.00")
    print("  TaxTotal is SAP-calculated (7% demo rate):")
    print("    Credit Note A expected TaxTotal: 70.00")
    print("    Credit Note B expected TaxTotal: 35.00")
    print("  Expected F5 deltas vs pre-seed Q3 2024 figures:")
    print("    Box 1 (standard-rated sales):   -1000.00")
    print("    Box 5 (taxable purchases):        -500.00")
    print("    Box 6 (output tax):                -70.00")
    print("    Box 7 (input tax):                 -35.00")
    print("    Box 4 (total sales):             -1000.00")
    print("    Box 8 (net GST):                   -35.00  (Box 6 - Box 7 = -70 - -35)")
    print()

    password = load_password()
    print("\nConnecting to SAP B1...")
    b1 = B1Session(password)

    print("\nLooking up an item code for credit note lines...")
    item_code = find_item_code(b1)

    credit_notes_out = []
    purchase_credit_notes_out = []
    errors = []

    print("\nCreating credit note seed documents...\n")
    for spec in CREDIT_NOTE_SPECS:
        entity = spec["_entity"]
        label = spec["_label"]
        body = copy.deepcopy({k: v for k, v in spec.items() if not k.startswith("_")})
        for line in body["DocumentLines"]:
            if "ItemCode" not in line:
                line["ItemCode"] = item_code

        print(f"  {label}")
        try:
            result = b1.post(entity, body)
            doc_num = result.get("DocNum")
            doc_entry = result.get("DocEntry")
            # Confirm actual TaxTotal SAP applied
            detail = b1.get(f"{entity}({doc_entry})")
            lines = detail.get("DocumentLines", [])
            actual_tax = sum(l.get("TaxTotal", 0) for l in lines)
            actual_lt = sum(l.get("LineTotal", 0) for l in lines)
            print(f"    ✓  DocNum: {doc_num}  DocEntry: {doc_entry}")
            print(f"       LineTotal: {actual_lt:.2f}  TaxTotal (SAP-calculated): {actual_tax:.2f}")
            record = {"DocNum": doc_num, "DocEntry": doc_entry, "label": label,
                      "line_total": actual_lt, "tax_total": actual_tax}
            if entity == "CreditNotes":
                credit_notes_out.append(record)
            else:
                purchase_credit_notes_out.append(record)
        except RuntimeError as exc:
            print(f"    ✗  FAILED: {exc}", file=sys.stderr)
            errors.append({"label": label, "error": str(exc)})

    if errors:
        print(f"\n{len(errors)} document(s) failed — aborting registry update.", file=sys.stderr)
        sys.exit(1)

    # Load existing registry and append credit note entries
    if REGISTRY_FILE.exists():
        registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    else:
        registry = {"invoices": [], "purchase_invoices": []}

    registry["credit_notes"] = credit_notes_out
    registry["purchase_credit_notes"] = purchase_credit_notes_out
    registry["credit_notes_created_at"] = datetime.now(timezone.utc).isoformat()

    REGISTRY_FILE.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    print(f"\nRegistry updated → {REGISTRY_FILE}")
    print(f"Done — {len(credit_notes_out)} sales credit note(s), "
          f"{len(purchase_credit_notes_out)} purchase credit note(s) created.")


if __name__ == "__main__":
    main()
