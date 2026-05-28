#!/usr/bin/env python3
"""
Creates synthetic test invoices in SAP B1 SBODEMOSG for GST F5 baseline testing.
All dated 2024-07-15 (Q3 2024), tagged FreeText=BASELINE_TEST_DATA for cleanup.

Connection details come from config/clients/<CLIENT_ID>.yaml (default: sbodemosg)
so that seed writes and baseline tests always target the same SAP instance.
"""

import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3

# Add repo root to sys.path so config.loader is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass  # rely on environment being pre-set if dotenv is unavailable

from config.loader import load_client_config  # noqa: E402

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load client config — defaults to sbodemosg; override with CLIENT_ID env var.
# IMPORTANT: seed writes must always target the same instance as run_baseline_tests.py.
# Both scripts read the same CLIENT_ID env var and the same YAML, so they cannot diverge.
_cfg = load_client_config(
    os.environ.get("CLIENT_ID", "sbodemosg"),
    check_connectivity=False,
)

BASE_URL = _cfg.service_layer_url
COMPANY_DB = _cfg.company_db

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
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
]


class B1Session:
    def __init__(self):
        self.s = requests.Session()
        self.s.verify = _cfg.ssl_verify
        resp = self.s.post(f"{BASE_URL}/Login", json={
            "CompanyDB": COMPANY_DB,
            "UserName": _cfg.username,
            "Password": _cfg.password,
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
    print(f"Client: {_cfg.client_name} ({_cfg.client_id})")
    print(f"SAP B1: {BASE_URL}  company_db={COMPANY_DB}")

    print("\nConnecting to SAP B1...")
    b1 = B1Session()

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
