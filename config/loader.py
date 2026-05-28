"""
config/loader.py — AgentAssist per-client configuration loader.

Loads config/clients/<client_id>.yaml, validates it completely (required
fields, credential env-var resolution, GST-rate sanity, VatGroup collision
detection, optional SAP connectivity probe), and returns a ClientConfig.

Independence contract: this module has NO dependency on mcp-servers/ or
scripts/. Both consumers may import it; they must never import each other.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
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


# ── Standard VatGroup codes ────────────────────────────────────────────────────
# Authoritative set for Singapore GST F5. Custom codes must not collide with these.
_STANDARD_VAT_GROUPS = frozenset({
    "SO", "DS", "ZR", "ES33", "ESN33", "OS",           # sales side
    "SI", "ZP", "IM", "IGDS", "ME", "NR",              # purchase side (Box 5 / Box 7)
    "BL", "EP", "OP", "TX-E33", "TX-N33", "TX-RE",     # excluded purchases
})


@dataclass
class ClientConfig:
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


class ConfigError(RuntimeError):
    """Raised when config validation fails. Message is always human-readable."""


def load_client_config(
    client_id: str,
    *,
    check_connectivity: bool = True,
    config_dir: Optional[Path] = None,
) -> ClientConfig:
    """
    Load, validate, and return a ClientConfig.

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

    Args:
        client_id:           Filename stem in config/clients/ (e.g. "sbodemosg").
        check_connectivity:  False to skip the SAP login probe.
        config_dir:          Override config/clients/ path (for testing).
    """
    base_dir = config_dir or (_repo_root() / "config" / "clients")
    config_path = base_dir / f"{client_id}.yaml"

    # Step 1 — file existence
    if not config_path.exists():
        available = sorted(p.stem for p in base_dir.glob("*.yaml") if p.stem != "example")
        raise ConfigError(
            f"Client config not found: {config_path}\n"
            f"  Available clients: {available or ['(none — create one from example.yaml)']}\n"
            f"  To add a new client: copy config/clients/example.yaml to\n"
            f"  config/clients/{client_id}.yaml and fill in the values."
        )

    # Step 2 — YAML parse
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML parse error in {config_path}:\n  {exc}") from exc

    # Step 3 — required top-level fields
    for key in ("client_id", "client_name", "applicable_gst_rate", "sap_b1"):
        _require_field(raw, key, config_path)
    sap = raw["sap_b1"]
    for key in ("service_layer_url", "company_db", "username_env_var", "password_env_var"):
        _require_field(sap, key, config_path, parent="sap_b1")

    # Step 4 — client_id must match filename stem
    if raw["client_id"] != client_id:
        raise ConfigError(
            f"client_id mismatch in {config_path}:\n"
            f"  File declares client_id: '{raw['client_id']}' "
            f"but filename is '{client_id}.yaml'.\n"
            f"  Fix: update client_id in the YAML to '{client_id}'."
        )

    # Step 5 — credential env-var resolution
    username_var: str = sap["username_env_var"]
    password_var: str = sap["password_env_var"]
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

    # Step 6 — GST rate plausibility [0.05, 0.15]
    rate = float(raw["applicable_gst_rate"])
    if not (0.05 <= rate <= 0.15):
        raise ConfigError(
            f"applicable_gst_rate {rate} is outside the plausible range [0.05, 0.15].\n"
            f"  Singapore GST is currently 9% (0.09). Demo databases use 7% (0.07).\n"
            f"  Update the value in config/clients/{client_id}.yaml if this is a typo."
        )

    # Step 7 — custom_vat_groups collision check
    custom_vg: dict = dict(raw.get("custom_vat_groups") or {})
    collisions = sorted(set(custom_vg) & _STANDARD_VAT_GROUPS)
    if collisions:
        raise ConfigError(
            f"custom_vat_groups in '{client_id}.yaml' collides with standard "
            f"VatGroup code(s): {collisions}.\n"
            f"  Standard IRAS codes cannot be overridden — they are defined by IRAS.\n"
            f"  Remove or rename the conflicting key(s) in config/clients/{client_id}.yaml."
        )

    service_layer_url: str = sap["service_layer_url"].rstrip("/")
    company_db: str = sap["company_db"]
    ssl_verify: bool = bool(sap.get("ssl_verify", True))

    # Step 8 — optional SAP connectivity probe
    if check_connectivity:
        _probe_sap_login(service_layer_url, company_db, username, password, ssl_verify)

    period = raw.get("period_defaults") or {}
    report = raw.get("report") or {}

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
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    """config/loader.py lives at <repo>/config/loader.py; parent.parent = repo root."""
    return Path(__file__).resolve().parent.parent


def _require_field(d: dict, key: str, path: Path, parent: str = "") -> None:
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
    """Lightweight SAP B1 login probe — logs out immediately on success."""
    if not ssl_verify:
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
