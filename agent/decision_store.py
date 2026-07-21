"""
agent/decision_store.py — Durable, per-client, append-only home for the DecisionLedger.

t-decision-persistence: the FIRST writable on-disk persistence of reviewer adjudications.
Before this module the DecisionLedger existed only in memory (agent/decision_ledger.py)
or as the committed READ-ONLY demo fixture (tests/fixtures/demo-artifacts/
decision-ledger.json); every reviewer decision on the web surface died with the React
state that held it. This module gives the ledger a durable file so decisions survive a
refresh and RE-APPLY on the next read of the same data.

STORE SHAPE — ``<_DECISIONS_ROOT>/<client_id>/ledger.jsonl`` (ruling M1): one JSON object
per line, each line the ``dataclasses.asdict`` serialisation of one ``AdjudicationEntry``.
``_DECISIONS_ROOT`` is a module-level constant mirroring ``audit_bundle.seal._AUDIT_ROOT``:
repo-relative, gitignored (``decisions/`` — the store is runtime data, never committed),
and monkeypatchable by tests. Unlike the per-run seal dir (fresh ``run_ts`` every upload)
this location is STABLE across uploads — that stability is the point.

APPEND-ONLY IS STRUCTURAL: ``append_decision`` opens the file in append mode and writes
exactly one line; no code path here rewrites, edits, or deletes a stored line. A change
of mind is a NEW appended entry over the same fingerprint. The hash chain continues from
the last stored entry, so ``load_decision_ledger(...).verify()`` catches any out-of-band
tamper of the file. Each client's file is ONE self-contained chain; merged in-memory
views built from several sources (e.g. frozen fixture + this store) are LOOKUP-ONLY and
must never be ``verify()``-ed — the chains are independently rooted.

CLIENT KEY (ruling M2): the store is keyed by config ``client_id`` (``xero_demo``,
``sbodemosg``, ...). All uploads routed through one demo config share ONE store — a
known multi-tenant gap, filed as an open item; acceptable only while uploads carry no
real client identity. ``client_id`` lands in a filesystem path, so it is validated
against ``^[a-z0-9_]+$`` (path-traversal guard) before any path is built.

READ-NEVER-WRITE-ON-SOURCE: this module writes ONLY under ``_DECISIONS_ROOT`` —
AgentAssist's own store. It imports nothing that can reach Xero, SAP, or any client
source (stdlib + agent.decision_ledger only; pinned by an AST-scan test).

Zero anthropic import. Zero SDK import. Stdlib + agent.decision_ledger only.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from agent.decision_ledger import DecisionLedger

#: Stable, gitignored root for all per-client decision ledgers (ruling M1).
#: Module-level and monkeypatchable — mirrors audit_bundle.seal._AUDIT_ROOT.
_DECISIONS_ROOT: Path = Path(__file__).resolve().parent.parent / "decisions"

#: client_id is a filesystem path segment — anything outside this alphabet is refused.
_CLIENT_ID_RE = re.compile(r"^[a-z0-9_]+$")

_LEDGER_FILENAME = "ledger.jsonl"


def _validated_client_id(client_id: str) -> str:
    """Refuse any client_id that could escape the decisions root (or is malformed)."""
    if not isinstance(client_id, str) or not _CLIENT_ID_RE.fullmatch(client_id):
        raise ValueError(
            f"invalid client_id {client_id!r}: must match ^[a-z0-9_]+$ "
            f"(it names a directory under the decisions store)"
        )
    return client_id


def ledger_path(client_id: str, root: Optional[Path] = None) -> Path:
    """The on-disk ledger file for *client_id*: <root>/<client_id>/ledger.jsonl."""
    base = Path(root) if root is not None else _DECISIONS_ROOT
    return base / _validated_client_id(client_id) / _LEDGER_FILENAME


def load_decision_entries(client_id: str, *, root: Optional[Path] = None) -> list[dict]:
    """All persisted entry dicts for *client_id*, oldest first; [] when no store exists."""
    path = ledger_path(client_id, root=root)
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def load_decision_ledger(client_id: str, *, root: Optional[Path] = None) -> DecisionLedger:
    """Reconstruct the client's DecisionLedger from disk (verify() to check the chain)."""
    return DecisionLedger.from_entries(load_decision_entries(client_id, root=root))


def append_decision(
    client_id: str,
    *,
    fingerprint: str,
    disposition: str,
    reviewer: str,
    reason: Optional[str] = None,
    period: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict:
    """Durably append ONE adjudication to the client's ledger; return the entry dict.

    Continues the hash chain from the last stored entry (the whole file is reloaded so
    ``prev_hash`` links correctly), then appends exactly one JSON line. Prior lines are
    never touched — append-only is structural, and an invalid disposition propagates
    ``ValueError`` from ``DecisionLedger.append`` before anything is written.
    """
    path = ledger_path(client_id, root=root)
    ledger = DecisionLedger.from_entries(load_decision_entries(client_id, root=root))
    entry = ledger.append(
        fingerprint=fingerprint,
        disposition=disposition,
        reviewer=reviewer,
        reason=reason,
        period=period,
    )
    record = asdict(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record
