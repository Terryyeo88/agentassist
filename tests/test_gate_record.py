"""
Tests for audit_bundle.gate_record.build_gate_results, exercised both directly
and through run_chain (via monkeypatched steps).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from audit_bundle.gate_record import build_gate_results
from orchestrator.chain import run_chain
from orchestrator.exceptions import GateFailure

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402

from config.loader import ClientConfig  # noqa: E402

_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}


# ---------------------------------------------------------------------------
# Shared helpers (self-contained; no imports from test_chain)
# ---------------------------------------------------------------------------

@pytest.fixture()
def cfg():
    return ClientConfig(
        client_id="test", client_name="Test", gst_registration_number="",
        applicable_gst_rate=0.07, service_layer_url="https://fake",
        company_db="TEST", username="u", password="p", ssl_verify=False,
        fiscal_year_start_month=1, custom_vat_groups={},
        completeness_threshold=0.1, reviewer_name="", firm_name="",
    )


def _make_manifest():
    doc_nums = {1}
    return {
        "period": _PERIOD, "fetched_at": "2024-10-01T00:00:00+00:00",
        "records": [{"doc_num": 1, "doc_date": "2024-07-15", "doc_type": "sales_invoice",
                     "doc_currency": "SGD", "doc_total": 100.0, "card_name": "Co", "vat_group": "SO"}],
        "doc_nums": doc_nums, "sap_inline_count": None,
    }


def _make_calc(box_4_override=None):
    box_1, box_2, box_3 = 100.0, 0.0, 0.0
    box_4 = box_4_override if box_4_override is not None else (box_1 + box_2 + box_3)
    return {
        "period": _PERIOD, "currency": "SGD",
        "boxes": {
            "box_1_standard_rated_sales": box_1, "box_2_zero_rated_sales": box_2,
            "box_3_exempt_sales": box_3, "box_4_total_sales": box_4,
            "box_5_taxable_purchases": 50.0, "box_6_output_tax": 9.0,
            "box_7_input_tax": 4.0, "box_8_net_gst": 5.0,
        },
        "fx_invoices_requiring_conversion": [],
        "e1_candidates": [{"doc_num": 1, "doc_date": "2024-07-15",
                           "card_name": "Co", "doc_currency": "USD", "vat_group": "SO"}],
        "record_counts": {}, "credit_note_counts": {}, "credit_notes_applied": [],
        "anomalies": [],
    }


def _make_classify():
    return {
        "period": _PERIOD, "expected_rate": 0.07,
        "vatgroup_inventory": {"SO": {"gst_category": "Standard-rated output", "side": "sales",
                                      "lt_box": "box_1_standard_rated_sales", "tt_box": "box_6_output_tax",
                                      "doc_count": 1, "known_to_mapping": True}},
        "issues": [], "summary": {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 0},
    }


def _make_detect():
    return {
        "period": _PERIOD,
        "severity_counts": {"HIGH": 1, "MEDIUM": 0, "LOW": 0},
        "issues": [{"severity": "HIGH", "error_code": "E1", "doc_num": 1,
                    "doc_date": "2024-07-15", "card_name": "Co",
                    "description": "FX+SO", "recommendation": "Reclassify as ZR."}],
    }


def _patch(monkeypatch, calc=None):
    manifest = _make_manifest()
    c = calc if calc is not None else _make_calc()
    cls = _make_classify()
    det = _make_detect()
    monkeypatch.setattr(sap_b1_server, "configure_client", lambda *a, **kw: None)
    monkeypatch.setattr("orchestrator.chain.fetch",     lambda cfg, p: manifest)
    monkeypatch.setattr("orchestrator.chain.calculate", lambda cfg, p: c)
    monkeypatch.setattr("orchestrator.chain.classify",  lambda cfg, p: cls)
    monkeypatch.setattr("orchestrator.chain.detect",    lambda cfg, p: det)


# ---------------------------------------------------------------------------
# Unit tests for build_gate_results directly
# ---------------------------------------------------------------------------

def test_build_all_passed():
    records = [
        {"gate": 1, "name": "record-count", "after_step": "fetch",
         "status": "PASS", "passed": True, "checked": {"fetched_count": 10}},
        {"gate": 2, "name": "box-reconciliation", "after_step": "calculate",
         "status": "PASS", "passed": True, "checked": {"box_4": 100.0}},
    ]
    result = build_gate_results(records)
    assert result["all_passed"] is True
    assert len(result["gates"]) == 2


def test_build_warn_pass_still_passes():
    records = [
        {"gate": 1, "name": "record-count", "after_step": "fetch",
         "status": "WARN_PASS", "passed": True, "checked": {"sap_inline_count": None},
         "message": "unavailable"},
    ]
    result = build_gate_results(records)
    assert result["all_passed"] is True
    assert result["gates"][0]["status"] == "WARN_PASS"
    assert "message" in result["gates"][0]


def test_build_one_fail_sets_all_passed_false():
    records = [
        {"gate": 1, "name": "record-count", "after_step": "fetch",
         "status": "PASS", "passed": True, "checked": {}},
        {"gate": 2, "name": "box-reconciliation", "after_step": "calculate",
         "status": "FAIL", "passed": False, "checked": {"box_4": 999.0},
         "message": "Gate 2 [box-4]: ..."},
    ]
    result = build_gate_results(records)
    assert result["all_passed"] is False
    assert result["gates"][1]["status"] == "FAIL"
    assert result["gates"][1]["checked"]["box_4"] == 999.0


def test_build_message_omitted_when_absent():
    records = [
        {"gate": 2, "name": "box-reconciliation", "after_step": "calculate",
         "status": "PASS", "passed": True, "checked": {}},
    ]
    result = build_gate_results(records)
    assert "message" not in result["gates"][0]


def test_build_empty_records():
    result = build_gate_results([])
    assert result["all_passed"] is True
    assert result["gates"] == []


# ---------------------------------------------------------------------------
# Integration: clean run via run_chain → all 5 gates passed with checked dicts
# ---------------------------------------------------------------------------

def test_clean_run_all_5_gates_passed(cfg, monkeypatch):
    _patch(monkeypatch)
    _, gate_results = run_chain(cfg, _PERIOD)

    assert gate_results["all_passed"] is True
    assert len(gate_results["gates"]) == 5

    for entry in gate_results["gates"]:
        assert entry["passed"] is True
        assert isinstance(entry["checked"], dict)
        assert len(entry["checked"]) > 0


def test_clean_run_gate1_is_warn_pass(cfg, monkeypatch):
    # Manifest has sap_inline_count=None → WARN_PASS
    _patch(monkeypatch)
    _, gate_results = run_chain(cfg, _PERIOD)
    g1 = gate_results["gates"][0]
    assert g1["gate"] == 1
    assert g1["status"] == "WARN_PASS"
    assert g1["passed"] is True
    assert g1["checked"]["sap_inline_count"] is None
    assert "message" in g1


def test_clean_run_gate2_checked_has_box_values(cfg, monkeypatch):
    _patch(monkeypatch)
    _, gate_results = run_chain(cfg, _PERIOD)
    g2 = gate_results["gates"][1]
    assert g2["gate"] == 2
    assert "box_4" in g2["checked"]
    assert "box_1_2_3_sum" in g2["checked"]
    assert "tolerance" in g2["checked"]


# ---------------------------------------------------------------------------
# Integration: corrupted box_4 → gate_2 FAIL with checked box values on exc
# ---------------------------------------------------------------------------

def test_corrupt_box4_gate2_fail_exc_has_checked(cfg, monkeypatch):
    bad_calc = _make_calc(box_4_override=999.0)
    _patch(monkeypatch, calc=bad_calc)
    with pytest.raises(GateFailure) as exc_info:
        run_chain(cfg, _PERIOD)
    exc = exc_info.value
    assert hasattr(exc, "checked")
    assert exc.checked.get("box_4") == 999.0
    # box_1 + box_2 + box_3 = 100.0
    assert exc.checked.get("box_1_2_3_sum") == 100.0


def test_corrupt_box4_exc_checked_has_tolerance(cfg, monkeypatch):
    bad_calc = _make_calc(box_4_override=999.0)
    _patch(monkeypatch, calc=bad_calc)
    with pytest.raises(GateFailure) as exc_info:
        run_chain(cfg, _PERIOD)
    assert exc_info.value.checked.get("tolerance") == 0.01
