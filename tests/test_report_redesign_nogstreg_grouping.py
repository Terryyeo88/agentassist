"""
Report redesign (Avinash feedback) — Change 3: NO_GST_REG supplier grouping.

DISPLAY ONLY. Unregistered-supplier findings (error_code == "NO_GST_REG") must
render grouped under one subheading per supplier (card_name), but:
  * every per-document row is preserved (no collapsing of findings), and
  * the model's ``findings.total_findings`` is unchanged, and
  * enrich keying (one finding per (doc_num, error_code)) is untouched.

RED before the redesign: the pure helper
``report.render._group_nogstreg_by_supplier`` does not yet exist, and Section 3
renders NO_GST_REG as flat rows with no supplier subheading.

The SBODEMOSG fixture has 7 NO_GST_REG findings, each a distinct supplier, so this
test injects two extra NO_GST_REG documents for an EXISTING supplier ("Lasercom")
to prove multiple documents group under one subheading without losing rows.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

import report.render as R
from config.loader import ClientConfig
from report.contract import load_compile_output
from report.enrich import enrich
from report.report import build_report

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"

_EXTRA_DOCS = [
    # Two more unregistered-supplier purchases for the EXISTING supplier "Lasercom".
    {"doc_num": 8001, "card_name": "Lasercom", "doc_total": 4200.00},
    {"doc_num": 8002, "card_name": "Lasercom", "doc_total": 3100.00},
]


def _make_cfg(**overrides) -> ClientConfig:
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


def _inject_nogstreg(data: dict) -> dict:
    """Add two NO_GST_REG detect issues + manifest records for supplier 'Lasercom'."""
    d = copy.deepcopy(data)
    for doc in _EXTRA_DOCS:
        d["detect"]["issues"].append({
            "severity": "MEDIUM",
            "error_code": "NO_GST_REG",
            "doc_num": doc["doc_num"],
            "doc_date": "2024-08-10",
            "card_name": doc["card_name"],
            "description": "Input tax claimed on purchase from supplier with blank GST reg no.",
            "recommendation": "Confirm supplier GST registration before claiming input tax.",
        })
        d["detect"]["severity_counts"]["MEDIUM"] = (
            d["detect"]["severity_counts"].get("MEDIUM", 0) + 1
        )
        d["fetch_manifest"]["records"].append({
            "doc_num": doc["doc_num"],
            "doc_date": "2024-08-10",
            "doc_type": "purchase_invoice",
            "doc_currency": "SGD",
            "doc_total": doc["doc_total"],
            "card_name": doc["card_name"],
            "vat_group": "NR",
        })
    return d


def _walk(node, out: list) -> None:
    from reportlab.platypus import Paragraph, Table
    from reportlab.platypus.flowables import KeepTogether

    if isinstance(node, Paragraph):
        out.append(node.getPlainText())
    elif isinstance(node, Table):
        for row in node._cellvalues:
            for cell in row:
                _walk(cell, out)
    elif isinstance(node, KeepTogether):
        for c in node._content:
            _walk(c, out)
    elif isinstance(node, (list, tuple)):
        for c in node:
            _walk(c, out)
    elif isinstance(node, str):
        out.append(node)


@pytest.fixture(scope="module")
def raw_data() -> dict:
    return load_compile_output(FIXTURE)


@pytest.fixture(scope="module")
def injected(raw_data) -> dict:
    return _inject_nogstreg(raw_data)


# ── Pure grouping helper ──────────────────────────────────────────────────────

class TestGroupHelper:
    def test_groups_preserve_every_row(self, injected):
        findings = enrich(injected, actively_makes_exempt=False)
        ngr = [f for f in findings if f.error_code == "NO_GST_REG"]
        assert len(ngr) == 9  # 7 fixture + 2 injected

        groups = R._group_nogstreg_by_supplier(ngr)
        total_rows = sum(len(fs) for _, fs in groups)
        assert total_rows == len(ngr), "grouping must not drop or merge any per-doc row"

    def test_lasercom_supplier_has_three_docs(self, injected):
        findings = enrich(injected, actively_makes_exempt=False)
        ngr = [f for f in findings if f.error_code == "NO_GST_REG"]
        groups = dict(R._group_nogstreg_by_supplier(ngr))
        assert "Lasercom" in groups
        assert len(groups["Lasercom"]) == 3
        assert {f.doc_num for f in groups["Lasercom"]} == {595, 8001, 8002}

    def test_distinct_supplier_count_preserved(self, injected):
        findings = enrich(injected, actively_makes_exempt=False)
        ngr = [f for f in findings if f.error_code == "NO_GST_REG"]
        groups = R._group_nogstreg_by_supplier(ngr)
        assert len(groups) == 7  # 7 distinct suppliers (Lasercom now holds 3 docs)


# ── Render: supplier subheadings present, no per-doc row dropped ──────────────

class TestGroupingRender:
    def test_supplier_subheadings_and_all_rows_render(self, injected):
        model = build_report(injected, _make_cfg(), generated_at=_GENERATED_AT)
        story: list = []
        R._findings(model, story)
        texts: list = []
        _walk(story, texts)
        blob = "\n".join(texts)
        # Supplier subheading present for the grouped supplier.
        assert "Lasercom" in blob
        # Every injected + existing NO_GST_REG document number still rendered.
        for doc_num in (592, 594, 595, 600, 601, 604, 605, 8001, 8002):
            assert str(doc_num) in blob, f"NO_GST_REG doc {doc_num} row was dropped"


# ── Invariants: total_findings + enrich keying + boxes unchanged ─────────────

class TestGroupingInvariants:
    def test_total_findings_not_collapsed(self, raw_data, injected):
        base = build_report(raw_data, _make_cfg(), generated_at=_GENERATED_AT)
        inj = build_report(injected, _make_cfg(), generated_at=_GENERATED_AT)
        assert base.findings.total_findings == 18
        assert inj.findings.total_findings == 20, "display grouping must not collapse findings"

    def test_enrich_keying_still_one_per_doc_code(self, injected):
        findings = enrich(injected, actively_makes_exempt=False)
        keys = [(f.doc_num, f.error_code) for f in findings]
        assert len(keys) == len(set(keys))

    def test_boxes_untouched(self, raw_data):
        model = build_report(raw_data, _make_cfg(), generated_at=_GENERATED_AT)
        assert model.f5_boxes.boxes == raw_data["calculate"]["boxes"]
