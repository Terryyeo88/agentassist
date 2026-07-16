"""
tests/test_document_dup_isolation.py — FAILING-FIRST listing-isolation test for the
NEW same-day duplicate-purchase surfacer.

This SUPERSEDES the vacuously-green sibling in tests/test_document_dup_chain.py
(test_listing_findings_unaffected_by_dup_check), which asserts only `listing_findings
== []` and therefore passes even before the feature exists. The append-only-test hook
prevented strengthening that sibling in place, so the meaningful (RED-now) isolation
assertion lives here: it first proves the dup check FIRED (a finding under its OWN key)
and only then asserts the finding never leaked into listing_findings.

RED by design: pre-implementation result has no "document_dup_findings" key, so the
"check fired" assertion fails. Hermetic harness replicated from tests/test_chain.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from orchestrator.chain import run_chain

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402 — path set above

from config.loader import ClientConfig  # noqa: E402


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


def _manifest_with_collision():
    records = [
        _purch(501, "2024-08-01", 1200.00),
        _purch(502, "2024-08-01", 1200.00),
    ]
    return {
        "period": _PERIOD,
        "fetched_at": "2024-10-01T00:00:00+00:00",
        "records": records,
        "doc_nums": {501, 502},
        "sap_inline_count": None,
    }


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


def _patch_chain(monkeypatch, manifest):
    monkeypatch.setattr(sap_b1_server, "configure_client", lambda *a, **kw: None)
    monkeypatch.setattr("orchestrator.chain.fetch",     lambda cfg, p: manifest)
    monkeypatch.setattr("orchestrator.chain.calculate", lambda cfg, p: _calc())
    monkeypatch.setattr("orchestrator.chain.classify",  lambda cfg, p: _classify())
    monkeypatch.setattr("orchestrator.chain.detect",    lambda cfg, p: _detect())
    monkeypatch.setattr("orchestrator.chain.fetch_listing_data", lambda cfg, p: {
        "period_sales_headers": [], "period_purch_headers": [],
        "all_sales_headers": [],   "all_purch_headers": [],
    })

    def _guard(*a, **kw):
        raise AssertionError("real SAP contact attempted in hermetic test")
    monkeypatch.setattr(sap_b1_server.SAPB1Client, "login", _guard)
    monkeypatch.setattr(sap_b1_server.SAPB1Client, "request", _guard)


class TestDupCheckDoesNotLeakIntoListing:

    def test_dup_finding_stays_out_of_listing_findings(self, cfg, monkeypatch):
        _patch_chain(monkeypatch, _manifest_with_collision())
        result, _ = run_chain(cfg, _PERIOD)

        # 1) The check FIRED — the collision is surfaced under its own key.
        assert result.get("document_dup_findings"), (
            "the colliding manifest must surface a document_dup finding, otherwise "
            "the isolation assertion below is vacuous"
        )
        assert any(f["check"] == "DUP_SAME_DAY"
                   for f in result["document_dup_findings"])

        # 2) ...and it never leaked into listing_findings (SEQ_GAP/DUP_CLAIM only).
        assert result["listing_findings"] == []
        for f in (result["listing_findings"] or []):
            assert f.get("check") != "DUP_SAME_DAY"
