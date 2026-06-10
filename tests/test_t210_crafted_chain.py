"""
tests/test_t210_crafted_chain.py — T2.10 Phase 2: crafted-input full-chain validation.

Runs the REAL run_chain with fetch_listing_data PATCHED to return crafted header sets.
Everything else is real: real detect_seq_gaps, real detect_dup_claims, real post-gate_5
wiring, real BOX-ISOLATION assertion, real report render.

NO SAP WRITES. All chain steps (fetch/calculate/classify/detect) are monkeypatched so
no live SAP connection is required.

Crafted population:

    SEQ_GAP (Series=1 sales):
        period_sales_headers = [8001, 8004]          active range [8001, 8004]
        all_sales_headers    = [8001, 8003, 8004]
          8002 absent from all_records → truly absent      FLAGGED
          8003 within range but present in all_records     NOT flagged (other-period slot)
          8001, 8004 present in period                     not gaps

    DUP_CLAIM (Series=6 purchases):
        7001, 7002 → same CardCode + NumAtCard + DocTotal  FLAGGED (dup pair)
        7003       → same CardCode + DocTotal, different NumAtCard  NOT flagged (near-miss)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

import sap_b1_server  # noqa: E402

from config.loader import ClientConfig  # noqa: E402
from orchestrator.chain import run_chain  # noqa: E402
from report.report import build_report  # noqa: E402
from report.render import render_pdf  # noqa: E402


# ---------------------------------------------------------------------------
# Shared config + period
# ---------------------------------------------------------------------------

_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}


@pytest.fixture()
def cfg():
    return ClientConfig(
        client_id="test",
        client_name="Test Client",
        gst_registration_number="",
        applicable_gst_rate=0.07,
        service_layer_url="https://fake",
        company_db="TEST",
        username="user",
        password="pass",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.1,
        reviewer_name="",
        firm_name="",
    )


# ---------------------------------------------------------------------------
# Minimal chain step outputs (mirroring test_chain.py helpers)
# ---------------------------------------------------------------------------

def _make_manifest():
    return {
        "period": _PERIOD,
        "fetched_at": "2024-10-01T00:00:00+00:00",
        "records": [
            {
                "doc_num": 1, "doc_date": "2024-07-15", "doc_type": "sales_invoice",
                "doc_currency": "USD", "doc_total": 100.0,
                "card_name": "Overseas Co", "vat_group": "SO",
            }
        ],
        "doc_nums": {1},
        "sap_inline_count": None,
    }


def _make_calc():
    return {
        "period": _PERIOD,
        "currency": "SGD",
        "boxes": {
            "box_1_standard_rated_sales": 100.0,
            "box_2_zero_rated_sales": 0.0,
            "box_3_exempt_sales": 0.0,
            "box_4_total_sales": 100.0,
            "box_5_taxable_purchases": 50.0,
            "box_6_output_tax": 9.0,
            "box_7_input_tax": 4.0,
            "box_8_net_gst": 5.0,
        },
        "fx_invoices_requiring_conversion": [],
        # E1 candidate doc_num=1 must match detect's E1 issue for Gate 5
        "e1_candidates": [
            {"doc_num": 1, "doc_date": "2024-07-15",
             "card_name": "Overseas Co", "doc_currency": "USD", "vat_group": "SO"}
        ],
        "record_counts": {},
        "credit_note_counts": {},
        "credit_notes_applied": [],
        "anomalies": [],
    }


def _make_classify():
    return {
        "period": _PERIOD,
        "expected_rate": 0.07,
        "vatgroup_inventory": {
            "SO": {
                "gst_category": "Standard-rated output",
                "side": "sales",
                "lt_box": "box_1_standard_rated_sales",
                "tt_box": "box_6_output_tax",
                "doc_count": 1,
                "known_to_mapping": True,
            }
        },
        "issues": [],
        "summary": {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 0},
    }


def _make_detect():
    # E1 for doc_num=1 must match calc's e1_candidates for Gate 5
    return {
        "period": _PERIOD,
        "severity_counts": {"HIGH": 1, "MEDIUM": 0, "LOW": 0},
        "issues": [
            {
                "severity": "HIGH",
                "error_code": "E1",
                "doc_num": 1,
                "doc_date": "2024-07-15",
                "card_name": "Overseas Co",
                "description": "FX invoice coded SO — should be ZR for overseas sale.",
                "recommendation": "Reclassify as ZR.",
            }
        ],
    }


def _patch_main_chain(monkeypatch):
    """Patch all five main chain steps so no SAP connection is needed."""
    monkeypatch.setattr(sap_b1_server, "configure_client", lambda *a, **kw: None)
    monkeypatch.setattr("orchestrator.chain.fetch",     lambda cfg, p: _make_manifest())
    monkeypatch.setattr("orchestrator.chain.calculate", lambda cfg, p: _make_calc())
    monkeypatch.setattr("orchestrator.chain.classify",  lambda cfg, p: _make_classify())
    monkeypatch.setattr("orchestrator.chain.detect",    lambda cfg, p: _make_detect())


# ---------------------------------------------------------------------------
# Crafted listing data
# ---------------------------------------------------------------------------

def _sales_hdr(doc_num: int, series: int = 1, cancelled: str = "tNO") -> dict:
    return {"DocNum": doc_num, "Series": series, "Cancelled": cancelled}


def _purch_hdr(
    doc_num: int,
    card_code: str,
    num_at_card: str,
    doc_total: float,
    series: int = 6,
    cancelled: str = "tNO",
) -> dict:
    return {
        "DocNum": doc_num,
        "Series": series,
        "Cancelled": cancelled,
        "CardCode": card_code,
        "NumAtCard": num_at_card,
        "DocTotal": doc_total,
    }


# SEQ_GAP crafted set
# period_sales_headers = [8001, 8004]  → active range [8001, 8004]
# all_sales_headers    = [8001, 8003, 8004]
#   8002: absent from all_records         → truly absent        → FLAGGED
#   8003: absent from period, in all_records → other-period slot → NOT flagged
_PERIOD_SALES = [_sales_hdr(8001), _sales_hdr(8004)]
_ALL_SALES    = [_sales_hdr(8001), _sales_hdr(8003), _sales_hdr(8004)]

# DUP_CLAIM crafted set (Series=6 purchases)
# 7001 + 7002: same CardCode + NumAtCard + DocTotal → dup pair → FLAGGED
# 7003:        same CardCode + DocTotal, different NumAtCard → near-miss → NOT flagged
_PERIOD_PURCH = [
    _purch_hdr(7001, "V-DUP-A", "INV-VENDOR-001", 1500.00),
    _purch_hdr(7002, "V-DUP-A", "INV-VENDOR-001", 1500.00),
    _purch_hdr(7003, "V-DUP-A", "INV-VENDOR-002", 1500.00),
]

_CRAFTED_LISTING_DATA = {
    "period_sales_headers": _PERIOD_SALES,
    "period_purch_headers": _PERIOD_PURCH,
    "all_sales_headers":    _ALL_SALES,
    "all_purch_headers":    _PERIOD_PURCH,  # not consumed by detect_dup_claims
}


def _patch_listing(monkeypatch):
    monkeypatch.setattr(
        "orchestrator.chain.fetch_listing_data",
        lambda cfg, p: _CRAFTED_LISTING_DATA,
    )


# ---------------------------------------------------------------------------
# Shared fixture: run chain once; all tests share the result
# ---------------------------------------------------------------------------

@pytest.fixture()
def crafted_result(cfg, monkeypatch):
    """Run the full chain (main steps patched, listing data crafted)."""
    _patch_main_chain(monkeypatch)
    _patch_listing(monkeypatch)
    compile_out, gate_results = run_chain(cfg, _PERIOD)
    return compile_out, gate_results


@pytest.fixture()
def compile_out(crafted_result):
    return crafted_result[0]


@pytest.fixture()
def gate_results(crafted_result):
    return crafted_result[1]


@pytest.fixture()
def report_model(cfg, compile_out):
    return build_report(compile_out, cfg, generated_at="2026-06-10T00:00:00+00:00")


# ---------------------------------------------------------------------------
# SEQ_GAP assertions
# ---------------------------------------------------------------------------

class TestSeqGapCrafted:

    def _seq_gaps(self, compile_out):
        return [f for f in compile_out["listing_findings"] if f["check"] == "SEQ_GAP"]

    def test_8002_truly_absent_flagged(self, compile_out):
        gap_nums = [f["gap_doc_num"] for f in self._seq_gaps(compile_out)]
        assert 8002 in gap_nums, (
            f"DocNum 8002 absent from all company records within range [8001,8004] "
            f"— must be flagged SEQ_GAP; gaps found: {gap_nums}"
        )

    def test_8003_other_period_not_flagged(self, compile_out):
        gap_nums = [f["gap_doc_num"] for f in self._seq_gaps(compile_out)]
        assert 8003 not in gap_nums, (
            "DocNum 8003 is within range but present in all_records (other period) "
            "— must NOT be flagged; this is the discriminating period-boundary case"
        )

    def test_exactly_one_seq_gap_finding(self, compile_out):
        gaps = self._seq_gaps(compile_out)
        assert len(gaps) == 1, (
            f"Expected exactly 1 SEQ_GAP finding (DocNum 8002); "
            f"got {len(gaps)}: {[f['gap_doc_num'] for f in gaps]}"
        )

    def test_8001_and_8004_not_flagged(self, compile_out):
        gap_nums = {f["gap_doc_num"] for f in self._seq_gaps(compile_out)}
        assert 8001 not in gap_nums, "8001 is an active period record — not a gap"
        assert 8004 not in gap_nums, "8004 is an active period record — not a gap"

    def test_finding_schema(self, compile_out):
        gap = self._seq_gaps(compile_out)[0]
        assert gap["check"] == "SEQ_GAP"
        assert gap["gap_doc_num"] == 8002
        assert gap["series"] == 1
        assert gap["series_min"] == 8001
        assert gap["series_max"] == 8004
        assert "§10.1(c)(i)" in gap["basis"]
        assert "candidate" in gap["note"]

    def test_description_uses_candidate_language(self, compile_out):
        gap = self._seq_gaps(compile_out)[0]
        desc = gap.get("description", "").lower()
        for forbidden in ("must", "is a violation", "non-compliant"):
            assert forbidden not in desc, (
                f"SEQ_GAP description must not assert verdict: {desc!r}"
            )


# ---------------------------------------------------------------------------
# DUP_CLAIM assertions
# ---------------------------------------------------------------------------

class TestDupClaimCrafted:

    def _dup_claims(self, compile_out):
        return [f for f in compile_out["listing_findings"] if f["check"] == "DUP_CLAIM"]

    def test_dup_pair_7002_flagged(self, compile_out):
        pairs = [(f["doc_num"], f["duplicate_of"]) for f in self._dup_claims(compile_out)]
        assert (7002, 7001) in pairs, (
            f"DocNums 7001+7002 share CardCode+NumAtCard+DocTotal — "
            f"(7002, 7001) must be a DUP_CLAIM finding; got {pairs}"
        )

    def test_near_miss_7003_not_flagged(self, compile_out):
        all_nums = {f["doc_num"] for f in self._dup_claims(compile_out)}
        all_nums |= {f["duplicate_of"] for f in self._dup_claims(compile_out)}
        assert 7003 not in all_nums, (
            "DocNum 7003 has different NumAtCard (INV-VENDOR-002) vs 7001 (INV-VENDOR-001) "
            "— near-miss must NOT be flagged as DUP_CLAIM"
        )

    def test_exactly_one_dup_claim_finding(self, compile_out):
        dups = self._dup_claims(compile_out)
        assert len(dups) == 1, (
            f"Expected exactly 1 DUP_CLAIM finding; "
            f"got {len(dups)}: {[(f['doc_num'],f['duplicate_of']) for f in dups]}"
        )

    def test_finding_schema(self, compile_out):
        dup = self._dup_claims(compile_out)[0]
        assert dup["check"] == "DUP_CLAIM"
        assert dup["doc_num"] == 7002
        assert dup["duplicate_of"] == 7001
        assert dup["card_code"] == "V-DUP-A"
        assert dup["num_at_card"] == "INV-VENDOR-001"
        assert dup["doc_total"] == 1500.00
        assert "§10.1(d)(i)" in dup["basis"]
        assert "candidate" in dup["note"]

    def test_description_uses_candidate_language(self, compile_out):
        dup = self._dup_claims(compile_out)[0]
        desc = dup.get("description", "").lower()
        for forbidden in ("must", "is a violation", "non-compliant"):
            assert forbidden not in desc


# ---------------------------------------------------------------------------
# listing_findings key and combined count
# ---------------------------------------------------------------------------

class TestListingFindingsKey:

    def test_listing_findings_key_present(self, compile_out):
        assert "listing_findings" in compile_out

    def test_total_listing_findings_count(self, compile_out):
        findings = compile_out["listing_findings"]
        assert len(findings) == 2, (
            f"Expected 2 total listing findings (1 SEQ_GAP + 1 DUP_CLAIM); "
            f"got {len(findings)}: {[f['check'] for f in findings]}"
        )


# ---------------------------------------------------------------------------
# PDF render: section renders without error
# ---------------------------------------------------------------------------

class TestCraftedChainRenders:

    def test_pdf_renders_without_error(self, report_model, tmp_path):
        out = tmp_path / "t210_crafted.pdf"
        render_pdf(report_model, out)
        assert out.exists(), "PDF was not written"
        assert out.stat().st_size > 1024, "PDF appears empty"

    def test_listing_section_populated_in_model(self, report_model):
        lf = report_model.listing_findings
        assert lf is not None
        assert len(lf.seq_gap_findings) == 1
        assert len(lf.dup_claim_findings) == 1
        assert lf.seq_gap_findings[0]["gap_doc_num"] == 8002
        assert lf.dup_claim_findings[0]["doc_num"] == 7002


# ---------------------------------------------------------------------------
# Not-Examined suppression: both checks produced findings → both items removed
# ---------------------------------------------------------------------------

class TestCraftedNotExaminedSuppression:

    def test_seq_gap_item_suppressed(self, report_model):
        combined = " ".join(report_model.not_examined.items).lower()
        assert "sequence gap detection" not in combined, (
            "SEQ_GAP findings present — Not-Examined 'sequence gap detection' item "
            "must be suppressed from the report"
        )

    def test_dup_claim_item_suppressed(self, report_model):
        combined = " ".join(report_model.not_examined.items).lower()
        assert "duplicate input-tax claims" not in combined, (
            "DUP_CLAIM findings present — Not-Examined 'duplicate input-tax claims' "
            "item must be suppressed from the report"
        )

    def test_other_items_intact(self, report_model):
        combined = " ".join(report_model.not_examined.items).lower()
        for expected in [
            "manual journal",
            "partial-exemption",
            "reverse charge",
            "declared-vs-computed",
            "time-of-supply",
        ]:
            assert expected in combined, (
                f"Expected '{expected}' still in Not-Examined after suppression; "
                f"it should only suppress SEQ_GAP and DUP_CLAIM items"
            )


# ---------------------------------------------------------------------------
# BOX-ISOLATION: listing checks must not mutate F5 box values
# ---------------------------------------------------------------------------

class TestBoxIsolationCrafted:

    def test_boxes_match_crafted_calc(self, compile_out):
        """F5 boxes in compile output must equal the patched _make_calc values."""
        boxes = compile_out["calculate"]["boxes"]
        assert boxes["box_1_standard_rated_sales"] == 100.0
        assert boxes["box_2_zero_rated_sales"] == 0.0
        assert boxes["box_3_exempt_sales"] == 0.0
        assert boxes["box_4_total_sales"] == 100.0
        assert boxes["box_5_taxable_purchases"] == 50.0
        assert boxes["box_6_output_tax"] == 9.0
        assert boxes["box_7_input_tax"] == 4.0
        assert boxes["box_8_net_gst"] == 5.0

    def test_chain_completed_without_box_isolation_violation(self, compile_out):
        """If BOX-ISOLATION RuntimeError had fired, the fixture would have errored.

        The fact that compile_out is populated proves the assertion in chain.py
        (result["calculate"]["boxes"] != _boxes_before → RuntimeError) did not fire.
        """
        assert compile_out["listing_findings"] is not None
        # Cross-check: boxes still intact (belt-and-suspenders)
        assert compile_out["calculate"]["boxes"]["box_8_net_gst"] == 5.0

    def test_gate_results_all_passed(self, gate_results):
        """All five gates must have passed on the crafted run."""
        assert gate_results["all_passed"] is True
        assert len(gate_results["gates"]) == 5
        for g in gate_results["gates"]:
            assert g["passed"] is True, f"Gate '{g['name']}' failed: {g}"
