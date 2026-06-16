"""
tests/replay_shim.py — reusable offline-replay harness for the frozen SBODEMOSG extract.

Behaviour-preserving extraction of the patch set that was inline in
``tests/test_t2_12a_offline_replay.py``. The SAME fixture-injection shims (S0/S1/S2/S3/S5
+ frozen clock + no-contact guard) are defined ONCE here and exposed two ways:

  * ``install_replay_patches(monkeypatch, extract_dir)`` — installs the patch set via a
    pytest ``monkeypatch`` and returns the call-tracking ``contact`` dict. The T2.12a
    byte-identity gate uses this; the patch set is IDENTICAL to the old inline fixture,
    so the gate is unchanged.
  * ``frozen_extract_sap(extract_dir)`` — a stdlib ``unittest.mock``-based context manager
    yielding the same ``contact`` dict, for callers that have no pytest ``monkeypatch``.
  * ``replay_chain(period, ...)``  → ``(compile_output, gate_results)`` from ``run_chain``.
  * ``replay_review(period, ...)`` → a chain-only ``ReviewResult`` (T5.3h, decision B1):
    real findings via the byte-identity-gated deterministic chain, with
    ``reasoning_artefact=None`` (the Reg 26/27 pass is NOT run here) and
    ``document_candidates=None`` (no provider) — the honest SBODEMOSG degraded case.
    Report/seal are skipped (``report_pdf_path``/``bundle_dir`` ``None``); the findings the
    case-file loop consumes all live in ``compile_output``.

This is a TEST HARNESS, not the product adapter (mirroring the T2.12a docstring): it
injects frozen fixtures by patching the live SAP fetch primitives. It builds NO Excel/CSV
adapter (T2.12) and validates NO accuracy (T2.11). ``orchestrator/`` is untouched.
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


def _build_replay_specs(extract_dir: Path) -> "tuple[list[tuple[str, Any]], dict]":
    """Return ``(specs, contact)``: the fixture-injection patch set + contact tracker.

    ``specs`` is a list of ``(dotted_target, replacement)`` installable via EITHER
    ``monkeypatch.setattr(target, replacement)`` OR ``unittest.mock.patch(target,
    replacement)`` — the SINGLE definition of the replay patch set, so the pytest-fixture
    installer and the standalone context manager cannot drift. ``contact`` counts any
    real SAP login/request (must stay zero for a fully-offline run).
    """
    import sap_b1_server  # noqa: E402,F401 — path inserted at import; resolves dotted targets

    # Frozen extract data — deepcopy per call so each (redundant) call site gets fresh
    # objects, exactly as live SAP returns a fresh payload every fetch.
    invoices_by_entity = {
        "Invoices": _load(extract_dir, "invoices.raw.json"),
        "PurchaseInvoices": _load(extract_dir, "purchase-invoices.raw.json"),
        "CreditNotes": _load(extract_dir, "credit-notes.raw.json"),
        "PurchaseCreditNotes": _load(extract_dir, "purchase-credit-notes.raw.json"),
    }
    credit_notes_by_type = {
        "sales": _load(extract_dir, "credit-notes.raw.json"),
        "purchases": _load(extract_dir, "purchase-credit-notes.raw.json"),
    }
    listing = _load(extract_dir, "listing-headers.json")
    business_partners = _load(extract_dir, "business-partners.raw.json")
    inline_counts = _load(extract_dir, "inline-counts.json")["counts"]

    contact = {"login": 0, "request": 0}

    # --- S1 + fetch()'s CN reads: _fetch_invoices_paginated dispatch on entity ---
    def fake_fetch_invoices(entity, period_start, period_end):
        assert entity in invoices_by_entity, f"unexpected entity {entity!r}"
        return copy.deepcopy(invoices_by_entity[entity])

    # --- S2: _fetch_credit_notes_paginated dispatch on entity_type ---
    def fake_fetch_credit_notes(entity_type, period_start, period_end):
        assert entity_type in credit_notes_by_type, f"unexpected type {entity_type!r}"
        return copy.deepcopy(credit_notes_by_type[entity_type])

    # --- S5: fetch_listing_data (patched in chain's namespace) ---
    def fake_fetch_listing_data(client_config, period):
        return copy.deepcopy(listing)

    # --- S0 + S3: SAPB1Client.get fake (class-level; serves the only two sap.get call
    #     sites left after the high-level patches: count-probe + BP lookup) ---
    def fake_get(self, endpoint, params=None):
        params = params or {}
        if "$inlinecount" in params:
            # S0 count-probe. Return the count under the @-prefixed key only, so the
            # current code's resp.get("odata.count") -> None (Gate-1 dormancy),
            # reproducing TODAY's behaviour rather than the future fix.
            entity = endpoint.lstrip("/")
            return {"@odata.count": inline_counts.get(entity), "value": []}
        if endpoint.startswith("/BusinessPartners('") and endpoint.endswith("')"):
            card_code = endpoint[len("/BusinessPartners('"):-2]
            assert card_code in business_partners, f"unfrozen supplier {card_code!r}"
            return copy.deepcopy(business_partners[card_code])
        raise NoContactError(f"unexpected offline GET: {endpoint} params={params}")

    # --- No-contact guard: the only network entry points must never fire ---
    def guard_login(self, *a, **kw):
        contact["login"] += 1
        raise NoContactError("SAPB1Client.login attempted during offline replay")

    def guard_request(self, method, endpoint, **kw):
        contact["request"] += 1
        raise NoContactError(f"SAPB1Client.request attempted: {method} {endpoint}")

    # --- Frozen-clock pin: fetch() stamps fetch_manifest["fetched_at"] via datetime.now();
    #     pin it to the oracle's instant so the re-stamped string byte-matches. Scoped to
    #     orchestrator.steps.datetime only — nothing else in the run_chain path stamps a
    #     timestamp. ---
    oracle_fetched_at = _load(
        extract_dir, "_replay-oracle.compiled.json"
    )["compile_output"]["fetch_manifest"]["fetched_at"]
    fixed = datetime.fromisoformat(oracle_fetched_at)

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    specs: list[tuple[str, Any]] = [
        ("sap_b1_server._fetch_invoices_paginated", fake_fetch_invoices),
        ("sap_b1_server._fetch_credit_notes_paginated", fake_fetch_credit_notes),
        ("orchestrator.chain.fetch_listing_data", fake_fetch_listing_data),
        ("sap_b1_server.SAPB1Client.get", fake_get),
        ("sap_b1_server.SAPB1Client.login", guard_login),
        ("sap_b1_server.SAPB1Client.request", guard_request),
        ("orchestrator.steps.datetime", _FrozenClock),
    ]
    return specs, contact


def install_replay_patches(monkeypatch, extract_dir: Path = FIXTURE_DIR) -> dict:
    """Install the replay patch set via a pytest ``monkeypatch``; return ``contact``.

    Behaviour-preserving extraction of the old T2.12a fixture body: identical patch set,
    installed with ``monkeypatch.setattr`` (auto-undone at fixture teardown).
    """
    specs, contact = _build_replay_specs(extract_dir)
    for target, replacement in specs:
        monkeypatch.setattr(target, replacement)
    return contact


@contextlib.contextmanager
def frozen_extract_sap(extract_dir: Path = FIXTURE_DIR) -> Iterator[dict]:
    """Context manager installing the replay patch set via ``unittest.mock``; yields ``contact``.

    For callers with no pytest ``monkeypatch`` (e.g. ``replay_chain``/``replay_review``).
    All patches are reverted on exit.
    """
    specs, contact = _build_replay_specs(extract_dir)
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

    This is the exact deterministic-chain path the T2.12a gate protects byte-for-byte.
    Raises ``NoContactError`` if any real SAP login/request was attempted.
    """
    from config.loader import load_client_config
    from orchestrator.chain import run_chain

    if client_config is None:
        client_config = load_client_config("sbodemosg", check_connectivity=False)
    if period is None:
        period = period_from_manifest(extract_dir)

    with frozen_extract_sap(extract_dir) as contact:
        compile_output, gate_results = run_chain(client_config, period)

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
