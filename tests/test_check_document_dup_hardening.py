"""
tests/test_check_document_dup_hardening.py — pins the doc_num TYPE-SAFETY hardening
of the same-day duplicate-purchase surfacer (orchestrator/check_document_dup.py).

A group's doc_nums can be heterogeneous: int on the SAP path, STRING on the Xero
path (a non-numeric reference like "BILL-3002" — see steps._coerce_doc_num), and a
group can mix them, or carry a None. A bare ``sorted`` over such a group raises
TypeError, which the chain's own try/except would turn into
document_dup_status="unavailable" — silently BLANKING the whole check for that run.
These tests pin that the detector NEVER raises and NEVER self-disables on a mixed
group: it surfaces the finding with a total, type-safe ordering (numeric first by
value, strings next lexically, None last), and represents a None doc_num as JSON
null in doc_nums and "(no DocNum)" in the description prose.
"""
from __future__ import annotations

from orchestrator.check_document_dup import detect_same_day_dups


def _rec(doc_num, *, doc_date="2024-08-01", doc_total=1200.00,
         card_name="Acme Supplies Pte Ltd", doc_type="purchase_invoice") -> dict:
    return {
        "doc_num": doc_num,
        "doc_date": doc_date,
        "doc_type": doc_type,
        "doc_currency": "SGD",
        "doc_total": doc_total,
        "card_name": card_name,
        "vat_group": "IP",
    }


class TestNoneIntMixDoesNotCrashOrDisable:
    """A group mixing a None and an int doc_num must surface, not blank the check."""

    def test_none_int_group_produces_one_finding(self):
        findings = detect_same_day_dups([_rec(505), _rec(None)])
        assert len(findings) == 1  # did NOT raise, did NOT return []

    def test_none_sorts_last_after_ints(self):
        findings = detect_same_day_dups([_rec(None), _rec(505)])
        # numeric first (by value), None last — total, type-safe order.
        assert findings[0]["doc_nums"] == [505, None]

    def test_none_preserved_as_null_in_doc_nums(self):
        findings = detect_same_day_dups([_rec(505), _rec(None)])
        assert None in findings[0]["doc_nums"]  # verbatim JSON null, not dropped

    def test_none_rendered_as_no_docnum_in_description(self):
        findings = detect_same_day_dups([_rec(505), _rec(None)])
        desc = findings[0]["description"]
        assert "(no DocNum)" in desc
        assert "None" not in desc  # never a bare Python 'None' in reviewer prose

    def test_two_none_doc_nums_do_not_crash(self):
        # Two records both missing a doc_num still share the key -> one finding.
        findings = detect_same_day_dups([_rec(None), _rec(None)])
        assert len(findings) == 1
        assert findings[0]["doc_nums"] == [None, None]


class TestIntStrMixDoesNotCrash:
    """The reachable Xero case: numeric + non-numeric reference in one group."""

    def test_int_str_group_produces_one_finding(self):
        findings = detect_same_day_dups([_rec(505), _rec("BILL-3002")])
        assert len(findings) == 1  # int vs str never compared -> no TypeError

    def test_ints_sort_before_strings(self):
        findings = detect_same_day_dups([_rec("BILL-3002"), _rec(505)])
        # numeric rank first (by value), string rank next (lexical).
        assert findings[0]["doc_nums"] == [505, "BILL-3002"]

    def test_all_string_group_sorts_lexically(self):
        findings = detect_same_day_dups(
            [_rec("BILL-3005"), _rec("BILL-3002"), _rec("BILL-3009")]
        )
        assert findings[0]["doc_nums"] == ["BILL-3002", "BILL-3005", "BILL-3009"]


class TestAllIntUnchanged:
    """The SAP path (all-int) ordering must be byte-identical to a plain sorted()."""

    def test_all_int_ascending_preserved(self):
        findings = detect_same_day_dups([_rec(609), _rec(606)])
        assert findings[0]["doc_nums"] == [606, 609]
        assert "None" not in findings[0]["description"]
        assert "(no DocNum)" not in findings[0]["description"]
