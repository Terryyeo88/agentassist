#!/usr/bin/env python3
"""
Phase 1 field verification probe — READ-ONLY.
Verifies T2.10 SAP field assumptions against live SBODEMOSG.
No POST/PATCH/PUT/DELETE. Only GET / OData $select queries.
Output: prints field findings; never prints credentials.
"""
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    # Worktree shares repo with main checkout — try both locations
    _env_candidates = [
        _REPO_ROOT / ".env",
        _REPO_ROOT.parent / "sap-b1-ai-agent" / ".env",
    ]
    for _env_path in _env_candidates:
        if _env_path.exists():
            load_dotenv(_env_path)
            break
except ImportError:
    pass

from config.loader import load_client_config
import httpx

PERIOD_START = "2024-07-01"
PERIOD_END   = "2024-09-30"
DATE_FILTER  = f"DocDate ge '{PERIOD_START}' and DocDate le '{PERIOD_END}'"


def login(cfg) -> httpx.Client:
    http = httpx.Client(verify=cfg.ssl_verify, timeout=30.0)
    resp = http.post(f"{cfg.service_layer_url}/Login", json={
        "CompanyDB": cfg.company_db,
        "UserName": cfg.username,
        "Password": cfg.password,
    })
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed ({resp.status_code})")
    http.cookies.update(resp.cookies)
    return http


def get(http, base_url, endpoint, params=None):
    r = http.get(f"{base_url}{endpoint}", params=params or {})
    r.raise_for_status()
    return r.json()


def redact_row(row: dict, fields_to_show: list[str]) -> dict:
    """Return only the requested fields — never show credentials."""
    return {k: row.get(k) for k in fields_to_show}


def main():
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    BASE = cfg.service_layer_url

    print("=" * 70)
    print("T2.10 Phase 1 — SAP Field Verification (READ-ONLY)")
    print(f"Period: {PERIOD_START} to {PERIOD_END}")
    print("=" * 70)

    print("\nConnecting to SAP...")
    http = login(cfg)
    print("  Connected.")

    results = {}

    # ── (a) Series on Invoices ──────────────────────────────────────────────
    print("\n--- (a) Series field on Invoices ---")
    resp = get(http, BASE, "/Invoices", {
        "$filter": DATE_FILTER,
        "$select": "DocNum,Series",
        "$top": 20,
    })
    inv_rows = resp.get("value", [])
    sample_inv = [redact_row(r, ["DocNum", "Series"]) for r in inv_rows[:5]]
    series_vals_sales = sorted(set(r.get("Series") for r in inv_rows if r.get("Series") is not None))
    print(f"  Invoices fetched: {len(inv_rows)} (top 20)")
    print(f"  Sample rows: {json.dumps(sample_inv, indent=4)}")
    print(f"  Distinct Series values in sales invoices: {series_vals_sales}")
    results["series_on_invoices"] = {
        "rows_fetched": len(inv_rows),
        "sample": sample_inv,
        "distinct_series": series_vals_sales,
        "field_present": any("Series" in r for r in inv_rows),
        "value_type": type(inv_rows[0].get("Series")).__name__ if inv_rows else "N/A",
    }

    # ── (a) Series on PurchaseInvoices ──────────────────────────────────────
    print("\n--- (a) Series field on PurchaseInvoices ---")
    resp = get(http, BASE, "/PurchaseInvoices", {
        "$filter": DATE_FILTER,
        "$select": "DocNum,Series",
        "$top": 20,
    })
    pi_rows = resp.get("value", [])
    sample_pi = [redact_row(r, ["DocNum", "Series"]) for r in pi_rows[:5]]
    series_vals_purch = sorted(set(r.get("Series") for r in pi_rows if r.get("Series") is not None))
    print(f"  PurchaseInvoices fetched: {len(pi_rows)} (top 20)")
    print(f"  Sample rows: {json.dumps(sample_pi, indent=4)}")
    print(f"  Distinct Series values in purchase invoices: {series_vals_purch}")
    results["series_on_purchase_invoices"] = {
        "rows_fetched": len(pi_rows),
        "sample": sample_pi,
        "distinct_series": series_vals_purch,
        "field_present": any("Series" in r for r in pi_rows),
        "value_type": type(pi_rows[0].get("Series")).__name__ if pi_rows else "N/A",
    }

    # ── (b) Cancelled field on Invoices ────────────────────────────────────
    print("\n--- (b) Cancelled field on Invoices ---")
    resp = get(http, BASE, "/Invoices", {
        "$filter": DATE_FILTER,
        "$select": "DocNum,Cancelled",
        "$top": 20,
    })
    inv_c_rows = resp.get("value", [])
    sample_c = [redact_row(r, ["DocNum", "Cancelled"]) for r in inv_c_rows[:5]]
    cancelled_vals = set(r.get("Cancelled") for r in inv_c_rows)
    print(f"  Sample rows: {json.dumps(sample_c, indent=4)}")
    print(f"  All Cancelled values seen: {sorted(str(v) for v in cancelled_vals)}")
    # Look for any tYES in the full period
    tyes_docs = [r["DocNum"] for r in inv_c_rows if r.get("Cancelled") == "tYES"]
    print(f"  Docs with Cancelled='tYES' in sample: {tyes_docs}")
    results["cancelled_on_invoices"] = {
        "field_present": any("Cancelled" in r for r in inv_c_rows),
        "distinct_values_in_sample": sorted(str(v) for v in cancelled_vals),
        "tyes_docs_in_sample": tyes_docs,
        "value_type": type(inv_c_rows[0].get("Cancelled")).__name__ if inv_c_rows else "N/A",
    }

    # Try to find any cancelled doc in wider search (no period filter)
    print("  Scanning for any Cancelled='tYES' invoice (no period filter, top 50)...")
    resp_all = get(http, BASE, "/Invoices", {
        "$filter": "Cancelled eq 'tYES'",
        "$select": "DocNum,DocDate,Cancelled",
        "$top": 5,
    })
    any_cancelled = resp_all.get("value", [])
    print(f"  Invoices with Cancelled='tYES' (any period): {[r['DocNum'] for r in any_cancelled]}")
    results["any_cancelled_invoices"] = {
        "found": len(any_cancelled),
        "samples": [redact_row(r, ["DocNum", "DocDate", "Cancelled"]) for r in any_cancelled],
    }

    # ── (c) NumAtCard on PurchaseInvoices ───────────────────────────────────
    print("\n--- (c) NumAtCard on PurchaseInvoices ---")
    resp = get(http, BASE, "/PurchaseInvoices", {
        "$filter": DATE_FILTER,
        "$select": "DocNum,CardCode,NumAtCard,DocTotal",
        "$top": 50,
    })
    pi_full = resp.get("value", [])
    sample_num = [redact_row(r, ["DocNum", "NumAtCard", "DocTotal"]) for r in pi_full[:8]]
    populated = [r for r in pi_full if (r.get("NumAtCard") or "").strip()]
    empty_or_null = [r for r in pi_full if not (r.get("NumAtCard") or "").strip()]
    print(f"  PurchaseInvoices in period: {len(pi_full)}")
    print(f"  NumAtCard POPULATED: {len(populated)}")
    print(f"  NumAtCard EMPTY/NULL: {len(empty_or_null)}")
    print(f"  Sample rows: {json.dumps(sample_num, indent=4)}")
    results["num_at_card"] = {
        "total_pi_in_period": len(pi_full),
        "populated": len(populated),
        "empty_or_null": len(empty_or_null),
        "population_rate_pct": round(100 * len(populated) / len(pi_full), 1) if pi_full else 0,
        "sample": sample_num,
    }

    # ── (c-ext) NumAtCard across ALL periods (not just Q3 2024) ────────────
    print("\n--- (c-ext) NumAtCard across ALL purchase invoices (no period filter, top 100) ---")
    resp_all_pi = get(http, BASE, "/PurchaseInvoices", {
        "$select": "DocNum,NumAtCard,DocTotal",
        "$top": 100,
    })
    all_pi = resp_all_pi.get("value", [])
    pop_all = [r for r in all_pi if (r.get("NumAtCard") or "").strip()]
    empty_all = [r for r in all_pi if not (r.get("NumAtCard") or "").strip()]
    print(f"  All PurchaseInvoices sampled (top 100): {len(all_pi)}")
    print(f"  NumAtCard POPULATED: {len(pop_all)}")
    print(f"  NumAtCard EMPTY/NULL: {len(empty_all)}")
    if pop_all:
        print(f"  Populated examples: {json.dumps([redact_row(r, ['DocNum', 'NumAtCard', 'DocTotal']) for r in pop_all[:5]], indent=4)}")
    results["num_at_card_all_periods"] = {
        "sampled": len(all_pi),
        "populated": len(pop_all),
        "empty_or_null": len(empty_all),
        "population_rate_pct": round(100 * len(pop_all) / len(all_pi), 1) if all_pi else 0,
        "populated_examples": [redact_row(r, ["DocNum", "NumAtCard"]) for r in pop_all[:5]],
    }

    # ── (d) DocTotal — tax-inclusive confirmation ───────────────────────────
    print("\n--- (d) DocTotal — tax-inclusive check ---")
    # Probe a single known-doc to check VatSum field name
    resp_one = get(http, BASE, "/PurchaseInvoices(591)", {
        "$select": "DocNum,DocTotal",
    })
    doc_one = resp_one if isinstance(resp_one, dict) else {}
    print(f"  PurchaseInvoice 591 DocTotal: {doc_one.get('DocTotal')}")
    # Fetch DocLines to compute net+tax manually
    resp_lines = get(http, BASE, "/PurchaseInvoices(591)", {
        "$select": "DocNum,DocTotal,DocumentLines",
    })
    lines_data = (resp_lines.get("DocumentLines") or []) if isinstance(resp_lines, dict) else []
    net_total = sum(float(l.get("LineTotal") or 0) for l in lines_data)
    tax_total = sum(float(l.get("TaxTotal") or 0) for l in lines_data)
    doc_total = float(doc_one.get("DocTotal") or 0)
    print(f"  PurchaseInvoice 591: DocTotal={doc_total}  sum(LineTotal)={net_total}  sum(TaxTotal)={tax_total}  net+tax={net_total+tax_total}")
    doctotal_samples = [{
        "DocNum": 591,
        "DocTotal": doc_total,
        "sum_LineTotal": net_total,
        "sum_TaxTotal": tax_total,
        "net_plus_tax": net_total + tax_total,
        "DocTotal_matches_net_plus_tax": abs(doc_total - (net_total + tax_total)) < 0.02,
    }]
    # Also check the ZP doc (DocNum 610) to confirm DocTotal
    resp_610 = get(http, BASE, "/PurchaseInvoices(610)", {
        "$select": "DocNum,DocTotal,DocumentLines",
    })
    lines_610 = (resp_610.get("DocumentLines") or []) if isinstance(resp_610, dict) else []
    net_610 = sum(float(l.get("LineTotal") or 0) for l in lines_610)
    tax_610 = sum(float(l.get("TaxTotal") or 0) for l in lines_610)
    doc_610 = float(resp_610.get("DocTotal") or 0) if isinstance(resp_610, dict) else 0
    print(f"  PurchaseInvoice 610 (ZP): DocTotal={doc_610}  sum(LineTotal)={net_610}  sum(TaxTotal)={tax_610}  net+tax={net_610+tax_610}")
    doctotal_samples.append({
        "DocNum": 610,
        "DocTotal": doc_610,
        "sum_LineTotal": net_610,
        "sum_TaxTotal": tax_610,
        "net_plus_tax": net_610 + tax_610,
        "DocTotal_matches_net_plus_tax": abs(doc_610 - (net_610 + tax_610)) < 0.02,
    })
    results["doctotal"] = {
        "sample": doctotal_samples,
        "conclusion": "DocTotal is tax-inclusive" if all(s["DocTotal_matches_net_plus_tax"] for s in doctotal_samples) else "DISCREPANCY — DocTotal may NOT be tax-inclusive",
    }

    print("\n" + "=" * 70)
    print("RESULTS JSON:")
    print(json.dumps(results, indent=2))
    print("=" * 70)

    return results


if __name__ == "__main__":
    main()
