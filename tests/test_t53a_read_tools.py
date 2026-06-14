"""
tests/test_t53a_read_tools.py — T5.3 Slice 1: new Tier-0 read tools (acceptance (d)).

Three new read-only tools are registered at Tier 0 and logged through the
PreToolUse gate:
  * get_source_document(provider, doc_num)  — wraps the T2.8 DocumentProvider seam
  * read_vendor_gst_status(catalog, card_name)
  * read_prior_period_treatment(store, key)

All hermetic: in-memory fakes, no SAP, no network, no writes.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from agent.hooks import make_hooks
from agent.ledger import Ledger
from agent.registry import REGISTRY, allowed_tools, get_tier
from agent.schemas import Tier


_NEW_TOOLS = [
    "get_source_document",
    "read_vendor_gst_status",
    "read_prior_period_treatment",
]

_CONTEXT: dict = {}


def _run(coro):
    return asyncio.run(coro)


def _pre(tool_name: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {},  # Tier-0: no justification required
        "tool_use_id": "uid-1",
        "session_id": "s",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/tmp",
    }


class TestNewToolsRegistration:
    def test_all_three_registered_tier0(self):
        for name in _NEW_TOOLS:
            assert name in REGISTRY, f"{name!r} missing from REGISTRY"
            assert get_tier(name) == Tier.ZERO, f"{name!r} must be Tier 0"

    def test_all_three_in_allowed_tools(self):
        names = {spec.name for spec in allowed_tools()}
        for name in _NEW_TOOLS:
            assert name in names

    def test_new_tools_are_allowed_and_logged(self):
        """Tier-0 reads pass the gate (read-only) and are logged to the ledger."""
        ledger = Ledger()
        pre_cb, _post, _audit = make_hooks(ledger)
        for name in _NEW_TOOLS:
            out = _run(pre_cb(_pre(name), "uid-1", _CONTEXT))
            assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
        # Every call logged as an allowed Tier-0 entry.
        assert len(ledger.entries) == len(_NEW_TOOLS)
        for entry in ledger.entries:
            assert entry.outcome == "allowed"
            assert entry.tier == Tier.ZERO.value
        ledger.verify()


class _FakeProvider:
    """Minimal DocumentProvider: doc_num -> Path or None. Read-only."""
    def __init__(self, mapping: dict):
        self._m = mapping

    def get_document(self, doc_num: int):
        return self._m.get(doc_num)


class TestReadToolBehaviour:
    def test_get_source_document_wraps_provider(self, tmp_path):
        from agent.read_tools import get_source_document
        pdf = tmp_path / "INV-101.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        provider = _FakeProvider({101: pdf})

        got = get_source_document(provider, 101)
        assert got == str(pdf)
        # Unknown doc → None (provider miss is not an error).
        assert get_source_document(provider, 999) is None
        # Read-only: the file is untouched.
        assert pdf.read_bytes() == b"%PDF-1.4 fake"

    def test_read_vendor_gst_status_lookup(self):
        from agent.read_tools import read_vendor_gst_status
        catalog = {
            "Acme Pte Ltd": {"gst_registered": True, "gst_reg_no": "200012345A"},
        }
        hit = read_vendor_gst_status(catalog, "Acme Pte Ltd")
        assert hit["found"] is True
        assert hit["gst_registered"] is True
        assert hit["gst_reg_no"] == "200012345A"

        miss = read_vendor_gst_status(catalog, "Unknown Vendor")
        assert miss["found"] is False
        assert miss["gst_registered"] is False

    def test_read_prior_period_treatment_lookup(self):
        from agent.read_tools import read_prior_period_treatment
        store = {"NO_GST_REG:Acme Pte Ltd": {"treatment": "disallowed", "period": "2024Q2"}}
        hit = read_prior_period_treatment(store, "NO_GST_REG:Acme Pte Ltd")
        assert hit["found"] is True
        assert hit["treatment"] == "disallowed"

        miss = read_prior_period_treatment(store, "NO_GST_REG:Other")
        assert miss["found"] is False
