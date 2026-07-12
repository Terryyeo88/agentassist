"""
tests/test_t224_ledger_recon_section.py — T2.24 PR-3 FAILING-FIRST tests.

Pins the "render the ledger recon into the PDF working paper" contract:
  * report.sections.build_ledger_recon_section(compile_output) -> LedgerReconSection
    (PURE/read-only; status derivation MIRRORS render_listing_findings_section,
    keeping None vs [] vs absent distinct for BOTH Signal A (ledger-vs-return
    divergence) and Signal B (not-included GST drop));
  * report.render.render_ledger_recon_section(section) -> str
    (empty-string-when-empty idiom, mirrors render_declared_f5_section; honest
    "not performed" line for unavailable; verbatim candidate-framed descriptions);
  * report.report.ReportModel.ledger_recon field, built once and shared;
  * build_not_examined_section(..., ledger_recon_section=) suppression, keyed on
    whether the recon was PERFORMED (present only when recon_status=="not_examined").

The compile_outputs are built by calling the REAL checks over the committed
xero-real-format fixtures (most faithful): recon yields two per-side divergence
dicts (output/270.0, input/6.3); drop yields one 820-control-account dict (6.3).

Hermetic: no live SAP, no anthropic import. The full-render proof writes only
into a TemporaryDirectory — never into the repo / sealed bundle.

These tests are RED until PR-3 is implemented (build_ledger_recon_section /
render_ledger_recon_section / the ReportModel.ledger_recon field / the
ledger_recon_section= kwarg do not exist yet).
"""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path
from typing import Any

import pytest

from report.sections import build_not_examined_section


# ---------------------------------------------------------------------------
# Real-check compile_output builders (over committed fixtures)
# ---------------------------------------------------------------------------

_FIX = Path(__file__).parent / "fixtures" / "xero-real-format"
_LEDGER_XLSX = _FIX / "AgentAssist_-_Account_Transactions.xlsx"
_F5_XLSX = _FIX / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"


def _build_recon_findings() -> list:
    """Signal A: ledger-derived GST vs declared F5 boxes → per-side divergences."""
    from feeders.xero_ledger_reader import load_gst_ledger
    from feeders.xero_f5_reader import parse_declared_return
    from orchestrator.check_gst_ledger_recon import run_ledger_recon_checks

    return run_ledger_recon_checks(
        load_gst_ledger(_LEDGER_XLSX),
        parse_declared_return(_F5_XLSX),
    )


def _build_drop_findings() -> list:
    """Signal B: GST posted to the 820 control account that dropped from the F5."""
    from feeders.xero_f5_reader import parse_not_included
    from orchestrator.check_gst_ledger_recon import run_not_included_checks

    return run_not_included_checks(parse_not_included(_F5_XLSX))


# Built once from the real checks over the committed fixtures.
_RECON = _build_recon_findings()   # two dicts: output/270.0, input/6.3
_DROP = _build_drop_findings()     # one dict: account "820 - GST", amount 6.3


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _import_new_symbols():
    """Import the PR-3 symbols lazily so collection stays clean while they are absent.

    Keeps the RED list per-test (an ImportError raised inside each test body) rather
    than a whole-module collection error before any test runs.
    """
    from report.sections import build_ledger_recon_section
    from report.render import render_ledger_recon_section

    return build_ledger_recon_section, render_ledger_recon_section


def _make_cfg(**overrides) -> Any:
    """Minimal duck-typed config for build_not_examined_section.

    Copied from tests/test_listing_findings_section.py so the _Cfg attributes and
    the build_not_examined_section call shape match exactly.
    """
    class _Cfg:
        custom_vat_groups: dict = {}

    cfg = _Cfg()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


_CFG = _make_cfg()


# Bare-verdict words the candidate framing must never emit — surfaces-never-asserts.
_VERDICT_WORDS = [" is wrong", " is incorrect", " is an error", " must be"]


# ---------------------------------------------------------------------------
# 1. Positive — both signals render
# ---------------------------------------------------------------------------

def test_positive_renders_both_signals():
    build_ledger_recon_section, render_ledger_recon_section = _import_new_symbols()

    co = {"ledger_recon_findings": _RECON, "not_included_findings": _DROP}
    sec = build_ledger_recon_section(co)
    text = render_ledger_recon_section(sec)
    low = text.lower()

    assert text != ""
    assert "GST Control-Ledger Reconciliation" in text

    # Evidence of BOTH divergences (Signal A: 270 and 6.3) …
    assert "270" in text
    assert ("6.3" in text) or ("6.30" in text)
    # … and the 820 not-included drop (Signal B).
    assert ("820 - GST" in text) or ("#14" in text)

    # Candidate framing carried verbatim from PR-1/PR-2 descriptions.
    assert "if a reviewer adjudicates" in low
    assert "not a verdict" in low

    # Surfaces-never-asserts: no bare verdict words.
    for word in _VERDICT_WORDS:
        assert word not in low, f"unexpected verdict phrasing {word!r} in rendered text"


# ---------------------------------------------------------------------------
# 2. Examined-clean — no fabricated all-clear line
# ---------------------------------------------------------------------------

def test_empty_when_empty_renders_nothing():
    build_ledger_recon_section, render_ledger_recon_section = _import_new_symbols()

    co = {"ledger_recon_findings": [], "not_included_findings": []}
    text = render_ledger_recon_section(build_ledger_recon_section(co))
    assert text == ""


# ---------------------------------------------------------------------------
# 3. No ledger at all — absent keys render nothing and never raise
# ---------------------------------------------------------------------------

def test_no_ledger_absent_keys_renders_nothing_no_raise():
    build_ledger_recon_section, render_ledger_recon_section = _import_new_symbols()

    co: dict = {}  # no ledger keys — the no-ledger path
    text = render_ledger_recon_section(build_ledger_recon_section(co))
    assert text == ""


# ---------------------------------------------------------------------------
# 4. Unavailable — honest not-performed line naming the reason
# ---------------------------------------------------------------------------

def test_unavailable_status_renders_honest_line():
    build_ledger_recon_section, render_ledger_recon_section = _import_new_symbols()

    co = {
        "ledger_recon_findings": None,
        "ledger_recon_status": {
            "level": "unavailable",
            "reason": "declared return boxes not supplied",
        },
    }
    text = render_ledger_recon_section(build_ledger_recon_section(co))
    low = text.lower()

    assert text != ""
    assert "declared return boxes not supplied" in text
    # Reads as not-performed / not-examined, NOT silence and NOT a divergence.
    assert ("not performed" in low) or ("not examined" in low)


# ---------------------------------------------------------------------------
# 5. Section 6 coordination — suppression keyed on whether recon was PERFORMED
# ---------------------------------------------------------------------------

def _mentions_ledger_recon(item: str) -> bool:
    """True when a Not-Examined item names the 820 control-ledger reconciliation."""
    low = item.lower()
    return "reconcil" in low and (
        "820" in low or "ledger" in low or "control" in low
    )


def test_section6_coordination_both_directions():
    build_ledger_recon_section, _render = _import_new_symbols()
    cfg = _make_cfg()

    # RENDERS case — recon performed (findings present) → line SUPPRESSED.
    co_positive = {"ledger_recon_findings": _RECON, "not_included_findings": _DROP}
    sec = build_ledger_recon_section(co_positive)
    ne = build_not_examined_section(co_positive, cfg, ledger_recon_section=sec)
    assert not any(_mentions_ledger_recon(i) for i in ne.items), (
        "recon was performed — the 820-ledger reconciliation Not-Examined line "
        "must be suppressed"
    )

    # NOT-RENDERED case — no ledger supplied (not_examined) → line PRESENT.
    co_absent: dict = {}
    sec2 = build_ledger_recon_section(co_absent)
    ne2 = build_not_examined_section(co_absent, cfg, ledger_recon_section=sec2)
    assert any(_mentions_ledger_recon(i) for i in ne2.items), (
        "no gst_ledger supplied — the control-ledger reconciliation Not-Examined "
        "line must be present"
    )


# ---------------------------------------------------------------------------
# 6. Read-only over compile_output (Invariant 4 / sealed-artifact protection)
# ---------------------------------------------------------------------------

def test_builder_does_not_mutate_compile_output():
    build_ledger_recon_section, render_ledger_recon_section = _import_new_symbols()

    co = {"ledger_recon_findings": _RECON, "not_included_findings": _DROP}
    before = copy.deepcopy(co)

    build_ledger_recon_section(co)
    render_ledger_recon_section(build_ledger_recon_section(co))

    assert co == before


# ---------------------------------------------------------------------------
# 7. Full PDF render proof — section present, render completes
# ---------------------------------------------------------------------------

class TestLedgerReconSectionRenders:
    """Verify the PDF render pipeline completes with the ledger-recon section present."""

    def _compile_output(self) -> dict:
        """Real chain fixture with the ledger-recon signals injected."""
        from report.contract import load_compile_output

        co = load_compile_output(
            Path(__file__).parent / "fixtures" / "chain-run-sample.json"
        )
        co = dict(co)
        co["ledger_recon_findings"] = _RECON
        co["not_included_findings"] = _DROP
        return co

    def _make_cfg(self) -> Any:
        from config.loader import ClientConfig

        return ClientConfig(
            client_id="sbodemosg",
            client_name="SBODEMOSG Demo",
            gst_registration_number="M12345678X",
            applicable_gst_rate=0.07,
            service_layer_url="https://fake",
            company_db="SBODEMOSG",
            username="manager",
            password="manager",
            ssl_verify=False,
            fiscal_year_start_month=1,
            custom_vat_groups={},
            completeness_threshold=0.1,
            reviewer_name="Terry Yeo",
            firm_name="AgentAssist Pte Ltd",
        )

    def test_full_pdf_render_proof(self):
        from report.render import render_pdf
        from report.report import build_report

        co = self._compile_output()
        cfg = self._make_cfg()
        model = build_report(co, cfg, generated_at="2026-06-10T00:00:00+00:00")

        # The section must be present on the model — the new ReportModel field.
        assert getattr(model, "ledger_recon", None) is not None, (
            "ReportModel must carry the ledger_recon section built once and shared"
        )

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.pdf"
            render_pdf(model, out)
            assert out.exists()
            assert out.stat().st_size > 0
