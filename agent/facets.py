"""
agent/facets.py — deterministic, source-agnostic, VIEW-ONLY faceted-filter engine.

T6.3 Slice 1. The deterministic foundation of the "prompt me for details" filter
feature: **data-derived faceted filtering**. The filter vocabulary is COMPUTED from the
actual findings (never hardcoded), proposed values are validated against the REAL domain
(the ⊆-menu discipline — never a silent empty result, never a fabricated value), and a
filter narrows the **view**, never the computation.

This module is the engine ONLY — pure Python, hermetic, token-free. NO dispatch wiring,
NO UI, NO live classifier (those are later slices that sit on top of this engine).

Source-agnostic by construction
--------------------------------
Facets are computed over the **canonical** findings the chain already produces (the
per-finding case files surfaced as the review queue), so the same facets result whether
the feeder was SAP or Excel. The engine itself knows NOTHING about findings: it is generic
over a declared **field-accessor** (``FacetSpec.accessor``). ``finding_facet_specs()`` is
the one place that encodes how a finding's facetable fields are read — change the feeder,
keep the accessors.

Scope of Slice 1 (Terry-approved 2026-06-18)
--------------------------------------------
* Findings facet_specs = ``error_code, counterparty, doc_num`` — the fields the canonical
  findings ACTUALLY carry, declared AND tested here.
* ``f5_box`` is DEFERRED-pending-enrichment: the canonical detect-issues drop ``vat_group``
  at the detect layer (see ``agent/decision_ledger.py`` module docstring), so the
  VatGroup→F5-box mapping cannot be applied, and ``error_code`` does NOT determine the box.
  Deriving an f5_box facet would assert a routing claim the data does not carry, so it is
  intentionally absent. The engine is generic, so it can be added once a finding carries a
  reliable box.
* Proposals / decision-ledger facet_specs are DEFERRED-pending-enrichment too: the
  ``read_proposals`` view buries error_code/counterparty inside ``evidence_refs`` strings,
  and ``read_decision_ledger`` collapses them into the one-way ``fingerprint`` hash (only
  ``disposition`` is cleanly facetable). The engine is generic and will serve those
  collections in a later slice once their views expose the fields.

View-only guarantee
-------------------
The engine NEVER mutates the input collection and NEVER recomputes any F5 box or finding.
``compute_facets`` and ``apply_filters`` are pure projections: they read the declared
fields and return new structures. Filtering a view changes no box (box-isolation is
structural — the F5 summary lives in ``compile_output.calculate``, a different object the
engine never touches).

Zero anthropic import. Zero SDK import. No network, no disk I/O. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence, Union


# ---------------------------------------------------------------------------
# Facet declaration — a name + an accessor that reads the value off one item
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FacetSpec:
    """Declares one facetable field: a ``name`` and an ``accessor`` callable.

    The accessor reads the facet value off a single collection item. Returning ``None``
    means "this item has no value for this facet" — the item is omitted from that facet's
    domain (you cannot meaningfully filter by an absent value), and it matches no filter on
    that facet. This is how the engine stays source-agnostic: the accessor is the ONLY
    field-shape knowledge; the engine itself reads nothing directly.
    """
    name: str
    accessor: Callable[[Any], Any]


# Accepted ``facet_specs`` shapes: a sequence of FacetSpec, or a mapping of
# name -> (FacetSpec | bare accessor callable).
FacetSpecs = Union[Sequence[FacetSpec], Mapping[str, Union[FacetSpec, Callable[[Any], Any]]]]


def _normalize_specs(facet_specs: FacetSpecs) -> dict[str, FacetSpec]:
    """Coerce any accepted facet_specs shape into an ordered ``{name: FacetSpec}`` dict."""
    if isinstance(facet_specs, Mapping):
        out: dict[str, FacetSpec] = {}
        for name, spec in facet_specs.items():
            if isinstance(spec, FacetSpec):
                out[name] = spec
            elif callable(spec):
                out[name] = FacetSpec(name, spec)
            else:
                raise TypeError(
                    f"facet_specs[{name!r}] must be a FacetSpec or a callable, got {type(spec)!r}"
                )
        return out
    return {spec.name: spec for spec in facet_specs}


# ---------------------------------------------------------------------------
# validate_filter results — the ⊆-domain twin of agent.intent.NeedsClarification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Valid:
    """A proposed filter value that IS in the real domain."""
    facet_name: str
    value: Any


@dataclass(frozen=True)
class NotInDomain:
    """A proposed filter value that is NOT in the real domain.

    Carries the ACTUAL domain (the live set of values) so a caller can re-prompt against
    real options — never a silent empty result, never a fabricated value. This is the
    ⊆-domain analogue of ``agent.intent.NeedsClarification``.
    """
    facet_name: str
    value: Any
    domain: tuple


# ---------------------------------------------------------------------------
# The engine — pure projection over declared accessors
# ---------------------------------------------------------------------------

def compute_facets(
    collection: Sequence[Any], facet_specs: FacetSpecs
) -> dict[str, dict[Any, int]]:
    """Return each declared facet's **domain + counts** over *collection*.

    For every facet, reads its accessor across the collection and tallies value -> count.
    A ``None`` value (absent field) is omitted — it never becomes a domain entry. Counts
    are in first-seen (collection) order, so the result is deterministic given the input.

    PURE: reads the collection, mutates nothing, returns fresh dicts.

    Example (canonical 21-finding SBODEMOSG set)::

        {"error_code": {"E1": 8, "NO_GST_REG": 7, "E2": 5, "gst_amount_mismatch": 1},
         "counterparty": {"SG Electronics": 2, ...},   # 10 names; probabilistic finding omitted
         "doc_num": {958: 1, 964: 1, ...}}
    """
    specs = _normalize_specs(facet_specs)
    out: dict[str, dict[Any, int]] = {}
    for name, spec in specs.items():
        counts: dict[Any, int] = {}
        for item in collection:
            value = spec.accessor(item)
            if value is None:
                continue
            counts[value] = counts.get(value, 0) + 1
        out[name] = counts
    return out


def facet_domain(
    collection: Sequence[Any], facet_specs: FacetSpecs, facet_name: str
) -> tuple:
    """Return the live domain (the value tuple) of one facet over *collection*."""
    facets = compute_facets(collection, facet_specs)
    if facet_name not in facets:
        raise ValueError(
            f"unknown facet {facet_name!r}; declared facets: {sorted(facets)}"
        )
    return tuple(facets[facet_name].keys())


def validate_filter(
    facet_name: str, value: Any, domain: Sequence[Any]
) -> Union[Valid, NotInDomain]:
    """Validate a single proposed filter value against the real *domain*.

    Returns ``Valid`` when the value is in the domain, else a ``NotInDomain`` carrying the
    real domain. Never returns a silent empty/None result.
    """
    if value in domain:
        return Valid(facet_name, value)
    return NotInDomain(facet_name, value, tuple(domain))


def _matches(item: Any, allowed: Mapping[str, set], specs: Mapping[str, FacetSpec]) -> bool:
    """True iff *item* satisfies every active filter (intersection / AND semantics)."""
    for fname, allowed_values in allowed.items():
        if specs[fname].accessor(item) not in allowed_values:
            return False
    return True


def apply_filters(
    collection: Sequence[Any],
    filters: Mapping[str, Union[Any, Sequence[Any]]],
    facet_specs: FacetSpecs,
) -> Union[NotInDomain, tuple[list, dict[str, dict[Any, int]]]]:
    """Narrow *collection* by *filters* and return ``(narrowed, remaining_facets)``.

    ``filters`` maps ``facet_name -> value`` or ``facet_name -> [values]``. Semantics:

    * **Intersection (AND across facets):** an item is kept iff, for EVERY filtered facet,
      its value is among the filter's allowed value(s). Multiple values for one facet are
      OR-ed within that facet.
    * **Per-filter validation:** every value is validated against the facet's domain over
      the FULL collection; an invalid value short-circuits the whole call to a structured
      ``NotInDomain`` (never a silently-empty result from a typo'd value).
    * **Empty is legitimate:** a valid combination that genuinely matches no rows returns
      an empty ``narrowed`` list — an honest empty set, not an error.
    * **remaining_facets:** the facets RECOMPUTED over the narrowed set (counts reflect the
      subset), so a caller can drill further.

    An unknown facet NAME in ``filters`` is a caller error (the facet was never declared
    facetable) and raises ``ValueError`` — distinct from ``NotInDomain``, which is a real
    user value missing from a real domain.

    PURE / VIEW-ONLY: the input collection is never mutated; ``narrowed`` is a fresh list;
    no finding and no F5 box is recomputed.
    """
    specs = _normalize_specs(facet_specs)
    full_facets = compute_facets(collection, specs)

    allowed: dict[str, set] = {}
    for fname, fval in filters.items():
        if fname not in specs:
            raise ValueError(
                f"unknown facet {fname!r}; declared facets: {sorted(specs)}"
            )
        domain = tuple(full_facets.get(fname, {}).keys())
        values = list(fval) if isinstance(fval, (list, tuple, set)) else [fval]
        for v in values:
            result = validate_filter(fname, v, domain)
            if isinstance(result, NotInDomain):
                return result
        allowed[fname] = set(values)

    narrowed = [item for item in collection if _matches(item, allowed, specs)]
    remaining_facets = compute_facets(narrowed, specs)
    return narrowed, remaining_facets


# ---------------------------------------------------------------------------
# Findings facet_specs — the ONE place that encodes how a finding is read
# ---------------------------------------------------------------------------
#
# Source-agnostic field extraction over the canonical per-finding case file. Tolerant of
# the three shapes a "finding" travels in (mirrors agent.decision_ledger's tolerance):
#   * a dossier dict with an ``evidence`` slot map (the frozen demo-artifact shape),
#   * a Finding-like object/dict carrying a ``payload`` (agent.dossier.extract_findings),
#   * a flat detect-issue payload dict (error_code / card_name / doc_num at top level).
# Adding a feeder means producing one of these shapes — the accessors do not change.

def _primary_payload(item: Any) -> dict:
    """Pick the canonical detect-issue payload out of a finding-shaped item.

    For a dossier, the evidence map's payload shape varies by finding type: deterministic
    slots carry ``description``/``error_code`` (NO_GST_REG also carries a ``supplier_catalog``
    decoy bearing neither), while the probabilistic ``sap_listing`` carries
    ``message``/``severity``. Selection prefers the description/error_code payload (so the
    decoy is never chosen), then a message/severity payload, then the first dict, then ``{}``.
    Mirrors ``ui.artifacts._primary_evidence_payload`` but kept here so this module imports
    no ``ui`` (layering + purity). Pure: reads only the passed-in item.
    """
    evidence = item.get("evidence") if isinstance(item, dict) else getattr(item, "evidence", None)
    if evidence:
        dict_payloads = [v for v in evidence.values() if isinstance(v, dict)]
        for p in dict_payloads:
            if "description" in p or "error_code" in p:
                return p
        for p in dict_payloads:
            if "message" in p or "severity" in p:
                return p
        return dict_payloads[0] if dict_payloads else {}
    if isinstance(item, dict):
        payload = item.get("payload")
        if isinstance(payload, dict):
            return payload
        return item
    payload = getattr(item, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _finding_error_code(item: Any) -> Any:
    """The canonical error_code: the finding's ``check_id`` (E1/.../gst_amount_mismatch),
    falling back to the payload ``error_code`` when no check_id is carried."""
    if isinstance(item, dict):
        cid = item.get("check_id")
    else:
        cid = getattr(item, "check_id", None)
    if cid:
        return cid
    return _primary_payload(item).get("error_code")


def _finding_counterparty(item: Any) -> Any:
    """The counterparty (``card_name``), or ``None`` when the finding carries none (the
    probabilistic gst_amount_mismatch finding has no counterparty — omitted from the facet)."""
    return _primary_payload(item).get("card_name")


def _finding_doc_num(item: Any) -> Any:
    """The source document number (``doc_num``)."""
    return _primary_payload(item).get("doc_num")


def finding_facet_specs() -> dict[str, FacetSpec]:
    """The declared facetable fields for canonical findings (Slice 1).

    ``error_code, counterparty, doc_num`` — the fields the canonical findings reliably
    carry. ``f5_box`` is intentionally absent (deferred-pending-enrichment; see the module
    docstring): the finding does not carry a reliable box, and error_code does not determine
    one. The values always come from the data.
    """
    return {
        "error_code": FacetSpec("error_code", _finding_error_code),
        "counterparty": FacetSpec("counterparty", _finding_counterparty),
        "doc_num": FacetSpec("doc_num", _finding_doc_num),
    }
