from __future__ import annotations

import json

import pytest

from audit_bundle.canonical import canonical_json
from audit_bundle.config_redaction import redact_config, _ALLOW_LIST, _DENY_ALWAYS
from config.loader import ClientConfig


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _cfg(**overrides) -> ClientConfig:
    defaults = dict(
        client_id="testclient",
        client_name="Test Client Pte Ltd",
        gst_registration_number="M90000001A",
        applicable_gst_rate=0.09,
        service_layer_url="https://10.0.0.1:50000/b1s/v2",
        company_db="TESTDB",
        username="sap_user",
        password="HUNTER2_TEST",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.10,
        reviewer_name="Jane Tan",
        firm_name="Tan & Associates",
    )
    defaults.update(overrides)
    return ClientConfig(**defaults)


# ---------------------------------------------------------------------------
# Credential exclusion
# ---------------------------------------------------------------------------

def test_redact_excludes_password():
    result = redact_config(_cfg())
    assert "password" not in result


def test_redact_excludes_username():
    result = redact_config(_cfg())
    assert "username" not in result


def test_redact_excludes_ssl_verify():
    result = redact_config(_cfg())
    assert "ssl_verify" not in result


def test_redact_password_value_absent_from_canonical_json():
    result = redact_config(_cfg(password="HUNTER2_TEST"))
    serialised = canonical_json(result).decode("utf-8")
    assert "HUNTER2_TEST" not in serialised


def test_redact_username_value_absent_from_canonical_json():
    result = redact_config(_cfg(username="sap_user_secret"))
    serialised = canonical_json(result).decode("utf-8")
    assert "sap_user_secret" not in serialised


def test_redact_no_secret_key_names_in_output():
    result = redact_config(_cfg())
    keys_lower = {k.lower() for k in result}
    forbidden = {"username", "password", "pwd", "secret", "token"}
    assert keys_lower.isdisjoint(forbidden), f"Forbidden keys present: {keys_lower & forbidden}"


# ---------------------------------------------------------------------------
# Allow-list completeness
# ---------------------------------------------------------------------------

def test_redact_includes_client_id():
    assert redact_config(_cfg())["client_id"] == "testclient"


def test_redact_includes_service_layer_url():
    result = redact_config(_cfg())
    assert "service_layer_url" in result
    assert result["service_layer_url"] == "https://10.0.0.1:50000/b1s/v2"


def test_redact_includes_company_db():
    assert redact_config(_cfg())["company_db"] == "TESTDB"


def test_redact_includes_reviewer_name():
    assert redact_config(_cfg())["reviewer_name"] == "Jane Tan"


def test_redact_includes_applicable_gst_rate():
    assert redact_config(_cfg())["applicable_gst_rate"] == 0.09


def test_redact_all_allow_list_fields_present():
    result = redact_config(_cfg())
    for field in _ALLOW_LIST:
        assert field in result, f"Allow-listed field '{field}' missing from redacted config"


# ---------------------------------------------------------------------------
# Deny-list invariant
# ---------------------------------------------------------------------------

def test_deny_always_disjoint_from_allow_list():
    # The allow-list and deny-always sets must be disjoint; overlap would be a
    # logic error that could cause a secret to appear in the bundle.
    overlap = _ALLOW_LIST & _DENY_ALWAYS
    assert not overlap, f"Allow-list and deny-always overlap: {overlap}"


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

def test_redact_returns_dict():
    assert isinstance(redact_config(_cfg()), dict)


def test_redact_result_is_json_serialisable():
    result = redact_config(_cfg())
    # Must not raise
    json.dumps(result)
