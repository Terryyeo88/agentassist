"""T2.24 PR-2 — additive-only guard + full-loop E2E + CLI period guard (FAILING-FIRST).

Three concerns over the frozen SBODEMOSG replay (SAP unreachable, offline), mirroring the
replay harness in tests/test_t224_chain_seam.py:

  1. ADDITIVE-ONLY guard — the PR-2 parsers do NOT touch XeroF5ChainReader._load_transactions.
     Over the ORIGINAL xero-f5-export fixture the value-box counts stay 3 / 7. Over the newer
     xero-real-format F5 (which carries a 'Transactions not included' section) the value-box
     counts are the DIFFERENT 4 / 8 — documented here, not a regression.

  2. E2E (ceiling retired) — run_chain with a gst_ledger assembled from the PRODUCT parsers
     (load_gst_ledger + parse_declared_return + parse_not_included), asserting BOTH signals:
       Signal A: two ledger-recon divergences (output 270.00, input 6.30) using
                 parse_declared_return's boxes (NOT caller-hand-built).
       Signal B: one not-included GST-drop finding (820 - GST, 6.30).
     Plus BOX-ISOLATION (boxes byte-identical to a no-ledger baseline) and the NO-LEDGER
     path adding ZERO of the four T2.24 keys.

  3. PERIOD GUARD — run_agent.build_gst_ledger_input validates the F5 workbook's OWN period
     against the passed --period; mismatch raises ValueError (--period is authoritative).

Real-FORMAT over SYNTHETIC content; NOT accuracy-validated (T2.11 unmoved).
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

from feeders.xero_f5_reader import (  # noqa: E402
    XeroF5ChainReader,
    parse_declared_return,
    parse_not_included,
)
from feeders.xero_ledger_reader import load_gst_ledger  # noqa: E402
from orchestrator.check_gst_ledger_recon import run_not_included_checks  # noqa: E402

_shim_spec = importlib.util.spec_from_file_location(
    "t224_pr2_replay_shim", Path(__file__).resolve().parent / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sbodemosg-extract"

# The ORIGINAL Xero F5 export fixture (additive-guard baseline — must stay 3 / 7).
_ORIG_F5 = (
    Path(__file__).resolve().parent
    / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)

# The newer real-format corpus (Return sheet + 'Transactions not included' + 820 ledger).
_REAL = Path(__file__).resolve().parent / "fixtures" / "xero-real-format"
_REAL_F5 = _REAL / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_REAL_LEDGER = _REAL / "AgentAssist_-_Account_Transactions.xlsx"

_PERIOD = {"start": "2026-04-01", "end": "2026-06-30"}
_MISMATCHED_PERIOD = {"start": "2026-01-01", "end": "2026-03-31"}


def _period() -> dict:
    return replay_shim.period_from_manifest(FIXTURE_DIR)


@pytest.fixture()
def replay_patches(monkeypatch):
    return replay_shim.install_replay_patches(monkeypatch, FIXTURE_DIR)


# --------------------------------------------------------------------------- #
# 1. ADDITIVE-ONLY guard — value-box loader untouched.
# --------------------------------------------------------------------------- #

def test_additive_original_fixture_counts_unchanged():
    """Over the ORIGINAL xero-f5-export fixture, value-box counts stay 3 / 7."""
    reader = XeroF5ChainReader(_ORIG_F5)
    assert reader.count("Invoices", "", "") == 3
    assert reader.count("PurchaseInvoices", "", "") == 7


def test_additive_real_format_fixture_counts_differ():
    """Over xero-real-format the value-box counts are 4 / 8 (different fixture, NOT 3/7)."""
    reader = XeroF5ChainReader(_REAL_F5)
    assert reader.count("Invoices", "", "") == 4
    assert reader.count("PurchaseInvoices", "", "") == 8


# --------------------------------------------------------------------------- #
# 2. E2E — both signals, box isolation, and the empty no-ledger path.
# --------------------------------------------------------------------------- #

def _real_gst_ledger() -> dict:
    """Assemble the gst_ledger side-input from the PRODUCT parsers (no hand-built boxes)."""
    return {
        "lines": load_gst_ledger(_REAL_LEDGER),
        "declared_boxes": parse_declared_return(_REAL_F5),
        "not_included": parse_not_included(_REAL_F5),
    }


def test_e2e_both_signals_and_box_isolation(replay_patches):
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    period = _period()

    # No-ledger baseline for the box-isolation comparison.
    baseline, _ = run_chain(cfg, period, reader=replay_shim.build_frozen_reader(FIXTURE_DIR))
    boxes_baseline = canonical_json(baseline["calculate"]["boxes"])

    result, _ = run_chain(
        cfg, period,
        reader=replay_shim.build_frozen_reader(FIXTURE_DIR),
        gst_ledger=_real_gst_ledger(),
    )

    # Signal A — two ledger-recon divergences, keyed by side (boxes from parse_declared_return).
    recon = result["ledger_recon_findings"]
    assert recon is not None and len(recon) == 2, f"expected two divergences, got {recon}"
    by_side = {f["side"]: f for f in recon}
    assert set(by_side) == {"output", "input"}
    assert by_side["output"]["divergence"] == 270.00
    assert by_side["input"]["divergence"] == 6.30

    # Signal B — exactly one not-included GST-drop finding.
    noti = result["not_included_findings"]
    assert noti is not None and len(noti) == 1, f"expected one GST-drop finding, got {noti}"
    assert noti[0]["account"] == "820 - GST"
    assert noti[0]["amount"] == 6.30
    assert noti[0]["finding_type"] == "not_included_gst_drop"

    # BOX-ISOLATION — the two side-inputs moved no box value.
    assert canonical_json(result["calculate"]["boxes"]) == boxes_baseline


def test_e2e_no_ledger_path_adds_no_keys(replay_patches):
    """gst_ledger=None -> none of the four T2.24 result keys appear (oracle stays byte-identical)."""
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    result, _ = run_chain(cfg, _period(), reader=replay_shim.build_frozen_reader(FIXTURE_DIR))
    assert "ledger_recon_findings" not in result
    assert "not_included_findings" not in result
    assert "ledger_recon_status" not in result
    assert "not_included_status" not in result


# --------------------------------------------------------------------------- #
# 3. PERIOD GUARD — run_agent.build_gst_ledger_input; --period is authoritative.
# --------------------------------------------------------------------------- #

def test_build_gst_ledger_input_matching_period():
    import run_agent

    bundle = run_agent.build_gst_ledger_input(_REAL_LEDGER, _REAL_F5, _PERIOD)
    assert bundle["declared_boxes"] == {"output_tax": 720.0, "input_tax": 1271.3}
    assert len(bundle["not_included"]) == 4
    assert len(bundle["lines"]) > 0


def test_build_gst_ledger_input_mismatched_period_raises():
    import run_agent

    with pytest.raises(ValueError):
        run_agent.build_gst_ledger_input(_REAL_LEDGER, _REAL_F5, _MISMATCHED_PERIOD)
