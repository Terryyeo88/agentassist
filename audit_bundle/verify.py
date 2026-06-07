"""verify.py — verify the tamper-evident integrity of a sealed audit bundle.

Performs two checks against the sealed bundle:

    1. Artefact integrity — every file listed in manifest.artefacts is re-hashed
       on disk and compared to its recorded sha256.  A missing file and a hash
       mismatch are both reported as separate problems.

    2. Root hash — the SHA-256 over the canonical JSON of the manifest with
       root_hash removed is recomputed and compared to the stored root_hash.
       This confirms the manifest itself has not been tampered with (including
       any per-artefact llm blocks or engagement/provenance fields).

Together these two checks confirm that neither the manifest metadata nor any
of the files it covers have changed since the bundle was sealed.

Runnable as:
    python -m audit_bundle.verify <bundle-dir>

CLI Args:
    bundle-dir  Path to the sealed bundle directory
                (e.g. audit/sbodemosg/2024-07-01_2024-09-30/20240930-120000).

Returns:
    Exits 0 and prints "PASS" on full verification success.
    Exits 1 and prints "FAIL" followed by a problem list on any failure.
    Exits 2 and prints usage to stderr on wrong argument count.

Example:
    python -m audit_bundle.verify audit/sbodemosg/2024-07-01_2024-09-30/20240930-120000

Dependencies:
    audit_bundle.canonical  canonical_json, sha256_bytes, sha256_file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from audit_bundle.canonical import canonical_json, sha256_bytes, sha256_file


def verify_bundle(bundle_dir: Path) -> tuple[bool, list[str]]:
    """Verify the integrity of a sealed bundle against its manifest.

    Two checks:
      1. Each artefact in manifest.artefacts re-hashes to its listed sha256.
      2. SHA-256 over canonical JSON of manifest-minus-root_hash equals
         the stored root_hash.

    Returns (True, []) on full pass; (False, [problem, ...]) on any failure.
    Problems name the failing artefact path or 'root_hash mismatch'.

    Args:
        bundle_dir: Path to the sealed bundle directory.  Must contain a
                    manifest.json at its root and all artefact files at their
                    relative paths as listed in manifest.artefacts.

    Returns:
        tuple[bool, list[str]]: A two-element tuple:
            - ok (bool): True only when every artefact hash matches and the
              root_hash is valid.  False if any single check fails.
            - problems (list[str]): Human-readable description of each
              failure, e.g. "artefact hash mismatch: steps/calculate.json"
              or "root_hash mismatch".  Empty on success.

    Raises:
        FileNotFoundError: If bundle_dir does not exist or manifest.json is
            absent from the bundle root.
        json.JSONDecodeError: If manifest.json is not valid JSON (implying
            the manifest file itself has been corrupted or truncated).

    Example:
        ok, problems = verify_bundle(Path("audit/sbodemosg/2024-07-01_2024-09-30/20240930-120000"))
        if not ok:
            for p in problems:
                print(f"  - {p}")
    """
    manifest_path = bundle_dir / "manifest.json"
    # read_bytes avoids any platform-specific line-ending translation that
    # text mode might apply, ensuring the manifest is parsed from raw bytes.
    manifest = json.loads(manifest_path.read_bytes())

    problems: list[str] = []

    # --- Check 1: per-artefact hash verification ---

    for artefact in manifest.get("artefacts", []):
        artefact_path = bundle_dir / artefact["path"]
        if not artefact_path.exists():
            problems.append(f"artefact missing: {artefact['path']}")
            # Skip hash check — file doesn't exist so there is nothing to hash.
            continue
        actual = sha256_file(artefact_path)
        if actual != artefact["sha256"]:
            problems.append(f"artefact hash mismatch: {artefact['path']}")

    # --- Check 2: root hash verification ---

    stored_root = manifest.get("root_hash")
    # Reconstruct the pre-seal manifest body by stripping root_hash, mirroring
    # the two-step construction in manifest.py: body first, then hash appended.
    manifest_without_root = {k: v for k, v in manifest.items() if k != "root_hash"}
    recomputed = sha256_bytes(canonical_json(manifest_without_root))
    if recomputed != stored_root:
        problems.append("root_hash mismatch")

    return len(problems) == 0, problems


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m audit_bundle.verify <bundle-dir>", file=sys.stderr)
        # Exit code 2 follows the Unix convention for argument/usage errors,
        # distinguishing them from a verification failure (exit 1).
        sys.exit(2)
    ok, problems = verify_bundle(Path(sys.argv[1]))
    if ok:
        print("PASS")
        sys.exit(0)
    print("FAIL")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)
