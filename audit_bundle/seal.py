"""seal.py — write a complete, sealed audit bundle for one chain run."""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from audit_bundle.canonical import canonical_json
from audit_bundle.config_redaction import redact_config
from audit_bundle.manifest import build_manifest
from audit_bundle.provenance import gather_provenance

log = logging.getLogger(__name__)

# Module-level so tests can redirect via monkeypatch without changing function signature.
_AUDIT_ROOT = Path(__file__).resolve().parent.parent / "audit"


def _write_canonical(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(data))


def _mark_readonly(bundle_dir: Path) -> None:
    """Mark bundle files and directories read-only — best-effort, advisory.

    The tamper evidence is the hash, not the permission.  Failures are logged
    but never propagate; on Windows os.chmod sets the read-only attribute but
    cannot prevent an administrator from overriding it.

    report.pdf is intentionally left writable: PDF viewers on Windows try to
    write last-opened-page state or annotation cache when opening a file; if
    the file is read-only they report "file cannot be opened" rather than
    "file is read-only".  The PDF's integrity is protected by its sha256 in
    manifest.json — the file-permission guard is redundant and user-hostile
    for this specific artefact.

    Files are processed before their parent directories so that POSIX systems
    do not lose directory-write before finishing individual file chmods.
    """
    try:
        paths = list(bundle_dir.rglob("*"))
        paths.sort(key=lambda p: (1 if p.is_dir() else 0))  # files first
        for path in paths:
            try:
                if path.is_file():
                    if path.name == "report.pdf":
                        continue  # leave PDF writable — see docstring
                    os.chmod(path, 0o444)
                elif path.is_dir():
                    os.chmod(path, 0o555)
            except Exception as exc:
                log.warning("mark_readonly: cannot chmod %s: %s", path, exc)
        os.chmod(bundle_dir, 0o555)
    except Exception as exc:
        log.warning("mark_readonly: failed on bundle root %s: %s", bundle_dir, exc)


def seal_bundle(
    *,
    client_config,
    period: dict,
    compile_output: dict,
    gate_results: dict,
    report_pdf_path: Path,
    run_started_at: str,
    run_completed_at: str,
) -> Path:
    """Write a sealed, tamper-evident audit bundle and return the bundle directory.

    Bundle layout (8 artefacts hashed in manifest.json):
        audit/<client_id>/<start>_<end>/<run_ts>/
            manifest.json                    ← written last; covers all others
            config.json                      ← allow-listed; no credentials
            inputs/fetch-manifest.json
            steps/{calculate,classify,detect}.json
            gates.json
            compile-output.json
            report.pdf

    All JSON written via canonical_json for stable, deterministic hashing.
    run_ts is derived from run_started_at (UTC, YYYYMMDD-HHMMSS) so the
    directory name and engagement.run_ts are always consistent.
    """
    # a. run_ts and bundle_dir
    dt = datetime.fromisoformat(run_started_at).astimezone(timezone.utc)
    run_ts = dt.strftime("%Y%m%d-%H%M%S")
    period_tag = f"{period['start']}_{period['end']}"
    bundle_dir = _AUDIT_ROOT / client_config.client_id / period_tag / run_ts
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # b. Write the 7 JSON artefacts and copy the PDF
    _write_canonical(bundle_dir / "config.json", redact_config(client_config))
    _write_canonical(bundle_dir / "inputs" / "fetch-manifest.json",
                     compile_output["fetch_manifest"])
    _write_canonical(bundle_dir / "steps" / "calculate.json", compile_output["calculate"])
    _write_canonical(bundle_dir / "steps" / "classify.json", compile_output["classify"])
    _write_canonical(bundle_dir / "steps" / "detect.json", compile_output["detect"])
    _write_canonical(bundle_dir / "gates.json", gate_results)
    _write_canonical(bundle_dir / "compile-output.json", compile_output)

    report_dest = bundle_dir / "report.pdf"
    shutil.copy2(report_pdf_path, report_dest)

    # c/d. Engagement and provenance
    engagement = {
        "client_id": client_config.client_id,
        "client_name": client_config.client_name,
        "period": period,
        "run_ts": run_ts,
        "run_started_at": run_started_at,
        "run_completed_at": run_completed_at,
    }
    provenance = gather_provenance(compile_output["classify"]["expected_rate"])

    # e. Build manifest over all 8 artefact paths; write it last
    artefact_paths = [
        bundle_dir / "compile-output.json",
        bundle_dir / "config.json",
        bundle_dir / "gates.json",
        bundle_dir / "inputs" / "fetch-manifest.json",
        bundle_dir / "report.pdf",
        bundle_dir / "steps" / "calculate.json",
        bundle_dir / "steps" / "classify.json",
        bundle_dir / "steps" / "detect.json",
    ]
    manifest = build_manifest(engagement, provenance, artefact_paths, bundle_dir)
    (bundle_dir / "manifest.json").write_bytes(canonical_json(manifest))

    # f. Advisory read-only marking
    _mark_readonly(bundle_dir)

    return bundle_dir
