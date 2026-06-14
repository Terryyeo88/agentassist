"""
agent/read_tools.py — Tier-0 read-only tool implementations for the dossier loop.

T5.3 Slice 1 (plumbing). Three read-only lookups the case-file builder uses to
assemble per-finding evidence. All are pure reads — no writes, no mutation of the
source, no network beyond whatever the injected provider performs.

Public API:
    get_source_document(provider, doc_num) -> str | None
    read_vendor_gst_status(catalog, card_name) -> dict
    read_prior_period_treatment(store, key) -> dict

These wrap their data sources by dependency injection (the provider / catalog /
store are passed in), so they stay hermetic and Tier-0. Their registry entries
(Tier 0) live in agent/registry.py; the live MCP wiring is Slice 2.

Zero SDK import. Stdlib only.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from documents.provider import DocumentProvider


def get_source_document(provider: "DocumentProvider", doc_num: int) -> Optional[str]:
    """Return the source-invoice PDF path for *doc_num*, or None if unavailable.

    Wraps the T2.8 DocumentProvider seam (documents/provider.py::get_document).
    A provider miss (None) is not an error — it means no PDF is available for that
    document, exactly as run_documents_pass treats it. Read-only: never writes.
    """
    path = provider.get_document(doc_num)
    return str(path) if path is not None else None


def read_vendor_gst_status(catalog: dict, card_name: str) -> dict:
    """Look up a vendor's GST-registration status in a supplier catalog (read-only).

    Args:
        catalog:   Mapping of card_name -> {"gst_registered": bool,
                   "gst_reg_no": str | None, ...}.
        card_name: Vendor card name to look up.

    Returns:
        {"card_name", "found", "gst_registered", "gst_reg_no"}.  A miss returns
        found=False, gst_registered=False, gst_reg_no=None.
    """
    record: Any = catalog.get(card_name)
    if record is None:
        return {
            "card_name": card_name,
            "found": False,
            "gst_registered": False,
            "gst_reg_no": None,
        }
    return {
        "card_name": card_name,
        "found": True,
        "gst_registered": bool(record.get("gst_registered", False)),
        "gst_reg_no": record.get("gst_reg_no"),
    }


def read_prior_period_treatment(store: dict, key: str) -> dict:
    """Look up how a finding key was treated in a prior period (read-only).

    Args:
        store: Mapping of key -> prior-period treatment record (any dict).
        key:   Lookup key (e.g. "NO_GST_REG:<card_name>").

    Returns:
        {"key", "found", "treatment", "record"}.  A miss returns found=False,
        treatment=None, record=None.
    """
    record: Any = store.get(key)
    if record is None:
        return {"key": key, "found": False, "treatment": None, "record": None}
    return {
        "key": key,
        "found": True,
        "treatment": record.get("treatment"),
        "record": record,
    }
