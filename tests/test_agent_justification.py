"""
tests/test_agent_justification.py — T-3, T-4, T-5: justification gate behaviour.

No SDK, no SAP, no network. Ledger is an in-memory instance for isolation.
"""
from __future__ import annotations

import pytest

from agent.justification import validate_justification, JustificationResult
from agent.ledger import Ledger
from agent.schemas import Tier


# ---------------------------------------------------------------------------
# T-3  Tier-1 call with missing justification → blocked
# ---------------------------------------------------------------------------

class TestMissingJustification:
    def test_none_justification_blocked(self):
        result = validate_justification(None, tier=Tier.ONE)
        assert result.allowed is False
        assert result.blocked_reason is not None

    def test_tier_zero_needs_no_justification(self):
        # Tier 0 is autonomous — no justification required; always allowed
        result = validate_justification(None, tier=Tier.ZERO)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# T-4  Tier-1 call with trivial justification → blocked
#
# The check is a HEURISTIC backstop, not a semantic validator. It catches
# empty, whitespace-only, and below-minimum-length strings. It does NOT
# verify that the justification is logically sound — that is human review.
# ---------------------------------------------------------------------------

MIN_JUSTIFICATION_LENGTH = 20  # characters after stripping whitespace

class TestTrivialJustification:
    @pytest.mark.parametrize("trivial", [
        "",
        "   ",
        "\t\n",
        "ok",
        "yes",
        "do it",
        "a" * (MIN_JUSTIFICATION_LENGTH - 1),   # one char under minimum
    ])
    def test_trivial_justification_blocked(self, trivial):
        result = validate_justification(trivial, tier=Tier.ONE)
        assert result.allowed is False, (
            f"Expected {trivial!r} to be blocked as trivial"
        )

    def test_boundary_at_minimum_length_passes(self):
        just = "a" * MIN_JUSTIFICATION_LENGTH
        result = validate_justification(just, tier=Tier.ONE)
        assert result.allowed is True

    def test_substantive_justification_passes(self):
        just = "Running the review chain for sbodemosg Q3 2024 as part of audit evidence assembly."
        result = validate_justification(just, tier=Tier.ONE)
        assert result.allowed is True

    def test_blocked_reason_present_on_trivial(self):
        result = validate_justification("too short", tier=Tier.ONE)
        assert result.blocked_reason is not None
        assert len(result.blocked_reason) > 0


# ---------------------------------------------------------------------------
# T-5  Tier-1 call with valid justification → allowed AND ledger written BEFORE allow returned
# ---------------------------------------------------------------------------

class TestValidJustificationOrderedLedgerWrite:
    def test_allowed_and_ledger_appended(self):
        ledger = Ledger()
        justification = "Initiating run_review_chain for sbodemosg period 2024-07-01 to 2024-09-30."

        result = validate_justification(
            justification,
            tier=Tier.ONE,
            tool_name="run_review_chain",
            call_params={"client_id": "sbodemosg"},
            ledger=ledger,
        )

        assert result.allowed is True
        assert len(ledger.entries) == 1

    def test_ledger_written_before_allow_returned(self):
        """Ordering invariant: the ledger entry is appended atomically inside
        validate_justification; it must be present when the function returns
        'allowed'. We verify by checking the entry exists in the returned result
        state — there is no gap between 'ledger write' and 'return allowed'."""
        ledger = Ledger()
        justification = "Drafting E1 dossier section for doc 8002 — evidence: SEQ_GAP finding + supplier confirmation."

        result = validate_justification(
            justification,
            tier=Tier.ONE,
            tool_name="draft_report_section",
            call_params={"section": "E1"},
            ledger=ledger,
        )

        assert result.allowed is True
        # Entry must exist with outcome=allowed
        assert len(ledger.entries) == 1
        assert ledger.entries[0].outcome == "allowed"
        assert ledger.entries[0].justification == justification

    def test_blocked_call_also_written_to_ledger(self):
        ledger = Ledger()
        result = validate_justification(
            None,
            tier=Tier.ONE,
            tool_name="run_review_chain",
            call_params={},
            ledger=ledger,
        )

        assert result.allowed is False
        assert len(ledger.entries) == 1
        assert ledger.entries[0].outcome == "blocked"
