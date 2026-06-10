"""
tests/conftest.py — Session-scoped env-var stubs for hermetic test imports.

Some scripts (e.g. scripts/run_baseline_tests.py) call load_client_config()
at module level.  load_client_config() requires SAP credential env vars to be
set; without them the import fails.  Setting dummy values here lets test
modules import those scripts without a live SAP connection — no actual SAP
call is made because the scripts are imported for their constants, not run.
"""
import os


def pytest_configure(config):
    os.environ.setdefault("SAP_USERNAME", "_test_stub_no_sap_")
    os.environ.setdefault("SAP_PASSWORD", "_test_stub_no_sap_")
    os.environ.setdefault("CLIENT_ID", "sbodemosg")
