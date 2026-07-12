"""T2.24 PR-2 — 'Transactions not included' reader + Signal-B GST-drop check (FAILING-FIRST).

Two contracts:

  1. feeders.xero_f5_reader.parse_not_included(source) -> list[dict]
     Reads the 'Transactions by box number' sheet's 'Transactions not included' section
     (header string EXACTLY "Transactions not included" in col A). Reuses the module's
     structural header locate and reads the Account column (index 1) the value-box loop
     ignores. Each row: {account, reference, description, tax_rate, gross, net, tax}.

  2. orchestrator.check_gst_ledger_recon.run_not_included_checks(rows, tolerance=0.01)
     Filters rows where account == "820 - GST" with a non-zero amount (|net| > tolerance),
     reading the amount from NET (the Tax column is 0). Emits one CANDIDATE finding per
     matching row (never a verdict, never a gate).

Ground truth (verified from the fixture): four not-included rows r78-81; the ONLY 820-GST
row is r80 (ref #14, MJ-RAWGL, net -6.3, tax 0) -> the single Signal-B finding, amount 6.30.

Real-FORMAT over SYNTHETIC content; NOT accuracy-validated (T2.11 unmoved).
"""
from __future__ import annotations

from pathlib import Path

from feeders.xero_f5_reader import parse_not_included
from orchestrator.check_gst_ledger_recon import run_not_included_checks

_FIX = Path(__file__).resolve().parent / "fixtures" / "xero-real-format"
_F5_WORKBOOK = _FIX / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

# Words that, asserted BARE, would make a finding a verdict rather than a candidate.
_VERDICT_WORDS = (" is wrong", " is incorrect", " is an error", " must be")


def test_parse_not_included_returns_four_rows_with_accounts():
    """Four not-included rows; every row carries a non-empty 'account'; the three appear."""
    rows = parse_not_included(_F5_WORKBOOK)
    assert len(rows) == 4, f"expected four not-included rows, got {rows}"
    for r in rows:
        assert r["account"].strip() != "", f"empty account in not-included row: {r}"
    accounts = {r["account"] for r in rows}
    assert {"820 - GST", "850 - Suspense", "485 - Subscriptions"} <= accounts


def test_run_not_included_checks_single_gst_drop_finding():
    """Exactly ONE finding: the 820-GST row #14, amount 6.30 (from net -6.3, NOT tax 0)."""
    findings = run_not_included_checks(parse_not_included(_F5_WORKBOOK))
    assert len(findings) == 1, f"expected exactly one GST-drop finding, got {findings}"
    f = findings[0]
    assert f["check_id"] == "GST_LEDGER_RECON"
    assert f["finding_type"] == "not_included_gst_drop"
    assert f["account"] == "820 - GST"
    assert f["reference"] == "#14"
    # Magnitude from NET (-6.3), rounded to 2dp — NOT the zero Tax column.
    assert f["amount"] == 6.30


def test_not_included_finding_is_a_candidate_not_a_verdict():
    """The finding is framed conditionally: candidate wording, no bare verdict assertions."""
    f = run_not_included_checks(parse_not_included(_F5_WORKBOOK))[0]
    desc = f["description"].lower()
    assert "internal-consistency" in desc
    assert "if a reviewer adjudicates" in desc
    assert "not a verdict" in desc
    # Names the offending journal so a reviewer can locate it.
    assert ("#14" in f["description"]) or ("mj-rawgl" in desc)
    # Never asserts a bare verdict.
    for w in _VERDICT_WORDS:
        assert w not in desc, f"asserted verdict word {w!r} in description: {f['description']}"
    assert f["recommendation"].startswith("Candidate for reviewer adjudication")
