"""
tests/test_t212c_coverage_render.py — failing-test-first for T2.12 slice 2C:
RENDER the per-check data-coverage status (2B's ``check_coverage``) so a reviewer
can SEE that a review was silently-partial and never unknowingly sign it.

2B (#62) produced ``compile_output["check_coverage"]`` — a list of per-check
``{check, level, reason}`` dicts (full / degraded(reason) / unavailable) — but
NOTHING in report/ rendered it (it dead-ended). 2C renders it on a DEDICATED
"Deterministic Check Coverage" sibling section that REUSES tfix #63's three-state
vocabulary + non-empty-reason discipline, but is its OWN home — NOT the listing-
completeness section (check_coverage spans NO_GST_REG, which is not a listing check),
NOT the show_ai_candidates-gated probabilistic surface, NOT Section 6 (binary
suppression).

Acceptance, all hermetic (no SAP, no live chain, no anthropic):
  * builder maps check_coverage → CheckCoverageSection rows, read-only over input;
  * the text renderer surfaces all three states with their reasons;
  * a FULL-coverage run renders every check as examined — no degraded/unavailable noise;
  * the surface is dedicated (its own heading), distinct from listing + Section 6;
  * render reads compile_output without mutation (chain output byte-identity is the
    job of the unchanged orchestrator; 2C touches no chain code — see
    tests/test_t2_12a_offline_replay.py::test_offline_replay_byte_identical_to_oracle).
"""
from __future__ import annotations

from report.render import render_check_coverage_section
from report.sections import (
    CheckCoverageSection,
    build_check_coverage_section,
)

# ---------------------------------------------------------------------------
# Shared test data — the three wired 2B cases (as emitted by chain check_coverage).
# ---------------------------------------------------------------------------

_DUP_REASON = "NumAtCard absent or unpopulated — DUP_CLAIM under-detects."
_SEQ_REASON = "company-wide document population absent — SEQ_GAP limited to within-period."
_NOREG_REASON = (
    "FederalTaxID absent — NO_GST_REG cannot run; require supplier-master sheet at onboarding."
)

# A run where every check's source data was present AND populated.
_FULL = {
    "check_coverage": [
        {"check": "DUP_CLAIM", "level": "full", "reason": ""},
        {"check": "NO_GST_REG", "level": "full", "reason": ""},
        {"check": "SEQ_GAP", "level": "full", "reason": ""},
    ]
}

# A run exercising all three non-full states with their reasons.
_DEGRADED = {
    "check_coverage": [
        {"check": "DUP_CLAIM", "level": "degraded", "reason": _DUP_REASON},
        {"check": "NO_GST_REG", "level": "unavailable", "reason": _NOREG_REASON},
        {"check": "SEQ_GAP", "level": "degraded", "reason": _SEQ_REASON},
    ]
}


# ---------------------------------------------------------------------------
# Builder — build_check_coverage_section over compile_output["check_coverage"].
# ---------------------------------------------------------------------------

class TestBuilder:

    def test_absent_key_produces_empty_section(self):
        sec = build_check_coverage_section({})
        assert isinstance(sec, CheckCoverageSection)
        assert sec.rows == []
        assert sec.show is False

    def test_empty_list_produces_empty_section(self):
        sec = build_check_coverage_section({"check_coverage": []})
        assert sec.rows == []
        assert sec.show is False

    def test_rows_preserve_check_level_reason(self):
        sec = build_check_coverage_section(_DEGRADED)
        assert sec.show is True
        by_check = {r["check"]: r for r in sec.rows}
        assert by_check["DUP_CLAIM"]["level"] == "degraded"
        assert by_check["DUP_CLAIM"]["reason"] == _DUP_REASON
        assert by_check["NO_GST_REG"]["level"] == "unavailable"
        assert by_check["NO_GST_REG"]["reason"] == _NOREG_REASON
        assert by_check["SEQ_GAP"]["level"] == "degraded"

    def test_full_rows_carry_no_reason(self):
        sec = build_check_coverage_section(_FULL)
        assert sec.show is True
        assert all(r["level"] == "full" for r in sec.rows)
        assert all(not r["reason"] for r in sec.rows)

    def test_input_not_mutated(self):
        co = {"check_coverage": [{"check": "DUP_CLAIM", "level": "full", "reason": ""}]}
        before = repr(co)
        build_check_coverage_section(co)
        assert repr(co) == before, "builder must be read-only over compile_output"


# ---------------------------------------------------------------------------
# Text renderer — render_check_coverage_section(section) -> str.
# (The testable surface, mirroring render_declared_f5_section; the PDF flowable
#  appender _check_coverage is exercised by the e2e PDF render test.)
# ---------------------------------------------------------------------------

class TestRender:

    def test_empty_section_renders_nothing(self):
        assert render_check_coverage_section(build_check_coverage_section({})) == ""

    def test_three_states_render_with_reasons(self):
        text = render_check_coverage_section(build_check_coverage_section(_DEGRADED))
        # every check is named
        assert "DUP_CLAIM" in text
        assert "SEQ_GAP" in text
        assert "NO_GST_REG" in text
        # the three-state vocabulary is reused (tfix #63 + 2B)
        assert "degraded" in text.lower()
        assert "unavailable" in text.lower()
        # the data-coverage reasons are surfaced verbatim (never silent)
        assert _DUP_REASON in text
        assert _SEQ_REASON in text
        assert _NOREG_REASON in text

    def test_full_coverage_renders_every_check_examined(self):
        text = render_check_coverage_section(build_check_coverage_section(_FULL))
        # positively marked — full-coverage checks are visible as "examined", not invisible
        assert text != ""
        assert text.lower().count("examined") >= 3
        # no degraded/unavailable noise on a clean full run
        assert "degraded" not in text.lower()
        assert "unavailable" not in text.lower()
        # no stray reason text leaks onto a full row
        for reason in (_DUP_REASON, _SEQ_REASON, _NOREG_REASON):
            assert reason not in text

    def test_full_coverage_names_all_three_checks(self):
        text = render_check_coverage_section(build_check_coverage_section(_FULL))
        for check in ("DUP_CLAIM", "NO_GST_REG", "SEQ_GAP"):
            assert check in text


# ---------------------------------------------------------------------------
# Dedicated surface — distinct from the two wrong homes.
# ---------------------------------------------------------------------------

class TestDedicatedSurface:

    def test_heading_is_dedicated_not_listing_or_section6(self):
        text = render_check_coverage_section(build_check_coverage_section(_DEGRADED))
        lowered = text.lower()
        # its OWN home …
        assert "deterministic check coverage" in lowered
        # … NOT folded into the listing-completeness section (which is scoped to
        # SEQ_GAP + DUP_CLAIM only and would misfile NO_GST_REG) …
        assert "invoice listing completeness" not in lowered
        # … and NOT Section 6 (binary suppression).
        assert "items not examined" not in lowered

    def test_no_gst_reg_present_here_not_a_listing_check(self):
        # NO_GST_REG lives in detect_gst_errors, not the listing pass; the dedicated
        # coverage surface is the one honest home that can carry all three checks.
        text = render_check_coverage_section(build_check_coverage_section(_DEGRADED))
        assert "NO_GST_REG" in text
