"""
report/contract.py — report-package entry contract.

Defines the single authorised ingestion point for chain-run output into the
report package.  By funnelling all file I/O through one function, the rest of
report/ stays insulated from path handling, encoding decisions, and the
structural validation that guards against malformed chain output.

load_compile_output: the only authorised way to ingest a chain-run JSON into the
report package. No SAP, no network — pure file I/O + structural validation.

Re-exports of orchestrator TypedDicts are provided here so the rest of report/
imports from one place and stays insulated from schema moves in orchestrator/.

Design rationale:
    The report package deliberately has no dependency on the orchestrator's
    runtime (no chain imports, no SAP client).  This file is the seam: it
    imports schemas for type-checking purposes only and exposes a single
    validated-load function.  Any future schema migration in orchestrator/
    requires changes only here, not across every report/ module.

Exports:
    load_compile_output  — load and shallow-validate a chain-run JSON file
    All TypedDicts re-exported from orchestrator.schemas (see import block)
"""
from __future__ import annotations

# from __future__ import annotations makes all annotations strings at parse time,
# enabling lowercase generic hints (dict[str, str]) and forward references on
# Python < 3.9 without a runtime cost.

import json
from pathlib import Path

# ── Re-exports for report-internal use ───────────────────────────────────────
# Import everything the report package will need. Other report/ modules should
# import schemas from here, not directly from orchestrator.schemas.
# noqa: F401 suppresses "imported but unused" linter warnings — these are
# intentional re-exports, not accidental dead imports.
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

# The five top-level keys that every chain-run JSON must contain.
# These correspond to the outputs of the five mandatory chain steps:
#   period        — date range the run covers
#   fetch_manifest — document counts and doc_num sets from the fetch step
#   calculate     — F5 box totals and FX document list
#   classify      — per-line E1–E4 issues and VatGroup inventory
#   detect        — enriched GST compliance issues with severity and recommendations
# Inner field shapes are intentionally not validated here — the chain's gate
# layer owns that invariant.  This check only guards against a completely
# truncated or wrong-file load.
_REQUIRED_KEYS: tuple[str, ...] = (
    "period",
    "fetch_manifest",
    "calculate",
    "classify",
    "detect",
)


def load_compile_output(path: str | Path) -> CompileOutput:
    """Load a chain-run JSON file and return it as a CompileOutput-shaped dict.

    The file must have been produced by orchestrator.chain.run_chain.
    Validates that the five top-level structural keys are present. Does not
    validate inner field shapes — the chain's gate layer owns that invariant.

    Args:
        path: File-system path (str or Path) to the chain-run JSON file.
            Accepts either type so callers need not convert before passing.

    Returns:
        CompileOutput: The parsed JSON as a CompileOutput-shaped dict.
            At runtime this is a plain dict; the return type annotation is a
            TypedDict cast for the benefit of static type checkers downstream.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If any required top-level key is missing, with a message
            listing all missing keys and the file path.
        json.JSONDecodeError: If the file is not valid JSON.

    Note:
        JSON serialisation converts Python sets (doc_nums, calc_doc_nums,
        detect_doc_nums) to sorted lists. Callers that need set semantics must
        convert explicitly: set(data["fetch_manifest"]["doc_nums"]).

    Example:
        data = load_compile_output("runs/2024Q1_compile.json")
        boxes = data["calculate"]["boxes"]
    """
    # Normalise to Path regardless of whether a str or Path was passed,
    # so the rest of the function can use Path methods uniformly.
    path = Path(path)
    # Explicit UTF-8 encoding guards against platform-default differences on
    # Windows, where the default code page may not decode JSON produced on Linux.
    with open(path, encoding="utf-8") as fh:
        # Annotate as dict to aid static analysis; json.load returns Any at runtime.
        data: dict = json.load(fh)

    # List comprehension preserves _REQUIRED_KEYS order so the error message
    # lists missing keys in a stable, readable sequence rather than set order.
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(
            f"load_compile_output: chain-run file is missing required top-level "
            f"key(s): {missing}. Path: {path}"
        )

    # type: ignore silences the type checker here — data is a plain dict at
    # runtime, but callers receive it typed as CompileOutput for downstream
    # attribute access without redundant casts.
    return data  # type: ignore[return-value]
