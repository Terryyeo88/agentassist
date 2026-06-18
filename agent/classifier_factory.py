"""agent/classifier_factory.py — T5.9e: env-gated classifier-backend factory (PURE).

One small, surface-agnostic chooser over the EXISTING two-backend seam in
``agent.intent_classifier``. It selects which ``ClassifierBackend`` an intent surface
uses, by environment:

    AGENT_UI_CLASSIFIER unset / "" / "scripted"  -> ScriptedClassifierBackend(curated)
    AGENT_UI_CLASSIFIER == "live"                -> AnthropicClassifierBackend(...)

NO surface wiring lives here. The production surface is React, so this factory is
consumed by the React API's ``POST /command`` handler (Lane C2), NOT by Streamlit and
NOT by this slice. Building only the factory + hermetic tests keeps Lane B's file set
disjoint from A and C1.

Why a factory at all (rather than a surface choosing a backend inline): so the
selection rule — and especially the "no silent fallback hiding a misconfig" rule —
is in ONE pure, hermetically-testable place, identical for every surface.

INVARIANTS this slice preserves:
  * Default is SCRIPTED — zero tokens, NO ``anthropic`` import. Importing this module
    (and constructing the scripted backend) never loads the SDK.
  * The ``anthropic`` import stays LAZY/CONFINED to ``AnthropicClassifierBackend``
    (deferred inside its call site). This factory only NAMES that class; selecting it
    does not import the SDK — the import happens when the live backend actually calls
    the model.
  * classify-never-obey is UNCHANGED: every backend (scripted or live) is contained by
    the same pure ``_enforce_menu_boundary`` in ``agent.intent_classifier``. This
    factory adds NO new path out of the menu.
  * ``orchestrator/`` + ``engine/`` are untouched. ``agent/`` is permitted the SDK
    lazily (``docs/merge-gates.md`` Gate a — the boundary is at ``orchestrator/``).

MISCONFIG IS LOUD: ``AGENT_UI_CLASSIFIER=live`` without ``ANTHROPIC_API_KEY`` raises
``ClassifierConfigError`` rather than silently falling back to scripted — a silent
fallback would hide a broken live deployment behind canned answers. An unrecognised
non-empty mode likewise raises (a typo'd ``"liv"`` must not silently route scripted).

Status: built + hermetically tested; NOT wired to any surface (C2). The live backend
is SELECTABLE here but its routing accuracy is UNMEASURED — that is the opt-in
``agent.eval.intent_routing`` run (ROUTING accuracy only, AUTHOR-CONSTRUCTED + SMALL).
"Selectable live" is NOT an accuracy claim.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional, Union

from agent.intent import IntentSpec
from agent.intent_classifier import (
    AnthropicClassifierBackend,
    ClassifierBackend,
    MessagesCreate,
    RawClassification,
    ScriptEntry,
    ScriptedClassifierBackend,
)

__all__ = [
    "CLASSIFIER_ENV_VAR",
    "API_KEY_ENV_VAR",
    "MODE_SCRIPTED",
    "MODE_LIVE",
    "ClassifierConfigError",
    "make_classifier_backend",
]

#: The env var that selects the backend. Absent/blank/"scripted" -> scripted (default).
CLASSIFIER_ENV_VAR: str = "AGENT_UI_CLASSIFIER"
#: The credential the live backend needs; its presence is required under live mode so a
#: misconfig surfaces here, not as a 401 deep inside a model call.
API_KEY_ENV_VAR: str = "ANTHROPIC_API_KEY"

MODE_SCRIPTED: str = "scripted"
MODE_LIVE: str = "live"

#: The curated script accepted by ``ScriptedClassifierBackend`` (single label, a
#: {utterance: entry} mapping, or a callable) — re-used verbatim, not re-modelled.
CuratedScript = Union[
    RawClassification,
    Mapping[str, ScriptEntry],
    Callable[[str, Mapping[str, IntentSpec]], RawClassification],
]


class ClassifierConfigError(RuntimeError):
    """Raised for a misconfigured backend selection (loud, never a silent fallback)."""


def make_classifier_backend(
    env: Mapping[str, str],
    *,
    curated: CuratedScript,
    messages_create: Optional[MessagesCreate] = None,
) -> ClassifierBackend:
    """Select a ``ClassifierBackend`` by environment. PURE; no surface wiring.

    Args:
        env: The environment to read (e.g. ``os.environ`` in production, or a plain
            ``dict`` in tests). Read-only — the factory never mutates it.
        curated: The script for the SCRIPTED backend (default path). Passed straight
            to ``ScriptedClassifierBackend`` so the scripted answers are owned by the
            caller, not this factory.
        messages_create: Optional ``messages.create``-shaped callable injected into the
            LIVE backend for HERMETIC exercise (zero tokens). In production this is
            None and the live backend lazily builds a real ``anthropic`` client at call
            time. Ignored entirely on the scripted path.

    Returns:
        ``ScriptedClassifierBackend(curated)`` by default (no tokens, no ``anthropic``
        import), or ``AnthropicClassifierBackend(...)`` when ``AGENT_UI_CLASSIFIER`` is
        ``"live"`` AND ``ANTHROPIC_API_KEY`` is present.

    Raises:
        ClassifierConfigError: ``"live"`` selected but ``ANTHROPIC_API_KEY`` is absent
            (no silent fallback that would hide a broken live deployment), or the env
            var holds an unrecognised non-empty mode (a typo must not route scripted).
    """
    mode = (env.get(CLASSIFIER_ENV_VAR) or "").strip().lower()

    if mode in ("", MODE_SCRIPTED):
        # DEFAULT: canned, zero-token. No anthropic import is triggered by this path.
        return ScriptedClassifierBackend(curated)

    if mode == MODE_LIVE:
        if not (env.get(API_KEY_ENV_VAR) or "").strip():
            raise ClassifierConfigError(
                f"{CLASSIFIER_ENV_VAR}={MODE_LIVE!r} requires {API_KEY_ENV_VAR} to be "
                "set; refusing to silently fall back to the scripted backend (that "
                "would hide a misconfigured live deployment behind canned answers)."
            )
        # The anthropic import stays DEFERRED inside AnthropicClassifierBackend's call
        # site — naming/constructing the class here does NOT import the SDK.
        return AnthropicClassifierBackend(messages_create=messages_create)

    raise ClassifierConfigError(
        f"unrecognised {CLASSIFIER_ENV_VAR}={mode!r}; expected one of "
        f"{('', MODE_SCRIPTED, MODE_LIVE)} (a typo must not silently route scripted)."
    )
