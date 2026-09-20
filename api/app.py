"""api/app.py — FastAPI seam over the FROZEN review surface (T6.1 + T6.2).

Endpoints (read the frozen SBODEMOSG artifacts via the Mock path — no SAP, no model,
no tokens by default):

  * GET  /review/{client}/{period}  → client + period + F5 summary + serialised queue.
  * POST /sign                      → reproduces ui.sign.sign_working_paper (box-isolated).
  * GET  /audit                     → the hash-chained justification ledger rows.
  * POST /command                   → T6.2 (Lane C2): env-selected classifier → intent →
                                      execute_intent over the SAME frozen artifacts → JSON.

**Single artifacts source (T6.2 convergence fix).** The frozen artifacts are loaded ONCE
(``_shared_demo_artifacts``, cached) and the SAME underlying dicts back BOTH the /review
serialisation AND ``execute_intent`` (via a ``FrozenArtifacts`` twin sharing those dicts).
So the command path and the review surface read byte-identical data — no double-load drift.

``orchestrator/`` and ``engine/`` are untouched. This module imports ``ui``/``agent``/
``report`` view-models only; it never imports ``anthropic``. The classifier factory NAMES
the live backend but the SDK import stays lazy/confined to ``AnthropicClassifierBackend``'s
call site — so importing ``api/`` stays anthropic-free. Live tokens are a runtime event
only under ``AGENT_UI_CLASSIFIER=live`` (+ ``ANTHROPIC_API_KEY``); the default is scripted
and token-free.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Union

from dataclasses import replace as _dc_replace

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent.classifier_factory import (
    CLASSIFIER_ENV_VAR,
    MODE_SCRIPTED,
    ClassifierConfigError,
    make_classifier_backend,
)
# Durable per-client decision store (t-decision-persistence): stdlib-only writes under
# the gitignored decisions/ root — AgentAssist's OWN store, never a client-source write.
from agent.decision_store import append_decision, load_decision_entries
from agent.dispatch_exec import FrozenArtifacts, FrozenEngine, execute_intent
from agent.intent_classifier import (
    Classified,
    IntentClassifier,
    NeedsClarification,
    OutOfScope,
)
from agent.intent_curated import scripted_script
from api.viewmodel import (
    DEMO_CLIENT_ID,
    DEMO_PERIOD_LABEL,
    DISCLAIMER,
    build_adjudication_view,
    build_audit_payload,
    build_recomputed_client_coded_f5_boxes,
    build_review_payload,
    f5_summary,
    serialize_ledger_recon_queue,
    serialize_xero_queue,
    upload_disclaimer,
)
# t-dossier-xero: hermetic case-file dossiers on the upload paths. agent.upload_dossiers
# is stdlib+agent/ only (no anthropic, no SDK) — api/ stays anthropic-free at import.
from agent.upload_dossiers import generate_upload_dossiers
# t-review-accumulation (D-2026-07-23-review-accumulation): uploads may ATTACH to an
# explicit review session (request-only review_id — upload responses stay byte-identical).
# agent.review_store is stdlib-only (decision_store pattern); api/ stays anthropic-free.
import agent.review_store as review_store
# Shared with the CLI (run_agent) — assembles the T2.24 gst_ledger side-input from the
# uploaded Xero F5 workbook + optional 820 account-transactions export. Calls only feeder
# leaves (no anthropic/engine drag); the web layer must NOT import run_agent (the CLI).
from gst_ledger_input import build_gst_ledger_input
# api/ → feeders/ edge (source-selector Xero branch). ``feeders`` is a pure stdlib leaf
# (openpyxl is lazy on the .xlsx path); it imports NO anthropic/agent/engine/orchestrator,
# so this edge keeps api/ anthropic-free and engine-free (pinned by the import-scan tests).
from feeders.extract_reader import ExtractChainReader
from feeders.xero_f5_reader import (
    XeroF5ChainReader,
    is_xero_f5_workbook,
    parse_review_period,
)
from feeders.xero_sales_reader import (
    XeroSalesInvoiceChainReader,
    is_xero_sales_invoice_workbook,
)
from ui.artifacts import VALIDATION_STATUS, DemoArtifacts, load_demo_artifacts
from ui.sign import DEFAULT_OUTPUT_DIR, sign_working_paper
from documents.provider import FixtureDocumentProvider, MappedDocumentProvider

log = logging.getLogger(__name__)

app = FastAPI(
    title="AgentAssist review surface (T6.1/T6.2 demo seam)",
    description=(
        "Thin serve layer over the FROZEN SBODEMOSG engine output. Demo/illustrative, "
        "validation_status=unvalidated (T2.11 is the binding gate). SAP off, mock engine. "
        "POST /command runs the env-selected classifier (scripted by default, no tokens; "
        "live opt-in) then dispatch-execution over the same frozen artifacts."
    ),
    version="0.2.0",
)

# The Vite dev server proxies /api → uvicorn (same-origin in dev), but allow direct
# localhost calls too so `npm run dev` works without the proxy if needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# The four menu intents as command-bar buttons (offered alongside an out-of-scope reply).
COMMAND_BUTTONS: list[str] = ["Run a review", "Show ledger", "Show proposals", "Prior decisions"]

# POST /command response-shape contracts — the single source of truth pinned by the
# contract test and mirrored by the TS types in frontend/src/api.ts. One per `kind`,
# plus the ExecutionResult key set (= agent.dispatch_exec.ExecutionResult.to_dict()).
COMMAND_RESULT_KEYS: tuple[str, ...] = ("classifier_mode", "disclaimer", "kind", "intent", "execution")
COMMAND_OUT_OF_SCOPE_KEYS: tuple[str, ...] = ("classifier_mode", "disclaimer", "kind", "message", "buttons")
COMMAND_NEEDS_CLARIFICATION_KEYS: tuple[str, ...] = (
    "classifier_mode", "disclaimer", "kind", "intent", "missing", "message",
)
EXECUTION_KEYS: tuple[str, ...] = ("intent", "outcome", "sequence", "tiers", "params", "data", "notes")

# POST /review/upload (source-selector Xero branch) response contract. COVERAGE-ONLY: the
# top-level key set + the per-check coverage-row key set, pinned by the contract test and
# mirrored by the TS types in frontend/src/api.ts.
UPLOAD_COVERAGE_KEYS: tuple[str, ...] = (
    "source_kind", "validation_status", "disclaimer", "coverage_status",
)
COVERAGE_ROW_KEYS: tuple[str, ...] = ("check", "level", "reason")

# POST /review/upload Xero-F5 branch (engine path) response contract (BUILD 2, A1 — same
# screen): the coverage keys PLUS `queue` — a real-Xero-FORMAT review over an uploaded F5
# export projected into the SHARED central-screen QueueItem shape
# (api.viewmodel.serialize_xero_queue), candidates NOT verdicts, validation_status stays
# "unvalidated" (Inv-5). XERO_F5_UPLOAD_KEYS names the F5 branch ONLY (sales and extract have
# their own constants below — three different contracts exist and no constant may claim to
# describe "the Xero upload" unqualified). The coverage-era flat `findings` row is superseded
# by `queue` (the shared screen consumes QueueItem, not a bespoke 7-key row);
# `recomputed_client_coded_f5_boxes` was added by D-2026-07-26-xero-f5-basis (PR #151).
# tests/test_upload_keys_binding.py binds this constant (and each sibling) to the live
# handler body — it can no longer drift silently.
XERO_F5_UPLOAD_KEYS: tuple[str, ...] = (
    "source_kind", "validation_status", "disclaimer", "coverage_status", "queue",
    "recomputed_client_coded_f5_boxes",
)

# POST /review/upload GENERAL-EXTRACT engine branch (BUILD 3) response contract: the Xero-branch
# keys PLUS `config_scope` — the general-extract path run through the SAME chain via
# ExtractChainReader, under a DEMO/DEFAULT client config (`extract_demo`), gated by the global
# default-ON kill switch. Findings are unvalidated candidates computed under a config that is NOT
# the uploader's; `config_scope="default_demo"` is the marker the surface renders the LOUD
# default-config caveat from. source_kind is "extract_review" (distinct from the coverage-only
# "extract_upload"). No per-client identity exists on this path — the switch is GLOBAL only.
EXTRACT_REVIEW_KEYS: tuple[str, ...] = (
    "source_kind", "validation_status", "disclaimer", "coverage_status", "queue", "config_scope",
)

# POST /review/upload INBOUND XERO SALES-INVOICE branch (xero_sales, option-3 slice) response
# contract: the extract-review keys PLUS `out_of_scope` — the visible out-of-scope-lines note
# (count/by_code/reason) for lines carrying an accepted-but-set-aside TaxType (e.g. "No Tax").
# Run through the SAME chain via XeroSalesInvoiceChainReader under the Terry-authored
# `xero_sales_demo` config; `config_scope="xero_sales_demo"`. source_kind is "xero_sales_upload".
XERO_SALES_REVIEW_KEYS: tuple[str, ...] = (
    "source_kind", "validation_status", "disclaimer", "coverage_status", "queue",
    "config_scope", "out_of_scope",
)
OUT_OF_SCOPE_KEYS: tuple[str, ...] = ("count", "by_code", "reason")

# POST /sign/upload response contract (t-xero-signoff / B4) — pinned by
# tests/test_sign_upload_endpoint.py. The ONE place an uploaded Xero F5 review becomes a
# signed working paper + sealed bundle: the reviewer identity is stamped into the config
# BEFORE review() runs, so review()'s own full-argument Phase-5 render produces the
# signed-identity paper (no second renderer, no sign-path content drift). The SYSTEM never
# signs — the paper carries the reviewer's identity above an EMPTY ruled signature line.
SIGN_UPLOAD_KEYS: tuple[str, ...] = (
    "source_kind", "reviewer_name", "firm_name", "working_paper_path",
    "bundle_dir", "validation_status", "disclaimer",
)

# POST /decision response contract (t-decision-persistence) — pinned by
# tests/test_decision_endpoint_contract.py and mirrored by DecisionResponse in
# frontend/src/api.ts. A decision is a recorded human adjudication over a finding
# fingerprint — NEVER a verdict, and never a write to client data.
DECISION_KEYS: tuple[str, ...] = (
    "client_id", "finding_id", "action", "disposition", "fingerprint",
    "entry_id", "entry_hash", "reviewer", "timestamp", "chain_length",
    "validation_status", "disclaimer",
)

# GET /decisions/{client_id} response contract (C-6b) — pinned by
# tests/test_decisions_read_route.py. The READ half of the store the route above writes.
# `entries` are the stored records VERBATIM (asdict of AdjudicationEntry, oldest first) —
# not a projection: a surface listing prior decisions must render the ledger's own values,
# and a re-shaped record here would be this layer's account of the adjudication rather than
# the tamper-evident one. Note what a stored entry does NOT carry: `finding_id`. The record
# is keyed on the deterministic fingerprint alone, so a prior-decision row can name the
# fingerprint and not the finding — an honest gap, not one to fill by inference.
DECISIONS_READ_KEYS: tuple[str, ...] = (
    "client_id", "entries", "chain_length", "validation_status", "disclaimer",
)

# The four reviewer actions (mirrors frontend/src/components/FindingDetail.tsx DECISIONS)
# mapped onto the controlled T5.5 disposition vocabulary. Per the documented semantics:
# Accept = genuine issue accepted this period (annotate-only); Decline = the reviewer
# DISPUTES the flag (annotate-only); "Not an issue" and "Mark known" both set the finding
# aside as known/acceptable → KNOWN_ACCEPTED (demote-on-recurrence). The UI verb is
# preserved verbatim in the stored reason ("[<action>] <note>") so the two set-aside verbs
# stay distinguishable in the append-only record.
_ACTION_TO_DISPOSITION: dict[str, str] = {
    "Accept": "ACCEPTED",
    "Decline": "REJECTED",
    "Not an issue": "KNOWN_ACCEPTED",
    "Mark known": "KNOWN_ACCEPTED",
}

# Note-required actions — mirrors frontend NOTE_REQUIRED (FindingDetail.tsx). Three-times
# rule: this rule lives in the FE code, HERE, and the contract test.
_NOTE_REQUIRED_ACTIONS = frozenset({"Decline", "Not an issue", "Mark known"})

_CLIENT_ID_RE = re.compile(r"^[a-z0-9_]+$")

# Global kill switch (BUILD 3) — DEFAULT ON. Disable globally, without a code change, by setting
# AGENTASSIST_EXTRACT_ENGINE to a falsey token (0/off/false/no). GLOBAL ONLY: an anonymous extract
# upload has no per-client identity, so there is deliberately no per-client disable.
_EXTRACT_ENGINE_FLAG = "AGENTASSIST_EXTRACT_ENGINE"


def _extract_engine_enabled() -> bool:
    """Whether the general-extract engine path is ON (default True; env kill switch)."""
    return os.environ.get(_EXTRACT_ENGINE_FLAG, "").strip().lower() not in {"0", "off", "false", "no"}


# GET /working-paper allowlist (C2) — the ONLY directories a signed working-paper PDF may be
# served from. Path-safety is a containment check against these resolved roots (see
# get_working_paper): DEFAULT_OUTPUT_DIR is the frozen /sign output; t1.4-reports holds the
# engine intermediate PDF that sign returns as working_paper_path; audit/ holds the sealed
# bundles' durable report.pdf. Read-only: this route serves bytes, it never signs.
_REPO = DEFAULT_OUTPUT_DIR.resolve().parent.parent
_WORKING_PAPER_ROOTS = tuple(p.resolve() for p in (
    DEFAULT_OUTPUT_DIR,                             # frozen /sign output
    _REPO / "exploration-notes" / "t1.4-reports",  # engine intermediate PDF (working_paper_path)
    _REPO / "audit",                               # sealed bundles (durable report.pdf)
))

# C1: source-document viewer backing. Offline-safe fixture provider (INV-<doc_num>.pdf under
# tests/fixtures/documents). Terry can swap for CompositeProvider([UploadProvider,
# B1AttachmentProvider]) for real deployments; the route shape is unchanged. Reuses _REPO
# (defined above for C2) rather than recomputing the repo root.
_DOC_FIXTURE_DIR = _REPO / "tests" / "fixtures" / "documents"
_DOC_PROVIDER = FixtureDocumentProvider(_DOC_FIXTURE_DIR)


# --------------------------------------------------------------------------- #
# Single artifacts source — load ONCE, share the same dicts everywhere (T6.2).
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=1)
def _shared_demo_artifacts() -> DemoArtifacts:
    """The ONE frozen-artifacts load. Cached so /review, /audit, /sign and /command all
    read the SAME underlying dicts (no per-request reload, no double-load drift)."""
    return load_demo_artifacts()


def shared_artifacts() -> DemoArtifacts:
    """The shared ``DemoArtifacts`` (ui view-model side)."""
    return _shared_demo_artifacts()


@lru_cache(maxsize=1)
def shared_frozen_artifacts() -> FrozenArtifacts:
    """A ``FrozenArtifacts`` (Lane-A side) wrapping the SAME dict objects as
    ``shared_artifacts()`` — so ``execute_intent`` and ``/review`` are byte-identical."""
    demo = _shared_demo_artifacts()
    return FrozenArtifacts(
        review_result=demo.review_result,
        dossiers=demo.dossiers,
        proposals=demo.proposals,
        ledger=demo.ledger,
        decision_ledger=demo.decision_ledger,
    )


@lru_cache(maxsize=1)
def _shared_frozen_engine() -> FrozenEngine:
    """The frozen RUN_REVIEW engine over the SAME review_result the surface serialises."""
    return FrozenEngine(_shared_demo_artifacts().review_result)


class SignRequest(BaseModel):
    """POST /sign body. ``reviewer_name`` is required (sign refuses an empty reviewer)."""

    reviewer_name: str = Field(..., description="Reviewer of record; carried onto the working paper.")
    firm_name: str = Field("", description="Reviewer's firm (optional).")


class DecisionRequest(BaseModel):
    """POST /decision body (t-decision-persistence).

    A human reviewer's adjudication of ONE finding, keyed by its deterministic
    fingerprint. Persisted to AgentAssist's OWN append-only store — never a write to
    Xero/SAP/client data, and never a verdict on the return.
    """

    client_id: str = Field(..., description="Store key (config client_id, e.g. sbodemosg).")
    finding_id: str = Field(..., description="The queue row's finding_id (display echo).")
    fingerprint: str = Field(..., description="Deterministic finding fingerprint (sha256:…).")
    action: str = Field(..., description="Accept | Decline | Not an issue | Mark known.")
    note: str = Field("", description="Reviewer note; REQUIRED for all actions but Accept.")
    reviewer_name: str = Field(..., description="Reviewer of record for the adjudication.")
    period: Optional[str] = Field(None, description="Audit period label (e.g. 2024Q3).")


class CommandRequest(BaseModel):
    """POST /command body.

    ``utterance`` is classified to an intent; ``client_id`` / ``period`` are the SURFACE
    CONTEXT (the frontend supplies them) — identity slots come from context, NEVER guessed
    by the model. They are merged over the classifier's params on the Classified path.

    ``filters`` is a VIEW parameter (T6.3 Slice 3a) — surface-supplied findings facets
    (``{facet_name: value | [values]}``), NOT identity and NOT classifier-extracted.
    Pydantic gives SHAPE validation only; DOMAIN validation stays the engine's job — an
    off-domain value flows through to a structured ``filter_rejection`` in the response
    body (a result, not a 4xx). It can only narrow a view over already-computed findings;
    it never touches identity and never triggers a write. (Findings facets only this slice.)
    """

    utterance: str = Field(..., description="Free-text request to classify.")
    client_id: str = Field("", description="Surface context client id (e.g. sbodemosg).")
    period: str = Field("", description="Surface context period (e.g. 2024Q3).")
    filters: Dict[str, Union[str, List[str]]] = Field(
        default_factory=dict,
        description="View-only findings facet filters; validated downstream by the engine.",
    )


def _classifier_mode() -> str:
    """The active classifier mode label for honest framing (scripted | live)."""
    return (os.environ.get(CLASSIFIER_ENV_VAR) or "").strip().lower() or MODE_SCRIPTED


@app.get("/health")
def health() -> dict:
    """Liveness probe + the loud demo framing."""
    return {
        "status": "ok",
        "validation_status": VALIDATION_STATUS,
        "classifier_mode": _classifier_mode(),
        "disclaimer": DISCLAIMER,
    }


@app.get("/working-paper")
def get_working_paper(path: str) -> FileResponse:
    """Serve a signed working-paper PDF for download. Read-only, path-safe: the file must
    end in .pdf, exist, and resolve INSIDE one of the allowlisted output roots — three
    independent guards. Any ../ traversal is neutralized by resolve() + the containment
    check. 404 for anything else. Serves the PDF produced by any of the sign routes; it
    does not sign anything itself."""
    candidate = Path(path).resolve()
    if candidate.suffix.lower() != ".pdf" or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    if not any(candidate.is_relative_to(r) for r in _WORKING_PAPER_ROOTS):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(candidate, media_type="application/pdf", filename=candidate.name)


# D-34: a reference is served ONLY when the FULL string is the document's own identity —
# the bare doc_num form ("3005") or the invoice-number form ("INV-3005", the fixture's
# filename stem and face value). The previous digits shim (findall(r"\d+") -> last run)
# erased the corpus namespace: GET /document/BILL-3002 served the SAP fixture
# INV-3002.pdf (sha 98d08a5e…) — a different company's invoice — while the reference
# names the Xero corpus document BILL-3002.pdf (sha 9107458253…). Safe while one corpus
# existed; unsafe the moment a second one's references arrived. Any other-shaped
# reference (BILL-*, Q-*, …) is refused with the SAME 404 as an absent document.
# A namespace-aware provider for uploaded documents is T-E's job, not this route's.
_DOC_REF_IDENTITY = re.compile(r"(?:INV-)?(\d+)")


@app.get("/document/{doc_ref}")
def get_document(doc_ref: str) -> FileResponse:
    """Serve the source invoice PDF for a finding's document reference. Read-only.

    Accepts the document's own identity ONLY: a bare SAP doc_num (e.g. "3005") or the
    invoice-number form (e.g. "INV-3005"). Any other reference shape — including a
    Xero-style "BILL-3003" that merely shares a digit run with a fixture — is REFUSED
    with the honest 404, byte-identical to the absent-document case (D-34: refuse,
    never substitute across corpora). Path-safety: only the matched digits (an int)
    reach the provider — the raw string never builds a path, and a str path-param does
    not match "/"."""
    m = _DOC_REF_IDENTITY.fullmatch(doc_ref)
    if m is None:
        raise HTTPException(status_code=404, detail="No source document on file")
    doc_num = int(m.group(1))
    path = _DOC_PROVIDER.get_document(doc_num)
    if path is None or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="No source document on file")
    return FileResponse(Path(path), media_type="application/pdf", filename=f"INV-{doc_num}.pdf")


@app.get("/review/{review_id}/document/{doc_ref}")
def get_review_document(review_id: str, doc_ref: str) -> FileResponse:
    """Serve an UPLOADED source document, scoped to its review session (T-E(1), D-42).

    A SEPARATE route, deliberately NOT an extension of GET /document/{doc_ref}: two
    corpora, two routes, no shared resolver. The route above resolves the SAP fixture
    namespace by the document's own identity; this one resolves ONLY this review's
    uploaded set, passing the FULL reference VERBATIM through document_map.json —
    never parsed, stripped, or pattern-matched. Putting a corpus's naming convention
    into a shared resolver is what caused the D-34 substitution, and a third corpus
    would have repeated it. Malformed review_id, unknown review_id, and unmapped
    reference all return the SAME honest 404 — a wrong review must not learn what
    another review holds.
    """
    try:
        docs_dir = review_store.documents_dir(review_id)
    except review_store.ReviewStoreError:
        raise HTTPException(status_code=404, detail="No source document on file")
    path = MappedDocumentProvider(docs_dir).get_by_reference(doc_ref)
    if path is None:
        raise HTTPException(status_code=404, detail="No source document on file")
    return FileResponse(path, media_type="application/pdf", filename=f"{doc_ref}.pdf")


@app.get("/review/{client}/{period}")
def get_review(client: str, period: str) -> dict:
    """Serialised review view-model for the frozen demo client/period.

    Only the frozen (sbodemosg, 2024Q3) pair is backed by artifacts; any other path is a
    404 — we never dress empty data as a real client's real numbers.
    """
    if client.lower() != DEMO_CLIENT_ID or period.upper() != DEMO_PERIOD_LABEL:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No frozen artifacts for {client}/{period}. This demo serves "
                f"{DEMO_CLIENT_ID}/{DEMO_PERIOD_LABEL} only."
            ),
        )
    # t-decision-persistence: persisted adjudications RE-APPLY on every read. Loaded
    # per-request (NEVER cached — the lru_cache holds only the frozen artifacts); an
    # absent/empty store is a structural no-op, leaving the frozen payload byte-identical.
    persisted = load_decision_entries(DEMO_CLIENT_ID)
    return build_review_payload(shared_artifacts(), extra_decision_entries=persisted or None)


@app.post("/decision")
def post_decision(req: DecisionRequest) -> dict:
    """Durably record ONE reviewer adjudication (t-decision-persistence).

    Appends to AgentAssist's OWN per-client append-only DecisionLedger store
    (``agent.decision_store`` — the gitignored ``decisions/`` root). READ-NEVER-WRITE-ON-
    SOURCE: this endpoint's only write is that append; it imports no SAP/MCP/executor
    surface and cannot reach client data. A change of mind is a NEW appended record —
    history is never rewritten. The decision RE-APPLIES on the next read of the same
    data (GET /review, or re-upload) via the existing demoted/annotation/
    prior_dispositions/fingerprint queue keys — present-but-demoted, never suppressed.
    """
    action = req.action
    if action not in _ACTION_TO_DISPOSITION:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown action {action!r}. "
                f"Valid actions: {sorted(_ACTION_TO_DISPOSITION)}."
            ),
        )
    note = (req.note or "").strip()
    if action in _NOTE_REQUIRED_ACTIONS and not note:
        raise HTTPException(
            status_code=422,
            detail=f"A reviewer note is required for {action!r} (Accept alone needs none).",
        )
    reviewer = (req.reviewer_name or "").strip()
    if not reviewer:
        raise HTTPException(status_code=422, detail="reviewer_name must not be empty.")
    if not _CLIENT_ID_RE.fullmatch(req.client_id or ""):
        raise HTTPException(
            status_code=422,
            detail="client_id must match ^[a-z0-9_]+$ (it keys the decision store).",
        )
    if not req.fingerprint or not req.fingerprint.startswith("sha256:"):
        raise HTTPException(
            status_code=422,
            detail="fingerprint must be the finding's deterministic 'sha256:…' fingerprint.",
        )

    disposition = _ACTION_TO_DISPOSITION[action]
    # The UI verb rides verbatim in the append-only record ("[Mark known] <note>") so the
    # two KNOWN_ACCEPTED-mapped verbs stay distinguishable forever.
    reason = f"[{action}] {note}".rstrip()
    try:
        entry = append_decision(
            req.client_id,
            fingerprint=req.fingerprint,
            disposition=disposition,
            reviewer=reviewer,
            reason=reason,
            period=req.period,
        )
    except ValueError as exc:  # store-level guard (client_id / disposition vocabulary)
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "client_id": req.client_id,
        "finding_id": req.finding_id,
        "action": action,
        "disposition": disposition,
        "fingerprint": req.fingerprint,
        "entry_id": entry["entry_id"],
        "entry_hash": entry["entry_hash"],
        # C-6(a): the reviewer and the WHEN, read straight off the record just appended —
        # never re-derived here. `entry["timestamp"]` is the store's own append-time UTC
        # ISO-8601 stamp (agent/decision_ledger.py: "ISO-8601 timestamp of the adjudication"),
        # and both fields are hashed into the chain, so what a surface renders is the
        # tamper-evident ledger value rather than a client-side clock or a re-typed name.
        # Both are already present in `entry` (asdict of AdjudicationEntry) — this reads two
        # more keys off a dict already in hand; it adds no call and no new import.
        "reviewer": entry["reviewer"],
        "timestamp": entry["timestamp"],
        "chain_length": len(load_decision_entries(req.client_id)),
        "validation_status": VALIDATION_STATUS,
        "disclaimer": DISCLAIMER,
    }


@app.get("/decisions/{client_id}")
def get_decisions(client_id: str) -> dict:
    """Every decision recorded for *client_id*, oldest first (C-6b). Read-only.

    The READ half of the store ``POST /decision`` writes. Until this route existed the
    entries were loaded server-side only to be folded into some OTHER artefact — a
    re-applied queue key, a signed paper's adjudication view, a superseded count — so no
    surface could list prior decisions and the upload Audit view was empty on load by
    necessity, not by choice.

    SCOPED BY client_id, because that is how the store is laid out
    (``decisions/<client_id>/ledger.jsonl``): an entry carries no review_id and there is no
    session index, so a session-scoped read is not a thing this store can answer.

    An empty list is a 200, never a 404 — "this client has adjudicated nothing" is a fact
    about the client, and a 404 would make it indistinguishable from "no such client".
    The client_id is validated against the SAME rule the write applies: it names a
    directory, so one alphabet governs both directions and no path is built until it passes.

    READ-NEVER-WRITE: this endpoint creates nothing — not a directory, not an empty ledger
    file — and returns the stored records verbatim, including the ``reviewer`` and
    ``timestamp`` C-6(a) surfaced on the write response. Both are hashed into the
    append-only chain, so what a surface renders is the ledger's record rather than a
    re-derivation here.
    """
    if not _CLIENT_ID_RE.fullmatch(client_id or ""):
        raise HTTPException(
            status_code=422,
            detail="client_id must match ^[a-z0-9_]+$ (it keys the decision store).",
        )
    entries = load_decision_entries(client_id)
    return {
        "client_id": client_id,
        "entries": entries,
        "chain_length": len(entries),
        "validation_status": VALIDATION_STATUS,
        "disclaimer": DISCLAIMER,
    }


# Provenance map for review-session slices (t-review-accumulation): the DEMO config
# client_id each upload branch runs under. RECORD-ONLY on the slice — never a storage
# key (keying accumulation on client_id would merge different clients' uploads; the
# review keys on the explicit review_id alone). Mirrors the load_decision_entries call
# sites in the three branch builders.
_SLICE_CLIENT_IDS = {
    "xero_f5_upload": "xero_demo",
    "xero_sales_upload": "xero_sales_demo",
    "extract_review": "extract_demo",
    "extract_upload": "extract_demo",
}


def _attach_review_slice(
    review_id: str, resp: dict, file_bytes: bytes, period: Optional[dict],
    ledger_bytes: Optional[bytes] = None,
) -> None:
    """Attach one upload's serialized results to a review session (R2 semantics).

    Identity is (source_kind, sha256 of the uploaded primary): the same bytes re-uploaded
    are an IDEMPOTENT SKIP (no duplicate slice, no double-counting); different bytes with
    the same source_kind APPEND a superseding slice — the store never rewrites history and
    merged_view surfaces the supersession visibly. The slice stores the ALREADY-SERIALIZED
    response pieces (plain JSON — queue rows incl. dossier fields, coverage rows, branch
    extras), so the merged view rebuilds without re-running review(). The upload RESPONSE
    is never modified — review_id is request-only (no key churn on any upload literal).
    """
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    source_kind = resp.get("source_kind", "")
    if review_store.sha_already_attached(review_id, source_kind, sha256):
        return
    # t-accumulated-sign (R1): RETAIN the upload bytes so an accumulated sign can
    # re-run review() over the primary slice's exact bytes — the bounding invariant
    # (primary boxes byte-identical, never merged) true by construction. Retention is
    # forward-only; older sessions refuse loudly at sign time.
    review_store.save_upload_bytes(review_id, sha256, file_bytes)
    if ledger_bytes:
        review_store.save_upload_bytes(review_id, sha256, ledger_bytes, suffix=".ledger.xlsx")
    slice_record = {
        "source_kind": source_kind,
        "sha256": sha256,
        "client_id": _SLICE_CLIENT_IDS.get(source_kind),
        "period": period,
        "queue": resp.get("queue", []),
        "coverage_status": resp.get("coverage_status", []),
    }
    for extra in ("config_scope", "out_of_scope"):
        if extra in resp:
            slice_record[extra] = resp[extra]
    review_store.append_slice(review_id, slice_record)


def _validated_upload_review_id(review_id: Optional[str]) -> Optional[str]:
    """Normalize + guard the optional review_id form field (422 bad shape, 404 unknown)."""
    rid = (review_id or "").strip()
    if not rid:
        return None
    try:
        review_store._validated_review_id(rid)
    except review_store.ReviewStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not review_store.review_exists(rid):
        raise HTTPException(
            status_code=404, detail=f"No review session {rid!r} — create one via POST /review-session."
        )
    return rid


# T-E(1) source-document caps (D-39). Hard limits with an honest 413 — an unbounded
# read times N multipart files is a denial of service shipped by accident. Module-level
# so tests can shrink them without amending anything.
_DOC_MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MiB per document
_DOC_MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 50 MiB per upload
_DOC_MAX_COUNT = 50                      # documents per upload


@app.post("/review/upload")
async def post_review_upload(
    file: UploadFile = File(...),
    ledger: Optional[UploadFile] = File(None),
    documents: Optional[List[UploadFile]] = File(None),
    review_id: Optional[str] = Form(None),
) -> dict:
    """View over an UPLOADED client GST export (source-selector Xero branch).

    FORMAT ROUTING (two honest branches, both ``validation_status=unvalidated``):
      * a real Xero IRAS-F5 export ("Transactions by box number" sheet,
        ``is_xero_f5_workbook``) goes down the ENGINE path — ``_xero_f5_review_response``
        threads ``XeroF5ChainReader`` through ``engine.review.review`` (``run_chain``) and
        returns REAL (but unvalidated) findings as the SHARED central-screen ``queue``
        (BUILD 2, A1), candidates NOT verdicts;
      * any other ``.xlsx`` (the synthetic documents/business_partners/listing shape) stays
        COVERAGE-ONLY — an ``ExtractChainReader`` returns that reader's per-check
        DATA-COVERAGE status (``coverage_status()`` → ``CoverageStatus.as_dict()``), never
        running the engine. Coverage is a data-presence fact — which canonical fields the
        export carried — NOT a validated review and NOT a compliance verdict.

    Both responses are honestly framed — ``validation_status=unvalidated`` + the demo
    disclaimer; neither asserts a verdict.

    MULTIPART upload: a REQUIRED primary ``file`` (the GST export) + an OPTIONAL ``ledger``
    (the Xero 820 account-transactions export, T2.24). The multipart filename carries the
    name for the ``.xlsx`` suffix gate. When a ledger is supplied AND the primary routes to
    the Xero F5 handler, the ledger↔declared-return reconciliation runs (fork b: F5 path
    only); every other path IGNORES a supplied ledger. Omitting the ledger is a clean no-op.

    Both files land ONLY on a private system-temp dir (never the repo / committed fixtures)
    and are deleted right after the read, so no client data enters the diff. Any
    unreadable/garbage upload — primary OR ledger — is a client-input error (422), never a 500.
    """
    primary_name = file.filename or ""
    if Path(primary_name).suffix.lower() != ".xlsx":
        raise HTTPException(
            status_code=422,
            detail="Upload a single .xlsx GST export workbook as the 'file' part.",
        )
    body = await file.read()
    if not body:
        raise HTTPException(status_code=422, detail="Empty upload.")

    # t-review-accumulation: guard the OPTIONAL review_id up front (422 malformed,
    # 404 unknown) BEFORE any store write can happen. Absent → None → the stateless
    # path below is byte-identical to today (R1 pin).
    rid = _validated_upload_review_id(review_id)

    # --- T-E(1) source documents (D-36..D-39): validate-then-persist, BEFORE the ----
    # workbook branches run. Documents belong to the review SESSION, not the request:
    # D-37 makes review_id REQUIRED when documents are supplied — an honest 422, never
    # a silent drop into the request-scoped tmp_dir below (which dies in the finally).
    # Validation is all-or-nothing; the store writes only after every part passes.
    # The four document checks DO NOT run in T-E(1): nothing here touches coverage
    # rows, findings, boxes, or the response key set.
    doc_parts = [d for d in (documents or []) if (d.filename or "").strip()]
    if doc_parts:
        if rid is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Source documents require a review_id (create a session via "
                    "POST /review-session). Without one the upload is stateless and "
                    "the documents would be discarded with the request."
                ),
            )
        if len(doc_parts) > _DOC_MAX_COUNT:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Too many documents: the file-count limit is {_DOC_MAX_COUNT} "
                    "per upload."
                ),
            )
        doc_files: list = []
        doc_total = 0
        for part in doc_parts:
            doc_body = await part.read()
            if len(doc_body) > _DOC_MAX_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Document {part.filename!r} exceeds the per-file limit of "
                        f"{_DOC_MAX_FILE_BYTES} bytes."
                    ),
                )
            doc_total += len(doc_body)
            if doc_total > _DOC_MAX_TOTAL_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "Documents exceed the total upload limit of "
                        f"{_DOC_MAX_TOTAL_BYTES} bytes."
                    ),
                )
            doc_files.append((part.filename, doc_body))
        try:
            review_store.save_documents(rid, doc_files)
        except review_store.ReviewStoreError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    tmp_dir = Path(tempfile.mkdtemp(prefix="aa-extract-upload-"))
    try:
        dest = tmp_dir / "upload.xlsx"
        dest.write_bytes(body)

        # Optional ledger (T2.24). Suffix-gated like the primary; the BYTES are written to
        # temp here, but the ledger is only PARSED in the Xero F5 branch below (fork b) —
        # every other path ignores it. A present-but-empty part is treated as "no ledger".
        ledger_dest: Optional[Path] = None
        if ledger is not None and (ledger.filename or "").strip():
            if Path(ledger.filename).suffix.lower() != ".xlsx":
                raise HTTPException(
                    status_code=422,
                    detail="The optional ledger must be a .xlsx account-transactions export.",
                )
            ledger_body = await ledger.read()
            if ledger_body:
                ledger_dest = tmp_dir / "ledger.xlsx"
                ledger_dest.write_bytes(ledger_body)

        # --- PARSE BOUNDARY (Option A positional split) --------------------------------
        # ONLY reading/parsing the UNTRUSTED upload lives inside this try. A failure while
        # detecting the format or CONSTRUCTING a reader over the file (bad zip, missing
        # sheet, non-numeric cell, off-format) IS the client's file being unreadable → an
        # honest 422. FORMAT ROUTING: a real Xero IRAS-F5 export ("Transactions by box
        # number" sheet) uses the Xero reader; any other .xlsx (the synthetic documents/
        # business_partners/listing shape) uses ExtractChainReader. is_xero_f5_workbook
        # self-guards (an unreadable upload → False), so the only raisers here are the
        # reader constructors + the Xero period parse (+ the ledger assembly on the F5 path).
        gst_ledger: Optional[dict] = None
        try:
            is_xero = is_xero_f5_workbook(dest)
            # xero_sales is checked AFTER F5 (F5 keeps precedence) and BEFORE the Extract
            # fallback — a flat sales-invoice sheet is neither the F5 box-number sheet nor the
            # three-sheet extract shape, so without this branch it would hit ExtractChainReader
            # and hard-fail on the missing documents/business_partners/listing sheets.
            is_xero_sales = (not is_xero) and is_xero_sales_invoice_workbook(dest)
            if is_xero:
                reader = XeroF5ChainReader(dest)
                xero_period = parse_review_period(dest)
                # T2.24 (fork b): assemble the ledger side-input ONLY on the F5 path, and
                # ONLY when a ledger was uploaded — this PARSES the untrusted ledger and reads
                # the F5 workbook's declared boxes / not-included rows, inside the parse
                # boundary so a bad ledger is an honest 422 (never a 500).
                if ledger_dest is not None:
                    gst_ledger = build_gst_ledger_input(ledger_dest, dest, xero_period)
            elif is_xero_sales:
                # A TaxType the client neither maps nor marks out-of-scope makes the reader raise
                # ValueError — that is the USER'S FILE carrying an unmapped/parked code, an honest
                # 422 at the parse boundary (the committed config is tested to load clean).
                reader = _build_xero_sales_reader(dest)
            else:
                reader = ExtractChainReader(dest)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            # A parse failure on an UNTRUSTED upload (bad zip, missing sheet, bad cell, …)
            # is a 422 client-input error — never a 500, and never our internal bug.
            raise HTTPException(
                status_code=422, detail=f"Could not read export: {exc}"
            ) from exc

        # --- ENGINE EXECUTION (below the parse boundary) -------------------------------
        # run_chain / review / serialize / compile-access / coverage_status() derivation, over
        # an ALREADY-PARSED file. A failure here is OUR bug, not the user's file → an honest
        # 500, NEVER a mislabeled 422 "Could not read export". BUILD 3: the general-extract
        # engine path is ON by default (global kill switch); OFF → the coverage-only path,
        # byte-identical to before. The helpers' deliberate reconciliation-halt
        # HTTPException(422)s re-raise unchanged (they are a client-input signal, not our bug).
        try:
            resp: Optional[dict] = None
            if is_xero:
                # D-2026-07-26-xero-f5-basis (R6): the box object identifies the SOURCE
                # FILE (filename + sha256 of the uploaded bytes) — the identity a
                # reviewer can verify; never a synthesised company_db.
                source_file = {
                    "filename": primary_name,
                    "sha256": f"sha256:{hashlib.sha256(body).hexdigest()}",
                }
                resp = _xero_f5_review_response(
                    reader, xero_period, gst_ledger, source_file=source_file,
                    review_id=rid,
                )
            elif is_xero_sales:
                resp = _xero_sales_review_response(reader)
            elif _extract_engine_enabled():
                resp = _extract_review_response(reader)
            if resp is not None:
                # t-review-accumulation: attach AFTER the branch built its response —
                # the response itself is returned unchanged (review_id never enters it).
                # period is recorded when cheaply known (F5 title block); other branches
                # record None (provenance field, not a merge key).
                if rid:
                    _attach_review_slice(
                        rid, resp, body, period=xero_period if is_xero else None,
                        # Ledger companion bytes retained alongside (F5 path only) so an
                        # accumulated sign re-runs with the same reconciliation inputs.
                        ledger_bytes=(
                            ledger_dest.read_bytes()
                            if (is_xero and ledger_dest is not None) else None
                        ),
                    )
                return resp
            coverage_status = [status.as_dict() for status in reader.coverage_status()]
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("engine-internal failure on POST /review/upload")
            raise HTTPException(
                status_code=500,
                detail=(
                    "Internal error while processing this export — an application error, "
                    "not a problem with your uploaded file."
                ),
            ) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    coverage_only = {
        "source_kind": "extract_upload",
        "validation_status": VALIDATION_STATUS,
        "disclaimer": upload_disclaimer("extract_upload"),
        "coverage_status": coverage_status,
    }
    # Coverage-only uploads attach too (uniform slice shape, queue []) — coverage facts
    # are evidence about the review's period even when the engine did not run.
    if rid:
        _attach_review_slice(rid, coverage_only, body, period=None)
    return coverage_only


# ── Review sessions (t-review-accumulation) — accumulate uploads into ONE review ──────

class ReviewSessionRequest(BaseModel):
    """POST /review-session body — the deliberate create action (R1)."""
    label: str = Field("", description="Optional human label for the review session.")


@app.post("/review-session")
def post_review_session(req: Optional[ReviewSessionRequest] = None) -> dict:
    """Create an explicit review session; uploads then attach via the review_id form field.

    The id is server-generated (never client-derived — see agent/review_store.py's keying
    note). Local-files store under a gitignored root; append-only. Candidates-not-verdicts
    framing carries to every accumulated view.
    """
    record = review_store.create_review(label=(req.label if req is not None else ""))
    return {
        "review_id": record["review_id"],
        "created_at": record["created_at"],
        "label": record["label"],
        "validation_status": VALIDATION_STATUS,
        "disclaimer": DISCLAIMER,
    }


@app.get("/review-session")
def get_review_sessions() -> dict:
    """List review sessions (summaries only — id, label, slice count, source kinds)."""
    return {"reviews": review_store.list_reviews()}


class ReviewSessionSignRequest(BaseModel):
    """POST /review-session/{id}/sign body — the human sign action over a session."""
    reviewer_name: str = Field(..., description="Reviewer of record (required, non-empty).")
    firm_name: str = Field("", description="Optional firm name.")


@app.post("/review-session/{review_id}/sign")
def post_review_session_sign(review_id: str, req: ReviewSessionSignRequest) -> dict:
    """Sign ONE working paper over an accumulated review session (t-accumulated-sign).

    BOUNDING INVARIANT: the paper's boxes/structure/period come from the DESIGNATED
    PRIMARY slice ALONE (the active F5 slice, re-executed over its RETAINED bytes at
    sign time — byte-identical by construction, never merged arithmetic). Every other
    slice contributes FINDINGS ONLY, rendered from the #136 STORED rows (Terry R6:
    the reviewer signs what the merged view showed them) with visible provenance and
    attach timestamps (mixed vintage shown, never hidden). Refusals are LOUD and
    ordered: unknown session -> 404; empty / no-F5 / missing-retained-bytes / period
    disagreement / empty reviewer -> 422 with the reason named. THE SYSTEM NEVER
    SIGNS: the paper carries the reviewer identity above an empty ruled line, and the
    #43 guard applies exactly as on per-slice papers.
    """
    try:
        review_store._validated_review_id(review_id)
    except review_store.ReviewStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not review_store.review_exists(review_id):
        raise HTTPException(status_code=404, detail=f"No review session {review_id!r}.")

    reviewer = (req.reviewer_name or "").strip()
    if not reviewer:
        raise HTTPException(status_code=422, detail="reviewer_name must not be empty.")
    firm = (req.firm_name or "").strip()

    view = review_store.merged_view(review_id)
    active = view.get("slices") or []
    if not active:
        raise HTTPException(
            status_code=422,
            detail="This review session has no attached uploads — nothing to sign.",
        )

    # R2: F5-required primary — the F5 export carries the actual return figures.
    primary = next(
        (s for s in active if s.get("source_kind") == "xero_f5_upload"), None
    )
    if primary is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "This session has no F5 slice. The F5 export carries the return "
                "figures, so an accumulated paper cannot honestly claim F5 boxes "
                "without one — attach the F5 export, or sign per-slice."
            ),
        )

    # R1 (loud, forward-only): EVERY active slice must have retained bytes.
    for s in active:
        p = review_store.upload_bytes_path(review_id, s.get("sha256") or "")
        if not p.is_file():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Slice {s.get('source_kind')} (sha {str(s.get('sha256'))[:8]}) has "
                    "no retained upload bytes — this session predates byte retention; "
                    "re-attach its exports to sign the accumulated review."
                ),
            )

    # R3: hard refusal on any non-None period disagreement — never a silent union.
    periods = [
        (s.get("source_kind"), s["period"]) for s in active
        if isinstance(s.get("period"), dict)
    ]
    distinct = {(p["start"], p["end"]) for _, p in periods}
    if len(distinct) > 1:
        detail = "; ".join(
            f"{kind}: {p['start']} to {p['end']}" for kind, p in periods
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "Slices disagree on the review period — refusing to sign one paper "
                f"over conflicting periods ({detail}). Resolve the disagreement first."
            ),
        )

    # --- Re-run the PRIMARY over its retained bytes (persist_artifacts=False; the
    # accumulated render/seal below is THE persist event for this sign). -------------
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review
    import engine.review as _rev

    tmp_dir = Path(tempfile.mkdtemp(prefix="aa-accum-sign-"))
    try:
        primary_sha = primary.get("sha256") or ""
        dest = tmp_dir / "primary.xlsx"
        dest.write_bytes(review_store.upload_bytes_path(review_id, primary_sha).read_bytes())
        ledger_path = review_store.upload_bytes_path(
            review_id, primary_sha, suffix=".ledger.xlsx"
        )
        try:
            reader = XeroF5ChainReader(dest)
            xero_period = parse_review_period(dest)
            gst_ledger = None
            if ledger_path.is_file():
                ledger_dest = tmp_dir / "ledger.xlsx"
                ledger_dest.write_bytes(ledger_path.read_bytes())
                gst_ledger = build_gst_ledger_input(ledger_dest, dest, xero_period)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=422, detail=f"Could not re-read retained primary: {exc}"
            ) from exc

        try:
            cfg = _dc_replace(
                load_client_config("xero_demo", check_connectivity=False),
                reviewer_name=reviewer,
                firm_name=firm,
            )
            inputs = ReviewInputs(
                line_source=lambda: [], provider=None, reader=reader,
                gst_ledger=gst_ledger,
            )
            result = review(cfg, xero_period, inputs, persist_artifacts=False)
            if result.status != "completed" or result.compile_output is None:
                raise HTTPException(
                    status_code=422,
                    detail="Primary review could not complete (reconciliation halted).",
                )

            # Accumulated render: primary boxes/structure + non-primary STORED rows.
            from report.report import build_report
            from report.render import render_pdf
            from report.sections import build_accumulated_section
            from audit_bundle.seal import seal_bundle

            sign_run_at = result.run_completed_at
            accumulated = build_accumulated_section(
                view,
                primary_source_kind="xero_f5_upload",
                primary_sha256=primary_sha,
                sign_run_at=sign_run_at,
            )
            extra_artefacts = (
                {"exempt-supply": result.exempt_artefact}
                if result.exempt_artefact is not None else None
            )

            # t-decision-render: decision view over the primary run's findings + every
            # non-primary slice's STORED rows (stored fingerprints used as-is — no
            # recompute), one spec per client STORE. Visibility follows the per-slice
            # client split: F5 reads decisions/xero_demo/, sales xero_sales_demo/,
            # extract extract_demo/ — the #45 caveat (no client component in the
            # fingerprint) is unchanged and now user-facing on this paper.
            stored_rows_by_client: dict[str, list] = {}
            # Slice B: the PRIMARY F5 slice is still not taken wholesale — its detect rows are
            # RECOMPUTED below from result.compile_output, which stays authoritative. But its
            # ledger-recon and document rows are recomputed nowhere, so before Slice B a
            # decision on one of them was invisible on the accumulated paper exactly as it was
            # on the per-upload one. They now carry fingerprints, so they go down the SAME
            # stored_rows path as every non-primary slice. No double-count: detect rows come
            # from `issues`, these come from stored_rows, and the two sets are disjoint.
            primary_extra: list = []
            for s in active:
                if s.get("source_kind") == "xero_f5_upload":
                    primary_extra.extend([
                        r for r in (s.get("queue") or [])
                        if not str(r.get("finding_id", "")).startswith("detect:")
                    ])
                    continue
                cid = _SLICE_CLIENT_IDS.get(s.get("source_kind") or "")
                if cid:
                    stored_rows_by_client.setdefault(cid, []).extend(s.get("queue") or [])
            adjudication_view = build_adjudication_view([
                {
                    "client_id": cfg.client_id,
                    "issues": result.compile_output["detect"]["issues"],
                    "stored_rows": primary_extra,
                    "entries": load_decision_entries(cfg.client_id),
                },
                *[
                    {
                        "client_id": cid,
                        "stored_rows": rows,
                        "entries": load_decision_entries(cid),
                    }
                    for cid, rows in stored_rows_by_client.items()
                ],
            ])

            model = build_report(
                result.compile_output,
                cfg,
                generated_at=result.compile_output["fetch_manifest"]["fetched_at"],
                judgment_artefact=result.reasoning_artefact,
                document_candidates=result.document_candidates,
                extra_judgment_artefacts=extra_artefacts,
                accumulated=accumulated,
                adjudications=adjudication_view,
            )
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            safe_reviewer = re.sub(r"[^a-z0-9]+", "-", reviewer.lower()).strip("-") or "reviewer"
            pdf_path = render_pdf(
                model,
                Path(_rev._REPORTS_DIR)
                / f"accumulated-working-paper-{review_id}-{safe_reviewer}-{ts}.pdf",
            )
            signed_at = datetime.now(timezone.utc).isoformat()
            accumulated_json = {
                "review": view,
                "signed": {
                    "signed_at": signed_at,
                    "reviewer_name": reviewer,
                    "firm_name": firm,
                    "primary_source_kind": "xero_f5_upload",
                    "primary_sha256": primary_sha,
                    "sign_run_at": sign_run_at,
                },
            }
            bundle_dir = seal_bundle(
                client_config=cfg,
                period=xero_period,
                compile_output=result.compile_output,
                gate_results=result.gate_results,
                report_pdf_path=pdf_path,
                run_started_at=result.run_started_at,
                run_completed_at=result.run_completed_at,
                reasoning_artefact=result.reasoning_artefact,
                extra_reasoning_artefacts=extra_artefacts,
                extra_json_artefacts={"accumulated-review": accumulated_json},
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("engine-internal failure on POST /review-session/{id}/sign")
            raise HTTPException(
                status_code=500,
                detail=(
                    "Internal error while signing this review session — an "
                    "application error, not a problem with your session data."
                ),
            ) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    review_store.append_signed(review_id, {
        "signed_at": signed_at,
        "reviewer_name": reviewer,
        "firm_name": firm,
        "primary_source_kind": "xero_f5_upload",
        "primary_sha256": primary_sha,
        "working_paper_path": str(pdf_path),
        "bundle_dir": str(bundle_dir),
        "slices_signed": len(active),
    })
    return {
        "source_kind": "review_session_signed",
        "review_id": review_id,
        "reviewer_name": reviewer,
        "firm_name": firm,
        "working_paper_path": str(pdf_path),
        "bundle_dir": str(bundle_dir),
        "primary_source_kind": "xero_f5_upload",
        "primary_sha256": primary_sha,
        "slices_signed": len(active),
        "validation_status": VALIDATION_STATUS,
        "disclaimer": DISCLAIMER,
    }


@app.get("/review-session/{review_id}")
def get_review_session(review_id: str) -> dict:
    """The grouped-slices merged view of one review session (R6; 404 on unknown).

    Slices are grouped, never flattened (two sightings of one document from two export
    types are two evidentiary rows); supersession is VISIBLE (R2); coverage_matrix
    carries per-source attribution so one slice's level never masks another's. Honest
    limits (R3/R5, stated in docs): the signed working paper remains PER-SLICE, and a
    decision recorded on one slice does not carry to a same-fingerprint finding on a
    slice under a different config client_id (#45 territory).
    """
    try:
        review_store._validated_review_id(review_id)
    except review_store.ReviewStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not review_store.review_exists(review_id):
        raise HTTPException(status_code=404, detail=f"No review session {review_id!r}.")
    view = review_store.merged_view(review_id)
    # t-fingerprint-v1 (Terry R1): surface, AS DATA, how many stored adjudications do
    # NOT apply to this session's findings because their fingerprint version is
    # superseded (v0 entries are INERT under the v1 key — see decision_ledger's
    # named inert rule). Additive key, per distinct active-slice client_id; nothing
    # renders; non-application is never silent.
    from agent.decision_ledger import count_superseded_entries

    superseded: dict[str, int] = {}
    for s in view.get("slices") or []:
        cid = s.get("client_id")
        if cid and cid not in superseded:
            superseded[cid] = count_superseded_entries(load_decision_entries(cid))
    view["superseded_decisions"] = superseded
    view["validation_status"] = VALIDATION_STATUS
    view["disclaimer"] = DISCLAIMER
    return view


def _export_stated_currency(reader, period: dict) -> Optional[str]:
    """The export's OWN uniformly-stated currency, or None (R5: omit-never-default).

    Reads the reader's RAW ``DocCurrency`` values — the export's "Source currency"
    column verbatim (an empty cell stays "" = unstated). Deliberately NOT
    compile_output's ``doc_currency``, which orchestrator/steps.py normalises with an
    "SGD" default at fetch time — a defaulted value is not an export-stated fact, and
    a defaulted "SGD" on a non-SGD org would be a false statement about money.
    Exactly one distinct stated value across every fetched document → that value;
    none stated, or mixed → None (the response key is omitted entirely).
    """
    stated: set[str] = set()
    for entity in ("Invoices", "PurchaseInvoices", "CreditNotes", "PurchaseCreditNotes"):
        for doc in reader.fetch_invoices(entity, period["start"], period["end"]) or []:
            value = str(doc.get("DocCurrency") or "").strip().upper()
            if value:
                stated.add(value)
    return stated.pop() if len(stated) == 1 else None


def _xero_document_context(reader, period: dict, rid: Optional[str]):
    """(line_source, provider, join) for a review session's uploaded documents (T-E(2)).

    join = (matched, total), COMPUTED from the actual reference join (D-40 — never a
    flag, never an assumed length): total = the distinct documents the export carries
    (the review's own document population); matched = those with an uploaded document
    in reviews/<rid>/documents/. Returns (None, None, None) when the session has no
    documents — every caller then behaves exactly as before T-E(2).
    """
    if not rid:
        return None, None, None
    try:
        mapping = review_store.document_map(rid)
    except review_store.ReviewStoreError:
        return None, None, None
    if not mapping:
        return None, None, None
    docs = []
    for entity in ("Invoices", "PurchaseInvoices", "CreditNotes", "PurchaseCreditNotes"):
        docs.extend(reader.fetch_invoices(entity, period["start"], period["end"]))
    by_doc: Dict[str, dict] = {}
    for d in docs:
        ref = str(d.get("DocNum"))
        li = by_doc.setdefault(ref, {
            "doc_num": ref, "doc_date": d.get("DocDate"),
            "card_name": d.get("CardName"), "line_index": 0,
            "line_total": 0.0, "tax_total": 0.0,
        })
        for ln in d.get("DocumentLines") or []:
            li["line_total"] += float(ln.get("LineTotal") or 0)
            li["tax_total"] += float(ln.get("TaxTotal") or 0)
    items = list(by_doc.values())
    provider = MappedDocumentProvider(review_store.documents_dir(rid))
    matched = sum(1 for it in items if provider.get_document(it["doc_num"]) is not None)
    return (lambda: items), provider, (matched, len(items))


def _serialize_document_candidates(
    cands,
    line_items_by_ref: "Optional[dict]" = None,
    decision_entries: "Optional[list]" = None,
) -> list:
    """DocumentCandidate -> QueueItem rows via the SAME resolution the viewmodel uses.

    D-47: this function previously re-implemented an existing projection and violated
    the declared api.ts contract (completeness / iras_basis_caveat / inputs_hash null
    on non-nullable fields) — FindingDetail crashed live. Now: display_name and
    iras_basis resolve through CHECK_REGISTRY (the registry the viewmodel resolves
    through), the caveat is the shared _IRAS_CAVEAT constant, completeness states the
    truth (a candidate cannot exist unless the line item AND the source document were
    both present), inputs_hash is computed over the comparison's inputs, and
    vendor/doc_date carry the BOOKS' values joined from the very line items
    reconcile() consumed — passed in by the ONE call site; no second source of truth,
    no duplicated storage. (The invoice FACE's supplier/date may disagree with the
    books; that comparison is a FILED ASK B1 item — nothing here silently picks one.)

    finding_type derives from extraction_source (D-47): born-digital extraction is
    deterministic end to end; a model-assisted (scanned) extraction is probabilistic.
    D-46's ungated paper rendering rests on exactly this distinction.

    Slice B (G-4): the row now carries a fingerprint keyed on
    (check_id, counterparty, doc_num) — the SAME v1 triple the E-check family uses, so the
    canonicalisation rules are shared rather than re-implemented. The counterparty is KEPT
    (Terry ruling 1): Xero bill numbers can collide across suppliers, so keying on the
    document alone would let one adjudication sweep two suppliers' bills. A join MISS
    normalises to the named empty counterparty, which fails to re-apply — the honest failure —
    rather than re-applying to the wrong document.
    """
    from agent.decision_ledger import (  # noqa: PLC0415 — keep module import graph flat
        DecisionLedger, annotate_and_demote, compute_family_fingerprint,
    )
    from agent.registry import CHECK_REGISTRY  # noqa: PLC0415
    from api.viewmodel import _IRAS_CAVEAT  # noqa: PLC0415

    joined = line_items_by_ref or {}
    # The fingerprint payloads, in row order — the shape the fingerprint layer reads.
    fp_findings = [
        {
            "error_code": getattr(c, "check_id", None),
            "card_name": (joined.get(str(getattr(c, "doc_num", ""))) or {}).get("card_name"),
            "doc_num": getattr(c, "doc_num", None),
        }
        for c in (cands or [])
    ]
    annotated = None
    if decision_entries:
        # The SAME re-apply join as every other family, so a decision on a document row
        # comes back demoted/annotated instead of persisting invisibly.
        annotated = annotate_and_demote(
            fp_findings, DecisionLedger.from_entries(list(decision_entries))
        )

    rows = []
    for pos, c in enumerate(cands or []):
        born = getattr(c, "extraction_source", "") == "born_digital"
        prov = (
            "born-digital (deterministic extraction)" if born
            else "model-assisted extraction (scanned image)"
        )
        li = joined.get(str(c.doc_num)) or {}
        spec = CHECK_REGISTRY.get(c.check_id)
        inputs_hash = "sha256:" + hashlib.sha256(json.dumps({
            "check_id": c.check_id,
            "doc_num": str(c.doc_num),
            "extracted_value": c.extracted_value,
            "listing_value": c.listing_value,
        }, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        rows.append({
            "finding_id": f"doccheck:{c.check_id}:{c.doc_num}",
            "check_id": c.check_id,
            "finding_type": "deterministic" if born else "probabilistic",
            "group": "needs_review",
            "vendor": li.get("card_name"),
            "severity": c.severity,
            "description": c.message,
            "recommendation": None,
            "doc_num": c.doc_num,
            "doc_date": li.get("doc_date"),
            "error_code": c.check_id,
            "display_name": (spec.display_name if spec else str(c.check_id).replace("_", " ")),
            "iras_basis": (spec.iras_basis if spec else None),
            "iras_basis_caveat": _IRAS_CAVEAT,
            # Slice B: adjudicable. The fingerprint is unconditional and store-independent
            # (the fingerprint-always property); the re-apply join below overwrites with the
            # identical value plus this row's decision history.
            "demoted": False if annotated is None else annotated[pos].demoted,
            "annotation": None if annotated is None else annotated[pos].annotation,
            "prior_dispositions": (
                [] if annotated is None else list(annotated[pos].prior_dispositions)
            ),
            "fingerprint": (
                compute_family_fingerprint(fp_findings[pos]) if annotated is None
                else annotated[pos].fingerprint
            ),
            "candidate_framing_text": (
                f"Invoice cross-reference candidate ({prov}) — a reviewer adjudicates "
                "against the source document; this is a candidate, not a verdict."
            ),
            "completeness": {
                "required": ["line_item", "source_document"],
                "present": ["line_item", "source_document"],
                "missing": [],
                "satisfied": True,
            },
            "inputs_hash": inputs_hash,
            "proposal_id": None,
            "proposal_status": None,
            "validation_status": "unvalidated",
        })
    return rows


def _xero_f5_review_response(
    reader, period: dict, gst_ledger: Optional[dict] = None,
    *, source_file: Optional[dict] = None, review_id: Optional[str] = None,
) -> dict:
    """Run the real (UNVALIDATED) engine review over an uploaded Xero IRAS-F5 export.

    ``reader`` (``XeroF5ChainReader``) and ``period`` are constructed at the PARSE BOUNDARY in
    ``post_review_upload`` and passed in, so this function is pure ENGINE EXECUTION — any failure
    here is our internal bug over an already-parsed file (→ honest 500), never a mislabeled 422.

    Threads PR-A's XeroF5ChainReader through engine.review.review(): the deterministic chain
    (run_chain) surfaces the line-level E-check findings (E2/E3/E4 on the demo fixture); the
    surfaces a Xero export lacks (supplier master, document-number listing) degrade honestly in
    coverage_status (NO_GST_REG unavailable, DUP_CLAIM/SEQ_GAP degraded) — never as silent
    absence and never fabricated.

    HONEST STATUS: real-Xero-FORMAT findings over (here) SYNTHETIC data — CANDIDATES, never
    verdicts. validation_status stays "unvalidated" (Inv-5); no AI candidates surface; the
    VatGroup mapping is PROPOSED (DEBT-1); accuracy is NOT validated (T2.11 unmoved).

    DEBT-9 RESOLVED (8daf757 / PR #83): load_client_config("xero_demo") requires NO SAP
    credentials — xero_demo.yaml declares source_system "xero", so the loader's is_sap_sourced
    gate (config/loader.py, step 2.5/5) skips the sap_b1 block + env-var requirement; SAP
    connection fields load as "" and the injected XeroF5ChainReader short-circuits every read.
    Endpoint-level pin: tests/test_debt9_endpoint_creds_absent.py (creds-absent 200).
    """
    # Lazy imports keep api/ anthropic-free AT MODULE IMPORT (Inv-1): engine.review pulls
    # reasoning.reg2627, whose anthropic import is itself lazy — so importing api.app loads
    # neither; they resolve only when this endpoint actually runs.
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review

    cfg = load_client_config("xero_demo", check_connectivity=False)
    # A Xero F5 export has no SI-purchase-line / source-document surface; the surfaced findings
    # come entirely from run_chain via the reader. An empty line_source (Reg26/27 emits a clean
    # no-LLM artefact) and no provider (documents pass skipped) keep this hermetic.
    # T2.24 (fork b/c): gst_ledger is supplied only on the F5 path and only when a ledger was
    # uploaded; None → run_chain adds no ledger keys and the recon is a clean no-op.
    # T-E(2): when the review session carries uploaded documents, thread them into
    # Phase 3 — a per-document line_source built from the reader's own rows, the
    # review's MappedDocumentProvider, and the COMPUTED join on the reader's coverage
    # rows (D-40). Without documents all three are None and this is byte-identical.
    doc_line_source, doc_provider, doc_join = _xero_document_context(reader, period, review_id)
    if doc_join is not None:
        reader.document_join = doc_join
    inputs = ReviewInputs(
        line_source=doc_line_source or (lambda: []), provider=doc_provider,
        reader=reader, gst_ledger=gst_ledger
    )
    # M2 (t-xero-signoff): a plain upload is a PURE review — no unsigned PDF, no unsigned
    # bundle lands on disk. Persistence happens only at sign time (POST /sign/upload).
    result = review(cfg, period, inputs, persist_artifacts=False)
    if result.status != "completed" or result.compile_output is None:
        # A reconciliation halt on an untrusted upload is a client-input error, never a 500.
        raise HTTPException(
            status_code=422,
            detail="Review could not complete over this export (reconciliation halted).",
        )

    # A1 (same screen): project each detect issue into the SHARED central-screen QueueItem
    # (reuses serialize_queue_item/check_reference — E2/E3/E4 carry their real registry
    # iras_basis). The dark checks a Xero export cannot run stay in coverage_status
    # (degraded/unavailable), NEVER fabricated into this queue. T2.24: the ledger-recon rows
    # (Signal A + B) merge in via serialize_ledger_recon_queue — [] when no ledger, both
    # emit QUEUE_ITEM_KEYS, ungated.
    # t-decision-persistence: persisted adjudications for this config's client_id RE-APPLY
    # here (loaded per-request; [] → falsy → demoted/annotation/prior_dispositions stay at
    # defaults). B3a-2: detect rows ALWAYS carry their fingerprint (store-independent), so
    # the panel can persist a first-ever decision. Ledger-recon rows stay un-fingerprinted
    # (different finding shape, no counterparty; #46 territory) and render non-adjudicable.
    # t-dossier-xero: hermetic case-file dossiers over the SAME ReviewResult (no model,
    # no network — the loop runs an authored template transport; cage stays PENDING-only
    # and the staging store is discarded with the request). Cap fired → no dossiers, an
    # honest degraded coverage row below, queue fields stay at their defaults.
    upload_dossiers = generate_upload_dossiers(result)
    # Loaded ONCE and shared by all three families, so every row on this queue re-applies
    # against the same store read (Slice B).
    decision_entries = load_decision_entries(cfg.client_id)
    queue = serialize_xero_queue(
        result.compile_output["detect"]["issues"],
        decision_entries=decision_entries,
        dossiers=upload_dossiers.dossiers,
    ) + serialize_ledger_recon_queue(result.compile_output, decision_entries=decision_entries)
    # T-E(2): document cross-reference candidates join the queue. Slice B: they now carry a
    # fingerprint and re-apply like every other family.
    queue = queue + _serialize_document_candidates(
        result.document_candidates,
        {str(it["doc_num"]): it for it in (doc_line_source() if doc_line_source else [])},
        decision_entries=decision_entries,
    )
    coverage_status = [status.as_dict() for status in reader.coverage_status()]
    if upload_dossiers.capped:
        log.warning("dossier cap exceeded on xero_f5_upload — generation skipped")
        coverage_status.append(_dossier_cap_coverage_row())
    return {
        "source_kind": "xero_f5_upload",
        "validation_status": VALIDATION_STATUS,
        "disclaimer": upload_disclaimer("xero_f5_upload"),
        "coverage_status": coverage_status,
        "queue": queue,
        # D-2026-07-26-xero-f5-basis: the basis-carrying box object — a PURE READ over
        # the upload's OWN just-computed compile_output (box-isolation; NEVER
        # viewmodel.f5_summary(artifacts), which reads FROZEN SBODEMOSG — R7a).
        # Constructed ONLY here, on the F5 branch (R3 structural gate): an F5 export is
        # the full return, so all 8 boxes are legitimate; sales/extract are one-sided
        # and carry no boxes (adding them would widen #48 onto unsigned JSON). The key
        # name deliberately avoids "f5_summary" (R2 failure asymmetry: old code looking
        # for that key finds NOTHING rather than something SAP-styled).
        "recomputed_client_coded_f5_boxes": build_recomputed_client_coded_f5_boxes(
            result.compile_output,
            period=period,
            source_file=source_file or {},
            currency=_export_stated_currency(reader, period),
        ),
    }


def _dossier_cap_coverage_row() -> dict:
    """The honest degraded row appended when the bounded dossier cap fires (R2).

    coverage_status is the surface that says what ran and what degraded — the
    disclaimer stays legal framing. Same {check, level, reason} shape as every
    other row; appended, never replacing the reader's rows.
    """
    from agent.upload_dossiers import _MAX_DOSSIER_FINDINGS

    return {
        "check": "case_file_dossiers",
        "level": "degraded",
        "reason": (
            f"finding count exceeds the {_MAX_DOSSIER_FINDINGS}-finding dossier "
            "cap — case-file dossier generation was skipped for this upload; "
            "queue rows carry no framing/completeness/inputs_hash content."
        ),
    }


def _derive_extract_period(reader) -> dict:
    """Derive ``{start, end}`` from the extract's own DocDate range.

    A generic extract carries no "for the period …" line (unlike a Xero F5 export). The reader
    IGNORES the period args (it returns every row), so this only labels the review + scopes the
    Reg 26/27 pass. Falls back to a wide window when no dated document is present. Plumbing only —
    no chain/engine change, no tax semantics.
    """
    dates: list[str] = []
    # The four ENTITY_ROUTING buckets (Invoices/PurchaseInvoices/CreditNotes/PurchaseCreditNotes).
    for entity in ("Invoices", "PurchaseInvoices", "CreditNotes", "PurchaseCreditNotes"):
        for doc in reader.fetch_invoices(entity, "", ""):
            iso = str(doc.get("DocDate") or "")[:10]
            if iso:
                dates.append(iso)
    if dates:
        return {"start": min(dates), "end": max(dates)}
    return {"start": "1900-01-01", "end": "2999-12-31"}


def _extract_review_response(reader) -> dict:
    """Run the real (UNVALIDATED) engine review over an uploaded GENERAL extract, under a
    DEMO/DEFAULT client config (BUILD 3 — general-extract path ON; global kill switch).

    ``reader`` (``ExtractChainReader``) is constructed at the PARSE BOUNDARY in
    ``post_review_upload`` and passed in, so this function is pure ENGINE EXECUTION — any failure
    here is our internal bug over an already-parsed file (→ honest 500), never a mislabeled 422.

    Threads ``ExtractChainReader`` through ``engine.review.review()`` EXACTLY as the Xero branch
    does — NO chain/engine change. Findings are projected into the SHARED central-screen QueueItem
    shape (``serialize_xero_queue``); the checks the export cannot support degrade honestly in
    ``coverage_status`` (never fabricated — the fixed-schema reader cannot infer/guess a column).

    THE HONESTY LINE: this run uses the ``extract_demo`` DEFAULT config, NOT the uploader's own tax
    settings — ``config_scope="default_demo"`` is the marker the surface renders the LOUD
    default-config caveat from (any rate/tax-code-mapping-dependent finding is the demo's, not the
    client's). Findings are CANDIDATES, never verdicts; validation_status stays "unvalidated"
    (Inv-5); no AI candidates; accuracy NOT validated (T2.11 unmoved). Synthetic-format at best;
    real-client-export validation stays GTM-gated.
    """
    # Lazy imports keep api/ anthropic-free AT MODULE IMPORT (Inv-1) — same posture as the Xero branch.
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review

    cfg = load_client_config("extract_demo", check_connectivity=False)
    period = _derive_extract_period(reader)
    inputs = ReviewInputs(line_source=lambda: [], provider=None, reader=reader)
    # M2: pure review — no persisted artefacts on a plain upload.
    result = review(cfg, period, inputs, persist_artifacts=False)
    if result.status != "completed" or result.compile_output is None:
        # A reconciliation halt on an untrusted upload is a client-input error, never a 500.
        raise HTTPException(
            status_code=422,
            detail="Review could not complete over this export (reconciliation halted).",
        )

    # t-dossier-xero DEFERRAL (reported, not silent): the extract branch is NOT wired for
    # dossiers in this build. Extract uploads yield NO_GST_REG findings whose required
    # supplier_catalog slot is agent-gathered; the extract SOURCE genuinely carries the
    # supplier data (FederalTaxID sheet), so neither R5 reason ("not gatherable on this
    # source" / "gathering failed") would be honest for an unwired gather — and the
    # reader's canonical BP projection carries no CardName to key an honest catalog.
    # Rows keep today's ""/empty/"—" defaults until the catalog plumbing follow-up.
    queue = serialize_xero_queue(
        result.compile_output["detect"]["issues"],
        decision_entries=load_decision_entries(cfg.client_id),
    )
    coverage_status = [status.as_dict() for status in reader.coverage_status()]
    return {
        "source_kind": "extract_review",
        "validation_status": VALIDATION_STATUS,
        "disclaimer": upload_disclaimer("extract_review"),
        "coverage_status": coverage_status,
        "queue": queue,
        "config_scope": "default_demo",
    }


def _build_xero_sales_reader(source):
    """Construct the inbound Xero sales-invoice reader over an uploaded export.

    The TaxType -> VatGroup mapping + out_of_scope_codes are read from the Terry-authored
    ``xero_sales_demo`` config (IRAS Annex E). The reader holds NO table of its own — the config
    is the authority. A TaxType the client neither maps nor marks out-of-scope makes the reader
    raise ValueError; at the parse boundary that is the client's file carrying an unmapped/parked
    code → an honest 422 (the committed config is tested to load clean, so a config-load failure
    is not the expected raiser here).
    """
    from config.loader import load_client_config

    cfg = load_client_config("xero_sales_demo", check_connectivity=False)
    return XeroSalesInvoiceChainReader(
        source,
        tax_code_mappings=cfg.effective_tax_code_mappings,
        out_of_scope_codes=cfg.out_of_scope_codes,
    )


def _xero_sales_review_response(reader) -> dict:
    """Run the real (UNVALIDATED) engine review over an uploaded inbound Xero SALES-INVOICE export.

    ``reader`` (``XeroSalesInvoiceChainReader``) is constructed at the PARSE BOUNDARY in
    ``post_review_upload`` and passed in, so this function is pure ENGINE EXECUTION — any failure
    here is our internal bug over an already-parsed file (→ honest 500), never a mislabeled 422.

    Threads the reader through ``engine.review.review()`` EXACTLY as the Xero-F5 / general-extract
    branches do — NO chain/engine change. Findings project into the SHARED central-screen QueueItem
    shape (``serialize_xero_queue``); the surfaces a sales-only export lacks (supplier master,
    listing, credit notes, purchase side, source PDFs) degrade honestly in ``coverage_status``
    (NO_GST_REG unavailable, DUP_CLAIM/SEQ_GAP degraded), never fabricated. The out-of-scope-lines
    note is surfaced VISIBLY in ``out_of_scope`` (count/by_code/reason).

    HONEST STATUS: real-Xero-FORMAT findings over (here) SYNTHETIC data — CANDIDATES, never
    verdicts. validation_status stays "unvalidated" (Inv-5); no AI candidates; the mapping is
    Terry-authored (IRAS Annex E); accuracy NOT validated (T2.11 unmoved). ``config_scope`` marks
    that the review ran under the ``xero_sales_demo`` config (13 further Xero codes are PARKED).
    """
    # Lazy imports keep api/ anthropic-free AT MODULE IMPORT (Inv-1) — same posture as the other branches.
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review
    from feeders.xero_sales_lines import xero_sales_lines

    cfg = load_client_config("xero_sales_demo", check_connectivity=False)
    period = _derive_extract_period(reader)  # a sales export carries no "for the period …" line
    # Prompt E: the adapter connects this upload to the exempt-supply pass (Phase 2b).
    # real-FORMAT over synthetic Xero, NOT real-client-validated; exempt skill now runs
    # on Xero over synthetic data only. Candidates stay gated (show_ai_candidates=False).
    inputs = ReviewInputs(
        line_source=lambda: [], provider=None, reader=reader,
        sales_line_source=lambda: xero_sales_lines(reader, period["start"], period["end"]),
    )
    # M2: pure review — no persisted artefacts on a plain upload.
    result = review(cfg, period, inputs, persist_artifacts=False)
    if result.status != "completed" or result.compile_output is None:
        # A reconciliation halt on an untrusted upload is a client-input error, never a 500.
        raise HTTPException(
            status_code=422,
            detail="Review could not complete over this export (reconciliation halted).",
        )

    # t-dossier-xero: same hermetic dossier pass as the F5 branch (symmetric wiring —
    # any sales detect finding is an E-check whose slots are engine-seeded). The
    # committed clean sales fixture yields no findings, so this is exercised at the
    # serializer level in tests; a finding-bearing sales fixture is a filed follow-up.
    upload_dossiers = generate_upload_dossiers(result)
    queue = serialize_xero_queue(
        result.compile_output["detect"]["issues"],
        decision_entries=load_decision_entries(cfg.client_id),
        dossiers=upload_dossiers.dossiers,
    )
    coverage_status = [status.as_dict() for status in reader.coverage_status()]
    if upload_dossiers.capped:
        log.warning("dossier cap exceeded on xero_sales_upload — generation skipped")
        coverage_status.append(_dossier_cap_coverage_row())
    return {
        "source_kind": "xero_sales_upload",
        "validation_status": VALIDATION_STATUS,
        "disclaimer": upload_disclaimer("xero_sales_upload"),
        "coverage_status": coverage_status,
        "queue": queue,
        "config_scope": "xero_sales_demo",
        "out_of_scope": reader.out_of_scope_summary(),
    }


@app.post("/sign/upload")
async def post_sign_upload(
    file: UploadFile = File(...),
    ledger: Optional[UploadFile] = File(None),
    reviewer_name: str = Form(...),
    firm_name: str = Form(""),
    review_id: Optional[str] = Form(None),
) -> dict:
    """Sign an uploaded Xero F5 review — the ONE persist event on the upload path (B4).

    Takes the SAME multipart workbook (+ optional 820 ledger) as POST /review/upload,
    PLUS the reviewer's identity. The reviewer is stamped into the xero_demo config
    BEFORE ``review()`` runs, so review()'s own Phase-5 render — the FULL build_report
    argument set, including scheme-status / partial-exemption / exempt sections —
    produces the signed-identity working paper and seals the bundle. No second renderer
    exists to drift (the ui/sign.py reduced-arg path is deliberately NOT reused here).

    THE SYSTEM NEVER SIGNS: the rendered paper carries the reviewer's captured identity
    above an EMPTY ruled signature line — a human signs the paper, never AgentAssist.
    READ-NEVER-WRITE-ON-SOURCE: the only writes are AgentAssist's own PDF + sealed
    bundle (both under gitignored roots); nothing touches Xero/SAP/client data.

    Xero F5 exports only this slice — any other format is a 422 (extract / xero_sales
    sign-off is a follow-up). Halted reconciliation → 422 (client-input signal). The
    response is SIGN_UPLOAD_KEYS; paths are returned as strings (the /sign convention —
    no file bytes served). validation_status stays "unvalidated" (T2.11 gates the AI
    layer; the deterministic paper is human-signed regardless — see the #43 guard).
    """
    reviewer = (reviewer_name or "").strip()
    if not reviewer:
        raise HTTPException(status_code=422, detail="reviewer_name must not be empty.")
    firm = (firm_name or "").strip()

    primary_name = file.filename or ""
    if Path(primary_name).suffix.lower() != ".xlsx":
        raise HTTPException(
            status_code=422,
            detail="Upload the .xlsx Xero F5 export workbook as the 'file' part.",
        )
    body = await file.read()
    if not body:
        raise HTTPException(status_code=422, detail="Empty upload.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="aa-sign-upload-"))
    try:
        dest = tmp_dir / "upload.xlsx"
        dest.write_bytes(body)

        ledger_dest: Optional[Path] = None
        if ledger is not None and (ledger.filename or "").strip():
            if Path(ledger.filename).suffix.lower() != ".xlsx":
                raise HTTPException(
                    status_code=422,
                    detail="The optional ledger must be a .xlsx account-transactions export.",
                )
            ledger_body = await ledger.read()
            if ledger_body:
                ledger_dest = tmp_dir / "ledger.xlsx"
                ledger_dest.write_bytes(ledger_body)

        # --- PARSE BOUNDARY (mirrors post_review_upload) -------------------------------
        # t-demo-prep-xero (D-2026-07-23-demo-prep-xero): sign-off now FORMAT-ROUTES,
        # mirroring post_review_upload — F5 keeps precedence, then the sales-invoice
        # workbook (B4's filed extract/sales-sign follow-up, sales half). Anything
        # else stays a 422; both detectors self-guard False on garbage uploads, so
        # the existing rejects-non-Xero pin holds unamended.
        gst_ledger: Optional[dict] = None
        source_kind = None
        try:
            if is_xero_f5_workbook(dest):
                source_kind = "xero_f5_signed"
                reader = XeroF5ChainReader(dest)
                xero_period = parse_review_period(dest)
                if ledger_dest is not None:
                    gst_ledger = build_gst_ledger_input(ledger_dest, dest, xero_period)
            elif is_xero_sales_invoice_workbook(dest):
                source_kind = "xero_sales_signed"
                reader = _build_xero_sales_reader(dest)
                # A sales export carries no "for the period ..." line — derive from
                # the documents' own DocDate range (same as the sales review branch).
                xero_period = _derive_extract_period(reader)
            else:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Sign-off supports Xero IRAS-F5 and Xero sales-invoice exports "
                        "only in this slice. Upload the 'Transactions by box number' F5 "
                        "workbook or the sales-invoice export."
                    ),
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=422, detail=f"Could not read export: {exc}"
            ) from exc

        # --- ENGINE EXECUTION (below the parse boundary) -------------------------------
        try:
            # Lazy imports keep api/ anthropic-free AT MODULE IMPORT (Inv-1) — same
            # posture as the upload branches.
            from config.loader import load_client_config
            from engine.review import ReviewInputs, review

            # Reviewer identity stamped BEFORE the run: review()'s own render carries it
            # into the signature block. NEVER reads shared_artifacts() (that is the
            # frozen SBODEMOSG demo) — this signs the uploaded review, nothing else.
            config_id = "xero_demo" if source_kind == "xero_f5_signed" else "xero_sales_demo"
            cfg = _dc_replace(
                load_client_config(config_id, check_connectivity=False),
                reviewer_name=reviewer,
                firm_name=firm,
            )

            # T-E(2)/D-45: the optional review session, validated by the SAME guard the
            # review upload uses (422 malformed, 404 unknown) BEFORE any path is built.
            # Absent -> None -> this sign is byte-identical to pre-D-45 behaviour: the
            # re-run cannot see uploaded documents, and the paper says so honestly.
            rid = _validated_upload_review_id(review_id)

            def _mk_inputs(adjudications: Optional[dict] = None) -> ReviewInputs:
                """Fresh reader + inputs per review() run.

                t-decision-render: the decision pre-pass below may run the chain once
                BEFORE the persist run; a fresh reader per run never gambles on reader
                statefulness across two run_chain invocations.
                """
                if source_kind == "xero_f5_signed":
                    # D-45: thread the session's documents into the SIGN re-run so the
                    # sealed paper carries what the screen showed. The join lands on the
                    # reader BEFORE review() runs -> run_chain embeds the same COMPUTED
                    # coverage rows the review response emitted (one value, two surfaces).
                    sign_reader = XeroF5ChainReader(dest)
                    doc_ls, doc_prov, doc_join = _xero_document_context(
                        sign_reader, xero_period, rid
                    )
                    if doc_join is not None:
                        sign_reader.document_join = doc_join
                    return ReviewInputs(
                        line_source=doc_ls or (lambda: []), provider=doc_prov,
                        reader=sign_reader, gst_ledger=gst_ledger,
                        adjudications=adjudications,
                    )
                # Sales sign runs the SAME inputs as the sales review branch — including
                # sales_line_source, so the exempt pass runs and its artefact seals into
                # the bundle (steps/exempt-supply-candidates.json). Over a fixture with
                # no ES33/ESN33 line the pass short-circuits ok/0-candidates with NO
                # model call — the signed paper stays hermetic by default.
                from feeders.xero_sales_lines import xero_sales_lines

                sales_reader = _build_xero_sales_reader(dest)
                return ReviewInputs(
                    line_source=lambda: [], provider=None, reader=sales_reader,
                    sales_line_source=lambda: xero_sales_lines(
                        sales_reader, xero_period["start"], xero_period["end"]
                    ),
                    adjudications=adjudications,
                )

            # t-decision-render (Branch B): the signed paper renders stored reviewer
            # adjudications. The per-finding join needs the run's findings, which are
            # born inside review() — so a NON-EMPTY store costs one extra PURE chain
            # run (persist_artifacts=False; deterministic, T9-pinned identical) to
            # discover them, and the view is built HERE in api/ and handed through the
            # bounded ReviewInputs pass-through. An EMPTY store keeps the exact
            # single-run flow (and a silent paper) as before.
            adjudication_view = None
            decision_entries = load_decision_entries(cfg.client_id)
            if decision_entries:
                pre = review(cfg, xero_period, _mk_inputs(), persist_artifacts=False)
                if pre.status == "completed" and pre.compile_output is not None:
                    # Slice B: the paper must show a decision on ANY family, not just the
                    # detect rows. The ledger-recon and document rows now carry fingerprints,
                    # so they go down build_adjudication_view's EXISTING stored_rows path —
                    # which uses a row's fingerprint as-is and skips un-fingerprinted rows.
                    # Without this a reviewer could adjudicate a document finding, see it
                    # demoted on screen, and find no trace of it on the signed paper.
                    # The document rows' fingerprints key on the BOOKS counterparty, so the
                    # join here must be the same one the review used — otherwise the sign
                    # would recompute a different key and silently show no history.
                    doc_join_items: list = []
                    if source_kind == "xero_f5_signed":
                        _ls, _prov, _join = _xero_document_context(
                            XeroF5ChainReader(dest), xero_period, rid
                        )
                        doc_join_items = list(_ls() if _ls else [])
                    stored_rows = serialize_ledger_recon_queue(
                        pre.compile_output, decision_entries=decision_entries
                    ) + _serialize_document_candidates(
                        pre.document_candidates,
                        {str(it["doc_num"]): it for it in doc_join_items},
                        decision_entries=decision_entries,
                    )
                    adjudication_view = build_adjudication_view([{
                        "client_id": cfg.client_id,
                        "issues": pre.compile_output["detect"]["issues"],
                        "stored_rows": stored_rows,
                        "entries": decision_entries,
                    }])

            # persist_artifacts default True — signing IS the persist event.
            result = review(cfg, xero_period, _mk_inputs(adjudication_view))
            if result.status != "completed" or result.compile_output is None:
                raise HTTPException(
                    status_code=422,
                    detail="Review could not complete over this export (reconciliation halted).",
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("engine-internal failure on POST /sign/upload")
            raise HTTPException(
                status_code=500,
                detail=(
                    "Internal error while signing this export — an application error, "
                    "not a problem with your uploaded file."
                ),
            ) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "source_kind": source_kind,
        "reviewer_name": reviewer,
        "firm_name": firm,
        "working_paper_path": str(result.report_pdf_path),
        "bundle_dir": str(result.bundle_dir),
        "validation_status": VALIDATION_STATUS,
        "disclaimer": upload_disclaimer(
            "xero_f5_upload" if source_kind == "xero_f5_signed" else "xero_sales_upload"
        ),
    }


@app.get("/audit")
def get_audit() -> dict:
    """The hash-chained justification ledger as display rows (read-only audit trail)."""
    return {"entries": build_audit_payload(shared_artifacts()), "disclaimer": DISCLAIMER}


@app.post("/sign")
def post_sign(req: SignRequest, out_dir: Optional[str] = None) -> dict:
    """Reproduce ui.sign.sign_working_paper over the frozen ReviewResult.

    Renders the signed working-paper PDF (reviewer name carried onto cover + signature)
    and returns the working-paper summary. BOX-ISOLATION: the F5 boxes in the response are
    read from the frozen compile_output, which the render never recomputes or mutates.
    """
    if not req.reviewer_name or not req.reviewer_name.strip():
        raise HTTPException(status_code=422, detail="Sign requires a non-empty reviewer name.")

    artifacts = shared_artifacts()
    destination = Path(out_dir) if out_dir else DEFAULT_OUTPUT_DIR
    try:
        pdf_path = sign_working_paper(
            artifacts.review_result,
            reviewer_name=req.reviewer_name.strip(),
            firm_name=req.firm_name.strip(),
            out_dir=destination,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "reviewer_name": req.reviewer_name.strip(),
        "firm_name": req.firm_name.strip(),
        "working_paper_path": str(pdf_path),
        "f5_summary": f5_summary(artifacts),  # box-isolated; unchanged by the render
        "validation_status": VALIDATION_STATUS,
        "disclaimer": DISCLAIMER,
    }


@app.post("/command")
def post_command(req: CommandRequest) -> dict:
    """T6.2 — the one place the whole thing runs end-to-end (Lane A + B + C1 join).

    Classify the utterance with the env-selected backend (scripted default, no tokens;
    ``AGENT_UI_CLASSIFIER=live`` → Haiku, tokens, NO SAP), then route by result kind:

      * OutOfScope          → polite message + the four intent buttons (NO tool runs).
      * NeedsClarification  → the structured ask (never a guessed client/period).
      * Classified          → merge the SURFACE client_id/period over the params (identity
                              from context, not the model), then ``execute_intent`` over the
                              SHARED frozen artifacts → the ExecutionResult as JSON.

    classify-never-obey is structural end-to-end: a hostile/off-menu utterance is contained
    to ``out_of_scope`` by the ⊆-menu boundary — no tool ever runs for it.
    """
    try:
        backend = make_classifier_backend(os.environ, curated=scripted_script())
    except ClassifierConfigError as exc:
        # Loud misconfig (e.g. live mode without ANTHROPIC_API_KEY) — never a silent fallback.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = IntentClassifier(backend).classify(req.utterance)
    base = {"classifier_mode": _classifier_mode(), "disclaimer": DISCLAIMER}

    if isinstance(result, OutOfScope):
        return {
            **base,
            "kind": "out_of_scope",
            "message": (
                "I can help with reviews, proposals, or prior decisions. "
                "Try one of the buttons."
            ),
            "buttons": COMMAND_BUTTONS,
        }

    if isinstance(result, NeedsClarification):
        return {
            **base,
            "kind": "needs_clarification",
            "intent": result.intent,
            "missing": list(result.missing_params),
            "message": result.message,
        }

    assert isinstance(result, Classified)  # the only remaining ClassificationResult
    # Identity slots come from the SURFACE context, never the model's guess.
    params = dict(result.candidate_params)
    if req.client_id.strip():
        params["client_id"] = req.client_id.strip()
    if req.period.strip():
        params["period"] = req.period.strip()

    execution = execute_intent(
        result.intent,
        params,
        artifacts=shared_frozen_artifacts(),
        engine=_shared_frozen_engine(),
        # View-only; the engine validates it against the real domain (off-domain →
        # structured filter_rejection in the body, never a 4xx; never touches identity).
        filters=req.filters,
    )
    return {
        **base,
        "kind": "result",
        "intent": result.intent,
        "execution": execution.to_dict(),
    }
