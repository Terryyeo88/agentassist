"""
tests/replay_shim.py — reusable offline-replay harness for the frozen SBODEMOSG extract.

Drives the deterministic chain (``run_chain``) against the frozen ``sbodemosg-extract``
fixtures with SAP physically unreachable.

T2.23 rewire: the frozen surfaces (S0/S1/S2/S3/S5) are now injected through the PUBLIC
chain source seam — ``run_chain(..., reader=FrozenExtractReader(...))`` — instead of
monkeypatching the ``_fetch_*`` / ``SAPB1Client.get`` internals. Only the no-contact
guards (``login``/``request``) and the frozen clock remain as patches: the guards prove
the run never touched real SAP, the clock pins ``fetch_manifest["fetched_at"]`` so the
re-stamped string byte-matches the oracle. The replayed bytes are unchanged (the reader
serves the same frozen payloads, deepcopy-per-call), so the T2.12a byte-identity gate and
the T5.3h loop-context consumers are behaviour-preserved.

Exposed:
  * ``FrozenExtractReader(extract_dir)`` / ``build_frozen_reader(extract_dir)`` — a
    ``ChainReader`` backed by the frozen extract (the injectable seam value).
  * ``install_replay_patches(monkeypatch, extract_dir)`` — installs the no-contact guards
    + frozen clock via a pytest ``monkeypatch``; returns the call-tracking ``contact`` dict.
  * ``frozen_extract_sap(extract_dir)`` — a stdlib ``unittest.mock``-based context manager
    installing the same guards + clock, yielding ``contact``.
  * ``replay_chain(period, ...)``  → ``(compile_output, gate_results)`` from ``run_chain``
    with the frozen reader injected.
  * ``replay_review(period, ...)`` → a chain-only ``ReviewResult`` (T5.3h, decision B1):
    real findings via the byte-identity-gated deterministic chain, with
    ``reasoning_artefact=None`` (the Reg 26/27 pass is NOT run here) and
    ``document_candidates=None`` (no provider) — the honest SBODEMOSG degraded case.
    Report/seal are skipped (``report_pdf_path``/``bundle_dir`` ``None``); the findings the
    case-file loop consumes all live in ``compile_output``.

This is a TEST HARNESS, not the product adapter (mirroring the T2.12a docstring): it
injects frozen fixtures via the chain source seam. It builds NO Excel/CSV adapter (T2.12)
and validates NO accuracy (T2.11). ``orchestrator/`` is untouched.
"""
from __future__ import annotations

import contextlib
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"

# sap_b1_server is importable only after mcp-servers/custom is on sys.path (chain.py also
# inserts it; we insert here so the dotted patch targets resolve when the shim is used
# standalone, before run_chain has run).
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))


class NoContactError(AssertionError):
    """Raised if any real SAP login/request is attempted during the replay."""


def _load(extract_dir: Path, name: str):
    return json.load(open(extract_dir / name, encoding="utf-8"))


def period_from_manifest(extract_dir: Path = FIXTURE_DIR) -> dict:
    """Pin the period from the capture manifest (fallback: chain-run-sample)."""
    manifest = extract_dir / "capture-manifest.json"
    if manifest.exists():
        return json.load(open(manifest, encoding="utf-8"))["period"]
    sample = _REPO_ROOT / "tests" / "fixtures" / "chain-run-sample.json"
    return json.load(open(sample, encoding="utf-8"))["period"]


# ---------------------------------------------------------------------------
# Frozen-extract ChainReader — the injectable seam value (S0/S1/S2/S3/S5)
# ---------------------------------------------------------------------------

class FrozenExtractReader:
    """A ``sap_b1_server.ChainReader`` backed by the frozen SBODEMOSG extract.

    Returns the same verbatim payloads the capture froze, ``deepcopy``-per-call so each
    (redundant) read site gets fresh objects — exactly as live SAP returns a fresh payload
    every fetch. The deepcopy is load-bearing: the ``is_credit_note=True`` tag baked into
    the credit-note fixtures can never leak into the untagged invoice read via a shared
    mutable object (the per-call-freshness hazard).
    """

    def __init__(self, extract_dir: Path = FIXTURE_DIR):
        # fetch()'s S1 reads dispatch on entity; CreditNotes / PurchaseCreditNotes map to
        # the (already-tagged) credit-note fixtures, exactly as the old shim did.
        self._invoices_by_entity = {
            "Invoices": _load(extract_dir, "invoices.raw.json"),
            "PurchaseInvoices": _load(extract_dir, "purchase-invoices.raw.json"),
            "CreditNotes": _load(extract_dir, "credit-notes.raw.json"),
            "PurchaseCreditNotes": _load(extract_dir, "purchase-credit-notes.raw.json"),
        }
        self._credit_notes_by_type = {
            "sales": _load(extract_dir, "credit-notes.raw.json"),
            "purchases": _load(extract_dir, "purchase-credit-notes.raw.json"),
        }
        self._listing = _load(extract_dir, "listing-headers.json")
        self._business_partners = _load(extract_dir, "business-partners.raw.json")
        self._inline_counts = _load(extract_dir, "inline-counts.json")["counts"]

    def count(self, entity: str, period_start: str, period_end: str):
        """S0 — the corrected ``@odata.count`` read (backlog #5 fixed).

        The v2 probe response carries the total under "@odata.count" (with @). We
        reconstruct that exact wire response and read the @-prefixed key, matching the
        corrected production read in ``sap_b1_server.SapChainReader.count`` so the shim
        stands in for real SAP faithfully (no lingering unprefixed read). The re-frozen
        oracle records Gate-1 PASS: over the frozen extract sap_inline_count 86 == 86 rows
        fetched, so pagination is genuinely complete.
        """
        resp = {"@odata.count": self._inline_counts.get(entity), "value": []}
        raw = resp.get("@odata.count")
        return int(raw) if raw is not None else None

    def fetch_invoices(self, entity: str, period_start: str, period_end: str) -> list:
        assert entity in self._invoices_by_entity, f"unexpected entity {entity!r}"
        return copy.deepcopy(self._invoices_by_entity[entity])

    def fetch_credit_notes(self, entity_type: str, period_start: str, period_end: str) -> list:
        assert entity_type in self._credit_notes_by_type, f"unexpected type {entity_type!r}"
        return copy.deepcopy(self._credit_notes_by_type[entity_type])

    def get_business_partner(self, card_code: str) -> dict:
        assert card_code in self._business_partners, f"unfrozen supplier {card_code!r}"
        return copy.deepcopy(self._business_partners[card_code])

    def fetch_listing(self, period: dict) -> dict:
        return copy.deepcopy(self._listing)


def build_frozen_reader(extract_dir: Path = FIXTURE_DIR) -> FrozenExtractReader:
    """Return a FrozenExtractReader — the value injected through the chain source seam."""
    return FrozenExtractReader(extract_dir)


# ---------------------------------------------------------------------------
# No-contact guards + frozen clock (the only remaining patches)
# ---------------------------------------------------------------------------

def _build_guard_specs(extract_dir: Path) -> "tuple[list[tuple[str, Any]], dict]":
    """Return ``(specs, contact)``: no-contact guards + frozen-clock patch set.

    ``specs`` is a list of ``(dotted_target, replacement)`` installable via EITHER
    ``monkeypatch.setattr`` OR ``unittest.mock.patch`` — the SINGLE definition so the
    pytest-fixture installer and the standalone context manager cannot drift. The frozen
    SAP reads are NOT patched here: they are served by an injected FrozenExtractReader via
    the public ``run_chain(reader=...)`` seam. ``contact`` counts any real SAP login/request
    (must stay zero — the request guard catches every ``SAPB1Client.get`` that would slip
    through to the network).
    """
    import sap_b1_server  # noqa: F401 — path inserted at import; resolves dotted targets

    contact = {"login": 0, "request": 0}

    def guard_login(self, *a, **kw):
        contact["login"] += 1
        raise NoContactError("SAPB1Client.login attempted during offline replay")

    def guard_request(self, method, endpoint, **kw):
        contact["request"] += 1
        raise NoContactError(f"SAPB1Client.request attempted: {method} {endpoint}")

    # Frozen-clock pin: fetch() stamps fetch_manifest["fetched_at"] via datetime.now();
    # pin it to the oracle's instant so the re-stamped string byte-matches. Scoped to
    # orchestrator.steps.datetime only — nothing else in the run_chain path stamps a
    # timestamp.
    oracle_fetched_at = _load(
        extract_dir, "_replay-oracle.compiled.json"
    )["compile_output"]["fetch_manifest"]["fetched_at"]
    fixed = datetime.fromisoformat(oracle_fetched_at)

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    specs: list[tuple[str, Any]] = [
        ("sap_b1_server.SAPB1Client.login", guard_login),
        ("sap_b1_server.SAPB1Client.request", guard_request),
        ("orchestrator.steps.datetime", _FrozenClock),
    ]
    return specs, contact


def install_replay_patches(monkeypatch, extract_dir: Path = FIXTURE_DIR) -> dict:
    """Install the no-contact guards + frozen clock via a pytest ``monkeypatch``.

    Returns the ``contact`` tracker. The frozen reads are injected separately via the
    chain source seam (``build_frozen_reader`` -> ``run_chain(reader=...)``).
    """
    specs, contact = _build_guard_specs(extract_dir)
    for target, replacement in specs:
        monkeypatch.setattr(target, replacement)
    return contact


@contextlib.contextmanager
def frozen_extract_sap(extract_dir: Path = FIXTURE_DIR) -> Iterator[dict]:
    """Context manager installing the no-contact guards + frozen clock via ``unittest.mock``.

    For callers with no pytest ``monkeypatch`` (e.g. ``replay_chain``/``replay_review``).
    All patches are reverted on exit. The frozen reads are injected via the seam separately.
    """
    specs, contact = _build_guard_specs(extract_dir)
    with contextlib.ExitStack() as stack:
        for target, replacement in specs:
            stack.enter_context(mock.patch(target, replacement))
        yield contact


def replay_chain(
    period: "dict | None" = None,
    *,
    extract_dir: Path = FIXTURE_DIR,
    client_config: Any = None,
) -> "tuple[dict, dict]":
    """Run ``run_chain`` off the frozen extract (SAP unreachable) → ``(compile_output, gate_results)``.

    Injects a FrozenExtractReader through the public chain source seam; this is the exact
    deterministic-chain path the T2.12a gate protects byte-for-byte. Raises
    ``NoContactError`` if any real SAP login/request was attempted.
    """
    from config.loader import load_client_config
    from orchestrator.chain import run_chain

    if client_config is None:
        client_config = load_client_config("sbodemosg", check_connectivity=False)
    if period is None:
        period = period_from_manifest(extract_dir)

    reader = build_frozen_reader(extract_dir)
    with frozen_extract_sap(extract_dir) as contact:
        compile_output, gate_results = run_chain(client_config, period, reader=reader)

    if contact != {"login": 0, "request": 0}:  # pragma: no cover - guard fires as AssertionError first
        raise NoContactError(f"SAP contact during replay: {contact}")
    return compile_output, gate_results


def replay_review(
    period: "dict | None" = None,
    *,
    extract_dir: Path = FIXTURE_DIR,
    client_config: Any = None,
) -> Any:
    """Build a chain-only offline-replay ``ReviewResult`` from the frozen extract (B1).

    Runs the byte-identity-gated deterministic chain off the frozen extract and assembles
    a real ``ReviewResult(status="completed")``. The Reg 26/27 reasoning pass is NOT run
    (``reasoning_artefact=None``) and no document provider is supplied
    (``document_candidates=None``) — the honest SBODEMOSG degraded case. Report and seal
    are skipped (``report_pdf_path``/``bundle_dir`` ``None``); the findings the case-file
    loop consumes all live in ``compile_output.detect.issues``.

    ``run_started_at`` is pinned to the frozen fetch instant (deterministic; not a live
    wall-clock run). ``extract_findings`` is None-safe over the ``None`` reasoning /
    document fields.
    """
    from engine.review import ReviewResult

    compile_output, gate_results = replay_chain(
        period, extract_dir=extract_dir, client_config=client_config
    )
    fetched_at = compile_output["fetch_manifest"]["fetched_at"]
    return ReviewResult(
        status="completed",
        compile_output=compile_output,
        gate_results=gate_results,
        reasoning_artefact=None,
        document_candidates=None,
        analytical_review_data=None,
        report_pdf_path=None,
        bundle_dir=None,
        run_started_at=fetched_at,
        run_completed_at=None,
        gate_failure=None,
    )
