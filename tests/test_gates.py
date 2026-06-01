from __future__ import annotations

import logging
import pytest

from orchestrator.exceptions import GateFailure
from orchestrator.gates import (
    gate_1_record_count,
    gate_2_box_reconciliation,
    gate_3_inventory_consistency,
    gate_4_detect_consistency,
    gate_5_cross_tool_consistency,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _period():
    return {"start": "2024-07-01", "end": "2024-09-30"}


def _record(doc_num=1):
    return {
        "doc_num": doc_num,
        "doc_date": "2024-07-15",
        "doc_type": "sales_invoice",
        "doc_currency": "SGD",
        "doc_total": 100.0,
        "card_name": "Test Co",
        "vat_group": "SR",
    }


def _manifest(records=None, doc_nums=None, sap_inline_count=None):
    records = records if records is not None else []
    doc_nums = doc_nums if doc_nums is not None else set()
    return {
        "period": _period(),
        "fetched_at": "2024-10-01T00:00:00",
        "records": records,
        "doc_nums": doc_nums,
        "sap_inline_count": sap_inline_count,
    }


def _boxes(box_1=100.0, box_2=0.0, box_3=0.0, box_4=None,
           box_5=50.0, box_6=9.0, box_7=4.0, box_8=None):
    return {
        "box_1_standard_rated_sales": box_1,
        "box_2_zero_rated_sales": box_2,
        "box_3_exempt_sales": box_3,
        "box_4_total_sales": box_1 + box_2 + box_3 if box_4 is None else box_4,
        "box_5_taxable_purchases": box_5,
        "box_6_output_tax": box_6,
        "box_7_input_tax": box_7,
        "box_8_net_gst": box_6 - box_7 if box_8 is None else box_8,
    }


def _calc(boxes=None, e1_candidates=None, anomalies=None):
    return {
        "period": _period(),
        "currency": "SGD",
        "boxes": boxes if boxes is not None else _boxes(),
        "fx_invoices_requiring_conversion": [],
        "e1_candidates": e1_candidates if e1_candidates is not None else [],
        "record_counts": {},
        "credit_note_counts": {},
        "credit_notes_applied": [],
        "anomalies": anomalies if anomalies is not None else [],
    }


def _vg_entry(known=True):
    return {
        "gst_category": "Standard-rated output (sales)",
        "side": "sales",
        "lt_box": "box_1_standard_rated_sales",
        "tt_box": None,
        "doc_count": 1,
        "known_to_mapping": known,
    }


def _classify_issue(doc_num=1, vat_group="SR", error_code="E1"):
    return {
        "doc_num": doc_num,
        "doc_date": "2024-07-15",
        "doc_currency": "SGD",
        "card_name": "Test Co",
        "vat_group": vat_group,
        "line_total": 100.0,
        "tax_total": 9.0,
        "error_code": error_code,
        "description": "Test issue",
    }


def _classify(issues=None, summary=None, vatgroup_inventory=None):
    issues = issues if issues is not None else []
    return {
        "period": _period(),
        "expected_rate": 0.09,
        "vatgroup_inventory": vatgroup_inventory if vatgroup_inventory is not None else {},
        "issues": issues,
        "summary": summary if summary is not None else {
            "E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": len(issues)
        },
    }


def _detect_issue(doc_num=1, error_code="E1", severity="HIGH"):
    return {
        "severity": severity,
        "error_code": error_code,
        "doc_num": doc_num,
        "doc_date": "2024-07-15",
        "card_name": "Test Co",
        "description": "Test error",
        "recommendation": "Fix it",
    }


def _detect(issues=None, severity_counts=None):
    issues = issues if issues is not None else []
    if severity_counts is None:
        counts: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for i in issues:
            counts[i["severity"]] += 1
        severity_counts = counts
    return {
        "period": _period(),
        "severity_counts": severity_counts,
        "issues": issues,
    }


def _e1_candidate(doc_num=1):
    return {
        "doc_num": doc_num,
        "doc_date": "2024-07-15",
        "card_name": "Test Co",
        "doc_currency": "USD",
        "vat_group": "SO",
    }


# ---------------------------------------------------------------------------
# Gate 1 — record-count sanity
# ---------------------------------------------------------------------------

class TestGate1:
    def test_passes_when_counts_match(self):
        records = [_record(1)]
        manifest = _manifest(records=records, doc_nums={1}, sap_inline_count=1)
        gate_1_record_count(manifest)  # must not raise

    def test_raises_when_counts_differ(self):
        records = [_record(1)]
        manifest = _manifest(records=records, doc_nums={1}, sap_inline_count=5)
        with pytest.raises(GateFailure, match="Gate 1 \\[record-count\\]"):
            gate_1_record_count(manifest)

    def test_raises_message_contains_both_counts(self):
        records = [_record(1)]
        manifest = _manifest(records=records, doc_nums={1}, sap_inline_count=5)
        with pytest.raises(GateFailure) as exc_info:
            gate_1_record_count(manifest)
        msg = str(exc_info.value)
        assert "5" in msg   # sap_inline_count
        assert "1" in msg   # actual fetched

    def test_none_inline_count_warns_and_does_not_raise(self, caplog):
        manifest = _manifest(records=[], doc_nums=set(), sap_inline_count=None)
        with caplog.at_level(logging.WARNING, logger="orchestrator.gates"):
            gate_1_record_count(manifest)  # must not raise
        assert "Gate 1" in caplog.text
        assert "$inlinecount" in caplog.text


# ---------------------------------------------------------------------------
# Gate 2 — box reconciliation (acceptance-test gate)
# ---------------------------------------------------------------------------

class TestGate2:
    def test_passes_clean_boxes(self):
        calc = _calc(boxes=_boxes(100.0, 50.0, 10.0))
        gate_2_box_reconciliation(calc)  # must not raise

    def test_raises_box4_mismatch_message_contains_tag_and_delta(self):
        # box_1+box_2+box_3 = 100, but box_4 = 200 → delta = 100
        boxes = _boxes(box_1=100.0, box_2=0.0, box_3=0.0, box_4=200.0)
        with pytest.raises(GateFailure) as exc_info:
            gate_2_box_reconciliation(_calc(boxes=boxes))
        msg = str(exc_info.value)
        assert "box-4" in msg
        assert "100." in msg  # delta appears in the message

    def test_raises_box8_mismatch_message_contains_tag_and_delta(self):
        # box_6=9, box_7=4 → expected box_8=5, but set to 10 → delta=5
        boxes = _boxes(box_6=9.0, box_7=4.0, box_8=10.0)
        with pytest.raises(GateFailure) as exc_info:
            gate_2_box_reconciliation(_calc(boxes=boxes))
        msg = str(exc_info.value)
        assert "box-8" in msg
        assert "5." in msg

    def test_passes_within_tolerance(self):
        # delta = 0.005 < 0.01 — must pass
        boxes = _boxes(box_1=100.0, box_2=0.0, box_3=0.0, box_4=100.005)
        gate_2_box_reconciliation(_calc(boxes=boxes))  # must not raise

    def test_raises_at_tolerance_boundary(self):
        # delta = 0.02 > 0.01 — must raise
        boxes = _boxes(box_1=100.0, box_2=0.0, box_3=0.0, box_4=100.02)
        with pytest.raises(GateFailure, match="box-4"):
            gate_2_box_reconciliation(_calc(boxes=boxes))

    def test_anomalies_logged_not_raised(self, caplog):
        anomalies = [{"doc_num": 42, "issue": "unknown VatGroup 'XZ' — not in mapping"}]
        calc = _calc(anomalies=anomalies)
        with caplog.at_level(logging.WARNING, logger="orchestrator.gates"):
            gate_2_box_reconciliation(calc)  # must not raise
        assert "doc_num=42" in caplog.text


# ---------------------------------------------------------------------------
# Gate 3 — inventory consistency
# ---------------------------------------------------------------------------

class TestGate3:
    def test_passes_clean_classify(self):
        issue = _classify_issue(doc_num=1, vat_group="SR")
        classify = _classify(
            issues=[issue],
            summary={"E1": 1, "E2": 0, "E3": 0, "E4": 0, "total": 1},
            vatgroup_inventory={"SR": _vg_entry(known=True)},
        )
        gate_3_inventory_consistency(classify)  # must not raise

    def test_passes_empty_issues(self):
        classify = _classify(issues=[], vatgroup_inventory={})
        gate_3_inventory_consistency(classify)  # must not raise

    def test_raises_summary_total_mismatch(self):
        issue = _classify_issue(doc_num=1, vat_group="SR")
        classify = _classify(
            issues=[issue],
            summary={"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 99},  # wrong
            vatgroup_inventory={"SR": _vg_entry()},
        )
        with pytest.raises(GateFailure, match="Gate 3 \\[summary-count\\]"):
            gate_3_inventory_consistency(classify)

    def test_raises_vg_not_in_inventory(self):
        issue = _classify_issue(doc_num=5, vat_group="GHOST")
        classify = _classify(
            issues=[issue],
            summary={"E1": 1, "E2": 0, "E3": 0, "E4": 0, "total": 1},
            vatgroup_inventory={"SR": _vg_entry()},  # GHOST absent
        )
        with pytest.raises(GateFailure, match="Gate 3 \\[vg-reference\\]"):
            gate_3_inventory_consistency(classify)

    def test_raises_message_names_missing_vg(self):
        issue = _classify_issue(doc_num=7, vat_group="MISSING")
        classify = _classify(
            issues=[issue],
            summary={"E1": 1, "E2": 0, "E3": 0, "E4": 0, "total": 1},
            vatgroup_inventory={},
        )
        with pytest.raises(GateFailure) as exc_info:
            gate_3_inventory_consistency(classify)
        assert "MISSING" in str(exc_info.value)

    def test_unknown_mapping_warns_not_raises(self, caplog):
        classify = _classify(
            issues=[],
            summary={"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 0},
            vatgroup_inventory={"ZZ": _vg_entry(known=False)},
        )
        with caplog.at_level(logging.WARNING, logger="orchestrator.gates"):
            gate_3_inventory_consistency(classify)  # must not raise
        assert "ZZ" in caplog.text


# ---------------------------------------------------------------------------
# Gate 4 — severity-count and DocNum-reference consistency
# ---------------------------------------------------------------------------

class TestGate4:
    def test_passes_clean_detect(self):
        manifest = _manifest(doc_nums={1, 2})
        issue = _detect_issue(doc_num=1, error_code="E2", severity="MEDIUM")
        detect = _detect(issues=[issue])
        gate_4_detect_consistency(detect, manifest)  # must not raise

    def test_raises_severity_count_sum_mismatch(self):
        manifest = _manifest(doc_nums={1})
        issue = _detect_issue(doc_num=1, severity="HIGH")
        detect = _detect(
            issues=[issue],
            severity_counts={"HIGH": 99, "MEDIUM": 0, "LOW": 0},  # sum=99 != len=1
        )
        with pytest.raises(GateFailure, match="Gate 4 \\[severity-count\\]"):
            gate_4_detect_consistency(detect, manifest)

    def test_raises_dangling_doc_num(self):
        manifest = _manifest(doc_nums={1, 2})
        issue = _detect_issue(doc_num=999, error_code="E3", severity="LOW")  # 999 absent
        detect = _detect(issues=[issue])
        with pytest.raises(GateFailure, match="Gate 4 \\[dangling-ref\\]"):
            gate_4_detect_consistency(detect, manifest)

    def test_raises_dangling_ref_message_names_doc_num(self):
        manifest = _manifest(doc_nums=set())
        issue = _detect_issue(doc_num=777, severity="HIGH")
        detect = _detect(issues=[issue])
        with pytest.raises(GateFailure) as exc_info:
            gate_4_detect_consistency(detect, manifest)
        assert "777" in str(exc_info.value)

    def test_null_doc_num_skipped_not_raised(self):
        manifest = _manifest(doc_nums=set())
        completeness_issue = {
            "severity": "LOW",
            "error_code": "COMPLETENESS",
            "doc_num": None,
            "doc_date": None,
            "card_name": None,
            "description": "Missing period data",
            "recommendation": "Review",
        }
        detect = _detect(issues=[completeness_issue])
        gate_4_detect_consistency(detect, manifest)  # None doc_num must not raise

    def test_passes_empty_detect(self):
        manifest = _manifest()
        detect = _detect()
        gate_4_detect_consistency(detect, manifest)  # must not raise


# ---------------------------------------------------------------------------
# Gate 5 — cross-tool consistency
# ---------------------------------------------------------------------------

class TestGate5:
    def test_passes_empty_sets(self):
        calc = _calc()
        classify = _classify()
        detect = _detect()
        gate_5_cross_tool_consistency(calc, classify, detect)  # must not raise

    def test_passes_e1_sets_agree(self):
        calc = _calc(e1_candidates=[_e1_candidate(1), _e1_candidate(2)])
        detect = _detect(issues=[
            _detect_issue(doc_num=1, error_code="E1"),
            _detect_issue(doc_num=2, error_code="E1"),
        ])
        classify = _classify()
        gate_5_cross_tool_consistency(calc, classify, detect)  # must not raise

    def test_raises_e1_set_mismatch_calc_extra(self):
        # calc has doc 1, detect has doc 2 — sets differ
        calc = _calc(e1_candidates=[_e1_candidate(1)])
        detect = _detect(issues=[_detect_issue(doc_num=2, error_code="E1")])
        classify = _classify()
        with pytest.raises(GateFailure, match="Gate 5 \\[E1-set\\]"):
            gate_5_cross_tool_consistency(calc, classify, detect)

    def test_raises_e1_mismatch_message_names_doc_nums(self):
        calc = _calc(e1_candidates=[_e1_candidate(10)])
        detect = _detect(issues=[_detect_issue(doc_num=20, error_code="E1")])
        classify = _classify()
        with pytest.raises(GateFailure) as exc_info:
            gate_5_cross_tool_consistency(calc, classify, detect)
        msg = str(exc_info.value)
        assert "10" in msg
        assert "20" in msg

    def test_raises_unknown_vg_not_flagged_by_classify(self):
        calc = _calc(anomalies=[{"doc_num": 10, "issue": "unknown VatGroup 'ZZ' — not in mapping"}])
        classify = _classify(vatgroup_inventory={"SR": _vg_entry(known=True)})  # ZZ absent
        detect = _detect()
        with pytest.raises(GateFailure, match="Gate 5 \\[vg-unknown\\]"):
            gate_5_cross_tool_consistency(calc, classify, detect)

    def test_raises_vg_unknown_message_names_vg(self):
        calc = _calc(anomalies=[{"doc_num": 10, "issue": "unknown VatGroup 'BADCODE' — not in mapping"}])
        classify = _classify()
        detect = _detect()
        with pytest.raises(GateFailure) as exc_info:
            gate_5_cross_tool_consistency(calc, classify, detect)
        assert "BADCODE" in str(exc_info.value)

    def test_passes_unknown_vg_flagged_by_both(self):
        calc = _calc(anomalies=[{"doc_num": 10, "issue": "unknown VatGroup 'ZZ' — not in mapping"}])
        classify = _classify(vatgroup_inventory={"ZZ": _vg_entry(known=False)})
        detect = _detect()
        gate_5_cross_tool_consistency(calc, classify, detect)  # must not raise

    def test_malformed_anomaly_issue_string_does_not_raise(self):
        # split("'")[1] would IndexError — must be swallowed
        calc = _calc(anomalies=[{"doc_num": 10, "issue": "unknown VatGroup no-quotes-here"}])
        classify = _classify()
        detect = _detect()
        gate_5_cross_tool_consistency(calc, classify, detect)  # must not raise
