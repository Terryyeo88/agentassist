"""T2.12a offline replay — same-SAP-state rederivation gate.

Runs the deterministic chain (run_chain) against the frozen SBODEMOSG extract
fixtures with SAP physically unreachable, and asserts the result is BYTE-IDENTICAL
to the frozen same-session oracle (_replay-oracle.compiled.json).

Passing proves two things:
  (a) the freeze is SUFFICIENT — every field run_chain needs is present in the
      frozen fixtures; a missing field would error or diverge here; and
  (b) the chain is reproducible offline — no live SAP required.

This is a TEST HARNESS, not the product adapter. It injects frozen fixtures via
test-only monkeypatches at the fetch primitives; it does NOT build the Excel/CSV
adapter (T2.12) and does NOT validate accuracy (T2.11). orchestrator/ is untouched.

The fixture-injection patch set now lives in tests/replay_shim.py (reused by T5.3h);
this gate's behaviour is UNCHANGED — same patches, same assertions.

Consumed surfaces (recon S0/S1/S2/S3/S5; S4 is reasoning-pass only, not read by
run_chain). See exploration-notes/t2.12a-read-surface-inventory.md.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Importing from orchestrator wires mcp-servers/custom onto sys.path (chain.py does
# the insertion); sap_b1_server is importable as a top-level module afterwards.
from orchestrator.chain import run_chain

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402 — path set above

from audit_bundle.canonical import canonical_json  # noqa: E402
from config.loader import load_client_config  # noqa: E402

# Load the shared replay harness from the sibling module (tests/ is not a package).
_shim_spec = importlib.util.spec_from_file_location(
    "t2_12a_replay_shim", Path(__file__).resolve().parent / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)

# The guard the shim raises — same identity used in the fixture and the test bodies.
NoContactError = replay_shim.NoContactError

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sbodemosg-extract"
ORACLE_PATH = FIXTURE_DIR / "_replay-oracle.compiled.json"
MANIFEST_PATH = FIXTURE_DIR / "capture-manifest.json"


def _period() -> dict:
    """Pin the period from the capture manifest (fallback: chain-run-sample)."""
    return replay_shim.period_from_manifest(FIXTURE_DIR)


def _first_divergence(a, b, path="$"):
    """Return a human-readable first-divergence path between two JSON values.

    Used only on mismatch to point at which key diverged — surfaces a second
    non-deterministic source (if any) rather than dropping it silently.
    """
    if type(a) is not type(b):
        return f"{path}: type {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return f"{path}.{k}: missing in replay"
            if k not in b:
                return f"{path}.{k}: missing in oracle"
            d = _first_divergence(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: list len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_divergence(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    if a != b:
        return f"{path}: {a!r} != {b!r}"
    return None


@pytest.fixture()
def replay_patches(monkeypatch):
    """Install the fixture-injection shims, no-contact guard, and frozen clock.

    Delegates to the shared tests/replay_shim.py patch set (behaviour-preserving:
    identical patches). Returns the call-tracking dict so the test can assert no SAP
    contact occurred.
    """
    return replay_shim.install_replay_patches(monkeypatch, FIXTURE_DIR)


def test_offline_replay_byte_identical_to_oracle(replay_patches):
    """run_chain off frozen fixtures, SAP unreachable, == frozen oracle (bytes)."""
    # Hermetic config: same sbodemosg.yaml the capture used (identical tax-code
    # mappings / gst rate); creds are conftest stubs and never used (network blocked).
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    period = _period()

    compile_output, gate_results = run_chain(cfg, period)

    replayed = canonical_json({
        "period": period,
        "compile_output": compile_output,
        "gate_results": gate_results,
    })
    oracle_bytes = ORACLE_PATH.read_bytes()

    if replayed != oracle_bytes:
        # Surface which key diverged — a residual non-deterministic source, if any.
        diff = _first_divergence(
            json.loads(replayed), json.loads(oracle_bytes)
        )
        pytest.fail(f"offline replay diverged from oracle at {diff}")

    # No-contact guard must have stayed silent — proves the run was fully offline.
    assert replay_patches == {"login": 0, "request": 0}


def test_no_contact_guard_actually_fires_if_sap_touched(replay_patches):
    """Sanity: the guard is armed — a real request would raise, not pass silently."""
    fresh = sap_b1_server.SAPB1Client.__new__(sap_b1_server.SAPB1Client)
    with pytest.raises(NoContactError):
        sap_b1_server.SAPB1Client.request(fresh, "GET", "/Invoices")
    with pytest.raises(NoContactError):
        sap_b1_server.SAPB1Client.login(fresh)
