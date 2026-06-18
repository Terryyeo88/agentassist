"""T2.12b — honest-degradation coverage mechanism.

Slice 2B maps the extract-feeder coverage seam onto a per-check DATA-COVERAGE status
(full / degraded(reason) / unavailable) so a reviewer never signs a silently-partial
review. This suite is failing-test-first for:

  * the new ``CoverageStatus`` type (carries a reason; full carries none);
  * the (surface, field)-keyed coverage map (the two DocTotal surfaces stay distinct —
    the bare-field-key collapse is the bug 2B fixes);
  * value-population-aware coverage (a present-but-0%-populated column is NOT ``full``);
  * the three in-scope cases emitting their approved status + SURFACED caveat:
      NumAtCard absent/empty   → DUP_CLAIM   → degraded
      FederalTaxID absent      → NO_GST_REG  → unavailable
      company-wide pop absent  → SEQ_GAP     → degraded
  * NO_GST_REG is SUPPRESSED (no degraded variant) when FederalTaxID is unavailable;
  * the chain emits ``check_coverage`` only when the reader declares one (the live-SAP /
    frozen-replay readers expose none → byte-identical there).

Caveats state the data-coverage FACT only — no IRAS rationale (Terry sources the tax basis).
"""
from __future__ import annotations

import csv as _csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from feeders.extract_reader import ExtractChainReader
from feeders import extract_schema as schema
from feeders import coverage_status as cov_status

# Importing the chain wires mcp-servers/custom onto sys.path; sap_b1_server then imports.
from orchestrator.chain import run_chain, _emit_check_coverage  # noqa: F401

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402

FROZEN_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
EXPORT_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "extract-export-sbodemosg"

# Load the synthetic exporter (tests/ is not a package — importlib, as replay_shim does).
_synth_spec = importlib.util.spec_from_file_location(
    "t212b_synth_export", _REPO_ROOT / "tests" / "synth_extract_export.py"
)
synth = importlib.util.module_from_spec(_synth_spec)
_synth_spec.loader.exec_module(synth)

# Load the replay shim (no-contact guards + frozen reader, for the end-to-end run).
_shim_spec = importlib.util.spec_from_file_location(
    "t212b_replay_shim", _REPO_ROOT / "tests" / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)


_BP_SHEET = schema.BUSINESS_PARTNERS_SHEET
_LISTING_SHEET = schema.LISTING_SHEET


def _export_to(tmp_path: Path) -> Path:
    synth.export_csv(FROZEN_DIR, tmp_path)
    return tmp_path


def _rewrite_csv(path: Path, fieldnames, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = _csv.DictReader(fh)
        return list(reader.fieldnames or []), [dict(r) for r in reader]


def _strip_federaltaxid(tmp_path: Path) -> Path:
    """Export, then drop the FederalTaxID column entirely from the BP sheet."""
    _export_to(tmp_path)
    bp = tmp_path / f"{_BP_SHEET}.csv"
    fields, rows = _read_csv(bp)
    kept = [f for f in fields if f != "FederalTaxID"]
    _rewrite_csv(bp, kept, rows)
    return tmp_path


def _drop_company_wide_listing(tmp_path: Path) -> Path:
    """Export, then drop every company-wide ('all' scope) listing row."""
    _export_to(tmp_path)
    listing = tmp_path / f"{_LISTING_SHEET}.csv"
    fields, rows = _read_csv(listing)
    period_only = [r for r in rows if r.get(schema.SCOPE_COL) != "all"]
    _rewrite_csv(listing, fields, period_only)
    return tmp_path


def _populate_one_numatcard(tmp_path: Path) -> Path:
    """Export, then give one period-purchase row a non-empty NumAtCard."""
    _export_to(tmp_path)
    listing = tmp_path / f"{_LISTING_SHEET}.csv"
    fields, rows = _read_csv(listing)
    for r in rows:
        if r.get(schema.SCOPE_COL) == "period" and r.get(schema.DOC_TYPE_COL) == "purchase":
            r["NumAtCard"] = "INV-0001"
            break
    _rewrite_csv(listing, fields, rows)
    return tmp_path


# ---------------------------------------------------------------------------
# CoverageStatus type — carries a reason; full carries none; levels are distinct.
# ---------------------------------------------------------------------------


def test_status_levels_are_three_distinct_values():
    assert {cov_status.FULL, cov_status.DEGRADED, cov_status.UNAVAILABLE} == cov_status.LEVELS
    assert len(cov_status.LEVELS) == 3


def test_full_status_carries_no_reason():
    s = cov_status.CoverageStatus("DUP_CLAIM", cov_status.FULL, "")
    assert s.as_dict() == {"check": "DUP_CLAIM", "level": "full", "reason": ""}


def test_degraded_and_unavailable_require_a_reason():
    # full ≠ ran-clean: a degraded/unavailable status MUST surface a non-empty reason.
    with pytest.raises(ValueError):
        cov_status.CoverageStatus("DUP_CLAIM", cov_status.DEGRADED, "")
    with pytest.raises(ValueError):
        cov_status.CoverageStatus("NO_GST_REG", cov_status.UNAVAILABLE, "")


def test_full_status_rejects_a_reason():
    with pytest.raises(ValueError):
        cov_status.CoverageStatus("SEQ_GAP", cov_status.FULL, "something")


def test_unknown_level_rejected():
    with pytest.raises(ValueError):
        cov_status.CoverageStatus("DUP_CLAIM", "partial", "x")


def test_statuses_stay_distinguishable():
    full = cov_status.CoverageStatus("X", cov_status.FULL, "")
    degraded = cov_status.CoverageStatus("X", cov_status.DEGRADED, "r1")
    unavail = cov_status.CoverageStatus("X", cov_status.UNAVAILABLE, "r2")
    # full ≠ degraded ≠ unavailable, and none is the bare "ran-clean" None.
    assert full != degraded != unavail and full != unavail
    assert full.level != degraded.level != unavail.level
    assert None not in (full, degraded, unavail)


# ---------------------------------------------------------------------------
# Constraint 1 — coverage map keyed by (surface, field); two DocTotal surfaces distinct.
# ---------------------------------------------------------------------------


def test_coverage_fields_keyed_by_surface_field_tuple():
    for key in schema.COVERAGE_FIELDS:
        assert isinstance(key, tuple) and len(key) == 2


def test_both_doctotal_surfaces_present_and_distinct():
    doc_key = (schema.DOCUMENTS_SHEET, "DocTotal")
    listing_key = (schema.LISTING_SHEET, "DocTotal")
    assert doc_key in schema.COVERAGE_FIELDS
    assert listing_key in schema.COVERAGE_FIELDS
    assert doc_key != listing_key
    # The bare-field collapse is the bug: a name-keyed map could hold only one.
    surfaces_for_doctotal = [s for (s, f) in schema.COVERAGE_FIELDS if f == "DocTotal"]
    assert sorted(surfaces_for_doctotal) == sorted([schema.DOCUMENTS_SHEET, schema.LISTING_SHEET])


# ---------------------------------------------------------------------------
# Constraint 2 — value-population-aware: present-but-empty is NOT covered.
# ---------------------------------------------------------------------------


def test_numatcard_present_but_empty_is_not_covered():
    cov = ExtractChainReader(EXPORT_FIXTURE_DIR).coverage()
    # Column present (header-full) but 0% populated in SBODEMOSG.
    assert cov.is_present(_LISTING_SHEET, "NumAtCard")
    assert not cov.is_populated(_LISTING_SHEET, "NumAtCard")
    assert not cov.is_covered(_LISTING_SHEET, "NumAtCard")
    # Header-fullness still holds — all columns are present.
    assert cov.is_full()


def test_federaltaxid_partially_populated_is_covered():
    cov = ExtractChainReader(EXPORT_FIXTURE_DIR).coverage()
    # Some BPs carry a FederalTaxID (V21000, V22000) → present AND populated → covered.
    assert cov.is_covered(_BP_SHEET, "FederalTaxID")


def test_federaltaxid_absent_is_not_covered(tmp_path):
    cov = ExtractChainReader(_strip_federaltaxid(tmp_path)).coverage()
    assert not cov.is_present(_BP_SHEET, "FederalTaxID")
    assert not cov.is_covered(_BP_SHEET, "FederalTaxID")
    assert (_BP_SHEET, "FederalTaxID") in cov.missing()


# ---------------------------------------------------------------------------
# derive_coverage_statuses — the pure mapping (coverage facts → per-check status).
# ---------------------------------------------------------------------------


def _status_by_check(statuses):
    return {s.check: s for s in statuses}


def test_derive_full_when_everything_covered(tmp_path):
    cov = ExtractChainReader(_populate_one_numatcard(tmp_path)).coverage()
    statuses = cov_status.derive_coverage_statuses(cov, company_wide_population_present=True)
    by = _status_by_check(statuses)
    assert by["DUP_CLAIM"].level == cov_status.FULL
    assert by["NO_GST_REG"].level == cov_status.FULL
    assert by["SEQ_GAP"].level == cov_status.FULL


def test_derive_dup_claim_degraded_when_numatcard_unpopulated():
    cov = ExtractChainReader(EXPORT_FIXTURE_DIR).coverage()
    by = _status_by_check(
        cov_status.derive_coverage_statuses(cov, company_wide_population_present=True)
    )
    assert by["DUP_CLAIM"].level == cov_status.DEGRADED
    assert by["DUP_CLAIM"].reason  # surfaced, non-empty
    assert "NumAtCard" in by["DUP_CLAIM"].reason


def test_derive_no_gst_reg_unavailable_when_federaltaxid_absent(tmp_path):
    cov = ExtractChainReader(_strip_federaltaxid(tmp_path)).coverage()
    by = _status_by_check(
        cov_status.derive_coverage_statuses(cov, company_wide_population_present=True)
    )
    assert by["NO_GST_REG"].level == cov_status.UNAVAILABLE
    assert "FederalTaxID" in by["NO_GST_REG"].reason


def test_derive_seq_gap_degraded_when_company_wide_absent():
    cov = ExtractChainReader(EXPORT_FIXTURE_DIR).coverage()
    by = _status_by_check(
        cov_status.derive_coverage_statuses(cov, company_wide_population_present=False)
    )
    assert by["SEQ_GAP"].level == cov_status.DEGRADED
    assert by["SEQ_GAP"].reason


def test_caveats_carry_no_iras_rationale():
    cov = ExtractChainReader(EXPORT_FIXTURE_DIR).coverage()
    statuses = cov_status.derive_coverage_statuses(cov, company_wide_population_present=False)
    for s in statuses:
        # Data-coverage facts only — no statute/citation/§ rationale.
        assert "§" not in s.reason
        assert "IRAS" not in s.reason
        assert "Reg " not in s.reason


# ---------------------------------------------------------------------------
# reader.coverage_status() — the three in-scope cases over real exports.
# ---------------------------------------------------------------------------


def test_reader_coverage_status_on_committed_export():
    # SBODEMOSG: NumAtCard 0% → DUP_CLAIM degraded; FederalTaxID partial → NO_GST_REG
    # full; company-wide 'all' rows present → SEQ_GAP full.
    by = _status_by_check(ExtractChainReader(EXPORT_FIXTURE_DIR).coverage_status())
    assert by["DUP_CLAIM"].level == cov_status.DEGRADED
    assert by["NO_GST_REG"].level == cov_status.FULL
    assert by["SEQ_GAP"].level == cov_status.FULL


def test_reader_coverage_status_federaltaxid_unavailable(tmp_path):
    by = _status_by_check(ExtractChainReader(_strip_federaltaxid(tmp_path)).coverage_status())
    assert by["NO_GST_REG"].level == cov_status.UNAVAILABLE


def test_reader_coverage_status_seq_gap_degraded(tmp_path):
    by = _status_by_check(ExtractChainReader(_drop_company_wide_listing(tmp_path)).coverage_status())
    assert by["SEQ_GAP"].level == cov_status.DEGRADED


def test_reader_coverage_status_dup_claim_full_when_numatcard_populated(tmp_path):
    by = _status_by_check(ExtractChainReader(_populate_one_numatcard(tmp_path)).coverage_status())
    assert by["DUP_CLAIM"].level == cov_status.FULL


# ---------------------------------------------------------------------------
# NO_GST_REG suppression — no degraded variant when FederalTaxID unavailable.
# ---------------------------------------------------------------------------


def _detect_codes(reader):
    out = json.loads(sap_b1_server.detect_gst_errors("2024-07-01", "2024-09-30", reader=reader))
    return {i["error_code"] for i in out["issues"]}


def test_no_gst_reg_runs_when_federaltaxid_covered():
    # Committed export has unregistered suppliers with input tax → NO_GST_REG fires.
    assert "NO_GST_REG" in _detect_codes(ExtractChainReader(EXPORT_FIXTURE_DIR))


def test_no_gst_reg_suppressed_when_federaltaxid_unavailable(tmp_path):
    assert "NO_GST_REG" not in _detect_codes(ExtractChainReader(_strip_federaltaxid(tmp_path)))


# ---------------------------------------------------------------------------
# Chain emission — check_coverage only when the reader declares one.
# ---------------------------------------------------------------------------


def test_emit_check_coverage_added_for_reader_with_status_seam():
    class _Fake:
        def coverage_status(self):
            return [cov_status.CoverageStatus("DUP_CLAIM", cov_status.DEGRADED, "r")]

    result: dict = {}
    _emit_check_coverage(result, _Fake())
    assert result["check_coverage"] == [{"check": "DUP_CLAIM", "level": "degraded", "reason": "r"}]


def test_emit_check_coverage_absent_for_reader_without_seam():
    class _Plain:
        pass

    result: dict = {}
    _emit_check_coverage(result, _Plain())
    assert "check_coverage" not in result
    # And a None reader (default SAP path) is a no-op too.
    _emit_check_coverage(result, None)
    assert "check_coverage" not in result


def test_full_chain_over_export_emits_check_coverage(monkeypatch):
    """End-to-end: run_chain over the committed export surfaces the per-check coverage."""
    from config.loader import load_client_config

    replay_shim.install_replay_patches(monkeypatch, FROZEN_DIR)
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    period = replay_shim.period_from_manifest(FROZEN_DIR)
    reader = ExtractChainReader(EXPORT_FIXTURE_DIR)

    compile_output, _gate_results = run_chain(cfg, period, reader=reader)

    assert "check_coverage" in compile_output
    by = {s["check"]: s for s in compile_output["check_coverage"]}
    assert by["DUP_CLAIM"]["level"] == "degraded"
    assert by["NO_GST_REG"]["level"] == "full"
    assert by["SEQ_GAP"]["level"] == "full"
