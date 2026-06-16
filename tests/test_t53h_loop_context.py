"""
tests/test_t53h_loop_context.py — the case-file loop over a REAL LoopContext (T5.3h).

Drives ``agent.loop.run_casefile_loop`` over the real ctx assembled by
``agent.loop_context.build_loop_context`` from the frozen SBODEMOSG extract:

  * a REAL ReviewResult via the offline-replay deterministic chain (SAP unreachable,
    no tokens) — ``tests/replay_shim.replay_review`` (chain-only, B1);
  * real findings via ``extract_findings`` (23 detect issues: E1 / E2 / NO_GST_REG);
  * a vendor catalog built from the S3 ``business-partners`` surface;
  * source-doc reads ABSENT (AbsentDocumentProvider) and prior-period store EMPTY — the
    honest SBODEMOSG degraded case.

A ``ScriptedLoopTransport`` (agent/eval/loop_runner.py) supplies the correct, CODE-DEFINED
evidence slots deterministically, so the loop runs end-to-end and produces real
``DossierArtifact``s and PENDING ``ProposalArtifact``s — asserted to conform to the frozen
contract. Hermetic: no live model, no live SAP, no tokens, no SDK.

NOT a live-model run (that is T5.3-V round-2) and NOT accuracy validation (T2.11).
"""
from __future__ import annotations

import dataclasses as dc
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.budget import RunBudget
from agent.dossier import DossierArtifact
from agent.ledger import Ledger
from agent.loop import FramingEvent, ResultEvent, ToolUseEvent, run_casefile_loop
from agent.loop_context import (
    FROZEN_EXTRACT,
    AbsentDocumentProvider,
    build_loop_context,
    build_vendor_catalog,
)
from agent.eval.loop_runner import ScriptedLoopTransport
from agent.proposals import ProposalArtifact, StagingStore, validate_proposal
from agent.read_tools import get_source_document, read_prior_period_treatment
from agent.schemas import Tier

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Load the shared replay harness from the sibling module (tests/ is not a package).
_shim_spec = importlib.util.spec_from_file_location(
    "t53h_replay_shim", _REPO_ROOT / "tests" / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)


# ---------------------------------------------------------------------------
# Scripted turns — deterministic, lint-clean candidate framing per finding
# ---------------------------------------------------------------------------

def _clean_framing(finding) -> FramingEvent:
    """A lint-clean candidate framing for *finding* (marker present, no verdict)."""
    payload = finding.payload or {}
    return FramingEvent(
        text=(
            f"Finding {finding.check_id} on doc {payload.get('doc_num')} appears to be a "
            f"candidate for reviewer attention; no compliance position is taken."
        )
    )


def _turn_for(finding) -> list:
    """Build one complete scripted turn for *finding*.

    NO_GST_REG needs the AGENT-GATHERED ``supplier_catalog`` slot, so the turn performs
    the ``read_vendor_gst_status`` read; E1/E2 are fully engine-seeded, so framing alone
    completes them. (``propose_action`` is driver-decided, so it is never scripted.)
    """
    events: list = []
    if finding.check_id == "NO_GST_REG":
        events.append(
            ToolUseEvent(
                tool_name="read_vendor_gst_status",
                tool_input={
                    "justification": "Gather supplier GST status for the case file.",
                    "card_name": (finding.payload or {}).get("card_name"),
                },
            )
        )
    events.append(_clean_framing(finding))
    events.append(ResultEvent(cost_usd=0.0))
    return events


def _build_scripts(findings) -> dict:
    """finding_id -> [turn, ...]; one complete turn per finding OCCURRENCE.

    Some findings share a finding_id (e.g. three E1 rows on doc 974). The loop processes
    each occurrence and pops one turn from the shared queue, so we append one complete
    turn per occurrence to keep every finding completable on its first attempt.
    """
    scripts: dict = {}
    for finding in findings:
        scripts.setdefault(finding.finding_id, []).append(_turn_for(finding))
    return scripts


# ---------------------------------------------------------------------------
# One real loop run, shared across assertions
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def loop_run():
    """Run the case-file loop ONCE over the real frozen-extract ctx; share the result."""
    period = replay_shim.period_from_manifest()
    review_result = replay_shim.replay_review(period)
    built = build_loop_context(period, review_result=review_result)

    ledger = Ledger()
    budget = RunBudget(max_turns=500, max_cost_usd=1000.0)
    store = StagingStore()
    transport = ScriptedLoopTransport(_build_scripts(built.findings), built.ctx, ledger)

    result = run_casefile_loop(
        invoke_review=lambda: built.review_result,
        transport=transport,
        ctx=built.ctx,
        ledger=ledger,
        budget=budget,
        store=store,
    )
    return SimpleNamespace(
        period=period, review_result=review_result, built=built,
        result=result, store=store, ledger=ledger,
    )


# ---------------------------------------------------------------------------
# Real findings from the frozen extract
# ---------------------------------------------------------------------------

def test_real_findings_extracted_from_frozen_extract(loop_run):
    """The injected ReviewResult yields the real frozen-extract detect findings."""
    findings = loop_run.built.findings
    assert len(findings) >= 23, f"expected the frozen detect issues, got {len(findings)}"
    check_ids = {f.check_id for f in findings}
    # The frozen extract surfaces E1 / E2 / NO_GST_REG deterministic detect issues.
    assert {"E1", "E2", "NO_GST_REG"} <= check_ids
    assert all(f.finding_type == "deterministic" for f in findings)
    assert all(f.source == "compile_output.detect" for f in findings)
    # >=1 NO_GST_REG finding carries a real supplier card_name.
    nog = [f for f in findings if f.check_id == "NO_GST_REG"]
    assert len(nog) >= 7
    assert all((f.payload or {}).get("card_name") for f in nog)


# ---------------------------------------------------------------------------
# Real-ctx loop acceptance: real dossiers + PENDING proposals, frozen contract
# ---------------------------------------------------------------------------

def test_loop_runs_end_to_end_over_real_ctx(loop_run):
    """The loop completes the review and stages real dossiers + PENDING proposals."""
    result = loop_run.result
    assert result.review_status == "completed"
    assert result.agent_layer_complete is True
    assert not result.budget_exceeded
    # Every finding has a registered CheckSpec → none skipped; all stage.
    statuses = {o.status for o in result.outcomes}
    assert statuses == {"staged"}, f"unexpected outcome statuses: {statuses}"
    assert len(result.dossiers) == len(result.outcomes) >= 23
    assert len(result.proposals) == len(result.dossiers)


def test_staged_dossiers_conform_to_frozen_contract(loop_run):
    """Each staged dossier is a real DossierArtifact with the frozen field set."""
    expected_fields = {
        "finding_id", "check_id", "finding_type", "evidence",
        "candidate_framing_text", "completeness", "inputs_hash",
    }
    for dossier in loop_run.result.dossiers:
        assert isinstance(dossier, DossierArtifact)
        assert {f.name for f in dc.fields(dossier)} == expected_fields
        assert dossier.completeness["satisfied"] is True
        assert dossier.inputs_hash.startswith("sha256:")
        assert isinstance(dossier.evidence, dict) and dossier.evidence
        assert dossier.candidate_framing_text  # lint-clean framing present


def test_staged_proposals_conform_to_frozen_contract(loop_run):
    """Each staged proposal is a PENDING Tier-2 ProposalArtifact (validates cleanly)."""
    pending = loop_run.store.list_pending()
    assert len(pending) == len(loop_run.result.proposals) >= 23
    for proposal in loop_run.result.proposals:
        assert isinstance(proposal, ProposalArtifact)
        validate_proposal(proposal)  # raises on any contract violation
        assert proposal.status == "pending"
        assert proposal.tier == Tier.TWO.value
        assert proposal.action == "attach_dossier"
        assert proposal.inputs_hash.startswith("sha256:")


def test_dossier_and_proposal_share_inputs_hash(loop_run):
    """The dossier and the proposal that stages it anchor to ONE inputs_hash."""
    for outcome in loop_run.result.outcomes:
        assert outcome.dossier is not None and outcome.proposal is not None
        assert outcome.dossier.inputs_hash == outcome.proposal.inputs_hash


# ---------------------------------------------------------------------------
# Vendor catalog from the S3 business-partners surface (real data)
# ---------------------------------------------------------------------------

def test_vendor_catalog_built_from_business_partners():
    """The catalog is keyed by CardName and surfaces only the GST-registration fields."""
    catalog = build_vendor_catalog(FROZEN_EXTRACT)
    # A NO_GST_REG supplier: present, no GST registration number (FederalTaxID null).
    assert catalog["Acme Associates"] == {"gst_registered": False, "gst_reg_no": None}
    # A GST-registered supplier: FederalTaxID present.
    assert catalog["Sea Corp"] == {"gst_registered": True, "gst_reg_no": "SK98467789"}
    # Minimal surface: ONLY the two GST fields (no other BP fields / secrets leaked).
    for record in catalog.values():
        assert set(record) == {"gst_registered", "gst_reg_no"}


def test_no_gst_reg_dossiers_carry_real_supplier_catalog(loop_run):
    """NO_GST_REG dossiers gathered the real (absent-GST) supplier_catalog evidence."""
    nog_dossiers = [d for d in loop_run.result.dossiers if d.check_id == "NO_GST_REG"]
    assert len(nog_dossiers) >= 7
    for dossier in nog_dossiers:
        rec = dossier.evidence.get("supplier_catalog")
        assert isinstance(rec, dict) and rec.get("found") is True
        # The frozen NO_GST_REG suppliers are all GST-unregistered in the BP surface.
        assert rec.get("gst_registered") is False
        assert rec.get("gst_reg_no") is None
        # purchase_invoices is the engine-seeded slot for NO_GST_REG.
        assert dossier.evidence.get("purchase_invoices") is not None


# ---------------------------------------------------------------------------
# Honest degraded case: source-doc + prior-period reads return ABSENT
# ---------------------------------------------------------------------------

def test_source_document_reads_are_absent(loop_run):
    """SBODEMOSG ships no attachments — the source-doc provider returns absent."""
    provider = loop_run.built.ctx.provider
    assert isinstance(provider, AbsentDocumentProvider)
    # Any doc_num (e.g. a real NO_GST_REG doc) resolves to no PDF.
    assert get_source_document(provider, 605) is None
    assert get_source_document(provider, 974) is None
    assert provider.get_document(605) is None


def test_prior_period_reads_are_absent(loop_run):
    """No prior-period record is held — the prior-period read returns found=False."""
    store = loop_run.built.ctx.prior_period_store
    assert store == {}
    rec = read_prior_period_treatment(store, "NO_GST_REG:Acme Associates")
    assert rec == {"key": "NO_GST_REG:Acme Associates", "found": False,
                   "treatment": None, "record": None}


def test_review_result_document_and_reasoning_absent(loop_run):
    """Chain-only replay (B1): no document candidates, no reasoning artefact."""
    rr = loop_run.review_result
    assert rr.status == "completed"
    assert rr.document_candidates is None
    assert rr.reasoning_artefact is None


# ---------------------------------------------------------------------------
# Invariant: agent/loop_context imports no SDK / anthropic (subprocess-clean)
# ---------------------------------------------------------------------------

def test_loop_context_import_is_sdk_free():
    """Importing agent.loop_context loads neither claude_agent_sdk nor anthropic."""
    code = (
        "import sys, agent.loop_context\n"
        "assert 'claude_agent_sdk' not in sys.modules, 'claude_agent_sdk loaded'\n"
        "assert 'anthropic' not in sys.modules, 'anthropic loaded'\n"
        "print('SDK-FREE-OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(_REPO_ROOT)
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "SDK-FREE-OK" in proc.stdout
