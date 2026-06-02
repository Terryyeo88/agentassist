"""canonical.py — deterministic serialisation and hashing for audit artefacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _default(obj):
    # FetchManifest.doc_nums is set[int] at runtime; sorted list is canonical.
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def canonical_json(obj) -> bytes:
    """Return obj serialised to canonical JSON bytes.

    Canonical form: keys sorted recursively, no insignificant whitespace,
    UTF-8 encoded.  ensure_ascii=False so em-dashes and non-ASCII characters
    in descriptions hash stably without percent-encoding expansion.
    Sets are serialised as sorted lists so runtime CompileOutput objects
    (doc_nums: set) hash identically to fixture-loaded ones (already lists).
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return 'sha256:<hexdigest>' of data."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    """Return 'sha256:<hexdigest>' of file contents, read in 64 KiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return "sha256:" + h.hexdigest()
