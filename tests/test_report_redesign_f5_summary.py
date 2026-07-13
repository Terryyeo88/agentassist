"""
Report redesign (Avinash feedback) — Change 2: four-number F5 summary block.

Section 2 must foreground four figures read VERBATIM from
``compile_output["calculate"]["boxes"]`` (BOX-ISOLATION / Invariant 3+4 — no
arithmetic, no recompute):

    Box 1 — Standard-rated supplies
    Box 5 — Taxable purchases
    Box 6 — Output tax due
    Box 7 — Input tax and refunds claimed

RED before the redesign: the pure helper ``report.render._f5_summary_pairs`` does
not yet exist, and the per-box table is not preceded by a highlighted summary.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

import report.render as R
from config.loader import ClientConfig
from report.contract import load_compile_output
from report.report import build_report

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"

_FOUR_KEYS = (
    "box_1_standard_rated_sales",
    "box_5_taxable_purchases",
    "box_6_output_tax",
    "box_7_input_tax",
)


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
def model(raw_data):
    return build_report(raw_data, _make_cfg(), generated_at=_GENERATED_AT)


class TestF5SummaryHelper:
    def test_helper_returns_four_pairs_verbatim(self, raw_data):
        boxes = raw_data["calculate"]["boxes"]
        pairs = R._f5_summary_pairs(boxes)
        values = [v for _, v in pairs]
        # Byte-for-byte identity to the compile-output box values (no arithmetic).
        assert values == [boxes[k] for k in _FOUR_KEYS]

    def test_helper_does_not_mutate_boxes(self, raw_data):
        boxes = raw_data["calculate"]["boxes"]
        before = copy.deepcopy(boxes)
        R._f5_summary_pairs(boxes)
        assert boxes == before, "summary helper must be read-only over boxes"


class TestF5SummaryRender:
    def test_summary_values_appear_in_section_2(self, raw_data, model):
        boxes = raw_data["calculate"]["boxes"]
        story: list = []
        R._f5_boxes(model, story)
        texts: list = []
        _walk(story, texts)
        blob = " || ".join(texts)
        for k in _FOUR_KEYS:
            assert f"{boxes[k]:,.2f}" in blob, f"summary must show {k} verbatim"

    def test_summary_precedes_per_box_table(self, raw_data, model):
        # The highlighted summary must be foregrounded — i.e. the four figures
        # appear before the full per-box breakdown (Box 8 net GST is only in the
        # full table, never the four-number summary).
        story: list = []
        R._f5_boxes(model, story)
        texts: list = []
        _walk(story, texts)
        joined = "\n".join(texts)
        assert "box_8" not in joined.lower()  # sanity: keys never rendered
        # First occurrence of the output-tax figure (summary) precedes Box 8's
        # label text (only in the detailed table).
        box8_label = "Net GST"
        out_tax = f"{raw_data['calculate']['boxes']['box_6_output_tax']:,.2f}"
        assert out_tax in joined
        if box8_label in joined:
            assert joined.index(out_tax) < joined.index(box8_label)


class TestBoxIsolationUnderSummary:
    def test_box_values_byte_identical(self, raw_data, model):
        assert model.f5_boxes.boxes == raw_data["calculate"]["boxes"]
