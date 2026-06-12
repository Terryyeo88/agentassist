"""
agent/justification.py — Justification gate for Tier-1 tool calls.

Public API:
    validate_justification(text, tier, *, tool_name, call_params, ledger) -> JustificationResult
    JustificationResult  — dataclass carrying allowed/blocked_reason

The gate is a HEURISTIC BACKSTOP, not a semantic validator. It catches missing,
whitespace-only, and below-minimum-length strings. It does NOT verify that the
justification is logically sound — that is the reviewer's responsibility. A
compliant-sounding justification that is actually wrong passes the gate; the
ledger records it verbatim for the reviewer to assess.

Minimum length: 20 characters (after stripping whitespace). This is a
mechanical floor, not a quality threshold.

Tier 0 calls are autonomous — no justification required; always allowed.
Tier 1 calls require a non-trivial justification.
Tier 2 calls never reach this gate (proposals use agent.proposals).

The ledger (when supplied) is written BEFORE the allowed/blocked decision is
returned, satisfying the T-5 ordering invariant.

Zero anthropic import. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from agent.schemas import Tier

_MIN_JUSTIFICATION_LENGTH: int = 20  # characters after stripping


@dataclass
class JustificationResult:
    """Result of a justification gate check.

    Attributes:
        allowed:        True if the call is permitted to proceed.
        blocked_reason: Human-readable explanation when allowed=False; None otherwise.
    """
    allowed: bool
    blocked_reason: Optional[str]


def _is_trivial(text: Optional[str]) -> tuple[bool, str]:
    """Return (is_trivial, reason) for a justification string.

    A string is trivial if it is None, empty, whitespace-only, or shorter than
    _MIN_JUSTIFICATION_LENGTH characters after stripping.
    """
    if text is None:
        return True, "justification is missing (None)"
    stripped = text.strip()
    if not stripped:
        return True, "justification is empty or whitespace-only"
    if len(stripped) < _MIN_JUSTIFICATION_LENGTH:
        return True, (
            f"justification too short ({len(stripped)} chars after stripping; "
            f"minimum is {_MIN_JUSTIFICATION_LENGTH}). "
            "Heuristic backstop — provide a substantive reason."
        )
    return False, ""


def validate_justification(
    text: Optional[str],
    tier: Tier,
    *,
    tool_name: str = "unknown",
    call_params: Optional[dict] = None,
    ledger=None,  # agent.ledger.Ledger | None; typed as Any to avoid circular import
) -> JustificationResult:
    """Gate a Tier-1 tool call on the quality of its justification.

    For Tier 0: always allowed, no justification required.
    For Tier 1: blocked if justification is missing or trivial (heuristic check).

    The ledger entry (allowed or blocked) is appended BEFORE this function
    returns, satisfying the ordering invariant: the justification is on the
    ledger before the caller learns the outcome.

    Args:
        text:        The justification string supplied by the agent.
        tier:        Tier of the tool being called.
        tool_name:   Tool name for the ledger entry.
        call_params: Sanitised call parameters for the ledger entry.
        ledger:      Optional Ledger instance. When supplied, an entry is
                     appended before returning. When None, the gate still
                     returns the allow/block decision; no ledger write occurs.

    Returns:
        JustificationResult with allowed=True or False + reason.
    """
    params = call_params or {}

    if tier == Tier.ZERO:
        result = JustificationResult(allowed=True, blocked_reason=None)
        if ledger is not None:
            ledger.append(
                tool_name=tool_name,
                tier=tier,
                justification=text,
                call_params=params,
                outcome="allowed",
                blocked_reason=None,
            )
        return result

    # Tier 1 — justification required
    trivial, reason = _is_trivial(text)
    if trivial:
        result = JustificationResult(allowed=False, blocked_reason=reason)
        if ledger is not None:
            ledger.append(
                tool_name=tool_name,
                tier=tier,
                justification=text,
                call_params=params,
                outcome="blocked",
                blocked_reason=reason,
            )
        return result

    result = JustificationResult(allowed=True, blocked_reason=None)
    if ledger is not None:
        ledger.append(
            tool_name=tool_name,
            tier=tier,
            justification=text,
            call_params=params,
            outcome="allowed",
            blocked_reason=None,
        )
    return result
