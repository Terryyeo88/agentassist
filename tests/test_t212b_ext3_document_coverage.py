"""T2.12-2B-ext-3 — explicit coverage for the four document-pre-pass (T2.8) checks.

ext-1 made the line-level E-checks explicit; ext-3 does the same for the four
document-pre-pass checks (`documents/reconcile.py`), keyed on the document_pdfs surface:

  gst_amount_mismatch, correct_period, total_inconsistency, reg11_supplier_gst_absent

Per Terry's ruling:
  * level is UNAVAILABLE (not degraded) when document_pdfs is absent — all four share the
    same PDF-ingest gate (`run_documents_pass` skips a doc_num whose provider returns None,
    so `reconcile` is never reached), so NONE can run. This is the NO_GST_REG←FederalTaxID
    cannot-run pattern, not the DUP_CLAIM under-detect pattern. The provider is binary —
    there is NO present-but-sparse middle state representable here (document_pdfs is not a
    COVERAGE_FIELDS pair; there is no per-PDF field coverage).
  * the signal is a CHECK-KEYED bool `document_pdfs_present` (NOT a `(surface, field)`
    is_covered pair — document_pdfs is not in the coverage model), mirroring SEQ_GAP's
    company-wide population bool. The ExtractChainReader is a listing/transaction export
    with no PDF surface, so it passes the constant False — `run_chain` is never coupled to
    the engine-level provider, and the seamless SAP/replay readers (no coverage seam) stay
    byte-identical.

SYMMETRY-BREAKING: provider-present → full; provider-absent → unavailable. A blind
`return full` fails the absent branch; a blind `return unavailable` fails the present branch.

The three locked 2B cases and the four ext-1 E-checks stay byte-identical (asserted).
Caveats carry the coverage FACT only — no §/IRAS rationale. Hermetic: no SAP, no live chain.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from feeders.extract_reader import ExtractChainReader
from feeders import coverage_status as cov_status

# Importing the chain wires mcp-servers/custom onto sys.path; sap_b1_server then imports.
from orchestrator.chain import run_chain  # noqa: F401

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

FROZEN_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
EXPORT_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "extract-export-sbodemosg"

# Load the replay shim (no-contact guards + frozen reader, for the end-to-end run).
_shim_spec = importlib.util.spec_from_file_location(
    "t212b_ext3_replay_shim", _REPO_ROOT / "tests" / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)


# The four document-pre-pass checks, in the stable order they append (map §A / reconcile.py).
_DOC_CHECKS = (
    "gst_amount_mismatch",
    "correct_period",
    "total_inconsistency",
    "reg11_supplier_gst_absent",
)

# Expected full status-list order after ext-3 (3 locked 2B + 4 ext-1 + 4 ext-3).
_EXPECTED_ORDER = [
    "DUP_CLAIM", "NO_GST_REG", "SEQ_GAP",
    "E1", "E2", "E3", "E4",
    "gst_amount_mismatch", "correct_period", "total_inconsistency", "reg11_supplier_gst_absent",
]


def _by_check(statuses):
    return {s.check: s for s in statuses}


def _derive(*, document_pdfs_present):
    cov = ExtractChainReader(EXPORT_FIXTURE_DIR).coverage()
    return cov_status.derive_coverage_statuses(
        cov,
        company_wide_population_present=True,
        document_pdfs_present=document_pdfs_present,
    )


# ---------------------------------------------------------------------------
# derive_coverage_statuses — symmetry-breaking on the document_pdfs_present bool.
# ---------------------------------------------------------------------------


def test_ext3_unavailable_when_document_pdfs_absent():
    by = _by_check(_derive(document_pdfs_present=False))
    for check in _DOC_CHECKS:
        assert by[check].level == cov_status.UNAVAILABLE
        assert by[check].reason  # surfaced, non-empty
        assert check in by[check].reason


def test_ext3_full_when_document_pdfs_present():
    by = _by_check(_derive(document_pdfs_present=True))
    for check in _DOC_CHECKS:
        assert by[check].level == cov_status.FULL
        assert by[check].reason == ""


def test_ext3_default_is_absent():
    # Default (no document_pdfs_present passed) must be the honest "absent" → unavailable,
    # so a caller that forgets the flag never silently reports the docs as examined.
    cov = ExtractChainReader(EXPORT_FIXTURE_DIR).coverage()
    by = _by_check(
        cov_status.derive_coverage_statuses(cov, company_wide_population_present=True)
    )
    for check in _DOC_CHECKS:
        assert by[check].level == cov_status.UNAVAILABLE


# ---------------------------------------------------------------------------
# Caveat hygiene — the document-coverage reasons state the FACT only.
# ---------------------------------------------------------------------------


def test_ext3_reasons_carry_no_iras_rationale():
    by = _by_check(_derive(document_pdfs_present=False))
    for check in _DOC_CHECKS:
        reason = by[check].reason
        assert reason
        assert "§" not in reason
        assert "IRAS" not in reason
        assert "Reg " not in reason


# ---------------------------------------------------------------------------
# Reader real-path — the extract feeder has no PDF surface → all four unavailable.
# ---------------------------------------------------------------------------


def test_ext3_reader_committed_export_documents_unavailable():
    by = _by_check(ExtractChainReader(EXPORT_FIXTURE_DIR).coverage_status())
    for check in _DOC_CHECKS:
        assert by[check].level == cov_status.UNAVAILABLE
        assert by[check].reason


# ---------------------------------------------------------------------------
# Locked 2B + ext-1 invariance — byte-identical with ext-3 wired.
# ---------------------------------------------------------------------------


def test_ext3_does_not_disturb_locked_2b_cases():
    by = _by_check(ExtractChainReader(EXPORT_FIXTURE_DIR).coverage_status())
    assert by["DUP_CLAIM"].as_dict() == {
        "check": "DUP_CLAIM",
        "level": "degraded",
        "reason": "NumAtCard absent or unpopulated — DUP_CLAIM under-detects.",
    }
    assert by["NO_GST_REG"].as_dict() == {
        "check": "NO_GST_REG", "level": "full", "reason": "",
    }
    assert by["SEQ_GAP"].as_dict() == {
        "check": "SEQ_GAP", "level": "full", "reason": "",
    }


def test_ext3_does_not_disturb_ext1_e_checks():
    by = _by_check(ExtractChainReader(EXPORT_FIXTURE_DIR).coverage_status())
    for check in ("E1", "E2", "E3", "E4"):
        assert by[check].as_dict() == {"check": check, "level": "full", "reason": ""}


def test_ext3_full_status_order_is_stable():
    order = [s.check for s in ExtractChainReader(EXPORT_FIXTURE_DIR).coverage_status()]
    assert order == _EXPECTED_ORDER


# ---------------------------------------------------------------------------
# End-to-end — run_chain over the committed export surfaces the four document rows.
# ---------------------------------------------------------------------------


def test_ext3_full_chain_emits_document_rows(monkeypatch):
    from config.loader import load_client_config

    replay_shim.install_replay_patches(monkeypatch, FROZEN_DIR)
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    period = replay_shim.period_from_manifest(FROZEN_DIR)
    reader = ExtractChainReader(EXPORT_FIXTURE_DIR)

    compile_output, _gate = run_chain(cfg, period, reader=reader)

    assert "check_coverage" in compile_output
    by = {s["check"]: s for s in compile_output["check_coverage"]}
    for check in _DOC_CHECKS:
        assert by[check]["level"] == "unavailable"
        assert by[check]["reason"]
    # locked + ext-1 unchanged through the chain too
    assert by["DUP_CLAIM"]["level"] == "degraded"
    assert by["NO_GST_REG"]["level"] == "full"
    assert by["E1"]["level"] == "full"
