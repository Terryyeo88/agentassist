"""
tests/test_t63_facet_engine.py — T6.3 Slice 1: the deterministic facet engine.

Acceptance for the pure, source-agnostic, VIEW-ONLY facet engine (agent/facets.py):

  * compute_facets returns correct domains + counts over the frozen SBODEMOSG findings
    (the canonical 21-finding set);
  * apply_filters narrows correctly for one facet and INTERSECTS correctly for two; an
    empty result is a legitimate empty set, not an error;
  * validate_filter returns NotInDomain (carrying the real domain) for an unknown value
    and Valid for a real one;
  * remaining_facets are recomputed over the narrowed subset;
  * BOX-ISOLATION: the F5 summary is byte-identical before/after any apply_filters call;
  * HERMETIC + PURE: agent/facets.py imports stdlib only (no anthropic / network /
    orchestrator / engine / ui / dispatch / classifier wiring); orchestrator/ untouched.

All hermetic — no tokens, no network, no SAP. Frozen artifacts only.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from agent.facets import (
    FacetSpec,
    NotInDomain,
    Valid,
    apply_filters,
    compute_facets,
    facet_domain,
    finding_facet_specs,
    validate_filter,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS = _REPO_ROOT / "tests" / "fixtures" / "demo-artifacts"


# ---------------------------------------------------------------------------
# Fixtures — the canonical 21-finding SBODEMOSG set (frozen dossiers)
# ---------------------------------------------------------------------------

@pytest.fixture()
def findings() -> list[dict]:
    """The canonical per-finding case files: the frozen 21-finding dossier set."""
    return json.loads((_ARTIFACTS / "dossiers.json").read_text(encoding="utf-8"))


@pytest.fixture()
def specs() -> dict:
    return finding_facet_specs()


# ---------------------------------------------------------------------------
# compute_facets — correct domains + counts over the canonical findings
# ---------------------------------------------------------------------------

class TestComputeFacets:
    def test_error_code_domain_and_counts(self, findings, specs):
        facets = compute_facets(findings, specs)
        assert facets["error_code"] == {
            "E1": 8,
            "NO_GST_REG": 7,
            "E2": 5,
            "gst_amount_mismatch": 1,
        }

    def test_error_code_counts_sum_to_full_set(self, findings, specs):
        assert sum(compute_facets(findings, specs)["error_code"].values()) == 21

    def test_counterparty_domain(self, findings, specs):
        cp = compute_facets(findings, specs)["counterparty"]
        # 10 real counterparties; the 1 probabilistic finding carries no card_name and is
        # OMITTED from the facet (None is never a domain entry) -> counts sum to 20.
        assert set(cp) == {
            "SG Electronics", "Aquent Systems", "Acme Associates", "Far East Imports",
            "SMD Technologies", "Lasercom", "ADA Technologies", "Lumarx",
            "CTI Computers", "Blockies Corporation",
        }
        assert cp["Acme Associates"] == 6
        assert None not in cp
        assert sum(cp.values()) == 20

    def test_doc_num_domain(self, findings, specs):
        dn = compute_facets(findings, specs)["doc_num"]
        assert None not in dn
        assert sum(dn.values()) == 21          # every finding carries a doc_num
        assert len(dn) == 19                    # 19 distinct documents (some repeat)
        assert 958 in dn and 592 in dn

    def test_only_declared_facets_returned(self, findings, specs):
        # f5_box is DEFERRED — it must NOT appear as a facet.
        facets = compute_facets(findings, specs)
        assert set(facets) == {"error_code", "counterparty", "doc_num"}
        assert "f5_box" not in facets

    def test_empty_collection_yields_empty_domains(self, specs):
        facets = compute_facets([], specs)
        assert facets == {"error_code": {}, "counterparty": {}, "doc_num": {}}

    def test_accepts_sequence_of_facetspec(self, findings):
        seq = list(finding_facet_specs().values())
        assert compute_facets(findings, seq)["error_code"]["E1"] == 8


# ---------------------------------------------------------------------------
# validate_filter — ⊆-domain: Valid vs NotInDomain carrying the real domain
# ---------------------------------------------------------------------------

class TestValidateFilter:
    def test_valid_value_returns_valid(self, findings, specs):
        domain = facet_domain(findings, specs, "error_code")
        result = validate_filter("error_code", "E1", domain)
        assert result == Valid("error_code", "E1")

    def test_unknown_value_returns_not_in_domain_with_real_domain(self, findings, specs):
        domain = facet_domain(findings, specs, "error_code")
        result = validate_filter("error_code", "E9", domain)
        assert isinstance(result, NotInDomain)
        assert result.facet_name == "error_code"
        assert result.value == "E9"
        # The structured result carries the ACTUAL domain — never a silent empty result.
        assert set(result.domain) == {"E1", "E2", "NO_GST_REG", "gst_amount_mismatch"}

    def test_unknown_counterparty_returns_not_in_domain(self, findings, specs):
        domain = facet_domain(findings, specs, "counterparty")
        result = validate_filter("counterparty", "Nonexistent Pte Ltd", domain)
        assert isinstance(result, NotInDomain)
        assert "Acme Associates" in result.domain


# ---------------------------------------------------------------------------
# apply_filters — single / intersection / empty / remaining_facets
# ---------------------------------------------------------------------------

class TestApplyFilters:
    def test_single_facet_narrows(self, findings, specs):
        narrowed, _ = apply_filters(findings, {"error_code": "E1"}, specs)
        assert len(narrowed) == 8
        assert all(f.get("check_id") == "E1" for f in narrowed)

    def test_single_facet_list_value_is_or_within_facet(self, findings, specs):
        narrowed, _ = apply_filters(findings, {"error_code": ["E1", "E2"]}, specs)
        assert len(narrowed) == 13          # 8 + 5

    def test_two_facets_intersect(self, findings, specs):
        # Acme Associates appears on 6 findings; intersect with error_code to a subset.
        acme_only, _ = apply_filters(findings, {"counterparty": "Acme Associates"}, specs)
        n_acme = len(acme_only)
        assert n_acme == 6
        narrowed, _ = apply_filters(
            findings, {"counterparty": "Acme Associates", "error_code": "NO_GST_REG"}, specs
        )
        # Intersection is a subset of each single filter and AND-consistent.
        assert len(narrowed) <= n_acme
        assert all(
            f.get("check_id") == "NO_GST_REG"
            and _card_name(f) == "Acme Associates"
            for f in narrowed
        )

    def test_empty_combination_is_legitimate_empty_set(self, findings, specs):
        # A VALID-but-disjoint combination: gst_amount_mismatch has no counterparty, so
        # pairing it with any real counterparty genuinely matches nothing -> [] (not error).
        narrowed, remaining = apply_filters(
            findings,
            {"error_code": "gst_amount_mismatch", "counterparty": "Acme Associates"},
            specs,
        )
        assert narrowed == []
        assert remaining == {"error_code": {}, "counterparty": {}, "doc_num": {}}

    def test_invalid_value_short_circuits_to_not_in_domain(self, findings, specs):
        result = apply_filters(findings, {"error_code": "E9"}, specs)
        assert isinstance(result, NotInDomain)
        assert result.value == "E9"
        assert set(result.domain) == {"E1", "E2", "NO_GST_REG", "gst_amount_mismatch"}

    def test_invalid_value_in_list_short_circuits(self, findings, specs):
        result = apply_filters(findings, {"error_code": ["E1", "E9"]}, specs)
        assert isinstance(result, NotInDomain)
        assert result.value == "E9"

    def test_unknown_facet_name_raises(self, findings, specs):
        # An undeclared facet is a caller error, distinct from NotInDomain (a real value miss).
        with pytest.raises(ValueError):
            apply_filters(findings, {"f5_box": "box_1"}, specs)

    def test_remaining_facets_recomputed_over_subset(self, findings, specs):
        narrowed, remaining = apply_filters(findings, {"error_code": "E1"}, specs)
        # error_code collapses to the single filtered value; counts reflect the subset only.
        assert remaining["error_code"] == {"E1": 8}
        assert "NO_GST_REG" not in remaining["error_code"]
        # counterparty domain over the subset is a subset of the full counterparty domain.
        full_cp = set(compute_facets(findings, specs)["counterparty"])
        assert set(remaining["counterparty"]).issubset(full_cp)
        assert sum(remaining["error_code"].values()) == 8


# ---------------------------------------------------------------------------
# View-only / purity of the data structures
# ---------------------------------------------------------------------------

class TestViewOnly:
    def test_input_collection_not_mutated(self, findings, specs):
        before = json.dumps(findings, sort_keys=True, ensure_ascii=False)
        apply_filters(findings, {"error_code": "E1"}, specs)
        compute_facets(findings, specs)
        after = json.dumps(findings, sort_keys=True, ensure_ascii=False)
        assert before == after

    def test_narrowed_is_a_fresh_list(self, findings, specs):
        narrowed, _ = apply_filters(findings, {"error_code": ["E1", "E2", "NO_GST_REG",
                                                               "gst_amount_mismatch"]}, specs)
        assert narrowed is not findings
        # Same membership (all kept) but a distinct list object.
        assert len(narrowed) == len(findings)


# ---------------------------------------------------------------------------
# Box-isolation — the F5 summary is byte-identical before/after a view filter
# ---------------------------------------------------------------------------

class TestBoxIsolation:
    def test_f5_summary_byte_identical_across_filter(self, findings, specs):
        from ui.artifacts import load_demo_artifacts
        from api.viewmodel import f5_summary

        artifacts = load_demo_artifacts(_ARTIFACTS)
        before = json.dumps(f5_summary(artifacts), sort_keys=True, ensure_ascii=False)

        # Filtering the (separate) findings view must touch no box.
        apply_filters(findings, {"error_code": "E1"}, specs)
        apply_filters(findings, {"counterparty": "Acme Associates"}, specs)

        after = json.dumps(f5_summary(artifacts), sort_keys=True, ensure_ascii=False)
        assert before == after
        # And the underlying calculate.boxes object is itself unchanged.
        boxes = ((artifacts.review_result or {}).get("compile_output") or {}).get("calculate")
        assert boxes is not None and boxes.get("boxes")


# ---------------------------------------------------------------------------
# Hermetic + pure — AST/import scan; engine-only (no wiring added)
# ---------------------------------------------------------------------------

def _imports_of(path: Path) -> list[str]:
    """All imported module names anywhere in the file (top-level OR deferred)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [n.name for n in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


_FACETS = _REPO_ROOT / "agent" / "facets.py"

# Top-level packages a PURE, view-only engine must never reach for.
_BANNED_ROOTS = {
    "anthropic", "claude_agent_sdk",          # no model / SDK
    "orchestrator", "engine",                  # no computation coupling (boundary stays here)
    "ui", "api", "streamlit", "fastapi",       # no UI / surface coupling
    "socket", "http", "urllib", "requests", "httpx",  # no network
}

# Wiring modules whose presence would mean this slice is no longer engine-only.
_WIRING_MODULES = {
    "agent.intent", "agent.intent_classifier", "agent.classifier_factory",
    "agent.dispatch_exec", "agent.executor", "agent.loop",
}


class TestHermeticPure:
    def test_facets_imports_stdlib_only(self):
        imported = _imports_of(_FACETS)
        roots = {name.split(".")[0] for name in imported if name}
        offenders = roots & _BANNED_ROOTS
        assert not offenders, f"agent/facets.py must import stdlib only; saw {sorted(offenders)}"

    def test_facets_adds_no_dispatch_ui_or_classifier_wiring(self):
        imported = set(_imports_of(_FACETS))
        wired = imported & _WIRING_MODULES
        assert not wired, f"engine-only slice must add no wiring; saw {sorted(wired)}"

    def test_importing_facets_does_not_load_anthropic(self):
        # Runtime half of the scan: importing the engine in a CLEAN interpreter pulls no
        # model SDK / UI / network. A subprocess avoids sys.modules pollution from other
        # tests in the full-suite process (which legitimately import streamlit/anthropic).
        import subprocess

        code = (
            "import importlib, sys\n"
            "importlib.import_module('agent.facets')\n"
            "banned = [m for m in ('anthropic','claude_agent_sdk','streamlit','fastapi',"
            "'orchestrator','engine') if m in sys.modules]\n"
            "print('BANNED:' + ','.join(banned))\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, check=True,
        ).stdout
        assert "BANNED:" in out
        loaded = out.split("BANNED:", 1)[1].strip()
        assert loaded == "", f"importing agent.facets must load none of these; loaded {loaded}"

    def test_orchestrator_untouched_by_facets(self):
        # orchestrator/ must not reach for the new engine.
        for py in (_REPO_ROOT / "orchestrator").rglob("*.py"):
            assert "agent.facets" not in " ".join(_imports_of(py)), f"{py} imports agent.facets"


# ---------------------------------------------------------------------------
# Generic-engine sanity — accessors are the only field knowledge
# ---------------------------------------------------------------------------

class TestGenericEngine:
    def test_engine_is_collection_agnostic(self):
        # The engine knows nothing about findings — give it arbitrary records + an accessor.
        rows = [{"k": "a"}, {"k": "b"}, {"k": "a"}, {"k": None}]
        specs = {"kind": FacetSpec("kind", lambda r: r["k"])}
        assert compute_facets(rows, specs) == {"kind": {"a": 2, "b": 1}}
        narrowed, remaining = apply_filters(rows, {"kind": "a"}, specs)
        assert len(narrowed) == 2
        assert remaining == {"kind": {"a": 2}}

    def test_bare_callable_accepted_as_spec(self):
        rows = [{"k": 1}, {"k": 2}, {"k": 1}]
        assert compute_facets(rows, {"kind": lambda r: r["k"]}) == {"kind": {1: 2, 2: 1}}


def _card_name(dossier: dict):
    from agent.facets import _finding_counterparty
    return _finding_counterparty(dossier)
