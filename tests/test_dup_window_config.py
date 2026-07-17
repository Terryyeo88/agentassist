"""
tests/test_dup_window_config.py — FAILING-FIRST loader tests for the NEW
dup_window_* ClientConfig fields (DUP_WINDOW surfacer).

ClientConfig does NOT yet carry ``dup_window_enabled`` / ``dup_window_days`` and
load_client_config does NOT yet validate them. Every test here is RED for the RIGHT
REASON today: the default tests fail with AttributeError (no such field), and the
fail-loud tests fail because no ConfigError is raised (the keys are silently ignored).

Harness + idiom mirror tests/test_config_scheme_flags.py (the existing scheme_flags
loader-validation pattern): a tmp_path YAML written from a minimal base config, loaded
via load_client_config(check_connectivity=False, config_dir=tmp_path).

The contract these tests pin:

  - Absent keys, or explicit YAML null, -> the DEFAULTS (disabled, days None), and
    loading still SUCCEEDS. Every existing client YAML lacks these keys; they must
    keep loading unchanged.
  - dup_window_enabled must be a real bool (the quoted-"yes" truthy-string surprise
    is rejected), same isinstance(bool) guard as show_ai_candidates / scheme_flags.
  - Enabled WITHOUT a window -> ConfigError. FAIL LOUD: a guessed default window
    would be a fabricated threshold silently deciding which pairs a reviewer sees.
    There is no worksheet-derived value to fall back on.
  - Enabled with a non-int window (float / str / bool) -> ConfigError.
  - Enabled with a window < 1 -> ConfigError. A 0-day window is a silently-dead
    check (day-0 belongs to DUP_SAME_DAY, so a 0 window can never fire); it must
    fail at load, not read as "on" while surfacing nothing forever.
  - DISABLED with days set -> loads fine. days is INERT when disabled; failing here
    would punish a config that has merely parked a value.

No test asserts that any window VALUE is correct — days 1 and 7 below are boundary
and arbitrary inputs respectively, not validated truth. The worksheet that would
derive a blessed window does not exist yet.
"""
from __future__ import annotations

import pytest
import yaml

from config.loader import ConfigError, load_client_config

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


def _write_config(tmp_path, **overrides) -> None:
    config = {**_BASE_CONFIG, **overrides}
    (tmp_path / "testclient.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def _load(tmp_path):
    return load_client_config("testclient", check_connectivity=False, config_dir=tmp_path)


# ---------------------------------------------------------------------------
# Defaults — absent / null keys load fine and leave the check OFF
# ---------------------------------------------------------------------------

class TestDefaults:

    def test_absent_keys_default_to_disabled(self, tmp_path):
        _write_config(tmp_path)  # neither key present at all
        cfg = _load(tmp_path)
        assert cfg.dup_window_enabled is False
        assert cfg.dup_window_days is None

    def test_explicit_yaml_null_defaults_to_disabled(self, tmp_path):
        _write_config(tmp_path, dup_window_enabled=None, dup_window_days=None)
        cfg = _load(tmp_path)
        assert cfg.dup_window_enabled is False
        assert cfg.dup_window_days is None

    def test_explicit_false_loads_disabled(self, tmp_path):
        _write_config(tmp_path, dup_window_enabled=False)
        cfg = _load(tmp_path)
        assert cfg.dup_window_enabled is False
        assert cfg.dup_window_days is None

    def test_existing_demo_client_loads_with_check_off(self):
        # The committed demo config declares neither key — existing clients are
        # unaffected, and the OFF default is what keeps the replay oracle frozen.
        cfg = load_client_config("sbodemosg", check_connectivity=False)
        assert cfg.dup_window_enabled is False
        assert cfg.dup_window_days is None


# ---------------------------------------------------------------------------
# dup_window_enabled must be a real bool
# ---------------------------------------------------------------------------

class TestEnabledTypeValidation:

    def test_enabled_quoted_string_raises(self, tmp_path):
        # A quoted YAML string survives safe_load as a str, not a bool — exactly the
        # truthy-string surprise the isinstance(bool) guard must reject.
        _write_config(tmp_path, dup_window_enabled="yes", dup_window_days=7)
        with pytest.raises(ConfigError) as exc_info:
            _load(tmp_path)
        assert "dup_window_enabled" in str(exc_info.value)

    @pytest.mark.parametrize("bad", [1, 0, 7.0, [], {}])
    def test_enabled_non_bool_raises(self, tmp_path, bad):
        # 1/0 are truthy/falsy ints, not bools — also rejected.
        _write_config(tmp_path, dup_window_enabled=bad, dup_window_days=7)
        with pytest.raises(ConfigError):
            _load(tmp_path)


# ---------------------------------------------------------------------------
# Enabled WITHOUT a usable window -> fail loud, never a guessed default
# ---------------------------------------------------------------------------

class TestEnabledRequiresWindow:

    def test_enabled_with_days_absent_raises(self, tmp_path):
        # No silent fallback window: the value must be declared, because no
        # worksheet-derived default exists to fall back on.
        _write_config(tmp_path, dup_window_enabled=True)
        with pytest.raises(ConfigError) as exc_info:
            _load(tmp_path)
        assert "dup_window_days" in str(exc_info.value)

    def test_enabled_with_days_null_raises(self, tmp_path):
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days=None)
        with pytest.raises(ConfigError) as exc_info:
            _load(tmp_path)
        assert "dup_window_days" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Enabled with a non-int window -> fail loud
# ---------------------------------------------------------------------------

class TestWindowTypeValidation:

    def test_enabled_with_float_days_raises(self, tmp_path):
        # 7.0 is not an int. "Close enough" coercion is how a 7.5-day window
        # silently becomes something nobody chose.
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days=7.0)
        with pytest.raises(ConfigError) as exc_info:
            _load(tmp_path)
        assert "dup_window_days" in str(exc_info.value)

    def test_enabled_with_string_days_raises(self, tmp_path):
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days="7")
        with pytest.raises(ConfigError):
            _load(tmp_path)

    def test_enabled_with_bool_days_raises(self, tmp_path):
        # bool is an int SUBCLASS: a bare isinstance(days, int) would let True
        # through as a 1-day window. It must be rejected explicitly.
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days=True)
        with pytest.raises(ConfigError):
            _load(tmp_path)

    @pytest.mark.parametrize("bad", [[7], {"days": 7}])
    def test_enabled_with_structured_days_raises(self, tmp_path, bad):
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days=bad)
        with pytest.raises(ConfigError):
            _load(tmp_path)


# ---------------------------------------------------------------------------
# Enabled with a window < 1 -> fail loud (a 0 window is a silently-dead check)
# ---------------------------------------------------------------------------

class TestWindowRangeValidation:

    def test_enabled_with_zero_days_raises(self, tmp_path):
        # delta 0 is DUP_SAME_DAY's exclusively, so a 0-day window can NEVER fire.
        # Loading it would leave a check that reads as "on" and surfaces nothing.
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days=0)
        with pytest.raises(ConfigError) as exc_info:
            _load(tmp_path)
        assert "dup_window_days" in str(exc_info.value)

    def test_enabled_with_negative_days_raises(self, tmp_path):
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days=-1)
        with pytest.raises(ConfigError):
            _load(tmp_path)


# ---------------------------------------------------------------------------
# Valid enabled configs load (window values here are ARBITRARY inputs, not truth)
# ---------------------------------------------------------------------------

class TestValidEnabledConfigs:

    def test_enabled_with_days_one_loads(self, tmp_path):
        # The lower boundary of the valid range — 1 is the smallest window that
        # can fire. This asserts 1 is ACCEPTED, not that 1 is the right window.
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days=1)
        cfg = _load(tmp_path)
        assert cfg.dup_window_enabled is True
        assert cfg.dup_window_days == 1

    def test_enabled_with_days_seven_loads(self, tmp_path):
        # 7 is an arbitrary caller-chosen value used to prove a plain int loads.
        # NOTHING here claims 7 is the correct or validated window.
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days=7)
        cfg = _load(tmp_path)
        assert cfg.dup_window_enabled is True
        assert cfg.dup_window_days == 7

    def test_enabled_with_large_days_loads(self, tmp_path):
        # No upper bound is pinned — the loader validates TYPE and >= 1 only, since
        # no worksheet exists to justify a ceiling.
        _write_config(tmp_path, dup_window_enabled=True, dup_window_days=90)
        cfg = _load(tmp_path)
        assert cfg.dup_window_days == 90


# ---------------------------------------------------------------------------
# Disabled + days set -> inert, loads fine (do NOT fail loud here)
# ---------------------------------------------------------------------------

class TestDisabledWithDaysIsInert:

    def test_disabled_with_days_set_loads_fine(self, tmp_path):
        # A parked window on a disabled check is not an error. The days value is
        # preserved but inert; only dup_window_enabled decides whether it runs.
        _write_config(tmp_path, dup_window_enabled=False, dup_window_days=7)
        cfg = _load(tmp_path)
        assert cfg.dup_window_enabled is False
        assert cfg.dup_window_days == 7

    def test_disabled_with_invalid_days_still_loads(self, tmp_path):
        # The range/type checks are gated on ENABLED. A disabled check with a
        # nonsense window is inert, not a load failure.
        _write_config(tmp_path, dup_window_enabled=False, dup_window_days=0)
        cfg = _load(tmp_path)
        assert cfg.dup_window_enabled is False

    def test_days_absent_and_disabled_loads_fine(self, tmp_path):
        _write_config(tmp_path, dup_window_enabled=False)
        cfg = _load(tmp_path)
        assert cfg.dup_window_enabled is False
        assert cfg.dup_window_days is None
