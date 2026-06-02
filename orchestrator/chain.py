from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_CUSTOM = _REPO_ROOT / "mcp-servers" / "custom"
if str(_MCP_CUSTOM) not in sys.path:
    sys.path.insert(0, str(_MCP_CUSTOM))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import sap_b1_server  # noqa: E402

from config.loader import ClientConfig  # noqa: E402

from .exceptions import GateFailure  # noqa: E402
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
) -> tuple[dict, dict]:
    """Run the full six-step deterministic chain for a client and period.

    Returns (CompileOutput, gate_results) on success.
      - CompileOutput: the full aggregated dict from the compile step.
      - gate_results: shaped by audit_bundle.gate_record.build_gate_results —
        {all_passed, gates:[{gate, name, after_step, status, passed, checked, message?}]}.

    Raises GateFailure on any reconciliation failure.  The exception carries a
    .checked attribute with the values the failing gate inspected, so callers can
    build a partial diagnostic record even when the chain halts.

    JSON persistence (previously written to exploration-notes/t1.6-tool-outputs/) is
    now the responsibility of audit_bundle.seal.seal_bundle, which the caller
    (run_agent.py) invokes after this function returns.
    """
    from audit_bundle.gate_record import build_gate_results

    sap_b1_server.configure_client(
        client_config.service_layer_url,
        client_config.company_db,
        client_config.username,
        client_config.password,
        client_config.ssl_verify,
        client_config.custom_vat_groups,
    )

    _records: list[dict] = []

    def _rec(gate: int, name: str, after_step: str, status: str,
             passed: bool, checked: dict, message: str | None = None) -> None:
        entry: dict = {
            "gate": gate, "name": name, "after_step": after_step,
            "status": status, "passed": passed, "checked": checked,
        }
        if message is not None:
            entry["message"] = message
        _records.append(entry)

    manifest = fetch(client_config, period)
    try:
        checked = gate_1_record_count(manifest)
        if checked["sap_inline_count"] is None:
            _rec(1, "record-count", "fetch", "WARN_PASS", True, checked,
                 "SAP $inlinecount unavailable — cannot verify pagination completeness")
        else:
            _rec(1, "record-count", "fetch", "PASS", True, checked)
    except GateFailure as exc:
        _rec(1, "record-count", "fetch", "FAIL", False, exc.checked, str(exc))
        raise

    calc = calculate(client_config, period)
    try:
        checked = gate_2_box_reconciliation(calc)
        _rec(2, "box-reconciliation", "calculate", "PASS", True, checked)
    except GateFailure as exc:
        _rec(2, "box-reconciliation", "calculate", "FAIL", False, exc.checked, str(exc))
        raise

    cls = classify(client_config, period)
    try:
        checked = gate_3_inventory_consistency(cls)
        _rec(3, "inventory-consistency", "classify", "PASS", True, checked)
    except GateFailure as exc:
        _rec(3, "inventory-consistency", "classify", "FAIL", False, exc.checked, str(exc))
        raise

    det = detect(client_config, period)
    try:
        checked = gate_4_detect_consistency(det, manifest)
        _rec(4, "detect-consistency", "detect", "PASS", True, checked)
    except GateFailure as exc:
        _rec(4, "detect-consistency", "detect", "FAIL", False, exc.checked, str(exc))
        raise

    compiled = compile(manifest, calc, cls, det)
    try:
        checked = gate_5_cross_tool_consistency(calc, cls, det)
        _rec(5, "cross-tool-consistency", "compile", "PASS", True, checked)
    except GateFailure as exc:
        _rec(5, "cross-tool-consistency", "compile", "FAIL", False, exc.checked, str(exc))
        raise

    return dict(compiled), build_gate_results(_records)
