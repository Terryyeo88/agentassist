"""Loader validation for the xero_sales out_of_scope_codes key (Step 11).

Completes the three-times coverage for the DISJOINT rule (out_of_scope_codes must not overlap
tax_code_mappings keys): prompt/docstring + code (config/loader.py Step 11) + THIS test. New
file (append-only boundary honoured).

Pure stdlib + pytest. No anthropic.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from config.loader import ConfigError, load_client_config


def _write_cfg(dir_path: Path, stem: str, body: str) -> None:
    (dir_path / f"{stem}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


def test_out_of_scope_overlap_with_mapping_keys_is_rejected(tmp_path):
    """A code listed in BOTH tax_code_mappings and out_of_scope_codes fails loud (ConfigError)."""
    _write_cfg(
        tmp_path,
        "xero_sales_overlap",
        """
        client_id: xero_sales_overlap
        client_name: "Overlap Reject"
        applicable_gst_rate: 0.09
        source_system: xero_sales
        tax_code_mappings:
          "NO TAX": SR
        out_of_scope_codes:
          - "No Tax"
        """,
    )
    with pytest.raises(ConfigError, match="out_of_scope_codes"):
        load_client_config("xero_sales_overlap", check_connectivity=False, config_dir=tmp_path)


def test_out_of_scope_codes_are_uppercased_and_optional(tmp_path):
    """out_of_scope_codes is optional; when present it is uppercased (case-insensitive match)."""
    _write_cfg(
        tmp_path,
        "xero_sales_oos",
        """
        client_id: xero_sales_oos
        client_name: "OOS Uppercase"
        applicable_gst_rate: 0.09
        source_system: xero_sales
        tax_code_mappings:
          "STANDARD-RATED SUPPLIES": SR
        out_of_scope_codes:
          - "No Tax"
          - "Bad Debt Relief"
        """,
    )
    cfg = load_client_config("xero_sales_oos", check_connectivity=False, config_dir=tmp_path)
    assert cfg.out_of_scope_codes == frozenset({"NO TAX", "BAD DEBT RELIEF"})

    # Absent key → empty frozenset (optional).
    _write_cfg(
        tmp_path,
        "xero_sales_no_oos",
        """
        client_id: xero_sales_no_oos
        client_name: "No OOS"
        applicable_gst_rate: 0.09
        source_system: xero_sales
        tax_code_mappings:
          "STANDARD-RATED SUPPLIES": SR
        """,
    )
    cfg2 = load_client_config("xero_sales_no_oos", check_connectivity=False, config_dir=tmp_path)
    assert cfg2.out_of_scope_codes == frozenset()
