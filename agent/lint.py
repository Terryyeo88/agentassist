"""
agent/lint.py — deterministic language-lint over candidate framing text.

T5.3 Slice 2 (behavior). Enforces the invoke-never-perform invariant at the text
layer: the agent surfaces CANDIDATES for human review; it never voices a compliance
verdict. ``lint_framing`` REJECTS assertive compliance phrasing and REQUIRES at least
one candidate-framing marker.

HONEST STATUS: this lint is a BRITTLE BACKSTOP to prompt design, not a replacement
for it. A determined paraphrase can evade a phrase list. The REAL enforcement is
structural — there is no "assert compliance" tool in the registry, so the agent
cannot perform a compliance assertion regardless of what it writes. This lint only
catches the agent *voicing* a verdict in the free-text framing that a reviewer
would read; a lint failure holds the dossier back from staging.

Zero anthropic import. Zero SDK import. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Assertive compliance phrasing — a finding voiced as a verdict, not a candidate.
# Matched case-insensitively as substrings. Deliberately conservative: better to
# hold a borderline phrasing back for re-framing than to let a verdict through.
_ASSERTIVE_PHRASES: tuple[str, ...] = (
    "is non-compliant",
    "non-compliant",
    "is compliant",
    "violates",
    "violation of",
    "must repay",
    "must pay back",
    "is illegal",
    "illegal",
    "breaches",
    "in breach of",
    "fails to comply",
    "is fraudulent",
    "guilty of",
    "is liable for",
    "definitely",
    "certainly",
)

# Candidate-framing markers — at least one must be present.
_CANDIDATE_MARKERS: tuple[str, ...] = (
    "appears",
    "candidate",
    "for review",
    "for reviewer",
    "possible",
    "possibly",
    "potential",
    "may ",
    "might",
    "consider reviewing",
    "suspected",
    "hypothesis",
)


@dataclass
class LintResult:
    """Result of linting one candidate_framing_text.

    Attributes:
        passed:     True only when there are no assertive violations AND at least
                    one candidate-framing marker is present.
        violations: Assertive phrases found in the text (lowercased matches).
        reasons:    Machine-readable reason codes for failure
                    (e.g. "assertive-phrase", "missing-candidate-marker",
                    "empty-text").
    """
    passed: bool
    violations: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def lint_framing(text: str) -> LintResult:
    """Lint candidate framing text; reject assertive verdicts, require candidate framing.

    Args:
        text: The candidate_framing_text produced by the agent for a finding.

    Returns:
        LintResult. ``passed`` is True only when no assertive phrase is present and
        at least one candidate-framing marker is present.
    """
    lowered = (text or "").lower()
    reasons: list[str] = []

    if not lowered.strip():
        return LintResult(passed=False, violations=[], reasons=["empty-text"])

    violations = [phrase for phrase in _ASSERTIVE_PHRASES if phrase in lowered]
    if violations:
        reasons.append("assertive-phrase")

    has_marker = any(marker in lowered for marker in _CANDIDATE_MARKERS)
    if not has_marker:
        reasons.append("missing-candidate-marker")

    passed = not violations and has_marker
    return LintResult(passed=passed, violations=violations, reasons=reasons)
