"""
agent/eval/loop_scenarios.py — Scripted loop scenarios for the loop-quality basket.

Each scenario drives the real Slice-2 case-file loop over a ScriptedLoopTransport
(see agent.eval.loop_runner). The library exercises the two loop-quality signals:

  * golden_loop_scenario          — both findings gather their evidence and frame
    them as candidates: completeness = 1.0, lint = 1.0 (the headline basket).
  * incomplete_loop_scenario      — one finding never gathers its agent-gathered
    slot, so its dossier never reaches completeness: dossier_completeness_rate < 1.0
    in a controlled case (the other finding still completes).
  * assertive_framing_loop_scenario — one finding GATHERS its evidence (completeness
    satisfied) but voices an assertive compliance verdict, which the language-lint
    must catch: language_lint_pass_rate < 1.0 (completeness stays 1.0).

The canned review carries one deterministic (NO_GST_REG) and one probabilistic
(gst_amount_mismatch) finding, mirroring the engine's three finding surfaces.

Zero SDK import. Pure data builders.
"""
from __future__ import annotations

from agent.eval.loop_runner import LoopScenario
from agent.loop import FramingEvent, ResultEvent, ToolUseEvent

# Finding ids as produced by agent.dossier.extract_findings for the canned review.
_FID_NO_GST = "detect:NO_GST_REG:605"
_FID_DOC = "doc:gst_amount_mismatch:958"

_GST_JUST = (
    "Gathering supplier GST registration status to support the NO_GST_REG case file "
    "for doc 605 pending reviewer attention."
)
_DOC_JUST = (
    "Reading the source invoice PDF to support the gst_amount_mismatch case file for "
    "doc 958 pending reviewer attention."
)

# Clean candidate framing (passes agent.lint.lint_framing).
_CLEAN_NO_GST = (
    "Supplier GST registration appears absent; doc 605 is a candidate for reviewer "
    "attention on input-tax claimability."
)
_CLEAN_DOC = (
    "The invoice PDF GST amount appears to differ from the SAP line; flagged as a "
    "candidate for review."
)
# Assertive verdict the lint REJECTS (no candidate marker + assertive phrasing).
_ASSERTIVE_NO_GST = "This invoice is compliant and the supplier violates nothing."


def _canned_review() -> dict:
    """A ReviewResult with one deterministic (NO_GST_REG) + one probabilistic finding."""
    return {
        "status": "completed",
        "compile_output": {
            "detect": {
                "issues": [
                    {
                        "severity": "HIGH",
                        "error_code": "NO_GST_REG",
                        "doc_num": 605,
                        "doc_date": "2024-07-15",
                        "card_name": "Mama Shop Supplies",
                        "description": "Input tax claimed from supplier with no GST reg no.",
                        "recommendation": "Review whether input tax is claimable.",
                    },
                ],
            },
        },
        "reasoning_artefact": {"status": "ok", "candidates": []},
        "document_candidates": [
            {
                "doc_num": 958,
                "check_id": "gst_amount_mismatch",
                "severity": "MEDIUM",
                "message": "Invoice PDF GST (74.00) differs from SAP line (70.00).",
                "extracted_value": 74.0,
                "listing_value": 70.0,
                "determinability": "born_digital",
            },
        ],
        "report_pdf_path": "exploration-notes/t1.4-reports/sbodemosg.pdf",
        "bundle_dir": "audit/sbodemosg/2024Q3/seal-001",
        "gate_failure": None,
    }


def _vendor_catalog() -> dict:
    return {
        "Mama Shop Supplies": {"gst_registered": False, "gst_reg_no": None},
        "Acme Pte Ltd": {"gst_registered": True, "gst_reg_no": "200012345A"},
    }


def _prior_period_store() -> dict:
    return {"NO_GST_REG:Mama Shop Supplies": {"treatment": "disallowed", "period": "2024Q2"}}


def _provider_docs() -> dict:
    return {958: "/tmp/INV-958.pdf"}


# ---------------------------------------------------------------------------
# Scripted turns
# ---------------------------------------------------------------------------

def _gather_no_gst() -> ToolUseEvent:
    return ToolUseEvent(
        tool_name="read_vendor_gst_status",
        tool_input={
            "justification": _GST_JUST,
            "card_name": "Mama Shop Supplies",
            "evidence_slot": "supplier_catalog",
        },
    )


def _gather_doc() -> ToolUseEvent:
    return ToolUseEvent(
        tool_name="get_source_document",
        tool_input={
            "justification": _DOC_JUST,
            "doc_num": 958,
            "evidence_slot": "document_pdfs",
        },
    )


def _complete_no_gst_turn() -> list:
    # Arch A: the model gathers its read + frames; the DRIVER decides staging.
    return [_gather_no_gst(), FramingEvent(text=_CLEAN_NO_GST), ResultEvent(cost_usd=0.012)]


def _complete_doc_turn() -> list:
    return [_gather_doc(), FramingEvent(text=_CLEAN_DOC), ResultEvent(cost_usd=0.009)]


def _never_gather_no_gst_turn() -> list:
    """Frames but never reads supplier_catalog → completeness fails."""
    return [FramingEvent(text=_CLEAN_NO_GST), ResultEvent(cost_usd=0.003)]


def _assertive_no_gst_turn() -> list:
    """Gathers evidence (completeness satisfied) but voices an assertive verdict →
    the language-lint rejects it, so the dossier is held back from staging."""
    return [_gather_no_gst(), FramingEvent(text=_ASSERTIVE_NO_GST), ResultEvent(cost_usd=0.011)]


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def golden_loop_scenario() -> LoopScenario:
    """Both findings gather evidence + frame as candidates → both staged.

    dossier_completeness_rate = 1.0, language_lint_pass_rate = 1.0.
    """
    return LoopScenario(
        name="loop_golden_complete",
        description="Both findings gather evidence and frame as candidates → all staged.",
        review_result=_canned_review(),
        scripts={
            _FID_NO_GST: [_complete_no_gst_turn()],
            _FID_DOC: [_complete_doc_turn()],
        },
        provider_docs=_provider_docs(),
        vendor_catalog=_vendor_catalog(),
        prior_period_store=_prior_period_store(),
        max_attempts_per_finding=3,
    )


def incomplete_loop_scenario() -> LoopScenario:
    """One finding (NO_GST_REG) never gathers supplier_catalog → never completes.

    The doc finding still completes, so dossier_completeness_rate is a controlled
    0.5 (< 1.0). Framing stays clean so the lint metric is isolated at 1.0.
    """
    return LoopScenario(
        name="loop_deliberately_incomplete",
        description="NO_GST_REG never gathers its agent slot → dossier stays incomplete.",
        review_result=_canned_review(),
        scripts={
            # Re-supply an always-incomplete turn for every allowed attempt.
            _FID_NO_GST: [_never_gather_no_gst_turn() for _ in range(3)],
            _FID_DOC: [_complete_doc_turn()],
        },
        provider_docs=_provider_docs(),
        vendor_catalog=_vendor_catalog(),
        prior_period_store=_prior_period_store(),
        max_attempts_per_finding=3,
    )


def assertive_framing_loop_scenario() -> LoopScenario:
    """One finding (NO_GST_REG) frames an assertive verdict the lint must catch.

    Evidence IS gathered (completeness satisfied), so dossier_completeness_rate
    stays 1.0; only language_lint_pass_rate drops to a controlled 0.5 (< 1.0).
    """
    return LoopScenario(
        name="loop_assertive_framing",
        description="NO_GST_REG voices an assertive verdict → language-lint rejects it.",
        review_result=_canned_review(),
        scripts={
            _FID_NO_GST: [_assertive_no_gst_turn() for _ in range(3)],
            _FID_DOC: [_complete_doc_turn()],
        },
        provider_docs=_provider_docs(),
        vendor_catalog=_vendor_catalog(),
        prior_period_store=_prior_period_store(),
        max_attempts_per_finding=3,
    )


def build_loop_basket() -> list[LoopScenario]:
    """The headline loop-quality basket: the golden path (both metrics → 1.0).

    The deliberately-incomplete and assertive-framing scenarios are NOT in the
    headline basket (they would, by design, drive the rates below target); they are
    exercised directly in the T5.7b metric tests to prove each metric discriminates.
    """
    return [golden_loop_scenario()]
