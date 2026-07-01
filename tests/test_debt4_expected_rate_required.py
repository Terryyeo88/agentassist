"""
DEBT-4 — the silent ``expected_rate=0.07`` default is removed; an explicit rate
is now REQUIRED by ``_classify_line`` / ``validate_invoice_tax_codes`` /
``detect_gst_errors``.

Failing-test-first. These pin the required behaviour, so they FAIL against the
current code (which still defaults to 0.07):

  B1/B2/B3 — omitting the rate raises (no silent default); passing an explicit
             ``None`` raises a clear ValueError that names ``applicable_gst_rate``.
  B4       — behaviour-preservation: with an explicit rate the E4 outcome is
             exactly as today (this stays green before AND after the fix — it is
             the anchor that a behaviour change would trip).
  B5       — the FastMCP tool schema marks ``expected_rate`` as required (A5:
             only a no-default arg does this).

All calls are hermetic: the raise-path guards fire before any SAP contact, and
the None-path tests inject the frozen sbodemosg reader (no live SAP).
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402

# Frozen reader so the pre-fix (red) run never touches live SAP.
_shim_spec = importlib.util.spec_from_file_location(
    "debt4_replay_shim", Path(__file__).resolve().parent / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sbodemosg-extract"

_START, _END = "2024-07-01", "2024-09-30"


def _sr_line() -> dict:
    # SR line taxed at 9% — reaches the E4 branch (VatGroup in {SR, TX}).
    return {"VatGroup": "SR", "LineTotal": 1000.0, "TaxTotal": 90.0, "LineNum": 0}


def _doc() -> dict:
    return {"DocNum": 1, "DocDate": "2024-07-15", "DocCurrency": "SGD",
            "CardName": "X", "CardCode": "C1"}


# ---------------------------------------------------------------------------
# B3 — _classify_line
# ---------------------------------------------------------------------------

def test_classify_line_omitting_rate_raises():
    with pytest.raises(TypeError):
        sap_b1_server._classify_line(_sr_line(), _doc(), entity_type="sales")


def test_classify_line_none_rate_raises_named_error():
    with pytest.raises(ValueError, match="applicable_gst_rate"):
        sap_b1_server._classify_line(_sr_line(), _doc(), entity_type="sales",
                                     expected_rate=None)


# ---------------------------------------------------------------------------
# B1 — validate_invoice_tax_codes
# ---------------------------------------------------------------------------

def test_validate_none_rate_raises_named_error():
    reader = replay_shim.build_frozen_reader(FIXTURE_DIR)
    with pytest.raises(ValueError, match="applicable_gst_rate"):
        sap_b1_server.validate_invoice_tax_codes(_START, _END, expected_rate=None, reader=reader)


# ---------------------------------------------------------------------------
# B2 — detect_gst_errors
# ---------------------------------------------------------------------------

def test_detect_none_rate_raises_named_error():
    reader = replay_shim.build_frozen_reader(FIXTURE_DIR)
    with pytest.raises(ValueError, match="applicable_gst_rate"):
        sap_b1_server.detect_gst_errors(_START, _END, expected_rate=None, reader=reader)


# ---------------------------------------------------------------------------
# B4 — behaviour-preservation at an explicit rate (green before AND after)
# ---------------------------------------------------------------------------

def test_e4_behaviour_unchanged_at_explicit_rate():
    line, doc = _sr_line(), _doc()  # 9% line
    at_9 = sap_b1_server._classify_line(line, doc, entity_type="sales", expected_rate=0.09)
    assert not any(i["error_code"] == "E4" for i in at_9), "9% line at 9% expected must be clean"
    at_7 = sap_b1_server._classify_line(line, doc, entity_type="sales", expected_rate=0.07)
    assert any(i["error_code"] == "E4" for i in at_7), "9% line at 7% expected must flag E4"


# ---------------------------------------------------------------------------
# B5 — the MCP tool schema marks expected_rate required (A5)
# ---------------------------------------------------------------------------

def test_mcp_schema_marks_expected_rate_required():
    tools = {t.name: t for t in asyncio.run(sap_b1_server.mcp.list_tools())}
    for name in ("validate_invoice_tax_codes", "detect_gst_errors"):
        required = tools[name].inputSchema.get("required", [])
        assert "expected_rate" in required, (
            f"{name}: expected_rate must be REQUIRED in the MCP tool schema (no silent default)"
        )
