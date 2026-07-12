"""T2.24 chain seam — the optional gst_ledger side-input attaches as FINDINGS, never gates.

Three properties, all over the frozen SBODEMOSG replay (SAP unreachable, offline):

  1. no-ledger path adds ZERO keys — gst_ledger=None leaves neither "ledger_recon_findings"
     nor "ledger_recon_status" in the result, so the offline-replay oracle stays
     byte-identical (no re-freeze).
  2. offline-replay byte-identity holds on the no-ledger path AFTER the chain.py change.
  3. BOX-ISOLATION — supplying gst_ledger does NOT move any F5 box value (a test twin of
     the runtime snapshot assertion in chain.py).

Uses the shared replay harness (tests/replay_shim.py) exactly as test_t2_12a_offline_replay.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from orchestrator.chain import run_chain

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

from audit_bundle.canonical import canonical_json  # noqa: E402
from config.loader import load_client_config  # noqa: E402

_shim_spec = importlib.util.spec_from_file_location(
    "t224_replay_shim", Path(__file__).resolve().parent / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sbodemosg-extract"
ORACLE_PATH = FIXTURE_DIR / "_replay-oracle.compiled.json"

# A minimal, well-formed gst_ledger side-input (content irrelevant to box isolation).
_GST_LEDGER = {
    "lines": [
        {"date": "2026-04-10", "source": "Payable Invoice",
         "description": "x", "reference": "BILL-X", "debit": 10.0, "credit": 0.0},
    ],
    "declared_boxes": {"output_tax": 0.0, "input_tax": 0.0},
}


def _period() -> dict:
    return replay_shim.period_from_manifest(FIXTURE_DIR)


@pytest.fixture()
def replay_patches(monkeypatch):
    return replay_shim.install_replay_patches(monkeypatch, FIXTURE_DIR)


def test_no_ledger_path_adds_no_keys(replay_patches):
    """gst_ledger defaulted (None) -> neither ledger_recon key appears in the result."""
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    reader = replay_shim.build_frozen_reader(FIXTURE_DIR)
    result, _ = run_chain(cfg, _period(), reader=reader)
    assert "ledger_recon_findings" not in result
    assert "ledger_recon_status" not in result


def test_offline_replay_byte_identical_to_oracle(replay_patches):
    """The chain.py gst_ledger change must not alter the no-ledger path bytes (no re-freeze)."""
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    period = _period()
    reader = replay_shim.build_frozen_reader(FIXTURE_DIR)
    compile_output, gate_results = run_chain(cfg, period, reader=reader)
    replayed = canonical_json({
        "period": period,
        "compile_output": compile_output,
        "gate_results": gate_results,
    })
    assert replayed == ORACLE_PATH.read_bytes()
    assert replay_patches == {"login": 0, "request": 0}


def test_box_isolation_snapshot(replay_patches):
    """Supplying gst_ledger leaves result['calculate']['boxes'] byte-identical to baseline."""
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    period = _period()

    baseline, _ = run_chain(cfg, period, reader=replay_shim.build_frozen_reader(FIXTURE_DIR))
    boxes_baseline = canonical_json(baseline["calculate"]["boxes"])

    with_ledger, _ = run_chain(
        cfg, period,
        reader=replay_shim.build_frozen_reader(FIXTURE_DIR),
        gst_ledger=_GST_LEDGER,
    )
    assert canonical_json(with_ledger["calculate"]["boxes"]) == boxes_baseline
    # The ledger side-input DID attach its findings surface (proves the seam ran, not skipped).
    assert "ledger_recon_findings" in with_ledger
