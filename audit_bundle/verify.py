"""verify.py — verify the tamper-evident integrity of a sealed audit bundle.

Runnable as:
    python -m audit_bundle.verify <bundle-dir>
Prints PASS (exit 0) or FAIL with a problem list (exit 1).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from audit_bundle.canonical import canonical_json, sha256_bytes, sha256_file


def verify_bundle(bundle_dir: Path) -> tuple[bool, list[str]]:
    """Verify integrity of a sealed bundle.

    Two checks:
      1. Each artefact in manifest.artefacts re-hashes to its listed sha256.
      2. SHA-256 over canonical JSON of manifest-minus-root_hash equals
         the stored root_hash.

    Returns (True, []) on full pass; (False, [problem, ...]) on any failure.
    Problems name the failing artefact path or 'root_hash mismatch'.
    """
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())

    problems: list[str] = []

    for artefact in manifest.get("artefacts", []):
        artefact_path = bundle_dir / artefact["path"]
        if not artefact_path.exists():
            problems.append(f"artefact missing: {artefact['path']}")
            continue
        actual = sha256_file(artefact_path)
        if actual != artefact["sha256"]:
            problems.append(f"artefact hash mismatch: {artefact['path']}")

    stored_root = manifest.get("root_hash")
    manifest_without_root = {k: v for k, v in manifest.items() if k != "root_hash"}
    recomputed = sha256_bytes(canonical_json(manifest_without_root))
    if recomputed != stored_root:
        problems.append("root_hash mismatch")

    return len(problems) == 0, problems


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m audit_bundle.verify <bundle-dir>", file=sys.stderr)
        sys.exit(2)
    ok, problems = verify_bundle(Path(sys.argv[1]))
    if ok:
        print("PASS")
        sys.exit(0)
    print("FAIL")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)
