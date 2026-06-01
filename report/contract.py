"""
report/contract.py — report-package entry contract.

load_compile_output: the only authorised way to ingest a chain-run JSON into the
report package. No SAP, no network — pure file I/O + structural validation.

Re-exports of orchestrator TypedDicts are provided here so the rest of report/
imports from one place and stays insulated from schema moves in orchestrator/.
"""
from __future__ import annotations

import json
from pathlib import Path

# ── Re-exports for report-internal use ───────────────────────────────────────
# Import everything the report package will need. Other report/ modules should
# import schemas from here, not directly from orchestrator.schemas.
from orchestrator.schemas import (  # noqa: F401
    Anomaly,
    ClassifyIssue,
    ClassifyOutput,
    CompileOutput,
    CreditNoteApplied,
    DetectIssue,
    DetectOutput,
    E1Candidate,
    E1Reconciliation,
    F5ReturnOutput,
    FetchManifest,
    FxInvoice,
    InvoiceRecord,
    Period,
    ReportInput,
    VatGroupEntry,
)

# ── Structural contract ───────────────────────────────────────────────────────

_REQUIRED_KEYS: tuple[str, ...] = (
    "period",
    "fetch_manifest",
    "calculate",
    "classify",
    "detect",
)


def load_compile_output(path: str | Path) -> CompileOutput:
    """
    Load a chain-run JSON file produced by orchestrator.chain.run_chain and
    return it as a CompileOutput-shaped dict.

    Validates that the five top-level structural keys are present. Does not
    validate inner field shapes — the chain's gate layer owns that invariant.

    Raises:
        FileNotFoundError: if the path does not exist.
        ValueError: if any required top-level key is missing.
        json.JSONDecodeError: if the file is not valid JSON.

    Note: JSON serialisation converts Python sets (doc_nums, calc_doc_nums,
    detect_doc_nums) to sorted lists. Callers that need set semantics must
    convert explicitly: set(data["fetch_manifest"]["doc_nums"]).
    """
    path = Path(path)
    with open(path, encoding="utf-8") as fh:
        data: dict = json.load(fh)

    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(
            f"load_compile_output: chain-run file is missing required top-level "
            f"key(s): {missing}. Path: {path}"
        )

    return data  # type: ignore[return-value]
