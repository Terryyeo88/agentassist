"""
PR-2 — serialize ledger-recon findings into the review queue (hop 1, backend serializer).

Backend-only. A new ``serialize_ledger_recon_queue`` reads the deterministic T2.24
findings from compile_output —
  * ``ledger_recon_findings``  (Signal A: side + divergence), and
  * ``not_included_findings``  (Signal B: reference + amount) —
and maps each onto the EXISTING ``QUEUE_ITEM_KEYS`` contract (lean A, prose reuse):
NO new contract keys. The three review fields (ledger-transaction reference, GST box,
impact-on-GST-payable) are folded into description/recommendation as readable prose,
with the impact figure read VERBATIM from the finding (box-isolation — no arithmetic).

``iras_basis`` is the honest internal-consistency label — NOT a manufactured IRAS cite
(ledger-recon is an internal-consistency check, not an IRAS-cited finding).

These tests build a SYNTHETIC compile_output (the locked demo fixture is NOT touched)
and are RED before the serializer exists.
"""
from __future__ import annotations

import copy

import pytest

from api.viewmodel import QUEUE_ITEM_KEYS

# The serializer under test (does not exist yet → import guarded so collection shows RED clearly).
from api.viewmodel import serialize_ledger_recon_queue


# ── Synthetic compile_output carrying real-shaped Signal A + Signal B findings ────────

def _signal_a() -> dict:
    """Mirror orchestrator.check_gst_ledger_recon._make_finding (output side)."""
    return {
        "check_id": "GST_LEDGER_RECON",
        "finding_type": "ledger_recon_divergence",
        "side": "output",
        "ledger_gst": 26141.32,
        "declared_gst": 25871.32,
        "divergence": 270.0,
        "description": (
            "Ledger-derived output GST (26141.32) exceeds declared Box 6 (25871.32) by "
            "270.0. If a reviewer adjudicates this divergence as an error in the return, net "
            "GST payable would change by 270.0. This is an internal-consistency observation "
            "between two derivations of the same source, not a verdict that either side is correct."
        ),
        "recommendation": (
            "Candidate for reviewer adjudication. Reconcile the 820 control-account postings "
            "for this side against the declared return box."
        ),
    }


def _signal_b() -> dict:
    """Mirror orchestrator.check_gst_ledger_recon._make_not_included_finding."""
    return {
        "check_id": "GST_LEDGER_RECON",
        "finding_type": "not_included_gst_drop",
        "account": "820 - GST",
        "reference": "MJ-0007",
        "amount": 6.3,
        "description": (
            "A GST amount of 6.3 was posted to the control account (820 - GST) on MJ-0007 "
            "(manual journal) with no tax code, so it appears in the F5 report's 'Transactions "
            "not included' section and lands in no box while remaining in the 820 ledger. If a "
            "reviewer adjudicates this as GST that should have been declared, net GST payable "
            "would change by 6.3. This is an internal-consistency observation between the 820 "
            "ledger and the F5 report, not a verdict that the posting is correct."
        ),
        "recommendation": (
            "Candidate for reviewer adjudication. Reconcile this 820 control-account posting "
            "against the F5 return — confirm whether the GST should have been declared in a box."
        ),
    }


def _compile_output_with_findings() -> dict:
    return {
        "ledger_recon_findings": [_signal_a()],
        "not_included_findings": [_signal_b()],
    }


@pytest.fixture
def rows() -> list[dict]:
    return serialize_ledger_recon_queue(_compile_output_with_findings())


# ── Contract: exactly QUEUE_ITEM_KEYS, no new keys ────────────────────────────────────

class TestContract:
    def test_two_rows_one_per_finding(self, rows):
        assert len(rows) == 2

    def test_each_row_matches_queue_item_keys_exactly(self, rows):
        for row in rows:
            assert set(row.keys()) == set(QUEUE_ITEM_KEYS), (
                "ledger-recon rows must satisfy QUEUE_ITEM_KEYS exactly — no new contract keys"
            )

    def test_validation_status_unvalidated(self, rows):
        for row in rows:
            assert row["validation_status"] == "unvalidated"


# ── error_code: mechanical routing label, not tax meaning ─────────────────────────────

class TestRoutingLabels:
    def test_signal_a_error_code(self, rows):
        a = next(r for r in rows if r["description"].startswith("Ledger-derived"))
        assert a["error_code"] == "LEDGER_RECON"

    def test_signal_b_error_code(self, rows):
        b = next(r for r in rows if "Transactions" in (r["description"] or ""))
        assert b["error_code"] == "NOT_INCLUDED"


# ── The three review fields, as prose; impact surfaced VERBATIM (box-isolation) ───────

class TestProseReuseAndBoxIsolation:
    def test_signal_a_prose_carries_ref_box_and_impact(self, rows):
        a = next(r for r in rows if r["error_code"] == "LEDGER_RECON")
        blob = f"{a['description']} || {a['recommendation']}"
        assert "GST box" in blob or "Box 6" in blob            # GST box
        assert "impact on GST payable" in blob.lower() or "net GST payable" in blob  # impact
        assert "270.0" in blob                                  # impact VERBATIM (== finding divergence)
        assert "output" in blob.lower()                         # ledger reference / side

    def test_signal_b_prose_carries_ref_box_and_impact(self, rows):
        b = next(r for r in rows if r["error_code"] == "NOT_INCLUDED")
        blob = f"{b['description']} || {b['recommendation']}"
        assert "MJ-0007" in blob                                # ledger-transaction reference VERBATIM
        assert "not included" in blob.lower() or "no box" in blob.lower()  # GST box (none)
        assert "6.3" in blob                                    # impact VERBATIM (== finding amount)

    def test_impact_is_verbatim_not_recomputed(self):
        # The surfaced impact must be the finding's own divergence/amount, byte-for-byte.
        co = _compile_output_with_findings()
        out = serialize_ledger_recon_queue(co)
        a = next(r for r in out if r["error_code"] == "LEDGER_RECON")
        b = next(r for r in out if r["error_code"] == "NOT_INCLUDED")
        assert str(_signal_a()["divergence"]) in f"{a['description']} {a['recommendation']}"
        assert str(_signal_b()["amount"]) in f"{b['description']} {b['recommendation']}"

    def test_serializer_does_not_mutate_compile_output(self):
        co = _compile_output_with_findings()
        before = copy.deepcopy(co)
        serialize_ledger_recon_queue(co)
        assert co == before, "serializer must be read-only over compile_output"


# ── iras_basis: honest internal-consistency label, NOT a manufactured IRAS cite ───────

class TestHonestIrasBasis:
    def test_iras_basis_is_internal_consistency_not_a_fake_cite(self, rows):
        for row in rows:
            basis = (row["iras_basis"] or "").lower()
            assert "internal-consistency" in basis or "internal consistency" in basis, (
                "ledger-recon iras_basis must be the honest internal-consistency label"
            )
            # No manufactured IRAS statutory/e-Tax citation.
            assert "iras gst act" not in basis
            assert "e-tax guide" not in basis
            assert "regulation" not in basis


# ── severity: keep the key, carry the finding's value (lean B; None here) ─────────────

class TestSeverity:
    def test_severity_key_present_and_from_finding(self, rows):
        for row in rows:
            assert "severity" in row
            # ledger-recon findings carry no severity → None (honest, renders "—")
            assert row["severity"] is None


# ── Unavailable-status inputs degrade cleanly (no fabricated rows, no crash) ──────────

class TestUnavailableDegradesCleanly:
    def test_none_findings_yield_no_rows(self):
        co = {
            "ledger_recon_findings": None,
            "ledger_recon_status": {"level": "unavailable", "reason": "declared return boxes not supplied"},
            "not_included_findings": None,
            "not_included_status": {"level": "unavailable", "reason": "not supplied"},
        }
        assert serialize_ledger_recon_queue(co) == []

    def test_absent_keys_yield_no_rows(self):
        assert serialize_ledger_recon_queue({}) == []

    def test_only_signal_a_present(self):
        co = {"ledger_recon_findings": [_signal_a()]}
        out = serialize_ledger_recon_queue(co)
        assert len(out) == 1
        assert out[0]["error_code"] == "LEDGER_RECON"
