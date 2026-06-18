"""
tests/test_listing_findings_section.py — T2.10 Phase 1 hermetic tests.

Covers render_listing_findings_section + build_not_examined_section suppression
for all four present/absent combinations of SEQ_GAP and DUP_CLAIM findings.

All tests are hermetic: no live SAP calls, no anthropic import, no PDF written.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from report.sections import (
    ListingFindingsSection,
    build_not_examined_section,
    render_listing_findings_section,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_cfg(**overrides) -> Any:
    """Minimal duck-typed config for build_not_examined_section."""
    class _Cfg:
        custom_vat_groups: dict = {}
    cfg = _Cfg()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


_CFG = _make_cfg()

_SEQ_GAP_FINDING = {
    "check": "SEQ_GAP",
    "series": 1,
    "gap_doc_num": 102,
    "series_min": 101,
    "series_max": 104,
    "description": "DocNum 102 (Series 1) is absent from all company records.",
    "basis": "IRAS ASK Annual Review Guide §10.1(c)(i)",
    "note": "candidate for reviewer attention",
}

_DUP_CLAIM_FINDING = {
    "check": "DUP_CLAIM",
    "doc_num": 502,
    "duplicate_of": 501,
    "card_code": "V10000",
    "num_at_card": "INV-ABC-001",
    "doc_total": 1000.00,
    "description": "DocNum 502 appears to be a duplicate of DocNum 501.",
    "basis": "IRAS ASK Annual Review Guide §10.1(d)(i)",
    "note": "candidate for reviewer attention",
}

_CO_NEITHER = {"listing_findings": []}
_CO_SEQ_ONLY = {"listing_findings": [_SEQ_GAP_FINDING]}
_CO_DUP_ONLY = {"listing_findings": [_DUP_CLAIM_FINDING]}
_CO_BOTH = {"listing_findings": [_SEQ_GAP_FINDING, _DUP_CLAIM_FINDING]}
_CO_NO_KEY = {}  # listing_findings key absent (older chain output)


# ---------------------------------------------------------------------------
# render_listing_findings_section — basic partitioning
# ---------------------------------------------------------------------------

class TestRenderListingFindingsSection:

    def test_neither_produces_empty_section(self):
        sec = render_listing_findings_section(_CO_NEITHER)
        assert sec.seq_gap_findings == []
        assert sec.dup_claim_findings == []

    def test_absent_key_produces_empty_section(self):
        sec = render_listing_findings_section(_CO_NO_KEY)
        assert sec.seq_gap_findings == []
        assert sec.dup_claim_findings == []

    def test_seq_only_partitions_correctly(self):
        sec = render_listing_findings_section(_CO_SEQ_ONLY)
        assert len(sec.seq_gap_findings) == 1
        assert sec.dup_claim_findings == []
        assert sec.seq_gap_findings[0]["gap_doc_num"] == 102

    def test_dup_only_partitions_correctly(self):
        sec = render_listing_findings_section(_CO_DUP_ONLY)
        assert sec.seq_gap_findings == []
        assert len(sec.dup_claim_findings) == 1
        assert sec.dup_claim_findings[0]["doc_num"] == 502

    def test_both_partitions_into_separate_lists(self):
        sec = render_listing_findings_section(_CO_BOTH)
        assert len(sec.seq_gap_findings) == 1
        assert len(sec.dup_claim_findings) == 1

    def test_unknown_check_type_excluded_from_both(self):
        co = {"listing_findings": [{"check": "UNKNOWN_TYPE", "foo": "bar"}]}
        sec = render_listing_findings_section(co)
        assert sec.seq_gap_findings == []
        assert sec.dup_claim_findings == []

    def test_returns_listing_findings_section_type(self):
        sec = render_listing_findings_section(_CO_BOTH)
        assert isinstance(sec, ListingFindingsSection)

    def test_multiple_seq_gap_findings(self):
        co = {"listing_findings": [
            {**_SEQ_GAP_FINDING, "gap_doc_num": 102},
            {**_SEQ_GAP_FINDING, "gap_doc_num": 103},
        ]}
        sec = render_listing_findings_section(co)
        assert len(sec.seq_gap_findings) == 2
        gap_nums = [f["gap_doc_num"] for f in sec.seq_gap_findings]
        assert sorted(gap_nums) == [102, 103]

    def test_multiple_dup_claim_findings(self):
        co = {"listing_findings": [
            _DUP_CLAIM_FINDING,
            {**_DUP_CLAIM_FINDING, "doc_num": 503, "duplicate_of": 501},
        ]}
        sec = render_listing_findings_section(co)
        assert len(sec.dup_claim_findings) == 2

    def test_input_not_mutated(self):
        import copy
        co = copy.deepcopy(_CO_BOTH)
        render_listing_findings_section(co)
        assert co == _CO_BOTH


# ---------------------------------------------------------------------------
# build_not_examined_section — independent Not-Examined suppression
# ---------------------------------------------------------------------------

def _items(compile_output: dict, listing_section: ListingFindingsSection | None = None) -> list[str]:
    """Helper: call build_not_examined_section and return its items list."""
    return build_not_examined_section(compile_output, _CFG, listing_section=listing_section).items


class TestNotExaminedSuppression:

    # ── Baseline: no listing_section passed → all items present ──────────────

    def test_no_listing_section_keeps_seq_gap_item(self):
        items = _items(_CO_NEITHER)
        combined = " ".join(items).lower()
        assert "sequence gap detection" in combined

    def test_no_listing_section_keeps_dup_claim_item(self):
        items = _items(_CO_NEITHER)
        combined = " ".join(items).lower()
        assert "duplicate input-tax claims" in combined

    # ── NEITHER present (examined-clean) → BOTH items suppressed ─────────────
    # tfix: listing_findings present-and-empty means the pass RAN and found nothing
    # (status "examined").  Both checks share one try, so NEITHER is "not performed";
    # both not-examined lines are suppressed and the report marks the run examined-clean
    # via the listing section (was BUG 2: a clean run mislabelled as "not examined").

    def test_neither_suppresses_seq_gap_item(self):
        sec = render_listing_findings_section(_CO_NEITHER)
        assert sec.status == "examined"
        items = _items(_CO_NEITHER, listing_section=sec)
        assert not any("sequence gap detection" in i.lower() for i in items), (
            "examined-clean run must not claim sequence gap detection was not examined"
        )

    def test_neither_suppresses_dup_claim_item(self):
        sec = render_listing_findings_section(_CO_NEITHER)
        items = _items(_CO_NEITHER, listing_section=sec)
        assert not any("duplicate input-tax claims" in i.lower() for i in items), (
            "examined-clean run must not claim duplicate input-tax claims was not examined"
        )

    # ── SEQ_GAP only → BOTH items suppressed (the pass ran; both checks examined) ──

    def test_seq_only_suppresses_seq_gap_item(self):
        sec = render_listing_findings_section(_CO_SEQ_ONLY)
        items = _items(_CO_SEQ_ONLY, listing_section=sec)
        combined = " ".join(items).lower()
        assert "sequence gap detection" not in combined, (
            "SEQ_GAP findings present — sequence gap detection Not-Examined item "
            "must be suppressed"
        )

    def test_seq_only_suppresses_dup_claim_item(self):
        # tfix: DUP_CLAIM ran clean in the same pass, so its line is suppressed too —
        # the pass was performed; nothing about it is "not examined".
        sec = render_listing_findings_section(_CO_SEQ_ONLY)
        items = _items(_CO_SEQ_ONLY, listing_section=sec)
        assert not any("duplicate input-tax claims" in i.lower() for i in items), (
            "listing pass ran — duplicate input-tax claims must not read as not examined"
        )

    # ── DUP_CLAIM only → BOTH items suppressed (the pass ran; both checks examined) ──

    def test_dup_only_suppresses_dup_claim_item(self):
        sec = render_listing_findings_section(_CO_DUP_ONLY)
        items = _items(_CO_DUP_ONLY, listing_section=sec)
        combined = " ".join(items).lower()
        assert "duplicate input-tax claims" not in combined, (
            "DUP_CLAIM findings present — duplicate input-tax claims Not-Examined "
            "item must be suppressed"
        )

    def test_dup_only_suppresses_seq_gap_item(self):
        # tfix: SEQ_GAP ran clean in the same pass, so its line is suppressed too.
        sec = render_listing_findings_section(_CO_DUP_ONLY)
        items = _items(_CO_DUP_ONLY, listing_section=sec)
        assert not any("sequence gap detection" in i.lower() for i in items), (
            "listing pass ran — sequence gap detection must not read as not examined"
        )

    # ── BOTH present → both items suppressed ─────────────────────────────────

    def test_both_suppresses_seq_gap_item(self):
        sec = render_listing_findings_section(_CO_BOTH)
        items = _items(_CO_BOTH, listing_section=sec)
        assert not any("sequence gap detection" in i.lower() for i in items)

    def test_both_suppresses_dup_claim_item(self):
        sec = render_listing_findings_section(_CO_BOTH)
        items = _items(_CO_BOTH, listing_section=sec)
        assert not any("duplicate input-tax claims" in i.lower() for i in items)

    # ── Suppression does not disturb other items ──────────────────────────────

    def test_both_keeps_manual_journal_item(self):
        sec = render_listing_findings_section(_CO_BOTH)
        items = _items(_CO_BOTH, listing_section=sec)
        combined = " ".join(items).lower()
        assert "manual journal" in combined

    def test_both_keeps_partial_exemption_item(self):
        sec = render_listing_findings_section(_CO_BOTH)
        items = _items(_CO_BOTH, listing_section=sec)
        combined = " ".join(items).lower()
        assert "partial-exemption" in combined

    def test_both_keeps_reverse_charge_item(self):
        sec = render_listing_findings_section(_CO_BOTH)
        items = _items(_CO_BOTH, listing_section=sec)
        combined = " ".join(items).lower()
        assert "reverse charge" in combined

    def test_both_keeps_declared_vs_computed_item(self):
        sec = render_listing_findings_section(_CO_BOTH)
        items = _items(_CO_BOTH, listing_section=sec)
        combined = " ".join(items).lower()
        assert "declared-vs-computed" in combined

    def test_time_of_supply_item_never_suppressed(self):
        sec = render_listing_findings_section(_CO_BOTH)
        items = _items(_CO_BOTH, listing_section=sec)
        combined = " ".join(items).lower()
        assert "time-of-supply" in combined


# ---------------------------------------------------------------------------
# PDF render — section renders without error
# ---------------------------------------------------------------------------

class TestListingFindingsSectionRenders:
    """Verify the PDF render pipeline completes without errors for all combinations."""

    def _minimal_compile_output(self, listing_findings: list) -> dict:
        """Build a minimal CompileOutput-shaped dict from the real chain fixture."""
        from report.contract import load_compile_output
        co = load_compile_output(
            Path(__file__).parent / "fixtures" / "chain-run-sample.json"
        )
        co = dict(co)
        co["listing_findings"] = listing_findings
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

    def _render(self, listing_findings: list) -> None:
        from report.render import render_pdf
        from report.report import build_report
        co = self._minimal_compile_output(listing_findings)
        cfg = self._make_cfg()
        model = build_report(co, cfg, generated_at="2026-06-10T00:00:00+00:00")
        with tempfile.TemporaryDirectory() as td:
            render_pdf(model, Path(td) / "test_out.pdf")

    def test_renders_neither(self):
        self._render([])

    def test_renders_seq_only(self):
        self._render([_SEQ_GAP_FINDING])

    def test_renders_dup_only(self):
        self._render([_DUP_CLAIM_FINDING])

    def test_renders_both(self):
        self._render([_SEQ_GAP_FINDING, _DUP_CLAIM_FINDING])


# ---------------------------------------------------------------------------
# Box-isolation: listing_findings key does not affect F5 boxes
# ---------------------------------------------------------------------------

class TestBoxIsolation:
    """Verify that render_listing_findings_section is read-only over compile_output."""

    def test_listing_section_does_not_mutate_compile_output(self):
        import copy
        co = copy.deepcopy(_CO_BOTH)
        render_listing_findings_section(co)
        assert co == _CO_BOTH

    def test_build_not_examined_does_not_mutate_compile_output(self):
        import copy
        co = {"listing_findings": [_SEQ_GAP_FINDING], "deduplicated_anomalies": []}
        co_before = copy.deepcopy(co)
        sec = render_listing_findings_section(co)
        build_not_examined_section(co, _CFG, listing_section=sec)
        assert co == co_before
