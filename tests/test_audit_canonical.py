from __future__ import annotations

import hashlib

from audit_bundle.canonical import canonical_json, sha256_bytes, sha256_file


# ---------------------------------------------------------------------------
# canonical_json
# ---------------------------------------------------------------------------

def test_canonical_json_order_independent():
    a = {"z": 1, "a": 2, "m": 3}
    b = {"m": 3, "z": 1, "a": 2}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_nested_order_independent():
    a = {"outer": {"z": 1, "a": 2}, "key": "val"}
    b = {"key": "val", "outer": {"a": 2, "z": 1}}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_byte_stable():
    obj = {"artefacts": [{"path": "compile-output.json", "sha256": "sha256:abc"}], "schema": "1.0"}
    first = canonical_json(obj)
    second = canonical_json(obj)
    assert first == second


def test_canonical_json_returns_bytes():
    result = canonical_json({"k": "v"})
    assert isinstance(result, bytes)


def test_canonical_json_utf8_passthrough():
    # em-dash in a description must not be percent-encoded
    obj = {"description": "rate — anomaly"}
    raw = canonical_json(obj)
    assert "—".encode("utf-8") in raw


def test_canonical_json_no_insignificant_whitespace():
    raw = canonical_json({"a": 1, "b": 2}).decode("utf-8")
    assert "  " not in raw
    assert "\n" not in raw


# ---------------------------------------------------------------------------
# sha256_bytes
# ---------------------------------------------------------------------------

def test_sha256_bytes_prefix():
    result = sha256_bytes(b"hello")
    assert result.startswith("sha256:")


def test_sha256_bytes_correct_digest():
    data = b"hello"
    expected_hex = hashlib.sha256(data).hexdigest()
    assert sha256_bytes(data) == f"sha256:{expected_hex}"


def test_sha256_bytes_different_inputs_differ():
    assert sha256_bytes(b"foo") != sha256_bytes(b"bar")


# ---------------------------------------------------------------------------
# sha256_file
# ---------------------------------------------------------------------------

def test_sha256_file_matches_bytes(tmp_path):
    f = tmp_path / "sample.txt"
    content = b"audit trail test content"
    f.write_bytes(content)
    assert sha256_file(f) == sha256_bytes(content)


def test_sha256_file_prefix(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"\x00\x01\x02")
    assert sha256_file(f).startswith("sha256:")


def test_sha256_file_accepts_str_path(tmp_path):
    f = tmp_path / "str.txt"
    f.write_bytes(b"str path test")
    assert sha256_file(str(f)) == sha256_bytes(b"str path test")
