#!/usr/bin/env python3
"""
Creates 6 synthetic test invoices in SAP B1 SBODEMOSG for GST F5 baseline testing.
All dated 2024-07-15 (Q3 2024), tagged FreeText=BASELINE_TEST_DATA for cleanup.
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
    print("SAP B1 — Seed Test Data")
    print("=" * 60)

    password = load_password()
    print("\nConnecting to SAP B1...")
    b1 = B1Session(password)

    print("\nLooking up an item code for invoice lines...")
    item_code = find_item_code(b1)

    invoices_out = []
    purchases_out = []
    errors = []

    print("\nCreating test invoices...\n")
    for spec in INVOICE_SPECS:
        entity = spec["_entity"]
        label = spec["_label"]
        body = copy.deepcopy({k: v for k, v in spec.items() if not k.startswith("_")})
        for line in body["DocumentLines"]:
            line["ItemCode"] = item_code

        print(f"  {label}")
        try:
            result = b1.post(entity, body)
            doc_num = result.get("DocNum")
            doc_entry = result.get("DocEntry")
            print(f"    ✓  DocNum: {doc_num}  DocEntry: {doc_entry}")
            record = {"DocNum": doc_num, "DocEntry": doc_entry, "label": label}
            if entity == "Invoices":
                invoices_out.append(record)
            else:
                purchases_out.append(record)
        except RuntimeError as exc:
            print(f"    ✗  FAILED: {exc}", file=sys.stderr)
            errors.append({"label": label, "error": str(exc)})

    if errors:
        print(f"\n{len(errors)} invoice(s) failed — aborting.", file=sys.stderr)
        sys.exit(1)

    registry = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "invoices": invoices_out,
        "purchase_invoices": purchases_out,
    }
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    print(f"\nRegistry saved → {REGISTRY_FILE}")
    print(f"Done — {len(invoices_out)} sales invoices, {len(purchases_out)} purchase invoices created.")


if __name__ == "__main__":
    main()
