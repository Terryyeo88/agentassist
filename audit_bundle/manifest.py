"""manifest.py — build the tamper-evident manifest.json for an audit bundle.

Produces the manifest dict that is written as manifest.json at the root of
every sealed audit bundle.  The manifest covers three concerns:

    1. Engagement metadata — client, period, and run timestamps.
    2. Provenance metadata — tool versions, chain flags, and LLM run info.
    3. Artefact integrity — a per-file SHA-256 digest and byte-count for
       every file in the bundle.

Tamper-evidence is achieved via a root_hash: the SHA-256 of the canonical
JSON of the manifest with root_hash absent.  Any post-seal edit to any
field — including per-artefact llm blocks or the root_hash itself — changes
the canonical bytes and invalidates the hash.

Manifest schema (schema_version "1.0"):

    {
        "schema_version": "1.0",
        "engagement":  { <client/period fields> },
        "provenance":  { <run/tool/llm fields> },
        "artefacts": [
            {
                "path":   str,    # relative POSIX path from bundle root
                "sha256": str,    # "sha256:<hexdigest>"
                "bytes":  int,    # file size at seal time
                "llm":    dict    # optional; only on AI-produced artefacts
            },
            ...
        ],
        "root_hash": str          # "sha256:<hexdigest>" of the above
    }

Artefacts are always sorted by relative POSIX path so the canonical order
is independent of filesystem traversal order.

Public API:
    build_manifest(engagement, provenance, artefact_paths, bundle_dir, *,
                   artefact_llm_meta) -> dict

Dependencies:
    audit_bundle.canonical  canonical_json, sha256_bytes, sha256_file.
"""
from __future__ import annotations

from pathlib import Path

from audit_bundle.canonical import canonical_json, sha256_bytes, sha256_file


def build_manifest(
    engagement: dict,
    provenance: dict,
    artefact_paths: list[Path],
    bundle_dir: Path,
    *,
    artefact_llm_meta: dict[str, dict] | None = None,
) -> dict:
    """Build a manifest dict covering all artefact files and seal it with a root hash.

    Artefacts are sorted by relative POSIX path (ascending).  root_hash is
    SHA-256 over canonical JSON of the manifest with that field absent, so
    any post-seal edit to any field (including the per-artefact llm block)
    invalidates the hash.

    artefact_llm_meta, if provided, maps relative POSIX paths to an llm block
    dict {"in_run_path": bool, "model_id": str, "prompt_version": str,
    "kb_slice_hash": str}.  The llm block is attached to matching artefact
    entries only; deterministic artefacts carry no llm key (absence ≡ false).
    The global provenance.llm_in_run_path flag is unaffected by this parameter
    and stays False for the deterministic chain.

    Args:
        engagement:        Dict of client and period metadata written verbatim
                           into the manifest's "engagement" field
                           (e.g. {"client_id": "sbodemosg", "period": {...}}).
        provenance:        Dict of run and tooling metadata written verbatim
                           into the manifest's "provenance" field
                           (e.g. {"run_started_at": "...", "chain_version": "..."}).
        artefact_paths:    Absolute paths to every file that should be covered
                           by the manifest.  Each file is hashed and stat'd at
                           call time; the files must already exist on disk.
        bundle_dir:        Root directory of the bundle, used to compute each
                           file's relative path.  Every path in artefact_paths
                           must be a descendant of this directory.
        artefact_llm_meta: Optional mapping of relative POSIX path strings to
                           llm block dicts.  When provided, matching artefact
                           entries receive an "llm" key; unmatched entries do
                           not.  Pass None (default) for fully deterministic
                           bundles with no AI-produced artefacts.

    Returns:
        dict: Complete manifest ready to be JSON-serialised and written to
            manifest.json.  Always contains "schema_version", "engagement",
            "provenance", "artefacts", and "root_hash".  The root_hash covers
            all other fields so it must be the last operation before returning.

    Raises:
        ValueError: (from Path.relative_to) if any path in artefact_paths is
            not a descendant of bundle_dir.
        FileNotFoundError: (from sha256_file / Path.stat) if any artefact file
            does not exist at call time.

    Example:
        manifest = build_manifest(
            engagement={"client_id": cfg.client_id, "period": period},
            provenance={"run_started_at": run_started_at},
            artefact_paths=list(bundle_dir.iterdir()),
            bundle_dir=bundle_dir,
        )
        (bundle_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False)
        )
    """
    artefacts = []
    for path in artefact_paths:
        # POSIX paths (forward slashes) are used for all manifest entries so
        # the relative path strings are identical on Windows and Unix, keeping
        # the root_hash platform-independent.
        rel_path = path.relative_to(bundle_dir).as_posix()
        entry: dict = {
            "path": rel_path,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        if artefact_llm_meta and rel_path in artefact_llm_meta:
            entry["llm"] = artefact_llm_meta[rel_path]
        artefacts.append(entry)

    # Sort after building all entries so order is deterministic regardless of
    # the order artefact_paths was supplied or filesystem traversal order.
    # Artefact order is part of what root_hash covers, so any reordering
    # would invalidate the hash.
    artefacts.sort(key=lambda a: a["path"])

    # Build the manifest body first, without root_hash, because root_hash is
    # computed as the SHA-256 of this body.  Including root_hash in its own
    # input would require solving for a fixed point — instead it is appended
    # after the hash is computed.
    manifest_without_root = {
        "schema_version": "1.0",
        "engagement": engagement,
        "provenance": provenance,
        "artefacts": artefacts,
    }
    root_hash = sha256_bytes(canonical_json(manifest_without_root))
    return {**manifest_without_root, "root_hash": root_hash}
