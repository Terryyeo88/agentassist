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
from config.loader import load_client_config  # noqa: E402

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
