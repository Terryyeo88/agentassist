"""
tests/test_agent_ledger.py — T-7: hash-chain integrity.

No SDK, no SAP, no network. Fully hermetic; uses only agent.ledger.
"""
from __future__ import annotations

import pytest

from agent.ledger import Ledger, LedgerVerificationError
from agent.schemas import Tier


def _append_n(ledger: Ledger, n: int) -> None:
    for i in range(n):
        ledger.append(
            tool_name="read_sap_invoices",
            tier=Tier.ZERO,
            justification=None,
            call_params={"iteration": i},
            outcome="allowed",
            blocked_reason=None,
        )


# ---------------------------------------------------------------------------
# T-7  Hash chain: append N entries, verify() passes; mutate one, verify() FAILS
# ---------------------------------------------------------------------------

class TestLedgerHashChain:
    def test_empty_ledger_verifies(self):
        ledger = Ledger()
        ledger.verify()  # must not raise

    def test_single_entry_verifies(self):
        ledger = Ledger()
        _append_n(ledger, 1)
        ledger.verify()

    def test_five_entries_verify(self):
        ledger = Ledger()
        _append_n(ledger, 5)
        ledger.verify()

    def test_twenty_entries_verify(self):
        ledger = Ledger()
        _append_n(ledger, 20)
        ledger.verify()

    def test_mutate_first_entry_justification_fails_verify(self):
        ledger = Ledger()
        _append_n(ledger, 5)
        # Tamper: change justification on entry 0
        ledger.entries[0].justification = "TAMPERED"
        with pytest.raises(LedgerVerificationError):
            ledger.verify()

    def test_mutate_middle_entry_outcome_fails_verify(self):
        ledger = Ledger()
        _append_n(ledger, 5)
        ledger.entries[2].outcome = "TAMPERED"
        with pytest.raises(LedgerVerificationError):
            ledger.verify()

    def test_mutate_last_entry_fails_verify(self):
        ledger = Ledger()
        _append_n(ledger, 5)
        ledger.entries[-1].tool_name = "tampered_tool"
        with pytest.raises(LedgerVerificationError):
            ledger.verify()

    def test_delete_middle_entry_fails_verify(self):
        ledger = Ledger()
        _append_n(ledger, 5)
        del ledger.entries[2]
        with pytest.raises(LedgerVerificationError):
            ledger.verify()

    def test_hash_chain_is_sequential(self):
        """Each entry's prev_hash must equal the prior entry's entry_hash."""
        ledger = Ledger()
        _append_n(ledger, 4)
        for i in range(1, len(ledger.entries)):
            assert ledger.entries[i].prev_hash == ledger.entries[i - 1].entry_hash, (
                f"Chain broken between entry {i-1} and {i}"
            )

    def test_genesis_entry_prev_hash_is_zero_sentinel(self):
        ledger = Ledger()
        _append_n(ledger, 1)
        assert ledger.entries[0].prev_hash == "sha256:" + "0" * 64

    def test_tier_one_entry_with_justification_verifies(self):
        ledger = Ledger()
        ledger.append(
            tool_name="run_review_chain",
            tier=Tier.ONE,
            justification="Running full audit chain for Q3 2024 evidence assembly.",
            call_params={"client_id": "sbodemosg"},
            outcome="allowed",
            blocked_reason=None,
        )
        ledger.verify()

    def test_blocked_entry_verifies(self):
        ledger = Ledger()
        ledger.append(
            tool_name="run_review_chain",
            tier=Tier.ONE,
            justification=None,
            call_params={},
            outcome="blocked",
            blocked_reason="justification missing",
        )
        ledger.verify()
