"""manifest.py — build the tamper-evident manifest.json for an audit bundle."""

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
    """
    artefacts = []
    for path in artefact_paths:
        rel_path = path.relative_to(bundle_dir).as_posix()
        entry: dict = {
            "path": rel_path,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        if artefact_llm_meta and rel_path in artefact_llm_meta:
            entry["llm"] = artefact_llm_meta[rel_path]
        artefacts.append(entry)
    artefacts.sort(key=lambda a: a["path"])

    manifest_without_root = {
        "schema_version": "1.0",
        "engagement": engagement,
        "provenance": provenance,
        "artefacts": artefacts,
    }
    root_hash = sha256_bytes(canonical_json(manifest_without_root))
    return {**manifest_without_root, "root_hash": root_hash}
