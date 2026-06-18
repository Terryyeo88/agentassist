"""api/app.py — FastAPI seam serving the FROZEN review surface as JSON (T6.1, Lane C1).

Endpoints (read the frozen SBODEMOSG artifacts via the Mock path — no SAP, no model,
no tokens):

  * GET  /review/{client}/{period}  → client + period + F5 summary + serialised queue.
  * POST /sign                      → reproduces ui.sign.sign_working_paper (carries the
                                      reviewer name); box-isolation preserved.
  * GET  /audit                     → the hash-chained justification ledger rows.

There is deliberately NO /command (classify+execute) endpoint — that is Lane C2,
gated on Lanes A + B. ``orchestrator/`` and ``engine/`` are untouched. This module
imports ``ui``/``agent``/``report`` view-models only; it never imports ``anthropic``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.viewmodel import (
    DEMO_CLIENT_ID,
    DEMO_PERIOD_LABEL,
    DISCLAIMER,
    build_audit_payload,
    build_review_payload,
    f5_summary,
)
from ui.artifacts import VALIDATION_STATUS, load_demo_artifacts
from ui.sign import DEFAULT_OUTPUT_DIR, sign_working_paper

app = FastAPI(
    title="AgentAssist review surface (T6.1 demo seam)",
    description=(
        "Thin serve layer over the FROZEN SBODEMOSG engine output. Demo/illustrative, "
        "validation_status=unvalidated (T2.11 is the binding gate). SAP off, mock engine, "
        "no tokens. No classify/execute endpoint (Lane C2 deferred)."
    ),
    version="0.1.0",
)

# The Vite dev server proxies /api → uvicorn (same-origin in dev), but allow direct
# localhost calls too so `npm run dev` works without the proxy if needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class SignRequest(BaseModel):
    """POST /sign body. ``reviewer_name`` is required (sign refuses an empty reviewer)."""

    reviewer_name: str = Field(..., description="Reviewer of record; carried onto the working paper.")
    firm_name: str = Field("", description="Reviewer's firm (optional).")


@app.get("/health")
def health() -> dict:
    """Liveness probe + the loud demo framing."""
    return {"status": "ok", "validation_status": VALIDATION_STATUS, "disclaimer": DISCLAIMER}


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
    return build_review_payload(load_demo_artifacts())


@app.get("/audit")
def get_audit() -> dict:
    """The hash-chained justification ledger as display rows (read-only audit trail)."""
    return {"entries": build_audit_payload(load_demo_artifacts()), "disclaimer": DISCLAIMER}


@app.post("/sign")
def post_sign(req: SignRequest, out_dir: Optional[str] = None) -> dict:
    """Reproduce ui.sign.sign_working_paper over the frozen ReviewResult.

    Renders the signed working-paper PDF (reviewer name carried onto cover + signature)
    and returns the working-paper summary. BOX-ISOLATION: the F5 boxes in the response are
    read from the frozen compile_output, which the render never recomputes or mutates.
    """
    if not req.reviewer_name or not req.reviewer_name.strip():
        raise HTTPException(status_code=422, detail="Sign requires a non-empty reviewer name.")

    artifacts = load_demo_artifacts()
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
