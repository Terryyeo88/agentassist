#!/usr/bin/env python3
"""
scripts/seed_demo.py — Seed demo PurchaseInvoices into SAP B1 SBODEMOSG.

Two groups seeded into a target period (passed via --period):

  GROUP 1  8 PurchaseInvoices mirroring the T2.8 document-reconciliation
           fixture cases, with controlled injected issues baked into the PDFs.
  GROUP 2  5 PurchaseInvoices whose SI line descriptions trigger the Reg 26/27
           reasoning layer: club_subscriptions, medical_expenses (x2),
           family_benefits, motor_car_s_plate.

Modes:
  (default) --dry-run: Print the seed plan. No writes to SAP. No PDFs.
  --commit            : POST documents to SAP, capture DocNums, generate PDFs
                        keyed INV-<DocNum>.pdf, write scripts/seed_manifest.json.

Every seeded document carries AGENTASSIST_SEED in Remarks so seeds can be
found and cancelled (via cleanup_test_data.py pattern) at any time.

Usage:
    # Review plan (safe, no writes):
    python scripts/seed_demo.py --client sbodemosg --period 2024-07-01 2024-09-30

    # Execute:
    python scripts/seed_demo.py --client sbodemosg --period 2024-07-01 2024-09-30 \\
        --commit --upload-dir scripts/seed_uploads
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
import urllib3

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

from config.loader import load_client_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED_MARKER    = "AGENTASSIST_SEED"
_VENDOR        = "V21000"   # Sea Corp — FederalTaxID=SK98467789, confirmed GST-registered cSupplier in SBODEMOSG
_ITEM          = "A00001"   # J.B. Officeprint 1420 — confirmed PVATGroup=SI
_EXPECTED_RATE = 0.07       # SAP computes TaxTotal internally; 7% confirmed on SBODEMOSG 2024 dates

# ---------------------------------------------------------------------------
# Group 1 case specifications (8 document-reconciliation cases)
#
# pdf_gst_amount   None  → PDF GST = SAP-computed TaxTotal (no GST injection)
#                  float → INJECTED PDF GST (used for gst_amount_mismatch / combined)
# pdf_gst_rate_label None → "7%"
# pdf_gst_reg      True  → include supplier_gst_reg_str in PDF
#                  False → INJECTED: omit GST reg from PDF (supplier_gst_reg_absent)
# pdf_date_delta   0     → PDF date = SAP DocDate
#                  N>0   → INJECTED: PDF date = period_end + N days (date_outside_period)
# pdf_total_delta  0.0   → PDF total = excl_gst + gst_amount (correct)
#                  N>0   → INJECTED: PDF total overstated by N (total_inconsistency)
# day_offset            → SAP DocDate = period_start + day_offset (clamped to period_end)
# ---------------------------------------------------------------------------

_G1: list[dict] = [
    {
        "case_name": "clean_1",
        "injected_issue": "none",
        "day_offset": 14,
        "unit_price": 5000.00,
        "item_desc": "Professional IT Consulting Services",
        "supplier_name": "TechSupply Solutions Pte Ltd",
        "supplier_addr": "100 Beach Road #20-01, Singapore 189702",
        "supplier_gst_reg_str": "M12345678X",
        "customer_name": "Acme Corporation Pte Ltd",
        "customer_addr": "50 Raffles Place #30-01, Singapore 048623",
        "pdf_gst_amount": None,
        "pdf_gst_rate_label": None,
        "pdf_gst_reg": True,
        "pdf_date_delta": 0,
        "pdf_total_delta": 0.0,
    },
    {
        "case_name": "clean_2",
        "injected_issue": "none",
        "day_offset": 50,
        "unit_price": 2800.00,
        "item_desc": "Office Supplies - Stationery and Consumables",
        "supplier_name": "Office Essentials Pte Ltd",
        "supplier_addr": "30 Tanjong Pagar Road, Singapore 088461",
        "supplier_gst_reg_str": "M87654321X",
        "customer_name": "BuildCo Engineering Pte Ltd",
        "customer_addr": "200 Pandan Loop, Singapore 128388",
        "pdf_gst_amount": None,
        "pdf_gst_rate_label": None,
        "pdf_gst_reg": True,
        "pdf_date_delta": 0,
        "pdf_total_delta": 0.0,
    },
    {
        "case_name": "gst_mismatch_over",
        "injected_issue": "gst_amount_mismatch",
        "day_offset": 29,
        "unit_price": 12000.00,
        "item_desc": "Excavator Equipment Rental - Monthly Hire",
        "supplier_name": "Heavy Equipment Rentals Pte Ltd",
        "supplier_addr": "45 Tuas Avenue 11, Singapore 638785",
        "supplier_gst_reg_str": "M11223344X",
        "customer_name": "ConstructMaster Pte Ltd",
        "customer_addr": "10 Changi South Lane, Singapore 486162",
        "pdf_gst_amount": 900.00,   # INJECTED — SAP will compute ~840.00 (7%)
        "pdf_gst_rate_label": "7%",
        "pdf_gst_reg": True,
        "pdf_date_delta": 0,
        "pdf_total_delta": 0.0,
    },
    {
        "case_name": "gst_mismatch_under",
        "injected_issue": "gst_amount_mismatch",
        "day_offset": 35,
        "unit_price": 3200.00,
        "item_desc": "Corporate Catering Services - Board Meeting",
        "supplier_name": "Premium Catering Services Pte Ltd",
        "supplier_addr": "22 Jurong Port Road, Singapore 619092",
        "supplier_gst_reg_str": "M99887766X",
        "customer_name": "Events Management Asia Ltd",
        "customer_addr": "80 Middle Road #10-01, Singapore 188966",
        "pdf_gst_amount": 192.00,   # INJECTED — 6% of 3200; SAP will have 224.00 (7%)
        "pdf_gst_rate_label": "6%", # INJECTED — wrong rate label
        "pdf_gst_reg": True,
        "pdf_date_delta": 0,
        "pdf_total_delta": 0.0,
    },
    {
        "case_name": "no_gst_reg",
        "injected_issue": "supplier_gst_reg_absent",
        "day_offset": 71,
        "unit_price": 1500.00,
        "item_desc": "Fresh Produce Supply - Delivery Batch",
        "supplier_name": "Fresh Food Distributors Pte Ltd",
        "supplier_addr": "5 Senoko Way, Singapore 758057",
        "supplier_gst_reg_str": "M55667788X",
        "customer_name": "FoodChain Operations Pte Ltd",
        "customer_addr": "25 Mandai Estate, Singapore 729933",
        "pdf_gst_amount": None,
        "pdf_gst_rate_label": None,
        "pdf_gst_reg": False,       # INJECTED — GST reg omitted from PDF face
        "pdf_date_delta": 0,
        "pdf_total_delta": 0.0,
    },
    {
        # SAP DocDate = period_start (within period so chain fetches this doc).
        # PDF date = period_end + 5 days (outside period → reconcile flags date_outside_period).
        "case_name": "date_outside_period",
        "injected_issue": "date_outside_period",
        "day_offset": 0,
        "unit_price": 7800.00,
        "item_desc": "Network Infrastructure Maintenance - Support Services",
        "supplier_name": "TechSupply Solutions Pte Ltd",
        "supplier_addr": "100 Beach Road #20-01, Singapore 189702",
        "supplier_gst_reg_str": "M12345678X",
        "customer_name": "LogiCo Singapore Pte Ltd",
        "customer_addr": "3 Changi Business Park Vista, Singapore 486051",
        "pdf_gst_amount": None,
        "pdf_gst_rate_label": None,
        "pdf_gst_reg": True,
        "pdf_date_delta": 5,        # INJECTED — PDF date = period_end + 5 days
        "pdf_total_delta": 0.0,
    },
    {
        "case_name": "total_inconsistency",
        "injected_issue": "total_inconsistency",
        "day_offset": 52,
        "unit_price": 4200.00,
        "item_desc": "Digital Marketing Campaign Services",
        "supplier_name": "MarketSG Advertising Pte Ltd",
        "supplier_addr": "14 Science Park Drive, Singapore 118228",
        "supplier_gst_reg_str": "M44556677X",
        "customer_name": "RetailPro Solutions Ltd",
        "customer_addr": "60 Alexandra Terrace #08-18, Singapore 118502",
        "pdf_gst_amount": None,
        "pdf_gst_rate_label": None,
        "pdf_gst_reg": True,
        "pdf_date_delta": 0,
        "pdf_total_delta": 36.0,    # INJECTED — PDF total overstated by 36.00
    },
    {
        "case_name": "combined",
        "injected_issue": "combined",
        "day_offset": 76,
        "unit_price": 6000.00,
        "item_desc": "Building Cleaning and Maintenance Services",
        "supplier_name": "CleanSpace Facilities Pte Ltd",
        "supplier_addr": "77 Science Park Drive, Singapore 118256",
        "supplier_gst_reg_str": "M33221100X",
        "customer_name": "PropMgmt Singapore Pte Ltd",
        "customer_addr": "1 Marina Boulevard, Singapore 018989",
        "pdf_gst_amount": 360.00,   # INJECTED — 6% of 6000; SAP will have 420.00 (7%)
        "pdf_gst_rate_label": "7%",
        "pdf_gst_reg": False,       # INJECTED — GST reg omitted
        "pdf_date_delta": 0,
        "pdf_total_delta": 0.0,
    },
]

# ---------------------------------------------------------------------------
# Group 2 case specifications (5 Reg 26/27 reasoning-bait cases)
#
# Descriptions chosen to match the KB categories the reasoning layer looks for.
# All are clean PDFs (no document-reconciliation injections).
# ---------------------------------------------------------------------------

_G2: list[dict] = [
    {
        "case_name": "club_subscriptions",
        "kb_category": "club_subscriptions",
        "kb_note": "sporting/recreational club subscription, membership, transfer fees — IRAS Reg 26/27",
        "day_offset": 20,
        "unit_price": 1200.00,
        "item_desc": "Annual Sports Club Membership Subscription and Transfer Fees 2024",
        "supplier_name": "Singapore Sports Club Pte Ltd",
        "supplier_addr": "1 Sports Drive, Singapore 397628",
        "supplier_gst_reg_str": "M20240001X",
        "customer_name": "Acme Corporation Pte Ltd",
        "customer_addr": "50 Raffles Place #30-01, Singapore 048623",
    },
    {
        "case_name": "medical_expenses_direct",
        "kb_category": "medical_expenses",
        "kb_note": "staff medical expenses — consultations, dental, health screenings — IRAS Reg 26/27",
        "day_offset": 35,
        "unit_price": 3500.00,
        "item_desc": "Staff Annual Health Screening, Dental Consultation and Medical Examination Fees",
        "supplier_name": "HealthFirst Medical Group Pte Ltd",
        "supplier_addr": "10 Novena Walk, Singapore 307602",
        "supplier_gst_reg_str": "M20240002X",
        "customer_name": "Acme Corporation Pte Ltd",
        "customer_addr": "50 Raffles Place #30-01, Singapore 048623",
    },
    {
        "case_name": "medical_expenses_insurance",
        "kb_category": "medical_expenses",
        "kb_note": "staff medical and accident insurance premiums — IRAS Reg 26/27",
        "day_offset": 45,
        "unit_price": 8400.00,
        "item_desc": "Staff Group Medical and Accident Insurance Premiums 2024",
        "supplier_name": "Great Eastern Life Assurance Co Ltd",
        "supplier_addr": "1 Pickering Street, Singapore 048659",
        "supplier_gst_reg_str": "M20240003X",
        "customer_name": "Acme Corporation Pte Ltd",
        "customer_addr": "50 Raffles Place #30-01, Singapore 048623",
    },
    {
        "case_name": "family_benefits",
        "kb_category": "family_benefits",
        "kb_note": "benefits for family members/relatives of staff — IRAS Reg 26/27",
        "day_offset": 60,
        "unit_price": 2200.00,
        "item_desc": "Staff Family Benefits Package - Spouse and Children Educational and Medical Benefits",
        "supplier_name": "Corporate Benefits Asia Pte Ltd",
        "supplier_addr": "20 Cecil Street #10-01, Singapore 049705",
        "supplier_gst_reg_str": "M20240004X",
        "customer_name": "Acme Corporation Pte Ltd",
        "customer_addr": "50 Raffles Place #30-01, Singapore 048623",
    },
    {
        "case_name": "motor_car_s_plate",
        "kb_category": "motor_car_s_plate",
        "kb_note": "S-plate private motor car costs and running expenses — IRAS Reg 26/27",
        "day_offset": 75,
        "unit_price": 4800.00,
        "item_desc": "Company Private Car (S-Plate) Petrol, Parking, Road Tax and Maintenance Expenses",
        "supplier_name": "AutoServ Singapore Pte Ltd",
        "supplier_addr": "30 Tuas Road, Singapore 638490",
        "supplier_gst_reg_str": "M20240005X",
        "customer_name": "Acme Corporation Pte Ltd",
        "customer_addr": "50 Raffles Place #30-01, Singapore 048623",
    },
]


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------

def _et(price: float) -> float:
    """Estimate SAP TaxTotal at 7% (SAP may round; actual read-back after commit)."""
    return round(price * _EXPECTED_RATE, 2)


def _build_plan(period_start_str: str, period_end_str: str, upload_dir: Path) -> dict:
    ps = date.fromisoformat(period_start_str)
    pe = date.fromisoformat(period_end_str)

    def _sap_date(offset: int) -> str:
        return min(ps + timedelta(days=offset), pe).isoformat()

    def _g1_entry(spec: dict) -> dict:
        sap_doc_date = _sap_date(spec["day_offset"])
        et = _et(spec["unit_price"])

        pdf_gst = spec["pdf_gst_amount"] if spec["pdf_gst_amount"] is not None else et
        pdf_rate = spec["pdf_gst_rate_label"] or "7%"
        pdf_reg = spec["supplier_gst_reg_str"] if spec["pdf_gst_reg"] else None

        if spec["pdf_date_delta"] > 0:
            pdf_date = (pe + timedelta(days=spec["pdf_date_delta"])).isoformat()
        else:
            pdf_date = sap_doc_date

        pdf_total = spec["unit_price"] + pdf_gst + spec["pdf_total_delta"]
        remarks = f"{SEED_MARKER}: group1_{spec['case_name']} | {spec['injected_issue']}"

        return {
            "group": 1,
            "case_name": spec["case_name"],
            "injected_issue": spec["injected_issue"],
            "_use_actual_tax": spec["pdf_gst_amount"] is None,
            "_pdf_total_delta": spec["pdf_total_delta"],
            "_expected_tax": et,
            "sap_doc": {
                "CardCode": _VENDOR,
                "DocDate": sap_doc_date,
                "DocDueDate": pe.isoformat(),
                "Remarks": remarks,
                "DocumentLines": [{
                    "ItemCode": _ITEM,
                    "ItemDescription": spec["item_desc"],
                    "Quantity": 1,
                    "UnitPrice": spec["unit_price"],
                    "VatGroup": "SI",
                }],
            },
            "pdf_spec": {
                "invoice_num": "INV-<TBD>",
                "date": pdf_date,
                "supplier_name": spec["supplier_name"],
                "supplier_address": spec["supplier_addr"],
                "supplier_gst_reg": pdf_reg,
                "customer_name": spec["customer_name"],
                "customer_address": spec["customer_addr"],
                "description": spec["item_desc"],
                "excl_gst": spec["unit_price"],
                "gst_rate_label": pdf_rate,
                "gst_amount": pdf_gst,
                "total": pdf_total,
            },
        }

    def _g2_entry(spec: dict) -> dict:
        sap_doc_date = _sap_date(spec["day_offset"])
        et = _et(spec["unit_price"])
        remarks = f"{SEED_MARKER}: group2_{spec['case_name']} | reasoning_bait"
        return {
            "group": 2,
            "case_name": spec["case_name"],
            "kb_category": spec["kb_category"],
            "kb_note": spec["kb_note"],
            "injected_issue": "reasoning_bait",
            "_use_actual_tax": True,
            "_pdf_total_delta": 0.0,
            "_expected_tax": et,
            "sap_doc": {
                "CardCode": _VENDOR,
                "DocDate": sap_doc_date,
                "DocDueDate": pe.isoformat(),
                "Remarks": remarks,
                "DocumentLines": [{
                    "ItemCode": _ITEM,
                    "ItemDescription": spec["item_desc"],
                    "Quantity": 1,
                    "UnitPrice": spec["unit_price"],
                    "VatGroup": "SI",
                }],
            },
            "pdf_spec": {
                "invoice_num": "INV-<TBD>",
                "date": sap_doc_date,
                "supplier_name": spec["supplier_name"],
                "supplier_address": spec["supplier_addr"],
                "supplier_gst_reg": spec["supplier_gst_reg_str"],
                "customer_name": spec["customer_name"],
                "customer_address": spec["customer_addr"],
                "description": spec["item_desc"],
                "excl_gst": spec["unit_price"],
                "gst_rate_label": "7%",
                "gst_amount": et,
                "total": spec["unit_price"] + et,
            },
        }

    return {
        "period_start": period_start_str,
        "period_end": period_end_str,
        "upload_dir": str(upload_dir),
        "entries": [_g1_entry(s) for s in _G1] + [_g2_entry(s) for s in _G2],
    }


# ---------------------------------------------------------------------------
# Dry-run printer
# ---------------------------------------------------------------------------

_W = 76


def _bar() -> str:
    return "─" * _W


def _print_dry_run(plan: dict) -> None:
    print()
    print("=" * _W)
    print("  SEED DRY RUN — no writes to SAP; no PDFs generated")
    print("=" * _W)
    print(f"  Period    : {plan['period_start']} → {plan['period_end']}")
    print(f"  Upload dir: {plan['upload_dir']}")
    print(f"  Marker    : {SEED_MARKER}")
    print()

    g1 = [e for e in plan["entries"] if e["group"] == 1]
    g2 = [e for e in plan["entries"] if e["group"] == 2]

    print(_bar())
    print(f"  GROUP 1 — Document Reconciliation Cases ({len(g1)} PurchaseInvoices)")
    print(_bar())
    for i, entry in enumerate(g1, 1):
        sd = entry["sap_doc"]
        ps = entry["pdf_spec"]
        ln = sd["DocumentLines"][0]
        et = entry["_expected_tax"]

        print(f"\n  [G1-{i}] {entry['case_name']}  |  injected_issue: {entry['injected_issue']}")
        print(f"    SAP POST /PurchaseInvoices:")
        print(f"      CardCode       : {sd['CardCode']}  ({_VENDOR} = Sea Corp, FederalTaxID=SK98467789)")
        print(f"      DocDate        : {sd['DocDate']}")
        print(f"      DocDueDate     : {sd['DocDueDate']}")
        print(f"      Remarks        : {sd['Remarks']}")
        print(f"      Line.ItemCode  : {ln['ItemCode']}")
        print(f"      Line.Desc      : {ln['ItemDescription']}")
        print(f"      Line.UnitPrice : {ln['UnitPrice']:.2f}")
        print(f"      Line.VatGroup  : {ln['VatGroup']}")
        print(f"      TaxTotal       : <SAP-computed, expected ~{et:.2f} at 7%>")

        gst_reg_disp = ps["supplier_gst_reg"] if ps["supplier_gst_reg"] else "[OMITTED — injected]"
        gst_disp = f"{ps['gst_amount']:.2f}"
        if entry["injected_issue"] in ("gst_amount_mismatch", "combined"):
            gst_disp += f"  ← INJECTED (SAP expected ~{et:.2f})"
        total_disp = f"{ps['total']:.2f}"
        if entry["_pdf_total_delta"]:
            correct = ps["excl_gst"] + ps["gst_amount"]
            total_disp += f"  ← INJECTED (correct={correct:.2f}, overstated by {entry['_pdf_total_delta']:.2f})"
        date_disp = ps["date"]
        if entry["injected_issue"] == "date_outside_period":
            date_disp += f"  ← INJECTED (SAP DocDate={sd['DocDate']}, outside period)"

        print(f"    PDF (INV-<ASSIGNED>.pdf):")
        print(f"      Supplier       : {ps['supplier_name']}")
        print(f"      GST Reg No     : {gst_reg_disp}")
        print(f"      Invoice Date   : {date_disp}")
        print(f"      Excl GST       : {ps['excl_gst']:.2f}")
        print(f"      GST ({ps['gst_rate_label']:>3s})       : {gst_disp}")
        print(f"      Total          : {total_disp}")

    print()
    print(_bar())
    print(f"  GROUP 2 — Reg 26/27 Reasoning Bait ({len(g2)} PurchaseInvoices)")
    print(_bar())
    for i, entry in enumerate(g2, 1):
        sd = entry["sap_doc"]
        ps = entry["pdf_spec"]
        ln = sd["DocumentLines"][0]
        et = entry["_expected_tax"]

        print(f"\n  [G2-{i}] {entry['case_name']}  |  KB: {entry['kb_category']}")
        print(f"    Trigger : {entry['kb_note']}")
        print(f"    SAP POST /PurchaseInvoices:")
        print(f"      CardCode       : {sd['CardCode']}")
        print(f"      DocDate        : {sd['DocDate']}")
        print(f"      Remarks        : {sd['Remarks']}")
        print(f"      Line.Desc      : {ln['ItemDescription']}")
        print(f"      Line.UnitPrice : {ln['UnitPrice']:.2f}")
        print(f"      Line.VatGroup  : SI")
        print(f"      TaxTotal       : <SAP-computed, expected ~{et:.2f} at 7%>")
        print(f"    PDF (INV-<ASSIGNED>.pdf): clean — GST reg={ps['supplier_gst_reg']}")

    total = len(g1) + len(g2)
    print()
    print(_bar())
    print(f"  TOTALS  Group1={len(g1)}  Group2={len(g2)}  Total={total}")
    print(f"  Seed marker: '{SEED_MARKER}'")
    print(_bar())
    print()
    print("  No writes performed. Re-run with --commit to execute.")
    print()


# ---------------------------------------------------------------------------
# PDF generation (reuses _render_invoice from generate_invoices.py)
# ---------------------------------------------------------------------------

def _load_gen_module():
    gen_path = _REPO_ROOT / "tests" / "fixtures" / "documents" / "generate_invoices.py"
    spec = importlib.util.spec_from_file_location("_fixture_gen", gen_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _generate_pdf(
    entry: dict,
    doc_num: int,
    actual_tax: float,
    upload_dir: Path,
    gen_mod,
    period_start: str,
    period_end: str,
) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas

    ps = dict(entry["pdf_spec"])
    ps["invoice_num"] = f"INV-{doc_num}"

    # For cases where PDF GST = SAP TaxTotal (not injected), use the actual value.
    if entry["_use_actual_tax"]:
        ps["gst_amount"] = actual_tax
        ps["total"] = ps["excl_gst"] + actual_tax + entry["_pdf_total_delta"]

    # Patch period display strings in the generator module before rendering.
    gen_mod.GST_PERIOD_START = period_start
    gen_mod.GST_PERIOD_END = period_end

    pdf_path = upload_dir / f"INV-{doc_num}.pdf"
    c = rl_canvas.Canvas(str(pdf_path), pagesize=A4, invariant=1)
    gen_mod._render_invoice(c, {"pdf": ps})
    c.showPage()
    c.save()
    return pdf_path


# ---------------------------------------------------------------------------
# SAP B1 session (write-capable — script only, never called by runtime)
# ---------------------------------------------------------------------------

class _B1Session:
    def __init__(self, cfg):
        base = cfg.service_layer_url.rstrip("/")
        self._base = base
        self.s = requests.Session()
        self.s.verify = cfg.ssl_verify
        self.s.headers.update({"Content-Type": "application/json",
                                "Accept": "application/json"})
        resp = self.s.post(f"{base}/Login", json={
            "CompanyDB": cfg.company_db,
            "UserName": cfg.username,
            "Password": cfg.password,
        }, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"Login failed ({resp.status_code}): {resp.text[:500]}")
        d = resp.json()
        print(f"  Logged in — session timeout: {d.get('SessionTimeout', '?')} min")

    def post(self, path: str, body: dict) -> dict:
        resp = self.s.post(f"{self._base}/{path}", json=body, timeout=30)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"POST /{path} ({resp.status_code}): {resp.text[:1000]}"
            )
        return resp.json()

    def get(self, path: str, params: dict | None = None) -> dict:
        resp = self.s.get(f"{self._base}/{path}", params=params, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(
                f"GET /{path} ({resp.status_code}): {resp.text[:500]}"
            )
        return resp.json()

    def logout(self) -> None:
        try:
            self.s.post(f"{self._base}/Logout", timeout=5)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Commit executor
# ---------------------------------------------------------------------------

def _commit(plan: dict, cfg, upload_dir: Path) -> None:
    upload_dir.mkdir(parents=True, exist_ok=True)
    gen_mod = _load_gen_module()

    print(f"\nConnecting to SAP B1 ...")
    b1 = _B1Session(cfg)

    manifest: dict = {}
    errors: list[dict] = []
    entries = plan["entries"]

    try:
        for idx, entry in enumerate(entries, 1):
            label = f"G{entry['group']}-{entry['case_name']}"
            issue = entry["injected_issue"]
            print(f"\n  [{idx}/{len(entries)}] {label} | {issue}")

            try:
                result = b1.post("PurchaseInvoices", entry["sap_doc"])
            except RuntimeError as exc:
                print(f"    FAILED: {exc}", file=sys.stderr)
                errors.append({"label": label, "error": str(exc)})
                continue

            doc_num = result["DocNum"]
            doc_entry = result["DocEntry"]

            # Read back actual TaxTotal (SAP-computed)
            detail = b1.get(f"PurchaseInvoices({doc_entry})")
            lines = detail.get("DocumentLines", [])
            actual_tax = sum(ln.get("TaxTotal", 0.0) for ln in lines)
            actual_lt = sum(ln.get("LineTotal", 0.0) for ln in lines)

            print(f"    DocNum={doc_num}  DocEntry={doc_entry}"
                  f"  LineTotal={actual_lt:.2f}  TaxTotal(SAP)={actual_tax:.2f}")

            pdf_path = _generate_pdf(
                entry, doc_num, actual_tax, upload_dir, gen_mod,
                plan["period_start"], plan["period_end"],
            )
            print(f"    PDF → {pdf_path}")

            manifest[str(doc_num)] = {
                "group": entry["group"],
                "case_or_category": entry.get("kb_category", entry["case_name"]),
                "injected_issue": issue,
                "listing_values": {
                    "line_total": actual_lt,
                    "tax_total": actual_tax,
                },
                "pdf_path": str(pdf_path),
                "doc_entry": doc_entry,
                "seed_marker": entry["sap_doc"]["Remarks"],
            }
    finally:
        b1.logout()
        print("\n  Logged out.")

    if errors:
        print(f"\n{len(errors)} document(s) failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e['label']}: {e['error']}", file=sys.stderr)

    manifest_path = Path(__file__).parent / "seed_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest → {manifest_path}")
    print(f"Done. {len(manifest)}/{len(entries)} document(s) created.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="seed_demo",
        description="Seed demo PurchaseInvoices + PDFs into SAP B1 SBODEMOSG.",
    )
    ap.add_argument(
        "--client", default="sbodemosg", metavar="CLIENT_ID",
        help="Client config stem in config/clients/ (default: sbodemosg)",
    )
    ap.add_argument(
        "--period", nargs=2, default=["2024-07-01", "2024-09-30"],
        metavar=("START", "END"),
        help="Period as two YYYY-MM-DD dates (default: 2024-07-01 2024-09-30)",
    )
    ap.add_argument(
        "--commit", action="store_true",
        help="Execute writes to SAP and generate PDFs (default: dry-run only)",
    )
    ap.add_argument(
        "--upload-dir",
        default=str(Path(__file__).parent / "seed_uploads"),
        metavar="DIR",
        help="Directory to write PDFs into (default: scripts/seed_uploads/)",
    )
    args = ap.parse_args()

    upload_dir = Path(args.upload_dir)
    plan = _build_plan(args.period[0], args.period[1], upload_dir)

    if not args.commit:
        _print_dry_run(plan)
        sys.exit(0)

    cfg = load_client_config(args.client, check_connectivity=False)
    print(f"Client : {cfg.client_name} ({cfg.client_id})")
    print(f"SAP B1 : {cfg.service_layer_url}  db={cfg.company_db}")
    _commit(plan, cfg, upload_dir)


if __name__ == "__main__":
    main()
