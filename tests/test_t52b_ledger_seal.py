"""
tests/test_t52b_ledger_seal.py — T-7: Ledger sealing into audit bundle.

Hermetic. No SDK, no SAP, no live model, no network.

T-7  A synthetic Ledger seals into an audit bundle as steps/agent-ledger.json.
     The bundle root-hash verify (verify_bundle) passes.
     The ledger chain verify still passes on the RECONSTRUCTED object loaded
     from the sealed JSON (AMEND-1: not the in-memory object — the bytes on disk).
     The test also proves tamper-detection: mutating a single byte in the sealed
     JSON breaks BOTH the bundle root-hash AND the ledger chain verify.

     Depends on:
       agent.ledger.Ledger.from_entries (new method added for 2b)
       audit_bundle.seal.seal_bundle (agent_ledger= parameter added for 2b)
       audit_bundle.verify.verify_bundle
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

import audit_bundle.seal as _seal_mod
from agent.ledger import Ledger, LedgerVerificationError
from agent.schemas import Tier
from audit_bundle.seal import seal_bundle
from audit_bundle.verify import verify_bundle
from config.loader import ClientConfig


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_cfg() -> ClientConfig:
    return ClientConfig(
        client_id="sealtest",
        client_name="Seal Test Ltd",
        gst_registration_number="M99999999Z",
        applicable_gst_rate=0.09,
        service_layer_url="https://fake",
        company_db="SEALDB",
        username="u",
        password="test_pass",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.10,
        reviewer_name="Test Reviewer",
        firm_name="Test Firm",
    )


def _gate_results() -> dict:
    return {
        "all_passed": True,
        "gates": [
            {
                "gate": i, "name": f"gate-{i}", "after_step": "step",
                "status": "PASS", "passed": True, "checked": {},
            }
            for i in range(1, 6)
        ],
    }


def _minimal_compile_output() -> dict:
    return {
        "period": {"start": "2024-07-01", "end": "2024-09-30"},
        "fetch_manifest": {
            "fetched_at": "2024-09-30T10:00:00+00:00",
            "records": [],
        },
        "classify": {"expected_rate": 0.09, "results": []},
        "calculate": {
            "boxes": {
                "box_1_std_rated_supplies": 0.0,
                "box_2_zero_rated_supplies": 0.0,
                "box_3_exempt_supplies": 0.0,
                "box_4_total_value_of_supplies": 0.0,
                "box_5_taxable_purchases": 0.0,
                "box_6_output_tax_due": 0.0,
                "box_7_input_tax_and_refunds": 0.0,
                "box_8_net_gst": 0.0,
                "box_9_total_value_of_taxable_purchases": 0.0,
            }
        },
        "detect": {"issues": []},
        "surfaced_warnings": [],
        "compile_ts": "2024-09-30T10:00:00+00:00",
    }


def _make_ledger_with_entries() -> Ledger:
    ledger = Ledger()
    ledger.append(
        tool_name="read_sap_invoices",
        tier=Tier.ZERO,
        justification=None,
        call_params={"period": "2024-Q3"},
        outcome="allowed",
        blocked_reason=None,
        timestamp="2024-09-30T10:00:00+00:00",
    )
    ledger.append(
        tool_name="run_review_chain",
        tier=Tier.ONE,
        justification="Running full Q3 review per IRAS ASK audit protocol Step 1.3c engagement scope.",
        call_params={"period": "2024-Q3"},
        outcome="allowed",
        blocked_reason=None,
        timestamp="2024-09-30T10:01:00+00:00",
    )
    ledger.append(
        tool_name="draft_report_section",
        tier=Tier.ONE,
        justification=None,
        call_params={},
        outcome="blocked",
        blocked_reason="justification is missing (None)",
        timestamp="2024-09-30T10:02:00+00:00",
    )
    return ledger


# ---------------------------------------------------------------------------
# T-7 tests
# ---------------------------------------------------------------------------

class TestT7LedgerSealing:
    def test_agent_ledger_json_written_to_bundle(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        dummy_pdf = tmp_path / "report.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 test")

        ledger = _make_ledger_with_entries()
        bundle_dir = seal_bundle(
            client_config=_make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=_minimal_compile_output(),
            gate_results=_gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2024-09-30T10:00:00+00:00",
            run_completed_at="2024-09-30T10:05:00+00:00",
            agent_ledger=ledger,
        )

        ledger_path = bundle_dir / "steps" / "agent-ledger.json"
        assert ledger_path.exists(), "steps/agent-ledger.json not written"
        entries = json.loads(ledger_path.read_bytes())
        assert isinstance(entries, list)
        assert len(entries) == 3

    def test_bundle_verify_passes_with_agent_ledger(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        dummy_pdf = tmp_path / "report.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 test")

        ledger = _make_ledger_with_entries()
        bundle_dir = seal_bundle(
            client_config=_make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=_minimal_compile_output(),
            gate_results=_gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2024-09-30T10:00:00+00:00",
            run_completed_at="2024-09-30T10:05:00+00:00",
            agent_ledger=ledger,
        )

        ok, problems = verify_bundle(bundle_dir)
        assert ok is True, f"verify_bundle failed: {problems}"

    def test_ledger_chain_verify_passes_on_reconstructed_object(self, monkeypatch, tmp_path):
        """AMEND-1: reload from sealed JSON and verify() the reconstructed Ledger."""
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        dummy_pdf = tmp_path / "report.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 test")

        original_ledger = _make_ledger_with_entries()
        bundle_dir = seal_bundle(
            client_config=_make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=_minimal_compile_output(),
            gate_results=_gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2024-09-30T10:00:00+00:00",
            run_completed_at="2024-09-30T10:05:00+00:00",
            agent_ledger=original_ledger,
        )

        ledger_path = bundle_dir / "steps" / "agent-ledger.json"
        raw_entries = json.loads(ledger_path.read_bytes())

        # Reconstruct from the SEALED bytes — not the in-memory object
        reconstructed = Ledger.from_entries(raw_entries)
        reconstructed.verify()  # must not raise

    def test_tamper_breaks_bundle_verify(self, monkeypatch, tmp_path):
        """Mutating a byte in agent-ledger.json breaks the bundle root-hash verify."""
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        dummy_pdf = tmp_path / "report.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 test")

        ledger = _make_ledger_with_entries()
        bundle_dir = seal_bundle(
            client_config=_make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=_minimal_compile_output(),
            gate_results=_gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2024-09-30T10:00:00+00:00",
            run_completed_at="2024-09-30T10:05:00+00:00",
            agent_ledger=ledger,
        )

        ledger_path = bundle_dir / "steps" / "agent-ledger.json"
        # The file is marked read-only by seal_bundle; make it writable to tamper
        import os, stat
        os.chmod(ledger_path, stat.S_IRUSR | stat.S_IWUSR)

        # Tamper: change "allowed" to "TAMPER_" in the raw bytes
        raw = ledger_path.read_bytes()
        tampered = raw.replace(b'"allowed"', b'"TAMPER_"', 1)
        assert tampered != raw, "Tampering did not change bytes — test setup issue"
        ledger_path.write_bytes(tampered)

        # bundle verify MUST fail
        ok, problems = verify_bundle(bundle_dir)
        assert ok is False
        assert any("agent-ledger" in p for p in problems)

    def test_tamper_breaks_ledger_chain_verify(self, monkeypatch, tmp_path):
        """Mutating agent-ledger.json breaks Ledger.verify() on the reconstructed object."""
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        dummy_pdf = tmp_path / "report.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 test")

        ledger = _make_ledger_with_entries()
        bundle_dir = seal_bundle(
            client_config=_make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=_minimal_compile_output(),
            gate_results=_gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2024-09-30T10:00:00+00:00",
            run_completed_at="2024-09-30T10:05:00+00:00",
            agent_ledger=ledger,
        )

        ledger_path = bundle_dir / "steps" / "agent-ledger.json"
        import os, stat
        os.chmod(ledger_path, stat.S_IRUSR | stat.S_IWUSR)

        # Load the entries as JSON, mutate one field, write back
        entries = json.loads(ledger_path.read_bytes())
        entries[0]["outcome"] = "TAMPERED"
        ledger_path.write_bytes(json.dumps(entries).encode())

        # Reconstruct and verify must FAIL
        reconstructed = Ledger.from_entries(entries)
        with pytest.raises(LedgerVerificationError):
            reconstructed.verify()

    def test_seal_without_agent_ledger_does_not_write_ledger_file(self, monkeypatch, tmp_path):
        """When agent_ledger=None, steps/agent-ledger.json is NOT written."""
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        dummy_pdf = tmp_path / "report.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 test")

        bundle_dir = seal_bundle(
            client_config=_make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=_minimal_compile_output(),
            gate_results=_gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2024-09-30T10:00:00+00:00",
            run_completed_at="2024-09-30T10:05:00+00:00",
            # no agent_ledger
        )

        ledger_path = bundle_dir / "steps" / "agent-ledger.json"
        assert not ledger_path.exists()

        ok, problems = verify_bundle(bundle_dir)
        assert ok is True, f"verify_bundle failed without ledger: {problems}"
