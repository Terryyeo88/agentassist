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

# Pure hermetic core (stdlib-only): fingerprint + append-only ledger + annotate/demote.
# Used here READ-ONLY — this module never writes the ledger (serialisers stay pure).
from agent.decision_ledger import (
    DEMOTE_DISPOSITIONS,
    AdjudicationEntry,
    DecisionLedger,
    annotate_and_demote,
    compute_family_fingerprint,
    compute_finding_fingerprint,
    count_superseded_entries,
)
from agent.upload_dossiers import dossier_queue_fields
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

# Source-aware disclaimers for the REAL-upload endpoints (D-2026-07-20-source-provenance).
# Value-only: the response key stays "disclaimer" (the exact key-set contract tests are
# locked) and every text preserves the honest-status wording verbatim. The demo-specific
# clauses ("Demo over FROZEN SBODEMOSG engine output", "not a real client's real numbers")
# are dropped only where they would be FALSE for a real upload; the b1-demo surfaces
# (/health, /audit, /command, /sign, serialize_review) keep DISCLAIMER unchanged.
_UPLOAD_DISCLAIMER_TEMPLATE = (
    "AgentAssist flags — you decide. Computed from {source_phrase}; "
    "validation_status=unvalidated (T2.11 is the binding gate). Findings are "
    "unvalidated candidates — not a compliance verdict."
)

# D-2026-07-26-xero-f5-basis (Terry R1/R4): the F5 entry is SOURCE-AWARE and basis-
# correct. On the F5 path the chain RECOMPUTES the boxes from transactions the
# client's own export already grouped by their own tax-code assignments — the bare
# word "Computed" (implies independent derivation, as on SAP) is FALSE there the
# moment boxes ship in the same body. Sales/extract genuinely compute from
# line-level data, so their wording stays byte-identical. This SUPERSEDES the old
# M2 one-Xero-text rule for the F5 entry only.
_XERO_F5_DISCLAIMER = (
    "AgentAssist flags — you decide. Recomputed from transactions your uploaded "
    "Xero export already grouped by your own tax-code assignments — the arithmetic "
    "is AgentAssist's, the classification is yours; "
    "validation_status=unvalidated (T2.11 is the binding gate). Findings are "
    "unvalidated candidates — not a compliance verdict."
)

#: source_kind -> disclaimer text. F5 carries the basis-correct wording (R1/R4);
#: sales + extract keep the legacy computed-from wording (true for them).
UPLOAD_DISCLAIMERS: dict[str, str] = {
    "xero_f5_upload": _XERO_F5_DISCLAIMER,
    "xero_sales_upload": _UPLOAD_DISCLAIMER_TEMPLATE.format(
        source_phrase="your uploaded Xero export"),
    "extract_review": _UPLOAD_DISCLAIMER_TEMPLATE.format(
        source_phrase="your uploaded extract"),
    "extract_upload": _UPLOAD_DISCLAIMER_TEMPLATE.format(
        source_phrase="your uploaded extract"),
}


def upload_disclaimer(source_kind: str) -> str:
    """Source-aware disclaimer for an upload response.

    Unknown/unmapped kinds fall back to the demo DISCLAIMER — fail-closed to the
    loudest wording rather than inventing a source label.
    """
    return UPLOAD_DISCLAIMERS.get(source_kind, DISCLAIMER)


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


# ── Xero F5 boxes — basis-carrying projection (D-2026-07-26-xero-f5-basis) ──────────

#: THE BASIS (Terry R1, client-facing, REQUIRED on every box-bearing F5 response).
#: Neither "computed" bare (implies independent derivation, as on SAP) nor "declared"
#: (implies figures read off the return) — the arithmetic is ours, the classification
#: is theirs, and agreement with the filed return is tautological (chain.py in-code).
XERO_F5_BOX_BASIS = (
    "Recomputed by AgentAssist from the transactions your Xero export already "
    "grouped by your own tax-code assignments. The arithmetic is AgentAssist's; "
    "the classification is yours. Agreement with the filed return is tautological, "
    "not confirmatory."
)


def build_recomputed_client_coded_f5_boxes(
    compile_output: dict,
    *,
    period: dict,
    source_file: dict,
    currency: str | None,
) -> dict[str, Any]:
    """The Xero-F5 box object — DELIBERATELY NOT named or shaped like ``f5_summary``.

    R2 failure asymmetry: an embedded discriminator can be ignored, and the failure
    mode of ignoring it is a Xero box strip rendering identically to the SAP one —
    a non-independent figure presented as a computed one. With a distinct key the
    worst case is the strip DOESN'T RENDER: failing-to-render is the honest failure.

    The basis is NOT a parameter: the constant is stamped here so no caller can omit
    or override it (required-never-optional, R2 belt and braces). A boxes-less object
    is impossible — missing/empty ``calculate.boxes`` raises instead of emitting a
    hollow basis-carrying shell.

    PURE READ over the JUST-COMPUTED compile_output (box-isolation): never call this
    with frozen demo artifacts — ``f5_summary(artifacts)`` reads FROZEN SBODEMOSG and
    would serve another client's boxes on a Xero page (R7a; test-pinned).

    Args:
        compile_output: the upload's own run_chain output (result.compile_output).
        period:         {"start","end"} as parsed from the export title block.
        source_file:    {"filename","sha256"} — the identity a reviewer can verify
                        (R6: no synthesised company identity on the Xero path).
        currency:       the export's OWN uniformly-stated currency, or None. None
                        OMITS the key entirely — never defaulted (R5: a defaulted
                        "SGD" on a non-SGD org is a false statement about money).
    """
    boxes = dict(((compile_output or {}).get("calculate") or {}).get("boxes") or {})
    if not boxes:
        raise ValueError(
            "recomputed_client_coded_f5_boxes requires the upload's computed calculate.boxes — "
            "refusing to emit a box object without boxes"
        )
    out: dict[str, Any] = {
        "boxes": boxes,
        "basis": XERO_F5_BOX_BASIS,
        "period": {"start": (period or {}).get("start"), "end": (period or {}).get("end")},
        "source_file": dict(source_file or {}),
    }
    if currency:
        out["currency"] = currency
    return out


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


def serialize_xero_queue(
    issues: list[dict],
    decision_entries: list[dict] | None = None,
    dossiers: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Project engine detect-issues from an uploaded Xero F5 export into the SHARED
    ``QueueItem`` rows the central review screen consumes (BUILD 2, A1 — same screen).

    REUSES ``serialize_queue_item`` / ``check_reference`` — so the Xero E-checks (E2/E3/E4)
    resolve to their REAL ``CHECK_REGISTRY`` ``iras_basis`` (the SAME citation the SAP path
    shows for the same check), never manufactured.

    t-dossier-xero: ``dossiers`` (finding_id → DossierArtifact from
    ``agent.upload_dossiers.generate_upload_dossiers``) populates the three ALREADY-PRESENT
    queue fields ``candidate_framing_text`` / ``completeness`` / ``inputs_hash`` with real
    hermetic-loop content — a VALUE-only change (the keys were already in QUEUE_ITEM_KEYS,
    previously defaulted to ""/empty/"—"). Falsy/absent dossiers (None, {}, or a finding
    with no matching dossier — e.g. the cap fired, or a branch not yet wired) leaves those
    fields at today's defaults — nothing is invented.

    ``finding_id`` uses the SAME semantics as the SAP path (``agent/dossier.py``):
    ``detect:{error_code}:{doc_num}``. A same-(code, doc_num) collision collides IDENTICALLY
    on both paths — a pre-existing property, deliberately NOT diverged on the Xero side.

    t-decision-persistence: ``decision_entries`` (persisted adjudications from
    ``agent.decision_store``, keyed on the upload's config client_id) RE-APPLIES prior
    reviewer decisions to this queue. Falsy (None or [] — no store / empty store) leaves
    the decision-memory keys at their defaults (demoted False, annotation None,
    prior_dispositions []). Non-empty entries run ``annotate_and_demote`` over the detect
    issues — the same cardinality-preserving read the frozen /review path uses — so a
    prior KNOWN_ACCEPTED renders the row demoted-but-PRESENT (never suppressed).
    VALUES change, KEYS never do (QUEUE_ITEM_KEYS intact).

    B3a-2 (fingerprint-always): every DETECT row carries its deterministic fingerprint
    REGARDLESS of store contents — computed here from the raw issue, and provably
    identical to the value ``annotate_and_demote`` stamps on the non-empty path (same
    ``compute_finding_fingerprint`` call on the same issue dict). This is what lets the
    panel POST a first-ever decision on a finding. Ledger-recon rows are NOT produced
    here and deliberately stay un-fingerprinted (no counterparty in their shape — a
    counterparty-free composition is #46 migration territory, not this build).

    Surfaces, never asserts: every row carries ``validation_status="unvalidated"``; no verdict,
    no auto-correction, no write. The dark checks a Xero export cannot run are surfaced in
    ``coverage_status`` (degraded/unavailable), NEVER fabricated into this queue.
    """
    annotated = None
    if decision_entries:
        ledger = DecisionLedger.from_entries(list(decision_entries))
        # Detect issues ARE the counterparty-bearing payloads the fingerprint keys on —
        # the same shape ui.artifacts feeds annotate_and_demote on the frozen path.
        annotated = annotate_and_demote(issues, ledger)

    items: list[dict[str, Any]] = []
    for pos, issue in enumerate(issues):
        code = issue.get("error_code")
        item = {
            "finding_id": f"detect:{code}:{issue.get('doc_num')}",
            "check_id": code,
            "finding_type": "deterministic",
            # flatten_finding_card picks the payload bearing description/error_code (the issue).
            "evidence": {"detect_issue": issue},
        }
        # B3a-2 fingerprint-always: unconditional, store-independent. The annotated branch
        # below overwrites with af.fingerprint — the identical value (annotate_and_demote
        # computes compute_finding_fingerprint(finding) on this same issue dict).
        item["fingerprint"] = compute_finding_fingerprint(issue)
        # t-dossier-xero: thread the three dossier-derived fields when this finding has a
        # dossier (1:1 join on the identical detect:{code}:{doc_num} id; string doc_nums
        # preserved). Absent → serialize_queue_item's defaults, exactly as before.
        if dossiers:
            dossier = dossiers.get(item["finding_id"])
            if dossier is not None:
                item.update(dossier_queue_fields(dossier))
        if annotated is not None:
            af = annotated[pos]
            item["fingerprint"] = af.fingerprint
            item["demoted"] = af.demoted
            item["annotation"] = af.annotation
            item["prior_dispositions"] = af.prior_dispositions
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


def _serialize_one_ledger_finding(
    finding: dict,
    period: Any = None,
    annotated: Any = None,
) -> dict[str, Any]:
    """One T2.24 ledger-recon finding → a QueueItem row (exactly QUEUE_ITEM_KEYS).

    Slice B: the row now carries a FAMILY-KEYED fingerprint, so a reviewer can adjudicate it.
    Signal A keys on (error_code, side, period_start, period_end) — the side and the
    AUTHORITATIVE run period, never anything parsed out of the description prose. Signal B
    keys on its journal reference; a BLANK reference keeps fingerprint None, which leaves the
    row visibly non-adjudicable rather than collapsing every blank-reference posting onto one
    shared key.

    ``annotated`` is this finding's AnnotatedFinding from the re-apply join, when a decision
    store exists — the same object the detect path uses, so a decision recorded here comes
    back demoted/annotated on the next read.
    """
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
    # Slice B: the family-keyed fingerprint. Computed from the PRODUCER dict (side /
    # reference), never from finding_id or prose. None stays None — an un-keyable row is
    # honestly non-adjudicable.
    item["fingerprint"] = compute_family_fingerprint(finding, period=period)
    if annotated is not None:
        item["fingerprint"] = annotated.fingerprint
        item["demoted"] = annotated.demoted
        item["annotation"] = annotated.annotation
        item["prior_dispositions"] = list(annotated.prior_dispositions)

    row = serialize_queue_item(item)
    # serialize_queue_item resolves display_name/iras_basis from CHECK_REGISTRY, which has
    # NO GST_LEDGER_RECON entry (→ id/"—"). Override with the HONEST internal-consistency
    # labels — never a manufactured IRAS citation. Same key set → QUEUE_ITEM_KEYS intact.
    return {
        **row,
        "display_name": _LEDGER_RECON_DISPLAY.get(ftype, "Ledger-vs-return reconciliation"),
        "iras_basis": _LEDGER_RECON_IRAS_BASIS,
    }


def serialize_ledger_recon_queue(
    compile_output: dict, decision_entries: Any = None
) -> list[dict[str, Any]]:
    """Project the T2.24 ledger-recon findings into SHARED QueueItem rows (PR-2, hop 1).

    Reads ``compile_output["ledger_recon_findings"]`` (Signal A: side + divergence) and
    ``compile_output["not_included_findings"]`` (Signal B: reference + amount). A None or
    absent key — the "unavailable" cannot-run state carried in the sibling ``*_status``
    key — yields NO rows (honest degradation, never a fabricated finding). The findings are
    DETERMINISTIC and UNGATED (never behind show_ai_candidates). Read-only over
    compile_output: the F5 boxes and the offline-replay oracle are untouched.
    """
    # Slice B: the run period keys Signal A, and it comes from compile_output — the
    # authoritative period the chain actually ran, not a string scraped from prose.
    period = compile_output.get("period")
    findings = list(compile_output.get("ledger_recon_findings") or []) + list(
        compile_output.get("not_included_findings") or []
    )
    annotated = None
    if decision_entries:
        ledger = DecisionLedger.from_entries(list(decision_entries))
        # The SAME join the detect path uses, so a decision recorded against one of these
        # rows re-applies on the next read instead of persisting invisibly.
        annotated = annotate_and_demote(findings, ledger, period=period)

    rows: list[dict[str, Any]] = []
    for pos, finding in enumerate(findings):
        rows.append(_serialize_one_ledger_finding(
            finding, period=period, annotated=None if annotated is None else annotated[pos]
        ))
    return rows


def build_review_payload(
    artifacts: DemoArtifacts,
    extra_decision_entries: list[dict] | None = None,
) -> dict[str, Any]:
    """Assemble GET /review: client + period + F5 summary + the serialised queue.

    The queue comes from ``annotated_adjudication_items`` — the demoted doc-592
    ``NO_GST_REG`` "Far East Imports" entry is present-but-demoted (T5.5b). Only the REAL
    frozen check types appear (E1 / E2 / NO_GST_REG / gst_amount_mismatch); the mock's
    aspirational DUP_CLAIM / SEQ_GAP / FLUX are not in the engine and never appear.

    t-decision-persistence: ``extra_decision_entries`` (the durable per-client store) is
    MERGED with the frozen fixture entries into one in-memory ledger for annotation.
    Falsy → byte-identical to before (the frozen fixture alone; empty store is a no-op).
    The merged object concatenates two independently-rooted hash chains, so it is a
    LOOKUP-ONLY view — it is never ``verify()``-ed and never persisted; each source chain
    verifies alone against its own store. Loaded per-request by the route handler, never
    cached (the lru_cache holds only the frozen artifacts).
    """
    period = ((artifacts.review_result or {}).get("compile_output") or {}).get("period") or {}
    merged_ledger = None
    if extra_decision_entries:
        merged_ledger = DecisionLedger.from_entries(
            list(artifacts.decision_ledger or []) + list(extra_decision_entries)
        )
    items = annotated_adjudication_items(artifacts, decision_ledger=merged_ledger)
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


# ── Decision-render view (D-2026-07-24-decision-render) ─────────────────────────────


def _adjudication_history(entries: list[AdjudicationEntry]) -> list[dict[str, Any]]:
    """AdjudicationEntry rows → plain history dicts (R4: structured fields AS DATA).

    Append-ordered, last = most recent (DecisionLedger.lookup preserves chain order —
    run-proven in the Phase-1 recon). Carries the STRUCTURED fields the paper may render
    (disposition/reviewer/timestamp/period); NEVER the latest-only annotation string, and
    NEVER the free-text reason (the UI verb hides in it — R3 forbids rendering verbs).
    """
    return [
        {
            "disposition": e.disposition,
            "reviewer": e.reviewer,
            "timestamp": e.timestamp,
            "period": e.period,
        }
        for e in entries
    ]


def _canonical_doc_num_str(raw: Any) -> str:
    """Display form of a doc_num: str-canonical, NEVER int() (the #34 pattern)."""
    return "" if raw is None else str(raw).strip()


def build_adjudication_view(clients: list[dict]) -> dict[str, Any] | None:
    """Assemble the decision view a signed paper renders — built HERE, passed AS DATA.

    The report layer stays a pure leaf (tests/test_leaf_import_purity.py): everything it
    needs arrives in this plain-dict view; it imports nothing from agent/.

    Args:
        clients: one spec per client store involved in the paper:
            ``{"client_id": str, "issues": [raw detect issues]?,``
            ``"stored_rows": [queue rows carrying "fingerprint"]?, "entries": [entry dicts]}``
            *issues* is the recompute path (the primary/per-slice run — the SAME
            annotate_and_demote read the upload queue uses, so demote semantics cannot
            drift); *stored_rows* is the accumulated non-primary path (stored fingerprints
            used AS-IS — stored rows carry "vendor" not "card_name", so a recompute would
            be wrong-by-construction; rows without a fingerprint, e.g. ledger-recon rows,
            are skipped, never crashed on).

    Returns:
        ``{"clients": [{"client_id", "superseded_count", "findings": [...]}]}`` with only
        ADJUDICATED findings (>=1 matching entry), each carrying its FULL ordered history;
        clients with nothing to say (no matches AND superseded_count == 0) are dropped;
        None when no client has anything to say — legacy renders stay byte-identical.
        A client with ONLY superseded (v0) entries IS kept: the aggregate count is the
        surfaced trace (R2); per-finding attribution of a v0 entry is structurally
        impossible (inert by construction) and is not attempted.
    """
    blocks: list[dict[str, Any]] = []
    for spec in clients:
        client_id = str(spec.get("client_id") or "")
        entries = list(spec.get("entries") or [])
        superseded = count_superseded_entries(entries) if entries else 0
        findings: list[dict[str, Any]] = []
        if entries:
            ledger = DecisionLedger.from_entries(entries)

            for af in annotate_and_demote(list(spec.get("issues") or []), ledger):
                if not af.prior_dispositions:
                    continue
                issue = af.finding
                findings.append({
                    # Same finding_id semantics as serialize_xero_queue (raw doc_num in
                    # the id, str-canonical in the display field).
                    "finding_id": f"detect:{issue.get('error_code')}:{issue.get('doc_num')}",
                    "check_id": str(issue.get("error_code") or ""),
                    "vendor": str(issue.get("card_name") or ""),
                    "doc_num": _canonical_doc_num_str(issue.get("doc_num")),
                    "fingerprint": af.fingerprint,
                    "demoted": af.demoted,
                    "history": _adjudication_history(ledger.lookup(af.fingerprint)),
                })

            for row in list(spec.get("stored_rows") or []):
                fingerprint = row.get("fingerprint")
                if not fingerprint:
                    continue  # un-fingerprinted rows (ledger-recon) — honest skip
                priors = ledger.lookup(fingerprint)
                if not priors:
                    continue
                findings.append({
                    "finding_id": str(row.get("finding_id") or ""),
                    "check_id": str(row.get("check_id") or ""),
                    "vendor": str(row.get("vendor") or ""),
                    "doc_num": _canonical_doc_num_str(row.get("doc_num")),
                    "fingerprint": fingerprint,
                    "demoted": any(e.disposition in DEMOTE_DISPOSITIONS for e in priors),
                    "history": _adjudication_history(priors),
                })

        if findings or superseded:
            blocks.append({
                "client_id": client_id,
                "superseded_count": superseded,
                "findings": findings,
            })
    return {"clients": blocks} if blocks else None
