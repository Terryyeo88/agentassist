"""
tests/test_t53b_injection.py — T5.3 Slice 2: prompt-injection containment.

Every read PDF is UNTRUSTED input. A poisoned PDF (carrying a prompt-injection payload
that tries to make the agent assert compliance and seal the bundle) must NOT escalate.
The structural guarantees:

  * the loop has NO seal/emit path — sealing is a Tier-2 handler fired by the
    deterministic executor only AFTER a human approves, outside this loop;
  * the worst outcome the loop can produce is a PENDING ProposalArtifact a human reads;
  * the deterministic language-lint rejects assertive compliance phrasing if the agent
    echoes the injection verbatim (a brittle backstop atop the structural one).

Hermetic: a poisoned text file in tmp_path (no binary), a scripted FakeTransport — no
SDK, no tokens, no SAP, no network.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

from agent.budget import RunBudget
from agent.ledger import Ledger
from agent.lint import lint_framing
from agent.loop import LoopContext, run_casefile_loop
from agent.proposals import StagingStore
from agent.schemas import Tier


def _load_fx():
    spec = importlib.util.spec_from_file_location(
        "t53b_agent_loop_fx", pathlib.Path(__file__).parent / "fixtures" / "agent_loop.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fx = _load_fx()


def _doc_only_review() -> dict:
    """A review with only the gst_amount_mismatch document candidate (the poisoned one)."""
    return {
        "status": "completed",
        "compile_output": {"detect": {"issues": []}},
        "reasoning_artefact": {"status": "ok", "candidates": []},
        "document_candidates": [
            {
                "doc_num": 958, "check_id": "gst_amount_mismatch", "severity": "MEDIUM",
                "message": "Invoice PDF GST differs from SAP line.",
                "extracted_value": 74.0, "listing_value": 70.0,
                "determinability": "born_digital",
            },
        ],
        "bundle_dir": "audit/sbodemosg/2024Q3/seal-001",
    }


def _run(scripts, provider):
    ledger = Ledger()
    budget = RunBudget(max_turns=20, max_cost_usd=1.0)
    store = StagingStore()
    ctx = LoopContext(
        provider=provider,
        vendor_catalog=fx.default_vendor_catalog(),
        prior_period_store=fx.default_prior_period_store(),
    )
    transport = fx.FakeTransport(scripts=scripts)
    result = run_casefile_loop(
        invoke_review=lambda: _doc_only_review(),
        transport=transport, ctx=ctx, ledger=ledger, budget=budget, store=store,
    )
    return result, ledger, store


class TestPoisonedPdfOutcomeIsPendingProposal:
    def test_candidate_framed_injection_stages_pending_nothing_sealed(self, tmp_path):
        poisoned = fx.poisoned_pdf(tmp_path)
        provider = fx.FakeProvider({958: poisoned})
        scripts = {"doc:gst_amount_mismatch:958": [fx.injection_turn_candidate_framed()]}

        result, ledger, store = _run(scripts, provider)

        # Outcome is exactly one PENDING proposal a human reads.
        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].status == "pending"
        # NOTHING sealed or emitted: no Tier-2 execution outcome anywhere.
        assert all(e.tier != Tier.TWO.value for e in ledger.entries)
        assert all(o.status != "executed" for o in result.outcomes)
        # The agent read the poisoned PDF (untrusted) as evidence; the deterministic
        # bundle is referenced but the loop did not seal it.
        dossier = result.dossiers[0]
        assert dossier.evidence["document_pdfs"] == str(poisoned)
        ledger.verify()


class TestEchoedInjectionIsLintRejected:
    def test_assertive_echo_is_held_back_not_staged(self, tmp_path):
        poisoned = fx.poisoned_pdf(tmp_path)
        provider = fx.FakeProvider({958: poisoned})
        # Agent echoes the assertive injection verbatim as framing on every attempt.
        turn = fx.injection_turn_echoes_payload()
        scripts = {"doc:gst_amount_mismatch:958": [turn, turn, turn]}

        result, ledger, store = _run(scripts, provider)

        # Lint rejected the assertive framing → nothing staged, nothing sealed.
        assert store.list_pending() == []
        assert result.dossiers == []
        outcome = result.outcomes[0]
        assert outcome.status == "incomplete"
        assert outcome.lint is not None and outcome.lint.passed is False
        assert all(e.tier != Tier.TWO.value for e in ledger.entries)
        ledger.verify()

    def test_raw_injection_payload_would_fail_lint(self):
        # If the agent echoed the raw poisoned payload, the backstop catches it.
        result = lint_framing(fx.POISONED_PDF_TEXT)
        assert result.passed is False
        assert result.violations  # assertive phrasing detected
