"""
tests/test_check_listing.py — T2.10 acceptance + regression tests.

Covers three checks:
    1. SEQ_GAP  — invoice sequence gap detection
    2. DUP_CLAIM — duplicate input-tax claim detection
    3. ZP E2 extension — ZP added to both production and reference E2 code sets

AUDIT-NOT-PARTNER: each check has both a production test and a reference test,
plus an agreement test asserting the two implementations produce identical
output on the same input.

All tests are hermetic: no live SAP calls, no anthropic import.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_CUSTOM = _REPO_ROOT / "mcp-servers" / "custom"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_MCP_CUSTOM) not in sys.path:
    sys.path.insert(0, str(_MCP_CUSTOM))

from orchestrator.check_listing import detect_seq_gaps, detect_dup_claims
from scripts.check_listing_reference import ref_detect_seq_gaps, ref_detect_dup_claims


# =============================================================================
# Fixtures
# =============================================================================

# SEQ_GAP acceptance fixture:
#   Series 1:
#     DocNums 101, 103, 104 → gap at 102 (no cancelled doc) → FLAGGED
#     DocNums 105, (106 cancelled), 107 → gap at 106 explained by cancelled → NOT FLAGGED
#   Series 2:
#     DocNums 201, 202 → no gap (consecutive) → NOT FLAGGED
#   Cross-series: the gap "200-201" is between Series 1 and Series 2 → NOT a gap
SEQ_GAP_FIXTURE = [
    # Series 1 — genuine gap at 102
    {"DocNum": 101, "Series": 1, "Cancelled": "tNO"},
    {"DocNum": 103, "Series": 1, "Cancelled": "tNO"},
    {"DocNum": 104, "Series": 1, "Cancelled": "tNO"},
    # Series 1 — cancelled doc explains gap at 106
    {"DocNum": 105, "Series": 1, "Cancelled": "tNO"},
    {"DocNum": 106, "Series": 1, "Cancelled": "tYES"},
    {"DocNum": 107, "Series": 1, "Cancelled": "tNO"},
    # Series 2 — consecutive, no gap
    {"DocNum": 201, "Series": 2, "Cancelled": "tNO"},
    {"DocNum": 202, "Series": 2, "Cancelled": "tNO"},
]

# DUP_CLAIM acceptance fixture:
#   DocNums 501 + 502: same (CardCode, NumAtCard, DocTotal) → TRUE DUPLICATE → FLAGGED
#   DocNums 503 + 504: same amount+vendor, DIFFERENT NumAtCard → RECURRING CHARGE → NOT FLAGGED
#   DocNum 505: same NumAtCard+amount as 501/502 but DIFFERENT CardCode → NOT FLAGGED
DUP_CLAIM_FIXTURE = [
    # True duplicate: same key
    {"DocNum": 501, "CardCode": "V10000", "NumAtCard": "INV-ABC-001", "DocTotal": 1000.00},
    {"DocNum": 502, "CardCode": "V10000", "NumAtCard": "INV-ABC-001", "DocTotal": 1000.00},
    # Recurring charge: same amount + same vendor, different NumAtCard
    {"DocNum": 503, "CardCode": "V10000", "NumAtCard": "INV-MONTHLY-JUL", "DocTotal": 500.00},
    {"DocNum": 504, "CardCode": "V10000", "NumAtCard": "INV-MONTHLY-AUG", "DocTotal": 500.00},
    # Different vendor, same NumAtCard string — NOT a dup (different CardCode)
    {"DocNum": 505, "CardCode": "V20000", "NumAtCard": "INV-ABC-001", "DocTotal": 1000.00},
]


# =============================================================================
# SEQ_GAP — production implementation
# =============================================================================

class TestSeqGapProduction:

    def test_genuine_gap_flagged(self):
        # period=all_records: DocNum 102 absent from entire fixture → flagged
        findings = detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        gap_nums = [f["gap_doc_num"] for f in findings]
        assert 102 in gap_nums, "Gap at DocNum 102 in Series 1 must be flagged"

    def test_cancelled_doc_slot_not_flagged(self):
        # DocNum 106 is cancelled but present in all_records → slot occupied → not a gap
        findings = detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        gap_nums = [f["gap_doc_num"] for f in findings]
        assert 106 not in gap_nums, "DocNum 106 is in all_records (cancelled) — must NOT be flagged"

    def test_consecutive_series_no_gap(self):
        findings = detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        series_2_findings = [f for f in findings if f["series"] == 2]
        assert series_2_findings == [], "Series 2 has no gaps — no findings expected"

    def test_multi_series_no_cross_gap(self):
        # Series 1 max = 107, Series 2 min = 201.  The integers between them
        # belong to neither series and must not be flagged.
        findings = detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        cross_nums = [f["gap_doc_num"] for f in findings if f["gap_doc_num"] > 107]
        assert cross_nums == [], "No cross-series gap should be flagged"

    def test_only_genuine_gaps_surface(self):
        findings = detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        assert len(findings) == 1, (
            f"Expected exactly 1 SEQ_GAP finding (gap at 102); got {len(findings)}: "
            f"{[f['gap_doc_num'] for f in findings]}"
        )

    def test_finding_schema(self):
        findings = detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        assert findings
        f = findings[0]
        required_keys = {
            "check", "series", "gap_doc_num", "series_min", "series_max",
            "description", "basis", "note",
        }
        assert required_keys.issubset(f.keys()), f"Missing keys: {required_keys - f.keys()}"
        assert f["check"] == "SEQ_GAP"
        assert "§10.1(c)(i)" in f["basis"]

    def test_empty_input_returns_empty(self):
        assert detect_seq_gaps([], []) == []

    def test_single_doc_per_series_no_finding(self):
        records = [{"DocNum": 100, "Series": 1, "Cancelled": "tNO"}]
        assert detect_seq_gaps(records, records) == []

    def test_findings_never_halt_or_assert_verdict(self):
        findings = detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        for f in findings:
            desc = f.get("description", "")
            for forbidden in ("must", "is a violation", "non-compliant"):
                assert forbidden not in desc.lower(), (
                    f"SEQ_GAP finding must not assert verdict: {desc!r}"
                )

    def test_input_not_mutated(self):
        import copy
        original = copy.deepcopy(SEQ_GAP_FIXTURE)
        detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        assert SEQ_GAP_FIXTURE == original, "detect_seq_gaps must not mutate input"

    def test_multiple_gaps_in_same_series(self):
        records = [
            {"DocNum": 10, "Series": 1, "Cancelled": "tNO"},
            {"DocNum": 15, "Series": 1, "Cancelled": "tNO"},
        ]
        findings = detect_seq_gaps(records, records)
        gap_nums = sorted(f["gap_doc_num"] for f in findings)
        assert gap_nums == [11, 12, 13, 14], f"Expected gaps 11-14, got {gap_nums}"

    def test_gap_at_boundary_not_flagged(self):
        records = [{"DocNum": 50, "Series": 5, "Cancelled": "tNO"}]
        assert detect_seq_gaps(records, records) == []

    def test_cancelled_with_different_encoding_tyes(self):
        # DocNum 301 cancelled (tYES) is still in all_records → slot occupied → not a gap
        records = [
            {"DocNum": 300, "Series": 3, "Cancelled": "tNO"},
            {"DocNum": 301, "Series": 3, "Cancelled": "tYES"},
            {"DocNum": 302, "Series": 3, "Cancelled": "tNO"},
        ]
        findings = detect_seq_gaps(records, records)
        assert all(f["gap_doc_num"] != 301 for f in findings), (
            "DocNum 301 is in all_records (cancelled) — must NOT be flagged"
        )

    def test_other_period_doc_not_flagged(self):
        """DocNum present in another period (in all_records) must NOT be flagged."""
        period_records = [
            {"DocNum": 101, "Series": 1, "Cancelled": "tNO"},
            {"DocNum": 103, "Series": 1, "Cancelled": "tNO"},
        ]
        all_records = period_records + [
            {"DocNum": 102, "Series": 1, "Cancelled": "tNO"},  # issued in other period
        ]
        assert detect_seq_gaps(period_records, all_records) == [], (
            "DocNum 102 exists in all_records (other period) — must NOT be flagged"
        )

    def test_truly_absent_flagged(self):
        """DocNum absent from ALL company records IS a genuine gap."""
        period_records = [
            {"DocNum": 101, "Series": 1, "Cancelled": "tNO"},
            {"DocNum": 103, "Series": 1, "Cancelled": "tNO"},
        ]
        all_records = list(period_records)  # 102 absent from entire company history
        findings = detect_seq_gaps(period_records, all_records)
        gap_nums = [f["gap_doc_num"] for f in findings]
        assert 102 in gap_nums, "DocNum 102 absent from all company records — must be flagged"


# =============================================================================
# SEQ_GAP — reference implementation
# =============================================================================

class TestSeqGapReference:

    def test_genuine_gap_flagged(self):
        findings = ref_detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        gap_nums = [f["gap_doc_num"] for f in findings]
        assert 102 in gap_nums

    def test_cancelled_doc_slot_not_flagged(self):
        findings = ref_detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        gap_nums = [f["gap_doc_num"] for f in findings]
        assert 106 not in gap_nums

    def test_only_genuine_gaps_surface(self):
        findings = ref_detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        assert len(findings) == 1

    def test_empty_input(self):
        assert ref_detect_seq_gaps([], []) == []


# =============================================================================
# SEQ_GAP — production vs reference agreement (AUDIT-NOT-PARTNER)
# =============================================================================

class TestSeqGapAgreement:

    def test_agree_on_acceptance_fixture(self):
        prod = detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        ref = ref_detect_seq_gaps(SEQ_GAP_FIXTURE, SEQ_GAP_FIXTURE)
        prod_keys = sorted((f["series"], f["gap_doc_num"]) for f in prod)
        ref_keys = sorted((f["series"], f["gap_doc_num"]) for f in ref)
        assert prod_keys == ref_keys, (
            f"Production and reference SEQ_GAP disagree.\n"
            f"  Production: {prod_keys}\n"
            f"  Reference:  {ref_keys}"
        )

    def test_agree_on_empty_input(self):
        assert detect_seq_gaps([], []) == ref_detect_seq_gaps([], [])

    def test_agree_on_single_series_multiple_gaps(self):
        records = [
            {"DocNum": 10, "Series": 1, "Cancelled": "tNO"},
            {"DocNum": 14, "Series": 1, "Cancelled": "tNO"},
        ]
        prod = detect_seq_gaps(records, records)
        ref = ref_detect_seq_gaps(records, records)
        prod_nums = sorted(f["gap_doc_num"] for f in prod)
        ref_nums = sorted(f["gap_doc_num"] for f in ref)
        assert prod_nums == ref_nums

    def test_agree_on_all_cancelled_gaps(self):
        records = [
            {"DocNum": 20, "Series": 2, "Cancelled": "tNO"},
            {"DocNum": 21, "Series": 2, "Cancelled": "tYES"},
            {"DocNum": 22, "Series": 2, "Cancelled": "tNO"},
        ]
        prod = detect_seq_gaps(records, records)
        ref = ref_detect_seq_gaps(records, records)
        assert prod == [] and ref == []

    def test_agree_on_mixed_multi_series(self):
        records = SEQ_GAP_FIXTURE[:]
        prod = detect_seq_gaps(records, records)
        ref = ref_detect_seq_gaps(records, records)
        prod_keys = sorted((f["series"], f["gap_doc_num"]) for f in prod)
        ref_keys = sorted((f["series"], f["gap_doc_num"]) for f in ref)
        assert prod_keys == ref_keys

    def test_agree_on_other_period_exclusion(self):
        """Both implementations must NOT flag a DocNum present in another period."""
        period_records = [
            {"DocNum": 50, "Series": 4, "Cancelled": "tNO"},
            {"DocNum": 52, "Series": 4, "Cancelled": "tNO"},
        ]
        all_records = period_records + [
            {"DocNum": 51, "Series": 4, "Cancelled": "tNO"},
        ]
        prod = detect_seq_gaps(period_records, all_records)
        ref = ref_detect_seq_gaps(period_records, all_records)
        assert prod == [] and ref == [], (
            "DocNum 51 exists in all_records — neither implementation should flag it"
        )


# =============================================================================
# DUP_CLAIM — production implementation
# =============================================================================

class TestDupClaimProduction:

    def test_true_duplicate_flagged(self):
        findings = detect_dup_claims(DUP_CLAIM_FIXTURE)
        dup_pairs = [(f["doc_num"], f["duplicate_of"]) for f in findings]
        # DocNums 501 and 502 should form a dup pair
        assert (502, 501) in dup_pairs, (
            f"True duplicate (501, 502) not found in findings: {dup_pairs}"
        )

    def test_only_one_dup_pair_found(self):
        findings = detect_dup_claims(DUP_CLAIM_FIXTURE)
        assert len(findings) == 1, (
            f"Expected exactly 1 DUP_CLAIM finding; got {len(findings)}: "
            f"{[(f['doc_num'], f['duplicate_of']) for f in findings]}"
        )

    def test_recurring_charge_not_flagged(self):
        findings = detect_dup_claims(DUP_CLAIM_FIXTURE)
        flagged_nums = {f["doc_num"] for f in findings} | {f["duplicate_of"] for f in findings}
        assert 503 not in flagged_nums and 504 not in flagged_nums, (
            "Recurring charge (503, 504) with different NumAtCard must NOT be flagged"
        )

    def test_different_vendor_same_ref_not_flagged(self):
        findings = detect_dup_claims(DUP_CLAIM_FIXTURE)
        flagged_nums = {f["doc_num"] for f in findings}
        assert 505 not in flagged_nums, (
            "DocNum 505 has same ref as 501 but different CardCode — must NOT be flagged"
        )

    def test_finding_schema(self):
        findings = detect_dup_claims(DUP_CLAIM_FIXTURE)
        assert findings
        f = findings[0]
        required_keys = {
            "check", "doc_num", "duplicate_of", "card_code",
            "num_at_card", "doc_total", "description", "basis", "note",
        }
        assert required_keys.issubset(f.keys()), f"Missing keys: {required_keys - f.keys()}"
        assert f["check"] == "DUP_CLAIM"
        assert "§10.1(d)(i)" in f["basis"]

    def test_empty_input_returns_empty(self):
        assert detect_dup_claims([]) == []

    def test_blank_num_at_card_excluded(self):
        records = [
            {"DocNum": 600, "CardCode": "V10000", "NumAtCard": "", "DocTotal": 100.00},
            {"DocNum": 601, "CardCode": "V10000", "NumAtCard": "", "DocTotal": 100.00},
            {"DocNum": 602, "CardCode": "V10000", "NumAtCard": None, "DocTotal": 100.00},
        ]
        assert detect_dup_claims(records) == [], (
            "Blank/None NumAtCard should be excluded from duplicate detection"
        )

    def test_same_vendor_different_amounts_not_flagged(self):
        records = [
            {"DocNum": 700, "CardCode": "V30000", "NumAtCard": "REF-001", "DocTotal": 100.00},
            {"DocNum": 701, "CardCode": "V30000", "NumAtCard": "REF-001", "DocTotal": 200.00},
        ]
        assert detect_dup_claims(records) == [], (
            "Same vendor + same ref but different totals must NOT be flagged"
        )

    def test_findings_never_halt_or_assert_verdict(self):
        findings = detect_dup_claims(DUP_CLAIM_FIXTURE)
        for f in findings:
            desc = f.get("description", "")
            for forbidden in ("must", "is a violation", "non-compliant"):
                assert forbidden not in desc.lower()

    def test_input_not_mutated(self):
        import copy
        original = copy.deepcopy(DUP_CLAIM_FIXTURE)
        detect_dup_claims(DUP_CLAIM_FIXTURE)
        assert DUP_CLAIM_FIXTURE == original

    def test_three_duplicates_surface_two_findings(self):
        # Three entries with same key → 2 findings (502 dup of 501, 503 dup of 501)
        records = [
            {"DocNum": 801, "CardCode": "V50000", "NumAtCard": "INV-TRI", "DocTotal": 250.00},
            {"DocNum": 802, "CardCode": "V50000", "NumAtCard": "INV-TRI", "DocTotal": 250.00},
            {"DocNum": 803, "CardCode": "V50000", "NumAtCard": "INV-TRI", "DocTotal": 250.00},
        ]
        findings = detect_dup_claims(records)
        assert len(findings) == 2, f"Expected 2 findings for 3 duplicates; got {len(findings)}"


# =============================================================================
# DUP_CLAIM — reference implementation
# =============================================================================

class TestDupClaimReference:

    def test_true_duplicate_flagged(self):
        findings = ref_detect_dup_claims(DUP_CLAIM_FIXTURE)
        dup_pairs = [(f["doc_num"], f["duplicate_of"]) for f in findings]
        assert (502, 501) in dup_pairs

    def test_only_one_dup_pair(self):
        findings = ref_detect_dup_claims(DUP_CLAIM_FIXTURE)
        assert len(findings) == 1

    def test_recurring_not_flagged(self):
        findings = ref_detect_dup_claims(DUP_CLAIM_FIXTURE)
        flagged = {f["doc_num"] for f in findings} | {f["duplicate_of"] for f in findings}
        assert 503 not in flagged and 504 not in flagged

    def test_empty_input(self):
        assert ref_detect_dup_claims([]) == []


# =============================================================================
# DUP_CLAIM — production vs reference agreement (AUDIT-NOT-PARTNER)
# =============================================================================

class TestDupClaimAgreement:

    def test_agree_on_acceptance_fixture(self):
        prod = detect_dup_claims(DUP_CLAIM_FIXTURE)
        ref = ref_detect_dup_claims(DUP_CLAIM_FIXTURE)
        prod_keys = sorted((f["doc_num"], f["duplicate_of"]) for f in prod)
        ref_keys = sorted((f["doc_num"], f["duplicate_of"]) for f in ref)
        assert prod_keys == ref_keys, (
            f"Production and reference DUP_CLAIM disagree.\n"
            f"  Production: {prod_keys}\n"
            f"  Reference:  {ref_keys}"
        )

    def test_agree_on_empty_input(self):
        assert detect_dup_claims([]) == ref_detect_dup_claims([])

    def test_agree_on_blank_num_at_card(self):
        records = [
            {"DocNum": 600, "CardCode": "V10000", "NumAtCard": "", "DocTotal": 100.00},
            {"DocNum": 601, "CardCode": "V10000", "NumAtCard": "", "DocTotal": 100.00},
        ]
        assert detect_dup_claims(records) == ref_detect_dup_claims(records) == []

    def test_agree_on_three_duplicates(self):
        records = [
            {"DocNum": 900, "CardCode": "V40000", "NumAtCard": "REF-X", "DocTotal": 999.00},
            {"DocNum": 901, "CardCode": "V40000", "NumAtCard": "REF-X", "DocTotal": 999.00},
            {"DocNum": 902, "CardCode": "V40000", "NumAtCard": "REF-X", "DocTotal": 999.00},
        ]
        prod = detect_dup_claims(records)
        ref = ref_detect_dup_claims(records)
        prod_keys = sorted((f["doc_num"], f["duplicate_of"]) for f in prod)
        ref_keys = sorted((f["doc_num"], f["duplicate_of"]) for f in ref)
        assert prod_keys == ref_keys

    def test_agree_on_recurring_charges(self):
        records = [
            {"DocNum": 1001, "CardCode": "V99000", "NumAtCard": "MONTHLY-Q1", "DocTotal": 300.00},
            {"DocNum": 1002, "CardCode": "V99000", "NumAtCard": "MONTHLY-Q2", "DocTotal": 300.00},
            {"DocNum": 1003, "CardCode": "V99000", "NumAtCard": "MONTHLY-Q3", "DocTotal": 300.00},
        ]
        prod = detect_dup_claims(records)
        ref = ref_detect_dup_claims(records)
        assert prod == [] and ref == []


# =============================================================================
# ZP E2 extension — production path (sap_b1_server._classify_line)
# =============================================================================

class TestZpE2Production:

    def _make_zp_line(self, line_total: float, tax_total: float) -> tuple[dict, dict]:
        line = {
            "VatGroup": "ZP",
            "LineTotal": line_total,
            "TaxTotal": tax_total,
            "LineNum": 0,
        }
        doc = {
            "DocNum": 610,
            "DocDate": "2024-07-15",
            "DocCurrency": "SGD",
            "CardName": "Test Vendor",
            "CardCode": "V10000",
        }
        return line, doc

    def test_zp_with_tax_flagged_e2(self):
        import sap_b1_server
        line, doc = self._make_zp_line(1200.00, 84.00)
        issues = sap_b1_server._classify_line(line, doc, entity_type="purchase", expected_rate=0.07)
        error_codes = [i["error_code"] for i in issues]
        assert "E2" in error_codes, (
            f"ZP line with TaxTotal=84 must be flagged E2; got codes: {error_codes}"
        )

    def test_zp_doc610_taxed_84_flagged(self):
        # Acceptance: the specific DocNum 610 / TaxTotal=84 case per task spec
        import sap_b1_server
        line, doc = self._make_zp_line(1200.00, 84.00)
        issues = sap_b1_server._classify_line(line, doc, entity_type="purchase", expected_rate=0.07)
        e2_issues = [i for i in issues if i["error_code"] == "E2"]
        assert len(e2_issues) == 1, (
            f"Expected exactly 1 E2 issue for ZP+TaxTotal=84; got {len(e2_issues)}"
        )
        assert e2_issues[0]["doc_num"] == 610

    def test_zp_zero_tax_not_flagged(self):
        # ZP line with TaxTotal=0 is correct — must NOT be flagged E2
        import sap_b1_server
        line, doc = self._make_zp_line(1200.00, 0.00)
        issues = sap_b1_server._classify_line(line, doc, entity_type="purchase", expected_rate=0.07)
        error_codes = [i["error_code"] for i in issues]
        assert "E2" not in error_codes, (
            "ZP line with TaxTotal=0 must NOT be flagged E2"
        )

    def test_zp_in_e2_zero_rate_codes(self):
        import sap_b1_server
        assert "ZP" in sap_b1_server._E2_ZERO_RATE_CODES, (
            "ZP must be in _E2_ZERO_RATE_CODES"
        )

    def test_existing_e2_codes_still_present(self):
        import sap_b1_server
        expected = {"ZR", "OS", "ES33", "ESN33", "BL", "NR"}
        missing = expected - sap_b1_server._E2_ZERO_RATE_CODES
        assert not missing, f"Pre-existing E2 codes removed: {missing}"

    def test_zr_still_flagged_e2(self):
        import sap_b1_server
        line = {"VatGroup": "ZR", "LineTotal": 1000.00, "TaxTotal": 70.00, "LineNum": 0}
        doc = {"DocNum": 900, "DocDate": "2024-07-15", "DocCurrency": "SGD",
               "CardName": "Test", "CardCode": "C10000"}
        issues = sap_b1_server._classify_line(line, doc, entity_type="sales", expected_rate=0.07)
        assert any(i["error_code"] == "E2" for i in issues), "ZR+TaxTotal>0 must still flag E2"

    def test_nr_still_flagged_e2(self):
        # DocNum 611 fixture: NR with TaxTotal=45.00 — existing E2 case must not regress
        import sap_b1_server
        line = {"VatGroup": "NR", "LineTotal": 500.00, "TaxTotal": 45.00, "LineNum": 0}
        doc = {"DocNum": 611, "DocDate": "2024-09-15", "DocCurrency": "SGD",
               "CardName": "Test Vendor", "CardCode": "V10000"}
        issues = sap_b1_server._classify_line(line, doc, entity_type="purchase", expected_rate=0.07)
        assert any(i["error_code"] == "E2" for i in issues), "NR+TaxTotal>0 must still flag E2"

    def test_si_with_tax_not_flagged_e2(self):
        # SI is standard-rated — tax on SI is correct; must NOT be flagged E2
        import sap_b1_server
        line = {"VatGroup": "SI", "LineTotal": 1000.00, "TaxTotal": 70.00, "LineNum": 0}
        doc = {"DocNum": 800, "DocDate": "2024-07-15", "DocCurrency": "SGD",
               "CardName": "Test Vendor", "CardCode": "V20000"}
        issues = sap_b1_server._classify_line(line, doc, entity_type="purchase", expected_rate=0.07)
        assert not any(i["error_code"] == "E2" for i in issues), (
            "SI+TaxTotal>0 must NOT be flagged E2 (SI is standard-rated)"
        )


# =============================================================================
# ZP E2 extension — reference implementation (run_baseline_tests.py)
# =============================================================================

class TestZpE2Reference:

    def test_zp_in_reference_e2_codes(self):
        import scripts.run_baseline_tests as rbt
        assert "ZP" in rbt.E2_ZERO_RATE_CODES, (
            "ZP must be in E2_ZERO_RATE_CODES in run_baseline_tests.py"
        )

    def test_existing_e2_codes_still_in_reference(self):
        import scripts.run_baseline_tests as rbt
        expected = {"ZR", "OS", "ES33", "ESN33", "BL", "NR"}
        missing = expected - rbt.E2_ZERO_RATE_CODES
        assert not missing, f"Pre-existing E2 codes removed from reference: {missing}"

    def test_reference_detects_zp_tax_via_code_membership(self):
        # Verify the check logic: if a line's VatGroup is in E2_ZERO_RATE_CODES
        # and TaxTotal > 0.01, it should be flagged E2 by the reference logic.
        import scripts.run_baseline_tests as rbt
        vg = "ZP"
        tax_total = 84.00
        flagged = vg in rbt.E2_ZERO_RATE_CODES and tax_total > 0.01
        assert flagged, (
            "Reference logic: ZP with TaxTotal=84 should be detected as E2"
        )

    def test_reference_does_not_flag_zp_zero_tax(self):
        import scripts.run_baseline_tests as rbt
        vg = "ZP"
        tax_total = 0.00
        flagged = vg in rbt.E2_ZERO_RATE_CODES and tax_total > 0.01
        assert not flagged, (
            "Reference logic: ZP with TaxTotal=0 must NOT be flagged E2"
        )


# =============================================================================
# ZP E2 — production vs reference agreement (AUDIT-NOT-PARTNER)
# =============================================================================

class TestZpE2Agreement:

    def test_both_contain_zp(self):
        import sap_b1_server
        import scripts.run_baseline_tests as rbt
        assert "ZP" in sap_b1_server._E2_ZERO_RATE_CODES
        assert "ZP" in rbt.E2_ZERO_RATE_CODES

    def test_code_sets_agree_on_e2_membership(self):
        """Production and reference E2 code sets must contain the same codes."""
        import sap_b1_server
        import scripts.run_baseline_tests as rbt
        prod_codes = sap_b1_server._E2_ZERO_RATE_CODES
        ref_codes = rbt.E2_ZERO_RATE_CODES
        assert prod_codes == ref_codes, (
            f"Production and reference E2 code sets diverge.\n"
            f"  Production only: {prod_codes - ref_codes}\n"
            f"  Reference only:  {ref_codes - prod_codes}"
        )

    def test_both_flag_zp_84(self):
        # Production: _classify_line with ZP+84
        import sap_b1_server
        line = {"VatGroup": "ZP", "LineTotal": 1200.00, "TaxTotal": 84.00, "LineNum": 0}
        doc = {"DocNum": 610, "DocDate": "2024-07-15", "DocCurrency": "SGD",
               "CardName": "Test Vendor", "CardCode": "V10000"}
        prod_issues = sap_b1_server._classify_line(line, doc, entity_type="purchase", expected_rate=0.07)
        prod_e2 = any(i["error_code"] == "E2" for i in prod_issues)

        # Reference: code-set membership check (same logic used by run_test_3)
        import scripts.run_baseline_tests as rbt
        ref_e2 = "ZP" in rbt.E2_ZERO_RATE_CODES and 84.00 > 0.01

        assert prod_e2 and ref_e2, (
            f"ZP+TaxTotal=84 must be flagged E2 by both implementations. "
            f"Production flagged: {prod_e2}, Reference flagged: {ref_e2}"
        )

    def test_both_skip_zp_zero_tax(self):
        import sap_b1_server
        import scripts.run_baseline_tests as rbt
        line = {"VatGroup": "ZP", "LineTotal": 1200.00, "TaxTotal": 0.00, "LineNum": 0}
        doc = {"DocNum": 610, "DocDate": "2024-07-15", "DocCurrency": "SGD",
               "CardName": "Test Vendor", "CardCode": "V10000"}
        prod_issues = sap_b1_server._classify_line(line, doc, entity_type="purchase", expected_rate=0.07)
        prod_e2 = any(i["error_code"] == "E2" for i in prod_issues)
        ref_e2 = "ZP" in rbt.E2_ZERO_RATE_CODES and 0.00 > 0.01
        assert not prod_e2 and not ref_e2
