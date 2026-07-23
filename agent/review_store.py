"""
agent/review_store.py — append-only accumulation store for upload review sessions
(t-review-accumulation, D-2026-07-23-review-accumulation).

An ASK review is a review OF A PERIOD FOR AN ENTITY, evidenced by several exports.
This store lets uploads ATTACH to an explicit review session instead of replacing
each other. Mirrors the ``agent/decision_store.py`` precedent exactly: local files
only, append-only JSONL under a gitignored root, module-level monkeypatchable root
constant, and a strict path-segment guard.

KEYING (Terry R1, load-bearing): a review is keyed on an EXPLICIT ``review_id``
created by a deliberate ``create_review()`` call — NEVER on a client_id. Uploads
inherit DEMO config client_ids (xero_demo / xero_sales_demo / extract_demo), so a
client-derived key would merge DIFFERENT CLIENTS' uploads into one review — strictly
worse than the #45 decision-store leak. The per-slice ``client_id`` is recorded as
PROVENANCE ONLY (the structural hook Terry R5 named for the eventual #45 fix); it is
never used as a storage key and decision-store keying is untouched.

RE-UPLOAD SEMANTICS (Terry R2): slice identity is (source_kind, file sha256).
Same sha256 -> the caller skips the append (idempotent). Different sha256 + same
source_kind -> the new slice is APPENDED and the older one is SUPERSEDED-IN-VIEW:
the on-disk record is never rewritten (audit trail retained) and ``merged_view``
surfaces the supersession visibly (a reviewer must never wonder why a finding
vanished).

MERGED VIEW (Terry R6): grouped slices, never a flattened queue — two sightings of
one document from two export types ARE two evidentiary rows. The coverage_matrix
carries PER-SOURCE attribution per check so one slice's "examined" never masks
another's "unavailable".

Zero anthropic import. Zero SDK import. Stdlib only.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Module-level so tests can redirect via monkeypatch (decision_store precedent).
# Gitignored (reviews/) — runtime data, never committed; CI assumes it absent.
_REVIEWS_ROOT: Path = Path(__file__).resolve().parent.parent / "reviews"

# Path-segment guard (same class as decision_store._CLIENT_ID_RE): review_id lands
# in a filesystem path, so reject anything that could traverse or surprise.
_REVIEW_ID_RE = re.compile(r"^[a-z0-9_]+$")


class ReviewStoreError(ValueError):
    """Invalid review_id or malformed store operation."""


def _validated_review_id(review_id: str) -> str:
    rid = (review_id or "").strip()
    if not _REVIEW_ID_RE.fullmatch(rid):
        raise ReviewStoreError(
            f"review_id must match {_REVIEW_ID_RE.pattern!r}; got {review_id!r}"
        )
    return rid


def _slices_path(review_id: str) -> Path:
    return _REVIEWS_ROOT / _validated_review_id(review_id) / "slices.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def create_review(label: str = "") -> dict:
    """Create a new review session; returns its create record (incl. review_id)."""
    review_id = f"r_{uuid.uuid4().hex[:12]}"
    record = {
        "type": "create",
        "review_id": review_id,
        "created_at": _now_iso(),
        "label": str(label or ""),
    }
    _append(_slices_path(review_id), record)
    return record


def review_exists(review_id: str) -> bool:
    return _slices_path(review_id).is_file()


def load_review(review_id: str) -> dict:
    """Read the raw append-only record stream: {create: {...}, slices: [...]}."""
    path = _slices_path(review_id)
    if not path.is_file():
        raise FileNotFoundError(f"no review session {review_id!r}")
    create: dict = {}
    slices: list[dict] = []
    signed: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("type") == "create":
            create = record
        elif record.get("type") == "slice":
            slices.append(record)
        elif record.get("type") == "signed":
            signed.append(record)
    return {"create": create, "slices": slices, "signed": signed}


def upload_bytes_path(review_id: str, sha256: str, suffix: str = ".xlsx") -> Path:
    """Path of a slice's RETAINED upload bytes (t-accumulated-sign, Terry R1).

    reviews/<review_id>/uploads/<sha256><suffix>. Retention is what lets an accumulated
    sign re-run review() over the PRIMARY slice's exact bytes — the bounding invariant
    (boxes byte-identical, never merged) true BY CONSTRUCTION. Forward-only: sessions
    accumulated before retention landed have no bytes file, and the sign path refuses
    LOUDLY rather than producing a partial paper.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ReviewStoreError(f"sha256 must be 64 lowercase hex chars; got {sha256!r}")
    if suffix not in (".xlsx", ".ledger.xlsx"):
        raise ReviewStoreError(f"unsupported retained-bytes suffix {suffix!r}")
    return _REVIEWS_ROOT / _validated_review_id(review_id) / "uploads" / f"{sha256}{suffix}"


def save_upload_bytes(
    review_id: str, sha256: str, data: bytes, suffix: str = ".xlsx"
) -> Path:
    """Retain an upload's bytes for later accumulated signing (idempotent by sha)."""
    path = upload_bytes_path(review_id, sha256, suffix)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


def append_signed(review_id: str, signed_record: dict) -> None:
    """Append a type=="signed" event (append-only, like slices; history never rewritten)."""
    record = dict(signed_record)
    record["type"] = "signed"
    record.setdefault("signed_at", _now_iso())
    _append(_slices_path(review_id), record)


def sha_already_attached(review_id: str, source_kind: str, sha256: str) -> bool:
    """R2 idempotency probe: is this exact (source_kind, sha256) already a slice?"""
    data = load_review(review_id)
    return any(
        s.get("source_kind") == source_kind and s.get("sha256") == sha256
        for s in data["slices"]
    )


def append_slice(review_id: str, slice_record: dict) -> None:
    """Append one upload slice (already-serialized queue/coverage rows; plain JSON).

    Caller supplies: source_kind, sha256, client_id (provenance only), period (may be
    None), queue, coverage_status, plus branch extras. uploaded_at is stamped here.
    Append-only: superseding never rewrites prior lines.
    """
    record = dict(slice_record)
    record["type"] = "slice"
    record.setdefault("uploaded_at", _now_iso())
    _append(_slices_path(review_id), record)


def merged_view(review_id: str) -> dict:
    """The grouped-slices merged view (Terry R6) with visible supersession (R2).

    Active slice per source_kind = the LAST appended (file order == upload order).
    Earlier same-source_kind slices appear in "superseded" with superseded_at = the
    active slice's uploaded_at. coverage_matrix: per check name, one entry per ACTIVE
    slice carrying {source_kind, level, reason} — per-source attribution, never a
    collapsed verdict.
    """
    data = load_review(review_id)
    create = data["create"]

    active_by_kind: dict[str, dict] = {}
    superseded: list[dict] = []
    for s in data["slices"]:
        kind = s.get("source_kind", "")
        prior = active_by_kind.get(kind)
        if prior is not None:
            superseded.append({
                "source_kind": prior.get("source_kind"),
                "sha256": prior.get("sha256"),
                "uploaded_at": prior.get("uploaded_at"),
                "superseded_at": s.get("uploaded_at"),
            })
        active_by_kind[kind] = s

    active = list(active_by_kind.values())

    coverage_matrix: dict[str, list[dict]] = {}
    for s in active:
        for row in s.get("coverage_status") or []:
            coverage_matrix.setdefault(row.get("check", ""), []).append({
                "source_kind": s.get("source_kind"),
                "level": row.get("level"),
                "reason": row.get("reason"),
            })

    slices_out = [
        {k: v for k, v in s.items() if k != "type"} for s in active
    ]
    return {
        "review_id": create.get("review_id", review_id),
        "created_at": create.get("created_at"),
        "label": create.get("label", ""),
        "slices": slices_out,
        "superseded": superseded,
        "coverage_matrix": coverage_matrix,
        # t-accumulated-sign: sign events surface ADDITIVELY (existing keys unchanged).
        "signed": [
            {k: v for k, v in rec.items() if k != "type"}
            for rec in data.get("signed", [])
        ],
    }


def list_reviews() -> list[dict]:
    """Summaries of every review session under the root (empty root -> [])."""
    if not _REVIEWS_ROOT.is_dir():
        return []
    out: list[dict] = []
    for child in sorted(_REVIEWS_ROOT.iterdir()):
        if not (child / "slices.jsonl").is_file():
            continue
        try:
            data = load_review(child.name)
        except (OSError, json.JSONDecodeError, ReviewStoreError):
            continue
        create = data["create"]
        kinds: list[str] = []
        for s in data["slices"]:
            kind = s.get("source_kind", "")
            if kind not in kinds:
                kinds.append(kind)
        out.append({
            "review_id": create.get("review_id", child.name),
            "created_at": create.get("created_at"),
            "label": create.get("label", ""),
            "slice_count": len(data["slices"]),
            "source_kinds": kinds,
        })
    return out
