"""
Tests for report/sections.py and report/report.py.
Uses tests/fixtures/chain-run-sample.json (SBODEMOSG Q3 2024).
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from config.loader import ClientConfig
from report.contract import load_compile_output
from report.report import ReportModel, build_report

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def raw_data() -> dict:
    return load_compile_output(FIXTURE)


def _make_cfg(**overrides) -> ClientConfig:
    """Minimal ClientConfig for tests; no SAP connectivity."""
    base = dict(
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
    base.update(overrides)
    return ClientConfig(**base)


@pytest.fixture(scope="module")
def cfg() -> ClientConfig:
    return _make_cfg()


@pytest.fixture(scope="module")
def report(raw_data, cfg) -> ReportModel:
    return build_report(raw_data, cfg, generated_at=_GENERATED_AT)


# ── All eight sections present and non-empty ─────────────────────────────────

class TestAllSectionsPresent:
    def test_cover_present(self, report):
        assert report.cover is not None
        assert report.cover.client_name != ""

    def test_scope_present(self, report):
        assert report.scope is not None
        assert report.scope.items_examined

    def test_f5_boxes_present(self, report):
        assert report.f5_boxes is not None
        assert report.f5_boxes.attribution

    def test_findings_present(self, report):
        assert report.findings is not None
        assert report.findings.groups

    def test_cross_findings_present(self, report):
        assert report.cross_findings is not None
        assert report.cross_findings.multi_error_docs

    def test_judgment_present(self, report):
        assert report.judgment is not None
        assert report.judgment.groups

    def test_not_examined_present(self, report):
        assert report.not_examined is not None
        assert report.not_examined.items

    def test_signature_present(self, report):
        assert report.signature is not None
        assert report.signature.disclaimer != ""


# ── FindingsSection routing ───────────────────────────────────────────────────

class TestFindingsRouting:
    def _flat(self, report: ReportModel):
        return [f for g in report.findings.groups for f in g.findings]

    def _group(self, report: ReportModel, template_num: int):
        return next(
            (g for g in report.findings.groups if g.template_ref["number"] == template_num),
            None,
        )

    def test_e2_doc605_bl_routes_to_template_6(self, report):
        f = next(
            x for x in self._flat(report)
            if x.doc_num == 605 and x.error_code == "E2"
        )
        assert f.template_ref["number"] == 6

    def test_e1_doc958_routes_to_template_2(self, report):
        f = next(
            x for x in self._flat(report)
            if x.doc_num == 958 and x.error_code == "E1"
        )
        assert f.template_ref["number"] == 2

    def test_severity_order_within_template_2_group(self, report):
        g2 = self._group(report, 2)
        assert g2 is not None
        sev_values = [{"HIGH": 0, "MEDIUM": 1, "LOW": 2}[f.severity] for f in g2.findings]
        assert sev_values == sorted(sev_values)

    def test_severity_order_within_template_6_group(self, report):
        g6 = self._group(report, 6)
        assert g6 is not None
        sev_values = [{"HIGH": 0, "MEDIUM": 1, "LOW": 2}[f.severity] for f in g6.findings]
        assert sev_values == sorted(sev_values)

    def test_doc_nums_ascending_within_same_severity(self, report):
        for g in report.findings.groups:
            prev_sev = -1
            prev_doc = -1
            for f in g.findings:
                sev = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[f.severity]
                doc = f.doc_num if f.doc_num is not None else float("inf")
                if sev == prev_sev:
                    assert doc >= prev_doc, (
                        f"doc_num ordering broken in template {g.template_ref['number']}: "
                        f"{prev_doc} then {f.doc_num}"
                    )
                prev_sev = sev
                prev_doc = doc


# ── ES33 E2 exempt routing — Template 4 vs 5 ─────────────────────────────────

def _inject_es33_e2(data: dict) -> dict:
    """Add a synthetic ES33 E2 finding to classify and detect."""
    d = copy.deepcopy(data)
    d["classify"]["issues"].append({
        "doc_num": 9999,
        "doc_date": "2024-07-15",
        "doc_currency": "SGD",
        "card_name": "Test Exempt Co",
        "vat_group": "ES33",
        "line_total": 5000.0,
        "tax_total": 350.0,
        "error_code": "E2",
        "description": "Tax 350.00 charged on non-taxable supply (VatGroup=ES33)",
    })
    d["detect"]["issues"].append({
        "severity": "MEDIUM",
        "error_code": "E2",
        "doc_num": 9999,
        "doc_date": "2024-07-15",
        "card_name": "Test Exempt Co",
        "description": "Tax 350.00 charged on non-taxable supply (VatGroup=ES33)",
        "recommendation": "Remove the GST charge.",
    })
    d["detect"]["severity_counts"]["MEDIUM"] = (
        d["detect"]["severity_counts"].get("MEDIUM", 0) + 1
    )
    d["fetch_manifest"]["records"].append({
        "doc_num": 9999,
        "doc_date": "2024-07-15",
        "doc_type": "sales_invoice",
        "doc_currency": "SGD",
        "doc_total": 5350.0,
        "card_name": "Test Exempt Co",
        "vat_group": "ES33",
    })
    return d


class TestES33ExemptRouting:
    def _find_es33(self, report: ReportModel):
        for g in report.findings.groups:
            for f in g.findings:
                if f.doc_num == 9999 and f.error_code == "E2":
                    return f
        return None

    def test_es33_e2_routes_to_template_5_without_flag(self, raw_data):
        data = _inject_es33_e2(raw_data)
        cfg = _make_cfg()
        r = build_report(data, cfg, generated_at=_GENERATED_AT)
        f = self._find_es33(r)
        assert f is not None, "ES33 E2 finding not found"
        assert f.template_ref["number"] == 5

    def test_es33_e2_routes_to_template_4_with_flag(self, raw_data):
        data = _inject_es33_e2(raw_data)
        cfg = _make_cfg()
        cfg.actively_makes_exempt_supplies = True  # dynamic attribute via getattr
        r = build_report(data, cfg, generated_at=_GENERATED_AT)
        f = self._find_es33(r)
        assert f is not None, "ES33 E2 finding not found"
        assert f.template_ref["number"] == 4


# ── CrossFindingSection ───────────────────────────────────────────────────────

class TestCrossFindings:
    def test_doc_605_flagged(self, report):
        docs = {e.doc_num for e in report.cross_findings.multi_error_docs}
        assert 605 in docs

    def test_doc_605_has_e2_and_no_gst_reg(self, report):
        entry = next(
            e for e in report.cross_findings.multi_error_docs if e.doc_num == 605
        )
        assert "E2" in entry.error_codes
        assert "NO_GST_REG" in entry.error_codes

    def test_no_spurious_cross_findings(self, report):
        # Only doc 605 should appear in the SBODEMOSG fixture.
        doc_nums = [e.doc_num for e in report.cross_findings.multi_error_docs]
        assert doc_nums == [605], f"unexpected multi-error docs: {doc_nums}"


# ── NotExaminedSection substring checks ──────────────────────────────────────

class TestNotExamined:
    def _combined(self, report: ReportModel) -> str:
        return " ".join(report.not_examined.items).lower()

    def test_contains_manual_journal(self, report):
        assert "manual journal" in self._combined(report)

    def test_contains_partial_exemption(self, report):
        assert "partial-exemption" in self._combined(report)

    def test_contains_export_evidence(self, report):
        assert "export evidence" in self._combined(report)

    def test_contains_financial_statement(self, report):
        assert "financial statement" in self._combined(report)

    def test_contains_reverse_charge(self, report):
        assert "reverse charge" in self._combined(report)


# ── F5BoxSection ──────────────────────────────────────────────────────────────

class TestF5BoxSection:
    def test_box_8_value(self, report):
        assert report.f5_boxes.boxes["box_8_net_gst"] == pytest.approx(17045.87)

    def test_box_5_attribution_has_tx_im_zp(self, report):
        # T2.21b: SI->TX rename. Expected to fail today: chain-run-sample.json's
        # classify.vatgroup_inventory still has "SI" (not "TX"), so the
        # _BOX_VATGROUPS["box_5_taxable_purchases"] intersection yields
        # {"SI", "ZP", "IM"} and "TX" is not present.
        box5 = next(
            a for a in report.f5_boxes.attribution
            if a.box_name == "box_5_taxable_purchases"
        )
        vgs = set(box5.vat_groups)
        assert "TX" in vgs
        assert "IM" in vgs
        assert "ZP" in vgs

    def test_box_5_attribution_excludes_me_and_igds(self, report):
        box5 = next(
            a for a in report.f5_boxes.attribution
            if a.box_name == "box_5_taxable_purchases"
        )
        vgs = set(box5.vat_groups)
        assert "ME" not in vgs, "ME not in SBODEMOSG inventory; should be filtered out"
        assert "IGDS" not in vgs, "IGDS not in SBODEMOSG inventory; should be filtered out"

    def test_all_eight_boxes_present(self, report):
        assert len(report.f5_boxes.attribution) == 8

    def test_box_4_equals_box1_plus_box2_plus_box3(self, report):
        b = report.f5_boxes.boxes
        expected = (
            b["box_1_standard_rated_sales"]
            + b["box_2_zero_rated_sales"]
            + b["box_3_exempt_sales"]
        )
        assert b["box_4_total_sales"] == pytest.approx(expected, abs=0.01)
