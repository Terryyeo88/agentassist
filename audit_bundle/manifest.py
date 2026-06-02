"""manifest.py — build the tamper-evident manifest.json for an audit bundle."""

from __future__ import annotations

from pathlib import Path

from audit_bundle.canonical import canonical_json, sha256_bytes, sha256_file


def build_manifest(
    engagement: dict,
    provenance: dict,
    artefact_paths: list[Path],
    bundle_dir: Path,
) -> dict:
    """Build a manifest dict covering all artefact files and seal it with a root hash.

    Artefacts are sorted by relative POSIX path (ascending).  root_hash is
    SHA-256 over canonical JSON of the manifest with that field absent, so
    any post-seal edit to any field invalidates the hash.
    """
    artefacts = []
    for path in artefact_paths:
        artefacts.append({
            "path": path.relative_to(bundle_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    artefacts.sort(key=lambda a: a["path"])

    manifest_without_root = {
        "schema_version": "1.0",
        "engagement": engagement,
        "provenance": provenance,
        "artefacts": artefacts,
    }
    root_hash = sha256_bytes(canonical_json(manifest_without_root))
    return {**manifest_without_root, "root_hash": root_hash}
