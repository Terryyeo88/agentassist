"""
tests/test_tfix_chain_listing_swallow.py — failing-test-first for the listing-checks
swallowed-exception fix (branch ``tfix-chain-listing-swallow``).

Two coupled bugs on the listing-findings surface, both proven RED here first:

  BUG 1 (the swallow): orchestrator/chain.py catches ALL exceptions from the listing
  checks and sets ``listing_findings = []`` with only a log line — a thrown listing
  check renders byte-identical to a genuine clean run. The honest outcome is a
  chain-level ``listing_checks_status`` of ``unavailable`` (Terry's Option B: a SEPARATE
  result key, borrowing 2B's vocabulary but importing nothing from feeders).

  BUG 2 (the mislabel): a genuine clean run (checks RAN, found nothing) is labelled
  "not examined" rather than "examined — no findings". The render layer must positively
  mark examined-clean and keep all THREE states distinct.

Hermetic: frozen reader injected through the public ``run_chain(reader=...)`` seam, SAP
unreachable. No anthropic import, no live SAP.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from orchestrator.chain import run_chain

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402,F401 — path set above; needed so the seam imports

from config.loader import load_client_config  # noqa: E402
from report.sections import (  # noqa: E402
    build_not_examined_section,
    render_listing_findings_section,
)

# Load the shared replay harness (tests/ is not a package).
_shim_spec = importlib.util.spec_from_file_location(
    "tfix_replay_shim", Path(__file__).resolve().parent / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sbodemosg-extract"

_SEQ_GAP_NE = "sequence gap detection"
_DUP_CLAIM_NE = "duplicate input-tax claims"


# ---------------------------------------------------------------------------
# Injection: a frozen reader whose listing fetch THROWS, all else frozen.
# ---------------------------------------------------------------------------

class _ThrowingListingReader(replay_shim.FrozenExtractReader):
    """FrozenExtractReader with ONLY fetch_listing forced to raise.

    Every other surface (count/fetch_invoices/fetch_credit_notes/get_business_partner)
    stays frozen so the chain reaches the post-gate-5 listing block normally and the
    throw lands in exactly the except under test.
    """

    def fetch_listing(self, period: dict) -> dict:
        raise RuntimeError("listing read failed")


def _period() -> dict:
    return replay_shim.period_from_manifest(FIXTURE_DIR)


def _cfg():
    return load_client_config("sbodemosg", check_connectivity=False)


@pytest.fixture()
def replay_patches(monkeypatch):
    """No-contact guards + frozen clock; reads injected via the seam."""
    return replay_shim.install_replay_patches(monkeypatch, FIXTURE_DIR)


# ---------------------------------------------------------------------------
# Test A — the swallow surfaces as `unavailable`, never silent [].
# ---------------------------------------------------------------------------

class TestSwallowSurfacesUnavailable:

    def test_thrown_listing_check_sets_unavailable_status(self, replay_patches):
        cfg, period = _cfg(), _period()
        compile_output, _ = run_chain(cfg, period, reader=_ThrowingListingReader(FIXTURE_DIR))

        status = compile_output.get("listing_checks_status")
        assert status is not None, (
            "BUG 1: a thrown listing check left NO chain-level signal — it renders "
            "identical to a genuine clean run"
        )
        assert status.get("level") == "unavailable"
        assert status.get("reason"), "unavailable status must surface a non-empty reason"
        assert "listing read failed" in status["reason"]

    def test_thrown_listing_check_does_not_report_zero_findings(self, replay_patches):
        cfg, period = _cfg(), _period()
        compile_output, _ = run_chain(cfg, period, reader=_ThrowingListingReader(FIXTURE_DIR))
        # Honest contract: a failed run must NOT masquerade as a clean [] zero-findings run.
        assert compile_output.get("listing_findings") != [], (
            "BUG 1: failed listing checks must not read as zero findings"
        )

    def test_thrown_listing_check_does_not_crash_chain(self, replay_patches):
        cfg, period = _cfg(), _period()
        # Findings never gate: the chain must complete (the throw is non-fatal).
        compile_output, gate_results = run_chain(
            cfg, period, reader=_ThrowingListingReader(FIXTURE_DIR)
        )
        assert compile_output is not None and gate_results is not None

    def test_box_isolation_holds_under_throw(self, replay_patches):
        """F5 boxes byte-identical between a clean run and a throwing-listing run."""
        cfg, period = _cfg(), _period()
        clean_out, _ = run_chain(cfg, period, reader=replay_shim.build_frozen_reader(FIXTURE_DIR))
        throw_out, _ = run_chain(cfg, period, reader=_ThrowingListingReader(FIXTURE_DIR))
        assert throw_out["calculate"]["boxes"] == clean_out["calculate"]["boxes"]


# ---------------------------------------------------------------------------
# Test B — a genuine clean run is positively marked examined, not "not examined".
# ---------------------------------------------------------------------------

class TestCleanRunMarkedExamined:

    def test_clean_run_listing_findings_empty(self, replay_patches):
        cfg, period = _cfg(), _period()
        compile_output, _ = run_chain(cfg, period, reader=replay_shim.build_frozen_reader(FIXTURE_DIR))
        # SBODEMOSG: NumAtCard all-null + no gaps → genuine clean run.
        assert compile_output["listing_findings"] == []
        # Clean SUCCESS path must NOT set an unavailable status.
        assert compile_output.get("listing_checks_status") is None

    def test_clean_run_section_status_examined(self):
        sec = render_listing_findings_section({"listing_findings": []})
        assert sec.status == "examined", (
            "BUG 2: a ran-clean listing pass must be marked 'examined', not 'not_examined'"
        )

    def test_clean_run_suppresses_not_examined_items(self):
        co = {"listing_findings": []}
        sec = render_listing_findings_section(co)
        items = build_not_examined_section(co, _Cfg(), listing_section=sec).items
        combined = " ".join(items).lower()
        assert _SEQ_GAP_NE not in combined, (
            "BUG 2: examined-clean run must NOT claim 'sequence gap detection' was not examined"
        )
        assert _DUP_CLAIM_NE not in combined, (
            "BUG 2: examined-clean run must NOT claim 'duplicate input-tax claims' was not examined"
        )


# ---------------------------------------------------------------------------
# Test C — the THREE states stay mutually distinguishable.
# ---------------------------------------------------------------------------

class _Cfg:
    custom_vat_groups: dict = {}


def _state_items(compile_output: dict) -> str:
    sec = render_listing_findings_section(compile_output)
    items = build_not_examined_section(compile_output, _Cfg(), listing_section=sec).items
    return " ".join(items).lower()


class TestThreeStatesDistinct:

    def test_unavailable_examined_notexamined_all_distinct(self):
        unavailable_co = {
            "listing_findings": None,
            "listing_checks_status": {
                "level": "unavailable",
                "reason": "listing checks failed to run: boom",
            },
        }
        examined_co = {"listing_findings": []}          # ran-clean
        not_examined_co = {}                            # listing key absent → never ran

        sec_unavail = render_listing_findings_section(unavailable_co)
        sec_examined = render_listing_findings_section(examined_co)
        sec_notexam = render_listing_findings_section(not_examined_co)

        statuses = {sec_unavail.status, sec_examined.status, sec_notexam.status}
        assert statuses == {"unavailable", "examined", "not_examined"}, (
            f"three states must be distinct; got {statuses}"
        )

        unavail_items = _state_items(unavailable_co)
        notexam_items = _state_items(not_examined_co)

        # genuinely-not-examined keeps the static catalogue lines …
        assert _SEQ_GAP_NE in notexam_items
        # … while unavailable surfaces a distinct "could not run" caveat (not the
        # static "not examined" line), so a reviewer never reads a throw as never-run.
        assert "could not run" in unavail_items
