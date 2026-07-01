"""
DEBT-9 — SAP-decouple in the loader via the ``source_system`` gate.

The loader previously required a ``sap_b1`` block + credential env vars for EVERY
client, forcing a file-import client (e.g. Xero) to carry a dummy SAP block. This
build makes ``sap_b1`` required IFF ``source_system == "sap_b1"``, keeps
``source_system`` an OPEN accounting-system label, and rejects only values a user
plausibly wrote while intending ``sap_b1`` (typo-guard).

Failing-test-first — these pin the required behaviour and FAIL against current code:

  T1  file-import client (source_system: xero), no sap_b1 block/creds → loads.
  T2  SAP client with a block but missing cred env vars → still raises (loud).
  T3  SAP-marked client with no sap_b1 block → clear error naming sap_b1, at load.
  T4  source_system stays OPEN: sap_b1-lookalikes rejected; xero/myob/... accepted.
  T5  a decoupled config through the REAL run_chain makes ZERO SAP contact.
  T6  the same decoupled config completes run_chain with empty-string SAP fields.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from config.loader import ConfigError, load_client_config

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

# Shared replay harness (frozen SAP reader + no-contact guards) for the T5/T6
# real-run_chain checks — no live SAP.
_shim_spec = importlib.util.spec_from_file_location(
    "debt9_replay_shim", Path(__file__).resolve().parent / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sbodemosg-extract"

# A valid sap_b1 block; username/password env vars are the conftest stubs (set).
_SAP_BLOCK = {
    "service_layer_url": "https://fake",
    "company_db": "TESTDB",
    "username_env_var": "SAP_USERNAME",
    "password_env_var": "SAP_PASSWORD",
    "ssl_verify": False,
}


def _write(tmp_path: Path, **overrides) -> None:
    cfg = {"client_id": "testclient", "client_name": "Test Client", "applicable_gst_rate": 0.09}
    cfg.update(overrides)
    (tmp_path / "testclient.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")


def _load(tmp_path: Path):
    return load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)


# ---------------------------------------------------------------------------
# T1 — file-import client loads with NO sap_b1 block and NO creds.
# ---------------------------------------------------------------------------

def test_t1_file_import_no_sap_block_loads(tmp_path):
    _write(tmp_path, source_system="xero")  # no sap_b1 block
    cfg = _load(tmp_path)
    assert cfg.source_system == "xero"
    assert cfg.service_layer_url == "" and cfg.company_db == ""
    assert cfg.username == "" and cfg.password == ""


# ---------------------------------------------------------------------------
# T2 — SAP client with a block but MISSING creds still raises loudly.
# ---------------------------------------------------------------------------

def test_t2_sap_client_missing_creds_still_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("DEBT9_MISSING_USER", raising=False)
    monkeypatch.delenv("DEBT9_MISSING_PWD", raising=False)
    block = {**_SAP_BLOCK, "username_env_var": "DEBT9_MISSING_USER",
             "password_env_var": "DEBT9_MISSING_PWD"}
    _write(tmp_path, source_system="sap_b1", sap_b1=block)
    with pytest.raises(ConfigError, match="DEBT9_MISSING_USER"):
        _load(tmp_path)


# ---------------------------------------------------------------------------
# T3 — SAP-marked client with NO block → clear error naming sap_b1 at load.
# ---------------------------------------------------------------------------

def test_t3_sap_marked_no_block_raises_naming_sap_b1(tmp_path):
    _write(tmp_path, source_system="sap_b1")  # no sap_b1 block
    with pytest.raises(ConfigError, match="sap_b1"):
        _load(tmp_path)


def test_t3b_absent_source_system_defaults_sap_and_requires_block(tmp_path):
    _write(tmp_path)  # no source_system (→ sap_b1), no sap_b1 block
    with pytest.raises(ConfigError, match="sap_b1"):
        _load(tmp_path)


# ---------------------------------------------------------------------------
# T4 — typo-guard, OPEN set preserved.
# ---------------------------------------------------------------------------

# Given a VALID sap_b1 block, each lookalike would LOAD today (no guard) — so
# asserting a raise proves the guard is genuinely new.
_LOOKALIKES = ["sapb1", "SAP_B1", "sap-b1", "SAP B1", "Sap_b1", "sap", "SAP"]
# Open, legitimate accounting-system labels — must all load (no hidden allow-list).
_OPEN_VALUES = ["xero", "myob", "quickbooks", "freshbooks"]


@pytest.mark.parametrize("val", _LOOKALIKES)
def test_t4_sap_b1_lookalike_rejected(tmp_path, val):
    _write(tmp_path, source_system=val, sap_b1=dict(_SAP_BLOCK))
    with pytest.raises(ConfigError, match="sap_b1"):
        _load(tmp_path)


@pytest.mark.parametrize("val", _OPEN_VALUES)
def test_t4_open_values_accepted(tmp_path, val):
    _write(tmp_path, source_system=val)  # non-SAP → no block needed
    cfg = _load(tmp_path)
    assert cfg.source_system == val


def test_t4_canonical_sap_b1_accepted_with_block(tmp_path):
    _write(tmp_path, source_system="sap_b1", sap_b1=dict(_SAP_BLOCK))
    assert _load(tmp_path).source_system == "sap_b1"


# ---------------------------------------------------------------------------
# T5 / T6 — a decoupled config on the REAL run_chain.
# ---------------------------------------------------------------------------

def _decoupled_cfg(tmp_path):
    # A non-SAP client whose export uses SO/SI codes → declare the mapping to
    # canonical (SR/TX) explicitly (no SAP default is applied for non-SAP clients),
    # so the frozen-data run stays gate-clean.
    _write(
        tmp_path,
        source_system="xero",
        applicable_gst_rate=0.07,
        custom_vat_groups={},
        completeness_threshold=0.10,
        tax_code_mappings={"SO": "SR", "SI": "TX"},
    )
    return _load(tmp_path)


def test_t5_decoupled_config_makes_zero_sap_contact(tmp_path):
    from orchestrator.chain import run_chain
    cfg = _decoupled_cfg(tmp_path)
    reader = replay_shim.build_frozen_reader(FIXTURE_DIR)
    period = replay_shim.period_from_manifest(FIXTURE_DIR)
    with replay_shim.frozen_extract_sap(FIXTURE_DIR) as contact:
        run_chain(cfg, period, reader=reader)
    # configure_client constructed the client with "" fields, but nothing ever
    # logged in or issued a Service Layer request.
    assert contact == {"login": 0, "request": 0}


def test_t6_decoupled_config_empty_sap_fields_complete_run_chain(tmp_path):
    from orchestrator.chain import run_chain
    cfg = _decoupled_cfg(tmp_path)
    assert cfg.service_layer_url == "" and cfg.username == ""  # empty-string, not None
    reader = replay_shim.build_frozen_reader(FIXTURE_DIR)
    period = replay_shim.period_from_manifest(FIXTURE_DIR)
    with replay_shim.frozen_extract_sap(FIXTURE_DIR):
        compile_output, gate_results = run_chain(cfg, period, reader=reader)
    assert isinstance(compile_output, dict) and isinstance(gate_results, dict)
