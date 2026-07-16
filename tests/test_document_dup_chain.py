"""
tests/test_document_dup_chain.py — FAILING-FIRST chain-wiring + box-isolation tests
for the NEW same-day duplicate-purchase surfacer.

The chain does NOT yet attach the check; these tests are RED by design:
  - the wiring tests fail because result["document_dup_findings"] is absent;
  - the box-isolation test asserts the check actually FIRED (finding present) while
    result["calculate"]["boxes"] stays byte-identical — so it is meaningful RED now
    (no finding) and a true box-isolation guard once built;
  - the failure-contract test drives the OWN-try-block "unavailable" contract
    (document_dup_findings is None + document_dup_status.level == "unavailable").

Hermetic run_chain harness REPLICATED from tests/test_chain.py (not imported, not
edited): fetch/calculate/classify/detect/fetch_listing_data monkeypatched, plus the
no-contact SAP guard. Unlike test_chain._make_manifest (sales_invoice only), this file
builds a PURCHASE-INVOICE manifest carrying a same-day collision.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Import run_chain first — this triggers the mcp-servers/custom sys.path setup.
from orchestrator.chain import run_chain

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402 — path set above

from config.loader import ClientConfig  # noqa: E402


_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}


# ---------------------------------------------------------------------------
# Config fixture (mirrors test_chain.cfg)
# ---------------------------------------------------------------------------

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
# Purchase-invoice manifest builders
# ---------------------------------------------------------------------------

def _purch(doc_num, doc_date, doc_total, card_name="Acme Supplies Pte Ltd"):
    return {
        "doc_num": doc_num,
        "doc_date": doc_date,
        "doc_type": "purchase_invoice",
        "doc_currency": "SGD",
        "doc_total": doc_total,
        "card_name": card_name,
        "vat_group": "IP",
    }


def _manifest(records):
    doc_nums = {r["doc_num"] for r in records if r["doc_num"]}
    return {
        "period": _PERIOD,
        "fetched_at": "2024-10-01T00:00:00+00:00",
        "records": records,
        "doc_nums": doc_nums,
        "sap_inline_count": None,
    }


def _manifest_with_collision():
    # 501 and 502: same supplier + same amount + same day -> ONE finding.
    return _manifest([
        _purch(501, "2024-08-01", 1200.00),
        _purch(502, "2024-08-01", 1200.00),
    ])


def _manifest_without_collision():
    # Same two docs but on different days -> no same-day collision.
    return _manifest([
        _purch(501, "2024-08-01", 1200.00),
        _purch(502, "2024-08-02", 1200.00),
    ])


# ---------------------------------------------------------------------------
# Gate-consistent step outputs (empty issues/e1 -> all five gates pass)
# ---------------------------------------------------------------------------

def _calc():
    return {
        "period": _PERIOD,
        "currency": "SGD",
        "boxes": {
            "box_1_standard_rated_sales": 0.0,
            "box_2_zero_rated_sales": 0.0,
            "box_3_exempt_sales": 0.0,
            "box_4_total_sales": 0.0,
            "box_5_taxable_purchases": 1200.0,
            "box_6_output_tax": 0.0,
            "box_7_input_tax": 84.0,
            "box_8_net_gst": -84.0,
        },
        "fx_invoices_requiring_conversion": [],
        "e1_candidates": [],
        "record_counts": {},
        "credit_note_counts": {},
        "credit_notes_applied": [],
        "anomalies": [],
    }


def _classify():
    return {
        "period": _PERIOD,
        "expected_rate": 0.07,
        "vatgroup_inventory": {
            "IP": {
                "gst_category": "Standard-rated input",
                "side": "purchases",
                "lt_box": "box_5_taxable_purchases",
                "tt_box": "box_7_input_tax",
                "doc_count": 2,
                "known_to_mapping": True,
            }
        },
        "issues": [],
        "summary": {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 0},
    }


def _detect():
    return {
        "period": _PERIOD,
        "severity_counts": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
        "issues": [],
    }


# ---------------------------------------------------------------------------
# Hermetic patch (replicated from test_chain._patch_chain)
# ---------------------------------------------------------------------------

def _patch_chain(monkeypatch, manifest):
    monkeypatch.setattr(sap_b1_server, "configure_client", lambda *a, **kw: None)
    monkeypatch.setattr("orchestrator.chain.fetch",     lambda cfg, p: manifest)
    monkeypatch.setattr("orchestrator.chain.calculate", lambda cfg, p: _calc())
    monkeypatch.setattr("orchestrator.chain.classify",  lambda cfg, p: _classify())
    monkeypatch.setattr("orchestrator.chain.detect",    lambda cfg, p: _detect())
    # Empty success-shaped listing -> listing_findings == [] (SEQ_GAP/DUP_CLAIM none).
    monkeypatch.setattr("orchestrator.chain.fetch_listing_data", lambda cfg, p: {
        "period_sales_headers": [], "period_purch_headers": [],
        "all_sales_headers": [],   "all_purch_headers": [],
    })
    # No-contact guard: any real SAP login/request fails fast.
    def _guard(*a, **kw):
        raise AssertionError("real SAP contact attempted in hermetic test")
    monkeypatch.setattr(sap_b1_server.SAPB1Client, "login", _guard)
    monkeypatch.setattr(sap_b1_server.SAPB1Client, "request", _guard)


# ---------------------------------------------------------------------------
# Wiring: the collision is surfaced under document_dup_findings, NOT listing_findings
# ---------------------------------------------------------------------------

class TestDocumentDupWiring:

    def test_collision_surfaced_in_document_dup_findings(self, cfg, monkeypatch):
        _patch_chain(monkeypatch, _manifest_with_collision())
        result, _ = run_chain(cfg, _PERIOD)

        assert "document_dup_findings" in result, (
            "chain must attach result['document_dup_findings']"
        )
        findings = result["document_dup_findings"]
        assert isinstance(findings, list) and len(findings) == 1
        f = findings[0]
        assert f["check"] == "DUP_SAME_DAY"
        assert f["doc_nums"] == [501, 502]

    def test_listing_findings_unaffected_by_dup_check(self, cfg, monkeypatch):
        # listing_findings is for SEQ_GAP/DUP_CLAIM only — the dup finding must NOT
        # leak into it. The patched listing fetch is empty -> listing_findings == [].
        _patch_chain(monkeypatch, _manifest_with_collision())
        result, _ = run_chain(cfg, _PERIOD)

        assert result["listing_findings"] == []
        for f in (result["listing_findings"] or []):
            assert f.get("check") != "DUP_SAME_DAY"


# ---------------------------------------------------------------------------
# Box-isolation: boxes byte-identical with vs without the colliding pair
# ---------------------------------------------------------------------------

class TestBoxIsolation:

    def test_boxes_byte_identical_regardless_of_collision(self, cfg, monkeypatch):
        # WITH the colliding pair: the check must actually FIRE (finding present),
        # otherwise box-isolation is a vacuous assertion.
        _patch_chain(monkeypatch, _manifest_with_collision())
        with_result, _ = run_chain(cfg, _PERIOD)
        assert with_result.get("document_dup_findings"), (
            "the colliding manifest must produce a document_dup finding — "
            "box-isolation is only meaningful when the check has fired"
        )
        boxes_with = with_result["calculate"]["boxes"]

        _patch_chain(monkeypatch, _manifest_without_collision())
        without_result, _ = run_chain(cfg, _PERIOD)
        boxes_without = without_result["calculate"]["boxes"]

        assert boxes_with == boxes_without, (
            "F5 boxes must be byte-identical whether or not the dup check surfaced a "
            "collision — the surfacer must never mutate the deterministic chain"
        )


# ---------------------------------------------------------------------------
# Failure contract: OWN try block -> None findings + unavailable status
# ---------------------------------------------------------------------------

class TestFailureContract:

    def test_thrown_check_yields_none_and_unavailable_status(self, cfg, monkeypatch):
        _patch_chain(monkeypatch, _manifest_with_collision())

        # Force the detector (imported into chain's namespace, mirroring
        # detect_dup_claims) to raise; the chain's own try block must degrade to
        # the "unavailable" contract rather than halting.
        def _boom(*a, **kw):
            raise RuntimeError("simulated detector failure")
        monkeypatch.setattr("orchestrator.chain.detect_same_day_dups", _boom)

        result, _ = run_chain(cfg, _PERIOD)

        assert result["document_dup_findings"] is None
        assert result["document_dup_status"]["level"] == "unavailable"
        assert result["document_dup_status"]["reason"]  # non-empty execution fact
