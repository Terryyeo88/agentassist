"""
Failing-test-first coverage for the Gate-1 ``@odata.count`` key fix (backlog #5).

The SAP v2 Service Layer returns the inline record count under the key
``"@odata.count"`` (with the ``@`` prefix).  ``SapChainReader.count`` historically
read the unprefixed ``"odata.count"`` — so the probe always yielded ``None``,
``sap_inline_count`` was always ``None``, and Gate 1 warn-passed unconditionally
(the pagination-completeness check was dormant).

These tests assert the CORRECT behaviour and therefore FAIL against the buggy
code:

  1. ``SapChainReader.count`` reads ``"@odata.count"`` and returns the real int.
  2. With a real inline count present, Gate 1 FAILS on a genuine pagination
     mismatch (fetched rows != SAP-reported count) — i.e. it is no longer dormant.
  3. With complete pagination the inline count surfaces on the manifest and Gate 1
     verifies it (no longer forced to ``None``/WARN_PASS).

All SAP contact is mocked; no live instance is touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402

from orchestrator.steps import fetch  # noqa: E402
from orchestrator.gates import gate_1_record_count  # noqa: E402
from orchestrator.exceptions import GateFailure  # noqa: E402

_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}

# Mirrors tests/fixtures/sbodemosg-extract/inline-counts.json (the frozen key + values).
_COUNTS = {"Invoices": 50, "PurchaseInvoices": 34, "CreditNotes": 1, "PurchaseCreditNotes": 1}
_TOTAL = sum(_COUNTS.values())  # 86


class _FakeSap:
    """Stand-in for the module-global SAP client.

    ``get`` distinguishes the S0 count-probe ($top=0) from a data read and returns
    the count under the ``@``-prefixed key exactly as the v2 Service Layer does.
    """

    def __init__(self, counts):
        self._counts = counts

    def get(self, endpoint, params=None):
        entity = endpoint.lstrip("/")
        if params and params.get("$top") == 0:
            # v2 wire shape: count lives under "@odata.count".
            return {"@odata.count": self._counts[entity],
                    "@odata.context": "https://fake/$metadata", "value": []}
        return {"value": []}


def _docs(n: int) -> list:
    """n minimal OData documents with distinct, non-zero DocNums."""
    return [{"DocNum": i + 1, "DocDate": "2024-07-15", "DocumentLines": []}
            for i in range(n)]


def _reader_with_fetched(monkeypatch, fetched_per_entity):
    """A real SapChainReader whose count() hits the (mocked) @odata.count probe,
    with fetch_invoices stubbed to return a controlled row count per entity."""
    monkeypatch.setattr(sap_b1_server, "sap", _FakeSap(_COUNTS))
    reader = sap_b1_server.SapChainReader()
    monkeypatch.setattr(
        reader, "fetch_invoices",
        lambda entity, ps, pe: _docs(fetched_per_entity[entity]),
    )
    return reader


# ---------------------------------------------------------------------------
# 1. Unit: the count probe must read the @-prefixed key.
# ---------------------------------------------------------------------------

def test_count_reads_at_prefixed_odata_count_key(monkeypatch):
    monkeypatch.setattr(sap_b1_server, "sap", _FakeSap(_COUNTS))
    reader = sap_b1_server.SapChainReader()
    got = reader.count("Invoices", _PERIOD["start"], _PERIOD["end"])
    assert got == 50, "count() must read the @-prefixed '@odata.count' key, not None"


# ---------------------------------------------------------------------------
# 2. Integration: a genuine pagination mismatch must now FAIL Gate 1.
# ---------------------------------------------------------------------------

def test_gate1_fails_on_real_pagination_mismatch(monkeypatch):
    # SAP reports 86 across the four entities but we only fetched 84 → truncated.
    short = dict(_COUNTS)
    short["Invoices"] = 48  # 2 rows short of the reported 50
    reader = _reader_with_fetched(monkeypatch, short)

    manifest = fetch(client_config=None, period=_PERIOD, reader=reader)
    assert manifest["sap_inline_count"] == _TOTAL, "inline count must aggregate the real probe"

    with pytest.raises(GateFailure):
        gate_1_record_count(manifest)


# ---------------------------------------------------------------------------
# 3. Integration: complete pagination surfaces the count and Gate 1 verifies it.
# ---------------------------------------------------------------------------

def test_gate1_verifies_count_on_complete_pagination(monkeypatch):
    reader = _reader_with_fetched(monkeypatch, dict(_COUNTS))
    manifest = fetch(client_config=None, period=_PERIOD, reader=reader)

    assert manifest["sap_inline_count"] == _TOTAL
    checked = gate_1_record_count(manifest)
    assert checked["sap_inline_count"] == _TOTAL
    assert checked["fetched_count"] == _TOTAL
