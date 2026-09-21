"""
tests/test_unmapped_code_guard.py — Slice D: unmapped tax codes must never silently
reduce an F5 box.

D-2026-09-21-unmapped-codes (PROPOSED). Two defects, one root cause.

#49 — THE EXTRACT PATH UNDERSTATED EVERY BOX. `config/clients/extract_demo.yaml` was cloned
from `xero_demo.yaml`, so it declared Xero LABEL strings ("STANDARD-RATED SUPPLIES") while
its own fixture carries raw SAP codes (SO/SI), and `source_system: extract` blocks the
sap_b1 SO/SI default. 133 of 146 lines were dropped. Box 8 did not merely understate — it
INVERTED, reporting a refund where the truth was a payable. Ruling R-1 fixes the config's
declaration (and its `applicable_gst_rate`, cloned from the same place).

R-2 — THE CLASS BEHIND IT. Fixing one config does not stop the next one silently losing a
box. When ANY line is excluded because its tax code is unrecognised, EVERY value box is
rendered with NO FIGURE and a stated reason, and the derived boxes follow. Ruling Q3
option (a), deliberately blunt: an unmapped code has no F5_BOX_MAPPING entry, so its SIDE
is genuinely unknowable — inferring one from doc_type would be tax semantics by inference,
which the architecture forbids. If the system cannot tell what a code means, it cannot
vouch for ANY box. NO THRESHOLD: one excluded line is enough.

WHAT THIS PROVES AND WHAT IT DOES NOT. It proves the MECHANISM: that the mapping reaches
the boxes, that an exclusion blanks the figures rather than shaving them, and that a clean
run is untouched. It proves NOTHING about accuracy — the corrected figures are asserted
against the frozen SAP oracle COMPUTED AT RUNTIME, never against numbers written here by
hand (Terry hand-pins the literals in a separate commit). T2.11 unmoved.

APPEND-ONLY BOUNDARY: NEW file. No existing test file is modified.

Hermetic: no network, no anthropic, no live SAP/Xero. SAP off, dummy creds only.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

from audit_bundle.canonical import canonical_json  # noqa: E402
from config.loader import load_client_config  # noqa: E402
from feeders.extract_reader import ExtractChainReader  # noqa: E402
from orchestrator.chain import run_chain  # noqa: E402

_FROZEN = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
_ORACLE = _FROZEN / "_replay-oracle.compiled.json"

_VALUE_BOXES = (
    "box_1_standard_rated_sales",
    "box_2_zero_rated_sales",
    "box_3_exempt_sales",
    "box_5_taxable_purchases",
    "box_6_output_tax",
    "box_7_input_tax",
)
_DERIVED_BOXES = ("box_4_total_sales", "box_8_net_gst")


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def synth_xlsx(tmp_path_factory) -> Path:
    """The synthetic extract export, built from the SAME frozen data as the oracle."""
    synth = _load("slice_d_synth", "tests/synth_extract_export.py")
    out = tmp_path_factory.mktemp("slice-d") / "synthetic-extract.xlsx"
    return synth.export_xlsx(_FROZEN, out)


@pytest.fixture(scope="module")
def period() -> dict:
    return _load("slice_d_shim", "tests/replay_shim.py").period_from_manifest(_FROZEN)


@pytest.fixture(scope="module")
def oracle_run(period):
    """The frozen SAP replay — the RUNTIME source of truth for the corrected figures."""
    shim = _load("slice_d_shim2", "tests/replay_shim.py")
    with shim.frozen_extract_sap(_FROZEN) as contact:
        out, gates = run_chain(
            load_client_config("sbodemosg", check_connectivity=False),
            period,
            reader=shim.build_frozen_reader(_FROZEN),
        )
    assert contact == {"login": 0, "request": 0}, "replay touched real SAP"
    return out, gates


def _extract_run(xlsx: Path, period: dict, cfg=None):
    cfg = cfg or load_client_config("extract_demo", check_connectivity=False)
    return run_chain(cfg, period, reader=ExtractChainReader(xlsx))


# ══ D1 — the extract path now agrees with the oracle, box for box ════════════════════


class TestD1MappingReachesTheBoxes:

    def test_every_box_equals_the_oracle_computed_at_runtime(self, synth_xlsx, period, oracle_run):
        """NO hand-written numbers: the expected values are READ from the oracle run in
        this same process, over the same underlying data."""
        oracle_boxes = oracle_run[0]["calculate"]["boxes"]
        out, _ = _extract_run(synth_xlsx, period)
        for box, expected in oracle_boxes.items():
            assert out["calculate"]["boxes"][box] == pytest.approx(expected, abs=0.005), box

    def test_box_8_is_a_payable_not_a_refund(self, synth_xlsx, period, oracle_run):
        """The defect's sharpest edge, pinned by SIGN rather than by magnitude: the
        extract path reported a refund where the data says payable."""
        out, _ = _extract_run(synth_xlsx, period)
        oracle_net = oracle_run[0]["calculate"]["boxes"]["box_8_net_gst"]
        got = out["calculate"]["boxes"]["box_8_net_gst"]
        assert (got > 0) == (oracle_net > 0)
        assert got == pytest.approx(oracle_net, abs=0.005)

    def test_extract_config_declares_the_vocabulary_of_its_own_file(self):
        """R-1 lives in the CONFIG, not in the reader and not by ungating the SAP default."""
        cfg = load_client_config("extract_demo", check_connectivity=False)
        assert cfg.source_system == "extract"
        assert cfg.tax_code_mappings.get("SO") == "SR"
        assert cfg.tax_code_mappings.get("SI") == "TX"

    def test_the_sap_default_stays_gated_exactly_as_before(self):
        """The fix must NOT be 'ungate the default'. A non-sap_b1 source still gets only
        what it declares; sap_b1 still gets the default merged."""
        from config.loader import _SAP_B1_DEFAULT_TAX_CODE_MAPPINGS

        assert _SAP_B1_DEFAULT_TAX_CODE_MAPPINGS == {"SO": "SR", "SI": "TX"}
        sap = load_client_config("sbodemosg", check_connectivity=False)
        assert sap.effective_tax_code_mappings["SO"] == "SR"
        assert not sap.tax_code_mappings, "sbodemosg must keep declaring nothing"

    def test_expected_rate_matches_the_data_this_client_supplies(self, synth_xlsx, period):
        """The rate came from the same clone as the mappings. Left at 0.09 against 7%-era
        data it manufactures a rate-deviation finding on essentially every mapped line —
        noise that would bury the real ones."""
        cfg = load_client_config("extract_demo", check_connectivity=False)
        assert cfg.applicable_gst_rate == pytest.approx(0.07)


class TestD2Anomalies:

    def test_so_and_si_no_longer_become_anomalies(self, synth_xlsx, period):
        out, _ = _extract_run(synth_xlsx, period)
        assert out["calculate"]["anomalies"] == []
        assert out["deduplicated_anomalies"] == []

    def test_a_genuinely_unknown_code_still_becomes_an_anomaly(self, synth_xlsx, period):
        """The fix must not blunt the detector: an unrecognised code is still caught."""
        cfg = load_client_config("extract_demo", check_connectivity=False)
        crippled = dataclasses.replace(
            cfg, tax_code_mappings={k: v for k, v in cfg.tax_code_mappings.items() if k != "SO"}
        )
        out, _ = _extract_run(synth_xlsx, period, cfg=crippled)
        assert any("SO" in a["issue"] for a in out["deduplicated_anomalies"])

    def test_the_findings_match_the_oracle_too(self, synth_xlsx, period, oracle_run):
        """Not just the boxes: once the codes are mapped the extract path surfaces the
        SAME findings as the SAP oracle over the same data."""
        import collections

        def codes(out):
            return collections.Counter(i["error_code"] for i in out["detect"]["issues"])

        out, _ = _extract_run(synth_xlsx, period)
        assert codes(out) == codes(oracle_run[0])


# ══ D3 — the guard, on a synthetic case independent of #49 ═══════════════════════════


class TestD3TheGuard:

    @pytest.fixture(scope="class")
    def excluded_run(self, synth_xlsx, period):
        """extract_demo with SO deliberately unmapped: a complete mapping minus one code."""
        cfg = load_client_config("extract_demo", check_connectivity=False)
        without_so = dataclasses.replace(
            cfg, tax_code_mappings={k: v for k, v in cfg.tax_code_mappings.items() if k != "SO"}
        )
        out, _ = _extract_run(synth_xlsx, period, cfg=without_so)
        return out

    def test_compile_output_carries_a_box_completeness_record(self, excluded_run):
        bc = excluded_run.get("box_completeness")
        assert bc is not None, "an exclusion must be recorded as DATA, not only as prose"
        assert bc["status"] == "incomplete"

    def test_it_names_the_code_with_line_count_and_total_value(self, excluded_run):
        """R-2: the anomaly record alone could not satisfy this — it carried only
        {doc_num, issue}. The count and the value are what let a reviewer judge scale."""
        codes = {c["code"]: c for c in excluded_run["box_completeness"]["excluded_codes"]}
        assert "SO" in codes
        assert codes["SO"]["line_count"] > 0
        assert codes["SO"]["net_total"] != 0.0
        assert "tax_total" in codes["SO"]

    def test_every_value_box_is_blanked_and_the_derived_boxes_follow(self, excluded_run):
        """Q3 option (a): an unmapped code's SIDE is unknowable, so no box is vouched for."""
        blanked = set(excluded_run["box_completeness"]["blanked_boxes"])
        assert set(_VALUE_BOXES) <= blanked
        assert set(_DERIVED_BOXES) <= blanked

    def test_the_raw_figures_survive_in_the_sealed_record(self, excluded_run):
        """The paper GLOSSES the seal, never contradicts it: calculate.boxes still carries
        the raw computed figures, however incomplete."""
        assert excluded_run["calculate"]["boxes"]["box_5_taxable_purchases"] is not None
        assert isinstance(excluded_run["calculate"]["boxes"]["box_1_standard_rated_sales"], float)

    def test_a_finding_is_surfaced_in_candidate_framing(self, excluded_run):
        issues = [i for i in excluded_run["detect"]["issues"] if i["error_code"] == "UNMAPPED_TAX_CODE"]
        assert issues, "an exclusion must reach the reviewer as a finding"
        text = " ".join(i["description"] + " " + i["recommendation"] for i in issues)
        assert "SO" in text
        # Candidate framing, never a verdict: the code may be perfectly legitimate.
        assert "may be" in text.lower() or "candidate" in text.lower()
        for word in ("must", "illegal", "wrong", "error in your"):
            assert word not in text.lower().replace("unrecognised", "")

    def test_no_partial_figure_reaches_the_report_section(self, excluded_run):
        """The load-bearing half of R-2: a partial Box 5 is MORE dangerous than a blank
        one, because a reviewer can act on a number."""
        from report.sections import build_f5_box_section

        section = build_f5_box_section(excluded_run)
        for row in section.attribution:
            if row.box_name in _VALUE_BOXES + _DERIVED_BOXES:
                assert row.status == "incomplete", row.box_name
                assert row.exclusion_reason, row.box_name
                assert "SO" in row.exclusion_reason

    def test_no_threshold_one_excluded_line_is_enough(self, synth_xlsx, period):
        """Explicitly pinned so nobody later adds a materiality percentage."""
        cfg = load_client_config("extract_demo", check_connectivity=False)
        without_nr = dataclasses.replace(
            cfg, tax_code_mappings={k: v for k, v in cfg.tax_code_mappings.items()}
        )
        # NR appears on exactly ONE line in the frozen data.
        out, _ = _extract_run(synth_xlsx, period, cfg=_drop_canonical(without_nr, "NR"))
        bc = out.get("box_completeness")
        assert bc is not None and bc["status"] == "incomplete"
        nr = {c["code"]: c for c in bc["excluded_codes"]}.get("NR")
        assert nr is not None and nr["line_count"] == 1


def _drop_canonical(cfg, code: str):
    """Force a CANONICAL code to be unrecognised, via the CONFIG alone.

    A canonical code cannot be un-declared (it is canonical by definition and lives in
    F5_BOX_MAPPING), so the config maps it to a target that no box recognises. This
    exercises the guard through the same door a real mis-declaration would come through —
    no monkeypatching of the mapping table, no test-only branch in product code.
    """
    return dataclasses.replace(
        cfg, tax_code_mappings={**cfg.tax_code_mappings, code: "ZZ_UNRECOGNISED"}
    )


# ══ D5 — clean runs are unchanged ════════════════════════════════════════════════════


class TestD5CleanRunsUnchanged:

    def test_clean_extract_run_emits_no_completeness_key(self, synth_xlsx, period):
        """Absent-when-clean is what keeps the oracle byte-identical (Invariant 4)."""
        out, _ = _extract_run(synth_xlsx, period)
        assert "box_completeness" not in out

    def test_clean_run_has_no_unmapped_finding(self, synth_xlsx, period):
        out, _ = _extract_run(synth_xlsx, period)
        assert not [i for i in out["detect"]["issues"] if i["error_code"] == "UNMAPPED_TAX_CODE"]

    def test_every_box_renders_a_figure_on_a_clean_run(self, synth_xlsx, period):
        from report.sections import build_f5_box_section

        out, _ = _extract_run(synth_xlsx, period)
        section = build_f5_box_section(out)
        assert all(row.status != "incomplete" for row in section.attribution)


# ══ D7 — the SAP path is untouched, and the oracle needs no re-freeze ════════════════


class TestD7SapByteIdentity:

    def test_offline_replay_is_byte_identical_to_the_committed_oracle(self, period, oracle_run):
        out, gates = oracle_run
        blob = canonical_json({"period": period, "compile_output": out, "gate_results": gates})
        assert blob == _ORACLE.read_bytes(), "the oracle moved — a re-freeze is NOT allowed"

    def test_the_replay_carries_no_new_keys(self, oracle_run):
        """A clean run must not gain box_completeness — that is the conditional emission
        the byte-identity above depends on."""
        assert "box_completeness" not in oracle_run[0]
