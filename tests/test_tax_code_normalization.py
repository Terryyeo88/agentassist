"""
tests/test_tax_code_normalization.py — non-SAP-B1 tax code normalization layer.

Covers:
  - normalize_vat_group() passthrough / mapping / case-insensitivity
    (mcp-servers/custom/sap_b1_server.py)
  - tax_code_mappings validation and key normalization
    (config/loader.py)
  - tax_code_mappings / source_system inclusion in the audit bundle
    config allow-list (audit_bundle/config_redaction.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402
from sap_b1_server import normalize_vat_group  # noqa: E402

import audit_bundle.seal as _seal_mod  # noqa: E402
from audit_bundle import seal_bundle  # noqa: E402
from audit_bundle.config_redaction import _ALLOW_LIST, _DENY_ALWAYS  # noqa: E402
from audit_bundle.verify import verify_bundle  # noqa: E402
from config.loader import _STANDARD_VAT_GROUPS, load_client_config  # noqa: E402

_CHAIN_RUN_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "chain-run-sample.json"
_NORMALIZATION_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "chain-run-normalization-sample.json"
)


# ---------------------------------------------------------------------------
# normalize_vat_group()
# ---------------------------------------------------------------------------

def test_passthrough_when_no_mappings():
    assert normalize_vat_group("SO", {}) == "SO"


def test_maps_known_code():
    assert normalize_vat_group("OUTPUT", {"OUTPUT": "SO"}) == "SO"


def test_unknown_code_passthrough():
    assert normalize_vat_group("WEIRDCODE", {"OUTPUT": "SO"}) == "WEIRDCODE"


def test_case_insensitive():
    assert normalize_vat_group("output", {"OUTPUT": "SO"}) == "SO"


def test_non_sap_code_passthrough_when_no_mappings():
    # Empty mappings means "no translation configured" — even a recognisable
    # source-system code (not just canonical ones) must pass through untouched.
    assert normalize_vat_group("OUTPUT", {}) == "OUTPUT"


def test_maps_known_xero_code():
    mappings = {"OUTPUT": "SO", "INPUT": "SI", "ZERORATEDSUPPLIES": "ZR"}
    assert normalize_vat_group("OUTPUT", mappings) == "SO"
    assert normalize_vat_group("INPUT", mappings) == "SI"
    assert normalize_vat_group("ZERORATEDSUPPLIES", mappings) == "ZR"


def test_unknown_code_passes_through_to_anomalies():
    # A code with no entry in mappings is returned unchanged — the caller's
    # F5_BOX_MAPPING.get(vg) lookup will then miss and route it to anomalies.
    mappings = {"OUTPUT": "SO"}
    assert normalize_vat_group("WEIRDCODE", mappings) == "WEIRDCODE"


def test_case_insensitive_lookup(tmp_path):
    # Mappings as produced by load_client_config() have uppercase keys; the
    # raw_code itself may arrive in any case from the source system.
    _write_config(tmp_path, tax_code_mappings={"output": "SO"})
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert normalize_vat_group("output", cfg.tax_code_mappings) == "SO"
    assert normalize_vat_group("Output", cfg.tax_code_mappings) == "SO"
    assert normalize_vat_group("OUTPUT", cfg.tax_code_mappings) == "SO"


def test_canonical_code_passthrough():
    # A partially-migrated SAP B1 client may map a canonical code to itself.
    # Must return the same code, not double-map or loop.
    assert normalize_vat_group("SO", {"SO": "SO"}) == "SO"


# ---------------------------------------------------------------------------
# config/loader.py — tax_code_mappings validation
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "client_id": "testclient",
    "client_name": "Test Client",
    "applicable_gst_rate": 0.09,
    "sap_b1": {
        "service_layer_url": "https://fake",
        "company_db": "TESTDB",
        "username_env_var": "SAP_USERNAME",
        "password_env_var": "SAP_PASSWORD",
        "ssl_verify": False,
    },
}


def _write_config(tmp_path: Path, **overrides) -> None:
    config = {**_BASE_CONFIG, **overrides}
    (tmp_path / "testclient.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def test_load_client_config_validates_bad_target(tmp_path):
    _write_config(tmp_path, tax_code_mappings={"OUTPUT": "BADCODE"})
    with pytest.raises(ValueError):
        load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)


def test_load_client_config_normalizes_keys_to_uppercase(tmp_path):
    _write_config(tmp_path, tax_code_mappings={"output": "SO", "Input": "SI"})
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert cfg.tax_code_mappings == {"OUTPUT": "SO", "INPUT": "SI"}


def test_valid_mapping_loads_cleanly(tmp_path):
    _write_config(tmp_path, tax_code_mappings={"OUTPUT": "SO", "INPUT": "SI"})
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert cfg.tax_code_mappings == {"OUTPUT": "SO", "INPUT": "SI"}


def test_invalid_target_code_raises(tmp_path):
    _write_config(tmp_path, tax_code_mappings={"X": "NOTACODE"})
    with pytest.raises(ValueError) as exc_info:
        load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert "NOTACODE" in str(exc_info.value)


def test_keys_normalized_to_uppercase(tmp_path):
    _write_config(tmp_path, tax_code_mappings={"output": "SO", "Input": "SI"})
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert cfg.tax_code_mappings == {"OUTPUT": "SO", "INPUT": "SI"}


def test_absent_mapping_block_gives_empty_dict(tmp_path):
    _write_config(tmp_path)  # no tax_code_mappings key at all
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert cfg.tax_code_mappings == {}


def test_source_system_defaults_to_sap_b1(tmp_path):
    _write_config(tmp_path)  # no source_system key at all
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert cfg.source_system == "sap_b1"


# ---------------------------------------------------------------------------
# T2.21a — built-in default tax_code_mappings for SAP B1 clients (SO->SR, SI->TX)
#
# SOP step 3 (failing test first). Per exploration-notes/t2.21/live-recon-findings.md
# and the (b') design refinement (built-in-default variant): config/loader.py
# should apply a default tax_code_mappings = {"SO": "SR", "SI": "TX"} for
# source_system == "sap_b1" clients that declare no tax_code_mappings of their
# own — mirroring T2.19's "absent block -> defaults" precedent
# (test_absent_mapping_block_gives_empty_dict above), without requiring any
# per-client YAML edits.
#
# ClientConfig.tax_code_mappings itself must keep reflecting only what the YAML
# declares (empty for sbodemosg today — see test_absent_mapping_block_gives_empty_dict,
# test_sbodemosg_client_has_empty_mappings, test_sbodemosg_bundle_config_passthrough,
# all of which assert == {}). The SAP-B1 default is exposed via a NEW computed
# property, ClientConfig.effective_tax_code_mappings, which does not exist yet —
# every test below fails with AttributeError until it is implemented (next slice).
# ---------------------------------------------------------------------------

def test_sap_b1_client_with_no_mappings_gets_default_effective_mapping():
    # sbodemosg.yaml declares no tax_code_mappings (source_system defaults to
    # "sap_b1") -> effective_tax_code_mappings should be the built-in default.
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    assert cfg.tax_code_mappings == {}  # unchanged T2.19 invariant
    assert cfg.effective_tax_code_mappings == {"SO": "SR", "SI": "TX"}


def test_non_sap_b1_client_does_not_get_sap_b1_default_merged(tmp_path):
    # A Xero client with its own mappings must not pick up the SAP-B1-only
    # SO->SR / SI->TX default — the default is source_system == "sap_b1" scoped.
    _write_config(
        tmp_path,
        source_system="xero",
        tax_code_mappings={"OUTPUT": "SO", "INPUT": "SI"},
    )
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert cfg.source_system == "xero"
    assert cfg.effective_tax_code_mappings == {"OUTPUT": "SO", "INPUT": "SI"}
    assert "SO" not in cfg.effective_tax_code_mappings  # no SAP-B1 default leakage
    assert "SI" not in cfg.effective_tax_code_mappings


def test_sap_b1_client_explicit_mapping_overrides_default_for_that_code(tmp_path):
    # An explicit tax_code_mappings entry for "SO" on a sap_b1 client overrides
    # the built-in SO->SR default, while SI still falls back to the default TX.
    # "ZR" (zero-rated sales) is used as the override target because it is
    # already a canonical code in _STANDARD_VAT_GROUPS — this isolates the
    # override/merge semantics from the separate _STANDARD_VAT_GROUPS "SR"/"TX"
    # question covered below.
    _write_config(tmp_path, tax_code_mappings={"SO": "ZR"})
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert cfg.source_system == "sap_b1"
    assert cfg.tax_code_mappings == {"SO": "ZR"}  # unchanged T2.19 invariant
    assert cfg.effective_tax_code_mappings == {"SO": "ZR", "SI": "TX"}


def test_default_mapping_round_trips_through_f5_box_mapping():
    # The point of the SO->SR / SI->TX rename is that once BOTH halves of (b')
    # land (this default mechanism + the F5_BOX_MAPPING vocabulary rename,
    # a later T2.21 slice), normalize_vat_group() resolves raw SAP B1 codes to
    # canonical SR/TX, and F5_BOX_MAPPING.get() on those canonical codes returns
    # the SAME box routing the old SO/SI entries had.
    #
    # This test hardcodes the target default mapping {"SO": "SR", "SI": "TX"}
    # directly (independent of ClientConfig.effective_tax_code_mappings, which
    # doesn't exist yet) to isolate the SECOND half of the gap: F5_BOX_MAPPING
    # has no "SR"/"TX" keys yet. Expected to fail at the F5_BOX_MAPPING lookups
    # below until the F5_BOX_MAPPING vocabulary rename lands.
    default_mapping = {"SO": "SR", "SI": "TX"}

    assert normalize_vat_group("SO", default_mapping) == "SR"
    assert normalize_vat_group("SI", default_mapping) == "TX"

    sr_mapping = sap_b1_server.F5_BOX_MAPPING.get("SR")
    tx_mapping = sap_b1_server.F5_BOX_MAPPING.get("TX")
    assert sr_mapping is not None, "F5_BOX_MAPPING has no 'SR' key yet (vocabulary rename pending)"
    assert tx_mapping is not None, "F5_BOX_MAPPING has no 'TX' key yet (vocabulary rename pending)"

    # Once the vocabulary rename lands, SR/TX must carry the SAME routing the
    # old SO/SI entries had (numerically-unchanged box totals, per
    # live-recon-findings.md §2).
    assert sr_mapping == {"lt_box": "box_1_standard_rated_sales", "tt_box": "box_6_output_tax", "side": "sales"}
    assert tx_mapping == {"lt_box": "box_5_taxable_purchases", "tt_box": "box_7_input_tax", "side": "purchase"}


# ---------------------------------------------------------------------------
# T2.21a — _STANDARD_VAT_GROUPS gap (scope-confirmation flag, see report)
#
# Characterization tests: confirm that _STANDARD_VAT_GROUPS (config/loader.py)
# does not yet contain "SR"/"TX". This documents a constraint on HOW the
# built-in default must be implemented: if {"SO": "SR", "SI": "TX"} were merged
# into raw_mappings BEFORE the Step 9 validation loop (which checks every
# mapping target against _STANDARD_VAT_GROUPS), load_client_config() would
# raise ValueError("'SR' is not a canonical AgentAssist VatGroup code") for
# every sap_b1 client — including sbodemosg — as soon as the default is wired
# in. The default must therefore be exposed via a property computed AFTER Step
# 9 (over the already-validated tax_code_mappings), as assumed by the tests
# above — NOT by injecting it into raw_mappings ahead of validation.
#
# These two tests currently PASS (they document today's state); they are not
# part of the "failing tests" deliverable above.
# ---------------------------------------------------------------------------

def test_standard_vat_groups_does_not_yet_include_sr_or_tx():
    assert "SR" not in _STANDARD_VAT_GROUPS
    assert "TX" not in _STANDARD_VAT_GROUPS


def test_explicit_sr_target_currently_rejected_by_loader_validation(tmp_path):
    # If a sap_b1 client's YAML explicitly declared a tax_code_mappings entry
    # targeting "SR" today (e.g. a forward-looking override), Step 9 validation
    # would reject it — the same _STANDARD_VAT_GROUPS gap as above, but via the
    # YAML-declared path rather than the hardcoded default.
    _write_config(tmp_path, tax_code_mappings={"SO": "SR"})
    with pytest.raises(ValueError) as exc_info:
        load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert "SR" in str(exc_info.value)


# ---------------------------------------------------------------------------
# audit_bundle/config_redaction.py — allow-list
# ---------------------------------------------------------------------------

def test_allow_list_includes_tax_code_mappings():
    assert "tax_code_mappings" in _ALLOW_LIST
    assert "tax_code_mappings" not in _DENY_ALWAYS
    assert "source_system" in _ALLOW_LIST
    assert "source_system" not in _DENY_ALWAYS


def test_tax_code_mappings_in_allow_list():
    assert "tax_code_mappings" in _ALLOW_LIST


def test_source_system_in_allow_list():
    assert "source_system" in _ALLOW_LIST


def test_neither_field_in_deny_always():
    assert "tax_code_mappings" not in _DENY_ALWAYS
    assert "source_system" not in _DENY_ALWAYS


def test_allow_list_and_deny_always_still_disjoint():
    # Existing invariant — confirm it still holds after the new fields were added.
    assert _ALLOW_LIST & _DENY_ALWAYS == set()


# ---------------------------------------------------------------------------
# sbodemosg.yaml — SAP B1 clients need no mapping
# ---------------------------------------------------------------------------

def test_sbodemosg_client_has_empty_mappings():
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    assert cfg.tax_code_mappings == {}


# ---------------------------------------------------------------------------
# End-to-end normalization through _classify_line() (still synthetic)
# ---------------------------------------------------------------------------

@pytest.fixture
def configured_mappings():
    """Activate sap_b1_server.configure_client() with a given tax_code_mappings,
    then restore module-level state so other tests are unaffected.

    configure_client() replaces the module-level `sap` client and
    `_tax_code_mappings`; both are pure in-memory state (constructing an
    httpx.Client makes no network call), so this is safe to call repeatedly
    in a test process.
    """
    original_sap = sap_b1_server.sap
    original_mappings = dict(sap_b1_server._tax_code_mappings)

    def _configure(mappings: dict) -> None:
        sap_b1_server.configure_client(
            "https://fake-sap.example/b1s/v2", "TESTDB", "test_user", "test_pass",
            ssl_verify=False, tax_code_mappings=mappings,
        )

    yield _configure

    sap_b1_server.sap = original_sap
    sap_b1_server._tax_code_mappings = original_mappings


def test_xero_output_code_routes_to_box1(configured_mappings):
    configured_mappings({"OUTPUT": "SO"})
    line = {"VatGroup": "OUTPUT", "LineTotal": 1000, "TaxTotal": 90}
    doc = {"DocNum": 101, "DocDate": "2024-07-15", "CardName": "Acme Pte Ltd", "DocCurrency": "SGD"}

    issues = sap_b1_server._classify_line(line, doc, entity_type="sales", expected_rate=0.09)

    # Clean line at the expected 9% rate — normalized to canonical SO,
    # raises no E1-E4 issue (i.e. does not land in anomalies).
    assert issues == []
    assert sap_b1_server.normalize_vat_group("OUTPUT", sap_b1_server._tax_code_mappings) == "SO"
    mapping = sap_b1_server.F5_BOX_MAPPING["SO"]
    assert mapping["lt_box"] == "box_1_standard_rated_sales"
    assert mapping["tt_box"] == "box_6_output_tax"


def test_xero_input_code_detects_e3(configured_mappings):
    configured_mappings({"INPUT": "SI"})
    line = {"VatGroup": "INPUT", "LineTotal": 500, "TaxTotal": 0}
    doc = {"DocNum": 102, "DocDate": "2024-07-16", "CardName": "Vendor Co", "DocCurrency": "SGD"}

    issues = sap_b1_server._classify_line(line, doc, entity_type="purchase", expected_rate=0.09)

    assert len(issues) == 1
    assert issues[0]["error_code"] == "E3"
    # The issue's vat_group is the canonical code, not the raw "INPUT".
    assert issues[0]["vat_group"] == "SI"


def test_unmapped_code_lands_in_anomalies(configured_mappings):
    configured_mappings({})  # SAP B1 client — no mappings configured
    line = {"VatGroup": "CUSTOM_MYSTERY_CODE", "LineTotal": 250, "TaxTotal": 0}
    doc = {"DocNum": 103, "DocDate": "2024-07-17", "CardName": "Mystery Co", "DocCurrency": "SGD"}

    issues = sap_b1_server._classify_line(line, doc, entity_type="sales", expected_rate=0.09)

    # Not a recognised error-triggering code, so _classify_line raises nothing...
    assert issues == []
    # ...but it also has no F5_BOX_MAPPING entry, which is exactly the
    # condition calculate_f5_return uses to route a line into `anomalies`.
    vg = sap_b1_server.normalize_vat_group("CUSTOM_MYSTERY_CODE", sap_b1_server._tax_code_mappings)
    assert vg == "CUSTOM_MYSTERY_CODE"
    assert sap_b1_server.F5_BOX_MAPPING.get(vg) is None


# ---------------------------------------------------------------------------
# Stage 2 — synthetic-fixture integration checks
#
# No live SAP, no run_agent.py, no seed_test_data.py. tests/fixtures/
# chain-run-normalization-sample.json is a copy of chain-run-sample.json
# (used by test_report_e2e.py / test_run_agent_e2e.py) with the SO/SI codes
# in the classify step renamed to Xero-style "OUTPUT"/"INPUT" codes, plus a
# "config" block documenting the tax_code_mappings that produced them.
# ---------------------------------------------------------------------------

def test_xero_fixture_codes_normalize_to_canonical():
    fixture = json.loads(_NORMALIZATION_FIXTURE.read_text(encoding="utf-8"))
    mappings = fixture["config"]["tax_code_mappings"]

    assert fixture["config"]["source_system"] == "xero"
    assert mappings == {"OUTPUT": "SO", "INPUT": "SI"}

    # Raw Xero codes are not recognised by F5_BOX_MAPPING on their own ...
    assert sap_b1_server.F5_BOX_MAPPING.get("OUTPUT") is None
    assert sap_b1_server.F5_BOX_MAPPING.get("INPUT") is None

    # ... but normalize_vat_group() resolves them to canonical codes that are.
    assert normalize_vat_group("OUTPUT", mappings) == "SO"
    assert normalize_vat_group("INPUT", mappings) == "SI"
    assert sap_b1_server.F5_BOX_MAPPING["SO"]["lt_box"] == "box_1_standard_rated_sales"
    assert sap_b1_server.F5_BOX_MAPPING["SI"]["lt_box"] == "box_5_taxable_purchases"


def test_xero_fixture_vatgroup_inventory_uses_xero_codes():
    fixture = json.loads(_NORMALIZATION_FIXTURE.read_text(encoding="utf-8"))
    inventory = fixture["classify"]["vatgroup_inventory"]

    assert "OUTPUT" in inventory
    assert "INPUT" in inventory
    assert "SO" not in inventory
    assert "SI" not in inventory
    assert inventory["OUTPUT"]["lt_box"] == "box_1_standard_rated_sales"
    assert inventory["INPUT"]["lt_box"] == "box_5_taxable_purchases"


# ---------------------------------------------------------------------------
# Stage 2 — sbodemosg passthrough check (static fixture, no live SBODEMOSG)
# ---------------------------------------------------------------------------

def _gate_results() -> dict:
    return {
        "all_passed": True,
        "gates": [
            {
                "gate": i,
                "name": f"gate-{i}",
                "after_step": "step",
                "status": "PASS" if i > 1 else "WARN_PASS",
                "passed": True,
                "checked": {"sap_inline_count": None} if i == 1 else {},
            }
            for i in range(1, 6)
        ],
    }


def test_sbodemosg_bundle_config_passthrough(tmp_path, monkeypatch):
    # Real sbodemosg.yaml has no tax_code_mappings — confirm the loaded config
    # reflects that, then confirm it survives the seal/redact round trip.
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    assert cfg.tax_code_mappings == {}
    assert cfg.source_system == "sap_b1"

    compile_output = json.loads(_CHAIN_RUN_FIXTURE.read_text(encoding="utf-8"))

    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy end-to-end test pdf")

    monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")

    bundle_dir = seal_bundle(
        client_config=cfg,
        period={"start": "2024-07-01", "end": "2024-09-30"},
        compile_output=compile_output,
        gate_results=_gate_results(),
        report_pdf_path=dummy_pdf,
        run_started_at="2026-06-01T09:11:17.649983+00:00",
        run_completed_at="2026-06-01T09:11:28.441921+00:00",
    )

    ok, problems = verify_bundle(bundle_dir)
    assert ok is True, f"verify_bundle failed: {problems}"

    config_json = json.loads((bundle_dir / "config.json").read_text(encoding="utf-8"))
    assert config_json["tax_code_mappings"] == {}
    assert config_json["source_system"] == "sap_b1"
    assert "password" not in config_json
