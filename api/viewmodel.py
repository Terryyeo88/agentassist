"""api/viewmodel.py — PURE serialisers: frozen view-models → JSON-safe dicts.

The SINGLE SOURCE OF TRUTH for the key set the React front end consumes. The exported
``*_KEYS`` tuples are asserted by the contract test (tests/test_t61_frontend_api.py) AND
mirror the TypeScript types in ``frontend/src/api.ts`` — change one, change all three.

Everything here is PURE: it reshapes the frozen ``DemoArtifacts`` (loaded by the Mock
path) into plain dicts/lists. No FastAPI import, no Streamlit, no engine call, no model,
no SAP. The trust signals (``validation_status``, candidate framing, demoted-but-present,
the unvalidated IRAS citations) are carried through verbatim — nothing here asserts a
verdict.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ui.artifacts import (
    DemoArtifacts,
    VALIDATION_STATUS,
    annotated_adjudication_items,
    check_reference,
    flatten_finding_card,
    ledger_timeline_rows,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLIENT_YAML = _REPO_ROOT / "config" / "clients" / "sbodemosg.yaml"

# The frozen demo this slice serves. Only this (client, period) is backed by artifacts;
# any other path returns 404 (we never dress empty data as a real client's numbers).
DEMO_CLIENT_ID = "sbodemosg"
DEMO_PERIOD_LABEL = "2024Q3"

# ── Key contracts (single source of truth; asserted by the contract test) ────────────

#: Top-level keys of GET /review/{client}/{period}.
REVIEW_KEYS: tuple[str, ...] = (
    "client",
    "period",
    "validation_status",
    "f5_summary",
    "queue",
    "disclaimer",
)

#: Keys of each queue item (one per-finding case file).
QUEUE_ITEM_KEYS: tuple[str, ...] = (
    "finding_id",
    "check_id",
    "finding_type",
    "group",
    # flatten_finding_card →
    "vendor",
    "severity",
    "description",
    "recommendation",
    "doc_num",
    "doc_date",
    "error_code",
    # check_reference →
    "display_name",
    "iras_basis",
    "iras_basis_caveat",
    # decision-ledger memory (T5.5b) →
    "demoted",
    "annotation",
    "prior_dispositions",
    "fingerprint",
    # framing + technical →
    "candidate_framing_text",
    "completeness",
    "inputs_hash",
    "proposal_id",
    "proposal_status",
    "validation_status",
)

#: Keys of each audit-trail row (ledger timeline).
AUDIT_ROW_KEYS: tuple[str, ...] = (
    "seq",
    "tier",
    "tier_label",
    "tool_name",
    "outcome",
    "justification",
    "blocked_reason",
    "timestamp",
    "entry_hash",
)

#: Keys of the POST /sign response.
SIGN_KEYS: tuple[str, ...] = (
    "reviewer_name",
    "firm_name",
    "working_paper_path",
    "f5_summary",
    "validation_status",
    "disclaimer",
)

# The per-finding IRAS citation caveat — kept verbatim from ui.artifacts.check_reference.
_IRAS_CAVEAT = (
    "Illustrative citation — the IRAS basis shown is itself UNVALIDATED (T2.11 gates "
    "customer-facing claims); verify against the e-Tax Guides before any customer use."
)

# A loud demo/illustrative disclaimer carried on every payload.
DISCLAIMER = (
    "AgentAssist flags — you decide. Demo over FROZEN SBODEMOSG engine output; "
    "validation_status=unvalidated (T2.11 is the binding gate). Illustrative only — "
    "not a real client's real numbers, and not a compliance verdict."
)


def _client_identity(client_yaml: Path | str = _CLIENT_YAML) -> dict[str, str]:
    """Read the real client display identity from the committed YAML (no secrets)."""
    raw = yaml.safe_load(Path(client_yaml).read_text(encoding="utf-8")) or {}
    sap = raw.get("sap_b1", {}) or {}
    return {
        "client_id": str(raw.get("client_id", DEMO_CLIENT_ID)),
        "client_name": str(raw.get("client_name", "")),
        "company_db": str(sap.get("company_db", "")),
    }


def _period_label(period: dict) -> str:
    """Derive a quarter label (e.g. ``2024Q3``) from a {start,end} period block."""
    start = str((period or {}).get("start", "") or "")
    try:
        year, month, _ = start.split("-")
        quarter = (int(month) - 1) // 3 + 1
        return f"{year}Q{quarter}"
    except (ValueError, AttributeError):
        return start or "—"


def f5_summary(artifacts: DemoArtifacts) -> dict[str, Any]:
    """The FROZEN GST F5 return boxes (box-isolated source; never recomputed here)."""
    calc = ((artifacts.review_result or {}).get("compile_output") or {}).get("calculate") or {}
    return {
        "currency": calc.get("currency", "SGD"),
        "boxes": dict(calc.get("boxes") or {}),
    }


def _group_of(item: dict) -> str:
    """Server-side queue bucket. The API has no decision store (decisions are held in the
    client until a sign), so an item is ``marked_known`` iff the decision-ledger demoted it
    (T5.5b, present-but-demoted), else ``needs_review``. ``decided`` is owned by the client.
    """
    return "marked_known" if item.get("demoted") else "needs_review"


def serialize_queue_item(item: dict) -> dict[str, Any]:
    """One annotated adjudication item → a flat JSON queue row (exactly QUEUE_ITEM_KEYS).

    Joins ``flatten_finding_card`` (buried evidence → top-level) with ``check_reference``
    (display name + UNVALIDATED IRAS basis) and the T5.5b memory fields. Cardinality is
    preserved upstream; demoted items are flagged, never dropped.
    """
    flat = flatten_finding_card(item)
    ref = check_reference(item.get("check_id", "—"))
    completeness = item.get("completeness") or {}
    return {
        "finding_id": item.get("finding_id", "—"),
        "check_id": item.get("check_id", "—"),
        "finding_type": item.get("finding_type", "—"),
        "group": _group_of(item),
        "vendor": flat.get("vendor"),
        "severity": flat.get("severity"),
        "description": flat.get("description"),
        "recommendation": flat.get("recommendation"),
        "doc_num": flat.get("doc_num"),
        "doc_date": flat.get("doc_date"),
        "error_code": flat.get("error_code"),
        "display_name": ref.get("display_name"),
        "iras_basis": ref.get("iras_basis"),
        "iras_basis_caveat": _IRAS_CAVEAT,
        "demoted": bool(item.get("demoted", False)),
        "annotation": item.get("annotation"),
        "prior_dispositions": list(item.get("prior_dispositions") or ()),
        "fingerprint": item.get("fingerprint"),
        "candidate_framing_text": item.get("candidate_framing_text", ""),
        "completeness": {
            "required": list(completeness.get("required") or []),
            "present": list(completeness.get("present") or []),
            "missing": list(completeness.get("missing") or []),
            "satisfied": bool(completeness.get("satisfied", False)),
        },
        "inputs_hash": item.get("inputs_hash", "—"),
        "proposal_id": item.get("proposal_id"),
        "proposal_status": item.get("proposal_status"),
        "validation_status": VALIDATION_STATUS,
    }


def serialize_xero_queue(issues: list[dict]) -> list[dict[str, Any]]:
    """Project engine detect-issues from an uploaded Xero F5 export into the SHARED
    ``QueueItem`` rows the central review screen consumes (BUILD 2, A1 — same screen).

    REUSES ``serialize_queue_item`` / ``check_reference`` — so the Xero E-checks (E2/E3/E4)
    resolve to their REAL ``CHECK_REGISTRY`` ``iras_basis`` (the SAME citation the SAP path
    shows for the same check), never manufactured. The Xero-only enrichments the agent-loop
    dossier builder would add (``candidate_framing_text``, ``completeness``, decision-ledger
    memory) are ABSENT here and render gracefully as ""/empty/"—" — nothing is invented.

    ``finding_id`` uses the SAME semantics as the SAP path (``agent/dossier.py``):
    ``detect:{error_code}:{doc_num}``. A same-(code, doc_num) collision collides IDENTICALLY
    on both paths — a pre-existing property, deliberately NOT diverged on the Xero side.

    Surfaces, never asserts: every row carries ``validation_status="unvalidated"``; no verdict,
    no auto-correction, no write. The dark checks a Xero export cannot run are surfaced in
    ``coverage_status`` (degraded/unavailable), NEVER fabricated into this queue.
    """
    items: list[dict[str, Any]] = []
    for issue in issues:
        code = issue.get("error_code")
        item = {
            "finding_id": f"detect:{code}:{issue.get('doc_num')}",
            "check_id": code,
            "finding_type": "deterministic",
            # flatten_finding_card picks the payload bearing description/error_code (the issue).
            "evidence": {"detect_issue": issue},
        }
        items.append(serialize_queue_item(item))
    return items


# ── Ledger-recon (T2.24) → SHARED queue rows (PR-2; lean A = prose reuse) ─────────────
# Reuses serialize_queue_item / QUEUE_ITEM_KEYS — NO new contract key. The three review
# fields (ledger-transaction reference, GST box, impact-on-GST-payable) are folded into
# description/recommendation as prose; the impact figure is read VERBATIM from the finding
# (divergence/amount) — no arithmetic, no recompute (box-isolation).

# Ledger-recon is an INTERNAL-CONSISTENCY check, NOT an IRAS-cited finding. This honest
# basis replaces the citation serialize_queue_item would resolve via CHECK_REGISTRY —
# GST_LEDGER_RECON is deliberately absent from the registry, so we never manufacture a cite.
_LEDGER_RECON_IRAS_BASIS = (
    "Internal-consistency check — ledger-derived GST versus the declared F5 return. "
    "Not an IRAS-cited finding: it flags a divergence between two derivations of the same "
    "source for reviewer adjudication, never a verdict that either side is correct."
)
_LEDGER_RECON_DISPLAY = {
    "ledger_recon_divergence": "Ledger vs declared-return divergence",
    "not_included_gst_drop": "GST posting not included in the F5 return",
}
# Mechanical routing labels (finding-type → error_code) — NOT tax meaning.
_LEDGER_RECON_CODE = {
    "ledger_recon_divergence": "LEDGER_RECON",
    "not_included_gst_drop": "NOT_INCLUDED",
}


def _ledger_recon_prose(finding: dict) -> tuple[str, str]:
    """Fold ledger reference / GST box / impact-on-GST-payable into (description,
    recommendation) prose. Impact (``divergence``/``amount``) is read VERBATIM from the
    finding — no arithmetic; the GST box is a constant side→box lookup, not a computation.
    """
    ftype = finding.get("finding_type")
    description = finding.get("description") or "—"
    base_reco = finding.get("recommendation") or ""
    if ftype == "ledger_recon_divergence":
        side = finding.get("side")
        box = "Box 6" if side == "output" else "Box 7"  # constant lookup, not arithmetic
        impact = finding.get("divergence")              # VERBATIM
        detail = (
            f" (Ledger transaction reference: {side}-side 820 control-account aggregate; "
            f"GST box: {box}; impact on GST payable if adjudicated as an error: {impact}.)"
        )
    else:  # not_included_gst_drop
        reference = finding.get("reference") or finding.get("account") or "—"
        impact = finding.get("amount")                  # VERBATIM
        detail = (
            f" (Ledger transaction reference: {reference}; GST box: not included in any F5 "
            f"box (Transactions-not-included section); impact on GST payable if adjudicated "
            f"as declarable: {impact}.)"
        )
    return description, (base_reco + detail).strip()


def _serialize_one_ledger_finding(finding: dict) -> dict[str, Any]:
    """One T2.24 ledger-recon finding → a QueueItem row (exactly QUEUE_ITEM_KEYS)."""
    ftype = finding.get("finding_type", "")
    code = _LEDGER_RECON_CODE.get(ftype, "LEDGER_RECON")
    description, recommendation = _ledger_recon_prose(finding)
    # Stable per-finding id, mirroring the detect: path's {code}:{key} semantics.
    key = finding.get("side") if ftype == "ledger_recon_divergence" else (
        finding.get("reference") or finding.get("account")
    )
    item = {
        "finding_id": f"ledger_recon:{ftype}:{key or '-'}",
        "check_id": finding.get("check_id", "GST_LEDGER_RECON"),
        "finding_type": "deterministic",
        "candidate_framing_text": (
            "Internal-consistency candidate — a reviewer adjudicates whether the divergence "
            "is an error in the return; this is not a verdict."
        ),
        # flatten_finding_card picks the payload bearing description/error_code.
        "evidence": {"ledger_recon_finding": {
            "description": description,
            "recommendation": recommendation,
            "error_code": code,
            "severity": finding.get("severity"),  # ledger-recon carries none → None (lean B)
        }},
    }
    row = serialize_queue_item(item)
    # serialize_queue_item resolves display_name/iras_basis from CHECK_REGISTRY, which has
    # NO GST_LEDGER_RECON entry (→ id/"—"). Override with the HONEST internal-consistency
    # labels — never a manufactured IRAS citation. Same key set → QUEUE_ITEM_KEYS intact.
    return {
        **row,
        "display_name": _LEDGER_RECON_DISPLAY.get(ftype, "Ledger-vs-return reconciliation"),
        "iras_basis": _LEDGER_RECON_IRAS_BASIS,
    }


def serialize_ledger_recon_queue(compile_output: dict) -> list[dict[str, Any]]:
    """Project the T2.24 ledger-recon findings into SHARED QueueItem rows (PR-2, hop 1).

    Reads ``compile_output["ledger_recon_findings"]`` (Signal A: side + divergence) and
    ``compile_output["not_included_findings"]`` (Signal B: reference + amount). A None or
    absent key — the "unavailable" cannot-run state carried in the sibling ``*_status``
    key — yields NO rows (honest degradation, never a fabricated finding). The findings are
    DETERMINISTIC and UNGATED (never behind show_ai_candidates). Read-only over
    compile_output: the F5 boxes and the offline-replay oracle are untouched.
    """
    rows: list[dict[str, Any]] = []
    for finding in (compile_output.get("ledger_recon_findings") or []):
        rows.append(_serialize_one_ledger_finding(finding))
    for finding in (compile_output.get("not_included_findings") or []):
        rows.append(_serialize_one_ledger_finding(finding))
    return rows


def build_review_payload(artifacts: DemoArtifacts) -> dict[str, Any]:
    """Assemble GET /review: client + period + F5 summary + the serialised queue.

    The queue comes from ``annotated_adjudication_items`` — the demoted doc-592
    ``NO_GST_REG`` "Far East Imports" entry is present-but-demoted (T5.5b). Only the REAL
    frozen check types appear (E1 / E2 / NO_GST_REG / gst_amount_mismatch); the mock's
    aspirational DUP_CLAIM / SEQ_GAP / FLUX are not in the engine and never appear.
    """
    period = ((artifacts.review_result or {}).get("compile_output") or {}).get("period") or {}
    items = annotated_adjudication_items(artifacts)
    return {
        "client": _client_identity(),
        "period": {
            "start": period.get("start", "—"),
            "end": period.get("end", "—"),
            "label": _period_label(period),
        },
        "validation_status": VALIDATION_STATUS,
        "f5_summary": f5_summary(artifacts),
        "queue": [serialize_queue_item(it) for it in items],
        "disclaimer": DISCLAIMER,
    }


def build_audit_payload(artifacts: DemoArtifacts) -> list[dict[str, Any]]:
    """Assemble GET /audit: the hash-chained justification ledger as display rows."""
    return ledger_timeline_rows(artifacts.ledger)
