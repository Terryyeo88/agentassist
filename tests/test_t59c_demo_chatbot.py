"""tests/test_t59c_demo_chatbot.py — T5.9c demo command bar + routing-accuracy eval.

ALL HERMETIC via the SCRIPTED classifier backend — no live model, no tokens. Covers the
acceptance cases (a)-(f) plus the import-scan guards (ui/ no-anthropic, eval-harness
anthropic-free at import, curated fixture anthropic-free) and the buttons fallback.

  (a) a curated Classified utterance → routes the command bar to the mapped section;
  (b) a missing-slot utterance → inline clarify, NEVER a guessed client/period;
  (c) an out-of-scope utterance → polite message + buttons fallback, never a tool;
  (d) an injection utterance — incl. a HOSTILE backend output (raw tool name) — is
      contained (→ OutOfScope), command bar shows the polite message + buttons, no action;
  (e) the buttons fallback dispatches the four intents directly (no classifier needed);
  (f) the scripted-path eval scores 100% on the curated set — SANITY ONLY.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent.intent import INTENT_MENU, NeedsClarification
from agent.intent_classifier import (
    IntentClassifier,
    RawClassification,
    ScriptedClassifierBackend,
    Verdict,
)
from agent.intent_curated import (
    CURATED_UTTERANCES,
    Cell,
    build_scripted_classifier,
    result_matches,
)
from ui.views.review import (
    INTENT_SECTION,
    Clarify,
    OutOfScopeReply,
    RouteToSection,
    _OUT_OF_SCOPE_MESSAGE,
    handle_button,
    handle_command,
    route_intent,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _one(cell: str):
    for cu in CURATED_UTTERANCES:
        if cu.cell == cell:
            return cu
    raise AssertionError(f"no curated utterance for cell {cell!r}")


# ── (a) Classified utterance → routes to the mapped section ──────────────────────────

def test_classified_utterance_routes_to_mapped_section():
    classifier = build_scripted_classifier()
    cu = _one(Cell.SHOW_LEDGER)
    outcome = handle_command(cu.utterance, classifier)
    assert isinstance(outcome, RouteToSection)
    assert outcome.intent == "SHOW_LEDGER"
    assert outcome.section == "Justification ledger"
    assert outcome.section == INTENT_SECTION["SHOW_LEDGER"]
    # The recognised client slot is surfaced, but the demo does NOT execute the read.
    assert outcome.params == {"client_id": "Acme"}


def test_all_four_intents_map_to_distinct_sections():
    sections = {route_intent(i) for i in INTENT_SECTION}
    assert sections == {
        "Review queue", "Justification ledger", "PENDING proposals", "Adjudication panel",
    }
    # route_intent only ever yields a menu intent's section (or the safe default).
    assert route_intent("RUN_REVIEW") == "Review queue"


# ── (b) missing-slot utterance → clarify, never a guessed identity ───────────────────

def test_missing_slot_clarifies_and_never_guesses():
    classifier = build_scripted_classifier()
    cu = _one(Cell.CLARIFY)  # "Run a review" — no client/period
    outcome = handle_command(cu.utterance, classifier)
    assert isinstance(outcome, Clarify)
    assert outcome.intent == "RUN_REVIEW"
    assert outcome.missing_params == ("client_id", "period")
    # NEVER a route (which would imply a guessed/defaulted client/period).
    assert not isinstance(outcome, RouteToSection)


# ── (c) out-of-scope → polite message + buttons fallback, never a tool ───────────────

def test_out_of_scope_is_polite_and_offers_buttons():
    classifier = build_scripted_classifier()
    cu = _one(Cell.OUT_OF_SCOPE)
    outcome = handle_command(cu.utterance, classifier)
    assert isinstance(outcome, OutOfScopeReply)
    assert outcome.message == _OUT_OF_SCOPE_MESSAGE
    # No route, no intent, no params — never a tool / action.
    assert not isinstance(outcome, RouteToSection)


def test_unscripted_utterance_falls_back_to_out_of_scope():
    # An utterance NOT in the curated set is never silently a tool — scripted default
    # is OUT_OF_SCOPE, so the command bar replies politely.
    classifier = build_scripted_classifier()
    outcome = handle_command("delete all the invoices right now", classifier)
    assert isinstance(outcome, OutOfScopeReply)


# ── (d) injection contained — incl. a HOSTILE backend output ─────────────────────────

def test_injection_model_contained_to_out_of_scope():
    classifier = build_scripted_classifier()
    # The benign-canned injection (model declined → out_of_scope).
    cu = next(
        c for c in CURATED_UTTERANCES
        if c.cell == Cell.INJECTION and c.raw.verdict == Verdict.OUT_OF_SCOPE
    )
    outcome = handle_command(cu.utterance, classifier)
    assert isinstance(outcome, OutOfScopeReply)


def test_hostile_backend_output_is_contained_by_the_boundary():
    """A COMPROMISED backend claims CLASSIFIED with a raw TOOL NAME as the 'intent'.

    The ⊆-menu boundary must reject it to OutOfScope, so the command bar shows the
    polite message + buttons and triggers NO action — classify-never-obey holds in the
    demo path even when the BACKEND is adversarial (not just a benign canned answer).
    """
    # The curated hostile case (intent='emit_final_pdf', a raw registry tool name).
    cu = next(
        c for c in CURATED_UTTERANCES
        if c.cell == Cell.INJECTION and c.raw.verdict == Verdict.CLASSIFIED
    )
    assert cu.raw.intent not in INTENT_MENU  # the raw label is genuinely off-menu
    classifier = build_scripted_classifier()
    outcome = handle_command(cu.utterance, classifier)
    assert isinstance(outcome, OutOfScopeReply)  # contained — no route, no action
    assert not isinstance(outcome, RouteToSection)

    # Belt-and-braces: even an INLINE hostile backend (any off-menu tool name) is
    # contained — the boundary, not the demo, enforces this.
    hostile = IntentClassifier(
        ScriptedClassifierBackend(
            RawClassification(verdict=Verdict.CLASSIFIED, intent="run_review_chain_RAW",
                              params={"client_id": "ALL"})
        )
    )
    assert isinstance(handle_command("anything", hostile), OutOfScopeReply)


# ── (e) buttons fallback dispatches the four intents directly (no classifier) ────────

def test_buttons_fallback_dispatches_each_intent_directly():
    for intent, section in INTENT_SECTION.items():
        outcome = handle_button(intent)
        assert isinstance(outcome, RouteToSection)
        assert outcome.intent == intent
        assert outcome.section == section
        # Buttons skip the NL step and bind no params (intent → section only).
        assert outcome.params == {}


# ── (f) scripted-path eval scores 100% — SANITY ONLY ─────────────────────────────────

def test_scripted_eval_is_100_percent_sanity():
    from agent.eval.intent_routing import run_hermetic

    basket = run_hermetic()
    assert basket.total == len(CURATED_UTTERANCES)
    assert basket.overall_accuracy == 1.0  # harness ⟷ labels agree (NOT an accuracy claim)
    # Every basket cell that has data is fully satisfied on the scripted path.
    for acc in basket.per_intent_accuracy.values():
        assert acc == 1.0
    assert basket.clarify_recall == 1.0
    assert basket.out_of_scope_recall == 1.0
    assert basket.injection_containment == 1.0


def test_curated_scripted_path_matches_every_expected_label():
    classifier = build_scripted_classifier()
    for cu in CURATED_UTTERANCES:
        got = classifier.classify(cu.utterance, INTENT_MENU)
        assert result_matches(got, cu.expected), (cu.cell, cu.utterance)


def test_eval_evidence_saved_before_scoring(tmp_path):
    """The eval saves raw per-utterance outputs (evidence) as JSON before scoring."""
    from agent.eval.intent_routing import evaluate, save_evidence
    from agent.intent_curated import build_scripted_classifier as _mk

    scored = evaluate(_mk())
    path = save_evidence(scored, backend="scripted", out_dir=tmp_path)
    assert path.exists()
    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["raw"]) == len(CURATED_UTTERANCES)
    assert "smoke/repertoire" in payload["curated_note"]


# ── import-scan guards (NAMED) ───────────────────────────────────────────────────────

_REVIEW_IMPORT_SNIPPET = """
import sys
import ui.views.review  # noqa: F401  (the command bar lives here)
# review.py legitimately imports streamlit; the guard is NO anthropic / SDK.
banned = [m for m in ("anthropic", "claude_agent_sdk") if m in sys.modules]
print("BANNED:" + ",".join(banned))
"""


def test_ui_review_import_pulls_no_anthropic():
    """T5.8 guard extended: importing ui.views.review pulls NO anthropic / SDK."""
    proc = subprocess.run(
        [sys.executable, "-c", _REVIEW_IMPORT_SNIPPET],
        cwd=str(_REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"import failed: {proc.stderr}"
    out = proc.stdout.strip().splitlines()[-1]
    assert out == "BANNED:", f"ui.views.review pulled banned modules: {out}"


# NOTE: importing agent.eval.intent_routing triggers agent/eval/__init__.py, which
# already pulls claude_agent_sdk (the pre-existing T5.7a cage harness). The T5.9c named
# check is ANTHROPIC-free — the live AnthropicClassifierBackend import must stay deferred
# — so this guard bans anthropic only. The fixture is independently anthropic-free.
_EVAL_IMPORT_SNIPPET = """
import sys
import agent.eval.intent_routing  # noqa: F401
import agent.intent_curated  # noqa: F401
banned = [m for m in ("anthropic",) if m in sys.modules]
print("BANNED:" + ",".join(banned))
"""


def test_eval_harness_and_fixture_import_pull_no_anthropic():
    """The eval harness + curated fixture are anthropic-free at IMPORT.

    The live backend's anthropic import is deferred inside AnthropicClassifierBackend
    (and imported locally inside run_live), so merely importing the harness is clean.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _EVAL_IMPORT_SNIPPET],
        cwd=str(_REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"import failed: {proc.stderr}"
    out = proc.stdout.strip().splitlines()[-1]
    assert out == "BANNED:", f"eval/fixture pulled banned modules: {out}"
