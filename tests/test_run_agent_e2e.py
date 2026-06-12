"""
Hermetic end-to-end tests for run_agent.py seal integration.  No live SAP.

All external I/O is monkeypatched:
  - load_client_config      → fake ClientConfig (patched on run_agent)
  - engine.review.run_chain → (fixture CompileOutput, fabricated gate_results)
  - engine.review.render_pdf → writes a dummy PDF at the given path
  - seal._AUDIT_ROOT        → tmp_path/audit (keeps bundles out of the repo tree)
  - engine.review._REPORTS_DIR → tmp_path/reports

T5.1 behavior-equivalence: run_agent.py now delegates to engine.review.review().
The same three tests (sealed bundle produced, T7 determinism, GateFailure exit)
pass unchanged, demonstrating content-equivalent observable behavior.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import audit_bundle.seal as _seal_mod
import run_agent as _run_agent_mod
from audit_bundle import seal_bundle
from audit_bundle.canonical import sha256_bytes
from audit_bundle.verify import verify_bundle
from config.loader import ClientConfig
from orchestrator.exceptions import GateFailure

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_PERIOD_ARGS = ["2024-07-01", "2024-09-30"]
_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}
_CLIENT = "testclient"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_cfg() -> ClientConfig:
    return ClientConfig(
        client_id=_CLIENT,
        client_name="Test Client Pte Ltd",
        gst_registration_number="M90000001A",
        applicable_gst_rate=0.09,
        service_layer_url="https://fake",
        company_db="TESTDB",
        username="u",
        password="HUNTER2_TEST",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.10,
        reviewer_name="Jane Tan",
        firm_name="Tan & Associates",
    )


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


def _mock_render_pdf(model, out_path):
    """Write a minimal dummy PDF at out_path and return the Path."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4 dummy end-to-end test pdf for run_agent seal")
    return p


def _setup_mocks(monkeypatch, tmp_path) -> dict:
    """Wire all mocks; return the compile_output dict used by run_chain.

    T5.1: run_chain, render_pdf, and _REPORTS_DIR are now inside engine.review,
    not run_agent directly.  Patch targets updated accordingly.
    """
    compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr(sys, "argv",
                        ["run_agent", "--client", _CLIENT, "--period"] + _PERIOD_ARGS)
    monkeypatch.setattr("run_agent.load_client_config", lambda *a, **kw: _make_cfg())
    monkeypatch.setattr("engine.review.run_chain",
                        lambda *a, **kw: (compile_output, _gate_results()))
    monkeypatch.setattr("engine.review.render_pdf", _mock_render_pdf)
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")

    return compile_output


def _find_bundles(tmp_path: Path) -> list[Path]:
    audit_dir = tmp_path / "audit"
    if not audit_dir.exists():
        return []
    return sorted(p.parent for p in audit_dir.rglob("manifest.json"))


# ---------------------------------------------------------------------------
# Test: sealed bundle produced and verify_bundle passes
# ---------------------------------------------------------------------------

def test_sealed_bundle_produced_and_verify_passes(monkeypatch, tmp_path, capsys):
    _setup_mocks(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _run_agent_mod.main()
    assert exc_info.value.code == 0

    bundles = _find_bundles(tmp_path)
    assert len(bundles) == 1, f"Expected 1 bundle, found: {bundles}"
    bundle_dir = bundles[0]

    assert (bundle_dir / "manifest.json").exists()
    assert (bundle_dir / "compile-output.json").exists()
    assert (bundle_dir / "report.pdf").exists()
    assert (bundle_dir / "gates.json").exists()
    assert (bundle_dir / "config.json").exists()

    ok, problems = verify_bundle(bundle_dir)
    assert ok is True, f"verify_bundle failed: {problems}"

    # Check that the printed output contains the bundle path and verify command
    out = capsys.readouterr().out
    assert str(bundle_dir) in out
    assert "python -m audit_bundle.verify" in out


# ---------------------------------------------------------------------------
# T7: determinism — compile-output.json bytes identical across two seals
#     from identical inputs (different run timestamps, same chain data)
# ---------------------------------------------------------------------------

def test_T7_compile_output_deterministic_across_seals(monkeypatch, tmp_path):
    monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")

    compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
    gate_results = _gate_results()
    cfg = _make_cfg()

    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 determinism test")

    # Two seals with different run timestamps but identical chain data
    dir_1 = seal_bundle(
        client_config=cfg,
        period=_PERIOD,
        compile_output=compile_output,
        gate_results=gate_results,
        report_pdf_path=dummy_pdf,
        run_started_at="2026-06-01T09:11:17.649983+00:00",
        run_completed_at="2026-06-01T09:11:28.441921+00:00",
    )
    dir_2 = seal_bundle(
        client_config=cfg,
        period=_PERIOD,
        compile_output=compile_output,
        gate_results=gate_results,
        report_pdf_path=dummy_pdf,
        run_started_at="2026-06-01T09:12:17.649983+00:00",  # different minute → different dir
        run_completed_at="2026-06-01T09:12:28.441921+00:00",
    )

    assert dir_1 != dir_2, "Two runs with different timestamps must produce different bundle dirs"

    hash_1 = sha256_bytes((dir_1 / "compile-output.json").read_bytes())
    hash_2 = sha256_bytes((dir_2 / "compile-output.json").read_bytes())
    assert hash_1 == hash_2, (
        "compile-output.json bytes differ across seals from identical chain data — "
        "canonical_json serialisation is not deterministic"
    )


# ---------------------------------------------------------------------------
# GateFailure: exit non-zero, no bundle directory created
# ---------------------------------------------------------------------------

def test_gate_failure_exits_nonzero_no_bundle_created(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv",
                        ["run_agent", "--client", _CLIENT, "--period"] + _PERIOD_ARGS)
    monkeypatch.setattr("run_agent.load_client_config", lambda *a, **kw: _make_cfg())

    def _raise(*a, **kw):
        raise GateFailure(
            "Gate 2 [box-4]: box_4=999.00 != box_1+box_2+box_3=100.00 (delta=899.0000)",
            checked={"box_4": 999.0, "box_1_2_3_sum": 100.0, "tolerance": 0.01},
        )

    # T5.1: run_chain lives in engine.review; review() catches GateFailure and
    # returns status="halted" — run_agent.main() reads this and calls sys.exit(1).
    monkeypatch.setattr("engine.review.run_chain", _raise)
    monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")

    with pytest.raises(SystemExit) as exc_info:
        _run_agent_mod.main()

    assert exc_info.value.code != 0, "Expected non-zero exit on GateFailure"

    bundles = _find_bundles(tmp_path)
    assert bundles == [], (
        f"Expected no bundles when chain halts on GateFailure, found: {bundles}"
    )
