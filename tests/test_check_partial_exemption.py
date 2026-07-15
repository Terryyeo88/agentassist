"""Failing-first tests for the DETERMINISTIC partial-exemption check (Prompt I Phase 2).

Rulings pinned here (three-times rule — prompt/code/test):
  * PREDICATE (corrected/inverted): fire = actively_makes_exempt_supplies AND Box 3 > 0
    AND De Minimis FAILS. TX-RE presence is INFORMATIONAL only, never a gate — the
    check MUST fire with zero TX-RE lines (absence = the STRONGER candidate note).
  * BASIS: per accounting period (chain boxes); $40k/month average scales by
    months-in-period derived from period start/end.
  * De Minimis fails if EITHER threshold is breached (monthly-average OR 5%-ratio).
  * Box 4 (= Box 1+2+3) == 0 -> no finding, no divide-by-zero.
  * WORDING: the computed position GIVEN THE CODED FIGURES — never asserts
    "De Minimis is satisfied"; every finding is a candidate for the reviewer.
  * Renders UNGATED (like TP/TS) — keyed on section.show, never show_ai_candidates.
  * OUT OF SCOPE: the module COMPUTES no apportionment formula / three-bucket
    attribution / Longer Period Adjustment. Disclosure is required, not banned:
    _NOTE states the position is provisional pending the LPA.
  * THRESHOLD ARITHMETIC: compared on RAW quotients, never rounded values;
    rounding is display-only ("less than or equals to" is exact).

All tests hermetic: crafted Decimals/dicts inline (the test_check_analytical_review
precedent). No SAP, no anthropic, no frozen-fixture edits.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from orchestrator.check_partial_exemption import (
    check_partial_exemption,
    months_in_period,
    run_partial_exemption_check,
)
from report.report import build_report
from report.sections import build_partial_exemption_section

from config.loader import ClientConfig

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-07-15T00:00:00+00:00"


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


def _fire_kwargs(**over):
    """A crafted input set that FIRES: flag on, Box-3-heavy, both thresholds breached,
    ZERO TX-RE lines (the corrected predicate: TX-RE is never a gate)."""
    base = dict(
        actively_makes_exempt=True,
        box_1=Decimal("50000"),
        box_2=Decimal("10000"),
        box_3=Decimal("300000"),   # 100k/month over 3 months; ratio 300k/360k = 83%
        months=3,
        txre_lines_present=False,
    )
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# months_in_period
# ---------------------------------------------------------------------------

class TestMonthsInPeriod:
    def test_quarter_is_three_months(self):
        assert months_in_period("2024-07-01", "2024-09-30") == 3

    def test_single_month(self):
        assert months_in_period("2024-07-01", "2024-07-31") == 1

    def test_year_is_twelve(self):
        assert months_in_period("2024-01-01", "2024-12-31") == 12


# ---------------------------------------------------------------------------
# (i) FIRES with zero TX-RE lines  /  (ii) flag off  /  (iii) De Minimis passes
# ---------------------------------------------------------------------------

class TestPredicate:
    def test_fires_with_zero_txre_lines(self):
        findings = check_partial_exemption(**_fire_kwargs())
        assert len(findings) == 1
        f = findings[0]
        assert f["check"] == "PARTIAL_EXEMPTION_DE_MINIMIS"
        # TX-RE absent -> the STRONGER candidate note (residual may be unidentified).
        assert f["txre_lines_present"] is False

    def test_silent_when_flag_false(self):
        assert check_partial_exemption(**_fire_kwargs(actively_makes_exempt=False)) == []

    def test_silent_when_box3_zero(self):
        assert check_partial_exemption(**_fire_kwargs(box_3=Decimal("0"))) == []

    def test_silent_when_de_minimis_passes(self):
        # monthly avg 30k/3 = 10k <= 40k AND ratio 30k/630k ≈ 4.8% <= 5% -> no finding
        findings = check_partial_exemption(**_fire_kwargs(
            box_1=Decimal("500000"), box_2=Decimal("100000"), box_3=Decimal("30000"),
        ))
        assert findings == []


# ---------------------------------------------------------------------------
# (iv) thresholds independent — failing EITHER fires
# ---------------------------------------------------------------------------

class TestThresholdIndependence:
    def test_monthly_average_breach_alone_fires(self):
        # 150k/3 = 50k > 40k BUT ratio 150k/10.15M ≈ 1.5% <= 5%
        findings = check_partial_exemption(**_fire_kwargs(
            box_1=Decimal("9000000"), box_2=Decimal("1000000"), box_3=Decimal("150000"),
        ))
        assert len(findings) == 1
        assert findings[0]["monthly_average_breached"] is True
        assert findings[0]["ratio_breached"] is False

    def test_ratio_breach_alone_fires(self):
        # 30k/3 = 10k <= 40k BUT ratio 30k/130k ≈ 23% > 5%
        findings = check_partial_exemption(**_fire_kwargs(
            box_1=Decimal("90000"), box_2=Decimal("10000"), box_3=Decimal("30000"),
        ))
        assert len(findings) == 1
        assert findings[0]["monthly_average_breached"] is False
        assert findings[0]["ratio_breached"] is True


# ---------------------------------------------------------------------------
# (v) months scaling  /  (vi) Box 4 == 0 guard
# ---------------------------------------------------------------------------

class TestMonthsScalingAndGuards:
    def test_months_scaling_flips_the_monthly_test(self):
        # box_3=90k with a huge taxable base (ratio passes). 3 months -> 30k avg
        # (passes); 2 months -> 45k avg (fails) -> fires ONLY at 2 months.
        base = dict(
            actively_makes_exempt=True,
            box_1=Decimal("9000000"), box_2=Decimal("0"), box_3=Decimal("90000"),
            txre_lines_present=False,
        )
        assert check_partial_exemption(months=3, **base) == []
        fired = check_partial_exemption(months=2, **base)
        assert len(fired) == 1
        assert fired[0]["monthly_average_breached"] is True

    def test_box4_zero_no_finding_no_zerodivision(self):
        # box_1 negative (credit-note-heavy) exactly offsets box_3 -> Box 4 == 0.
        findings = check_partial_exemption(**_fire_kwargs(
            box_1=Decimal("-300000"), box_2=Decimal("0"), box_3=Decimal("300000"),
        ))
        assert findings == []

    def test_inputs_not_mutated(self):
        # [I1] mirror: pure read-only arithmetic.
        b3 = Decimal("300000")
        check_partial_exemption(**_fire_kwargs(box_3=b3))
        assert b3 == Decimal("300000")


# ---------------------------------------------------------------------------
# (vii) TX-RE informational split — both directions render
# ---------------------------------------------------------------------------

class TestTxreInformationalSplit:
    def test_absent_is_the_stronger_candidate_note(self):
        f = check_partial_exemption(**_fire_kwargs(txre_lines_present=False))[0]
        assert "TX-RE" in f["txre_note"]
        assert "not" in f["txre_note"].lower()  # residual may NOT have been identified

    def test_present_notes_bucketing_begun(self):
        f = check_partial_exemption(**_fire_kwargs(txre_lines_present=True))[0]
        assert f["txre_lines_present"] is True
        assert "TX-RE" in f["txre_note"]

    def test_notes_differ_between_directions(self):
        absent = check_partial_exemption(**_fire_kwargs(txre_lines_present=False))[0]
        present = check_partial_exemption(**_fire_kwargs(txre_lines_present=True))[0]
        assert absent["txre_note"] != present["txre_note"]


# ---------------------------------------------------------------------------
# FINDING WORDING — computed position given the CODED figures; candidate only
# ---------------------------------------------------------------------------

class TestFindingWording:
    def _finding(self):
        return check_partial_exemption(**_fire_kwargs())[0]

    def test_never_asserts_de_minimis_satisfied(self):
        f = self._finding()
        joined = " ".join(str(v) for v in f.values()).lower()
        assert "de minimis is satisfied" not in joined
        assert "is disallowed" not in joined

    def test_reads_as_coded_position_candidate(self):
        f = self._finding()
        assert "coded" in f["description"].lower()
        assert "consider reviewing whether" in f["description"].lower()
        assert "candidate" in f["note"].lower()

    def test_caveat_is_separate_field_mirroring_rc_ovr(self):
        f = self._finding()
        assert "caveat" in f
        assert "RC/OVR" in f["caveat"] or "Boxes 14" in f["caveat"]
        assert f["caveat"] not in f["description"]  # separate, not baked in

    def test_basis_field_present(self):
        assert self._finding()["basis"]

    def test_caveat_incidental_is_separate_field_not_baked_in(self):
        # Mirrors the RC/OVR caveat discipline: the incidental-exempt-supplies
        # exposure (reg 29(3)) is a SEPARATE field, never baked into the
        # description, and distinct from the denominator caveat.
        f = self._finding()
        assert "caveat_incidental" in f
        assert "incidental" in f["caveat_incidental"].lower()
        assert f["caveat_incidental"] not in f["description"]
        assert f["caveat_incidental"] != f["caveat"]


# ---------------------------------------------------------------------------
# run_partial_exemption_check — reads compile_output only (boxes + inventory)
# ---------------------------------------------------------------------------

class TestRunnerOverCompileOutput:
    def _co(self, *, box_3=300000.0, txre=False):
        boxes = {
            "box_1_standard_rated_sales": 50000.0,
            "box_2_zero_rated_sales": 10000.0,
            "box_3_exempt_sales": box_3,
            "box_4_total_sales": 50000.0 + 10000.0 + box_3,
            "box_5_taxable_purchases": 1000.0,
            "box_6_output_tax": 0.0, "box_7_input_tax": 0.0, "box_8_net_gst": 0.0,
        }
        inventory = {"SR": {"doc_count": 5, "side": "sales"}}
        if txre:
            inventory["TX-RE"] = {"doc_count": 2, "side": "purchase"}
        return {
            "period": {"start": "2024-07-01", "end": "2024-09-30"},
            "calculate": {"boxes": boxes},
            "classify": {"vatgroup_inventory": inventory},
        }

    def test_fires_over_crafted_compile_output(self):
        findings = run_partial_exemption_check(
            _make_cfg(actively_makes_exempt_supplies=True), self._co())
        assert len(findings) == 1
        assert findings[0]["txre_lines_present"] is False

    def test_detects_txre_from_vatgroup_inventory(self):
        findings = run_partial_exemption_check(
            _make_cfg(actively_makes_exempt_supplies=True), self._co(txre=True))
        assert findings[0]["txre_lines_present"] is True

    def test_silent_without_flag(self):
        assert run_partial_exemption_check(_make_cfg(), self._co()) == []

    def test_compile_output_not_mutated(self):
        co = self._co()
        snapshot = json.dumps(co, sort_keys=True)
        run_partial_exemption_check(
            _make_cfg(actively_makes_exempt_supplies=True), co)
        assert json.dumps(co, sort_keys=True) == snapshot


# ---------------------------------------------------------------------------
# Report section — UNGATED (keyed on show, never show_ai_candidates)
# ---------------------------------------------------------------------------

class TestReportSurface:
    def _findings(self):
        return check_partial_exemption(**_fire_kwargs())

    def test_section_hidden_when_no_findings(self):
        sec = build_partial_exemption_section([])
        assert sec.show is False

    def test_section_shows_with_findings_regardless_of_ai_gate(self):
        sec = build_partial_exemption_section(self._findings())
        assert sec.show is True

    def test_build_report_default_none_backcompat(self):
        from report.contract import load_compile_output
        m = build_report(load_compile_output(FIXTURE), _make_cfg(),
                         generated_at=_GENERATED_AT)
        assert getattr(m, "partial_exemption", "MISSING") is None

    def test_build_report_carries_section_ungated(self):
        from report.contract import load_compile_output
        # show_ai_candidates stays False (frozen) — the section must still show.
        m = build_report(load_compile_output(FIXTURE), _make_cfg(),
                         generated_at=_GENERATED_AT,
                         partial_exemption_findings=self._findings())
        assert m.partial_exemption is not None
        assert m.partial_exemption.show is True

    def test_renderer_noop_when_hidden(self):
        import types
        from report.render import _partial_exemption
        story: list = []
        _partial_exemption(types.SimpleNamespace(partial_exemption=None), story)
        assert story == []
        _partial_exemption(types.SimpleNamespace(
            partial_exemption=build_partial_exemption_section([])), story)
        assert story == []

    def test_renderer_draws_when_shown(self):
        import types
        from report.render import _partial_exemption
        story: list = []
        _partial_exemption(types.SimpleNamespace(
            partial_exemption=build_partial_exemption_section(self._findings())),
            story)
        assert len(story) > 0


# ---------------------------------------------------------------------------
# Threshold boundaries — rounding-fix regression guards.
# The comparison MUST run on the RAW quotients; quantizing before comparing
# would round a hairline breach into compliance and every test here would
# pass vacuously (silent where it should fire).
# ---------------------------------------------------------------------------

class TestThresholdBoundaries:
    def test_ratio_hairline_above_threshold_fires(self):
        # raw ratio 5004/100000 = 0.05004 > 0.05 — ratio limb only
        # (monthly avg 5004/12 = 417/month, far under 40k).
        findings = check_partial_exemption(**_fire_kwargs(
            box_1=Decimal("94996"), box_2=Decimal("0"), box_3=Decimal("5004"),
            months=12,
        ))
        assert len(findings) == 1
        assert findings[0]["ratio_breached"] is True
        assert findings[0]["monthly_average_breached"] is False

    def test_ratio_exactly_at_threshold_is_silent(self):
        # 5000/100000 = 0.05 exactly — "less than or equals to" is satisfied.
        assert check_partial_exemption(**_fire_kwargs(
            box_1=Decimal("95000"), box_2=Decimal("0"), box_3=Decimal("5000"),
            months=12,
        )) == []

    def test_monthly_hairline_above_threshold_fires(self):
        # raw monthly avg 120000.012/3 = 40000.004 > 40000 — monthly limb only
        # (ratio 120000.012/2620000.012 ≈ 4.58% <= 5%).
        findings = check_partial_exemption(**_fire_kwargs(
            box_1=Decimal("2500000"), box_2=Decimal("0"),
            box_3=Decimal("120000.012"), months=3,
        ))
        assert len(findings) == 1
        assert findings[0]["monthly_average_breached"] is True
        assert findings[0]["ratio_breached"] is False

    def test_monthly_exactly_at_threshold_is_silent(self):
        # 120000/3 = 40000 exactly — satisfied.
        assert check_partial_exemption(**_fire_kwargs(
            box_1=Decimal("2500000"), box_2=Decimal("0"),
            box_3=Decimal("120000"), months=3,
        )) == []

    def test_display_rounding_never_masks_a_raw_breach(self):
        # The 0.05004 case DISPLAYS at the threshold (0.0500 after HALF_UP
        # quantization) yet fired on the raw quotient — the per-limb *_breached
        # flags are authoritative, not the rendered figure.
        f = check_partial_exemption(**_fire_kwargs(
            box_1=Decimal("94996"), box_2=Decimal("0"), box_3=Decimal("5004"),
            months=12,
        ))[0]
        assert f["exempt_ratio"] == Decimal("0.0500")
        assert f["ratio_breached"] is True


# ---------------------------------------------------------------------------
# Not-Examined suppression — keys on the CONFIG FLAG (did the check RUN),
# never on whether findings exist. Flag on + De Minimis passes = the position
# WAS computed, so the "not computed" line must still be suppressed; the
# permanent apportionment item is never suppressed.
# ---------------------------------------------------------------------------

class TestNotExaminedSuppression:
    _APPORTIONMENT_PREFIX = "Partial-exemption input tax apportionment"
    _DE_MINIMIS_PREFIX = "Partial-exemption De Minimis position"

    def test_flag_off_renders_both_partial_exemption_items(self):
        from report.sections import build_not_examined_section
        sec = build_not_examined_section({}, _make_cfg())
        apportionment = [i for i in sec.items
                         if i.startswith(self._APPORTIONMENT_PREFIX)]
        de_minimis = [i for i in sec.items
                      if i.startswith(self._DE_MINIMIS_PREFIX)]
        assert len(apportionment) == 1
        assert len(de_minimis) == 1

    def test_flag_on_suppresses_de_minimis_item_keeps_apportionment(self):
        # No findings are passed anywhere — suppression must key on the flag
        # alone (the check ran; a clean De Minimis pass still suppresses).
        from report.sections import build_not_examined_section
        sec = build_not_examined_section(
            {}, _make_cfg(actively_makes_exempt_supplies=True))
        assert not [i for i in sec.items
                    if i.startswith(self._DE_MINIMIS_PREFIX)]
        apportionment = [i for i in sec.items
                         if i.startswith(self._APPORTIONMENT_PREFIX)]
        assert len(apportionment) == 1


# ---------------------------------------------------------------------------
# Scope boundary + module hygiene
# ---------------------------------------------------------------------------

class TestScopeAndHygiene:
    def test_module_computes_no_apportionment(self):
        # Asserts NO COMPUTATION, not no MENTION: _NOTE must DISCLOSE that the
        # position is provisional pending the Longer Period Adjustment (scope
        # disclosure is required), so a substring ban on the phrase would
        # forbid required disclosure. Out-of-scope-ness is instead pinned
        # structurally: no apportionment function exists, and the module
        # defines exactly its three public callables — nothing that could
        # compute the formula, the three-bucket attribution, or the LPA.
        import inspect

        import orchestrator.check_partial_exemption as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "def apportion" not in src.lower()
        funcs = {
            name for name, obj in vars(mod).items()
            if inspect.isfunction(obj) and obj.__module__ == mod.__name__
        }
        assert funcs == {
            "months_in_period",
            "check_partial_exemption",
            "run_partial_exemption_check",
        }

    def test_no_anthropic_or_reasoning_import(self):
        import orchestrator.check_partial_exemption as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import anthropic" not in src
        assert "from reasoning" not in src and "import reasoning" not in src
