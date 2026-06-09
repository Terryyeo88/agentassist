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


# ---------------------------------------------------------------------------
# T9 — T2.9 bundle-isolation: declared_f5=None produces no extra artefact
#      and a manifest byte-identical to pre-T2.9 behaviour on the same inputs.
# ---------------------------------------------------------------------------

def test_T9_declared_f5_none_no_extra_artefact_and_stable_manifest(
    tmp_path, monkeypatch
):
    """When declared_f5 is not supplied, the bundle must contain exactly the
    8 pre-T2.9 artefacts (no inputs/declared-f5.json) and the manifest bytes
    must be deterministic across two seals of identical inputs — proving that
    T2.9 code is inert on the 'off' path.

    Two identical seals (same run_started_at, same inputs) are compared:
        - Both use declared_f5=None (the default).
        - manifest.json bytes must match exactly (root_hash and all artefact
          hashes computed from the same canonical content).
        - inputs/declared-f5.json must be absent from both bundles.
        - verify_bundle must pass on both.
    """
    monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
    compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cfg = _make_cfg()
    common_kwargs = dict(
        client_config=cfg,
        period=_PERIOD,
        compile_output=compile_output,
        gate_results=_gate_results(),
        run_started_at=_STARTED,
        run_completed_at=_COMPLETED,
        # declared_f5 intentionally omitted (defaults to None)
    )

    # --- Seal A ---
    pdf_a = tmp_path / "dummy_a.pdf"
    pdf_a.write_bytes(b"%PDF-1.4 dummy test pdf A")
    bundle_a = seal_bundle(report_pdf_path=pdf_a, **common_kwargs)

    # --- Seal B (same inputs, different tmp pdf so the PDF hash differs,
    #     but all JSON artefacts are byte-identical → manifest root_hash identical) ---
    pdf_b = tmp_path / "dummy_b.pdf"
    pdf_b.write_bytes(b"%PDF-1.4 dummy test pdf A")  # same bytes → same PDF hash
    # Use a distinct bundle path so the two seals don't collide.
    monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit2")
    bundle_b = seal_bundle(report_pdf_path=pdf_b, **common_kwargs)

    # 1. No inputs/declared-f5.json in either bundle.
    assert not (bundle_a / "inputs" / "declared-f5.json").exists(), (
        "inputs/declared-f5.json must NOT exist when declared_f5=None"
    )
    assert not (bundle_b / "inputs" / "declared-f5.json").exists(), (
        "inputs/declared-f5.json must NOT exist when declared_f5=None (second seal)"
    )

    # 2. Both bundles contain exactly the 8 pre-T2.9 artefacts — no extras.
    manifest_a = json.loads((bundle_a / "manifest.json").read_bytes())
    manifest_b = json.loads((bundle_b / "manifest.json").read_bytes())
    paths_a = {a["path"] for a in manifest_a["artefacts"]}
    paths_b = {a["path"] for a in manifest_b["artefacts"]}
    assert paths_a == _EXPECTED_ARTEFACTS, (
        f"Bundle A artefact set changed: {paths_a}"
    )
    assert paths_b == _EXPECTED_ARTEFACTS, (
        f"Bundle B artefact set changed: {paths_b}"
    )

    # 3. manifest.json bytes are identical across both seals (determinism / pre-T2.9
    #    behaviour unchanged).  This proves T2.9 adds nothing when declared_f5=None.
    manifest_bytes_a = (bundle_a / "manifest.json").read_bytes()
    manifest_bytes_b = (bundle_b / "manifest.json").read_bytes()
    assert manifest_bytes_a == manifest_bytes_b, (
        "manifest.json bytes differ between two identical seals with declared_f5=None "
        "— seal is not deterministic on the off path"
    )

    # 4. Both bundles verify cleanly.
    ok_a, problems_a = verify_bundle(bundle_a)
    assert ok_a is True and problems_a == [], f"Bundle A failed verify: {problems_a}"
    ok_b, problems_b = verify_bundle(bundle_b)
    assert ok_b is True and problems_b == [], f"Bundle B failed verify: {problems_b}"
