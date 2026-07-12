"""T2.24 — GST control-ledger <-> F5-return internal-consistency reconciliation.

Failing-test-first for the PURE check (orchestrator/check_gst_ledger_recon.py) plus the
side-input loader (feeders/xero_ledger_reader.py), driven over the committed real-FORMAT
fixtures (tests/fixtures/xero-real-format/) and a hand-authored synthetic-clean oracle
(tests/fixtures/xero-real-format-synthetic-clean/).

WHAT THIS CHECK IS: an internal-consistency reconciliation between two derivation paths over
the SAME source — GST posted to the Xero 820 control account (Account Transactions export)
vs GST declared in the F5 return. A divergence is a CANDIDATE FOR REVIEW, never a verdict.
It is BLIND to a tax code that is wrong but internally consistent across ledger and box.

Real-FORMAT over SYNTHETIC content; NOT accuracy-validated (T2.11 unmoved).
"""
from __future__ import annotations

import json
from pathlib import Path

from feeders.xero_ledger_reader import load_gst_ledger
from orchestrator.check_gst_ledger_recon import run_ledger_recon_checks

_FIX = Path(__file__).resolve().parent / "fixtures" / "xero-real-format"
_ACCOUNT_TXNS = _FIX / "AgentAssist_-_Account_Transactions.xlsx"
_F5_WORKBOOK = _FIX / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

_CLEAN = Path(__file__).resolve().parent / "fixtures" / "xero-real-format-synthetic-clean"
_CLEAN_TXNS = _CLEAN / "AgentAssist_-_Account_Transactions_SYNTHETIC_CLEAN.xlsx"
_CLEAN_BOXES = _CLEAN / "declared_boxes.json"

# Words that, asserted BARE, would make a finding a verdict rather than a candidate.
_VERDICT_WORDS = (" is wrong", " is incorrect", " is an error", " must be", " you must")


def _declared_boxes_from_return(path: Path) -> dict:
    """Read Box 6 (output tax) / Box 7 (input tax) off the F5 workbook's 'Return' sheet.

    TEST SCAFFOLDING ONLY — not a product parser (parse_declared_return is a deferred slice).
    The Return sheet lays out one box per row: col A = 'Box N', col C = value.
    """
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Return"]
        by_box: dict[str, float] = {}
        for row in ws.iter_rows(values_only=True):
            label = str(row[0] or "").strip()
            if label in ("Box 6", "Box 7") and row[2] is not None:
                by_box[label] = float(row[2])
    finally:
        wb.close()
    return {"output_tax": by_box["Box 6"], "input_tax": by_box["Box 7"]}


def _by_side(findings: list) -> dict:
    return {f["side"]: f for f in findings}


# --------------------------------------------------------------------------- #
# Positive: two internal-consistency divergences, surfaced as candidates.
# --------------------------------------------------------------------------- #

def test_positive_two_divergences_are_candidates_not_verdicts():
    lines = load_gst_ledger(_ACCOUNT_TXNS)
    declared = _declared_boxes_from_return(_F5_WORKBOOK)  # Box 6 = 720.00, Box 7 = 1271.30

    findings = run_ledger_recon_checks(lines, declared)
    assert len(findings) == 2, f"expected exactly two divergences, got {findings}"

    by_side = _by_side(findings)
    assert set(by_side) == {"output", "input"}

    # Input side: MJ-RAWGL (#14) drops from the F5 but sits in the 820 ledger -> +6.30.
    inp = by_side["input"]
    assert inp["divergence"] == 6.30
    assert inp["ledger_gst"] == 1277.60   # INCLUDES MJ-CODED + MJ-RAWGL + INV-2003? no (input side)
    assert inp["declared_gst"] == 1271.30

    # Output side: INV-2003's 270 GST is posted to 820 but routed to Box 2 (zero-rated),
    # absent from declared Box 6 -> +270.00.
    out = by_side["output"]
    assert out["divergence"] == 270.00
    assert out["ledger_gst"] == 990.00    # 900 (INV-2001) + 270 (INV-2003) - 180 (CN-0002)
    assert out["declared_gst"] == 720.00

    # Every finding is a CANDIDATE, never a verdict.
    for f in findings:
        desc = f["description"].lower()
        assert "internal-consistency" in desc
        assert "if a reviewer adjudicates" in desc
        assert "not a verdict" in desc
        for w in _VERDICT_WORDS:
            assert w not in desc, f"asserted verdict word {w!r} in description: {f['description']}"
        assert f["check_id"] == "GST_LEDGER_RECON"
        assert f["finding_type"] == "ledger_recon_divergence"
        assert f["recommendation"].startswith("Candidate for reviewer adjudication")


def test_ledger_totals_guard_source_classification():
    """The 990.00 / 1277.60 totals pin the Source-based recompute (not a column sum)."""
    lines = load_gst_ledger(_ACCOUNT_TXNS)
    declared = _declared_boxes_from_return(_F5_WORKBOOK)
    by_side = _by_side(run_ledger_recon_checks(lines, declared))
    # INV-2003's 270 credit is INCLUDED on output; CN-0002's 180 debit is an output
    # REVERSAL (-180), NOT an input line. Both MJs are Manual-Journal debits -> input.
    assert by_side["output"]["ledger_gst"] == 990.00
    assert by_side["input"]["ledger_gst"] == 1277.60


# --------------------------------------------------------------------------- #
# MJ-CODED (#13) reconciles; only MJ-RAWGL (#14) diverges — the two 6.30s disambiguate.
# --------------------------------------------------------------------------- #

def test_mjcoded_reconciles_no_finding():
    lines = load_gst_ledger(_ACCOUNT_TXNS)
    declared = _declared_boxes_from_return(_F5_WORKBOOK)
    inp = _by_side(run_ledger_recon_checks(lines, declared))["input"]
    # Both #13 and #14 are 6.30 Manual-Journal debits in the 820 ledger. #13 (coded) is
    # ALSO in declared Box 7; #14 (raw-GL) is NOT. If the check failed to disambiguate it
    # would read 12.60; the 6.30 proves #13 reconciled and only #14 diverges.
    assert inp["divergence"] == 6.30
    assert inp["divergence"] != 12.60


# --------------------------------------------------------------------------- #
# In-period credit note CN-0002 reconciles on the OUTPUT side (not flagged, not input).
# --------------------------------------------------------------------------- #

def test_credit_note_reconciles_not_flagged():
    lines = load_gst_ledger(_ACCOUNT_TXNS)
    declared = _declared_boxes_from_return(_F5_WORKBOOK)
    by_side = _by_side(run_ledger_recon_checks(lines, declared))
    # CN-0002 nets -180 on OUTPUT (990 = 900 + 270 - 180). Misclassifying it as input
    # would shift input by 180 (1277.60 -> 1097.60) and break the guard below.
    assert by_side["output"]["ledger_gst"] == 990.00
    assert by_side["input"]["ledger_gst"] == 1277.60
    # There is no independent CN finding — it folds into the output total.
    assert {f["side"] for f in run_ledger_recon_checks(lines, declared)} == {"output", "input"}


# --------------------------------------------------------------------------- #
# Blocked-input bills (Reg 26/27) reconcile on THIS check — a separate concern.
# --------------------------------------------------------------------------- #

def test_blocked_input_bills_reconcile_on_this_check():
    # BILL-3006 (Marina, 72) and BILL-3007 (AutoCare, 108) are ordinary Payable-Invoice
    # input postings that reconcile on the control-ledger check and produce NO T2.24
    # finding of their own. Blocked-input adjudication (Reg 26/27) is a separate
    # reasoning-layer concern (T-reg2627), NOT asserted clean here.
    lines = load_gst_ledger(_ACCOUNT_TXNS)
    declared = _declared_boxes_from_return(_F5_WORKBOOK)
    findings = run_ledger_recon_checks(lines, declared)
    # The only findings are the two structural divergences (input 6.30 / output 270.00);
    # 72 and 108 are silently INSIDE the reconciled input total, not called out.
    assert {f["divergence"] for f in findings} == {6.30, 270.00}
    for f in findings:
        assert "BILL-3006" not in f["description"]
        assert "BILL-3007" not in f["description"]


# --------------------------------------------------------------------------- #
# Clean synthetic oracle: zero divergences -> zero findings (no false positives).
# --------------------------------------------------------------------------- #

def test_synthetic_clean_zero_findings():
    lines = load_gst_ledger(_CLEAN_TXNS)
    declared = json.loads(_CLEAN_BOXES.read_text(encoding="utf-8"))
    declared = {"output_tax": declared["output_tax"], "input_tax": declared["input_tax"]}
    assert run_ledger_recon_checks(lines, declared) == []


# --------------------------------------------------------------------------- #
# Tolerance boundary — 0.01 no finding; 0.02 finding (NON-REGULATORY TUNING PARAM).
# --------------------------------------------------------------------------- #

def test_tolerance_boundary():
    # One Payable-Invoice input line vs a declared box 0.01 / 0.02 below it.
    def _lines(debit):
        return [{"date": "2026-04-10", "source": "Payable Invoice",
                 "description": "x", "reference": "BILL-X",
                 "debit": debit, "credit": 0.0}]

    exact_cent = run_ledger_recon_checks(
        _lines(100.01), {"output_tax": 0.0, "input_tax": 100.00})
    assert exact_cent == [], "a 0.01 divergence is within tolerance (no finding)"

    two_cent = run_ledger_recon_checks(
        _lines(100.02), {"output_tax": 0.0, "input_tax": 100.00})
    assert len(two_cent) == 1 and two_cent[0]["side"] == "input"
    assert two_cent[0]["divergence"] == 0.02
