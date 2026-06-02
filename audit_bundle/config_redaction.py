"""config_redaction.py — extract an allow-listed, secrets-free config dict from ClientConfig."""

from __future__ import annotations

from config.loader import ClientConfig

# Explicit allow-list.  Every field NOT listed here is excluded by default,
# so a new secret field added to ClientConfig cannot leak into a bundle.
_ALLOW_LIST: frozenset[str] = frozenset({
    "client_id",
    "client_name",
    "gst_registration_number",
    "applicable_gst_rate",
    "service_layer_url",
    "company_db",
    "fiscal_year_start_month",
    "custom_vat_groups",
    "completeness_threshold",
    "reviewer_name",
    "firm_name",
})

# Fields that must never enter the bundle even if inadvertently added to the allow-list.
_DENY_ALWAYS: frozenset[str] = frozenset({"username", "password", "ssl_verify"})


def redact_config(cfg: ClientConfig) -> dict:
    """Return an allow-listed dict suitable for writing to config.json in an audit bundle.

    username, password, and ssl_verify are unconditionally excluded.
    Any field added to ClientConfig in the future is excluded by default.
    """
    result = {}
    for field in _ALLOW_LIST:
        if field in _DENY_ALWAYS:
            # Belt-and-suspenders: should never happen given the sets are disjoint,
            # but guard explicitly so a future edit cannot accidentally leak a secret.
            continue
        value = getattr(cfg, field, None)
        if value is not None:
            result[field] = value
    return result
