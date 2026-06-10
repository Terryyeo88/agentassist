"""
tests/conftest.py — Session-scoped env-var stubs for hermetic test imports.

Some scripts (e.g. scripts/run_baseline_tests.py) call load_client_config()
at module level.  load_client_config() requires SAP credential env vars to be
set; without them the import fails.  Setting dummy values here lets test
modules import those scripts without a live SAP connection — no actual SAP
call is made because the scripts are imported for their constants, not run.
"""
import importlib.util
import os
from pathlib import Path

import pytest


def pytest_configure(config):
    os.environ.setdefault("SAP_USERNAME", "_test_stub_no_sap_")
    os.environ.setdefault("SAP_PASSWORD", "_test_stub_no_sap_")
    os.environ.setdefault("CLIENT_ID", "sbodemosg")


@pytest.fixture(scope="session", autouse=True)
def _provision_invoice_fixtures():
    """Generate PDF fixtures if absent (gitignored by *.pdf, not committed)."""
    docs_dir = Path(__file__).parent / "fixtures" / "documents"
    if not list(docs_dir.glob("INV-*.pdf")):
        generator = docs_dir / "generate_invoices.py"
        spec = importlib.util.spec_from_file_location("generate_invoices", generator)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.generate(docs_dir)
