#!/usr/bin/env python3
"""
Cancels the test invoices created by seed_test_data.py.
Reads DocEntry values from scripts/test_data_registry.json.

Note: SAP B1 does not allow deletion of posted invoices — we cancel them instead.
"""

import getpass
import json
import sys
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

    def post(self, path: str, body: dict = None) -> tuple[int, str]:
        resp = self.s.post(f"{BASE_URL}/{path}", json=body or {})
        return resp.status_code, resp.text[:500]


def cancel_document(b1: B1Session, entity: str, doc_entry: int, label: str) -> bool:
    path = f"{entity}({doc_entry})/cancel"
    status, text = b1.post(path)
    if status in (200, 201, 204):
        print(f"  ✓  Cancelled {label} (DocEntry {doc_entry})")
        return True
    else:
        print(f"  ✗  Failed to cancel {label} (DocEntry {doc_entry}): HTTP {status} — {text[:200]}")
        return False


def main():
    print("=" * 60)
    print("SAP B1 — Cleanup Test Data")
    print("=" * 60)

    if not REGISTRY_FILE.exists():
        print(f"Registry not found: {REGISTRY_FILE}", file=sys.stderr)
        print("Run seed_test_data.py first.", file=sys.stderr)
        sys.exit(1)

    registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    created_at = registry.get("created_at", "unknown")
    invoices = registry.get("invoices", [])
    purchases = registry.get("purchase_invoices", [])

    print(f"\nRegistry created: {created_at}")
    print(f"  Sales invoices: {len(invoices)}")
    print(f"  Purchase invoices: {len(purchases)}")

    if not invoices and not purchases:
        print("Nothing to cancel.")
        return

    password = load_password()
    print("\nConnecting to SAP B1...")
    b1 = B1Session(password)

    print("\nCancelling sales invoices...")
    ok = err = 0
    for rec in invoices:
        success = cancel_document(b1, "Invoices", rec["DocEntry"], rec.get("label", f"DocNum {rec['DocNum']}"))
        if success:
            ok += 1
        else:
            err += 1

    print("\nCancelling purchase invoices...")
    for rec in purchases:
        success = cancel_document(b1, "PurchaseInvoices", rec["DocEntry"], rec.get("label", f"DocNum {rec['DocNum']}"))
        if success:
            ok += 1
        else:
            err += 1

    total = ok + err
    print(f"\nDone: {ok}/{total} cancelled, {err} failed.")
    if err > 0:
        print("Review errors above — documents may already be cancelled or linked to dependent records.")


if __name__ == "__main__":
    main()
