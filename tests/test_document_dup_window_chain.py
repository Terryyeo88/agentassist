"""
tests/test_document_dup_window_chain.py — FAILING-FIRST chain-wiring, OFF-state and
box-isolation tests for the NEW windowed duplicate-purchase surfacer (DUP_WINDOW).

The chain does NOT yet attach the check and ClientConfig does NOT yet carry the
dup_window_* fields; every test here is RED for the RIGHT REASON today:

  - the ON tests fail at ClientConfig(dup_window_enabled=..., dup_window_days=...)
    with a TypeError (unexpected keyword argument) — the config field does not exist;
  - the OFF tests fail at ``cfg.dup_window_enabled`` with an AttributeError. The
    OFF precondition is asserted DELIBERATELY: without it, "key not in result"
    would pass vacuously today (nothing writes the key) and the test would be
    green-now / meaningless. Asserting the flag exists and is False makes the test
    RED now and a true OFF-state guard once built;
  - the failure-contract test fails monkeypatching a chain attribute
    (orchestrator.chain.detect_window_dups) that does not exist yet.

Hermetic run_chain harness REPLICATED from tests/test_document_dup_chain.py — not
imported, not edited (existing test files are append-only in this repo). Same shape:
fetch/calculate/classify/detect/fetch_listing_data monkeypatched, plus the no-contact
SAP guard, over a PURCHASE-INVOICE manifest.

The OFF state is the load-bearing one. When dup_window_enabled is False (the
DEFAULT), the chain writes NEITHER result key — not an empty list, not None, not a
status. That is what keeps the frozen offline-replay oracle byte-identical
(invariant 4) with no re-freeze. Template for the assertion shape:
tests/test_t224_chain_seam.py::test_no_ledger_path_adds_no_keys.

NOTE the state distinction these tests pin: "unavailable" means the check RAN AND
THREW. It is NOT the OFF state. Conflating them would let a silently-off check read
as a degraded one (and vice versa).

Window values below (7) are ARBITRARY caller inputs, never validated truth — the
worksheet that would derive a blessed window does not exist yet. No test here
asserts an over-firing / false-positive rate: no must-spare fixture exists.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Import run_chain first — this triggers the mcp-servers/custom sys.path setup.
from orchestrator.chain import run_chain

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))
import sap_b1_server  # noqa: E402 — path set above

from config.loader import ClientConfig  # noqa: E402


_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}

# Arbitrary caller-supplied window for these wiring tests. NOT a validated value.
_WINDOW_DAYS = 7


# ---------------------------------------------------------------------------
# Config fixtures (mirror test_document_dup_chain.cfg)
# ---------------------------------------------------------------------------

def _base_cfg_kwargs() -> dict:
    return dict(
        client_id="test",
        client_name="Test Client",
        gst_registration_number="",
        applicable_gst_rate=0.07,
        service_layer_url="https://fake",
        company_db="TEST",
        username="user",
        password="pass",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.1,
        reviewer_name="",
        firm_name="",
    )


@pytest.fixture()
def cfg_off():
    """DEFAULT config — dup_window_* untouched, so the check must stay OFF."""
    return ClientConfig(**_base_cfg_kwargs())


@pytest.fixture()
def cfg_on():
    """Check explicitly enabled with an arbitrary 7-day window."""
    return ClientConfig(
        **_base_cfg_kwargs(),
        dup_window_enabled=True,
        dup_window_days=_WINDOW_DAYS,
    )


# ---------------------------------------------------------------------------
# Purchase-invoice manifest builders
# ---------------------------------------------------------------------------

def _purch(doc_num, doc_date, doc_total, card_name="Acme Supplies Pte Ltd"):
    return {
        "doc_num": doc_num,
        "doc_date": doc_date,
        "doc_type": "purchase_invoice",
        "doc_currency": "SGD",
        "doc_total": doc_total,
        "card_name": card_name,
        "vat_group": "IP",
    }


def _manifest(records):
    doc_nums = {r["doc_num"] for r in records if r["doc_num"]}
    return {
        "period": _PERIOD,
        "fetched_at": "2024-10-01T00:00:00+00:00",
        "records": records,
        "doc_nums": doc_nums,
        "sap_inline_count": None,
    }


def _manifest_with_window_pair():
    # 501/502: same supplier, same amount, 3 days apart -> inside a 7-day window,
    # and NOT a same-day collision (so DUP_SAME_DAY stays silent on this manifest).
    return _manifest([
        _purch(501, "2024-08-01", 1200.00),
        _purch(502, "2024-08-04", 1200.00),
    ])


def _manifest_with_same_day_pair():
    # 501/502 on the SAME day -> DUP_SAME_DAY fires, DUP_WINDOW must not.
    return _manifest([
        _purch(501, "2024-08-01", 1200.00),
        _purch(502, "2024-08-01", 1200.00),
    ])


# ---------------------------------------------------------------------------
# Gate-consistent step outputs (empty issues/e1 -> all five gates pass)
# ---------------------------------------------------------------------------

def _calc():
    return {
        "period": _PERIOD,
        "currency": "SGD",
        "boxes": {
            "box_1_standard_rated_sales": 0.0,
            "box_2_zero_rated_sales": 0.0,
            "box_3_exempt_sales": 0.0,
            "box_4_total_sales": 0.0,
            "box_5_taxable_purchases": 1200.0,
            "box_6_output_tax": 0.0,
            "box_7_input_tax": 84.0,
            "box_8_net_gst": -84.0,
        },
        "fx_invoices_requiring_conversion": [],
        "e1_candidates": [],
        "record_counts": {},
        "credit_note_counts": {},
        "credit_notes_applied": [],
        "anomalies": [],
    }


def _classify():
    return {
        "period": _PERIOD,
        "expected_rate": 0.07,
        "vatgroup_inventory": {
            "IP": {
                "gst_category": "Standard-rated input",
                "side": "purchases",
                "lt_box": "box_5_taxable_purchases",
                "tt_box": "box_7_input_tax",
                "doc_count": 2,
                "known_to_mapping": True,
            }
        },
        "issues": [],
        "summary": {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 0},
    }


def _detect():
    return {
        "period": _PERIOD,
        "severity_counts": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
        "issues": [],
    }


# ---------------------------------------------------------------------------
# Hermetic patch (replicated from test_document_dup_chain._patch_chain)
# ---------------------------------------------------------------------------

def _patch_chain(monkeypatch, manifest):
    monkeypatch.setattr(sap_b1_server, "configure_client", lambda *a, **kw: None)
    monkeypatch.setattr("orchestrator.chain.fetch",     lambda cfg, p: manifest)
    monkeypatch.setattr("orchestrator.chain.calculate", lambda cfg, p: _calc())
    monkeypatch.setattr("orchestrator.chain.classify",  lambda cfg, p: _classify())
    monkeypatch.setattr("orchestrator.chain.detect",    lambda cfg, p: _detect())
    # Empty success-shaped listing -> listing_findings == [] (SEQ_GAP/DUP_CLAIM none).
    monkeypatch.setattr("orchestrator.chain.fetch_listing_data", lambda cfg, p: {
        "period_sales_headers": [], "period_purch_headers": [],
        "all_sales_headers": [],   "all_purch_headers": [],
    })
    # No-contact guard: any real SAP login/request fails fast.
    def _guard(*a, **kw):
        raise AssertionError("real SAP contact attempted in hermetic test")
    monkeypatch.setattr(sap_b1_server.SAPB1Client, "login", _guard)
    monkeypatch.setattr(sap_b1_server.SAPB1Client, "request", _guard)


# ---------------------------------------------------------------------------
# ON: the check runs and its findings land under their OWN key
# ---------------------------------------------------------------------------

class TestEnabledWiring:

    def test_window_pair_surfaced_in_document_dup_window_findings(self, cfg_on, monkeypatch):
        _patch_chain(monkeypatch, _manifest_with_window_pair())
        result, _ = run_chain(cfg_on, _PERIOD)

        assert "document_dup_window_findings" in result, (
            "an enabled dup-window check must attach "
            "result['document_dup_window_findings']"
        )
        findings = result["document_dup_window_findings"]
        assert isinstance(findings, list) and len(findings) == 1
        f = findings[0]
        assert f["check"] == "DUP_WINDOW"
        assert f["doc_nums"] == [501, 502]
        assert f["delta_days"] == 3

    def test_enabled_and_not_firing_yields_empty_list_not_missing_key(self, cfg_on, monkeypatch):
        # ON + nothing to surface is an EMPTY LIST (the check ran, found nothing).
        # Distinct from OFF (no key) and from unavailable (None + status).
        _patch_chain(monkeypatch, _manifest_with_same_day_pair())
        result, _ = run_chain(cfg_on, _PERIOD)

        assert result["document_dup_window_findings"] == []
        assert "document_dup_window_status" not in result, (
            "a clean run that surfaced nothing is NOT 'unavailable' — the status "
            "key is written only when the check threw"
        )

    def test_enabled_does_not_leak_into_listing_findings(self, cfg_on, monkeypatch):
        # listing_findings is SEQ_GAP/DUP_CLAIM only.
        _patch_chain(monkeypatch, _manifest_with_window_pair())
        result, _ = run_chain(cfg_on, _PERIOD)

        assert result["listing_findings"] == []
        for f in (result["listing_findings"] or []):
            assert f.get("check") != "DUP_WINDOW"


# ---------------------------------------------------------------------------
# OFF (the default): NEITHER key is written — this is what protects the oracle
# ---------------------------------------------------------------------------

class TestDisabledAddsNoKeys:

    def test_off_by_default_in_config(self, cfg_off):
        # The OFF precondition for every test below. RED now (AttributeError):
        # the field does not exist yet.
        assert cfg_off.dup_window_enabled is False
        assert cfg_off.dup_window_days is None

    def test_disabled_adds_neither_key(self, cfg_off, monkeypatch):
        # Shape mirrors tests/test_t224_chain_seam.py::test_no_ledger_path_adds_no_keys.
        # The precondition assert is what makes this RED now instead of vacuously
        # green (nothing writes these keys today).
        assert cfg_off.dup_window_enabled is False
        _patch_chain(monkeypatch, _manifest_with_window_pair())
        result, _ = run_chain(cfg_off, _PERIOD)

        assert "document_dup_window_findings" not in result, (
            "a disabled check must add NO findings key — not [], not None; the "
            "frozen replay oracle depends on the OFF path being byte-identical"
        )
        assert "document_dup_window_status" not in result, (
            "'unavailable' means RAN AND THREW — it must never describe the OFF state"
        )

    def test_disabled_leaves_sibling_same_day_key_intact(self, cfg_off, monkeypatch):
        # The new check must not disturb the shipped DUP_SAME_DAY sibling.
        assert cfg_off.dup_window_enabled is False
        _patch_chain(monkeypatch, _manifest_with_same_day_pair())
        result, _ = run_chain(cfg_off, _PERIOD)

        assert "document_dup_findings" in result
        findings = result["document_dup_findings"]
        assert isinstance(findings, list) and len(findings) == 1
        assert findings[0]["check"] == "DUP_SAME_DAY"
        assert findings[0]["doc_nums"] == [501, 502]

    def test_enabled_leaves_sibling_same_day_key_intact(self, cfg_on, monkeypatch):
        # ...and neither must the ENABLED path. Both checks coexist on their own keys.
        _patch_chain(monkeypatch, _manifest_with_same_day_pair())
        result, _ = run_chain(cfg_on, _PERIOD)

        assert result["document_dup_findings"][0]["check"] == "DUP_SAME_DAY"
        assert result["document_dup_window_findings"] == []


# ---------------------------------------------------------------------------
# Box-isolation (invariant 3): the surfacer never moves an F5 box
# ---------------------------------------------------------------------------

class TestBoxIsolation:

    def test_boxes_byte_identical_on_and_off(self, cfg_on, cfg_off, monkeypatch):
        # ON and FIRING vs OFF over the SAME manifest. The "must have fired" assert
        # keeps this from being a vacuous comparison.
        _patch_chain(monkeypatch, _manifest_with_window_pair())
        on_result, _ = run_chain(cfg_on, _PERIOD)
        assert on_result.get("document_dup_window_findings"), (
            "the within-window manifest must produce a DUP_WINDOW finding — "
            "box-isolation is only meaningful when the check has fired"
        )
        boxes_on = on_result["calculate"]["boxes"]

        _patch_chain(monkeypatch, _manifest_with_window_pair())
        off_result, _ = run_chain(cfg_off, _PERIOD)
        boxes_off = off_result["calculate"]["boxes"]

        assert boxes_on == boxes_off, (
            "F5 boxes must be byte-identical whether or not the dup-window check "
            "ran and fired — the surfacer must never mutate the deterministic chain"
        )


# ---------------------------------------------------------------------------
# Failure contract: OWN try block -> None findings + unavailable status
# ---------------------------------------------------------------------------

class TestFailureContract:

    def test_thrown_check_yields_none_and_unavailable_status(self, cfg_on, monkeypatch):
        _patch_chain(monkeypatch, _manifest_with_window_pair())

        # Force the detector (imported into chain's namespace, mirroring
        # detect_same_day_dups) to raise; the chain's OWN try block must degrade to
        # the "unavailable" contract rather than halting the run.
        def _boom(*a, **kw):
            raise RuntimeError("simulated dup-window detector failure")
        monkeypatch.setattr("orchestrator.chain.detect_window_dups", _boom)

        result, _ = run_chain(cfg_on, _PERIOD)

        assert result["document_dup_window_findings"] is None, (
            "a failed run must read None, never [] — [] would falsely mean "
            "'ran cleanly, found nothing'"
        )
        assert result["document_dup_window_status"]["level"] == "unavailable"
        assert result["document_dup_window_status"]["reason"]  # non-empty execution fact

    def test_thrown_check_does_not_take_down_the_sibling(self, cfg_on, monkeypatch):
        # The two dup surfacers have SEPARATE try blocks: DUP_WINDOW throwing must
        # not blank DUP_SAME_DAY.
        _patch_chain(monkeypatch, _manifest_with_same_day_pair())

        def _boom(*a, **kw):
            raise RuntimeError("simulated dup-window detector failure")
        monkeypatch.setattr("orchestrator.chain.detect_window_dups", _boom)

        result, _ = run_chain(cfg_on, _PERIOD)

        assert result["document_dup_window_findings"] is None
        assert result["document_dup_findings"][0]["check"] == "DUP_SAME_DAY"

    def test_thrown_check_leaves_boxes_untouched(self, cfg_on, cfg_off, monkeypatch):
        _patch_chain(monkeypatch, _manifest_with_window_pair())

        def _boom(*a, **kw):
            raise RuntimeError("simulated dup-window detector failure")
        monkeypatch.setattr("orchestrator.chain.detect_window_dups", _boom)

        thrown_result, _ = run_chain(cfg_on, _PERIOD)
        assert thrown_result["document_dup_window_findings"] is None
        boxes_thrown = thrown_result["calculate"]["boxes"]

        _patch_chain(monkeypatch, _manifest_with_window_pair())
        off_result, _ = run_chain(cfg_off, _PERIOD)

        assert boxes_thrown == off_result["calculate"]["boxes"]
