"""
orchestrator/chain.py — Deterministic six-step GST audit chain.

Drives the complete audit pipeline for a single client and period by
executing five tool steps in a fixed sequence, each immediately followed
by a reconciliation gate that halts the chain on irreconcilable data:

    fetch  →  gate_1  →  calculate  →  gate_2  →  classify  →  gate_3
    →  detect  →  gate_4  →  compile  →  gate_5

Every gate outcome (PASS, WARN_PASS, or FAIL) is recorded in the
`_records` accumulator regardless of whether the chain continues or halts,
so callers always receive a complete gate_results dict — even when
a GateFailure is caught and re-raised.

JSON persistence of step outputs is NOT handled here; it is the
responsibility of audit_bundle.seal.seal_bundle, called by run_agent.py
after this function returns.

Public API:
    run_chain(client_config, period) -> tuple[dict, dict]

Raises:
    GateFailure: Propagated from any of the five gate functions when
        reconciliation fails.  Callers should catch this at the top level.

Dependencies:
    sap_b1_server         Custom MCP server (mcp-servers/custom/).
    config.loader         ClientConfig dataclass.
    orchestrator.gates    Five gate functions (gate_1 … gate_5).
    orchestrator.steps    Five step functions (fetch, calculate, classify,
                          detect, compile).
    orchestrator.schemas  Period TypedDict.
    audit_bundle.gate_record  build_gate_results() — deferred import to
                              avoid potential circular import cycles.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add mcp-servers/custom/ so sap_b1_server is importable as a top-level module,
# and the repo root so config.loader and orchestrator.* resolve correctly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_CUSTOM = _REPO_ROOT / "mcp-servers" / "custom"
if str(_MCP_CUSTOM) not in sys.path:
    sys.path.insert(0, str(_MCP_CUSTOM))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import sap_b1_server  # noqa: E402

from config.loader import ClientConfig  # noqa: E402

from .exceptions import GateFailure  # noqa: E402
from .check_declared_f5 import run_declared_f5_checks  # noqa: E402
from .gates import (  # noqa: E402
    gate_1_record_count,
    gate_2_box_reconciliation,
    gate_3_inventory_consistency,
    gate_4_detect_consistency,
    gate_5_cross_tool_consistency,
)
from .schemas import Period  # noqa: E402
from .steps import (  # noqa: E402
    calculate,
    classify,
    compile,  # noqa: A004 — shadows builtin; this file does not use builtin compile
    detect,
    fetch,
)

log = logging.getLogger(__name__)


def run_chain(
    client_config: ClientConfig,
    period: Period,
    declared_f5: dict | None = None,
) -> tuple[dict, dict]:
    """Run the full six-step deterministic chain for a client and period.

    Executes fetch → calculate → classify → detect → compile in order,
    running one reconciliation gate after each step.  Gate outcomes are
    accumulated into `_records` and returned as gate_results whether the
    chain completes or halts on a GateFailure.

    When declared_f5 is supplied (a validated dict from check_declared_f5.
    load_declared_f5), Check A (declared internal consistency) and Check B
    (declared-vs-computed divergence) are run after compile and their findings
    are injected into the returned CompileOutput as "declared_f5_findings".
    A non-empty findings list is informational — it never halts the chain.

    Args:
        client_config: Validated ClientConfig from config.loader.  Provides
                       SAP credentials and behavioural settings.
        period:        Dict with "start" and "end" keys as ISO-8601 date
                       strings (e.g. {"start": "2024-07-01", "end": "2024-09-30"}).
        declared_f5:   Optional validated declared-F5 dict from
                       check_declared_f5.load_declared_f5().  When None,
                       declared_f5_findings in the returned CompileOutput is [].

    Returns:
        tuple[dict, dict]: A two-element tuple:
            - CompileOutput: The full aggregated dict from the compile step,
              containing "period", "fetch_manifest", "calculate", "classify",
              "detect", "surfaced_warnings", "declared_f5_findings", and
              chain metadata.
            - gate_results: Shaped by audit_bundle.gate_record.build_gate_results —
              {"all_passed": bool, "gates": [{"gate", "name", "after_step",
              "status", "passed", "checked", "message"?}, ...]}.

    Raises:
        GateFailure: When any gate detects irreconcilable data.  The exception
            carries a .checked attribute with the values the gate inspected.
            The failing gate is recorded in _records before the exception
            propagates, so the partial gate_results are available on exc.

    Example:
        compile_output, gate_results = run_chain(cfg, {"start": "2024-07-01",
                                                        "end": "2024-09-30"})
    """
    # Deferred to avoid a circular import: audit_bundle imports from config and
    # orchestrator; importing it at module level here would form a cycle.
    from audit_bundle.gate_record import build_gate_results

    # --- SAP session setup ---

    # Configure the module-global SAP B1 session used by all step functions.
    # Every step that calls sap_b1_server tools reads from this single session,
    # so this must run before any step is invoked.
    sap_b1_server.configure_client(
        client_config.service_layer_url,
        client_config.company_db,
        client_config.username,
        client_config.password,
        client_config.ssl_verify,
        client_config.custom_vat_groups,
    )

    # Mutable accumulator closed over by _rec; collects one entry per gate
    # in execution order so gate_results preserves the chain's gate sequence.
    _records: list[dict] = []

    def _rec(gate: int, name: str, after_step: str, status: str,
             passed: bool, checked: dict, message: str | None = None) -> None:
        """Append a single gate outcome entry to the _records accumulator.

        Args:
            gate:       Gate number (1–5), corresponds to its position in the chain.
            name:       Human-readable gate identifier (e.g. "record-count").
            after_step: Name of the step this gate follows (e.g. "fetch").
            status:     Outcome string — "PASS", "WARN_PASS", or "FAIL".
            passed:     True when the gate allows the chain to continue.
            checked:    Dict of the numeric/structural values the gate inspected.
            message:    Optional human-readable explanation, included only when
                        present to keep passing gate entries compact.
        """
        entry: dict = {
            "gate": gate, "name": name, "after_step": after_step,
            "status": status, "passed": passed, "checked": checked,
        }
        # Only attach message key when non-None to keep PASS entries lean.
        if message is not None:
            entry["message"] = message
        _records.append(entry)

    # --- Step 1: fetch + gate 1 ---

    manifest = fetch(client_config, period)
    try:
        checked = gate_1_record_count(manifest)
        # SAP $inlinecount is an optional OData hint; when the Service Layer
        # omits it we cannot verify full pagination, so we warn rather than fail.
        if checked["sap_inline_count"] is None:
            _rec(1, "record-count", "fetch", "WARN_PASS", True, checked,
                 "SAP $inlinecount unavailable — cannot verify pagination completeness")
        else:
            _rec(1, "record-count", "fetch", "PASS", True, checked)
    except GateFailure as exc:
        # Record the failure before re-raising so the partial gate_results
        # are complete even when the caller catches and surfaces this exception.
        _rec(1, "record-count", "fetch", "FAIL", False, exc.checked, str(exc))
        raise

    # --- Step 2: calculate + gate 2 ---

    calc = calculate(client_config, period)
    try:
        checked = gate_2_box_reconciliation(calc)
        _rec(2, "box-reconciliation", "calculate", "PASS", True, checked)
    except GateFailure as exc:
        _rec(2, "box-reconciliation", "calculate", "FAIL", False, exc.checked, str(exc))
        raise

    # --- Step 3: classify + gate 3 ---

    cls = classify(client_config, period)
    try:
        checked = gate_3_inventory_consistency(cls)
        _rec(3, "inventory-consistency", "classify", "PASS", True, checked)
    except GateFailure as exc:
        _rec(3, "inventory-consistency", "classify", "FAIL", False, exc.checked, str(exc))
        raise

    # --- Step 4: detect + gate 4 ---

    det = detect(client_config, period)
    try:
        checked = gate_4_detect_consistency(det, manifest)
        _rec(4, "detect-consistency", "detect", "PASS", True, checked)
    except GateFailure as exc:
        _rec(4, "detect-consistency", "detect", "FAIL", False, exc.checked, str(exc))
        raise

    # --- Step 5: compile + gate 5 ---

    compiled = compile(manifest, calc, cls, det)
    try:
        checked = gate_5_cross_tool_consistency(calc, cls, det)
        _rec(5, "cross-tool-consistency", "compile", "PASS", True, checked)
    except GateFailure as exc:
        _rec(5, "cross-tool-consistency", "compile", "FAIL", False, exc.checked, str(exc))
        raise

    # Shallow-copy compiled into a plain dict so the return type is consistent
    # regardless of whatever mapping subtype compile() returns internally.
    result = dict(compiled)

    # T2.9: Run declared-vs-computed checks when a declared_f5 input was supplied.
    # Findings are informational — a non-empty list never halts the chain or
    # prevents sealing.  The calculate step output (result["calculate"]["boxes"])
    # is never mutated; run_declared_f5_checks is strictly read-only over it.
    if declared_f5 is not None:
        result["declared_f5_findings"] = run_declared_f5_checks(
            declared_f5, result["calculate"]["boxes"]
        )

    return result, build_gate_results(_records)
