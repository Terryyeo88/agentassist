"""Source-system display labels — single source of truth for provenance strings.

D-2026-07-20-source-provenance: report/ and api/ render the data-source NAME from
``ClientConfig.source_system`` (or the api response's ``source_kind``) through this
mapping, never from a hardcoded literal. Both Xero variants (the F5-box and the
sales-invoice readers) render the same client-facing "Xero" label — the F5-vs-sales
distinction is internal and must not leak into client-facing text (ruling M2).

Fallback semantics (invariant-auditor caveats 1-2): a missing / ``None`` / empty
``source_system`` is treated as ``"sap_b1"`` (the ClientConfig default) so legal
text can never render "None"; an unknown label falls back to the raw string so a
future source (e.g. ``myob``) degrades honestly instead of masquerading as SAP.
"""
from __future__ import annotations

#: Short display name, used in body prose ("Computed from {label} invoice ... lines").
SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "sap_b1": "SAP B1",
    "xero": "Xero",
    "xero_sales": "Xero",
    "extract": "uploaded extract",
}

#: Long display name, used where the full product name reads naturally
#: (the legal disclaimer). Differs from the short form only for SAP.
SOURCE_DISPLAY_NAMES_LONG: dict[str, str] = {
    **SOURCE_DISPLAY_NAMES,
    "sap_b1": "SAP Business One",
}


def source_display_name(source_system: str | None, long: bool = False) -> str:
    """Display label for a ``source_system`` value; None/empty -> SAP, unknown -> raw."""
    key = (source_system or "sap_b1").strip() or "sap_b1"
    table = SOURCE_DISPLAY_NAMES_LONG if long else SOURCE_DISPLAY_NAMES
    return table.get(key, key)
