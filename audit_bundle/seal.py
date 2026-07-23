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
import re
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

# Bound on the -N same-run_ts suffix fallback (t-seal-run-ts-collision). Exceeding it
# means a runaway caller is re-sealing the identical run_started_at in a loop — refuse
# LOUDLY (RuntimeError) rather than filling the audit root; never hang, never reuse a
# sealed dir. Module-level so tests can shrink it via monkeypatch.
_MAX_SAME_TS_SEALS = 100

# T2.27: a second (or Nth) reasoning stream seals to steps/<skill_id>-candidates.json.
# skill_id must be filename-safe and must not collide with reg2627's fixed key
# (steps/judgment-candidates.json), which is reserved for the reasoning_artefact
# parameter.
_SAFE_SKILL_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _extra_candidates_filename(skill_id: str) -> str:
    """Return steps/<skill_id>-candidates.json filename, validating skill_id.

    Raises ValueError on an unsafe skill_id (path traversal, bad characters) or
    one that would collide with reg2627's reserved judgment-candidates.json key.
    """
    if not isinstance(skill_id, str) or not _SAFE_SKILL_ID.match(skill_id):
        raise ValueError(f"unsafe skill_id for bundle key: {skill_id!r}")
    stem = f"{skill_id}-candidates"
    if stem == "judgment-candidates":
        raise ValueError(
            "skill_id 'judgment' collides with the reserved reg2627 bundle key "
            "steps/judgment-candidates.json"
        )
    return stem + ".json"


def _reasoning_llm_meta(artefact: dict) -> dict:
    """Build the per-artefact manifest llm metadata block for a reasoning artefact."""
    prov = artefact.get("provenance", {})
    return {
        # Default in_run_path=True: if a reasoning artefact exists, an LLM was in
        # the run path by definition.
        "in_run_path": bool(prov.get("in_run_path", True)),
        # str() coercions ensure None values become "" rather than causing a JSON
        # serialisation error in canonical_json.
        "model_id": str(prov.get("model_id", "")),
        "prompt_version": str(prov.get("prompt_version", "")),
        "kb_slice_hash": str(prov.get("kb_slice_hash", "")),
    }


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
    declared_f5: dict | None = None,
    agent_ledger=None,
    extra_reasoning_artefacts: "dict[str, dict] | None" = None,
) -> Path:
    """Write a sealed, tamper-evident audit bundle and return the bundle directory.

    Bundle layout (8 core artefacts hashed in manifest.json; 9 when reasoning
    artefact is supplied; 9 when declared_f5 is supplied; +1 when agent_ledger
    is supplied):
        audit/<client_id>/<start>_<end>/<run_ts>/
            manifest.json                         ← written last; covers all others
            config.json                           ← allow-listed; no credentials
            inputs/fetch-manifest.json
            inputs/declared-f5.json               ← only when declared_f5 given (T2.9)
            steps/{calculate,classify,detect}.json
            steps/judgment-candidates.json        ← only when reasoning_artefact given
            steps/agent-ledger.json               ← only when agent_ledger given (T5.2b)
            gates.json
            compile-output.json
            report.pdf

    All JSON written via canonical_json for stable, deterministic hashing.
    run_ts is derived from run_started_at (UTC, YYYYMMDD-HHMMSS-ffffff — fixed-width
    microseconds keep it collision-resistant and lexicographically sortable); on a
    true name collision (identical run_started_at) a bounded -N suffix is appended.
    The CHOSEN name — suffix included — is used for both the directory name and
    engagement.run_ts, so the two are always consistent.
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
        declared_f5:         Optional validated declared-F5 dict from
                             orchestrator.check_declared_f5.load_declared_f5().
                             When provided, written as inputs/declared-f5.json and
                             included in the manifest hash as an immutable input
                             record alongside inputs/fetch-manifest.json.
        agent_ledger:        Optional agent.ledger.Ledger instance (T5.2b).
                             When provided, its entries are serialised and written
                             as steps/agent-ledger.json and included in the manifest
                             hash.  Typed as object to avoid importing agent/ into
                             audit_bundle/ at module level.
        extra_reasoning_artefacts: Optional {skill_id: artefact} mapping for a
                             SECOND (or Nth) reasoning stream (T2.27).  Each is
                             written to steps/<skill_id>-candidates.json and hashed
                             in the manifest with its own llm-provenance block.
                             reg2627 continues to use reasoning_artefact →
                             steps/judgment-candidates.json (byte-identical); a
                             skill_id that would collide with that key, or is not
                             filename-safe, raises ValueError.  Default None keeps
                             every existing bundle byte-identical.

    Returns:
        Path: Absolute path to the sealed bundle directory
              (e.g. audit/sbodemosg/2024-07-01_2024-09-30/20240930-120000-000000/;
              a same-run_ts collision appends -2, -3, ...).

    Raises:
        OSError: If the bundle directory or any artefact file cannot be created
                 or written.  Read-only marking failures are logged but do not
                 raise.
        RuntimeError: If _MAX_SAME_TS_SEALS bundles already exist for the same
                 run_ts (runaway re-sealing of one run_started_at) — loud
                 refusal, never a hang or a write into a sealed dir.
    """
    # --- 0. Validate second-stream skill_ids up front (before any write) ---

    # Resolve each extra skill_id to its bundle filename now so an unsafe or
    # colliding id raises before the bundle directory is created — no partial
    # bundle is left behind.
    extra_files: dict[str, str] = {
        skill_id: _extra_candidates_filename(skill_id)
        for skill_id in (extra_reasoning_artefacts or {})
    }

    # --- a. run_ts and bundle directory ---

    # Convert to UTC before formatting so the directory name is timezone-agnostic
    # and sortable regardless of the host machine's local timezone.
    dt = datetime.fromisoformat(run_started_at).astimezone(timezone.utc)
    # YYYYMMDD-HHMMSS-ffffff: no colons (illegal in Windows paths), fixed-width
    # microseconds so the name stays lexicographically sortable. Production callers
    # pass isoformat() strings that already carry microseconds (engine/review.py);
    # the old seconds-resolution format DISCARDED them, so two engine runs in the
    # same second mapped to ONE read-only bundle dir and the second seal died on
    # Windows with PermissionError overwriting config.json.
    run_ts = dt.strftime("%Y%m%d-%H%M%S-%f")
    # Underscore separator between dates avoids ambiguity with the hyphens
    # already present inside each YYYY-MM-DD date string.
    period_tag = f"{period['start']}_{period['end']}"
    run_root = _AUDIT_ROOT / client_config.client_id / period_tag
    run_root.mkdir(parents=True, exist_ok=True)
    # Collision-free arbiter: mkdir(exist_ok=False) is atomic, so an identical
    # run_started_at (second-resolution caller strings, replays) falls back to a
    # bounded -N suffix instead of writing into an existing READ-ONLY bundle.
    # The chosen name — suffix included — becomes run_ts, keeping the directory
    # name and engagement.run_ts equal (the documented invariant).
    candidate = run_ts
    for _n in range(2, _MAX_SAME_TS_SEALS + 2):
        try:
            (run_root / candidate).mkdir(exist_ok=False)
            break
        except FileExistsError:
            candidate = f"{run_ts}-{_n}"
    else:
        raise RuntimeError(
            f"seal_bundle: {_MAX_SAME_TS_SEALS} sealed bundles already exist for "
            f"run_ts {run_ts!r} under {run_root} — refusing to seal another. "
            "A runaway caller appears to be re-sealing the same run_started_at."
        )
    run_ts = candidate
    bundle_dir = run_root / run_ts

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

    # --- b2b. Optional second/Nth reasoning streams (T2.27) ---

    # Each extra reasoning stream seals to its own steps/<skill_id>-candidates.json
    # key (validated in step 0), never overwriting reg2627's judgment-candidates.json.
    for skill_id, filename in extra_files.items():
        _write_canonical(
            bundle_dir / "steps" / filename,
            extra_reasoning_artefacts[skill_id],
        )

    # --- b3. Optional declared-F5 immutable input (T2.9) ---

    # Written alongside inputs/fetch-manifest.json as an immutable input record.
    # The declared values are the client's manually-filed F5 figures; sealing
    # them here anchors the declared-vs-computed findings to this specific run.
    if declared_f5 is not None:
        _write_canonical(
            bundle_dir / "inputs" / "declared-f5.json",
            declared_f5,
        )

    # --- b4. Optional agent justification ledger (T5.2b) ---

    # Serialised as a list of entry dicts (all LedgerEntry fields).  Written
    # before the manifest so the manifest hash covers it.  Typed as object to
    # keep audit_bundle/ free of agent/ imports.  dataclasses.asdict is stdlib.
    if agent_ledger is not None:
        from dataclasses import asdict as _asdict  # noqa: PLC0415
        _write_canonical(
            bundle_dir / "steps" / "agent-ledger.json",
            [_asdict(e) for e in agent_ledger.entries],
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
    # T2.9: declared-f5.json is an input artefact; add it to the manifest hash
    # when present so the tamper-evidence chain covers the declared figures.
    if declared_f5 is not None:
        artefact_paths.append(bundle_dir / "inputs" / "declared-f5.json")
    # T5.2b: agent-ledger.json is a deterministic artefact; add to manifest hash
    # when present so the tamper-evidence chain covers permission decisions.
    if agent_ledger is not None:
        artefact_paths.append(bundle_dir / "steps" / "agent-ledger.json")
    # Build per-artefact llm metadata for reasoning artefacts only.
    # Deterministic artefacts carry no llm key (absence ≡ false).
    llm_meta: dict = {}
    if reasoning_artefact is not None:
        artefact_paths.append(bundle_dir / "steps" / "judgment-candidates.json")
        llm_meta["steps/judgment-candidates.json"] = _reasoning_llm_meta(reasoning_artefact)
    # T2.27: each extra reasoning stream is hashed and carries its own llm block.
    for skill_id, filename in extra_files.items():
        artefact_paths.append(bundle_dir / "steps" / filename)
        llm_meta[f"steps/{filename}"] = _reasoning_llm_meta(
            extra_reasoning_artefacts[skill_id]
        )
    # Pass None (not an empty dict) when there are no reasoning artefacts, so a
    # fully deterministic bundle is byte-identical to the pre-T2.27 manifest.
    manifest = build_manifest(
        engagement, provenance, artefact_paths, bundle_dir,
        artefact_llm_meta=llm_meta or None,
    )
    # Write manifest directly (not via _write_canonical) — bundle_dir already
    # exists, and writing it last makes the "covers all others" intent explicit.
    (bundle_dir / "manifest.json").write_bytes(canonical_json(manifest))

    # --- f. Advisory read-only marking ---

    _mark_readonly(bundle_dir)

    return bundle_dir
