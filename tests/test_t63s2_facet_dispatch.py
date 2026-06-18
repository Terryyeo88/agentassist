"""T6.3 Slice 2 — wire the facet engine into dispatch (view-only, box-isolated).

Slice 1 built the pure facet engine (agent/facets.py) but wired it to nothing. This
slice wires it into the EXECUTION layer (agent/dispatch_exec.py::execute_intent) so a
RUN_REVIEW result carries the data-derived filter MENU (facets over the canonical
findings) and accepts explicit, surface-supplied filter params that narrow only the
findings VIEW — validated against the real domain, box-isolated, never silently empty,
never an exception.

The contract under test:

  (a) RUN_REVIEW, no filters → available_facets = the canonical 21-finding domains;
      the findings rows are the full set; the F5 boxes are intact.
  (b) A valid single filter narrows the rows, recomputes remaining_facets over the
      subset, echoes applied_filters — and leaves the F5 boxes byte-identical.
  (c) A two-facet filter INTERSECTS; a valid-but-disjoint combo is a legitimate EMPTY
      set (not an error).
  (d) An invalid filter VALUE → a structured filter_rejection carrying the real
      domain; NOT a silent empty; NOT an exception; the full findings + F5 boxes stand.
  (e) An unknown facet NAME → a structured filter_rejection (not an exception at the
      dispatch seam); full findings stand.
  (f) Filters on a non-findings intent → a structured rejection; the underlying read
      still returns its rows unfiltered.
  (g) BOX ISOLATION: the F5 summary is byte-identical across no-filter / valid /
      invalid / two-filter runs.
  (h) to_dict() round-trips all new fields as JSON.
  (i) PURITY: agent/dispatch_exec.py imports agent.facets and stays free of
      anthropic / orchestrator / ui / fastapi / network / SAP; orchestrator/ untouched.

Hermetic: frozen artifacts only, no live model, no SAP, no tokens.
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from agent.dispatch_exec import (
    FILTER_NOT_IN_DOMAIN,
    FILTER_UNKNOWN_FACET,
    FILTER_UNSUPPORTED_INTENT,
    execute_intent,
    load_frozen_artifacts,
)

_REVIEW_PARAMS = {"client_id": "ACME", "period": "2024Q4"}


@pytest.fixture
def artifacts():
    return load_frozen_artifacts()


def _f5(result):
    return json.dumps(result.data["f5_summary"], sort_keys=True, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# (a) RUN_REVIEW, no filters → the full data-derived menu + full rows
# --------------------------------------------------------------------------- #

def test_run_review_no_filters_attaches_canonical_facet_menu(artifacts):
    result = execute_intent("RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts)
    assert result.outcome == "executed"
    facets = result.data["available_facets"]
    assert facets["error_code"] == {
        "E1": 8, "NO_GST_REG": 7, "E2": 5, "gst_amount_mismatch": 1,
    }
    assert len(facets["counterparty"]) == 10
    assert len(facets["doc_num"]) == 19
    # No filter: rows = full findings; nothing applied / rejected.
    assert result.data["findings"] == artifacts.dossiers
    assert len(result.data["findings"]) == 21
    assert result.data["applied_filters"] == {}
    assert result.data["filter_rejection"] is None
    # remaining over the (unnarrowed) view equals the full menu.
    assert result.data["remaining_facets"] == facets
    # The full dossiers contract is preserved unchanged.
    assert result.data["dossiers"] == artifacts.dossiers


# --------------------------------------------------------------------------- #
# (b) valid single filter narrows + remaining recomputed + echo
# --------------------------------------------------------------------------- #

def test_valid_single_filter_narrows_rows(artifacts):
    result = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters={"error_code": "E1"}
    )
    assert result.outcome == "executed"
    rows = result.data["findings"]
    assert len(rows) == 8
    assert all(f.get("check_id") == "E1" for f in rows)
    # remaining_facets recomputed over the narrowed subset.
    assert result.data["remaining_facets"]["error_code"] == {"E1": 8}
    assert result.data["applied_filters"] == {"error_code": "E1"}
    assert result.data["filter_rejection"] is None
    # available_facets is still the FULL menu (unchanged by narrowing).
    assert result.data["available_facets"]["error_code"] == {
        "E1": 8, "NO_GST_REG": 7, "E2": 5, "gst_amount_mismatch": 1,
    }
    # dossiers stays full; only the view narrowed.
    assert len(result.data["dossiers"]) == 21


def test_valid_single_filter_keeps_f5_byte_identical(artifacts):
    base = execute_intent("RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts)
    filtered = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters={"error_code": "E1"}
    )
    assert _f5(filtered) == _f5(base)


# --------------------------------------------------------------------------- #
# (c) two-facet intersection + legitimate empty set
# --------------------------------------------------------------------------- #

def test_two_facet_intersection(artifacts):
    flt = {"counterparty": "Acme Associates", "error_code": "NO_GST_REG"}
    result = execute_intent("RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters=flt)
    rows = result.data["findings"]
    # AND-across: every row matches BOTH facets.
    assert rows  # this combination is non-empty
    assert all(f.get("check_id") == "NO_GST_REG" for f in rows)
    from agent.facets import _finding_counterparty
    assert all(_finding_counterparty(f) == "Acme Associates" for f in rows)
    # Equals the manual intersection over the canonical set.
    expected = [
        f for f in artifacts.dossiers
        if f.get("check_id") == "NO_GST_REG"
        and _finding_counterparty(f) == "Acme Associates"
    ]
    assert len(rows) == len(expected)
    assert result.data["applied_filters"] == flt
    assert result.data["filter_rejection"] is None


def test_disjoint_valid_combo_is_legitimate_empty_set(artifacts):
    # gst_amount_mismatch carries no counterparty, so pairing it with any real
    # counterparty matches nothing — an honest empty set, NOT a rejection.
    flt = {"error_code": "gst_amount_mismatch", "counterparty": "Acme Associates"}
    result = execute_intent("RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters=flt)
    assert result.outcome == "executed"
    assert result.data["findings"] == []
    assert result.data["filter_rejection"] is None
    assert result.data["applied_filters"] == flt
    assert result.data["remaining_facets"] == {
        "error_code": {}, "counterparty": {}, "doc_num": {},
    }


# --------------------------------------------------------------------------- #
# (d) invalid filter value → structured rejection, full rows stand
# --------------------------------------------------------------------------- #

def test_invalid_filter_value_is_structured_rejection(artifacts):
    result = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters={"error_code": "E9"}
    )
    # NOT an exception, NOT a silent empty: the full findings + boxes still stand.
    assert result.outcome == "executed"
    rej = result.data["filter_rejection"]
    assert rej is not None
    assert rej["reason"] == FILTER_NOT_IN_DOMAIN
    assert rej["facet"] == "error_code"
    assert rej["value"] == "E9"
    assert set(rej["domain"]) == {"E1", "E2", "NO_GST_REG", "gst_amount_mismatch"}
    # Full (unfiltered) findings stand; nothing applied.
    assert len(result.data["findings"]) == 21
    assert result.data["applied_filters"] == {}


def test_invalid_value_keeps_f5_byte_identical(artifacts):
    base = execute_intent("RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts)
    rejected = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters={"error_code": "E9"}
    )
    assert _f5(rejected) == _f5(base)


def test_invalid_value_in_list_short_circuits_to_rejection(artifacts):
    result = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts,
        filters={"error_code": ["E1", "E9"]},
    )
    rej = result.data["filter_rejection"]
    assert rej["reason"] == FILTER_NOT_IN_DOMAIN
    assert rej["value"] == "E9"
    assert len(result.data["findings"]) == 21  # nothing applied


# --------------------------------------------------------------------------- #
# (e) unknown facet NAME → structured rejection (not an exception at the seam)
# --------------------------------------------------------------------------- #

def test_unknown_facet_name_is_structured_rejection_not_exception(artifacts):
    result = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters={"f5_box": "box_1"}
    )
    rej = result.data["filter_rejection"]
    assert rej["reason"] == FILTER_UNKNOWN_FACET
    assert "f5_box" in rej["requested_filters"]
    assert set(rej["available_facets"]) == {"error_code", "counterparty", "doc_num"}
    assert len(result.data["findings"]) == 21  # full rows still stand


# --------------------------------------------------------------------------- #
# (f) filters on a non-findings intent → structured rejection, rows unfiltered
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "intent, params, rows_key",
    [
        ("SHOW_LEDGER", {"client_id": "ACME"}, "ledger"),
        ("SHOW_PROPOSALS", {"client_id": "ACME"}, "proposals"),
        ("SHOW_PRIOR_ADJUDICATIONS", {"client_id": "A", "period": "P"}, "adjudications"),
    ],
)
def test_filters_on_non_findings_intent_rejected_rows_unfiltered(
    artifacts, intent, params, rows_key
):
    plain = execute_intent(intent, params, artifacts=artifacts)
    filtered = execute_intent(
        intent, params, artifacts=artifacts, filters={"error_code": "E1"}
    )
    assert filtered.outcome == "executed"
    rej = filtered.data["filter_rejection"]
    assert rej is not None and rej["reason"] == FILTER_UNSUPPORTED_INTENT
    # The underlying read returns the SAME rows, unfiltered.
    assert filtered.data[rows_key] == plain.data[rows_key]


def test_non_findings_intent_no_filters_unchanged(artifacts):
    # With no filters, a non-findings intent gets NO filter_rejection key (unchanged).
    result = execute_intent("SHOW_LEDGER", {"client_id": "ACME"}, artifacts=artifacts)
    assert "filter_rejection" not in result.data


# --------------------------------------------------------------------------- #
# (g) BOX ISOLATION — F5 byte-identical across all four filter scenarios
# --------------------------------------------------------------------------- #

def test_box_isolation_across_all_filter_scenarios(artifacts):
    no_filter = execute_intent("RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts)
    valid = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters={"error_code": "E1"}
    )
    invalid = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters={"error_code": "E9"}
    )
    two = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts,
        filters={"error_code": "NO_GST_REG", "counterparty": "Acme Associates"},
    )
    base = _f5(no_filter)
    assert _f5(valid) == base
    assert _f5(invalid) == base
    assert _f5(two) == base
    # And the frozen source boxes are themselves never mutated.
    assert no_filter.data["f5_summary"]["boxes"] == (
        artifacts.review_result["compile_output"]["calculate"]["boxes"]
    )


def test_filtering_does_not_mutate_frozen_dossiers(artifacts):
    before = json.dumps(artifacts.dossiers, sort_keys=True, ensure_ascii=False)
    execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters={"error_code": "E1"}
    )
    after = json.dumps(artifacts.dossiers, sort_keys=True, ensure_ascii=False)
    assert before == after


# --------------------------------------------------------------------------- #
# (h) serialisable unchanged — all new fields JSON round-trip
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "filters",
    [
        None,
        {"error_code": "E1"},
        {"error_code": "E9"},                                  # rejection
        {"f5_box": "box_1"},                                   # unknown facet
        {"error_code": "NO_GST_REG", "counterparty": "Acme Associates"},
    ],
)
def test_to_dict_round_trips_new_fields_as_json(artifacts, filters):
    result = execute_intent(
        "RUN_REVIEW", _REVIEW_PARAMS, artifacts=artifacts, filters=filters
    )
    blob = json.dumps(result.to_dict())
    back = json.loads(blob)
    assert back["intent"] == "RUN_REVIEW"
    for key in (
        "available_facets", "findings", "remaining_facets",
        "applied_filters", "filter_rejection",
    ):
        assert key in back["data"]


# --------------------------------------------------------------------------- #
# (i) PURITY — dispatch_exec imports agent.facets and stays pure; orchestrator clean
# --------------------------------------------------------------------------- #

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DISPATCH = _REPO_ROOT / "agent" / "dispatch_exec.py"

_BANNED_ROOTS = {
    "anthropic", "streamlit", "fastapi", "requests", "httpx", "urllib",
    "socket", "aiohttp", "orchestrator", "ui",
    "sap", "sap_client", "service_layer",
}


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
    return roots


def test_dispatch_exec_imports_agent_facets_and_stays_pure():
    roots = _import_roots(_DISPATCH)
    assert "agent" in roots  # agent.facets (+ agent.* siblings)
    assert not (roots & _BANNED_ROOTS)


def test_dispatch_exec_imports_the_facet_engine_by_name():
    tree = ast.parse(_DISPATCH.read_text(encoding="utf-8"))
    facet_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "agent.facets" in facet_modules


def test_orchestrator_does_not_import_dispatch_exec():
    for py in (_REPO_ROOT / "orchestrator").rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "dispatch_exec" not in src, f"{py} reaches into dispatch_exec"
