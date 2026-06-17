"""
agent/read_tools.py — Tier-0 read-only tool implementations for the dossier loop.

T5.3 Slice 1 (plumbing). Read-only lookups the case-file builder uses to assemble
per-finding evidence. All are pure reads — no writes, no mutation of the source, no
network beyond whatever the injected provider performs.

Public API:
    get_source_document(provider, doc_num) -> str | None
    read_vendor_gst_status(catalog, card_name) -> dict
    read_prior_period_treatment(store, key) -> dict
    read_proposals(staging_store) -> list[dict]                          # T5.9a1
    read_decision_ledger(decision_ledger, *, fingerprint) -> list[dict]  # T5.9a1

These wrap their data sources by dependency injection (the provider / catalog /
store are passed in), so they stay hermetic and Tier-0. Their registry entries
(Tier 0) live in agent/registry.py; the live MCP wiring is Slice 2.

T5.9a1 added the two product-surface reads the intent menu was conflating onto the
wrong tools: ``read_proposals`` is the PENDING-proposals queue (StagingStore), NOT
the justification ledger; ``read_decision_ledger`` is the T5.5 decision ledger of
human adjudications, NOT the per-key prior-period treatment store. Both stay pure
Tier-0 reads over a DI'd source.

Zero SDK import. Stdlib only.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent.decision_ledger import DecisionLedger
    from agent.proposals import StagingStore
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


def read_proposals(staging_store: "StagingStore") -> list[dict]:
    """List the PENDING proposals awaiting human approval (read-only).

    T5.9a1. The product surface's SHOW_PROPOSALS intent routes here — NOT to
    read_ledger. The justification ledger is a different artifact; the pending-
    proposals queue is the StagingStore (agent/proposals.py). Wraps
    ``StagingStore.list_pending`` and projects each ProposalArtifact to a plain
    dict view. Pure read: never stages, approves, rejects, or mutates the store.

    Returns:
        One view dict per PENDING proposal, in store order:
        {"proposal_id", "action", "tier", "justification", "evidence_refs",
         "inputs_hash", "status", "created_at"}.
    """
    return [
        {
            "proposal_id": p.proposal_id,
            "action": p.action,
            "tier": p.tier,
            "justification": p.justification,
            "evidence_refs": list(p.evidence_refs),
            "inputs_hash": p.inputs_hash,
            "status": p.status,
            "created_at": p.created_at,
        }
        for p in staging_store.list_pending()
    ]


def read_decision_ledger(
    decision_ledger: "DecisionLedger", *, fingerprint: Optional[str] = None
) -> list[dict]:
    """List prior human adjudications from the T5.5 decision ledger (read-only).

    T5.9a1. The product surface's SHOW_PRIOR_ADJUDICATIONS intent routes here —
    NOT to read_prior_period_treatment (a per-key prior-period treatment store,
    a different artifact). Wraps ``DecisionLedger.lookup`` (agent/decision_ledger.py)
    and projects each AdjudicationEntry to a plain dict view. Pure read: never
    appends to or mutates the ledger.

    The decision ledger's only query axis is the deterministic finding fingerprint
    (it carries NO client field — see agent/decision_ledger.py). So:
      * fingerprint given  -> prior adjudications for that fingerprint (lookup), and
      * fingerprint omitted -> ALL entries, oldest first (list-all).

    Returns:
        One view dict per adjudication, oldest first:
        {"entry_id", "fingerprint", "disposition", "reviewer", "reason",
         "period", "timestamp"}. (The hash-chain fields are an integrity detail,
        not part of the read view.)
    """
    entries = (
        list(decision_ledger.entries)
        if fingerprint is None
        else decision_ledger.lookup(fingerprint)
    )
    return [
        {
            "entry_id": e.entry_id,
            "fingerprint": e.fingerprint,
            "disposition": e.disposition,
            "reviewer": e.reviewer,
            "reason": e.reason,
            "period": e.period,
            "timestamp": e.timestamp,
        }
        for e in entries
    ]
