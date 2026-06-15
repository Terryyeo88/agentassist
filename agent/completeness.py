"""
agent/completeness.py — CODE-DEFINED completeness checklist for the case-file loop.

T5.3 Slice 2 (behavior). The verify step of the loop is a deterministic
completeness checklist keyed to ``CheckSpec.inputs_needed`` per finding type.

NON-NEGOTIABLE INVARIANT: verification is a CODE-DEFINED completeness checklist,
NEVER model self-assessment. ``evaluate_completeness`` is a pure function over the
staged dossier evidence map; the model is not consulted. A finding is "done" only
when every required input slot for its check carries a non-null value — the model
saying "I'm finished" is irrelevant to this gate.

The required set is the CheckSpec's ``inputs_needed`` VERBATIM (``required_inputs``),
so the checklist tracks the registry: change ``inputs_needed`` and the checklist
changes with it, with no duplicated literals.

Input taxonomy
--------------
Each required input slot is filled from one of two sources:

  * ENGINE-SEEDED — produced by the deterministic engine (``review()``) and carried
    on the finding payload (e.g. ``sales_invoices``, ``sap_listing``). The loop
    driver seeds these from the finding before invoking the model.
  * AGENT-GATHERED — gathered by the agent via a Slice-1 Tier-0 read:
      ``supplier_catalog`` ← read_vendor_gst_status
      ``document_pdfs``    ← get_source_document
    The agent MUST gather these for the dossier to be complete; an incomplete
    dossier re-enters gather (bounded by RunBudget).

Any input token not in AGENT_GATHERED_INPUTS is treated as engine-seeded.

Zero anthropic import. Zero SDK import. Stdlib only.
"""
from __future__ import annotations

from agent.registry import CHECK_REGISTRY

# Slots the agent must gather via a Tier-0 read (see agent/read_tools.py).
AGENT_GATHERED_INPUTS: frozenset[str] = frozenset({"supplier_catalog", "document_pdfs"})

# CODE-DEFINED binding: which Tier-0 read tool fills which canonical completeness slot.
# The slot a read fills is a deterministic property of the tool (globally 1:1 — verified
# across every CheckSpec needing an agent-gathered slot), NOT a string the model supplies
# (T5.3g — the T5.3-V live run showed the model invents slot names). Every member of
# AGENT_GATHERED_INPUTS MUST appear as a value here, or completeness can never be reached
# for the check that needs it (enforced by tests/test_t53g_slot_contract.py).
READ_TOOL_SLOT: dict[str, str] = {
    "get_source_document": "document_pdfs",
    "read_vendor_gst_status": "supplier_catalog",
}


def required_inputs(check_id: str) -> list[str]:
    """Return the required input slots for *check_id* — CheckSpec.inputs_needed verbatim.

    Raises:
        ValueError: if *check_id* is not a registered CheckSpec.
    """
    spec = CHECK_REGISTRY.get(check_id)
    if spec is None:
        raise ValueError(
            f"no CheckSpec registered for check_id={check_id!r}; "
            "completeness is undefined for findings without a registered check"
        )
    return list(spec.inputs_needed)


def engine_seeded_slots(check_id: str) -> list[str]:
    """Return the required slots that are engine-seeded (not agent-gathered).

    These are the inputs the deterministic engine already consumed to emit the
    finding; the loop driver seeds them from the finding payload.
    """
    return [s for s in required_inputs(check_id) if s not in AGENT_GATHERED_INPUTS]


def evaluate_completeness(check_id: str, evidence: dict) -> dict:
    """Evaluate dossier completeness for *check_id* against *evidence* (pure function).

    A required slot counts as present only when it appears in *evidence* with a
    non-null value. Completeness is structural presence of every required input —
    it is NOT a semantic judgement and NOT the model's self-assessment.

    Args:
        check_id: Registered CheckSpec id (e.g. "NO_GST_REG", "gst_amount_mismatch").
        evidence: The dossier evidence map (slot name -> evidence value).

    Returns:
        {"check_id", "required", "present", "satisfied", "missing"} where:
            required  = CheckSpec.inputs_needed (verbatim)
            present   = required slots carrying a non-null value
            missing   = required slots absent or null
            satisfied = (missing == [])

    Raises:
        ValueError: if *check_id* is not a registered CheckSpec.
    """
    required = required_inputs(check_id)
    present = [slot for slot in required if evidence.get(slot) is not None]
    missing = [slot for slot in required if evidence.get(slot) is None]
    return {
        "check_id": check_id,
        "required": required,
        "present": present,
        "missing": missing,
        "satisfied": not missing,
    }
