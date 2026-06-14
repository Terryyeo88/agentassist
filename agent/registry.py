"""
agent/registry.py — Tool registry and tier classification.

Public API:
    REGISTRY         — dict[str, ToolSpec]: all registered tools (Tier 0 and 1 only)
    CHECK_REGISTRY   — dict[str, CheckSpec]: v0/PROVISIONAL check registry
    CHECKSPEC_STATUS — str: "v0/PROVISIONAL" (signals non-frozen contract)
    get_tier(name)   — Tier: Tier.THREE for any absent/unknown name
    allowed_tools()  — list[ToolSpec]: tools the agent may call (Tier 0 + 1)

Invariants:
    - REGISTRY contains only Tier 0 and Tier 1 tools.
    - No Tier-2-executing tool exists in REGISTRY.
    - propose_action is the only path to Tier 2; it is registered at Tier 1.
    - get_tier returns Tier.THREE for any name not in REGISTRY.
    - Zero anthropic import.
"""
from __future__ import annotations

from agent.schemas import CheckSpec, Tier, ToolSpec

# ---------------------------------------------------------------------------
# Tool registry — Tier 0 (observe) and Tier 1 (work in staging) only
# ---------------------------------------------------------------------------

_TOOLS: list[ToolSpec] = [
    # Tier 0 — read-only, autonomous
    ToolSpec(
        name="read_sap_invoices",
        tier=Tier.ZERO,
        description="Read SAP B1 sales invoice listing for the audit period (read-only).",
    ),
    ToolSpec(
        name="read_sap_purchase_invoices",
        tier=Tier.ZERO,
        description="Read SAP B1 purchase invoice listing for the audit period (read-only).",
    ),
    ToolSpec(
        name="read_ledger",
        tier=Tier.ZERO,
        description="Read the current justification ledger entries (read-only).",
    ),
    ToolSpec(
        name="read_kb_slice",
        tier=Tier.ZERO,
        description="Read a knowledge-base slice by name (read-only).",
    ),
    # Tier 0 — dossier evidence reads (T5.3 Slice 1; impl in agent/read_tools.py)
    ToolSpec(
        name="get_source_document",
        tier=Tier.ZERO,
        description=(
            "Fetch the source invoice PDF path for a doc_num via the document "
            "provider seam (read-only). Returns None when no PDF is available."
        ),
    ),
    ToolSpec(
        name="read_vendor_gst_status",
        tier=Tier.ZERO,
        description="Look up a vendor's GST-registration status by card name (read-only).",
    ),
    ToolSpec(
        name="read_prior_period_treatment",
        tier=Tier.ZERO,
        description="Look up how a finding key was treated in a prior period (read-only).",
    ),
    # Tier 1 — work in staging; mandatory justification
    ToolSpec(
        name="run_review_chain",
        tier=Tier.ONE,
        description=(
            "Invoke the full deterministic audit chain as a single atomic tool "
            "(fetch → classify → calculate → detect → compile, all gates included). "
            "Effects confined to staging. Justification required."
        ),
    ),
    ToolSpec(
        name="run_reg2627_pass",
        tier=Tier.ONE,
        description=(
            "Invoke the Reg 26/27 disallowed input tax candidate pass. "
            "Outputs candidates for human review only; never asserts compliance. "
            "Justification required."
        ),
    ),
    ToolSpec(
        name="draft_report_section",
        tier=Tier.ONE,
        description=(
            "Draft a report section in the staging workspace. "
            "Does not emit or seal anything. Justification required."
        ),
    ),
    ToolSpec(
        name="propose_action",
        tier=Tier.ONE,
        description=(
            "Emit a schema-validated Tier-2 ProposalArtifact (action + justification + "
            "evidence refs). The ONLY path to Tier-2 effects. The agent emits the "
            "proposal; the deterministic executor fires only after human approval. "
            "Justification required."
        ),
    ),
]

REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in _TOOLS}


def _strip_mcp_prefix(name: str) -> str:
    """Resolve an SDK MCP tool name to its bare registry name.

    In-process MCP tools are exposed to the SDK as ``mcp__<server>__<tool>``.
    The tier/justification cage reasons in bare registry names, so an MCP-
    namespaced name is mapped back to ``<tool>`` before lookup. Names without
    the ``mcp__`` prefix are returned unchanged.
    """
    if name.startswith("mcp__"):
        # mcp__<server>__<tool>  ->  <tool>
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return name


def get_tier(name: str) -> Tier:
    """Return the Tier for a tool name.

    Accepts both bare registry names and SDK MCP-namespaced names
    (``mcp__<server>__<tool>``), resolving the latter to its registry entry so
    the justification gate applies to MCP tools too.

    Returns Tier.THREE for any name absent from REGISTRY, encoding the
    'structurally impossible' tier as 'absent, not denied' — the tool
    does not exist rather than being blocked at runtime.
    """
    spec = REGISTRY.get(_strip_mcp_prefix(name))
    return spec.tier if spec is not None else Tier.THREE


def allowed_tools() -> list[ToolSpec]:
    """Return all tools the agent may call (Tier 0 and Tier 1 only)."""
    return [spec for spec in REGISTRY.values() if spec.tier in (Tier.ZERO, Tier.ONE)]


# ---------------------------------------------------------------------------
# Check registry — v0/PROVISIONAL
#
# NOT wired into any consumer. Collin ratifies schema before building
# deterministic checks against it. check_id/iras_basis will be reconciled
# against the canonical IRAS VatGroup remap and T2.18 config_keys when those
# land (additive, non-breaking — config_keys re-adds for D+ checks).
# ---------------------------------------------------------------------------

CHECKSPEC_STATUS: str = "v0/PROVISIONAL"

_CHECKS: list[CheckSpec] = [
    # --- E1–E4: classify step (sap_b1_server.py / orchestrator) ---
    CheckSpec(
        check_id="E1",
        display_name="Standard-rated sales on likely export/overseas supply",
        iras_basis="IRAS GST Guide on Exports / Zero-Rating",
        inputs_needed=["sales_invoices", "vat_group_mapping"],
        finding_type="deterministic",
        finding_schema={"doc_num": "int", "vat_group": "str", "error_code": "str",
                        "description": "str"},
    ),
    CheckSpec(
        check_id="E2",
        display_name="GST charged on non-taxable or zero-rated supply",
        iras_basis="IRAS GST Act / applicable zero-rate and exempt supply provisions",
        inputs_needed=["sales_invoices", "purchase_invoices", "vat_group_mapping"],
        finding_type="deterministic",
        finding_schema={"doc_num": "int", "vat_group": "str", "tax_total": "float",
                        "error_code": "str"},
    ),
    CheckSpec(
        check_id="E3",
        display_name="Standard-rated supply with zero or missing GST amount",
        iras_basis="IRAS GST Act s10 / applicable output tax provisions",
        inputs_needed=["sales_invoices", "vat_group_mapping"],
        finding_type="deterministic",
        finding_schema={"doc_num": "int", "vat_group": "str", "tax_total": "float",
                        "error_code": "str"},
    ),
    CheckSpec(
        check_id="E4",
        display_name="GST rate deviation from expected applicable rate",
        iras_basis="IRAS GST Act / applicable rate schedule",
        inputs_needed=["sales_invoices", "purchase_invoices", "applicable_gst_rate"],
        finding_type="deterministic",
        finding_schema={"doc_num": "int", "vat_group": "str", "tax_total": "float",
                        "error_code": "str"},
    ),
    # --- detect step checks ---
    CheckSpec(
        check_id="NO_GST_REG",
        display_name="Input tax claimed from supplier with no GST registration number",
        iras_basis="IRAS GST Act s19(1) / Regulation 11 — Conditions for claiming input tax",
        inputs_needed=["purchase_invoices", "supplier_catalog"],
        finding_type="deterministic",
        finding_schema={"severity": "str", "doc_num": "int|None", "card_name": "str",
                        "error_code": "str", "description": "str",
                        "recommendation": "str"},
    ),
    CheckSpec(
        check_id="COMPLETENESS",
        display_name="Purchase volume below completeness threshold vs sales volume",
        iras_basis="IRAS ASK Annual Review Guide §10.1(d) — Input tax completeness",
        inputs_needed=["invoice_counts", "completeness_threshold"],
        finding_type="deterministic",
        finding_schema={"severity": "str", "error_code": "str", "description": "str",
                        "recommendation": "str"},
    ),
    # --- listing checks (check_listing.py) ---
    CheckSpec(
        check_id="SEQ_GAP",
        display_name="Invoice sequence gap — DocNum absent from company-wide records",
        iras_basis="IRAS ASK Annual Review Guide §10.1(c)(i)",
        inputs_needed=["sales_invoices", "all_period_invoices"],
        finding_type="deterministic",
        finding_schema={"check": "str", "series": "int", "gap_doc_num": "int",
                        "description": "str", "basis": "str"},
    ),
    CheckSpec(
        check_id="DUP_CLAIM",
        display_name="Duplicate input tax claim — same vendor reference entered twice",
        iras_basis="IRAS ASK Annual Review Guide §10.1(d)(i)",
        inputs_needed=["purchase_invoices"],
        finding_type="deterministic",
        finding_schema={"check": "str", "doc_num": "int", "duplicate_of": "int",
                        "num_at_card": "str", "description": "str", "basis": "str"},
    ),
    # --- declared-F5 checks (check_declared_f5.py) ---
    CheckSpec(
        check_id="declared_A",
        display_name="Declared F5 internal consistency (Box 4 = 1+2+3; Box 8 = 6−7)",
        iras_basis="IRAS GST F5 Return form — arithmetic consistency",
        inputs_needed=["declared_f5"],
        finding_type="deterministic",
        finding_schema={"check": "str", "finding_type": "str", "rule": "str",
                        "box": "str", "delta": "float", "description": "str"},
    ),
    CheckSpec(
        check_id="declared_B",
        display_name="Declared vs computed F5 divergence per independent box",
        iras_basis="IRAS ASK Annual Review Guide s10.1(d)(iii) fn33",
        inputs_needed=["declared_f5", "computed_boxes"],
        finding_type="deterministic",
        finding_schema={"check": "str", "box": "str", "declared": "float",
                        "computed": "float", "delta": "float", "basis": "str"},
    ),
    # --- document reconciliation checks (documents/reconcile.py) ---
    CheckSpec(
        check_id="gst_amount_mismatch",
        display_name="GST amount on invoice PDF differs from SAP line item",
        iras_basis="IRAS GST Act s19 / Regulation 11 — Tax invoice requirements",
        inputs_needed=["document_pdfs", "sap_listing"],
        finding_type="probabilistic",
        finding_schema={"check_id": "str", "severity": "str", "message": "str",
                        "extracted_value": "any", "listing_value": "any",
                        "determinability": "str"},
    ),
    CheckSpec(
        check_id="correct_period",
        display_name="Invoice date falls outside the audit period",
        iras_basis="IRAS GST Act s20 — Time of supply / correct accounting period",
        inputs_needed=["document_pdfs", "sap_listing"],
        finding_type="probabilistic",
        finding_schema={"check_id": "str", "severity": "str", "message": "str",
                        "extracted_value": "any", "listing_value": "any",
                        "determinability": "str"},
    ),
    CheckSpec(
        check_id="total_inconsistency",
        display_name="Invoice PDF internal total inconsistency (excl + GST ≠ total)",
        iras_basis="IRAS GST Act s19 / Regulation 11 — Tax invoice face accuracy",
        inputs_needed=["document_pdfs"],
        finding_type="probabilistic",
        finding_schema={"check_id": "str", "severity": "str", "message": "str",
                        "extracted_value": "any", "listing_value": "any",
                        "determinability": "str"},
    ),
    CheckSpec(
        check_id="reg11_supplier_gst_absent",
        display_name="Supplier GST registration number absent from invoice face",
        iras_basis="IRAS GST (General) Regulations Regulation 11 — Tax invoice requirements",
        inputs_needed=["document_pdfs"],
        finding_type="probabilistic",
        finding_schema={"check_id": "str", "severity": "str", "message": "str",
                        "extracted_value": "any", "listing_value": "any",
                        "determinability": "str"},
    ),
]

CHECK_REGISTRY: dict[str, CheckSpec] = {spec.check_id: spec for spec in _CHECKS}
