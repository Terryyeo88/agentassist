"""
tests/test_t53b_lint.py — T5.3 Slice 2: deterministic language-lint over framing.

The candidate_framing_text the agent produces for a finding is run through a
deterministic lint that REJECTS assertive compliance phrasing ("is non-compliant",
"violates", "must repay") and REQUIRES candidate framing ("appears", "candidate",
"for review").

HONEST STATUS (mirrored from the module docstring): this lint is a brittle backstop
to prompt design, NOT a replacement for it. The real structural enforcement is the
ABSENCE of any "assert compliance" tool in the registry — the agent cannot perform a
compliance assertion because no such tool exists. The lint catches the agent
*voicing* one in free text.

Hermetic: pure strings, no SDK, no model, no network.
"""
from __future__ import annotations

import pytest

from agent.lint import LintResult, lint_framing


class TestAssertiveFramingRejected:
    @pytest.mark.parametrize("text", [
        "Invoice 605 is non-compliant with the GST Act.",
        "This supplier violates Regulation 11 and the claim is invalid.",
        "The client must repay $1,200 of wrongly claimed input tax.",
        "This is illegal and breaches the zero-rating rules.",
    ])
    def test_assertive_phrases_fail(self, text):
        result = lint_framing(text)
        assert isinstance(result, LintResult)
        assert result.passed is False
        assert result.violations, "an assertive phrase must be reported as a violation"


class TestCandidateFramingPasses:
    @pytest.mark.parametrize("text", [
        "Invoice 605 appears to be a candidate for reviewer attention.",
        "This line is a candidate for review — possible export wrongly standard-rated.",
        "The supplier GST number appears absent; flagged as a candidate for review.",
    ])
    def test_candidate_phrases_pass(self, text):
        result = lint_framing(text)
        assert result.passed is True
        assert result.violations == []


class TestRequiresCandidateMarker:
    def test_neutral_text_without_marker_is_rejected(self):
        # No assertive phrase, but also no candidate-framing marker → not acceptable
        # framing for a human-reviewed dossier.
        result = lint_framing("Invoice 605 has a tax amount of 70 dollars.")
        assert result.passed is False
        assert "missing-candidate-marker" in result.reasons

    def test_empty_text_is_rejected(self):
        result = lint_framing("")
        assert result.passed is False
