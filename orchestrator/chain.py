from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_CUSTOM = _REPO_ROOT / "mcp-servers" / "custom"
if str(_MCP_CUSTOM) not in sys.path:
    sys.path.insert(0, str(_MCP_CUSTOM))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import sap_b1_server  # noqa: E402

from config.loader import ClientConfig  # noqa: E402

from .gates import (  # noqa: E402
    gate_1_record_count,
    gate_2_box_reconciliation,
    gate_3_inventory_consistency,
    gate_4_detect_consistency,
    gate_5_cross_tool_consistency,
)
from .schemas import Period, ReportInput  # noqa: E402
from .steps import (  # noqa: E402
    calculate,
    classify,
    compile,  # noqa: A004 — shadows builtin; this file does not use builtin compile
    detect,
    fetch,
    report_input,
)

log = logging.getLogger(__name__)

# Output directory is provisional — will be superseded by T1.5 audit trail integration.
_OUTPUT_DIR = _REPO_ROOT / "exploration-notes" / "t1.6-tool-outputs"


def _json_default(obj: object) -> object:
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _write_output(data: dict, path: Path) -> None:
    """Write compiled chain output to JSON. Extracted for testability."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, default=_json_default, indent=2, ensure_ascii=False)


def run_chain(
    client_config: ClientConfig,
    period: Period,
) -> tuple[ReportInput, Path]:
    """
    Run the full six-step deterministic chain for a client and period.

    Raises GateFailure (from orchestrator.exceptions) on any reconciliation failure.
    Returns (ReportInput, output_path) on success.
    """
    # Reconfigure the SAP client so run_chain is self-contained regardless of
    # module-level init state in sap_b1_server.
    sap_b1_server.configure_client(
        client_config.service_layer_url,
        client_config.company_db,
        client_config.username,
        client_config.password,
        client_config.ssl_verify,
        client_config.custom_vat_groups,
    )

    manifest = fetch(client_config, period)
    gate_1_record_count(manifest)

    calc = calculate(client_config, period)
    gate_2_box_reconciliation(calc)

    cls = classify(client_config, period)
    gate_3_inventory_consistency(cls)

    det = detect(client_config, period)
    gate_4_detect_consistency(det, manifest)

    compiled = compile(manifest, calc, cls, det)
    gate_5_cross_tool_consistency(calc, cls, det)

    report = report_input(compiled)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = _OUTPUT_DIR / f"chain-run-{ts}.json"
    _write_output(dict(compiled), out_path)
    log.info(f"run_chain: output written to {out_path}")

    return report, out_path
