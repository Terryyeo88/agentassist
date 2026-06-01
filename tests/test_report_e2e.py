"""
End-to-end tests for the report pipeline:
  load_compile_output → build_report → render_pdf

Uses tests/fixtures/chain-run-sample.json (SBODEMOSG Q3 2024 CompileOutput).
ClientConfig deliberately omits actively_makes_exempt_supplies, exercising
the default Template 5 path for E2/EXEMPT findings.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from config.loader import ClientConfig
from report.contract import load_compile_output
from report.render import render_pdf
from report.report import ReportModel, build_report

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"

# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_cfg(**overrides) -> ClientConfig:
    """Minimal ClientConfig for tests — no SAP connectivity, no exempt flag."""
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


def _inject_es33_e2(data: dict) -> dict:
    """Deep-copy data and insert a synthetic ES33 E2 finding for routing tests."""
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


def _all_findings(model: ReportModel):
    return [f for g in model.findings.groups for f in g.findings]


def _generated_text(model: ReportModel) -> str:
    """
    Collect all text that originates from tool output or authored judgment questions.
    Excludes the static disclaimer (constants.DISCLAIMER_TEXT) and box labels.
    """
    parts: list[str] = []
    for f in _all_findings(model):
        if f.description:
            parts.append(f.description)
        if f.recommendation:
            parts.append(f.recommendation)
    for jg in model.judgment.groups:
        parts.append(jg.judgment_question)
    return " ".join(parts).lower()


# ── Module-scoped fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def raw_data() -> dict:
    return load_compile_output(FIXTURE)


@pytest.fixture(scope="module")
def cfg() -> ClientConfig:
    return _make_cfg()


@pytest.fixture(scope="module")
def model(raw_data, cfg) -> ReportModel:
    return build_report(raw_data, cfg, generated_at=_GENERATED_AT)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_renders_pdf(raw_data, cfg, tmp_path):
    """load_compile_output → build_report → render_pdf produces a valid PDF."""
    m = build_report(raw_data, cfg, generated_at=_GENERATED_AT)
    out = tmp_path / "report.pdf"
    render_pdf(m, out)

    assert out.exists(), "PDF file was not created"
    size = out.stat().st_size
    assert size > 5 * 1024, f"PDF is too small ({size} bytes)"
    assert out.read_bytes()[:4] == b"%PDF", "File does not begin with %PDF"


def test_required_sections_present(model):
    """All eight ReportModel sections are present and non-empty."""
    assert model.cover is not None and model.cover.client_name != ""
    assert model.scope is not None and model.scope.items_examined
    assert model.f5_boxes is not None and model.f5_boxes.attribution
    assert model.findings is not None and model.findings.groups
    assert model.cross_findings is not None and model.cross_findings.multi_error_docs
    assert model.judgment is not None and model.judgment.groups
    assert model.not_examined is not None and model.not_examined.items
    assert model.signature is not None and model.signature.disclaimer != ""


def test_not_examined_boundary_present(model):
    """NotExaminedSection text contains every required coverage-boundary phrase."""
    combined = " ".join(model.not_examined.items).lower()

    assert "manual journal" in combined, "'manual journal' not found"
    assert (
        "partial-exemption" in combined or "partial exemption" in combined
    ), "'partial-exemption' / 'partial exemption' not found"
    assert "export evidence" in combined, "'export evidence' not found"
    assert "financial statement" in combined, "'financial statement' not found"
    assert "reverse charge" in combined, "'reverse charge' not found"


def test_routing_golden(model):
    """E2/BL→T6, E1→T2, CrossFindingSection flags only doc 605."""
    flat = _all_findings(model)

    # E2 doc 605 (BL) → Template 6
    e2_605 = next(
        (f for f in flat if f.doc_num == 605 and f.error_code == "E2"), None
    )
    assert e2_605 is not None, "E2 finding for doc 605 not found"
    assert e2_605.template_ref["number"] == 6, (
        f"E2/BL doc 605 routed to {e2_605.template_ref['number']}, expected 6"
    )

    # E1 doc 958 → Template 2
    e1_958 = next(
        (f for f in flat if f.doc_num == 958 and f.error_code == "E1"), None
    )
    assert e1_958 is not None, "E1 finding for doc 958 not found"
    assert e1_958.template_ref["number"] == 2, (
        f"E1 doc 958 routed to {e1_958.template_ref['number']}, expected 2"
    )

    # CrossFindingSection: doc 605 present and nothing spurious
    cross_doc_nums = [e.doc_num for e in model.cross_findings.multi_error_docs]
    assert 605 in cross_doc_nums, "doc 605 (E2 + NO_GST_REG) not flagged in CrossFindingSection"
    assert cross_doc_nums == [605], (
        f"Unexpected cross-finding docs: {cross_doc_nums}"
    )


def test_exempt_default_is_template_5(raw_data):
    """ES33 E2 → T5 without the flag; → T4 when actively_makes_exempt_supplies=True."""
    data_with_es33 = _inject_es33_e2(raw_data)

    def _find_es33(m: ReportModel):
        for g in m.findings.groups:
            for f in g.findings:
                if f.doc_num == 9999 and f.error_code == "E2":
                    return f
        return None

    # Without flag: default Template 5
    cfg_default = _make_cfg()
    m_default = build_report(data_with_es33, cfg_default, generated_at=_GENERATED_AT)
    f_default = _find_es33(m_default)
    assert f_default is not None, "Synthetic ES33 E2 finding not found in model"
    assert f_default.template_ref["number"] == 5, (
        f"Expected Template 5 without flag, got {f_default.template_ref['number']}"
    )

    # With flag: Template 4
    cfg_exempt = _make_cfg()
    cfg_exempt.actively_makes_exempt_supplies = True  # dynamic attr via getattr
    m_exempt = build_report(data_with_es33, cfg_exempt, generated_at=_GENERATED_AT)
    f_exempt = _find_es33(m_exempt)
    assert f_exempt is not None, "Synthetic ES33 E2 finding not found in model (exempt cfg)"
    assert f_exempt.template_ref["number"] == 4, (
        f"Expected Template 4 with flag, got {f_exempt.template_ref['number']}"
    )


def test_human_in_loop_invariant(model):
    """
    No generated text asserts a compliance conclusion or mandatory filing action.
    Conditional/candidate phrasing is allowed and verified to be present.
    """
    text = _generated_text(model)

    # Forbidden: definitive compliance conclusions or mandatory actions
    for phrase in (
        "must file f7",
        "file a gst f7",
        "voluntary disclosure is required",
        "we certify",
        "agentassist certifies",
    ):
        assert phrase not in text, (
            f"Forbidden phrase '{phrase}' found in generated text"
        )

    # Allowed: conditional/candidate phrasing must be present to confirm the
    # check isn't over-blocking — tool descriptions use "if" and "may" framing.
    assert (
        "if this is an export sale" in text or "may not be claimable" in text
    ), (
        "Expected conditional candidate phrasing not found — "
        "human-in-loop invariant check may be incorrectly blocking legitimate text"
    )
