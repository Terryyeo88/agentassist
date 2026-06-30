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

import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.classifier_factory import (
    CLASSIFIER_ENV_VAR,
    MODE_SCRIPTED,
    ClassifierConfigError,
    make_classifier_backend,
)
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
)
# api/ → feeders/ edge (source-selector Xero branch). ``feeders`` is a pure stdlib leaf
# (openpyxl is lazy on the .xlsx path); it imports NO anthropic/agent/engine/orchestrator,
# so this edge keeps api/ anthropic-free and engine-free (pinned by the import-scan tests).
from feeders.extract_reader import ExtractChainReader
from feeders.xero_f5_reader import (
    XeroF5ChainReader,
    is_xero_f5_workbook,
    parse_review_period,
)
from ui.artifacts import VALIDATION_STATUS, DemoArtifacts, load_demo_artifacts
from ui.sign import DEFAULT_OUTPUT_DIR, sign_working_paper

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

# POST /review/upload Xero-F5 branch (engine path) response contract: the coverage keys PLUS
# findings — a real-Xero-FORMAT review over an uploaded F5 export, candidates NOT verdicts,
# validation_status stays "unvalidated" (Inv-5). XERO_UPLOAD_KEYS documents the top-level shape
# (the source the frontend TS types mirror, as UPLOAD_COVERAGE_KEYS does); FINDING_ROW_KEYS is
# the engine detect-issue finding row that _xero_f5_review_response projects each finding to.
XERO_UPLOAD_KEYS: tuple[str, ...] = (
    "source_kind", "validation_status", "disclaimer", "coverage_status", "findings",
)
FINDING_ROW_KEYS: tuple[str, ...] = (
    "card_name", "description", "doc_date", "doc_num",
    "error_code", "recommendation", "severity",
)


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
    return build_review_payload(shared_artifacts())


@app.post("/review/upload")
async def post_review_upload(request: Request, filename: str = "") -> dict:
    """COVERAGE-ONLY view over an UPLOADED client GST export (source-selector Xero branch).

    The selector hands this route a single ``.xlsx`` export; it constructs an
    ``ExtractChainReader`` over the upload and returns that reader's per-check DATA-COVERAGE
    status (``coverage_status()`` → ``CoverageStatus.as_dict()``). Coverage is a data-presence
    fact — which canonical fields the export carried — NOT a validated review and NOT a
    compliance verdict.

    NEVER runs the engine. There is no ``orchestrator.chain.run_chain`` and no
    ``engine.review.review`` on this path: producing a real review from an uploaded extract
    needs the feeder→engine wiring and is a SEPARATE later task (deferred). The response is
    honestly framed — ``validation_status=unvalidated`` + the demo disclaimer.

    Raw-body upload (no multipart dependency): the file BYTES are the request body and
    ``filename`` (query param) carries the name for the ``.xlsx`` suffix gate. The upload
    lands ONLY on a private system-temp dir (never the repo / committed fixtures) and is
    deleted right after the read, so no client data enters the diff. Any unreadable/garbage
    upload is a client-input error (422), never a 500.
    """
    suffix = Path(filename).suffix.lower()
    if suffix != ".xlsx":
        raise HTTPException(
            status_code=422,
            detail="Upload a single .xlsx GST export workbook (pass ?filename=<name>.xlsx).",
        )
    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="Empty upload.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="aa-extract-upload-"))
    try:
        dest = tmp_dir / f"upload{suffix}"
        dest.write_bytes(body)
        try:
            # FORMAT ROUTING: a real Xero IRAS-F5 export ("Transactions by box number" sheet)
            # goes down the engine path and returns REAL (but unvalidated) findings; any other
            # .xlsx (the synthetic documents/business_partners/listing shape) stays on the
            # UNCHANGED ExtractChainReader coverage-only path — byte-identical to before.
            if is_xero_f5_workbook(dest):
                return _xero_f5_review_response(dest)
            reader = ExtractChainReader(dest)
            coverage_status = [status.as_dict() for status in reader.coverage_status()]
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            # Any parse failure on an UNTRUSTED upload (bad zip, missing sheet, …) is a
            # 422 client-input error — never a 500.
            raise HTTPException(
                status_code=422, detail=f"Could not read export: {exc}"
            ) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "source_kind": "extract_upload",
        "validation_status": VALIDATION_STATUS,
        "disclaimer": DISCLAIMER,
        "coverage_status": coverage_status,
    }


def _xero_f5_review_response(dest: Path) -> dict:
    """Run the real (UNVALIDATED) engine review over an uploaded Xero IRAS-F5 export.

    Threads PR-A's XeroF5ChainReader through engine.review.review(): the deterministic chain
    (run_chain) surfaces the line-level E-check findings (E2/E3/E4 on the demo fixture); the
    surfaces a Xero export lacks (supplier master, document-number listing) degrade honestly in
    coverage_status (NO_GST_REG unavailable, DUP_CLAIM/SEQ_GAP degraded) — never as silent
    absence and never fabricated.

    HONEST STATUS: real-Xero-FORMAT findings over (here) SYNTHETIC data — CANDIDATES, never
    verdicts. validation_status stays "unvalidated" (Inv-5); no AI candidates surface; the
    VatGroup mapping is PROPOSED (DEBT-1); accuracy is NOT validated (T2.11 unmoved).

    DEBT-9 runtime dependency: load_client_config("xero_demo") hard-requires SAP_USERNAME/
    SAP_PASSWORD env vars even though NO SAP call is made on this path (XeroF5ChainReader
    short-circuits every read). Making sap_b1 optional for non-SAP clients is deferred (PR-D).
    """
    reader = XeroF5ChainReader(dest)
    period = parse_review_period(dest)

    # Lazy imports keep api/ anthropic-free AT MODULE IMPORT (Inv-1): engine.review pulls
    # reasoning.reg2627, whose anthropic import is itself lazy — so importing api.app loads
    # neither; they resolve only when this endpoint actually runs.
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review

    cfg = load_client_config("xero_demo", check_connectivity=False)
    # A Xero F5 export has no SI-purchase-line / source-document surface; the surfaced findings
    # come entirely from run_chain via the reader. An empty line_source (Reg26/27 emits a clean
    # no-LLM artefact) and no provider (documents pass skipped) keep this hermetic.
    inputs = ReviewInputs(line_source=lambda: [], provider=None, reader=reader)
    result = review(cfg, period, inputs)
    if result.status != "completed" or result.compile_output is None:
        # A reconciliation halt on an untrusted upload is a client-input error, never a 500.
        raise HTTPException(
            status_code=422,
            detail="Review could not complete over this export (reconciliation halted).",
        )

    # Project each detect issue to exactly the contract finding-row shape so the response stays
    # contract-stable even if the internal detect-issue dict later gains a field.
    findings = [
        {key: issue.get(key) for key in FINDING_ROW_KEYS}
        for issue in result.compile_output["detect"]["issues"]
    ]
    coverage_status = [status.as_dict() for status in reader.coverage_status()]
    return {
        "source_kind": "xero_f5_upload",
        "validation_status": VALIDATION_STATUS,
        "disclaimer": DISCLAIMER,
        "coverage_status": coverage_status,
        "findings": findings,
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
