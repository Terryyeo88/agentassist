"""
Tests for report/enrich.py.
Uses tests/fixtures/chain-run-sample.json as the live fixture
(SBODEMOSG Q3 2024 chain run).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from report.contract import load_compile_output
from report.enrich import EnrichedFinding, enrich

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"


@pytest.fixture(scope="module")
def data() -> dict:
    return load_compile_output(FIXTURE)


@pytest.fixture(scope="module")
def findings(data) -> list[EnrichedFinding]:
    return enrich(data)


# ── Counts and uniqueness ─────────────────────────────────────────────────────

class TestCounts:
    def test_one_finding_per_doc_num_error_code(self, findings):
        keys = [(f.doc_num, f.error_code) for f in findings]
        assert len(keys) == len(set(keys)), "duplicate (doc_num, error_code) pairs found"

    def test_e1_count_is_8_distinct_docs(self, findings):
        e1 = [f for f in findings if f.error_code == "E1"]
        assert len(e1) == 8

    def test_no_gst_reg_count_is_7(self, findings):
        ngr = [f for f in findings if f.error_code == "NO_GST_REG"]
        assert len(ngr) == 7

    def test_e2_count_is_3(self, findings):
        e2 = [f for f in findings if f.error_code == "E2"]
        assert len(e2) == 3


# ── Multi-line collapse ───────────────────────────────────────────────────────

class TestLineCollapse:
    def test_doc_974_e1_has_line_count_3(self, findings):
        f = next(x for x in findings if x.doc_num == 974 and x.error_code == "E1")
        assert f.line_count == 3

    def test_doc_967_e1_has_line_count_2(self, findings):
        f = next(x for x in findings if x.doc_num == 967 and x.error_code == "E1")
        assert f.line_count == 2

    def test_doc_974_e1_line_total_equals_sum_of_classify_lines(self, data, findings):
        expected_lt = sum(
            i["line_total"]
            for i in data["classify"]["issues"]
            if i["doc_num"] == 974 and i["error_code"] == "E1"
        )
        expected_tt = sum(
            i["tax_total"]
            for i in data["classify"]["issues"]
            if i["doc_num"] == 974 and i["error_code"] == "E1"
        )
        f = next(x for x in findings if x.doc_num == 974 and x.error_code == "E1")
        assert abs(f.line_total - expected_lt) < 0.001
        assert abs(f.tax_total - expected_tt) < 0.001


# ── Manifest backfill ─────────────────────────────────────────────────────────

class TestManifestBackfill:
    def test_no_gst_reg_605_vat_group_is_bl_from_manifest(self, findings):
        f = next(x for x in findings if x.doc_num == 605 and x.error_code == "NO_GST_REG")
        assert f.vat_group == "BL"

    def test_no_gst_reg_605_line_total_is_none(self, findings):
        f = next(x for x in findings if x.doc_num == 605 and x.error_code == "NO_GST_REG")
        assert f.line_total is None

    def test_no_gst_reg_605_doc_total_matches_manifest(self, data, findings):
        manifest_605 = next(
            r for r in data["fetch_manifest"]["records"] if r["doc_num"] == 605
        )
        f = next(x for x in findings if x.doc_num == 605 and x.error_code == "NO_GST_REG")
        assert f.doc_total is not None
        assert f.doc_total == manifest_605["doc_total"]


# ── Routing and Appendix 1 wording ───────────────────────────────────────────

class TestRoutingAndWording:
    def test_every_finding_has_non_empty_appendix1_category(self, findings):
        for f in findings:
            assert f.appendix1_category, (
                f"empty appendix1_category on ({f.doc_num}, {f.error_code})"
            )

    def test_every_finding_has_valid_template_ref(self, findings):
        for f in findings:
            assert 1 <= f.template_ref["number"] <= 7, (
                f"template number {f.template_ref['number']} out of range "
                f"on ({f.doc_num}, {f.error_code})"
            )
            assert f.template_ref["label"] != ""

    def test_e1_findings_all_route_to_template_2(self, findings):
        for f in findings:
            if f.error_code == "E1":
                assert f.template_ref["number"] == 2, (
                    f"E1 doc {f.doc_num} routed to {f.template_ref['number']}, expected 2"
                )

    def test_e2_bl_findings_route_to_template_6(self, findings):
        for f in findings:
            if f.error_code == "E2" and f.vat_group == "BL":
                assert f.template_ref["number"] == 6

    def test_e2_nr_findings_route_to_template_6(self, findings):
        for f in findings:
            if f.error_code == "E2" and f.vat_group == "NR":
                assert f.template_ref["number"] == 6

    def test_no_gst_reg_findings_all_route_to_template_6(self, findings):
        for f in findings:
            if f.error_code == "NO_GST_REG":
                assert f.template_ref["number"] == 6

    def test_e1_appendix1_contains_wrong_classification(self, findings):
        for f in findings:
            if f.error_code == "E1":
                assert "Wrong classification" in f.appendix1_category
                break
