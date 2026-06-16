"""
tests/test_t58_real_vendor_ctx.py — T5.8c demo-convergence acceptance.

The T5.8 demo freezer (tests/fixtures/demo_artifacts_builder.py) used to FABRICATE the
vendor catalog: for each NO_GST_REG finding it hardcoded {gst_registered: False,
gst_reg_no: None}. T5.8c points the freezer at the T5.3h vendor-ctx assembler
(agent.loop_context.build_vendor_catalog) so the demo renders REAL frozen-extract-derived
vendor ctx from tests/fixtures/sbodemosg-extract/business-partners.raw.json.

Non-mock discriminator: the real catalog carries GST-REGISTERED vendors with real
gst_reg_no values (e.g. Ocean Computers -> GB765766545). The old hardcoded path could
NEVER emit a registered vendor or a non-null gst_reg_no — so a registered vendor in the
demo ctx proves the source is the real frozen extract, not the placeholder.

Hermetic: build_vendor_catalog reads one frozen JSON file. No network, no SAP, no token.
"""
from __future__ import annotations

from agent.loop_context import build_vendor_catalog
from tests.fixtures.demo_artifacts_builder import build_context, build_review_result


def _no_gst_card_names(review_result: dict) -> list[str]:
    return [
        issue.get("card_name")
        for issue in review_result["compile_output"]["detect"]["issues"]
        if issue["error_code"] == "NO_GST_REG"
    ]


def test_demo_vendor_ctx_is_real_frozen_extract_derived():
    """The demo's vendor catalog must come from the real frozen extract, not a placeholder.

    Discriminator: it carries at least one GST-REGISTERED vendor with a real reg-no.
    The old hardcoded freezer only ever produced {False, None} for finding card_names,
    so a registered vendor here is impossible under the mock.
    """
    rr = build_review_result()
    catalog = build_context(rr).vendor_catalog

    registered = {
        name: rec
        for name, rec in catalog.items()
        if rec.get("gst_registered") and rec.get("gst_reg_no")
    }
    assert registered, (
        "demo vendor ctx surfaced no GST-registered vendor — still the hardcoded "
        "placeholder rather than the real frozen extract"
    )

    # The real assembler is the authoritative source; the demo ctx must match it.
    assert catalog == build_vendor_catalog()


def test_no_gst_reg_findings_still_resolve_in_real_ctx():
    """Every NO_GST_REG finding card_name must still resolve found=True in the real ctx.

    These vendors are genuinely unregistered in the frozen extract (that is WHY they are
    findings), so swapping to the real source must not drop any supplier_catalog evidence.
    """
    rr = build_review_result()
    catalog = build_context(rr).vendor_catalog
    for card_name in _no_gst_card_names(rr):
        assert card_name in catalog, f"NO_GST_REG card_name absent from real ctx: {card_name}"
        rec = catalog[card_name]
        assert rec["gst_registered"] is False
        assert rec["gst_reg_no"] is None
