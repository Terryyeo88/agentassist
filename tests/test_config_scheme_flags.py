"""
tests/test_config_scheme_flags.py — T2.18 ClientConfig scheme-status flags.

Config infrastructure only — NO check logic. Covers the four flat top-level
boolean scheme-status fields promoted/added in T2.18:

    actively_makes_exempt_supplies   (promoted from a getattr-default read)
    participates_in_mes              (Major Exporter Scheme)
    participates_in_igds             (Import GST Deferment Scheme)
    reverse_charge_applicable        (imported services + LVG, registered customer)

All four are bool, default False. These tests assert the four-place contract:
  - loader read + validation (present true/false, invalid non-bool -> ConfigError);
  - backward-compat (existing YAML lacking the keys loads with all four False);
  - audit-bundle allow-list (all four survive redaction, including when False).

The Template-4 routing activation on the real (promoted) field is asserted in
tests/test_report_e2e.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from audit_bundle.config_redaction import _ALLOW_LIST, _DENY_ALWAYS, redact_config
from config.loader import ConfigError, load_client_config

# The four scheme-status flags, as a single source of truth for parametrization.
# This tuple IS the contract T5.2c config_keys and the downstream D+ checks bind
# to — keep the names verbatim.
SCHEME_FLAGS = (
    "actively_makes_exempt_supplies",
    "participates_in_mes",
    "participates_in_igds",
    "reverse_charge_applicable",
)

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


# ---------------------------------------------------------------------------
# Loader read — present true / present false
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", SCHEME_FLAGS)
def test_flag_present_true(tmp_path, flag):
    _write_config(tmp_path, **{flag: True})
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert getattr(cfg, flag) is True


@pytest.mark.parametrize("flag", SCHEME_FLAGS)
def test_flag_present_false(tmp_path, flag):
    _write_config(tmp_path, **{flag: False})
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert getattr(cfg, flag) is False


# ---------------------------------------------------------------------------
# Loader validation — non-bool value must fail loud (show_ai_candidates pattern)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", SCHEME_FLAGS)
def test_flag_invalid_type_raises(tmp_path, flag):
    # A quoted YAML string survives safe_load as a str, not a bool — exactly the
    # "truthy-string surprise" the isinstance(bool) guard must reject.
    _write_config(tmp_path, **{flag: "yes"})
    with pytest.raises(ConfigError) as exc_info:
        load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert flag in str(exc_info.value)


@pytest.mark.parametrize("flag", SCHEME_FLAGS)
def test_flag_invalid_int_raises(tmp_path, flag):
    # 1/0 are truthy/falsy ints, not bools — also rejected.
    _write_config(tmp_path, **{flag: 1})
    with pytest.raises(ConfigError):
        load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)


# ---------------------------------------------------------------------------
# Backward-compat — existing YAML lacking the keys loads with all four False
# ---------------------------------------------------------------------------

def test_absent_keys_all_default_false(tmp_path):
    _write_config(tmp_path)  # none of the four flags present at all
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    for flag in SCHEME_FLAGS:
        assert getattr(cfg, flag) is False, f"{flag} should default False when absent"


@pytest.mark.parametrize("flag", SCHEME_FLAGS)
def test_explicit_null_defaults_false(tmp_path, flag):
    # Explicit YAML null (key present, value None) must also default OFF.
    _write_config(tmp_path, **{flag: None})
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    assert getattr(cfg, flag) is False


def test_sbodemosg_loads_with_scheme_flags_false():
    # The committed demo config declares none of the flags — existing clients
    # are unaffected (every flag OFF == pre-T2.18 behaviour).
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    for flag in SCHEME_FLAGS:
        assert getattr(cfg, flag) is False


def test_example_yaml_loads_with_scheme_flags_false(tmp_path):
    # example.yaml documents the four flags as the onboarding schema template;
    # the documented defaults must all be False and the file must load cleanly.
    example = Path(__file__).resolve().parent.parent / "config" / "clients" / "example.yaml"
    raw = yaml.safe_load(example.read_text(encoding="utf-8"))
    raw["client_id"] = "testclient"  # load_client_config checks stem == client_id
    (tmp_path / "testclient.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    for flag in SCHEME_FLAGS:
        assert getattr(cfg, flag) is False


# ---------------------------------------------------------------------------
# Audit-bundle allow-list — Terry's explicit ask: FAIL if any of the four is
# missing from the sealed config.json output of redact_config (incl. when False)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", SCHEME_FLAGS)
def test_scheme_flag_in_allow_list(flag):
    assert flag in _ALLOW_LIST, f"{flag} must be allow-listed for the sealed bundle"
    assert flag not in _DENY_ALWAYS


def test_all_four_flags_present_in_redacted_config_when_false():
    cfg = load_client_config("sbodemosg", check_connectivity=False)  # all flags False
    redacted = redact_config(cfg)
    for flag in SCHEME_FLAGS:
        assert flag in redacted, f"{flag} missing from sealed config.json"
        assert redacted[flag] is False


def test_all_four_flags_present_in_redacted_config_when_true(tmp_path):
    _write_config(tmp_path, **{flag: True for flag in SCHEME_FLAGS})
    cfg = load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)
    redacted = redact_config(cfg)
    for flag in SCHEME_FLAGS:
        assert redacted[flag] is True
