"""
tests/test_xero_contacts_join.py — Slice C: the Xero Contacts → NO_GST_REG join.

D-2026-09-20-slice-c-contacts-no-gst-reg. Covers the RULED test set at the reader/join
layer: C1 (the three pairings), C3 (synthetic parse + join cases), C4 (coverage counts
equal the actual counts), C8 (the no-finding pins + the PII placeholder pin), plus the
normaliser-parity pin that keeps the feeder's local copy honest.

WHAT THIS PROVES AND WHAT IT DOES NOT. It proves the MECHANISM — that a supplied Xero
Contacts export joins to the F5 purchase rows by contact name, that a blank TaxNumber is
what makes NO_GST_REG fire, and that everything not examined is COUNTED rather than
silently dropped. It proves NOTHING about accuracy: the fixtures are real Xero FORMAT over
SYNTHETIC content (DEBT-3 — no real client export has ever been read), the check is
PRESENCE-ONLY (R1: a non-blank TaxNumber is never validated, looked up or compared), and a
finding is a CANDIDATE for a reviewer, never a verdict.

APPEND-ONLY BOUNDARY: this is a NEW test file. No existing test file is modified, and no
existing fixture is modified — both committed Contacts.csv files are read-only here (R6).

Hermetic: no network, no anthropic import, no live SAP/Xero. Pure stdlib + pytest.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

# Importing the chain wires mcp-servers/custom onto sys.path; sap_b1_server then imports.
from orchestrator.chain import run_chain  # noqa: F401
import sap_b1_server

from feeders import coverage_status as cov_status
from feeders import extract_schema as schema
from feeders.xero_contacts import (
    ContactsJoin,
    load_contacts,
    normalize_contact_name,
)
from feeders.xero_f5_reader import XeroF5ChainReader

_REPO_ROOT = Path(__file__).resolve().parents[1]

_DEMO_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-demo-2026Q2"
_REAL_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-real-format"

_DEMO_F5 = _DEMO_DIR / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_REAL_F5 = _REAL_DIR / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_DEMO_CONTACTS = _DEMO_DIR / "Contacts.csv"
_REAL_CONTACTS = _REAL_DIR / "Contacts.csv"

_START, _END = "2026-04-01", "2026-06-30"

#: The demo F5's one input-tax purchase row with NO contact name (F5, re-verified
#: 2026-09-20): reference "#13", 2026-05-29, GST 6.30. The real-format F5 carries the
#: SAME row — both pairings are DEGRADED by exactly one nameless line.
_NAMELESS_REFERENCE = "#13"


def _detect(reader):
    """Run the REAL detect pass over a reader and return its issues."""
    return json.loads(
        sap_b1_server.detect_gst_errors(_START, _END, expected_rate=0.09, reader=reader)
    )["issues"]


def _no_gst_reg(reader) -> list:
    return [i for i in _detect(reader) if i["error_code"] == "NO_GST_REG"]


def _cov_row(reader, check: str) -> dict:
    for row in reader.coverage_status():
        if row.check == check:
            return row.as_dict()
    raise AssertionError(f"coverage check {check!r} not emitted")


# ══ C1 — the three ruled pairings ═════════════════════════════════════════════════════


class TestPairings:
    """C1. Every pairing is (an F5 export) × (a Contacts export), both committed."""

    def test_pairing1_demo_f5_demo_contacts_fires_on_bill_3003_only(self):
        reader = XeroF5ChainReader(_DEMO_F5, contacts=_DEMO_CONTACTS)
        findings = _no_gst_reg(reader)
        assert [f["doc_num"] for f in findings] == ["BILL-3003"]
        assert findings[0]["card_name"] == "NoReg Trading"
        # R4: the finding shape is the SAP producer's, unchanged — same keys, same severity.
        assert findings[0]["severity"] == "HIGH"
        assert set(findings[0]) == {
            "severity", "error_code", "doc_num", "doc_date", "card_name",
            "description", "recommendation",
        }

    def test_pairing1_every_named_supplier_joins_uniquely(self):
        reader = XeroF5ChainReader(_DEMO_F5, contacts=_DEMO_CONTACTS)
        join = reader.contacts_join
        # 20 input-tax purchase lines; 19 named and all uniquely matched; 1 nameless.
        assert join == ContactsJoin(examined=19, missing=0, ambiguous=0, nameless=1)
        assert join.total == 20
        assert not join.fully_examined

    def test_pairing1_degraded_solely_by_the_nameless_line(self):
        reader = XeroF5ChainReader(_DEMO_F5, contacts=_DEMO_CONTACTS)
        row = _cov_row(reader, "NO_GST_REG")
        assert row["level"] == "degraded"
        # R3: the three counts stated SEPARATELY, and derived — never parsed from prose.
        assert "0 not found" in row["reason"]
        assert "0 ambiguous" in row["reason"]
        assert "1 with no supplier on the transaction" in row["reason"]

    def test_pairing2_real_format_f5_with_its_own_contacts(self):
        reader = XeroF5ChainReader(_REAL_F5, contacts=_REAL_CONTACTS)
        findings = _no_gst_reg(reader)
        assert [f["doc_num"] for f in findings] == ["BILL-3003"]
        # MEASURED nameless count on the real-format F5 (F5 re-verification): exactly one,
        # the same "#13" row the demo export carries.
        assert reader.contacts_join == ContactsJoin(
            examined=7, missing=0, ambiguous=0, nameless=1
        )
        assert _cov_row(reader, "NO_GST_REG")["level"] == "degraded"

    def test_pairing3_demo_f5_real_format_contacts(self):
        reader = XeroF5ChainReader(_DEMO_F5, contacts=_REAL_CONTACTS)
        findings = _no_gst_reg(reader)
        # NoReg fires; the twelve purchase lines whose supplier is absent from this
        # smaller Contacts export
        # produce NO findings at all (R2 — a join miss is never a finding).
        assert [f["doc_num"] for f in findings] == ["BILL-3003"]
        join = reader.contacts_join
        assert join == ContactsJoin(examined=7, missing=12, ambiguous=0, nameless=1)
        row = _cov_row(reader, "NO_GST_REG")
        assert row["level"] == "degraded"
        assert "12 not found" in row["reason"]
        assert "1 with no supplier on the transaction" in row["reason"]


# ══ C8 — what must NOT produce a finding, and the PII placeholder pin ═════════════════


class TestNoFinding:

    def test_shared_tax_number_never_flags_acme_or_goodvendor(self):
        """R6 bait: GoodVendor and Acme share 200611111A. PRESENCE-only (R1) means a
        shared — even duplicated — number is silent. A shared-registration check is a
        FUTURE build; this slice must not smuggle one in."""
        reader = XeroF5ChainReader(_DEMO_F5, contacts=_DEMO_CONTACTS)
        flagged = {f["card_name"] for f in _no_gst_reg(reader)}
        assert "GoodVendor Pte Ltd" not in flagged
        assert "Acme Pte Ltd" not in flagged

    def test_blank_tax_number_contact_with_no_input_tax_line_is_silent(self):
        """Meridian Systems Inc has a blank TaxNumber in the demo Contacts export but no
        input-tax purchase line in the demo F5 — the check is transaction-driven, so an
        unregistered contact nobody claimed from is never a finding."""
        reader = XeroF5ChainReader(_DEMO_F5, contacts=_DEMO_CONTACTS)
        assert "Meridian Systems Inc" not in {f["card_name"] for f in _no_gst_reg(reader)}

    def test_blank_reg_supplies_is_silent_in_pairing2(self):
        """Same property on the real-format pairing: Blank Reg Supplies Pte Ltd carries a
        blank TaxNumber but no input-tax line in the real-format F5."""
        reader = XeroF5ChainReader(_REAL_F5, contacts=_REAL_CONTACTS)
        assert "Blank Reg Supplies Pte Ltd" not in {
            f["card_name"] for f in _no_gst_reg(reader)
        }

    @pytest.mark.parametrize("path", [_DEMO_CONTACTS, _REAL_CONTACTS])
    def test_contacts_fixtures_carry_only_placeholder_contact_details(self, path: Path):
        """PII pin (R6 / PR #179). A 'synthetic' fixture once carried a real person's
        e-mail and phone number. Every non-blank contact detail in BOTH committed
        fixtures must be an obvious placeholder, so a re-import of a real export cannot
        land real personal data in the repo unnoticed."""
        rows = list(csv.reader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))
        header = rows[0]
        email_cols = [i for i, name in enumerate(header) if "Email" in name and "Include" not in name]
        phone_cols = [
            i for i, name in enumerate(header)
            if name in ("PhoneNumber", "MobileNumber", "FaxNumber", "DDINumber")
        ]
        for row in rows[1:]:
            for i in email_cols:
                value = row[i].strip() if i < len(row) else ""
                if value:
                    assert value.endswith("example.com"), f"non-placeholder e-mail {value!r}"
            for i in phone_cols:
                value = row[i].strip() if i < len(row) else ""
                if value:
                    assert "6000" in value, f"non-placeholder phone number {value!r}"


# ══ C3 — synthetic parse + join cases ════════════════════════════════════════════════


_HEADER = ["*ContactName"] + [f"col{i}" for i in range(1, 31)] + ["TaxNumber"] + [
    f"col{i}" for i in range(32, 73)
]


def _contacts_csv(tmp_path: Path, rows: list, *, bom: bool = False, ragged: bool = False) -> Path:
    """Write a synthetic Contacts export: real 73-field header, CRLF, optional BOM."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(_HEADER)
    for name, tax_number in rows:
        record = [""] * len(_HEADER)
        record[0] = name
        record[31] = tax_number
        if ragged:
            record = record[:53]  # a real Xero export's data rows are SHORT (53 of 73)
        writer.writerow(record)
    data = out.getvalue().encode("utf-8")
    path = tmp_path / ("contacts_bom.csv" if bom else "contacts.csv")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return path


class TestSyntheticJoinCases:

    def test_whitespace_only_tax_number_counts_as_blank(self, tmp_path):
        index = load_contacts(_contacts_csv(tmp_path, [("Ghost Pte Ltd", "   ")]))
        state, tax_number = index.match("Ghost Pte Ltd")
        assert (state, tax_number) == ("unique", "")

    def test_present_tax_number_is_silent(self, tmp_path):
        index = load_contacts(_contacts_csv(tmp_path, [("Ghost Pte Ltd", "200611111A")]))
        assert index.match("Ghost Pte Ltd") == ("unique", "200611111A")

    def test_missing_supplier_is_not_examined(self, tmp_path):
        index = load_contacts(_contacts_csv(tmp_path, [("Ghost Pte Ltd", "200611111A")]))
        assert index.match("Somebody Else Pte Ltd") == ("missing", None)

    def test_ambiguous_supplier_is_not_examined(self, tmp_path):
        """Two contacts of the SAME name: the join refuses to pick one (R2 — never a
        finding, and never a silent first-wins choice)."""
        index = load_contacts(
            _contacts_csv(tmp_path, [("Twin Pte Ltd", "200611111A"), ("Twin Pte Ltd", "")])
        )
        assert index.match("Twin Pte Ltd") == ("ambiguous", None)

    def test_nameless_row_is_counted_not_examined(self, tmp_path):
        index = load_contacts(_contacts_csv(tmp_path, [("Ghost Pte Ltd", "200611111A")]))
        assert index.match("") == ("nameless", None)
        assert index.match("   ") == ("nameless", None)
        assert index.match(None) == ("nameless", None)

    def test_ragged_row_parses(self, tmp_path):
        """A real Xero export's data rows carry 53 fields against a 73-field header."""
        index = load_contacts(
            _contacts_csv(tmp_path, [("Ghost Pte Ltd", "200611111A")], ragged=True)
        )
        assert index.match("Ghost Pte Ltd") == ("unique", "200611111A")

    def test_whitespace_and_case_variant_still_joins(self, tmp_path):
        """The E-check counterparty normaliser: collapse whitespace runs + casefold."""
        index = load_contacts(_contacts_csv(tmp_path, [("OldRate  Supplies Pte Ltd", "")]))
        assert index.match("  oldrate supplies   pte ltd ") == ("unique", "")

    def test_bom_and_no_bom_parse_identically(self, tmp_path):
        """D-2026-09-20 correction: NEITHER committed fixture carries a UTF-8 BOM (the
        recon claim was wrong). utf-8-sig tolerates both, so the same content must parse
        identically with and without one — a real Xero export may carry either."""
        rows = [("Ghost Pte Ltd", "200611111A"), ("NoReg Trading", "")]
        plain = load_contacts(_contacts_csv(tmp_path, rows))
        with_bom = load_contacts(_contacts_csv(tmp_path, rows, bom=True))
        assert plain.by_name == with_bom.by_name
        assert plain.contact_count == with_bom.contact_count == 2
        assert with_bom.match("Ghost Pte Ltd") == ("unique", "200611111A")

    def test_normaliser_matches_the_e_check_counterparty_normaliser(self):
        """`feeders/` may not import `agent/` (merge-gates Gate a), so the normaliser is
        re-implemented in the feeder. A TEST may import both — this pins that the two
        definitions agree, so the copy can never drift apart silently."""
        from agent.decision_ledger import _normalize_counterparty

        for value in ("OldRate  Supplies", "  ACME pte ltd ", "", "NoReg\tTrading", None):
            assert normalize_contact_name(value) == _normalize_counterparty(value)


# ══ C4 — coverage counts equal the ACTUAL counts, in all three pairings ══════════════


class TestCoverageCounts:

    @pytest.mark.parametrize(
        "f5, contacts",
        [(_DEMO_F5, _DEMO_CONTACTS), (_REAL_F5, _REAL_CONTACTS), (_DEMO_F5, _REAL_CONTACTS)],
    )
    def test_reason_counts_equal_the_measured_join(self, f5: Path, contacts: Path):
        """The reason is BUILT from the join summary; the join summary is COUNTED from the
        documents. Recount both here from the reader's own documents so a hand-typed
        number in either place fails."""
        reader = XeroF5ChainReader(f5, contacts=contacts)
        index = load_contacts(contacts)
        expected = {"examined": 0, "missing": 0, "ambiguous": 0, "nameless": 0}
        for doc in reader.fetch_invoices("PurchaseInvoices", _START, _END):
            tax = sum(float(l.get("TaxTotal") or 0) for l in doc["DocumentLines"])
            if tax <= 0.01:
                continue
            state, _ = index.match(doc["CardName"])
            expected["examined" if state == "unique" else state] += 1
        assert reader.contacts_join == ContactsJoin(**expected)
        reason = _cov_row(reader, "NO_GST_REG")["reason"]
        assert f"{expected['examined']} of {sum(expected.values())}" in reason
        assert f"{expected['missing']} not found" in reason
        assert f"{expected['ambiguous']} ambiguous" in reason
        assert f"{expected['nameless']} with no supplier on the transaction" in reason

    def test_full_only_when_every_input_tax_line_was_examined(self, tmp_path):
        """R3: FULL is reserved for a complete examination. The demo F5 can never reach it
        (its nameless line is in the denominator by ruling), so this proves the FULL leg
        through the seam itself."""
        coverage = XeroF5ChainReader(_DEMO_F5, contacts=_DEMO_CONTACTS).coverage()
        rows = cov_status.derive_coverage_statuses(
            coverage,
            company_wide_population_present=False,
            contacts_join=ContactsJoin(examined=20, missing=0, ambiguous=0, nameless=0),
        )
        row = next(r for r in rows if r.check == "NO_GST_REG")
        assert (row.level, row.reason) == ("full", "")

    def test_absent_contacts_join_is_todays_behaviour_exactly(self):
        """D2/C2 at the seam: no contacts → the SAME statuses, byte-identical, including
        the unchanged unavailable reason."""
        coverage = XeroF5ChainReader(_DEMO_F5).coverage()
        with_default = cov_status.derive_coverage_statuses(
            coverage, company_wide_population_present=False
        )
        explicit_none = cov_status.derive_coverage_statuses(
            coverage, company_wide_population_present=False, contacts_join=None
        )
        assert [r.as_dict() for r in with_default] == [r.as_dict() for r in explicit_none]
        row = next(r for r in with_default if r.check == "NO_GST_REG")
        assert row.level == "unavailable"
        assert row.reason == cov_status._NO_GST_REG_UNAVAILABLE


# ══ The reader's own surfaces under a supplied Contacts export ═══════════════════════


class TestReaderSurfaces:

    def test_business_partner_resolves_only_for_a_joined_supplier(self):
        reader = XeroF5ChainReader(_DEMO_F5, contacts=_DEMO_CONTACTS)
        assert reader.get_business_partner("NoReg Trading")["FederalTaxID"] == ""
        assert reader.get_business_partner("Acme Pte Ltd")["FederalTaxID"] == "200611111A"
        with pytest.raises(KeyError):
            reader.get_business_partner("Nobody Pte Ltd")

    def test_without_contacts_the_bp_surface_still_refuses(self):
        """D2: absent a contacts file the reader is byte-identical to today — the BP master
        is ABSENT and says so, rather than fabricating an empty supplier."""
        reader = XeroF5ChainReader(_DEMO_F5)
        assert reader.contacts_join is None
        with pytest.raises(KeyError):
            reader.get_business_partner("NoReg Trading")

    def test_card_code_is_set_only_for_uniquely_joined_purchase_rows(self):
        reader = XeroF5ChainReader(_DEMO_F5, contacts=_REAL_CONTACTS)
        by_ref = {
            d["DocNum"]: d for d in reader.fetch_invoices("PurchaseInvoices", _START, _END)
        }
        assert by_ref["BILL-3003"]["CardCode"] == "NoReg Trading"   # unique match
        assert by_ref["BILL-3008"]["CardCode"] == ""                # missing from Contacts
        assert by_ref[_NAMELESS_REFERENCE]["CardCode"] == ""        # nameless row
        # Sales documents are NEVER touched by the join (purchase-side check only).
        assert all(
            d["CardCode"] == "" for d in reader.fetch_invoices("Invoices", _START, _END)
        )

    def test_coverage_declares_federaltaxid_only_when_contacts_supplied(self):
        key = (schema.BUSINESS_PARTNERS_SHEET, "FederalTaxID")
        assert XeroF5ChainReader(_DEMO_F5).coverage().is_covered(*key) is False
        assert XeroF5ChainReader(_DEMO_F5, contacts=_DEMO_CONTACTS).coverage().is_covered(*key) is True

    def test_module_level_covered_fields_is_not_widened(self):
        """Ruling 3: the declaration is PER INSTANCE. A module-constant widening would
        make every reader — including one with no contacts — claim the surface."""
        from feeders import xero_f5_reader as mod

        assert (schema.BUSINESS_PARTNERS_SHEET, "FederalTaxID") not in mod._COVERED_FIELDS

    def test_contacts_with_no_populated_tax_number_stays_unavailable(self, tmp_path):
        """The OBSERVED-population doctrine (D-2026-07-27) applies to this surface too: a
        Contacts export whose TaxNumber column is present but 0%-populated is NOT covered,
        so the check reports unavailable rather than flagging every supplier off an empty
        column. Consequence of the doctrine, pinned so it can never change silently."""
        empty = _contacts_csv(tmp_path, [("NoReg Trading", ""), ("Acme Pte Ltd", "")])
        reader = XeroF5ChainReader(_DEMO_F5, contacts=empty)
        assert _cov_row(reader, "NO_GST_REG")["level"] == "unavailable"
        assert _no_gst_reg(reader) == []
