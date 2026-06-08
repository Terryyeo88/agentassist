"""canonical.py — deterministic serialisation and hashing for audit artefacts.

Provides the two primitives the audit bundle depends on for tamper-evidence:

    1. canonical_json() — converts any audit object to a byte-stable JSON
       representation.  The same logical object must always produce the same
       bytes regardless of Python dict insertion order, set iteration order,
       or platform.  This is the foundation for reproducible hash digests.

    2. sha256_bytes() / sha256_file() — produce "sha256:<hexdigest>" strings
       in a consistent prefixed format so the manifest can identify the hash
       algorithm used without out-of-band metadata.

Canonicalisation rules:
    - Keys sorted recursively (sort_keys=True).
    - No insignificant whitespace (separators=(",", ":")).
    - UTF-8 encoded; ensure_ascii=False so multi-byte characters hash
      stably without percent-encoding expansion.
    - Sets serialised as sorted lists so runtime CompileOutput objects
      (doc_nums: set[int]) hash identically to fixture-loaded dicts
      (where the same field is already a list).

Dependencies:
    hashlib  — SHA-256 implementation (stdlib).
    json     — JSON serialisation (stdlib).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _default(obj):
    """JSON default handler for types not natively serialisable by json.dumps.

    Currently handles set → sorted list.  All other non-serialisable types
    re-raise TypeError so json.dumps surfaces them as encoding errors rather
    than silently producing wrong output.

    Args:
        obj: The Python object that json.dumps could not serialise.

    Returns:
        A JSON-serialisable substitute — sorted list for sets.

    Raises:
        TypeError: For any type other than set, preserving json.dumps default
            error behaviour.
    """
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

    Args:
        obj: Any JSON-serialisable Python object.  Sets of int (e.g.
             FetchManifest.doc_nums) are handled via _default.

    Returns:
        bytes: UTF-8 encoded canonical JSON with no trailing newline.

    Example:
        digest = sha256_bytes(canonical_json(compile_output))
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return the SHA-256 digest of data as a prefixed hex string.

    The "sha256:" prefix embeds the algorithm name in the digest string so
    manifest readers can identify the hash function without out-of-band
    metadata.

    Args:
        data: Raw bytes to hash (e.g. the output of canonical_json()).

    Returns:
        str: Digest in the form "sha256:<64-char-hexdigest>".
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    """Return the SHA-256 digest of a file's contents as a prefixed hex string.

    Reads the file in 64 KiB chunks so large files (e.g. the sealed PDF
    report) are hashed without loading the entire content into memory.

    Args:
        path: Filesystem path to the file to hash (Path or str).

    Returns:
        str: Digest in the form "sha256:<64-char-hexdigest>", identical in
             format to sha256_bytes() so manifest entries are uniform.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        # Walrus operator reads a chunk and assigns it in one expression;
        # the loop exits when read() returns an empty bytes object (EOF).
        while chunk := fh.read(65536):
            h.update(chunk)
    return "sha256:" + h.hexdigest()
