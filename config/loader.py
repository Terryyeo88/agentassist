"""
config/loader.py — AgentAssist per-client configuration loader.

Loads config/clients/<client_id>.yaml, validates it completely (required
fields, credential env-var resolution, GST-rate sanity, VatGroup collision
detection, optional SAP connectivity probe), and returns a ClientConfig.

Independence contract: this module has NO dependency on mcp-servers/ or
scripts/. Both consumers may import it; they must never import each other.

Public API:
    load_client_config(client_id, *, check_connectivity, config_dir)
        -> ClientConfig  — primary entry point for all callers.
    probe_environment(config, b1_session) -> list[dict]
        — Tier 2 extension point (not yet implemented).

Raises:
    ConfigError: Any validation failure during load_client_config().
        Messages are always human-readable with remediation hints.
    SystemExit:  On import if PyYAML or requests is not installed.

Example:
    from config.loader import load_client_config, ConfigError

    try:
        cfg = load_client_config("sbodemosg", check_connectivity=True)
    except ConfigError as exc:
        sys.exit(str(exc))

Dependencies:
    PyYAML    — YAML parsing (pip install pyyaml).
    requests  — SAP B1 login probe (pip install requests).
    urllib3   — InsecureRequestWarning suppression when ssl_verify=False.
    python-dotenv (caller's responsibility) — env vars must be loaded
        before this module is imported if they live in a .env file.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("config/loader.py requires PyYAML: pip install pyyaml")

try:
    import requests
    import urllib3
except ImportError:  # pragma: no cover
    sys.exit("config/loader.py requires requests: pip install requests")

logger = logging.getLogger(__name__)


# ── Standard VatGroup codes ────────────────────────────────────────────────────
# Authoritative set for Singapore GST F5. Custom codes must not collide with these.
_STANDARD_VAT_GROUPS = frozenset({
    "SR", "DS", "ZR", "ES33", "ESN33", "OS", "NG",     # sales side
    "TX", "ZP", "IM", "IGDS", "ME", "NR",              # purchase side (Box 5 / Box 7)
    "BL", "EP", "OP", "TX-E33", "TX-N33", "TX-RE",     # excluded purchases
})

# ── SAP B1 built-in default tax_code_mappings (T2.21a) ─────────────────────────
# Annex E baseline-vocabulary rename: SAP B1's native SO/SI VatGroup codes
# normalize to the canonical SR/TX codes by default. Applied by
# ClientConfig.effective_tax_code_mappings for source_system == "sap_b1"
# clients that declare no tax_code_mappings of their own (or only a partial
# override) — mirrors T2.19's "absent block -> defaults" precedent without
# requiring per-client YAML edits.
#
# NOTE: as of T2.21b, "SR"/"TX" are canonical members of _STANDARD_VAT_GROUPS
# and F5_BOX_MAPPING. This constant and the property that uses it are still
# not validated against _STANDARD_VAT_GROUPS (see Step 9 below) — they are an
# unconditional built-in default, not a user-declared tax_code_mappings entry.
_SAP_B1_DEFAULT_TAX_CODE_MAPPINGS: dict[str, str] = {"SO": "SR", "SI": "TX"}


@dataclass
class ClientConfig:
    """Validated, ready-to-use configuration for a single AgentAssist client.

    All fields are fully resolved at construction time — credential fields
    contain the actual secret values (not env-var names), the URL has its
    trailing slash stripped, and every optional section has been defaulted.
    Callers should treat instances as read-only; nothing mutates them after
    load_client_config() returns.

    Attributes:
        client_id:               Unique identifier matching the YAML filename stem.
        client_name:             Human-readable company name for reports.
        gst_registration_number: IRAS-issued GST reg number (may be empty string).
        applicable_gst_rate:     GST rate as a decimal fraction (e.g. 0.09 for 9%).
        service_layer_url:       SAP B1 Service Layer base URL, trailing slash removed.
        company_db:              SAP B1 company database name (e.g. "SBODEMOUS").
        username:                Resolved SAP B1 username (from env var).
        password:                Resolved SAP B1 password (from env var).
        ssl_verify:              Whether to verify the Service Layer TLS certificate.
        fiscal_year_start_month: Month number (1-12) when the fiscal year begins.
        custom_vat_groups:       Client-specific VatGroup → box mappings; guaranteed
                                 collision-free with _STANDARD_VAT_GROUPS.
        completeness_threshold:  Fraction of missing documents tolerated before a
                                 completeness gate fires (default 0.10 = 10%).
        reviewer_name:           Name printed on the PDF report signature line.
        firm_name:               Accounting firm name printed on the PDF report.
        show_ai_candidates:      Whether the AI-candidate subsection appears in the
                                 PDF.  Defaults to False — must stay False until the
                                 recall/precision measurement gate is met.
        source_system:           Name of the client's accounting system (e.g.
                                 "xero", "myob", "quickbooks"). Optional, defaults
                                 to "sap_b1". Used only for logging/display.
        tax_code_mappings:       Source-system tax code (uppercase) -> canonical
                                 AgentAssist VatGroup code, exactly as declared
                                 in the client YAML. Empty by default. See
                                 effective_tax_code_mappings for the mapping
                                 that callers should actually use.
        actively_makes_exempt_supplies:
                                 Whether the client makes exempt supplies as a
                                 principal activity (vs. incidentally). Default
                                 False. When True, exempt-supply E2 findings route
                                 to IRAS ASK Template 4 instead of Template 5.
                                 (T2.18 — scheme-LEVEL fact; no check logic here.)
        participates_in_mes:     Whether the client is enrolled in the IRAS Major
                                 Exporter Scheme (MES). Default False. Scheme-status
                                 fact consumed by downstream checks; no behaviour
                                 in this module.
        participates_in_igds:    Whether the client is enrolled in the IRAS Import
                                 GST Deferment Scheme (IGDS). Default False. Distinct
                                 from the per-VatGroup-code "IGDS" treatment — this
                                 is a scheme-LEVEL participation flag.
        reverse_charge_applicable:
                                 Whether reverse charge applies to the client
                                 (imported services / low-value goods procured by a
                                 GST-registered customer not entitled to full input
                                 tax credit). Default False. Single bool — not split
                                 into per-code RC families.
    """
    client_id: str
    client_name: str
    gst_registration_number: str
    applicable_gst_rate: float
    # SAP B1 connection — username/password are resolved VALUES, not env-var names
    service_layer_url: str
    company_db: str
    username: str
    password: str
    ssl_verify: bool
    # Behaviour
    fiscal_year_start_month: int
    custom_vat_groups: dict       # validated; collision-free with standard codes
    completeness_threshold: float
    # Report metadata
    reviewer_name: str
    firm_name: str
    # AI candidates subsection in the PDF (default OFF — must stay false until the
    # recall/precision measurement gate is met; the artefact always seals into the
    # bundle regardless of this flag).
    show_ai_candidates: bool = False
    # Non-SAP-B1 source system support (logging/display only; see tax_code_mappings).
    source_system: str = "sap_b1"
    # Source tax code (uppercase) -> canonical VatGroup, as declared in the YAML.
    tax_code_mappings: dict = field(default_factory=dict)
    # GST scheme-status flags (T2.18) — flat, scheme-LEVEL participation facts,
    # all default OFF. These are distinct from per-VatGroup-code treatment (T2.2).
    # This task adds NO check logic; downstream D+ checks (3E.1, ME/MC reverse
    # charge, Template-4 routing) bind to these field names as their contract.
    # actively_makes_exempt_supplies is a PROMOTION of the former
    # getattr(client_config, "actively_makes_exempt_supplies", False) read in
    # report/report.py — default False == the existing behaviour for every client.
    actively_makes_exempt_supplies: bool = False
    participates_in_mes: bool = False
    participates_in_igds: bool = False
    reverse_charge_applicable: bool = False

    @property
    def effective_tax_code_mappings(self) -> dict:
        """tax_code_mappings merged with the built-in SAP B1 default (T2.21a).

        For source_system == "sap_b1", codes not explicitly mapped in
        tax_code_mappings fall back to the canonical Annex E rename
        (SO -> SR, SI -> TX); explicit per-code entries in tax_code_mappings
        override the default for that code. Non-SAP-B1 clients are unaffected
        — the SAP B1 default is source-system-scoped and tax_code_mappings is
        returned unchanged.

        This is the mapping callers (e.g. normalize_vat_group()) should use —
        tax_code_mappings itself continues to reflect only what the YAML
        declares.
        """
        if self.source_system != "sap_b1":
            return dict(self.tax_code_mappings)
        return {**_SAP_B1_DEFAULT_TAX_CODE_MAPPINGS, **self.tax_code_mappings}


class ConfigError(RuntimeError):
    """Raised when config validation fails. Message is always human-readable."""


def load_client_config(
    client_id: str,
    *,
    check_connectivity: bool = True,
    config_dir: Optional[Path] = None,
) -> ClientConfig:
    """Load, validate, and return a ClientConfig.

    Validation steps (each fails loud with a human-readable message):
      1. Locate config/clients/<client_id>.yaml — names the file if missing.
      2. Parse YAML — surfaces parse errors cleanly (no raw tracebacks).
      3. Validate required fields — names the missing field.
      4. Verify client_id matches filename stem — flags mismatches.
      5. Resolve credential env vars — names any unset variable.
      6. Check applicable_gst_rate in [0.05, 0.15] — flags likely typos.
      7. Check custom_vat_groups for collisions with standard codes.
      8. (if check_connectivity=True) SAP login probe — reports endpoint +
         failure mode. Skipped by consumers that manage their own sessions.
      9. Validate tax_code_mappings — every mapped-to value must be a
         canonical VatGroup code; keys are normalized to uppercase.
     10. Validate GST scheme-status flags (T2.18) — actively_makes_exempt_supplies,
         participates_in_mes, participates_in_igds, reverse_charge_applicable must
         each be boolean; absent/null defaults to False.

    Args:
        client_id:          Filename stem in config/clients/ (e.g. "sbodemosg").
        check_connectivity: False to skip the SAP B1 login probe.  Pass False
                            when the caller already holds an active session or
                            is running in an environment without SAP access.
        config_dir:         Override the config/clients/ search path.  Primarily
                            used by tests to point at a fixture directory.

    Returns:
        ClientConfig: Fully validated and resolved configuration object.

    Raises:
        ConfigError: On any validation failure — file missing, YAML error,
            required field absent, client_id mismatch, unset env var, GST
            rate out of range, VatGroup collision, or SAP login failure.
        ValueError: If tax_code_mappings maps a source code to a value that
            is not a canonical AgentAssist VatGroup code.

    Example:
        cfg = load_client_config("sbodemosg", check_connectivity=False)
        print(cfg.company_db, cfg.applicable_gst_rate)
    """
    base_dir = config_dir or (_repo_root() / "config" / "clients")
    config_path = base_dir / f"{client_id}.yaml"

    # --- Step 1: file existence ---

    if not config_path.exists():
        available = sorted(p.stem for p in base_dir.glob("*.yaml") if p.stem != "example")
        raise ConfigError(
            f"Client config not found: {config_path}\n"
            f"  Available clients: {available or ['(none — create one from example.yaml)']}\n"
            f"  To add a new client: copy config/clients/example.yaml to\n"
            f"  config/clients/{client_id}.yaml and fill in the values."
        )

    # --- Step 2: YAML parse ---

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML parse error in {config_path}:\n  {exc}") from exc

    # --- Step 3: required fields ---

    for key in ("client_id", "client_name", "applicable_gst_rate", "sap_b1"):
        _require_field(raw, key, config_path)
    sap = raw["sap_b1"]
    for key in ("service_layer_url", "company_db", "username_env_var", "password_env_var"):
        _require_field(sap, key, config_path, parent="sap_b1")

    # --- Step 4: client_id / filename consistency ---

    if raw["client_id"] != client_id:
        raise ConfigError(
            f"client_id mismatch in {config_path}:\n"
            f"  File declares client_id: '{raw['client_id']}' "
            f"but filename is '{client_id}.yaml'.\n"
            f"  Fix: update client_id in the YAML to '{client_id}'."
        )

    # --- Step 5: credential env-var resolution ---

    username_var: str = sap["username_env_var"]
    password_var: str = sap["password_env_var"]
    # Use .get() rather than direct lookup so we can collect all missing vars
    # in one pass and report them together instead of failing on the first one.
    missing_vars = [v for v in (username_var, password_var) if not os.environ.get(v)]
    if missing_vars:
        raise ConfigError(
            f"Credential environment variable(s) not set: {', '.join(missing_vars)}\n"
            f"  These are referenced in config/clients/{client_id}.yaml.\n"
            f"  Add them to your .env file (or shell environment) before running AgentAssist.\n"
            f"  Example .env entry: {missing_vars[0]}=your_value_here"
        )
    username: str = os.environ[username_var]
    password: str = os.environ[password_var]

    # --- Step 6: GST rate plausibility ---

    rate = float(raw["applicable_gst_rate"])
    # [0.05, 0.15] brackets the realistic range for Singapore GST (7 % historic,
    # 9 % current) while catching common mistakes like entering "9" instead of "0.09".
    if not (0.05 <= rate <= 0.15):
        raise ConfigError(
            f"applicable_gst_rate {rate} is outside the plausible range [0.05, 0.15].\n"
            f"  Singapore GST is currently 9% (0.09). Demo databases use 7% (0.07).\n"
            f"  Update the value in config/clients/{client_id}.yaml if this is a typo."
        )

    # --- Step 7: custom VatGroup collision check ---

    # `or {}` handles both the key being absent and it being explicitly null in YAML.
    custom_vg: dict = dict(raw.get("custom_vat_groups") or {})
    # Set intersection — any code appearing in both sets is a prohibited override.
    collisions = sorted(set(custom_vg) & _STANDARD_VAT_GROUPS)
    if collisions:
        raise ConfigError(
            f"custom_vat_groups in '{client_id}.yaml' collides with standard "
            f"VatGroup code(s): {collisions}.\n"
            f"  Standard IRAS codes cannot be overridden — they are defined by IRAS.\n"
            f"  Remove or rename the conflicting key(s) in config/clients/{client_id}.yaml."
        )

    # Strip trailing slash so all callers can safely append "/Endpoint" without
    # producing double-slash URLs regardless of what the YAML author wrote.
    service_layer_url: str = sap["service_layer_url"].rstrip("/")
    company_db: str = sap["company_db"]
    ssl_verify: bool = bool(sap.get("ssl_verify", True))

    # --- Step 8: optional SAP connectivity probe ---

    if check_connectivity:
        _probe_sap_login(service_layer_url, company_db, username, password, ssl_verify)

    # `or {}` makes downstream .get() calls safe even when these optional
    # YAML sections are entirely absent from the file.
    period = raw.get("period_defaults") or {}
    report = raw.get("report") or {}

    # show_ai_candidates: default OFF — stays false until the measurement gate is met.
    # Accepts Python-style bool or YAML boolean (true/false/yes/no/on/off).
    _raw_ai = report.get("show_ai_candidates", False)
    # YAML parsers may return strings for unquoted values; reject anything that
    # is not already a real bool to prevent silent truthy/falsy surprises.
    if not isinstance(_raw_ai, bool):
        raise ConfigError(
            f"report.show_ai_candidates in '{client_id}.yaml' must be a boolean "
            f"(true or false), got: {_raw_ai!r}"
        )
    show_ai: bool = bool(_raw_ai)

    # --- Step 9: tax_code_mappings validation (non-SAP-B1 source systems) ---

    source_system: str = str(raw.get("source_system") or "sap_b1")

    # `or {}` handles both the key being absent and it being explicitly null in YAML.
    raw_mappings: dict = dict(raw.get("tax_code_mappings") or {})
    tax_code_mappings: dict = {}
    for source_code, target_code in raw_mappings.items():
        if target_code not in _STANDARD_VAT_GROUPS:
            raise ValueError(
                f"tax_code_mappings in '{client_id}.yaml' maps "
                f"'{source_code}' -> '{target_code}', but '{target_code}' is not "
                f"a canonical AgentAssist VatGroup code.\n"
                f"  Valid targets: {sorted(_STANDARD_VAT_GROUPS)}"
            )
        # Normalize keys to uppercase so runtime lookups are case-insensitive.
        tax_code_mappings[str(source_code).upper()] = target_code

    if tax_code_mappings:
        # Gaps are not errors — a client may legitimately never use some codes —
        # but surfacing them helps catch missing mappings early.
        missing = sorted(_STANDARD_VAT_GROUPS - set(tax_code_mappings.values()))
        if missing:
            logger.warning(
                f"tax_code_mappings in '{client_id}.yaml' has no source code "
                f"mapped to canonical VatGroup(s): {missing}."
            )

    # --- Step 10: GST scheme-status flags (T2.18) ---

    # Flat top-level booleans, all default OFF. Absent key OR explicit YAML null
    # -> False. Non-bool values (e.g. the quoted-"yes" truthy-string surprise) are
    # rejected with the same isinstance(bool) guard used for show_ai_candidates
    # above, so the failure is loud at load time, not a silent truthy/falsy bug.
    # NOTE: this is config infrastructure only — no check logic reads these here.
    scheme_flags: dict[str, bool] = {}
    for _flag in (
        "actively_makes_exempt_supplies",
        "participates_in_mes",
        "participates_in_igds",
        "reverse_charge_applicable",
    ):
        _val = raw.get(_flag, False)
        if _val is None:  # explicit YAML null -> default OFF
            _val = False
        if not isinstance(_val, bool):
            raise ConfigError(
                f"{_flag} in '{client_id}.yaml' must be a boolean "
                f"(true or false), got: {_val!r}"
            )
        scheme_flags[_flag] = _val

    return ClientConfig(
        client_id=raw["client_id"],
        client_name=raw["client_name"],
        gst_registration_number=str(raw.get("gst_registration_number") or ""),
        applicable_gst_rate=rate,
        service_layer_url=service_layer_url,
        company_db=company_db,
        username=username,
        password=password,
        ssl_verify=ssl_verify,
        fiscal_year_start_month=int(period.get("fiscal_year_start_month", 1)),
        custom_vat_groups=custom_vg,
        completeness_threshold=float(raw.get("completeness_threshold", 0.10)),
        reviewer_name=str(report.get("reviewer_name") or ""),
        firm_name=str(report.get("firm_name") or ""),
        show_ai_candidates=show_ai,
        source_system=source_system,
        tax_code_mappings=tax_code_mappings,
        # Scheme-status flags (T2.18); keys match the kwarg names exactly.
        **scheme_flags,
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    """Return the repository root by walking two levels up from this file.

    config/loader.py lives at <repo>/config/loader.py, so .parent.parent
    resolves to the repo root without needing __file__ manipulation elsewhere.

    Returns:
        Path: Absolute path to the repository root directory.
    """
    return Path(__file__).resolve().parent.parent


def _require_field(d: dict, key: str, path: Path, parent: str = "") -> None:
    """Raise ConfigError if a required key is absent or explicitly null.

    Args:
        d:      The dict to inspect (top-level raw config or a nested section).
        key:    The field name that must be present and non-null.
        path:   Path to the YAML file, included in the error message for context.
        parent: Dotted prefix for nested keys (e.g. "sap_b1") used to build a
                human-readable location string like "sap_b1.company_db".

    Raises:
        ConfigError: If the key is missing from d or its value is None.
    """
    location = f"{parent}.{key}" if parent else key
    if key not in d or d[key] is None:
        raise ConfigError(
            f"Required field '{location}' is missing in {path}.\n"
            f"  See config/clients/example.yaml for the full schema."
        )


def _probe_sap_login(
    service_layer_url: str,
    company_db: str,
    username: str,
    password: str,
    ssl_verify: bool,
) -> None:
    """Perform a lightweight SAP B1 login probe and log out immediately on success.

    Sends a single POST to /Login to confirm the Service Layer is reachable and
    the credentials are valid.  The resulting session is discarded via /Logout so
    no session slots are consumed.  This is a validation-only probe, not a real
    session setup.

    Args:
        service_layer_url: Base URL of the SAP B1 Service Layer (no trailing slash).
        company_db:        SAP B1 company database name.
        username:          SAP B1 username (resolved credential value).
        password:          SAP B1 password (resolved credential value).
        ssl_verify:        Whether to verify the server's TLS certificate.

    Raises:
        ConfigError: On ConnectionError (host unreachable), Timeout (10 s exceeded),
            or a non-200 HTTP response from /Login.  Each case includes the endpoint
            URL and a remediation hint.
    """
    if not ssl_verify:
        # Suppress the per-request InsecureRequestWarning that urllib3 emits when
        # certificate verification is disabled — the operator opted in via YAML.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    login_url = f"{service_layer_url}/Login"
    try:
        resp = requests.post(
            login_url,
            json={"CompanyDB": company_db, "UserName": username, "Password": password},
            verify=ssl_verify,
            timeout=10,
        )
    except requests.exceptions.ConnectionError:
        raise ConfigError(
            f"SAP B1 connectivity probe failed — cannot reach: {login_url}\n"
            f"  Network error: host unreachable or connection refused.\n"
            f"  Check sap_b1.service_layer_url in your client config and "
            f"that the SAP B1 Service Layer is running."
        )
    except requests.exceptions.Timeout:
        raise ConfigError(
            f"SAP B1 connectivity probe timed out (10 s) — endpoint: {login_url}\n"
            f"  The host is reachable but the Service Layer is not responding. "
            f"Check SAP server health."
        )

    if resp.status_code != 200:
        # SAP B1 Service Layer error responses nest the message at
        # error.message.value — try that path first, fall back to raw text.
        try:
            detail = resp.json()["error"]["message"]["value"]
        except Exception:
            detail = resp.text[:300]
        raise ConfigError(
            f"SAP B1 login failed (HTTP {resp.status_code}) — endpoint: {login_url}\n"
            f"  SAP error: {detail}\n"
            f"  Check: sap_b1.company_db, username_env_var, password_env_var."
        )

    # Probe succeeded — log out immediately; this was validation, not a real session.
    try:
        requests.post(
            f"{service_layer_url}/Logout",
            verify=ssl_verify,
            timeout=5,
            cookies=resp.cookies,
        )
    except Exception:
        pass  # logout failure is non-fatal


# ── Tier 2 extension point — environment probing ──────────────────────────────

def probe_environment(config: ClientConfig, b1_session) -> list[dict]:
    """
    Extension point for Tier 2 environment discovery probes. NOT YET IMPLEMENTED.

    Intended future probes:
      - Unmapped VatGroup discovery: scan recent invoices for VatGroup codes absent
        from F5_BOX_MAPPING and surface them for custom_vat_groups mapping in YAML.
      - FederalTaxID bulk check: scan all suppliers with input tax claims for a
        missing GST registration number — bulk config-time complement to the
        per-period NO_GST_REG check in detect_gst_errors.

    Args:
        config:     Validated ClientConfig from load_client_config().
        b1_session: Caller-provided active SAP B1 session. No type constraint
                    imposed — caller decides which session object to pass.
    Returns:
        List of finding dicts. Currently always returns [].
    """
    # Tier 2 — not yet implemented.
    return []
