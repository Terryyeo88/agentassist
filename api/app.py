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
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
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
    """

    utterance: str = Field(..., description="Free-text request to classify.")
    client_id: str = Field("", description="Surface context client id (e.g. sbodemosg).")
    period: str = Field("", description="Surface context period (e.g. 2024Q3).")


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
    )
    return {
        **base,
        "kind": "result",
        "intent": result.intent,
        "execution": execution.to_dict(),
    }
