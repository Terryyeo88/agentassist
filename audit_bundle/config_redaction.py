"""config_redaction.py — extract an allow-listed, secrets-free config dict from ClientConfig.

Produces the config.json payload written into every sealed audit bundle.
The security model uses two complementary controls:

    1. Allow-list (_ALLOW_LIST): only explicitly named fields are copied.
       Any field added to ClientConfig in the future is excluded by default,
       so new secrets cannot silently enter the bundle.

    2. Deny-list (_DENY_ALWAYS): named credential fields are hard-blocked
       as a belt-and-suspenders guard, ensuring they cannot leak even if
       someone inadvertently adds them to _ALLOW_LIST.

The two sets are intentionally disjoint.  The deny-list is a redundant
safety net, not a primary control — the allow-list alone is sufficient for
correct operation.

Public API:
    redact_config(cfg) -> dict

Dependencies:
    config.loader  ClientConfig dataclass.
"""
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

    Iterates _ALLOW_LIST, skips any field also present in _DENY_ALWAYS, reads
    the value from cfg via getattr, and includes it only when non-None.  Fields
    absent from _ALLOW_LIST (including any future ClientConfig additions) are
    never examined, so they cannot appear in the output.

    Args:
        cfg: Validated ClientConfig instance from config.loader.load_client_config().
             Credential fields (username, password) must be present on the object
             but are unconditionally excluded from the returned dict.

    Returns:
        dict: JSON-serialisable mapping of allow-listed, non-None config fields.
              Never contains "username", "password", or "ssl_verify".

    Example:
        payload = redact_config(cfg)
        (bundle_dir / "config.json").write_text(json.dumps(payload, indent=2))
    """
    result = {}
    for field in _ALLOW_LIST:
        if field in _DENY_ALWAYS:
            # Belt-and-suspenders: should never happen given the sets are disjoint,
            # but guard explicitly so a future edit cannot accidentally leak a secret.
            continue
        # getattr with a None default tolerates fields that exist in _ALLOW_LIST but
        # have not yet been added to ClientConfig (e.g. during a schema migration),
        # avoiding AttributeError rather than crashing the entire seal operation.
        value = getattr(cfg, field, None)
        # Exclude None values to keep config.json lean; fields explicitly set to
        # False, 0, or "" are still included as they carry meaningful information.
        if value is not None:
            result[field] = value
    return result
