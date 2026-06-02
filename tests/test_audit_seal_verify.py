"""Hermetic seal/verify tests — no live SAP, no real report generation.

Fixture: tests/fixtures/chain-run-sample.json (SBODEMOSG Q3 2024 CompileOutput).
PDF: a minimal dummy file — seal_bundle copies it verbatim; no ReportLab needed.
"""
from __future__ import annotations

import json
import os
import platform
import stat
from pathlib import Path

import pytest

import audit_bundle.seal as _seal_mod
from audit_bundle.seal import seal_bundle
from audit_bundle.verify import verify_bundle
from config.loader import ClientConfig

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_STARTED   = "2026-06-01T09:11:17.649983+00:00"
_COMPLETED = "2026-06-01T09:11:28.441921+00:00"
_PERIOD    = {"start": "2024-07-01", "end": "2024-09-30"}

_EXPECTED_ARTEFACTS = {
    "compile-output.json",
    "config.json",
    "gates.json",
    "inputs/fetch-manifest.json",
    "report.pdf",
    "steps/calculate.json",
    "steps/classify.json",
    "steps/detect.json",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(**overrides) -> ClientConfig:
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


def _gate_results() -> dict:
    return {
        "all_passed": True,
        "gates": [
            {
                "gate": 1,
                "name": "record-count",
                "after_step": "fetch",
                "status": "WARN_PASS",
                "passed": True,
                "checked": {"sap_inline_count": None, "fetched_count": 73},
                "message": "SAP $inlinecount unavailable",
            },
        ],
    }


def _dummy_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "dummy_report.pdf"
    p.write_bytes(b"%PDF-1.4 dummy one-page test pdf for audit_bundle seal tests")
    return p


def _do_seal(tmp_path: Path, monkeypatch, cfg: ClientConfig | None = None) -> Path:
    monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
    compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return seal_bundle(
        client_config=cfg or _make_cfg(),
        period=_PERIOD,
        compile_output=compile_output,
        gate_results=_gate_results(),
        report_pdf_path=_dummy_pdf(tmp_path),
        run_started_at=_STARTED,
        run_completed_at=_COMPLETED,
    )


def _force_writable(path: Path) -> None:
    """Best-effort chmod +w on a single file — works on both POSIX and Windows."""
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    except OSError:
        pass  # already writable, or no permission to chmod on this platform


# ---------------------------------------------------------------------------
# T1 — bundle structure
# ---------------------------------------------------------------------------

def test_T1_bundle_has_all_artefacts(tmp_path, monkeypatch):
    bundle_dir = _do_seal(tmp_path, monkeypatch)

    manifest_path = bundle_dir / "manifest.json"
    assert manifest_path.exists(), "manifest.json missing"

    manifest = json.loads(manifest_path.read_bytes())
    assert "root_hash" in manifest
    assert manifest["root_hash"].startswith("sha256:")

    listed = {a["path"] for a in manifest["artefacts"]}
    assert listed == _EXPECTED_ARTEFACTS, (
        f"Artefact set mismatch.\n  expected: {_EXPECTED_ARTEFACTS}\n  got: {listed}"
    )
    assert len(manifest["artefacts"]) == 8

    for rel in _EXPECTED_ARTEFACTS:
        assert (bundle_dir / rel).exists(), f"artefact file missing: {rel}"


# ---------------------------------------------------------------------------
# T2 — fresh bundle verifies clean
# ---------------------------------------------------------------------------

def test_T2_verify_fresh_bundle_passes(tmp_path, monkeypatch):
    bundle_dir = _do_seal(tmp_path, monkeypatch)
    ok, problems = verify_bundle(bundle_dir)
    assert ok is True
    assert problems == []


# ---------------------------------------------------------------------------
# T3 — flipped byte in compile-output.json → verify names the file
# ---------------------------------------------------------------------------

def test_T3_tampered_artefact_fails_verification(tmp_path, monkeypatch):
    bundle_dir = _do_seal(tmp_path, monkeypatch)
    target = bundle_dir / "compile-output.json"

    _force_writable(target)
    data = bytearray(target.read_bytes())
    data[10] ^= 0xFF   # flip one bit in byte 10
    target.write_bytes(bytes(data))

    ok, problems = verify_bundle(bundle_dir)
    assert ok is False
    assert any("compile-output.json" in p for p in problems), (
        f"Expected compile-output.json in problems; got: {problems}"
    )


# ---------------------------------------------------------------------------
# T4 — tampered manifest field → root_hash mismatch
# ---------------------------------------------------------------------------

def test_T4_tampered_manifest_field_fails_root_hash(tmp_path, monkeypatch):
    bundle_dir = _do_seal(tmp_path, monkeypatch)
    manifest_path = bundle_dir / "manifest.json"

    _force_writable(manifest_path)
    manifest = json.loads(manifest_path.read_bytes())
    manifest["provenance"]["repo_commit"] = "TAMPERED_SHA"
    # Write back as plain JSON (not canonical) but keep the original root_hash
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    ok, problems = verify_bundle(bundle_dir)
    assert ok is False
    assert "root_hash mismatch" in problems, (
        f"Expected 'root_hash mismatch' in problems; got: {problems}"
    )


# ---------------------------------------------------------------------------
# T5 — credential values and keys absent from every file in the bundle
# ---------------------------------------------------------------------------

def test_T5_credentials_absent_from_bundle(tmp_path, monkeypatch):
    cfg = _make_cfg(password="HUNTER2_TEST", username="sap_user")
    bundle_dir = _do_seal(tmp_path, monkeypatch, cfg=cfg)

    # Walk every file — binary scan covers JSON and PDF alike
    for path in bundle_dir.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_bytes()
        assert b"HUNTER2_TEST" not in content, (
            f"Password 'HUNTER2_TEST' found in {path.relative_to(bundle_dir)}"
        )

    # config.json must not expose credential key names at the top level
    config_data = json.loads((bundle_dir / "config.json").read_bytes())
    for forbidden_key in ("username", "password", "ssl_verify"):
        assert forbidden_key not in config_data, (
            f"Forbidden key '{forbidden_key}' present in config.json"
        )


# ---------------------------------------------------------------------------
# T8 — files read-only after seal (POSIX only; skip on Windows)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    platform.system() == "Windows",
    reason=(
        "os.chmod read-only is not enforced by the OS for normal users on Windows; "
        "tamper evidence is provided by the hash, not the file permission."
    ),
)
def test_T8_config_json_readonly_after_seal_posix(tmp_path, monkeypatch):
    bundle_dir = _do_seal(tmp_path, monkeypatch)
    config_path = bundle_dir / "config.json"
    file_mode = os.stat(config_path).st_mode
    # Owner-write bit must be clear after seal
    assert not (file_mode & stat.S_IWRITE), (
        f"config.json is still writable after seal (mode={oct(file_mode)})"
    )


def test_report_pdf_is_writable_after_seal(tmp_path, monkeypatch):
    # report.pdf must NOT be marked read-only: Windows PDF viewers try to write
    # last-opened-page state when opening a file; read-only causes them to report
    # "file corrupted" rather than "file is read-only".  Integrity is protected
    # by its sha256 in manifest.json.
    bundle_dir = _do_seal(tmp_path, monkeypatch)
    pdf_path = bundle_dir / "report.pdf"
    file_mode = os.stat(pdf_path).st_mode
    assert bool(file_mode & stat.S_IWRITE), (
        f"report.pdf should remain writable after seal but mode={oct(file_mode)}"
    )
