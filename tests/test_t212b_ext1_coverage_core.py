"""T2.12-2B-ext-1 — explicit coverage for the always-present line core fields.

Slice 2B emitted per-check DATA-COVERAGE status for three cases (DUP_CLAIM, NO_GST_REG,
SEQ_GAP). ext-1 makes the previously-IMPLICIT-full status EXPLICIT for E1–E4, the four
line-level deterministic checks, using the EXACT same mechanism (``derive_coverage_statuses``
+ the value-population-aware ``is_covered(surface, field)`` predicate) over the documents
surface. Per Terry's ruling:

  * scope is E1–E4 ONLY, over (documents, VatGroup/LineTotal/TaxTotal). CardCode and
    computed_boxes/declared_B are descoped (no in-scope home / not an export field).
  * level is DEGRADED, not unavailable — the E-checks run over the documents surface and
    UNDER-DETECT when a line field is absent/unpopulated; they do not cannot-run. This
    mirrors DUP_CLAIM←NumAtCard.

SYMMETRY-BREAKING: each E-check is asserted full when its line fields are present+populated
AND degraded when EACH of its line fields is independently blanked (present-but-empty),
proving every field is load-bearing. A test that only checked the happy path would pass even
if the code blindly returned ``full`` — these do not.

The three locked 2B cases stay byte-identical (asserted). Caveats carry the coverage FACT
only — no IRAS rationale. Hermetic: no SAP, no live chain, no anthropic.
"""
from __future__ import annotations

import csv as _csv
import importlib.util
import sys
from pathlib import Path

import pytest

from feeders.extract_reader import ExtractChainReader
from feeders import extract_schema as schema
from feeders import coverage_status as cov_status

# Importing the chain wires mcp-servers/custom onto sys.path; sap_b1_server then imports.
from orchestrator.chain import run_chain  # noqa: F401

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

FROZEN_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
EXPORT_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "extract-export-sbodemosg"

# Load the synthetic exporter (tests/ is not a package — importlib, as the 2B suite does).
_synth_spec = importlib.util.spec_from_file_location(
    "t212b_ext1_synth_export", _REPO_ROOT / "tests" / "synth_extract_export.py"
)
synth = importlib.util.module_from_spec(_synth_spec)
_synth_spec.loader.exec_module(synth)

# Load the replay shim (no-contact guards + frozen reader, for the end-to-end run).
_shim_spec = importlib.util.spec_from_file_location(
    "t212b_ext1_replay_shim", _REPO_ROOT / "tests" / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)

_DOCS = schema.DOCUMENTS_SHEET


# ---------------------------------------------------------------------------
# Helpers — export the frozen surface to CSV, then mutate the documents sheet.
# ---------------------------------------------------------------------------


def _export_to(tmp_path: Path) -> Path:
    synth.export_csv(FROZEN_DIR, tmp_path)
    return tmp_path


def _read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = _csv.DictReader(fh)
        return list(reader.fieldnames or []), [dict(r) for r in reader]


def _rewrite_csv(path: Path, fieldnames, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _blank_doc_column(tmp_path: Path, column: str) -> Path:
    """Export, then EMPTY every cell of ``column`` in documents.csv (header kept).

    This is the population-aware case: the column stays PRESENT (header) but becomes
    0%-populated, so ``is_covered`` must read it as NOT covered — header-presence alone
    would wrongly pass. Stronger than dropping the column.
    """
    _export_to(tmp_path)
    docs = tmp_path / f"{_DOCS}.csv"
    fields, rows = _read_csv(docs)
    assert column in fields, f"{column} must be present to blank it"
    for r in rows:
        r[column] = ""
    _rewrite_csv(docs, fields, rows)
    return tmp_path


def _statuses(source: Path):
    cov = ExtractChainReader(source).coverage()
    return cov_status.derive_coverage_statuses(cov, company_wide_population_present=True)


def _by_check(statuses):
    return {s.check: s for s in statuses}


# Each E-check and the line fields it is load-bearing on (PR #66 map §B).
_ECHECK_FIELDS = {
    "E1": ("VatGroup", "LineTotal"),
    "E2": ("VatGroup", "TaxTotal"),
    "E3": ("VatGroup", "LineTotal", "TaxTotal"),
    "E4": ("VatGroup", "LineTotal", "TaxTotal"),
}


# ---------------------------------------------------------------------------
# Happy path — all four E-checks full when the line fields are present+populated.
# ---------------------------------------------------------------------------


def test_ext1_all_four_full_on_clean_export(tmp_path):
    by = _by_check(_statuses(_export_to(tmp_path)))
    for check in ("E1", "E2", "E3", "E4"):
        assert by[check].level == cov_status.FULL
        assert by[check].reason == ""


def test_ext1_e_checks_present_on_committed_export():
    by = _by_check(ExtractChainReader(EXPORT_FIXTURE_DIR).coverage_status())
    for check in ("E1", "E2", "E3", "E4"):
        assert by[check].level == cov_status.FULL


# ---------------------------------------------------------------------------
# Symmetry-breaking — each E-check degrades when EACH of its fields is blanked.
# Parametrised so every (check, field) load-bearing pair is proven independently.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "check,field",
    [(c, f) for c, fields in _ECHECK_FIELDS.items() for f in fields],
)
def test_ext1_degrades_when_each_field_blanked(tmp_path, check, field):
    by = _by_check(_statuses(_blank_doc_column(tmp_path, field)))
    assert by[check].level == cov_status.DEGRADED
    assert by[check].reason  # surfaced, non-empty
    assert field in by[check].reason  # names the specific missing field
    assert check in by[check].reason


def test_ext1_blanking_linetotal_spares_e2_only(tmp_path):
    # LineTotal is load-bearing for E1/E3/E4 but NOT E2 (VatGroup+TaxTotal). A blind
    # all-degrade or all-full implementation fails this.
    by = _by_check(_statuses(_blank_doc_column(tmp_path, "LineTotal")))
    assert by["E2"].level == cov_status.FULL
    assert by["E1"].level == cov_status.DEGRADED
    assert by["E3"].level == cov_status.DEGRADED
    assert by["E4"].level == cov_status.DEGRADED


def test_ext1_blanking_taxtotal_spares_e1_only(tmp_path):
    # TaxTotal is load-bearing for E2/E3/E4 but NOT E1 (VatGroup+LineTotal).
    by = _by_check(_statuses(_blank_doc_column(tmp_path, "TaxTotal")))
    assert by["E1"].level == cov_status.FULL
    assert by["E2"].level == cov_status.DEGRADED
    assert by["E3"].level == cov_status.DEGRADED
    assert by["E4"].level == cov_status.DEGRADED


def test_ext1_blanking_vatgroup_degrades_all_four(tmp_path):
    # VatGroup is load-bearing for every E-check.
    by = _by_check(_statuses(_blank_doc_column(tmp_path, "VatGroup")))
    for check in ("E1", "E2", "E3", "E4"):
        assert by[check].level == cov_status.DEGRADED


# ---------------------------------------------------------------------------
# Caveat hygiene — the new reasons state the coverage FACT only.
# ---------------------------------------------------------------------------


def test_ext1_reasons_carry_no_iras_rationale(tmp_path):
    by = _by_check(_statuses(_blank_doc_column(tmp_path, "VatGroup")))
    for check in ("E1", "E2", "E3", "E4"):
        reason = by[check].reason
        assert reason
        assert "§" not in reason
        assert "IRAS" not in reason
        assert "Reg " not in reason


# ---------------------------------------------------------------------------
# Locked-case invariance — the three 2B cases stay byte-identical with ext-1 wired.
# ---------------------------------------------------------------------------


def test_ext1_does_not_disturb_locked_2b_cases():
    # On the committed export: DUP_CLAIM degraded (NumAtCard 0%), NO_GST_REG full,
    # SEQ_GAP full. These dicts must be byte-identical to their pre-ext-1 values.
    by = _by_check(ExtractChainReader(EXPORT_FIXTURE_DIR).coverage_status())
    assert by["DUP_CLAIM"].as_dict() == {
        "check": "DUP_CLAIM",
        "level": "degraded",
        "reason": "NumAtCard absent or unpopulated — DUP_CLAIM under-detects.",
    }
    assert by["NO_GST_REG"].as_dict() == {
        "check": "NO_GST_REG",
        "level": "full",
        "reason": "",
    }
    assert by["SEQ_GAP"].as_dict() == {
        "check": "SEQ_GAP",
        "level": "full",
        "reason": "",
    }


def test_ext1_locked_cases_first_three_in_order(tmp_path):
    # The three locked cases keep their leading order; E1–E4 are appended after.
    checks = [s.check for s in _statuses(_export_to(tmp_path))]
    assert checks[:3] == ["DUP_CLAIM", "NO_GST_REG", "SEQ_GAP"]
    assert checks[3:] == ["E1", "E2", "E3", "E4"]


# ---------------------------------------------------------------------------
# End-to-end — run_chain over the committed export surfaces E1–E4 via the
# duck-typed coverage path (NOT the render — that is 2C).
# ---------------------------------------------------------------------------


def test_ext1_full_chain_emits_e_checks(monkeypatch):
    from config.loader import load_client_config

    replay_shim.install_replay_patches(monkeypatch, FROZEN_DIR)
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    period = replay_shim.period_from_manifest(FROZEN_DIR)
    reader = ExtractChainReader(EXPORT_FIXTURE_DIR)

    compile_output, _gate = run_chain(cfg, period, reader=reader)

    assert "check_coverage" in compile_output
    by = {s["check"]: s for s in compile_output["check_coverage"]}
    for check in ("E1", "E2", "E3", "E4"):
        assert by[check]["level"] == "full"
    # locked cases unchanged through the chain too
    assert by["DUP_CLAIM"]["level"] == "degraded"
    assert by["NO_GST_REG"]["level"] == "full"
    assert by["SEQ_GAP"]["level"] == "full"
