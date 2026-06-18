"""tests/test_t63s3a_command_filters.py — T6.3 Slice 3a (API filter-input threading).

Slice 2 wired the facet engine into ``execute_intent`` (a VIEW-only ``filters`` param)
and made the RUN_REVIEW response already carry ``available_facets / findings /
remaining_facets / applied_filters / filter_rejection``. But ``POST /command`` called
``execute_intent`` WITHOUT filters — a client could receive the menu but not SEND a
filter. Slice 3a is the backend seam only: ``POST /command`` reads an optional
``filters`` field and threads it to ``execute_intent(filters=...)``. The enriched
response already serialises (Slice 2's ``to_dict()``); this slice only enables INPUT.

Framing held under test: filters are a VIEW parameter, surface-supplied, validated
DOWNSTREAM by the dispatch against the real domain. The API does NO domain validation
of its own — an off-domain value flows through to a structured ``filter_rejection`` in
the **200** body (not a 4xx). Identity (``client_id``/``period``) handling is unchanged.

Hermetic: frozen artifacts, scripted classifier (no AGENT_UI_CLASSIFIER), no tokens.
NO frontend (Slice 3b); NO NL extraction (Slice 4); findings facets only.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.app import app

# Scripted curated utterances (mirrors tests/test_t62_command.py).
U_RUN_REVIEW = "Run the GST review for Acme for 2024-Q1"
U_SHOW_LEDGER = "Show me the justification ledger for Acme"

SURFACE = {"client_id": "sbodemosg", "period": "2024Q3"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _command(client: TestClient, utterance: str, **extra) -> dict:
    """POST /command with the scripted surface context; assert a 200 and return the body."""
    resp = client.post("/command", json={"utterance": utterance, **SURFACE, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── RUN_REVIEW, no filters → the full data-derived menu + full rows ───────────────────

def test_run_review_no_filters_carries_canonical_menu_and_full_findings(client: TestClient):
    body = _command(client, U_RUN_REVIEW)
    assert body["kind"] == "result" and body["intent"] == "RUN_REVIEW"
    data = body["execution"]["data"]
    assert data["available_facets"]["error_code"] == {
        "E1": 8, "NO_GST_REG": 7, "E2": 5, "gst_amount_mismatch": 1,
    }
    assert len(data["available_facets"]["counterparty"]) == 10
    assert len(data["available_facets"]["doc_num"]) == 19
    assert len(data["findings"]) == 21
    assert data["applied_filters"] == {}
    assert data["filter_rejection"] is None
    assert data["f5_summary"]["boxes"], "F5 summary intact with no filter"


# ── valid single filter narrows + remaining recomputed + echo; F5 byte-identical ──────

def test_valid_filter_narrows_findings_and_keeps_f5_byte_identical(client: TestClient):
    base = _command(client, U_RUN_REVIEW)
    base_f5 = json.dumps(base["execution"]["data"]["f5_summary"], sort_keys=True)

    body = _command(client, U_RUN_REVIEW, filters={"error_code": "E1"})
    data = body["execution"]["data"]
    assert len(data["findings"]) == 8
    assert all(f.get("check_id") == "E1" for f in data["findings"])
    assert data["remaining_facets"]["error_code"] == {"E1": 8}
    assert data["applied_filters"] == {"error_code": "E1"}
    assert data["filter_rejection"] is None
    # F5 summary is byte-identical to the no-filter response (box isolation at the seam).
    assert json.dumps(data["f5_summary"], sort_keys=True) == base_f5


# ── invalid filter VALUE → structured rejection in the 200 body; rows + F5 intact ─────

def test_invalid_filter_value_yields_rejection_in_200_body(client: TestClient):
    body = _command(client, U_RUN_REVIEW, filters={"error_code": "E9"})
    data = body["execution"]["data"]
    rejection = data["filter_rejection"]
    assert rejection is not None and rejection["reason"] == "not_in_domain"
    assert rejection["facet"] == "error_code" and rejection["value"] == "E9"
    # The rejection carries the REAL domain; full findings + F5 still stand.
    assert "E1" in rejection["domain"]
    assert len(data["findings"]) == 21
    assert data["applied_filters"] == {}
    assert data["f5_summary"]["boxes"]


# ── two-facet intersection + legitimate empty combo ───────────────────────────────────

def test_two_facet_intersection_threads_correctly(client: TestClient):
    body = _command(
        client, U_RUN_REVIEW,
        filters={"counterparty": "Acme Associates", "error_code": "NO_GST_REG"},
    )
    data = body["execution"]["data"]
    assert data["findings"], "this combination is non-empty"
    assert all(f.get("check_id") == "NO_GST_REG" for f in data["findings"])
    assert data["applied_filters"] == {
        "counterparty": "Acme Associates", "error_code": "NO_GST_REG",
    }
    assert data["filter_rejection"] is None


def test_legitimate_empty_combo_is_empty_list_not_error(client: TestClient):
    # gst_amount_mismatch carries no counterparty, so pairing it with a real counterparty
    # genuinely matches nothing -> an empty findings list (NOT a rejection, NOT an error).
    body = _command(
        client, U_RUN_REVIEW,
        filters={"error_code": "gst_amount_mismatch", "counterparty": "Acme Associates"},
    )
    data = body["execution"]["data"]
    assert data["findings"] == []
    assert data["filter_rejection"] is None
    assert data["applied_filters"] == {
        "error_code": "gst_amount_mismatch", "counterparty": "Acme Associates",
    }


# ── filters on a non-findings intent → unsupported_intent rejection; rows unfiltered ──

def test_filters_on_non_findings_intent_are_rejected_rows_unfiltered(client: TestClient):
    body = _command(client, U_SHOW_LEDGER, filters={"error_code": "E1"})
    assert body["kind"] == "result" and body["intent"] == "SHOW_LEDGER"
    data = body["execution"]["data"]
    assert data["filter_rejection"]["reason"] == "unsupported_intent"
    # The underlying read still returns its rows, unfiltered.
    assert isinstance(data["ledger"], list) and data["ledger"]


# ── box isolation at the seam: F5 byte-identical across no-filter / valid / invalid ───

def test_f5_summary_byte_identical_across_filter_outcomes(client: TestClient):
    none = _command(client, U_RUN_REVIEW)
    valid = _command(client, U_RUN_REVIEW, filters={"error_code": "E1"})
    invalid = _command(client, U_RUN_REVIEW, filters={"error_code": "E9"})

    def f5(b: dict) -> str:
        return json.dumps(b["execution"]["data"]["f5_summary"], sort_keys=True)

    assert f5(none) == f5(valid) == f5(invalid)


# ── identity untouched: a request WITHOUT filters is byte-identical to filters={} ─────

def test_request_without_filters_is_byte_identical_to_empty_filters(client: TestClient):
    without = client.post("/command", json={"utterance": U_RUN_REVIEW, **SURFACE})
    empty = client.post("/command", json={"utterance": U_RUN_REVIEW, **SURFACE, "filters": {}})
    assert without.status_code == 200 and empty.status_code == 200
    # The optional filters field defaults to empty; the no-filters response is unchanged.
    assert without.json() == empty.json()
    assert without.json()["execution"]["data"]["applied_filters"] == {}
