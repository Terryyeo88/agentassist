"""T2.12a offline replay — same-SAP-state rederivation gate.

Runs the deterministic chain (run_chain) against the frozen SBODEMOSG extract
fixtures with SAP physically unreachable, and asserts the result is BYTE-IDENTICAL
to the frozen same-session oracle (_replay-oracle.compiled.json).

Passing proves two things:
  (a) the freeze is SUFFICIENT — every field run_chain needs is present in the
      frozen fixtures; a missing field would error or diverge here; and
  (b) the chain is reproducible offline — no live SAP required.

This is a TEST HARNESS, not the product adapter. It injects frozen fixtures via
test-only monkeypatches at the fetch primitives; it does NOT build the Excel/CSV
adapter (T2.12) and does NOT validate accuracy (T2.11). orchestrator/ is untouched.

Consumed surfaces (recon S0/S1/S2/S3/S5; S4 is reasoning-pass only, not read by
run_chain). See exploration-notes/t2.12a-read-surface-inventory.md.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Importing from orchestrator wires mcp-servers/custom onto sys.path (chain.py does
# the insertion); sap_b1_server is importable as a top-level module afterwards.
from orchestrator.chain import run_chain

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402 — path set above

from audit_bundle.canonical import canonical_json  # noqa: E402
from config.loader import load_client_config  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sbodemosg-extract"
ORACLE_PATH = FIXTURE_DIR / "_replay-oracle.compiled.json"
MANIFEST_PATH = FIXTURE_DIR / "capture-manifest.json"


class NoContactError(AssertionError):
    """Raised if any real SAP login/request is attempted during the replay."""


def _load(name: str):
    return json.load(open(FIXTURE_DIR / name, encoding="utf-8"))


def _period() -> dict:
    """Pin the period from the capture manifest (fallback: chain-run-sample)."""
    if MANIFEST_PATH.exists():
        return json.load(open(MANIFEST_PATH, encoding="utf-8"))["period"]
    sample = _REPO_ROOT / "tests" / "fixtures" / "chain-run-sample.json"
    return json.load(open(sample, encoding="utf-8"))["period"]


def _first_divergence(a, b, path="$"):
    """Return a human-readable first-divergence path between two JSON values.

    Used only on mismatch to point at which key diverged — surfaces a second
    non-deterministic source (if any) rather than dropping it silently.
    """
    if type(a) is not type(b):
        return f"{path}: type {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return f"{path}.{k}: missing in replay"
            if k not in b:
                return f"{path}.{k}: missing in oracle"
            d = _first_divergence(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: list len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_divergence(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    if a != b:
        return f"{path}: {a!r} != {b!r}"
    return None


@pytest.fixture()
def replay_patches(monkeypatch):
    """Install the fixture-injection shims, no-contact guard, and frozen clock.

    Returns the call-tracking dict so the test can assert no SAP contact occurred.
    """
    # Frozen extract data — deepcopy per call so each (redundant) call site gets
    # fresh objects, exactly as live SAP returns a fresh payload every fetch.
    invoices_by_entity = {
        "Invoices": _load("invoices.raw.json"),
        "PurchaseInvoices": _load("purchase-invoices.raw.json"),
        "CreditNotes": _load("credit-notes.raw.json"),
        "PurchaseCreditNotes": _load("purchase-credit-notes.raw.json"),
    }
    credit_notes_by_type = {
        "sales": _load("credit-notes.raw.json"),
        "purchases": _load("purchase-credit-notes.raw.json"),
    }
    listing = _load("listing-headers.json")
    business_partners = _load("business-partners.raw.json")
    inline_counts = _load("inline-counts.json")["counts"]

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

    # --- S0 + S3: SAPB1Client.get fake (class-level; serves the only two sap.get
    #     call sites left after the high-level patches: count-probe + BP lookup) ---
    def fake_get(self, endpoint, params=None):
        params = params or {}
        if "$inlinecount" in params:
            # S0 count-probe. Return the count under the @-prefixed key only, so
            # the current code's resp.get("odata.count") -> None (Gate-1 dormancy),
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

    monkeypatch.setattr(sap_b1_server, "_fetch_invoices_paginated", fake_fetch_invoices)
    monkeypatch.setattr(sap_b1_server, "_fetch_credit_notes_paginated", fake_fetch_credit_notes)
    monkeypatch.setattr("orchestrator.chain.fetch_listing_data", fake_fetch_listing_data)
    monkeypatch.setattr(sap_b1_server.SAPB1Client, "get", fake_get)
    monkeypatch.setattr(sap_b1_server.SAPB1Client, "login", guard_login)
    monkeypatch.setattr(sap_b1_server.SAPB1Client, "request", guard_request)

    # --- Frozen-clock pin: fetch() stamps fetch_manifest["fetched_at"] via
    #     datetime.now(); pin it to the oracle's instant so the re-stamped string
    #     byte-matches. Scoped to orchestrator.steps.datetime only — nothing else
    #     in the run_chain path stamps a timestamp. ---
    oracle_fetched_at = _load("_replay-oracle.compiled.json")["compile_output"]["fetch_manifest"]["fetched_at"]
    fixed = datetime.fromisoformat(oracle_fetched_at)

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr("orchestrator.steps.datetime", _FrozenClock)
    return contact


def test_offline_replay_byte_identical_to_oracle(replay_patches):
    """run_chain off frozen fixtures, SAP unreachable, == frozen oracle (bytes)."""
    # Hermetic config: same sbodemosg.yaml the capture used (identical tax-code
    # mappings / gst rate); creds are conftest stubs and never used (network blocked).
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    period = _period()

    compile_output, gate_results = run_chain(cfg, period)

    replayed = canonical_json({
        "period": period,
        "compile_output": compile_output,
        "gate_results": gate_results,
    })
    oracle_bytes = ORACLE_PATH.read_bytes()

    if replayed != oracle_bytes:
        # Surface which key diverged — a residual non-deterministic source, if any.
        diff = _first_divergence(
            json.loads(replayed), json.loads(oracle_bytes)
        )
        pytest.fail(f"offline replay diverged from oracle at {diff}")

    # No-contact guard must have stayed silent — proves the run was fully offline.
    assert replay_patches == {"login": 0, "request": 0}


def test_no_contact_guard_actually_fires_if_sap_touched(replay_patches):
    """Sanity: the guard is armed — a real request would raise, not pass silently."""
    fresh = sap_b1_server.SAPB1Client.__new__(sap_b1_server.SAPB1Client)
    with pytest.raises(NoContactError):
        sap_b1_server.SAPB1Client.request(fresh, "GET", "/Invoices")
    with pytest.raises(NoContactError):
        sap_b1_server.SAPB1Client.login(fresh)
