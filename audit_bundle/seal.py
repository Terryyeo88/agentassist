"""seal.py — write a complete, sealed audit bundle for one chain run.

Orchestrates the six phases of the bundle-seal operation:

    a. Compute run_ts and create the bundle directory.
    b. Write the 7 core JSON artefacts and copy the PDF report.
    b2. Write the optional reasoning artefact (when supplied).
    c/d. Assemble engagement and provenance metadata.
    e. Build and write manifest.json (last — covers all other artefacts).
    f. Mark all bundle files advisory read-only.

The tamper-evidence guarantee comes from manifest.json's root_hash, not from
file permissions.  The read-only marking is a convenience advisory to prevent
accidental edits; a determined user or administrator can always override it.

Bundle layout:
    audit/<client_id>/<start>_<end>/<run_ts>/
        manifest.json                     ← written last; root_hash covers all
        config.json                       ← allow-listed, no credentials
        inputs/
            fetch-manifest.json
        steps/
            calculate.json
            classify.json
            detect.json
            judgment-candidates.json      ← only when reasoning_artefact given
        gates.json
        compile-output.json
        report.pdf

All JSON artefacts are written via canonical_json so their bytes are stable
and deterministic — the same logical data always produces the same file hash.

Public API:
    seal_bundle(**kwargs) -> Path

Dependencies:
    audit_bundle.canonical          canonical_json.
    audit_bundle.config_redaction   redact_config.
    audit_bundle.manifest           build_manifest.
    audit_bundle.provenance         gather_provenance.
"""
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
    """Serialise data to canonical JSON and write it to path, creating parents as needed.

    A thin wrapper around canonical_json that also handles directory creation,
    so callers writing into nested subdirectories (e.g. inputs/, steps/) do not
    need to pre-create those directories themselves.

    Args:
        path: Destination file path.  Parent directories are created
              automatically (parents=True, exist_ok=True).
        data: Any canonical_json-serialisable Python object (dict, list, etc.).
              Sets are handled via the canonical_json _default hook.
    """
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

    Args:
        bundle_dir: Root directory of the sealed bundle.  All files and
                    subdirectories within it are processed recursively.
    """
    try:
        paths = list(bundle_dir.rglob("*"))
        # Sort so files (key=0) are chmoded before their parent directories
        # (key=1); on POSIX, removing write on a directory first would prevent
        # subsequent file chmods from succeeding.
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
    reasoning_artefact: dict | None = None,
) -> Path:
    """Write a sealed, tamper-evident audit bundle and return the bundle directory.

    Bundle layout (8 core artefacts hashed in manifest.json; 9 when reasoning
    artefact is supplied):
        audit/<client_id>/<start>_<end>/<run_ts>/
            manifest.json                         ← written last; covers all others
            config.json                           ← allow-listed; no credentials
            inputs/fetch-manifest.json
            steps/{calculate,classify,detect}.json
            steps/judgment-candidates.json        ← only when reasoning_artefact given
            gates.json
            compile-output.json
            report.pdf

    All JSON written via canonical_json for stable, deterministic hashing.
    run_ts is derived from run_started_at (UTC, YYYYMMDD-HHMMSS) so the
    directory name and engagement.run_ts are always consistent.
    reasoning_artefact, when provided, is always written (status may be "errored")
    so the bundle records whether the pass ran and what happened.

    Args:
        client_config:       Validated ClientConfig from config.loader.  Used for
                             the bundle directory path, redacted config.json, and
                             engagement metadata.
        period:              Dict with "start" and "end" YYYY-MM-DD keys defining
                             the audit period.
        compile_output:      Full CompileOutput dict from orchestrator/chain.py,
                             containing all four step outputs and reconciliation data.
        gate_results:        Gate results dict from audit_bundle.gate_record, shaped
                             as {"all_passed": bool, "gates": [...]}.
        report_pdf_path:     Absolute path to the generated PDF report.  The file
                             is copied (not moved) into the bundle with shutil.copy2,
                             preserving the source file's metadata.
        run_started_at:      ISO-8601 UTC timestamp from before the chain ran.
                             Used to derive run_ts and the bundle directory name.
        run_completed_at:    ISO-8601 UTC timestamp from after the chain completed.
                             Recorded in engagement metadata only.
        reasoning_artefact:  Optional dict from reasoning.reg2627.run_reg2627_pass.
                             When provided, written as steps/judgment-candidates.json
                             and included in the manifest with its LLM provenance
                             block.  Pass None for a fully deterministic bundle.

    Returns:
        Path: Absolute path to the sealed bundle directory
              (e.g. audit/sbodemosg/2024-07-01_2024-09-30/20240930-120000/).

    Raises:
        OSError: If the bundle directory or any artefact file cannot be created
                 or written.  Read-only marking failures are logged but do not
                 raise.
    """
    # --- a. run_ts and bundle directory ---

    # Convert to UTC before formatting so the directory name is timezone-agnostic
    # and sortable regardless of the host machine's local timezone.
    dt = datetime.fromisoformat(run_started_at).astimezone(timezone.utc)
    # YYYYMMDD-HHMMSS: no colons (illegal in Windows paths), lexicographically
    # sortable, and matches the PDF filename format used in run_agent.py.
    run_ts = dt.strftime("%Y%m%d-%H%M%S")
    # Underscore separator between dates avoids ambiguity with the hyphens
    # already present inside each YYYY-MM-DD date string.
    period_tag = f"{period['start']}_{period['end']}"
    bundle_dir = _AUDIT_ROOT / client_config.client_id / period_tag / run_ts
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # --- b. Core JSON artefacts and PDF ---

    _write_canonical(bundle_dir / "config.json", redact_config(client_config))
    _write_canonical(bundle_dir / "inputs" / "fetch-manifest.json",
                     compile_output["fetch_manifest"])
    _write_canonical(bundle_dir / "steps" / "calculate.json", compile_output["calculate"])
    _write_canonical(bundle_dir / "steps" / "classify.json", compile_output["classify"])
    _write_canonical(bundle_dir / "steps" / "detect.json", compile_output["detect"])
    _write_canonical(bundle_dir / "gates.json", gate_results)
    _write_canonical(bundle_dir / "compile-output.json", compile_output)

    report_dest = bundle_dir / "report.pdf"
    # copy2 preserves the source file's timestamps, so the PDF in the bundle
    # retains the original generation time rather than the copy time.
    shutil.copy2(report_pdf_path, report_dest)

    # --- b2. Optional reasoning artefact ---

    # Always written when supplied — status may be "errored" — so the bundle
    # records whether the Reg 26/27 pass ran and what the outcome was.
    if reasoning_artefact is not None:
        _write_canonical(
            bundle_dir / "steps" / "judgment-candidates.json",
            reasoning_artefact,
        )

    # --- c/d. Engagement and provenance metadata ---

    engagement = {
        "client_id": client_config.client_id,
        "client_name": client_config.client_name,
        "period": period,
        "run_ts": run_ts,
        "run_started_at": run_started_at,
        "run_completed_at": run_completed_at,
    }
    # expected_rate is read from classify output rather than client_config so
    # the provenance block records the rate that was actually applied during
    # the run, not just what was configured.
    provenance = gather_provenance(compile_output["classify"]["expected_rate"])

    # --- e. Manifest (written last — covers all other artefacts) ---

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
    # Build per-artefact llm metadata for the reasoning artefact entry only.
    # Deterministic artefacts carry no llm key (absence ≡ false).
    artefact_llm_meta: dict | None = None
    if reasoning_artefact is not None:
        artefact_paths.append(bundle_dir / "steps" / "judgment-candidates.json")
        # provenance may be absent when the reasoning pass errored before
        # recording it; fall back to {} so all .get() calls below use defaults.
        ra_prov = reasoning_artefact.get("provenance", {})
        artefact_llm_meta = {
            "steps/judgment-candidates.json": {
                # Default in_run_path=True: if a reasoning artefact exists,
                # an LLM was in the run path by definition.
                "in_run_path": bool(ra_prov.get("in_run_path", True)),
                # str() coercions ensure None values become "" rather than
                # causing a JSON serialisation error in canonical_json.
                "model_id": str(ra_prov.get("model_id", "")),
                "prompt_version": str(ra_prov.get("prompt_version", "")),
                "kb_slice_hash": str(ra_prov.get("kb_slice_hash", "")),
            }
        }
    manifest = build_manifest(
        engagement, provenance, artefact_paths, bundle_dir,
        artefact_llm_meta=artefact_llm_meta,
    )
    # Write manifest directly (not via _write_canonical) — bundle_dir already
    # exists, and writing it last makes the "covers all others" intent explicit.
    (bundle_dir / "manifest.json").write_bytes(canonical_json(manifest))

    # --- f. Advisory read-only marking ---

    _mark_readonly(bundle_dir)

    return bundle_dir
