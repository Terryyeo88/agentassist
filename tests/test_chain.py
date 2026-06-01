"""
Hermetic acceptance tests for orchestrator/chain.py.
No live SAP — step functions are monkeypatched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Trigger sys.path setup (mcp-servers/custom) by importing from orchestrator.
# sap_b1_server will be in sys.modules after this.
from orchestrator.chain import run_chain
from orchestrator.exceptions import GateFailure

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402 — path set above

from config.loader import ClientConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures
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


def _make_manifest(doc_nums=None):
    doc_nums = doc_nums if doc_nums is not None else {1, 2, 3}
    records = [
        {"doc_num": n, "doc_date": "2024-07-15", "doc_type": "sales_invoice",
         "doc_currency": "SGD", "doc_total": 100.0, "card_name": "Co", "vat_group": "SO"}
        for n in doc_nums
    ]
    return {
        "period": _PERIOD,
        "fetched_at": "2024-10-01T00:00:00+00:00",
        "records": records,
        "doc_nums": doc_nums,
        "sap_inline_count": None,
    }


def _make_calc(box_4_override=None):
    box_1, box_2, box_3 = 100.0, 0.0, 0.0
    box_4 = box_4_override if box_4_override is not None else (box_1 + box_2 + box_3)
    return {
        "period": _PERIOD,
        "currency": "SGD",
        "boxes": {
            "box_1_standard_rated_sales": box_1,
            "box_2_zero_rated_sales": box_2,
            "box_3_exempt_sales": box_3,
            "box_4_total_sales": box_4,
            "box_5_taxable_purchases": 50.0,
            "box_6_output_tax": 9.0,
            "box_7_input_tax": 4.0,
            "box_8_net_gst": 5.0,
        },
        "fx_invoices_requiring_conversion": [],
        # e1_candidates must match detect E1 issues for Gate 5
        "e1_candidates": [
            {"doc_num": 1, "doc_date": "2024-07-15",
             "card_name": "Co", "doc_currency": "USD", "vat_group": "SO"}
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
                "doc_count": 3,
                "known_to_mapping": True,
            }
        },
        "issues": [],
        "summary": {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 0},
    }


def _make_detect(doc_nums_for_e1=None):
    # E1 doc_nums must match calc e1_candidates for Gate 5
    e1_doc_nums = doc_nums_for_e1 if doc_nums_for_e1 is not None else [1]
    issues = [
        {
            "severity": "HIGH",
            "error_code": "E1",
            "doc_num": n,
            "doc_date": "2024-07-15",
            "card_name": "Co",
            "description": "FX invoice with SO",
            "recommendation": "Reclassify as ZR.",
        }
        for n in e1_doc_nums
    ]
    return {
        "period": _PERIOD,
        "severity_counts": {"HIGH": len(issues), "MEDIUM": 0, "LOW": 0},
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Helper: patch all external dependencies so the chain runs hermetically
# ---------------------------------------------------------------------------

def _patch_chain(monkeypatch, manifest=None, calc=None, cls=None, det=None, tmp_path=None):
    manifest = manifest if manifest is not None else _make_manifest()
    calc     = calc     if calc     is not None else _make_calc()
    cls      = cls      if cls      is not None else _make_classify()
    det      = det      if det      is not None else _make_detect()

    monkeypatch.setattr(sap_b1_server, "configure_client", lambda *a, **kw: None)
    monkeypatch.setattr("orchestrator.chain.fetch",      lambda cfg, p: manifest)
    monkeypatch.setattr("orchestrator.chain.calculate",  lambda cfg, p: calc)
    monkeypatch.setattr("orchestrator.chain.classify",   lambda cfg, p: cls)
    monkeypatch.setattr("orchestrator.chain.detect",     lambda cfg, p: det)

    # Redirect file writes to tmp_path to keep tests side-effect-free
    if tmp_path is not None:
        monkeypatch.setattr("orchestrator.chain._OUTPUT_DIR", tmp_path)


# ---------------------------------------------------------------------------
# Test: clean run returns a valid ReportInput
# ---------------------------------------------------------------------------

class TestRunChainClean:
    def test_returns_report_input_on_all_gates_pass(self, cfg, monkeypatch, tmp_path):
        _patch_chain(monkeypatch, tmp_path=tmp_path)
        report, out_path = run_chain(cfg, _PERIOD)

        assert isinstance(report, dict)
        assert "boxes" in report
        assert "issues" in report
        assert "period" in report
        assert "items_examined" in report
        assert "generated_at" in report

    def test_output_json_written(self, cfg, monkeypatch, tmp_path):
        _patch_chain(monkeypatch, tmp_path=tmp_path)
        _, out_path = run_chain(cfg, _PERIOD)
        assert out_path.exists()

    def test_items_examined_counts_records(self, cfg, monkeypatch, tmp_path):
        _patch_chain(monkeypatch, tmp_path=tmp_path)
        report, _ = run_chain(cfg, _PERIOD)
        # manifest has 3 sales_invoice records
        assert report["items_examined"].get("sales_invoice") == 3

    def test_issues_sorted_high_first(self, cfg, monkeypatch, tmp_path):
        det = _make_detect()
        det["issues"].append({
            "severity": "MEDIUM", "error_code": "E2",
            "doc_num": 2, "doc_date": "2024-07-15",
            "card_name": "Co", "description": "Tax on exempt",
            "recommendation": "Fix.",
        })
        det["severity_counts"]["MEDIUM"] = 1
        # Gate 5 only checks E1, and calc.e1_candidates={1} vs detect E1={1} ✓
        _patch_chain(monkeypatch, det=det, tmp_path=tmp_path)
        report, _ = run_chain(cfg, _PERIOD)
        sevs = [i["severity"] for i in report["issues"]]
        assert sevs == sorted(sevs, key=lambda s: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[s])

    def test_gate1_warning_surfaced_when_inline_count_none(self, cfg, monkeypatch, tmp_path):
        _patch_chain(monkeypatch, tmp_path=tmp_path)
        report, _ = run_chain(cfg, _PERIOD)
        assert any("Gate 1" in w for w in report["warnings"])


# ---------------------------------------------------------------------------
# Gate 2 acceptance test (replaces scope-doc "hand-edit a fetched record")
# ---------------------------------------------------------------------------

class TestGate2Acceptance:
    def test_corrupt_box4_halts_with_box4_in_message(self, cfg, monkeypatch, tmp_path):
        # box_1+box_2+box_3 = 100, but box_4 set to 999 → delta = 899
        bad_calc = _make_calc(box_4_override=999.0)
        _patch_chain(monkeypatch, calc=bad_calc, tmp_path=tmp_path)
        with pytest.raises(GateFailure) as exc_info:
            run_chain(cfg, _PERIOD)
        assert "box-4" in str(exc_info.value)

    def test_corrupt_box4_message_contains_delta(self, cfg, monkeypatch, tmp_path):
        bad_calc = _make_calc(box_4_override=999.0)
        _patch_chain(monkeypatch, calc=bad_calc, tmp_path=tmp_path)
        with pytest.raises(GateFailure) as exc_info:
            run_chain(cfg, _PERIOD)
        # delta = |999 - 100| = 899
        assert "899." in str(exc_info.value)

    def test_clean_boxes_do_not_halt(self, cfg, monkeypatch, tmp_path):
        _patch_chain(monkeypatch, tmp_path=tmp_path)
        run_chain(cfg, _PERIOD)  # must not raise


# ---------------------------------------------------------------------------
# Individual gate failure paths through run_chain
# ---------------------------------------------------------------------------

class TestGateFailuresViaChain:
    def test_gate3_summary_mismatch_halts(self, cfg, monkeypatch, tmp_path):
        bad_cls = _make_classify()
        bad_cls["summary"]["total"] = 99  # mismatch: len(issues)=0
        _patch_chain(monkeypatch, cls=bad_cls, tmp_path=tmp_path)
        with pytest.raises(GateFailure, match="Gate 3"):
            run_chain(cfg, _PERIOD)

    def test_gate4_dangling_ref_halts(self, cfg, monkeypatch, tmp_path):
        bad_det = _make_detect(doc_nums_for_e1=[999])  # 999 not in manifest.doc_nums {1,2,3}
        # Fix Gate 5 by giving calc matching e1_candidates
        bad_calc = _make_calc()
        bad_calc["e1_candidates"] = [
            {"doc_num": 999, "doc_date": "2024-07-15",
             "card_name": "Co", "doc_currency": "USD", "vat_group": "SO"}
        ]
        _patch_chain(monkeypatch, calc=bad_calc, det=bad_det, tmp_path=tmp_path)
        with pytest.raises(GateFailure, match="Gate 4"):
            run_chain(cfg, _PERIOD)

    def test_gate5_e1_set_mismatch_halts(self, cfg, monkeypatch, tmp_path):
        # calc e1_candidates has doc_num=1, detect has doc_num=2 → sets differ
        bad_det = _make_detect(doc_nums_for_e1=[2])
        # manifest has {1,2,3} so Gate 4 passes
        _patch_chain(monkeypatch, det=bad_det, tmp_path=tmp_path)
        with pytest.raises(GateFailure, match="Gate 5"):
            run_chain(cfg, _PERIOD)
