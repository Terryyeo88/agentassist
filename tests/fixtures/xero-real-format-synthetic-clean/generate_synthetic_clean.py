"""Generate the T2.24 synthetic-clean GST control-ledger fixture (zero-divergence oracle).

HAND-AUTHORED SYNTHETIC — this is NOT a captured Xero export. It mirrors the LAYOUT of the
real Account Transactions export (tests/fixtures/xero-real-format/) but carries a
deliberately-clean line set in which the two divergences of the real fixture are removed:

  * MJ-RAWGL (#14) is DROPPED  -> removes the 6.30 input-side divergence.
  * INV-2003 is treated as a genuine zero-rate (0 GST) -> no 820 posting -> removes the
    270.00 output-side divergence.

The declared boxes (declared_boxes.json) are then internally consistent with the ledger:
  output_tax (Box 6) = 900 (INV-2001) - 180 (CN-0002)                 = 720.00
  input_tax  (Box 7) = 180+320+135+225+225+72+108 (BILL-3001..3007)
                       + 6.30 (MJ-CODED #13)                          = 1271.30

Run: python tests/fixtures/xero-real-format-synthetic-clean/generate_synthetic_clean.py
Emits: AgentAssist_-_Account_Transactions_SYNTHETIC_CLEAN.xlsx (committed alongside).
Deterministic — re-running produces a byte-stable workbook.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from openpyxl import Workbook

_HEADER = ["Date", "Source", "Description", "Reference",
           "Debit", "Credit", "Running Balance", "Gross", "Tax"]

# (date, source, description, reference, debit, credit) — clean, zero-divergence set.
_LINES = [
    (_dt.datetime(2026, 4, 8),  "Receivable Invoice",     "Acme Pte Ltd",        "INV-2001",  0.0,   900.0),
    (_dt.datetime(2026, 4, 10), "Payable Invoice",        "GoodVendor Pte Ltd",  "BILL-3001", 180.0, 0.0),
    (_dt.datetime(2026, 4, 22), "Payable Invoice",        "OldRate Supplies",    "BILL-3002", 320.0, 0.0),
    (_dt.datetime(2026, 5, 6),  "Payable Invoice",        "NoReg Trading",       "BILL-3003", 135.0, 0.0),
    (_dt.datetime(2026, 5, 12), "Payable Invoice",        "DupSupplier Pte Ltd", "BILL-3004", 225.0, 0.0),
    (_dt.datetime(2026, 5, 19), "Payable Invoice",        "DupSupplier Pte Ltd", "BILL-3005", 225.0, 0.0),
    (_dt.datetime(2026, 5, 28), "Payable Invoice",        "Marina Fine Dining",  "BILL-3006", 72.0,  0.0),
    (_dt.datetime(2026, 5, 29), "Manual Journal",         "MJ-CODED test",       "#13",       6.3,   0.0),
    (_dt.datetime(2026, 6, 3),  "Payable Invoice",        "AutoCare SG Pte Ltd", "BILL-3007", 108.0, 0.0),
    (_dt.datetime(2026, 6, 29), "Receivable Credit Note", "Acme Pte Ltd",        "CN-0002",   180.0, 0.0),
]


def build() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "GST Transactions"
    # Title block (rows 1-4) mirrors the real export; the reader locates the header
    # STRUCTURALLY (markers Date/Debit/Credit), so exact offsets are not load-bearing.
    ws.append(["GST Transactions"])
    ws.append(["AgentAssist (SYNTHETIC CLEAN)"])
    ws.append(["For the period 1 April 2026 to 30 June 2026"])
    ws.append([])
    ws.append(_HEADER)
    ws.append([])
    ws.append(["GST"])
    ws.append(["Opening Balance", "", "", "", 0, 0, 0, 0, 0])
    for date, source, desc, ref, debit, credit in _LINES:
        ws.append([date, source, desc, ref, debit, credit, 0, 0, 0])
    # Poison totals: like the real export, these do NOT foot cleanly and MUST NOT be
    # trusted by the reader/check (all totals are recomputed from line-level debit/credit).
    ws.append(["Total GST", "", "", "", 0, 0, 0, 0, 0])
    ws.append(["Closing Balance", "", "", "", 287.6, 0, 0, 0, 0])
    ws.append([])
    ws.append(["Total", "", "", "", 0, 0, 0, 0, 0])
    return wb


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "AgentAssist_-_Account_Transactions_SYNTHETIC_CLEAN.xlsx"
    build().save(out)
    print(f"wrote {out}")
