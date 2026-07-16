"""Failing-first tests for the DETERMINISTIC scheme-status contradiction check.

A CONFIG-vs-DATA contradiction check (D+), mirroring check_partial_exemption.py.

Rulings pinned here (three-times rule — prompt/code/test):
  * PREDICATE (config-vs-data contradiction): an arm fires iff the client's config
    flag is OFF yet the classify inventory carries docs coded to that scheme.
      - IGDS arm fires iff (not participates_in_igds) AND igds_doc_count > 0.
      - ME   arm fires iff (not participates_in_mes)  AND me_doc_count   > 0.
  * INVERSE DIRECTION IS OUT OF SCOPE: flag True + code absent (client SAYS it is
    in the scheme but no scheme-coded docs appear) is ruled OUT of this slice —
    it returns []. Only the flag-off/data-present direction is surfaced here.
  * REGISTRY IS OUT OF SCOPE: this check is self-gated by data presence (the
    inventory), never wired through a check registry; there is nothing to register.
  * NE-CHANGE IS OUT OF SCOPE: this check ALWAYS runs (self-gated by data
    presence), so it suppresses NOTHING — the 3E Not-Examined item is permanent
    and the scheme flags must not add/remove/suppress any Not-Examined item.
  * SEVERITY ASYMMETRY (rule-author-supplied):
      - ME arm = MEDIUM. If lines are coded to a scheme not participated in, the
        GST paid at the border was coded as SUSPENDED and no Box 7 claim was made
        — the client UNDER-CLAIMS its own input tax. That is the CLIENT'S loss,
        not IRAS exposure, so the severity is capped at MEDIUM.
      - IGDS arm = HIGH. Import GST would have been DEFERRED without entitlement —
        that is IRAS exposure, hence HIGH.
    When both fire, HIGH (IGDS) is surfaced BEFORE MEDIUM (ME).
  * FINDING-DESIGN INVARIANT (config-vs-data, the load-bearing one): the check
    CANNOT know which side is wrong (stale config OR miscoded lines). Every finding
    holds BOTH hypotheses verbatim, carries NO verdict language, keeps consequences
    CONDITIONAL, and defers to the reviewer confirming scheme participation with the
    client. severity_note and note are SEPARATE fields, never baked into description.
  * Renders UNGATED (like the mirror) — keyed on section.show, never
    show_ai_candidates (which stays frozen False).

All tests hermetic: crafted dicts inline (the mirror precedent). No SAP, no anthropic,
no frozen-fixture edits.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.check_scheme_status import (
    check_scheme_status,
    run_scheme_status_check,
)
from report.report import build_report
from report.sections import build_scheme_status_section

from config.loader import ClientConfig

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-07-15T00:00:00+00:00"

# The exact verdict language BANNED from description + severity_note (config-vs-data:
# the check cannot know which side is wrong, so it may never accuse either).
_VERDICT_BANS = ("miscoded", "are wrong", "non-compliance", "must be corrected")


def _make_cfg(**overrides) -> ClientConfig:
    base = dict(
        client_id="testclient",
        client_name="Test Client Pte Ltd",
        gst_registration_number="M90000001A",
        applicable_gst_rate=0.09,
        service_layer_url="https://fake",
        company_db="TESTDB",
        username="u",
        password="HUNTER2_TEST",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.10,
        reviewer_name="Jane Tan",
        firm_name="Tan & Associates",
    )
    base.update(overrides)
    return ClientConfig(**base)


def _fire_both(**over) -> list[dict]:
    """Both flags OFF, both inventories carry docs -> BOTH arms fire (len==2)."""
    base = dict(
        participates_in_mes=False,
        participates_in_igds=False,
        me_doc_count=4,
        igds_doc_count=7,
    )
    base.update(over)
    return check_scheme_status(**base)


def _me_finding() -> dict:
    """Only the ME arm fires (IGDS consistent: flag off, no docs)."""
    return check_scheme_status(
        participates_in_mes=False,
        participates_in_igds=False,
        me_doc_count=4,
        igds_doc_count=0,
    )[0]


def _igds_finding() -> dict:
    """Only the IGDS arm fires (ME consistent: flag off, no docs)."""
    return check_scheme_status(
        participates_in_mes=False,
        participates_in_igds=False,
        me_doc_count=0,
        igds_doc_count=7,
    )[0]


# ---------------------------------------------------------------------------
# Predicate corners — flag-off/data-present is the ONLY firing direction.
# ---------------------------------------------------------------------------

class TestPredicateCorners:
    def test_igds_arm_fires_flag_off_docs_present(self):
        findings = check_scheme_status(
            participates_in_mes=False, participates_in_igds=False,
            me_doc_count=0, igds_doc_count=7,
        )
        assert len(findings) == 1
        assert findings[0]["scheme"] == "IGDS"

    def test_me_arm_fires_flag_off_docs_present(self):
        findings = check_scheme_status(
            participates_in_mes=False, participates_in_igds=False,
            me_doc_count=4, igds_doc_count=0,
        )
        assert len(findings) == 1
        assert findings[0]["scheme"] == "MES"

    def test_consistent_flag_on_code_present_is_silent(self):
        # Flag True + docs present = CONSISTENT -> [].
        assert check_scheme_status(
            participates_in_mes=True, participates_in_igds=True,
            me_doc_count=4, igds_doc_count=7,
        ) == []

    def test_flag_off_code_absent_is_silent(self):
        # Flag False + zero docs = CONSISTENT (nothing coded) -> [].
        assert check_scheme_status(
            participates_in_mes=False, participates_in_igds=False,
            me_doc_count=0, igds_doc_count=0,
        ) == []

    def test_inverse_direction_flag_on_code_absent_ruled_out(self):
        # Flag True + code ABSENT is the INVERSE direction — OUT of this slice -> [].
        assert check_scheme_status(
            participates_in_mes=True, participates_in_igds=True,
            me_doc_count=0, igds_doc_count=0,
        ) == []

    def test_pure_no_side_effects_on_repeat(self):
        # Read-only: repeated calls give identical results (no accumulated state).
        first = _fire_both()
        second = _fire_both()
        assert first == second
        assert len(first) == 2


# ---------------------------------------------------------------------------
# Both arms + ordering — HIGH (IGDS) before MEDIUM (ME).
# ---------------------------------------------------------------------------

class TestBothArmsOrdering:
    def test_both_arms_fire_len_two(self):
        assert len(_fire_both()) == 2

    def test_igds_surfaces_before_me(self):
        findings = _fire_both()
        assert findings[0]["scheme"] == "IGDS"
        assert findings[1]["scheme"] == "MES"

    def test_order_is_severity_high_before_medium(self):
        findings = _fire_both()
        assert findings[0]["severity"] == "HIGH"
        assert findings[1]["severity"] == "MEDIUM"

    def test_doc_counts_passed_through_per_arm(self):
        findings = _fire_both(me_doc_count=4, igds_doc_count=7)
        by_scheme = {f["scheme"]: f for f in findings}
        assert by_scheme["IGDS"]["doc_count"] == 7
        assert by_scheme["MES"]["doc_count"] == 4


# ---------------------------------------------------------------------------
# Severity asymmetry — ME=MEDIUM (client's own under-claim, client's loss);
# IGDS=HIGH (import GST deferred without entitlement, IRAS exposure).
# ---------------------------------------------------------------------------

class TestSeverityAsymmetry:
    def test_me_severity_is_medium(self):
        assert _me_finding()["severity"] == "MEDIUM"

    def test_igds_severity_is_high(self):
        assert _igds_finding()["severity"] == "HIGH"

    def test_severities_differ_across_arms(self):
        findings = _fire_both()
        severities = {f["severity"] for f in findings}
        assert severities == {"HIGH", "MEDIUM"}
        assert len(severities) == 2


# ---------------------------------------------------------------------------
# Finding shape + wording — 11 keys; both hypotheses verbatim; no verdicts;
# conditional consequences; reviewer defers to the client.
# ---------------------------------------------------------------------------

class TestFindingShapeWording:
    _KEYS = {
        "check", "finding_type", "scheme", "vat_group", "config_flag",
        "doc_count", "severity", "severity_note", "basis", "description", "note",
    }

    def test_exact_key_set_both_arms(self):
        for f in (_me_finding(), _igds_finding()):
            assert set(f.keys()) == self._KEYS
            assert len(f) == 11

    def test_static_field_values(self):
        me, igds = _me_finding(), _igds_finding()
        assert me["check"] == "SCHEME_STATUS_CONTRADICTION"
        assert igds["check"] == "SCHEME_STATUS_CONTRADICTION"
        assert me["finding_type"] == "scheme_status"
        assert igds["finding_type"] == "scheme_status"

    def test_scheme_vat_group_and_flag_mapping(self):
        me, igds = _me_finding(), _igds_finding()
        assert (me["scheme"], me["vat_group"], me["config_flag"]) == (
            "MES", "ME", "participates_in_mes")
        assert (igds["scheme"], igds["vat_group"], igds["config_flag"]) == (
            "IGDS", "IGDS", "participates_in_igds")

    def test_doc_count_is_int(self):
        assert isinstance(_me_finding()["doc_count"], int)
        assert isinstance(_igds_finding()["doc_count"], int)

    def test_basis_cites_3d_and_discloses_proxy(self):
        # BASIS RULING v2 (rule-author, 2026-07-16), replacing
        # test_basis_disclaims_iras_prescription, which pinned a FALSE ruling.
        # v1 concluded no IRAS provision prescribes a config-vs-codes check.
        # ASK Annual Review Guide Step 3D.1.1(b) DOES prescribe it: a business
        # not approved under MES/IGDS must scan its listings for import permit
        # numbers beginning "ME" or "MC". v1 reasoned correctly that the check
        # is not 3E (3E presupposes participation) and then wrongly inferred it
        # was nowhere. It is in 3D — the step every business performs.
        # The honesty point that survives: IRAS's signal is the permit-number
        # prefix (Customs' record). Ours is the VatGroup code (the client's own
        # bookkeeping). We proxy the check on weaker evidence, which is why
        # findings surface both hypotheses rather than naming an error.
        for f in (_me_finding(), _igds_finding()):
            basis = f["basis"]
            assert basis.startswith("IRAS-prescribed check, proxied.")
            assert "3D.1.1(b)" in basis
            assert "'ME' or 'MC'" in basis
            assert "VatGroup" in basis
            assert "weaker evidence" in basis
            assert "not 3D.1.1(b)" in basis
            assert "Not an IRAS-prescribed check" not in basis
            assert "no IRAS provision or ASK cell prescribes it" not in basis
            assert "3E" not in basis
            assert "code treatments" in basis

    def test_description_holds_both_hypotheses_verbatim(self):
        # config-vs-data: the check cannot know which side is wrong, so the
        # description carries BOTH hypotheses literally.
        for f in (_me_finding(), _igds_finding()):
            assert "configuration is stale" in f["description"]
            assert ("coded to a scheme the client does not participate in"
                    in f["description"])

    def test_description_carries_no_verdict_language(self):
        for f in (_me_finding(), _igds_finding()):
            low = f["description"].lower()
            for banned in _VERDICT_BANS:
                assert banned not in low

    def test_severity_note_is_conditional_and_verdict_free(self):
        for f in (_me_finding(), _igds_finding()):
            low = f["severity_note"].lower()
            assert "if" in low  # consequence is CONDITIONAL, not asserted
            for banned in _VERDICT_BANS:
                assert banned not in low

    def test_note_defers_to_reviewer_confirming_with_client(self):
        for f in (_me_finding(), _igds_finding()):
            low = f["note"].lower()
            assert "confirm" in low
            assert "client" in low

    def test_severity_note_separate_field_not_baked_into_description(self):
        for f in (_me_finding(), _igds_finding()):
            assert f["severity_note"] not in f["description"]

    def test_me_description_names_scheme_and_suspended(self):
        d = _me_finding()["description"]
        assert "Major Exporter Scheme" in d
        assert "suspended" in d

    def test_igds_description_names_scheme_and_deferred(self):
        d = _igds_finding()["description"]
        assert "Import GST Deferment Scheme" in d
        assert "deferred" in d


# ---------------------------------------------------------------------------
# run_scheme_status_check — reads config flags + classify.vatgroup_inventory ONLY.
# INVENTORY CONTRACT: a zero-doc VatGroup is ABSENT from the inventory (never
# present with doc_count=0).
# ---------------------------------------------------------------------------

class TestRunnerOverCompileOutput:
    def _co(self, *, me=None, igds=None):
        """Craft a compile_output. A None arm is ABSENT from the inventory
        (the recon-proven contract: zero-doc groups do not appear)."""
        inventory = {"SR": {"doc_count": 5, "side": "sales"}}
        if me is not None:
            inventory["ME"] = {"doc_count": me, "side": "purchase"}
        if igds is not None:
            inventory["IGDS"] = {"doc_count": igds, "side": "purchase"}
        return {
            "period": {"start": "2024-07-01", "end": "2024-09-30"},
            "classify": {"vatgroup_inventory": inventory},
        }

    def test_fires_both_arms_flags_off(self):
        findings = run_scheme_status_check(_make_cfg(), self._co(me=4, igds=7))
        assert len(findings) == 2
        assert findings[0]["scheme"] == "IGDS"
        assert findings[1]["scheme"] == "MES"

    def test_silent_when_flags_on(self):
        findings = run_scheme_status_check(
            _make_cfg(participates_in_mes=True, participates_in_igds=True),
            self._co(me=4, igds=7),
        )
        assert findings == []

    def test_inventory_without_scheme_keys_is_silent(self):
        # INVENTORY CONTRACT: absent ME/IGDS keys (flags off) -> [] (no docs coded).
        assert run_scheme_status_check(_make_cfg(), self._co()) == []

    def test_no_classify_key_no_keyerror(self):
        # A compile_output missing "classify" entirely -> [] (no KeyError).
        co = {"period": {"start": "2024-07-01", "end": "2024-09-30"}}
        assert run_scheme_status_check(_make_cfg(), co) == []

    def test_doc_count_read_from_inventory_row(self):
        findings = run_scheme_status_check(_make_cfg(), self._co(me=4, igds=7))
        by_scheme = {f["scheme"]: f for f in findings}
        assert by_scheme["IGDS"]["doc_count"] == 7
        assert by_scheme["MES"]["doc_count"] == 4

    def test_compile_output_not_mutated(self):
        co = self._co(me=4, igds=7)
        snapshot = json.dumps(co, sort_keys=True)
        run_scheme_status_check(_make_cfg(), co)
        assert json.dumps(co, sort_keys=True) == snapshot


# ---------------------------------------------------------------------------
# Report section — UNGATED (keyed on show, never show_ai_candidates).
# ---------------------------------------------------------------------------

class TestReportSurface:
    def test_section_hidden_when_no_findings(self):
        sec = build_scheme_status_section([])
        assert sec.show is False

    def test_section_shows_with_findings_and_preserves_them(self):
        findings = _fire_both()
        sec = build_scheme_status_section(findings)
        assert sec.show is True
        assert sec.findings == findings

    def test_build_report_default_none_backcompat(self):
        from report.contract import load_compile_output
        m = build_report(load_compile_output(FIXTURE), _make_cfg(),
                         generated_at=_GENERATED_AT)
        assert getattr(m, "scheme_status", "MISSING") is None

    def test_build_report_carries_section_ungated(self):
        from report.contract import load_compile_output
        m = build_report(load_compile_output(FIXTURE), _make_cfg(),
                         generated_at=_GENERATED_AT,
                         scheme_status_findings=_fire_both())
        assert m.scheme_status is not None
        assert m.scheme_status.show is True
        # show_ai_candidates stays False (frozen) — the section shows regardless.
        assert getattr(m, "show_ai_candidates", False) is False

    def test_renderer_noop_when_hidden(self):
        import types
        from report.render import _scheme_status
        story: list = []
        _scheme_status(types.SimpleNamespace(scheme_status=None), story)
        assert story == []
        _scheme_status(types.SimpleNamespace(
            scheme_status=build_scheme_status_section([])), story)
        assert story == []

    def test_renderer_draws_when_shown(self):
        import types
        from report.render import _scheme_status
        story: list = []
        _scheme_status(types.SimpleNamespace(
            scheme_status=build_scheme_status_section(_fire_both())), story)
        assert len(story) > 0

    def test_rendered_heading_contains_no_ask(self):
        # BASIS RULING (rule-author, 2026-07-16): the heading must not carry an
        # ASK parenthetical — an "(ASK Step 3E)" tag reads as IRAS prescribing
        # this check, which no provision or ASK cell does.
        import types
        from report.render import _scheme_status
        story: list = []
        _scheme_status(types.SimpleNamespace(
            scheme_status=build_scheme_status_section(_fire_both())), story)
        heading = next(
            fl.text for fl in story
            if hasattr(fl, "text") and "Scheme Status" in getattr(fl, "text", "")
        )
        assert heading == "Scheme Status — Configuration vs Coded Lines"
        assert "ASK" not in heading


# ---------------------------------------------------------------------------
# Not-Examined — A13 3E line byte-identical; NO suppression by the scheme flags.
# ---------------------------------------------------------------------------

class TestNotExaminedFrozen:
    _3E_LINE = (
        "Scheme-specific imports with GST suspended or deferred (Boxes 9, 19, 21 "
        "not computed; MES / IGDS scheme approval status and import-permit "
        "verification not performed — ASK Step 3E)"
    )

    def test_3e_line_present_byte_identical(self):
        from report.constants import NOT_EXAMINED_ITEMS
        assert self._3E_LINE in NOT_EXAMINED_ITEMS

    def test_scheme_flags_do_not_change_not_examined_items(self):
        # This check always runs (self-gated by data presence): there is nothing
        # to suppress, so flag-on and flag-off must produce identical items.
        from report.sections import build_not_examined_section
        off = build_not_examined_section({}, _make_cfg())
        on = build_not_examined_section(
            {}, _make_cfg(participates_in_mes=True, participates_in_igds=True))
        assert off.items == on.items


# ---------------------------------------------------------------------------
# Scope boundary + module hygiene.
# ---------------------------------------------------------------------------

class TestScopeAndHygiene:
    def test_module_defines_exactly_two_functions(self):
        import inspect

        import orchestrator.check_scheme_status as mod
        funcs = {
            name for name, obj in vars(mod).items()
            if inspect.isfunction(obj) and obj.__module__ == mod.__name__
        }
        assert funcs == {"check_scheme_status", "run_scheme_status_check"}

    def test_no_anthropic_or_reasoning_import(self):
        import orchestrator.check_scheme_status as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import anthropic" not in src
        assert "from reasoning" not in src and "import reasoning" not in src
        assert "from agent" not in src and "import agent" not in src
        assert "from documents" not in src and "import documents" not in src
