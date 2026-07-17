"""
tests/test_check_document_dup_window.py — FAILING-FIRST unit tests for the NEW
windowed duplicate-purchase surfacer (DUP_WINDOW).

The module under test, ``orchestrator/check_document_dup_window.py``, does NOT yet
exist: every test in this file is RED at collection time with an ImportError on
``detect_window_dups``. That is the RIGHT REASON — the tests pin the settled design
BEFORE the implementation, so a build that deviates cannot go green.

What this file pins (the DUP_WINDOW contract, distinct from the shipped
DUP_SAME_DAY surfacer in orchestrator/check_document_dup.py):

  - Match predicate: same card_name (stripped), same doc_total EXACT
    (round(...,2) — NO tolerance), and 1 <= abs(date delta) <= window_days.
  - Day-0 is EXCLUDED: delta 0 belongs to DUP_SAME_DAY exclusively. The two
    surfacers are complementary and must never double-report the same pair.
  - Findings are PAIRWISE: a window is not an equivalence relation (A~B and B~C
    does not imply A~C), so there is NO transitive grouping — each qualifying
    pair yields ONE finding carrying exactly TWO doc_nums.
  - Type-safety: doc_num is int on the SAP path but a STRING on Xero
    ("BILL-3002") and may be None. A mixed pair must never raise TypeError —
    that would blank the whole check for the run via the chain's unavailable
    contract.
  - Surfaces-never-asserts (invariant 2): candidate language only. The
    description must NOT contain the word "duplicate".

Deliberately NOT tested here, and deliberately NOT testable:

  - No test asserts that any particular window value is "correct". The window is
    an ARBITRARY INPUT supplied by the caller; the worksheet that would derive a
    validated value does not exist yet. Asserting a blessed window would be a
    fabricated truth claim.
  - No test asserts anything about the over-firing / false-positive RATE. No
    must-spare fixture (a legitimate recurring identical charge) exists in the
    corpus — see tests/fixtures/xero-real-format/FIXTURE_NOTES.md. Accuracy is
    UNVALIDATED; these tests pin behaviour, not accuracy.
"""
from __future__ import annotations

import pytest

from orchestrator.check_document_dup_window import detect_window_dups


_SUPPLIER = "Acme Supplies Pte Ltd"


def _purch(doc_num, doc_date, doc_total=1200.00, card_name=_SUPPLIER,
           doc_type="purchase_invoice"):
    """A normalised purchase record (the ``steps._doc_to_record`` shape)."""
    return {
        "doc_num": doc_num,
        "doc_date": doc_date,
        "doc_type": doc_type,
        "doc_currency": "SGD",
        "doc_total": doc_total,
        "card_name": card_name,
        "vat_group": "IP",
    }


# ---------------------------------------------------------------------------
# Core firing behaviour — within-window pairs fire, day-0 and out-of-window do not
# ---------------------------------------------------------------------------

class TestWindowPredicate:

    def test_fires_on_within_window_pair(self):
        # delta 3, window 7 (window is an ARBITRARY caller-supplied input here,
        # not a validated value — see module docstring).
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-04"),
        ]
        findings = detect_window_dups(records, 7)
        assert len(findings) == 1
        assert findings[0]["delta_days"] == 3

    def test_does_not_fire_on_day_zero(self):
        # delta 0 is DUP_SAME_DAY's territory EXCLUSIVELY. If DUP_WINDOW also fired
        # here the reviewer would see the same pair twice under two check names.
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-01"),
        ]
        assert detect_window_dups(records, 7) == []

    def test_does_not_fire_beyond_window(self):
        # delta 8, window 7 -> outside.
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-09"),
        ]
        assert detect_window_dups(records, 7) == []

    def test_boundary_delta_one_fires(self):
        # The lower boundary of the half-open-below range: 1 is IN.
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-02"),
        ]
        findings = detect_window_dups(records, 7)
        assert len(findings) == 1
        assert findings[0]["delta_days"] == 1

    def test_boundary_delta_equals_window_fires(self):
        # delta == window is INSIDE (the range is inclusive at the top).
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-08"),
        ]
        findings = detect_window_dups(records, 7)
        assert len(findings) == 1
        assert findings[0]["delta_days"] == 7

    def test_boundary_delta_window_plus_one_does_not_fire(self):
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-09"),
        ]
        assert detect_window_dups(records, 7) == []

    def test_date_order_in_input_does_not_matter(self):
        # The later document listed first must still fire (abs delta).
        records = [
            _purch(502, "2024-08-04"),
            _purch(501, "2024-08-01"),
        ]
        assert len(detect_window_dups(records, 7)) == 1


# ---------------------------------------------------------------------------
# Non-matches — exact amount, supplier identity, doc_type scope, blank keys
# ---------------------------------------------------------------------------

class TestNonMatches:

    def test_amount_must_be_exact_no_tolerance(self):
        # One cent apart, well within the window -> NOT a collision. There is no
        # amount tolerance; adding one would be a design deviation.
        records = [
            _purch(501, "2024-08-01", doc_total=1200.00),
            _purch(502, "2024-08-04", doc_total=1200.01),
        ]
        assert detect_window_dups(records, 7) == []

    def test_different_supplier_does_not_fire(self):
        records = [
            _purch(501, "2024-08-01", card_name="Acme Supplies Pte Ltd"),
            _purch(502, "2024-08-04", card_name="Beta Trading Pte Ltd"),
        ]
        assert detect_window_dups(records, 7) == []

    @pytest.mark.parametrize("doc_type", ["sales_invoice", "purchase_credit_note"])
    def test_non_purchase_invoice_doc_types_ignored(self, doc_type):
        # Only doc_type == "purchase_invoice" is in scope.
        records = [
            _purch(501, "2024-08-01", doc_type=doc_type),
            _purch(502, "2024-08-04", doc_type=doc_type),
        ]
        assert detect_window_dups(records, 7) == []

    def test_mixed_doc_types_do_not_pair_across_scope(self):
        # A purchase invoice must not pair with a same-supplier/same-amount
        # sales invoice inside the window.
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-04", doc_type="sales_invoice"),
        ]
        assert detect_window_dups(records, 7) == []

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_card_name_excluded(self, blank):
        # A blank key cannot identify a document (mirrors DUP_SAME_DAY's skip).
        records = [
            _purch(501, "2024-08-01", card_name=blank),
            _purch(502, "2024-08-04", card_name=blank),
        ]
        assert detect_window_dups(records, 7) == []

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_doc_date_excluded(self, blank):
        records = [
            _purch(501, blank),
            _purch(502, blank),
        ]
        assert detect_window_dups(records, 7) == []

    def test_one_blank_date_excludes_only_that_record(self):
        # 502 has no date; 501/503 are 3 days apart -> exactly one finding.
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, ""),
            _purch(503, "2024-08-04"),
        ]
        findings = detect_window_dups(records, 7)
        assert len(findings) == 1
        assert findings[0]["doc_nums"] == [501, 503]

    def test_empty_input_returns_empty_list(self):
        assert detect_window_dups([], 7) == []

    def test_single_record_returns_empty_list(self):
        assert detect_window_dups([_purch(501, "2024-08-01")], 7) == []


# ---------------------------------------------------------------------------
# Finding shape — the exact dict contract
# ---------------------------------------------------------------------------

class TestFindingShape:

    @pytest.fixture()
    def finding(self):
        records = [
            _purch(501, "2024-08-01", doc_total=1200.00),
            _purch(502, "2024-08-04", doc_total=1200.00),
        ]
        findings = detect_window_dups(records, 7)
        assert len(findings) == 1
        return findings[0]

    def test_check_name_is_dup_window(self, finding):
        assert finding["check"] == "DUP_WINDOW"

    def test_carries_shared_keys(self, finding):
        assert finding["card_name"] == _SUPPLIER
        assert finding["doc_total"] == 1200.00
        assert isinstance(finding["doc_total"], float)

    def test_delta_days_is_int_at_least_one(self, finding):
        assert isinstance(finding["delta_days"], int)
        assert finding["delta_days"] >= 1
        assert finding["delta_days"] == 3

    def test_no_card_code_key(self, finding):
        # DUP_WINDOW keys on card_name over the DOCUMENTS surface — it is not
        # DUP_CLAIM, which keys on (CardCode, NumAtCard, DocTotal) over the LISTING.
        assert "card_code" not in finding

    def test_no_num_at_card_key(self, finding):
        assert "num_at_card" not in finding

    def test_doc_dates_ascending_pair(self, finding):
        assert finding["doc_dates"] == ["2024-08-01", "2024-08-04"]

    def test_doc_nums_ordered_to_match_doc_dates(self, finding):
        # doc_nums[i] is the DocNum of the document on doc_dates[i] — the two
        # lists are positionally coupled, ordered by DATE (not by doc_num).
        assert finding["doc_nums"] == [501, 502]

    def test_exactly_two_doc_nums_per_finding(self, finding):
        assert len(finding["doc_nums"]) == 2
        assert len(finding["doc_dates"]) == 2

    def test_note_is_candidate_language(self, finding):
        assert finding["note"] == "candidate for reviewer attention"

    def test_description_starts_with_consider_reviewing(self, finding):
        assert finding["description"].startswith("Consider reviewing whether")

    def test_description_never_asserts_duplicate(self, finding):
        # Invariant 2 (surfaces-never-asserts): the surfacer offers a CANDIDATE.
        # The word "duplicate" is a verdict and must not appear in reviewer-facing
        # prose, in any casing.
        assert "duplicate" not in finding["description"].lower()

    def test_doc_nums_ordered_by_date_not_by_number(self):
        # The EARLIER document carries the HIGHER doc_num here: ordering must
        # follow doc_dates, proving the coupling is not incidentally by number.
        records = [
            _purch(900, "2024-08-01"),
            _purch(100, "2024-08-04"),
        ]
        finding = detect_window_dups(records, 7)[0]
        assert finding["doc_dates"] == ["2024-08-01", "2024-08-04"]
        assert finding["doc_nums"] == [900, 100]


# ---------------------------------------------------------------------------
# Pairwise, NOT transitive — a window is not an equivalence relation
# ---------------------------------------------------------------------------

class TestPairwiseNotGrouped:

    def test_three_mutually_within_window_records_yield_three_pairwise_findings(self):
        # 08-01 / 08-03 / 08-05, window 7 -> all three pairs qualify -> THREE
        # findings of two doc_nums each, never ONE grouped finding of three.
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-03"),
            _purch(503, "2024-08-05"),
        ]
        findings = detect_window_dups(records, 7)
        assert len(findings) == 3
        for f in findings:
            assert len(f["doc_nums"]) == 2
        pairs = {tuple(f["doc_nums"]) for f in findings}
        assert pairs == {(501, 502), (501, 503), (502, 503)}

    def test_chain_outside_window_does_not_transitively_pair(self):
        # 08-01 ~ 08-05 (delta 4, in) and 08-05 ~ 08-09 (delta 4, in), but
        # 08-01 vs 08-09 is delta 8 -> OUT. Transitive grouping would wrongly
        # report all three together; pairwise yields exactly the two real pairs.
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-05"),
            _purch(503, "2024-08-09"),
        ]
        findings = detect_window_dups(records, 7)
        pairs = {tuple(f["doc_nums"]) for f in findings}
        assert pairs == {(501, 502), (502, 503)}
        assert (501, 503) not in pairs

    def test_each_pair_reported_once_not_twice(self):
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-04"),
        ]
        findings = detect_window_dups(records, 7)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# doc_num type-safety — int (SAP) / str (Xero) / None must never raise
# ---------------------------------------------------------------------------

class TestDocNumTypeSafety:

    def test_mixed_int_and_str_doc_nums_do_not_raise_and_fire(self):
        # A single group can mix an int SAP DocNum with a non-numeric Xero
        # reference. A bare comparison would raise TypeError and blank the whole
        # check for the run via the chain's unavailable contract.
        records = [
            _purch(3001, "2024-08-01"),
            _purch("BILL-3002", "2024-08-04"),
        ]
        findings = detect_window_dups(records, 7)  # must not raise TypeError
        assert len(findings) == 1
        assert set(findings[0]["doc_nums"]) == {3001, "BILL-3002"}

    def test_all_string_doc_nums_fire(self):
        records = [
            _purch("BILL-3001", "2024-08-01"),
            _purch("BILL-3002", "2024-08-04"),
        ]
        findings = detect_window_dups(records, 7)
        assert len(findings) == 1
        assert findings[0]["doc_nums"] == ["BILL-3001", "BILL-3002"]

    def test_none_doc_num_does_not_raise(self):
        records = [
            _purch(None, "2024-08-01"),
            _purch(502, "2024-08-04"),
        ]
        findings = detect_window_dups(records, 7)  # must not raise
        assert len(findings) == 1

    def test_none_doc_num_renders_no_docnum_in_description(self):
        # The prose must never read a bare "None".
        records = [
            _purch(None, "2024-08-01"),
            _purch(502, "2024-08-04"),
        ]
        finding = detect_window_dups(records, 7)[0]
        assert "(no DocNum)" in finding["description"]
        assert "None" not in finding["description"]

    def test_mixed_types_across_three_records_do_not_raise(self):
        records = [
            _purch(3001, "2024-08-01"),
            _purch("BILL-3002", "2024-08-03"),
            _purch(None, "2024-08-05"),
        ]
        findings = detect_window_dups(records, 7)  # must not raise
        assert len(findings) == 3


# ---------------------------------------------------------------------------
# Read-only contract
# ---------------------------------------------------------------------------

class TestReadOnly:

    def test_input_records_are_not_mutated(self):
        records = [
            _purch(501, "2024-08-01"),
            _purch(502, "2024-08-04"),
        ]
        before = [dict(r) for r in records]
        detect_window_dups(records, 7)
        assert records == before


# ---------------------------------------------------------------------------
# The motivating realism case (Xero-shaped bills 7 days apart)
# ---------------------------------------------------------------------------

class TestRealismCase:

    def test_bill_3004_3005_same_supplier_same_amount_seven_days_apart(self):
        # THE motivating case for building DUP_WINDOW beside DUP_SAME_DAY: the
        # shipped same-day check cannot see this pair at all. The window of 7 is
        # the caller's ARBITRARY input here — this test does not claim 7 is the
        # right window, only that a 7-day-apart pair fires under a 7-day window.
        records = [
            _purch("BILL-3004", "2026-04-10", doc_total=856.00,
                   card_name="Wellington Office Supplies"),
            _purch("BILL-3005", "2026-04-17", doc_total=856.00,
                   card_name="Wellington Office Supplies"),
        ]
        findings = detect_window_dups(records, 7)
        assert len(findings) == 1
        f = findings[0]
        assert f["check"] == "DUP_WINDOW"
        assert f["delta_days"] == 7
        assert f["doc_dates"] == ["2026-04-10", "2026-04-17"]
        assert f["doc_nums"] == ["BILL-3004", "BILL-3005"]
        assert f["card_name"] == "Wellington Office Supplies"
        assert f["doc_total"] == 856.00
        assert "duplicate" not in f["description"].lower()
