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

import logging
import os
import re
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Union

from dataclasses import replace as _dc_replace

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
    build_audit_payload,
    build_review_payload,
    f5_summary,
    serialize_ledger_recon_queue,
    serialize_xero_queue,
    upload_disclaimer,
)
# t-dossier-xero: hermetic case-file dossiers on the upload paths. agent.upload_dossiers
# is stdlib+agent/ only (no anthropic, no SDK) — api/ stays anthropic-free at import.
from agent.upload_dossiers import generate_upload_dossiers
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
# "unvalidated" (Inv-5). XERO_UPLOAD_KEYS documents the top-level shape the frontend TS types
# mirror (as UPLOAD_COVERAGE_KEYS does). The coverage-era flat `findings` row is superseded by
# `queue` (the shared screen consumes QueueItem, not a bespoke 7-key row).
XERO_UPLOAD_KEYS: tuple[str, ...] = (
    "source_kind", "validation_status", "disclaimer", "coverage_status", "queue",
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
    "entry_id", "entry_hash", "chain_length", "validation_status", "disclaimer",
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
        "chain_length": len(load_decision_entries(req.client_id)),
        "validation_status": VALIDATION_STATUS,
        "disclaimer": DISCLAIMER,
    }


@app.post("/review/upload")
async def post_review_upload(
    file: UploadFile = File(...),
    ledger: Optional[UploadFile] = File(None),
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
            if is_xero:
                return _xero_f5_review_response(reader, xero_period, gst_ledger)
            if is_xero_sales:
                return _xero_sales_review_response(reader)
            if _extract_engine_enabled():
                return _extract_review_response(reader)
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

    return {
        "source_kind": "extract_upload",
        "validation_status": VALIDATION_STATUS,
        "disclaimer": upload_disclaimer("extract_upload"),
        "coverage_status": coverage_status,
    }


def _xero_f5_review_response(reader, period: dict, gst_ledger: Optional[dict] = None) -> dict:
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
    inputs = ReviewInputs(
        line_source=lambda: [], provider=None, reader=reader, gst_ledger=gst_ledger
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
    queue = serialize_xero_queue(
        result.compile_output["detect"]["issues"],
        decision_entries=load_decision_entries(cfg.client_id),
        dossiers=upload_dossiers.dossiers,
    ) + serialize_ledger_recon_queue(result.compile_output)
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
        gst_ledger: Optional[dict] = None
        try:
            if not is_xero_f5_workbook(dest):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Sign-off supports Xero IRAS-F5 exports only in this slice. "
                        "Upload the 'Transactions by box number' F5 workbook."
                    ),
                )
            reader = XeroF5ChainReader(dest)
            xero_period = parse_review_period(dest)
            if ledger_dest is not None:
                gst_ledger = build_gst_ledger_input(ledger_dest, dest, xero_period)
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
            cfg = _dc_replace(
                load_client_config("xero_demo", check_connectivity=False),
                reviewer_name=reviewer,
                firm_name=firm,
            )
            inputs = ReviewInputs(
                line_source=lambda: [], provider=None, reader=reader,
                gst_ledger=gst_ledger,
            )
            # persist_artifacts default True — signing IS the persist event.
            result = review(cfg, xero_period, inputs)
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
        "source_kind": "xero_f5_signed",
        "reviewer_name": reviewer,
        "firm_name": firm,
        "working_paper_path": str(result.report_pdf_path),
        "bundle_dir": str(result.bundle_dir),
        "validation_status": VALIDATION_STATUS,
        "disclaimer": upload_disclaimer("xero_f5_upload"),
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
