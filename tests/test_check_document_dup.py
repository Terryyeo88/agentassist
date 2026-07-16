"""
tests/test_check_document_dup.py — FAILING-FIRST unit tests for the NEW
deterministic same-day duplicate-purchase surfacer (orchestrator/check_document_dup.py).

The module + function do NOT exist yet; these tests are RED by design (ImportError on
collection until the detector is built, then AttributeError / assertion failures until
the pinned contract is satisfied). They pin the PINNED CONTRACT exactly:

  - module   orchestrator/check_document_dup.py
  - function detect_same_day_dups(records: list[dict]) -> list[dict]
  - considers ONLY doc_type == "purchase_invoice"
  - match key (card_name, round(float(doc_total), 2), doc_date) — EXACT, SAME-DAY only
    (no date window, no amount tolerance)
  - blank card_name OR blank doc_date -> excluded
  - a group of >= 2 -> exactly ONE finding {check, card_name, doc_total, doc_date,
    doc_nums (sorted asc), description, note}; NO num_at_card, NO card_code
  - description surfaces ("Consider reviewing whether ...") and NEVER asserts a verdict
  - empty input -> []

All hermetic: pure Python, no SAP, no anthropic, no PDF.
"""
from __future__ import annotations

from orchestrator.check_document_dup import detect_same_day_dups


# ---------------------------------------------------------------------------
# Record builder — mirrors orchestrator/steps.py:_doc_to_record field names
# ---------------------------------------------------------------------------

def _rec(
    doc_num: int,
    *,
    doc_date: str = "2024-08-01",
    doc_type: str = "purchase_invoice",
    doc_currency: str = "SGD",
    doc_total: float = 1200.00,
    card_name: str = "Acme Supplies Pte Ltd",
    vat_group: str = "IP",
) -> dict:
    """Build a normalised InvoiceRecord dict (exact _doc_to_record shape)."""
    return {
        "doc_num": doc_num,
        "doc_date": doc_date,
        "doc_type": doc_type,
        "doc_currency": doc_currency,
        "doc_total": doc_total,
        "card_name": card_name,
        "vat_group": vat_group,
    }


# ---------------------------------------------------------------------------
# Positive: same supplier + same amount + same day -> ONE finding
# ---------------------------------------------------------------------------

class TestSameDayCollision:

    def test_pair_produces_exactly_one_finding(self):
        recs = [_rec(501), _rec(502)]
        findings = detect_same_day_dups(recs)
        assert len(findings) == 1

    def test_finding_check_is_dup_same_day(self):
        findings = detect_same_day_dups([_rec(501), _rec(502)])
        assert findings[0]["check"] == "DUP_SAME_DAY"

    def test_finding_carries_key_fields(self):
        findings = detect_same_day_dups([_rec(501), _rec(502)])
        f = findings[0]
        assert f["card_name"] == "Acme Supplies Pte Ltd"
        assert f["doc_total"] == 1200.00
        assert f["doc_date"] == "2024-08-01"

    def test_doc_nums_are_both_and_sorted_ascending(self):
        # Provide out-of-order doc_nums; finding must sort them ascending.
        findings = detect_same_day_dups([_rec(509), _rec(502)])
        assert findings[0]["doc_nums"] == [502, 509]

    def test_note_is_candidate_language(self):
        findings = detect_same_day_dups([_rec(501), _rec(502)])
        assert findings[0]["note"] == "candidate for reviewer attention"

    def test_doc_total_rounded_to_two_dp(self):
        # 1200.001 and 1200.004 both round to 1200.00 -> same key.
        recs = [_rec(501, doc_total=1200.001), _rec(502, doc_total=1200.004)]
        findings = detect_same_day_dups(recs)
        assert len(findings) == 1
        assert findings[0]["doc_total"] == 1200.00


# ---------------------------------------------------------------------------
# KEY NEGATIVE: same-day floor — a different DATE is NOT a match
# ---------------------------------------------------------------------------

class TestSameDayFloor:

    def test_same_supplier_same_amount_different_date_is_no_finding(self):
        # THE key negative test: no date window. A day apart is NOT a collision.
        recs = [
            _rec(501, doc_date="2024-08-01"),
            _rec(502, doc_date="2024-08-02"),
        ]
        assert detect_same_day_dups(recs) == []

    def test_same_supplier_same_date_different_amount_is_no_finding(self):
        # No amount tolerance: a cent apart is NOT a collision.
        recs = [
            _rec(501, doc_total=1200.00),
            _rec(502, doc_total=1200.01),
        ]
        assert detect_same_day_dups(recs) == []


# ---------------------------------------------------------------------------
# Grouping: three records sharing the key -> ONE finding, all three doc_nums
# ---------------------------------------------------------------------------

class TestGrouping:

    def test_three_records_one_finding_all_doc_nums_sorted(self):
        recs = [_rec(510), _rec(502), _rec(507)]
        findings = detect_same_day_dups(recs)
        assert len(findings) == 1
        assert findings[0]["doc_nums"] == [502, 507, 510]

    def test_group_of_one_produces_no_finding(self):
        assert detect_same_day_dups([_rec(501)]) == []


# ---------------------------------------------------------------------------
# doc_type filter — purchase_invoice ONLY
# ---------------------------------------------------------------------------

class TestDocTypeFilter:

    def test_sales_invoice_pair_ignored(self):
        recs = [
            _rec(501, doc_type="sales_invoice"),
            _rec(502, doc_type="sales_invoice"),
        ]
        assert detect_same_day_dups(recs) == []

    def test_credit_note_pair_ignored(self):
        recs = [
            _rec(501, doc_type="purchase_credit_note"),
            _rec(502, doc_type="purchase_credit_note"),
        ]
        assert detect_same_day_dups(recs) == []


# ---------------------------------------------------------------------------
# Blank-key exclusion — mirrors DUP_CLAIM's blank-NumAtCard skip
# ---------------------------------------------------------------------------

class TestBlankKeyExclusion:

    def test_blank_card_name_pair_excluded(self):
        recs = [_rec(501, card_name=""), _rec(502, card_name="")]
        assert detect_same_day_dups(recs) == []

    def test_blank_doc_date_pair_excluded(self):
        recs = [_rec(501, doc_date=""), _rec(502, doc_date="")]
        assert detect_same_day_dups(recs) == []


# ---------------------------------------------------------------------------
# Distinct-from-DUP_CLAIM shape: NO num_at_card, NO card_code
# ---------------------------------------------------------------------------

class TestFindingShape:

    def test_finding_has_no_num_at_card_key(self):
        findings = detect_same_day_dups([_rec(501), _rec(502)])
        assert "num_at_card" not in findings[0]

    def test_finding_has_no_card_code_key(self):
        findings = detect_same_day_dups([_rec(501), _rec(502)])
        assert "card_code" not in findings[0]


# ---------------------------------------------------------------------------
# Surfaces-never-asserts: description language
# ---------------------------------------------------------------------------

class TestDescriptionSurfaces:

    def test_description_starts_with_consider_reviewing_whether(self):
        findings = detect_same_day_dups([_rec(501), _rec(502)])
        assert findings[0]["description"].startswith("Consider reviewing whether")

    def test_description_does_not_assert_a_duplicate_verdict(self):
        findings = detect_same_day_dups([_rec(501), _rec(502)])
        desc = findings[0]["description"].lower()
        assert "is a duplicate" not in desc
        assert "are duplicates" not in desc


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput:

    def test_empty_input_returns_empty_list(self):
        assert detect_same_day_dups([]) == []
