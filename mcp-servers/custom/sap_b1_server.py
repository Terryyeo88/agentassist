#!/usr/bin/env python3
"""
SAP Business One MCP server — exposes Service Layer operations and Singapore GST
(F5 return) accounting tools to Claude Desktop via the FastMCP stdio transport.

This server bridges an LLM (Claude) and a live SAP B1 Service Layer instance.
It handles:

  * Session management (login, auto-renew on expiry, logout).
  * Generic OData CRUD operations (query, create, patch, delete).
  * Domain-specific accounting tools: GST F5 return calculation, tax-code
    validation, and a multi-check GST compliance audit (E1–E4 plus supplementary
    completeness and supplier-registration checks).

Assumptions:
  * The SAP B1 Service Layer is reachable over HTTPS from the host running
    this server.
  * CLIENT_ID is set in the environment (or .env) and matches a YAML file
    under config/clients/.  The server refuses to start without it.
  * All monetary amounts in the F5 / audit tools are in their document currency.
    Only SGD documents contribute to box totals; FX documents are surfaced
    separately for manual exchange-rate conversion.
  * The default expected GST rate is 7% (Singapore pre-2024 demo data).
    Pass expected_rate=0.09 for post-Jan-2024 production invoices.

Dependencies:
    httpx         -- async-capable HTTP client used here in sync mode
    python-dotenv -- loads .env at startup before any config is read
    mcp           -- FastMCP framework (stdio transport)
    config.loader -- internal; reads per-client YAML configs from config/clients/

Example usage (run as MCP server driven by Claude Desktop):
    CLIENT_ID=sbodemosg python mcp-servers/custom/sap_b1_server.py

Example usage (import into an orchestrator chain step):
    from mcp_servers.custom.sap_b1_server import configure_client, calculate_f5_return
    configure_client(url, db, user, pwd, ssl_verify=False)
    result = calculate_f5_return("2024-01-01", "2024-03-31")
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Any, Optional, Protocol
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Ensure repo root is on sys.path so config.loader is importable.
# This file lives at <repo>/mcp-servers/custom/ — three parent hops reach the root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config.loader import load_client_config, ClientConfig  # noqa: E402

# Load environment variables before config loader reads them.
load_dotenv(_REPO_ROOT / ".env")

# Configure logging to stderr (stdout is reserved for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("sap-b1-mcp")

# Initialize FastMCP server
mcp = FastMCP("sap-b1")


class SAPB1Client:
    """SAP Business One Service Layer client with session management."""

    def __init__(self, config: ClientConfig):
        """Initialise the HTTP client and store credentials from a ClientConfig.

        Args:
            config: A ClientConfig (or duck-typed object with the same attributes)
                providing service_layer_url, company_db, username, password,
                ssl_verify, and client_id.

        Note:
            An httpx.Client is created here and reused across all requests so
            that SAP's B1SESSION cookie is preserved automatically between calls.
        """
        self.base_url = config.service_layer_url
        self.company_db = config.company_db
        self.username = config.username
        self.password = config.password
        self.ssl_verify = config.ssl_verify
        self.session_id: Optional[str] = None
        self.session_timeout: Optional[datetime] = None
        # 30-second HTTP timeout; SAP's Service Layer can be slow on large queries
        self.http = httpx.Client(verify=self.ssl_verify, timeout=30.0)
        logger.info(
            f"SAP B1 Client initialised for {self.base_url} "
            f"(company_db={self.company_db}, client={config.client_id})"
        )

    def login(self) -> dict:
        """Authenticate against the SAP B1 Service Layer and store the session.

        Sends a POST to /Login, extracts the SessionId and SessionTimeout from
        the response, and merges the returned Set-Cookie header into the shared
        HTTP client so subsequent requests carry the session automatically.

        Returns:
            dict: Keys — status, company_db, session_timeout_minutes, version.

        Raises:
            Exception: If the Service Layer responds with a non-200 status code.
        """
        url = f"{self.base_url}/Login"
        payload = {
            "CompanyDB": self.company_db,
            "UserName": self.username,
            "Password": self.password,
        }
        logger.info(f"Logging in to {url}")
        resp = self.http.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            self.session_id = data.get("SessionId")
            # Default 30 min if SAP omits the SessionTimeout field
            timeout_mins = data.get("SessionTimeout", 30)
            self.session_timeout = datetime.now() + timedelta(minutes=timeout_mins)
            # Merge SAP's B1SESSION cookie into the persistent HTTP client
            self.http.cookies.update(resp.cookies)
            logger.info(f"Login successful. Session timeout: {timeout_mins} min")
            return {
                "status": "connected",
                "company_db": self.company_db,
                "session_timeout_minutes": timeout_mins,
                "version": data.get("Version", "unknown"),
            }
        else:
            raise Exception(f"Login failed (HTTP {resp.status_code}): {resp.text[:500]}")

    def ensure_session(self):
        """Re-authenticate if the session is missing or has expired.

        Called automatically by ``request`` before every API call.  The local
        expiry check avoids a wasted round-trip on the majority of calls where
        the session is still valid — only when it has lapsed does a fresh login
        occur.
        """
        if self.session_id and self.session_timeout and datetime.now() < self.session_timeout:
            return
        logger.info("Session expired or missing — re-authenticating")
        self.login()

    def request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Send an authenticated HTTP request to the Service Layer.

        Prepends base_url to the endpoint, ensures the session is valid first,
        and retries once with a fresh login if a 401 is received.  SAP can
        reject an apparently valid cookie if the server restarts mid-session;
        one automatic retry is sufficient to recover transparently.

        Args:
            method:   HTTP verb string ('GET', 'POST', 'PATCH', 'DELETE').
            endpoint: OData path starting with '/', e.g. '/Invoices(42)'.
            **kwargs: Forwarded verbatim to httpx.Client.request
                      (e.g. params=, json=).

        Returns:
            Parsed JSON dict for 200/201 responses; a status dict for 204
            (No Content); or a {'status': 'success', 'raw': ...} dict if JSON
            decoding fails unexpectedly.

        Raises:
            Exception: For any HTTP error status other than 200, 201, or 204.
        """
        self.ensure_session()
        url = f"{self.base_url}{endpoint}"
        logger.info(f"{method} {url}")
        resp = self.http.request(method, url, **kwargs)
        if resp.status_code == 401:
            logger.info("Got 401 — re-authenticating")
            self.login()
            resp = self.http.request(method, url, **kwargs)
        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"status": "success", "raw": resp.text[:500]}
        elif resp.status_code == 204:
            return {"status": "success", "message": "Operation completed (no content)"}
        else:
            raise Exception(f"SAP Error (HTTP {resp.status_code}): {resp.text[:1000]}")

    def get(self, endpoint: str, params: dict = None) -> Any:
        """Send a GET request. params are appended as OData query string options.

        Args:
            endpoint: OData path, e.g. '/BusinessPartners'.
            params:   OData query parameters dict, e.g. {'$top': 20, '$filter': ...}.

        Returns:
            Parsed JSON response from the Service Layer.
        """
        return self.request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: dict = None) -> Any:
        """Send a POST request with data serialised as JSON.

        Args:
            endpoint: OData path for the collection to create in, e.g. '/Invoices'.
            data:     Document payload dict to serialise as the request body.

        Returns:
            Parsed JSON response, typically the newly created document.
        """
        return self.request("POST", endpoint, json=data)

    def patch(self, endpoint: str, data: dict = None) -> Any:
        """Send a PATCH request — used for partial updates of existing records.

        Args:
            endpoint: OData path including the record key, e.g. '/Items(42)'.
            data:     Dict of fields to update; omitted fields are left unchanged.

        Returns:
            Parsed JSON response or a 204 status dict if SAP returns no content.
        """
        return self.request("PATCH", endpoint, json=data)

    def delete(self, endpoint: str) -> Any:
        """Send a DELETE request to remove a record by its OData key.

        Args:
            endpoint: OData path including the record key, e.g. "/Items('A001')".

        Returns:
            A 204 status dict; SAP returns no body on successful deletion.
        """
        return self.request("DELETE", endpoint)

    def logout(self) -> dict:
        """Terminate the current SAP session and clear stored credentials.

        A best-effort POST to /Logout is attempted; failures are logged but do
        not prevent local session state from being cleared, so subsequent calls
        will simply re-authenticate.

        Returns:
            dict: {'status': 'logged out'} or {'status': 'no active session'}
                  if no login had previously been performed.
        """
        if not self.session_id:
            return {"status": "no active session"}
        try:
            self.http.post(f"{self.base_url}/Logout")
        except Exception as e:
            logger.warning(f"Logout request failed: {e}")
        self.session_id = None
        self.session_timeout = None
        self.http.cookies.clear()
        return {"status": "logged out"}


# Global SAP client — initialised after F5_BOX_MAPPING is defined (see below).


def _fmt(data: Any) -> str:
    """Serialise data to a pretty-printed JSON string for MCP tool return values.

    Args:
        data: Any JSON-serialisable value, or a plain string.

    Returns:
        str: The original string unchanged, or a pretty-printed JSON string.
            ``default=str`` ensures non-serialisable types (e.g. Decimal,
            datetime) are converted to their string representation without
            raising a TypeError.
    """
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# --- Shared helpers for accounting tools ---

def _safe_float(val) -> float:
    """Convert a value to float, returning 0.0 on None or conversion failure.

    SAP B1's Service Layer occasionally returns None or empty string for monetary
    fields on lines that were not fully configured.  This guard prevents
    TypeError/ValueError from propagating through accumulator loops.

    Args:
        val: Any value — typically str, int, float, or None from a JSON field.

    Returns:
        float: The numeric value, or 0.0 if val is falsy or conversion fails.
    """
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_vat_group(raw_code: str, mappings: dict[str, str]) -> str:
    """Translate a source-system tax code to its canonical AgentAssist VatGroup.

    If mappings is empty (SAP B1 clients), returns raw_code unchanged.
    If raw_code is not in mappings, returns raw_code unchanged — unknown codes
    will fall through to the anomalies bucket in the existing logic.

    Args:
        raw_code: The VatGroup code as read from the source record.
        mappings: Source tax code (uppercase) -> canonical VatGroup code,
            from ClientConfig.tax_code_mappings. Empty for SAP B1 clients.

    Returns:
        str: The canonical VatGroup code, or raw_code unchanged if mappings
            is empty or raw_code has no entry in mappings.
    """
    if not mappings:
        return raw_code
    return mappings.get(raw_code.strip().upper(), raw_code)


def _is_sgd(doc: dict) -> bool:
    """Return True if the document's currency is SGD (or blank, which SAP defaults to SGD).

    Only SGD documents are included directly in F5 box totals.  FX documents
    require manual exchange-rate conversion before they can be filed with IRAS,
    so they are surfaced separately in the output.

    Args:
        doc: A SAP B1 document dict containing a 'DocCurrency' key.

    Returns:
        bool: True when the document is denominated in SGD.
    """
    currency = (doc.get("DocCurrency") or "SGD").strip().upper()
    return currency in ("SGD", "S$", "")


# VatGroup → F5 box routing. lt_box = line total destination, tt_box = tax total destination.
# None means the amount for this code is excluded from that box entirely (not zero — absent).
F5_BOX_MAPPING = {
    "SR":     {"lt_box": "box_1_standard_rated_sales", "tt_box": "box_6_output_tax",  "side": "sales"},
    "DS":     {"lt_box": "box_1_standard_rated_sales", "tt_box": "box_6_output_tax",  "side": "sales"},
    "ZR":     {"lt_box": "box_2_zero_rated_sales",     "tt_box": None,                "side": "sales"},
    "ES33":   {"lt_box": "box_3_exempt_sales",         "tt_box": None,                "side": "sales"},
    "ESN33":  {"lt_box": "box_3_exempt_sales",         "tt_box": None,                "side": "sales"},
    "OS":     {"lt_box": None,                         "tt_box": None,                "side": "sales"},
    # NG ("Supplies made by non-GST registered business", Annex E): recognized
    # but not expected to occur in AgentAssist's (GST-registered) clients' own
    # sales data. Excluded from all boxes, same treatment as OS, so that an
    # NG line (if it ever appears) is not misrouted to the "unknown VatGroup"
    # anomalies bucket.
    "NG":     {"lt_box": None,                         "tt_box": None,                "side": "sales"},
    "TX":     {"lt_box": "box_5_taxable_purchases",    "tt_box": "box_7_input_tax",   "side": "purchase"},
    "ZP":     {"lt_box": "box_5_taxable_purchases",    "tt_box": None,                "side": "purchase"},
    "IM":     {"lt_box": "box_5_taxable_purchases",    "tt_box": "box_7_input_tax",   "side": "purchase"},
    "IGDS":   {"lt_box": "box_5_taxable_purchases",    "tt_box": "box_7_input_tax",   "side": "purchase"},
    "ME":     {"lt_box": "box_5_taxable_purchases",    "tt_box": None,                "side": "purchase"},
    "NR":     {"description": "Non-GST registered purchase", "lt_box": None,           "tt_box": None,                "side": "purchase"},
    # NR excluded from Box 5 per IRAS para 5.11(o): purchases from non-GST registered
    # traders are not taxable purchases; no input tax is claimable on these.
    "BL":     {"lt_box": None,                         "tt_box": None,                "side": "purchase"},
    "EP":     {"lt_box": None,                         "tt_box": None,                "side": "purchase"},
    "OP":     {"lt_box": None,                         "tt_box": None,                "side": "purchase"},
    "TX-E33": {"lt_box": None,                         "tt_box": None,                "side": "purchase"},
    "TX-N33": {"lt_box": None,                         "tt_box": None,                "side": "purchase"},
    "TX-RE":  {"lt_box": None,                         "tt_box": None,                "side": "purchase"},
}

# NR added: non-GST-registered purchase with TaxTotal > 0 is a genuine E2 error
# (non-taxable supply carrying GST — input tax cannot be claimed per IRAS para 5.11(o)).
# ZP added (T2.10): zero-rated purchase with TaxTotal > 0 is an E2 error per
# IRAS ASK Annual Review Guide §10.1(d)(iv) — tax coded as zero-rated but reflects GST.
# DocNum 610 (LineTotal=1200, TaxTotal=84 at 7%) is the known live fixture for this case.
_E2_ZERO_RATE_CODES = {"ZR", "OS", "ES33", "ESN33", "BL", "NR", "ZP"}
# Only SR and DS are standard-rated on the sales side; DS is a domestic service variant.
_STANDARD_RATE_SALES = {"SR", "DS"}


# ── Module-level initialisation ───────────────────────────────────────────────

def _load_sap_config() -> ClientConfig:
    """Load client config from YAML. CLIENT_ID must be set — no silent fallback.

    Correction 2: if CLIENT_ID is absent we refuse to guess the target instance.
    A misconfigured MCP server silently pointed at the wrong SAP company database
    is a hard-to-detect, hard-to-undo data integrity risk.

    Returns:
        ClientConfig: Fully populated config object for the named client.

    Raises:
        RuntimeError: If CLIENT_ID is missing from the environment.
    """
    client_id = os.environ.get("CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "CLIENT_ID environment variable is not set.\n"
            "  AgentAssist refuses to start without an explicit client identifier.\n"
            "  Add CLIENT_ID=<client_id> to your .env file "
            "(e.g. CLIENT_ID=sbodemosg).\n"
            "  Available configs are in config/clients/ — "
            "see example.yaml for the schema."
        )
    return load_client_config(client_id, check_connectivity=False)


_tax_code_mappings: dict[str, str] = {}

try:
    _client_config = _load_sap_config()
    # Merge client-specific VatGroup codes into the standard mapping (additive only).
    # Collision with standard codes is already rejected by load_client_config, so
    # this loop can only add new codes — never overwrite existing ones.
    for _code, _mapping in _client_config.custom_vat_groups.items():
        F5_BOX_MAPPING[_code] = _mapping
    _tax_code_mappings = dict(_client_config.effective_tax_code_mappings)
    sap = SAPB1Client(_client_config)
except RuntimeError as _init_err:
    logger.warning(
        f"SAP client not initialised at module load time: {_init_err} — "
        "call configure_client() before using any tool."
    )
    sap = None


def configure_client(
    service_layer_url: str,
    company_db: str,
    username: str,
    password: str,
    ssl_verify: bool,
    custom_vat_groups: Optional[dict] = None,
    tax_code_mappings: Optional[dict] = None,
) -> None:
    """Override the module-level SAP client for orchestrator chain use.

    Accepts primitives only — no ClientConfig import; keeps dependency direction
    one-way.  Call once before invoking any step function.  Does not affect MCP
    tool signatures.

    Args:
        service_layer_url: Full HTTPS URL of the SAP B1 Service Layer root,
            e.g. 'https://sap-server:50000/b1s/v1'.
        company_db:        SAP company database name (CompanyDB field).
        username:          SAP B1 login username.
        password:          SAP B1 login password.
        ssl_verify:        Whether to verify the server's TLS certificate.
            Pass False for self-signed certificates on dev/test environments.
        custom_vat_groups: Optional dict of additional VatGroup → box mappings
            to merge into F5_BOX_MAPPING (additive; existing codes are not
            overwritten).
        tax_code_mappings: Optional dict of source-system tax code (uppercase)
            -> canonical VatGroup code. Callers should pass
            ClientConfig.effective_tax_code_mappings (T2.21b), which includes
            the SAP B1 default SO -> SR / SI -> TX rename for source_system ==
            "sap_b1" clients. See normalize_vat_group().
    """
    global sap, _tax_code_mappings

    # Lightweight duck-type stand-in for ClientConfig so this module does not
    # need to import it — attributes are assigned dynamically after construction.
    class _Cfg:
        pass

    cfg = _Cfg()
    cfg.service_layer_url = service_layer_url
    cfg.company_db = company_db
    cfg.username = username
    cfg.password = password
    cfg.ssl_verify = ssl_verify
    cfg.client_id = "<chain-configured>"

    sap = SAPB1Client(cfg)

    if custom_vat_groups:
        for _code, _mapping in custom_vat_groups.items():
            if _code not in F5_BOX_MAPPING:
                F5_BOX_MAPPING[_code] = _mapping

    _tax_code_mappings = dict(tax_code_mappings or {})

    logger.info(
        f"configure_client: SAP client set for {company_db} at {service_layer_url}"
    )


def _fetch_invoices_paginated(entity: str, period_start: str, period_end: str) -> list:
    """Fetch all documents for a date range, paging through results 20 at a time.

    The SAP B1 Service Layer applies a server-side page-size cap, so a single
    large $top request may silently truncate results.  This function loops until
    a partial page is returned, which is the sentinel for the last page.

    Args:
        entity:       OData entity collection name, e.g. 'Invoices' or
                      'PurchaseInvoices'.
        period_start: ISO date string 'YYYY-MM-DD' inclusive start of filter range.
        period_end:   ISO date string 'YYYY-MM-DD' inclusive end of filter range.

    Returns:
        list: All matching document dicts, each containing DocumentLines.
    """
    results = []
    skip = 0
    date_filter = f"DocDate ge '{period_start}' and DocDate le '{period_end}'"
    while True:
        data = sap.get(f"/{entity}", params={
            "$filter": date_filter,
            "$top": 20,
            "$skip": skip,
        })
        page = data.get("value", [])
        results.extend(page)
        # A page shorter than the requested size means there are no more records
        if len(page) < 20:
            break
        skip += 20
    return results


def _fetch_credit_notes_paginated(entity_type: str, period_start: str, period_end: str) -> list:
    """Fetch all credit notes with DocumentLines for the period, paginating 20 at a time.

    entity_type: 'sales' → CreditNotes, 'purchases' → PurchaseCreditNotes.
    Returned dicts are tagged is_credit_note=True; callers must negate LineTotal/TaxTotal.

    Args:
        entity_type:  Either 'sales' (maps to CreditNotes) or 'purchases'
                      (maps to PurchaseCreditNotes).
        period_start: ISO date string 'YYYY-MM-DD' inclusive start of filter range.
        period_end:   ISO date string 'YYYY-MM-DD' inclusive end of filter range.

    Returns:
        list: All matching credit note dicts tagged with is_credit_note=True.
            Callers are responsible for negating LineTotal and TaxTotal when
            accumulating box totals.
    """
    entity = "CreditNotes" if entity_type == "sales" else "PurchaseCreditNotes"
    results = []
    skip = 0
    date_filter = f"DocDate ge '{period_start}' and DocDate le '{period_end}'"
    while True:
        data = sap.get(f"/{entity}", params={
            "$filter": date_filter,
            "$top": 20,
            "$skip": skip,
        })
        page = data.get("value", [])
        for record in page:
            record["is_credit_note"] = True
        results.extend(page)
        # A page shorter than the requested size means there are no more records
        if len(page) < 20:
            break
        skip += 20
    return results


def _fetch_headers_paginated(
    entity: str,
    select_fields: str,
    date_filter: Optional[str] = None,
    page_size: int = 20,
) -> list:
    """Fetch header-only records for an OData entity, paginating via $skip.

    Uses $select to limit returned fields — no DocumentLines, no expensive
    line-level data.  Designed for the lightweight header reads needed by the
    T2.10 listing checks (SEQ_GAP, DUP_CLAIM).

    page_size defaults to 20 to match the SAP B1 Service Layer's server-side
    page cap — requesting more than the server returns per page causes the
    pagination loop to stop prematurely (returned < requested = "last page"
    sentinel), so the value must not exceed the server's actual page size.

    T2.23: relocated verbatim from orchestrator/steps.py so the default
    SapChainReader.fetch_listing (the S5 read surface) and the four header
    queries it issues live next to the other SAP fetch primitives. Behaviour
    is unchanged — same queries, same pagination sentinel.

    Args:
        entity:        OData entity name (e.g. "Invoices").
        select_fields: Comma-separated field names for $select.
        date_filter:   OData $filter expression, or None for company-wide.
        page_size:     Records per page; must not exceed SAP's server cap (default 20).

    Returns:
        List of dicts containing only the requested fields.
    """
    results: list = []
    skip = 0
    while True:
        params: dict = {"$select": select_fields, "$top": page_size, "$skip": skip}
        if date_filter:
            params["$filter"] = date_filter
        try:
            resp = sap.get(f"/{entity}", params=params)
            page = resp.get("value", [])
        except Exception as exc:
            logger.warning(f"_fetch_headers_paginated: {entity} skip={skip} failed ({exc})")
            break
        if not page:
            break
        results.extend(page)
        if len(page) < page_size:
            break
        skip += page_size
    return results


# ---------------------------------------------------------------------------
# T2.23 — Chain source seam: per-surface injectable read provider
# ---------------------------------------------------------------------------
#
# run_chain reads SAP only through five raw-read surfaces (recon S0/S1/S2/S3/S5),
# all bottoming out at SAPB1Client.get on the module-global ``sap``. ChainReader
# is the per-surface contract; SapChainReader is the default implementation that
# wraps the existing fetch primitives VERBATIM (no logic change — a wrapper, not a
# rewrite). A T2.12 CSV/Excel adapter supplies a different ChainReader without
# touching the deterministic chain. The type lives here (top-level sap_b1_server,
# NOT engine/) so the engine/ -> orchestrator/ import direction is preserved and
# the tool functions below can default-construct it with no circular import.


class ChainReader(Protocol):
    """Per-surface raw-read contract consumed by run_chain (recon S0/S1/S2/S3/S5).

    Each method returns ALREADY-SHAPED record lists (not raw OData envelopes);
    the OData wire shape stays inside the default SapChainReader. Implementations
    MUST return a fresh payload per call — the live client does (a fresh HTTP
    response each fetch) and any fixture-backed reader must deepcopy-per-call —
    so the ``is_credit_note=True`` tag applied inside the credit-note read can
    never leak into the untagged invoice read via a shared mutable object.
    """

    def count(self, entity: str, period_start: str, period_end: str) -> Optional[int]:
        """S0 — record-count probe for one entity over the period (Gate 1)."""
        ...

    def fetch_invoices(self, entity: str, period_start: str, period_end: str) -> list:
        """S1 — full line-level documents for one entity over the period."""
        ...

    def fetch_credit_notes(self, entity_type: str, period_start: str, period_end: str) -> list:
        """S2 — credit notes for 'sales'/'purchases', tagged is_credit_note=True."""
        ...

    def get_business_partner(self, card_code: str) -> dict:
        """S3 — single BusinessPartner master record by CardCode (FederalTaxID)."""
        ...

    def fetch_listing(self, period: dict) -> dict:
        """S5 — the four header-only listing queries (period + company-wide)."""
        ...


class SapChainReader:
    """Default SAP-backed ChainReader — wraps the existing fetch primitives verbatim.

    Stateless: every method delegates to the module-level fetch helpers / the
    module-global ``sap`` client at call time, so monkeypatching those primitives
    (as the offline-replay harness does) still intercepts the reads, and any
    number of instances behave identically. Constructed by run_chain (one shared
    instance threaded through the run) or, for standalone/MCP callers, by each
    tool function when reader is None.
    """

    def count(self, entity: str, period_start: str, period_end: str) -> Optional[int]:
        # S0 — relocated verbatim from orchestrator/steps.py::_fetch_entity.
        # NOTE (backlog #5, OUT OF SCOPE): the v2 Service Layer returns the total
        # under "@odata.count" (with @), but this reads "odata.count" (no @), so
        # the probe yields None and Gate 1 warn-passes. Preserved EXACTLY — the
        # frozen oracle was captured with this behaviour; do NOT fix it here.
        date_filter = f"DocDate ge '{period_start}' and DocDate le '{period_end}'"
        inline_count: Optional[int] = None
        try:
            count_resp = sap.get(f"/{entity}", params={
                "$filter": date_filter,
                "$top": 0,
                "$inlinecount": "allpages",
            })
            raw = count_resp.get("odata.count")
            if raw is not None:
                inline_count = int(raw)
        except Exception as exc:
            logger.warning(f"count probe for {entity} failed ({exc}) — Gate 1 will warn")
        return inline_count

    def fetch_invoices(self, entity: str, period_start: str, period_end: str) -> list:
        # S1 — full line-level documents (no $select/$expand; DocumentLines default).
        return _fetch_invoices_paginated(entity, period_start, period_end)

    def fetch_credit_notes(self, entity_type: str, period_start: str, period_end: str) -> list:
        # S2 — tags is_credit_note=True inside the paginator; callers sign-flip.
        return _fetch_credit_notes_paginated(entity_type, period_start, period_end)

    def get_business_partner(self, card_code: str) -> dict:
        # S3 — single-entity GET by key; detect_gst_errors reads FederalTaxID.
        return sap.get(f"/BusinessPartners('{card_code}')")

    def fetch_listing(self, period: dict) -> dict:
        # S5 — relocated verbatim from orchestrator/steps.py::fetch_listing_data.
        # Two period-scoped + two company-wide (no date filter) header queries.
        period_start = period["start"]
        period_end = period["end"]
        date_filter = f"DocDate ge '{period_start}' and DocDate le '{period_end}'"
        period_sales = _fetch_headers_paginated(
            "Invoices", "DocNum,Series,Cancelled", date_filter=date_filter
        )
        period_purch = _fetch_headers_paginated(
            "PurchaseInvoices",
            "DocNum,Series,Cancelled,CardCode,NumAtCard,DocTotal",
            date_filter=date_filter,
        )
        all_sales = _fetch_headers_paginated(
            "Invoices", "DocNum,Series,Cancelled", date_filter=None
        )
        all_purch = _fetch_headers_paginated(
            "PurchaseInvoices", "DocNum,Series,Cancelled", date_filter=None
        )
        return {
            "period_sales_headers": period_sales,
            "period_purch_headers": period_purch,
            "all_sales_headers": all_sales,
            "all_purch_headers": all_purch,
        }


def _resolve_reader(reader: Any) -> "ChainReader":
    """Return ``reader`` if injected, else a fresh default SapChainReader.

    Single defaulting point shared by the chain tool functions so the
    None -> SAP-backed-default rule is identical across calculate_f5_return,
    validate_invoice_tax_codes and detect_gst_errors.
    """
    return reader if reader is not None else SapChainReader()


def _classify_line(line: dict, doc: dict, entity_type: str = "sales", expected_rate: float = 0.07, credit_note: bool = False) -> list:
    """Check one document line for E1–E4 issues. Returns a list of issue dicts.

    Args:
        line:          A single DocumentLines entry from a SAP B1 document.
        doc:           The parent document dict (used for DocNum, DocDate,
                       CardName, DocCurrency).
        entity_type:   'sales' or 'purchase' — controls which error checks apply.
        expected_rate: Expected GST rate as a decimal (e.g. 0.07 or 0.09).
                       Used only for the E4 rate-deviation check.
        credit_note:   If True, prepends "Credit note — " to issue descriptions
                       so callers can distinguish credit note issues from invoice
                       issues at a glance.

    Returns:
        list: Zero or more issue dicts.  Each dict contains doc_num, doc_date,
            doc_currency, card_name, vat_group, line_total, tax_total,
            error_code ('E1'–'E4'), and a human-readable description.
    """
    issues = []
    vg = (line.get("VatGroup") or "").strip()
    vg = normalize_vat_group(vg, _tax_code_mappings)
    line_total = _safe_float(line.get("LineTotal"))
    tax_total = _safe_float(line.get("TaxTotal"))
    currency = (doc.get("DocCurrency") or "SGD").strip().upper()
    # FX detection replicates _is_sgd logic inline to avoid a dict lookup per line
    is_fx = currency not in ("SGD", "S$", "")
    prefix = "Credit note — " if credit_note else ""

    base = {
        "doc_num": doc.get("DocNum"),
        "doc_date": str(doc.get("DocDate", ""))[:10],
        "doc_currency": currency,
        "card_name": doc.get("CardName", ""),
        "vat_group": vg,
        "line_total": line_total,
        "tax_total": tax_total,
    }

    # E1: FX sales invoice using standard-rated code — overseas sales should be ZR
    if entity_type == "sales" and is_fx and vg in _STANDARD_RATE_SALES:
        issues.append({**base, "error_code": "E1",
            "description": f"{prefix}FX invoice ({currency}) with {vg} code — should likely be ZR for overseas sales"})

    # E2: GST charged on a non-taxable supply code (includes NR)
    # 0.01 threshold absorbs floating-point rounding; genuine zero-rate lines carry no tax
    if tax_total > 0.01 and vg in _E2_ZERO_RATE_CODES:
        issues.append({**base, "error_code": "E2",
            "description": f"{prefix}Tax {tax_total:.2f} charged on non-taxable supply (VatGroup={vg})"})

    # E3: Standard-rated code with zero tax
    if entity_type == "sales" and vg in _STANDARD_RATE_SALES and line_total > 0.01 and tax_total < 0.01:
        issues.append({**base, "error_code": "E3",
            "description": f"{prefix}Standard-rated line (VatGroup={vg}) with zero tax on {line_total:.2f}"})
    if entity_type == "purchase" and vg == "TX" and line_total > 0.01 and tax_total < 0.01:
        issues.append({**base, "error_code": "E3",
            "description": f"{prefix}Standard-rated purchase (VatGroup=TX) with zero tax on {line_total:.2f}"})

    # E4: GST rate deviates from expected (SR and TX only per spec)
    if vg in {"SR", "TX"} and line_total > 0.01 and tax_total > 0.01:
        ratio = tax_total / line_total
        # 0.001 tolerance absorbs floating-point rounding, not a business threshold
        if abs(ratio - expected_rate) > 0.001:
            issues.append({**base, "error_code": "E4",
                "description": f"{prefix}GST rate {ratio * 100:.2f}% deviates from expected {expected_rate * 100:.0f}%"})

    return issues


# --- Tools ---

@mcp.tool()
def sap_login() -> str:
    """Login to SAP Business One. Call this first before any other operation."""
    result = sap.login()
    return _fmt(result)


@mcp.tool()
def sap_logout() -> str:
    """Close the SAP session."""
    result = sap.logout()
    return _fmt(result)


@mcp.tool()
def sap_query(entity: str, select: str = "", filter: str = "", top: int = 20, skip: int = 0, orderby: str = "") -> str:
    """Query any SAP B1 entity with OData options. Use for SalesTaxCodes, ChartOfAccounts, Invoices, BusinessPartners, Items, JournalEntries, Currencies, Warehouses, etc."""
    params = {"$top": top}
    if select:
        params["$select"] = select
    if filter:
        params["$filter"] = filter
    if orderby:
        params["$orderby"] = orderby
    if skip:
        params["$skip"] = skip
    result = sap.get(f"/{entity}", params=params)
    return _fmt(result)


@mcp.tool()
def sap_get_business_partners(card_type: str = "", search: str = "", top: int = 20) -> str:
    """List business partners. card_type: 'C' for customers, 'S' for vendors, 'L' for leads."""
    params = {"$top": top, "$select": "CardCode,CardName,CardType,Country,FederalTaxID,Currency"}
    filters = []
    if card_type:
        filters.append(f"CardType eq '{card_type}'")
    if search:
        filters.append(f"contains(CardName, '{search}')")
    if filters:
        params["$filter"] = " and ".join(filters)
    result = sap.get("/BusinessPartners", params=params)
    return _fmt(result)


@mcp.tool()
def sap_get_business_partner(card_code: str) -> str:
    """Get a single business partner by CardCode."""
    result = sap.get(f"/BusinessPartners('{card_code}')")
    return _fmt(result)


@mcp.tool()
def sap_create_business_partner(CardCode: str, CardName: str, CardType: str, Country: str = "", FederalTaxID: str = "") -> str:
    """Create a new business partner. CardType: 'cCustomer', 'cSupplier', or 'cLead'."""
    data = {"CardCode": CardCode, "CardName": CardName, "CardType": CardType}
    if Country:
        data["Country"] = Country
    if FederalTaxID:
        data["FederalTaxID"] = FederalTaxID
    result = sap.post("/BusinessPartners", data=data)
    return _fmt(result)


@mcp.tool()
def sap_get_items(search: str = "", top: int = 20) -> str:
    """List items (products/services)."""
    params = {"$top": top, "$select": "ItemCode,ItemName,ItemType,SalesVATGroup,PurchaseVATGroup"}
    if search:
        params["$filter"] = f"contains(ItemName, '{search}')"
    result = sap.get("/Items", params=params)
    return _fmt(result)


@mcp.tool()
def sap_create_document(entity: str, document: str) -> str:
    """Create a document (Invoice, PurchaseInvoice, Order, etc). Pass entity name and JSON document string."""
    data = json.loads(document)
    result = sap.post(f"/{entity}", data=data)
    return _fmt(result)


@mcp.tool()
def sap_get_document(entity: str, doc_entry: int) -> str:
    """Get a single document by DocEntry."""
    result = sap.get(f"/{entity}({doc_entry})")
    return _fmt(result)


@mcp.tool()
def sap_create_journal_entry(journal_entry: str) -> str:
    """Create a manual journal entry. Pass JSON string with JournalEntryLines."""
    data = json.loads(journal_entry)
    result = sap.post("/JournalEntries", data=data)
    return _fmt(result)


@mcp.tool()
def sap_delete(entity: str, key: str) -> str:
    """Delete a record by entity name and key."""
    # Integer keys use bare numeric OData syntax (key); string keys require quoting ('key')
    if key.isdigit():
        endpoint = f"/{entity}({key})"
    else:
        endpoint = f"/{entity}('{key}')"
    result = sap.delete(endpoint)
    return _fmt(result)


@mcp.tool()
def calculate_f5_return(period_start: str, period_end: str, reader=None) -> str:
    """Calculate GST F5 return boxes 1–8 for a period.

    Fetches all SAP B1 invoices and credit notes within the date range and
    accumulates SGD amounts into the eight IRAS F5 boxes using F5_BOX_MAPPING.
    Credit note amounts are subtracted from their respective boxes.
    FX documents cannot be included without conversion rates and are listed
    separately for manual handling.

    Args:
        period_start: ISO date string 'YYYY-MM-DD' for the start of the GST period.
        period_end:   ISO date string 'YYYY-MM-DD' for the end of the GST period.
        reader:       Optional ChainReader (T2.23 chain source seam). None ->
                      the default SAP-backed reader. Internal DI only; never set
                      by MCP/agent callers (left untyped so @mcp.tool JSON-schema
                      generation does not choke on the ChainReader class).

    Returns:
        str: JSON string containing:
            - period: the requested date range
            - currency: always 'SGD'
            - boxes: the eight F5 box values rounded to 2 decimal places
            - fx_invoices_requiring_conversion: FX docs needing manual conversion
            - e1_candidates: FX sales lines with standard-rated codes (likely mis-coded)
            - record_counts: breakdown of SGD vs FX doc counts
            - credit_note_counts: breakdown of credit note counts
            - credit_notes_applied: detail of each credit note adjustment
            - anomalies: lines with VatGroup codes absent from F5_BOX_MAPPING
    """
    # --- Fetch (T2.23: via the chain source seam; default = SAP-backed reader) ---
    reader = _resolve_reader(reader)
    invoices = reader.fetch_invoices("Invoices", period_start, period_end)
    purchases = reader.fetch_invoices("PurchaseInvoices", period_start, period_end)
    sales_credits = reader.fetch_credit_notes("sales", period_start, period_end)
    purchase_credits = reader.fetch_credit_notes("purchases", period_start, period_end)

    # --- Split SGD vs FX ---
    sgd_sales = [d for d in invoices if _is_sgd(d)]
    fx_sales = [d for d in invoices if not _is_sgd(d)]
    sgd_purchases = [d for d in purchases if _is_sgd(d)]
    fx_purchases = [d for d in purchases if not _is_sgd(d)]
    sgd_sales_credits = [d for d in sales_credits if _is_sgd(d)]
    fx_sales_credits = [d for d in sales_credits if not _is_sgd(d)]
    sgd_purchase_credits = [d for d in purchase_credits if _is_sgd(d)]
    fx_purchase_credits = [d for d in purchase_credits if not _is_sgd(d)]

    # --- Initialise accumulators ---
    # All eight IRAS F5 boxes; boxes 4 and 8 are derived at the end
    boxes = {
        "box_1_standard_rated_sales": 0.0,
        "box_2_zero_rated_sales": 0.0,
        "box_3_exempt_sales": 0.0,
        "box_4_total_sales": 0.0,
        "box_5_taxable_purchases": 0.0,
        "box_6_output_tax": 0.0,
        "box_7_input_tax": 0.0,
        "box_8_net_gst": 0.0,
    }
    anomalies = []
    # Tracks (DocNum, VatGroup) pairs to emit one anomaly per code per document
    seen_unknown: set = set()
    credit_notes_applied = []

    # --- Accumulate sales invoices ---
    for doc in sgd_sales:
        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
            vg = normalize_vat_group(vg, _tax_code_mappings)
            mapping = F5_BOX_MAPPING.get(vg)
            if mapping is None:
                if vg:
                    key = (doc.get("DocNum"), vg)
                    if key not in seen_unknown:
                        seen_unknown.add(key)
                        anomalies.append({"doc_num": doc.get("DocNum"),
                            "issue": f"unknown VatGroup '{vg}' — not in mapping"})
                continue
            if mapping["side"] != "sales":
                continue
            lt = _safe_float(line.get("LineTotal"))
            tt = _safe_float(line.get("TaxTotal"))
            if mapping["lt_box"]:
                boxes[mapping["lt_box"]] += lt
            if mapping["tt_box"]:
                boxes[mapping["tt_box"]] += tt

    # --- Accumulate purchase invoices ---
    for doc in sgd_purchases:
        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
            vg = normalize_vat_group(vg, _tax_code_mappings)
            mapping = F5_BOX_MAPPING.get(vg)
            if mapping is None:
                if vg:
                    key = (doc.get("DocNum"), vg)
                    if key not in seen_unknown:
                        seen_unknown.add(key)
                        anomalies.append({"doc_num": doc.get("DocNum"),
                            "issue": f"unknown VatGroup '{vg}' — not in mapping"})
                continue
            if mapping["side"] != "purchase":
                continue
            lt = _safe_float(line.get("LineTotal"))
            tt = _safe_float(line.get("TaxTotal"))
            if mapping["lt_box"]:
                boxes[mapping["lt_box"]] += lt
            if mapping["tt_box"]:
                boxes[mapping["tt_box"]] += tt

    # Credit notes are stored with positive amounts in SAP B1 — subtract from boxes.

    # --- Subtract sales credit notes ---
    for doc in sgd_sales_credits:
        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
            vg = normalize_vat_group(vg, _tax_code_mappings)
            mapping = F5_BOX_MAPPING.get(vg)
            if mapping is None:
                if vg:
                    key = (doc.get("DocNum"), vg)
                    if key not in seen_unknown:
                        seen_unknown.add(key)
                        anomalies.append({"doc_num": doc.get("DocNum"),
                            "issue": f"unknown VatGroup '{vg}' — not in mapping (credit note)"})
                continue
            if mapping["side"] != "sales":
                continue
            lt = _safe_float(line.get("LineTotal"))
            tt = _safe_float(line.get("TaxTotal"))
            if mapping["lt_box"]:
                boxes[mapping["lt_box"]] -= lt
            if mapping["tt_box"]:
                boxes[mapping["tt_box"]] -= tt
            credit_notes_applied.append({
                "doc_num": doc.get("DocNum"),
                "doc_date": str(doc.get("DocDate", ""))[:10],
                "card_name": doc.get("CardName", ""),
                "type": "sales_credit_note",
                "vat_group": vg,
                "line_total_applied": -lt,
                "tax_total_applied": -tt,
            })

    # --- Subtract purchase credit notes ---
    for doc in sgd_purchase_credits:
        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
            vg = normalize_vat_group(vg, _tax_code_mappings)
            mapping = F5_BOX_MAPPING.get(vg)
            if mapping is None:
                if vg:
                    key = (doc.get("DocNum"), vg)
                    if key not in seen_unknown:
                        seen_unknown.add(key)
                        anomalies.append({"doc_num": doc.get("DocNum"),
                            "issue": f"unknown VatGroup '{vg}' — not in mapping (credit note)"})
                continue
            if mapping["side"] != "purchase":
                continue
            lt = _safe_float(line.get("LineTotal"))
            tt = _safe_float(line.get("TaxTotal"))
            if mapping["lt_box"]:
                boxes[mapping["lt_box"]] -= lt
            if mapping["tt_box"]:
                boxes[mapping["tt_box"]] -= tt
            credit_notes_applied.append({
                "doc_num": doc.get("DocNum"),
                "doc_date": str(doc.get("DocDate", ""))[:10],
                "card_name": doc.get("CardName", ""),
                "type": "purchase_credit_note",
                "vat_group": vg,
                "line_total_applied": -lt,
                "tax_total_applied": -tt,
            })

    # --- Derive boxes 4 and 8 ---
    # Box 4 = box 1 + box 2 + box 3 per IRAS F5 specification
    boxes["box_4_total_sales"] = (
        boxes["box_1_standard_rated_sales"]
        + boxes["box_2_zero_rated_sales"]
        + boxes["box_3_exempt_sales"]
    )
    # Box 8 = net GST payable (or refundable if negative)
    boxes["box_8_net_gst"] = boxes["box_6_output_tax"] - boxes["box_7_input_tax"]
    # IRAS requires amounts rounded to 2 decimal places
    boxes = {k: round(v, 2) for k, v in boxes.items()}

    # --- Build FX document list and flag E1 candidates ---
    fx_list = []
    e1_candidates = []
    for doc in fx_sales:
        fx_list.append({
            "doc_num": doc.get("DocNum"),
            "doc_date": str(doc.get("DocDate", ""))[:10],
            "currency": doc.get("DocCurrency", ""),
            "doc_total": _safe_float(doc.get("DocTotal")),
            "card_name": doc.get("CardName", ""),
            "type": "sales",
        })
        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
            vg = normalize_vat_group(vg, _tax_code_mappings)
            if vg in _STANDARD_RATE_SALES:
                e1_candidates.append({
                    "doc_num": doc.get("DocNum"),
                    "doc_date": str(doc.get("DocDate", ""))[:10],
                    "card_name": doc.get("CardName", ""),
                    "doc_currency": doc.get("DocCurrency", ""),
                    "vat_group": vg,
                })
    for doc in fx_purchases:
        fx_list.append({
            "doc_num": doc.get("DocNum"),
            "doc_date": str(doc.get("DocDate", ""))[:10],
            "currency": doc.get("DocCurrency", ""),
            "doc_total": _safe_float(doc.get("DocTotal")),
            "card_name": doc.get("CardName", ""),
            "type": "purchase",
        })
    for doc in fx_sales_credits:
        fx_list.append({
            "doc_num": doc.get("DocNum"),
            "doc_date": str(doc.get("DocDate", ""))[:10],
            "currency": doc.get("DocCurrency", ""),
            "doc_total": _safe_float(doc.get("DocTotal")),
            "card_name": doc.get("CardName", ""),
            "type": "sales_credit_note",
        })
    for doc in fx_purchase_credits:
        fx_list.append({
            "doc_num": doc.get("DocNum"),
            "doc_date": str(doc.get("DocDate", ""))[:10],
            "currency": doc.get("DocCurrency", ""),
            "doc_total": _safe_float(doc.get("DocTotal")),
            "card_name": doc.get("CardName", ""),
            "type": "purchase_credit_note",
        })

    return _fmt({
        "period": {"start": period_start, "end": period_end},
        "currency": "SGD",
        "boxes": boxes,
        "fx_invoices_requiring_conversion": fx_list,
        "e1_candidates": e1_candidates,
        "record_counts": {
            "sales_invoices_sgd": len(sgd_sales),
            "sales_invoices_fx": len(fx_sales),
            "purchase_invoices_sgd": len(sgd_purchases),
            "purchase_invoices_fx": len(fx_purchases),
        },
        "credit_note_counts": {
            "sgd_sales": len(sgd_sales_credits),
            "fx_sales": len(fx_sales_credits),
            "sgd_purchases": len(sgd_purchase_credits),
            "fx_purchases": len(fx_purchase_credits),
        },
        "credit_notes_applied": credit_notes_applied,
        "anomalies": anomalies,
    })


def _vg_category(vg: str) -> str:
    """Return a human-readable GST category label for a VatGroup code.

    Args:
        vg: A VatGroup code string, e.g. 'SR', 'ZR', 'TX'.

    Returns:
        str: A descriptive label for the code, or a fallback string indicating
            the code is not in the known mapping.
    """
    _categories = {
        "SR":     "Standard-rated output (sales)",
        "DS":     "Standard-rated output (sales)",
        "ZR":     "Zero-rated supply (sales)",
        "ES33":   "Exempt supply — Reg 33 (sales)",
        "ESN33":  "Exempt supply — non-Reg 33 (sales)",
        "OS":     "Out-of-scope supply (sales)",
        "NG":     "Supply by non-GST-registered business (sales)",
        "TX":     "Standard-rated input (purchases)",
        "ZP":     "Zero-rated purchase (purchases)",
        "IM":     "Import GST (purchases)",
        "IGDS":   "Import GST — IGDS scheme (purchases)",
        "ME":     "Major Exporter Scheme import (purchases)",
        "NR":     "Non-recoverable input (purchases)",
        "BL":     "Blocked input — Reg 26/27 (purchases)",
        "EP":     "Exempt purchase (purchases)",
        "OP":     "Out-of-scope purchase (purchases)",
        "TX-E33": "Tourist refund — Reg 33 (purchases)",
        "TX-N33": "Tourist refund — non-Reg 33 (purchases)",
        "TX-RE":  "Residual input tax (purchases)",
    }
    return _categories.get(vg, f"Unknown VatGroup '{vg}'")


@mcp.tool()
def validate_invoice_tax_codes(period_start: str, period_end: str, expected_rate: float = 0.07, reader=None) -> str:
    """Check all invoice and credit note lines in a period for E1–E4 tax code errors.

    In addition to the per-line error list, builds a vatgroup_inventory that
    maps every VatGroup code seen in the period to its F5 routing metadata.
    This gives auditors a complete picture of which codes are in active use.

    Args:
        period_start:  ISO date string 'YYYY-MM-DD'.
        period_end:    ISO date string 'YYYY-MM-DD'.
        expected_rate: Expected GST rate as a decimal; defaults to 0.07 (7%).
            Pass 0.09 for post-2024 production data.
        reader:        Optional ChainReader (T2.23). None -> default SAP-backed
            reader. Internal DI only; left untyped (see calculate_f5_return).

    Returns:
        str: JSON string containing:
            - period: the requested date range
            - expected_rate: the rate used for E4 checks
            - vatgroup_inventory: all distinct VatGroup codes seen, with
              GST category, F5 box routing, and document count
            - issues: list of E1–E4 issue dicts from _classify_line
            - summary: per-code and total issue counts
    """
    # T2.23: reads via the chain source seam; default = SAP-backed reader.
    reader = _resolve_reader(reader)
    invoices = reader.fetch_invoices("Invoices", period_start, period_end)
    purchases = reader.fetch_invoices("PurchaseInvoices", period_start, period_end)

    issues = []
    # Tracks all distinct VatGroup codes seen to help auditors understand active codes
    vg_inventory: dict[str, dict] = {}

    for doc in invoices:
        for line in doc.get("DocumentLines", []):
            issues.extend(_classify_line(line, doc, entity_type="sales", expected_rate=expected_rate))
            vg = (line.get("VatGroup") or "").strip()
            vg = normalize_vat_group(vg, _tax_code_mappings)
            if vg:
                if vg not in vg_inventory:
                    mapping = F5_BOX_MAPPING.get(vg, {})
                    vg_inventory[vg] = {
                        "gst_category": _vg_category(vg),
                        "side": mapping.get("side", "unknown"),
                        "lt_box": mapping.get("lt_box"),
                        "tt_box": mapping.get("tt_box"),
                        "doc_count": 0,
                        "known_to_mapping": vg in F5_BOX_MAPPING,
                    }
                vg_inventory[vg]["doc_count"] += 1

    for doc in purchases:
        for line in doc.get("DocumentLines", []):
            issues.extend(_classify_line(line, doc, entity_type="purchase", expected_rate=expected_rate))
            vg = (line.get("VatGroup") or "").strip()
            vg = normalize_vat_group(vg, _tax_code_mappings)
            if vg:
                if vg not in vg_inventory:
                    mapping = F5_BOX_MAPPING.get(vg, {})
                    vg_inventory[vg] = {
                        "gst_category": _vg_category(vg),
                        "side": mapping.get("side", "unknown"),
                        "lt_box": mapping.get("lt_box"),
                        "tt_box": mapping.get("tt_box"),
                        "doc_count": 0,
                        "known_to_mapping": vg in F5_BOX_MAPPING,
                    }
                vg_inventory[vg]["doc_count"] += 1

    for doc in reader.fetch_credit_notes("sales", period_start, period_end):
        for line in doc.get("DocumentLines", []):
            issues.extend(_classify_line(line, doc, entity_type="sales", expected_rate=expected_rate, credit_note=True))
            vg = (line.get("VatGroup") or "").strip()
            vg = normalize_vat_group(vg, _tax_code_mappings)
            if vg:
                if vg not in vg_inventory:
                    mapping = F5_BOX_MAPPING.get(vg, {})
                    vg_inventory[vg] = {
                        "gst_category": _vg_category(vg),
                        "side": mapping.get("side", "unknown"),
                        "lt_box": mapping.get("lt_box"),
                        "tt_box": mapping.get("tt_box"),
                        "doc_count": 0,
                        "known_to_mapping": vg in F5_BOX_MAPPING,
                    }
                vg_inventory[vg]["doc_count"] += 1

    for doc in reader.fetch_credit_notes("purchases", period_start, period_end):
        for line in doc.get("DocumentLines", []):
            issues.extend(_classify_line(line, doc, entity_type="purchase", expected_rate=expected_rate, credit_note=True))
            vg = (line.get("VatGroup") or "").strip()
            vg = normalize_vat_group(vg, _tax_code_mappings)
            if vg:
                if vg not in vg_inventory:
                    mapping = F5_BOX_MAPPING.get(vg, {})
                    vg_inventory[vg] = {
                        "gst_category": _vg_category(vg),
                        "side": mapping.get("side", "unknown"),
                        "lt_box": mapping.get("lt_box"),
                        "tt_box": mapping.get("tt_box"),
                        "doc_count": 0,
                        "known_to_mapping": vg in F5_BOX_MAPPING,
                    }
                vg_inventory[vg]["doc_count"] += 1

    summary = {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 0}
    for issue in issues:
        code = issue.get("error_code", "")
        if code in summary:
            summary[code] += 1
    summary["total"] = sum(summary[k] for k in ("E1", "E2", "E3", "E4"))

    return _fmt({
        "period": {"start": period_start, "end": period_end},
        "expected_rate": expected_rate,
        "vatgroup_inventory": vg_inventory,
        "issues": issues,
        "summary": summary,
    })


def _reader_field_covered(reader, surface: str, field: str) -> bool:
    """Duck-typed probe: does the reader declare ``(surface, field)`` value-covered?

    Returns True when the reader exposes no ``coverage()`` seam (the live SAP reader and
    the frozen-replay reader) so existing behaviour is unchanged and byte-identical there.
    The extract feeder returns an ``ExtractCoverage`` whose ``is_covered`` is value-aware
    (present AND populated). A failing probe defaults to covered — coverage must never
    break detection. No import of ``feeders`` (read entirely through duck typing).
    """
    cov_fn = getattr(reader, "coverage", None)
    if not callable(cov_fn):
        return True
    try:
        return bool(cov_fn().is_covered(surface, field))
    except Exception:
        return True


@mcp.tool()
def detect_gst_errors(period_start: str, period_end: str, expected_rate: float = 0.07, reader=None) -> str:
    """Audit GST compliance: E1–E4 line errors on invoices and credit notes, purchase completeness check, and supplier GST registration validation.

    Issues sorted HIGH → MEDIUM → LOW. expected_rate defaults to 0.07; pass 0.09
    for post-2024 production data.

    Args:
        period_start:  ISO date string 'YYYY-MM-DD'.
        period_end:    ISO date string 'YYYY-MM-DD'.
        expected_rate: Expected GST rate as a decimal. Defaults to 0.07 (7%).
        reader:        Optional ChainReader (T2.23). None -> default SAP-backed
            reader. Internal DI only; left untyped (see calculate_f5_return).

    Returns:
        str: JSON string containing:
            - period: the requested date range
            - severity_counts: count of HIGH / MEDIUM / LOW issues
            - issues: list of enriched issue dicts with severity, error_code,
              doc_num, doc_date, card_name, description, and recommendation.
              Additional error codes beyond E1–E4:
                COMPLETENESS — purchase volume is suspiciously low vs. sales
                NO_GST_REG   — input tax claimed from a supplier with no GST
                               registration number on their business partner record
    """
    # --- Fetch (T2.23: via the chain source seam; default = SAP-backed reader) ---
    reader = _resolve_reader(reader)
    invoices = reader.fetch_invoices("Invoices", period_start, period_end)
    purchases = reader.fetch_invoices("PurchaseInvoices", period_start, period_end)
    purchase_credits = reader.fetch_credit_notes("purchases", period_start, period_end)

    _severity_map = {"E1": "HIGH", "E2": "MEDIUM", "E3": "HIGH", "E4": "MEDIUM"}
    _rec_map = {
        "E1": "Reclassify as ZR (zero-rated) if this is an export sale.",
        "E2": "Remove the GST charge or correct the tax code to a standard-rated code.",
        "E3": "Apply GST at the applicable rate, or reclassify if the supply is exempt or zero-rated.",
        "E4": "Review the GST rate — demo data uses 7%, production uses 9% from 1 Jan 2024.",
    }

    # --- Classify all lines ---
    raw_issues = []
    for doc in invoices:
        for line in doc.get("DocumentLines", []):
            raw_issues.extend(_classify_line(line, doc, entity_type="sales", expected_rate=expected_rate))
    for doc in purchases:
        for line in doc.get("DocumentLines", []):
            raw_issues.extend(_classify_line(line, doc, entity_type="purchase", expected_rate=expected_rate))
    for doc in reader.fetch_credit_notes("sales", period_start, period_end):
        for line in doc.get("DocumentLines", []):
            raw_issues.extend(_classify_line(line, doc, entity_type="sales", expected_rate=expected_rate, credit_note=True))
    for doc in purchase_credits:
        for line in doc.get("DocumentLines", []):
            raw_issues.extend(_classify_line(line, doc, entity_type="purchase", expected_rate=expected_rate, credit_note=True))

    issues = []
    for issue in raw_issues:
        code = issue.get("error_code", "")
        issues.append({
            "severity": _severity_map.get(code, "LOW"),
            "error_code": code,
            "doc_num": issue.get("doc_num"),
            "doc_date": issue.get("doc_date"),
            "card_name": issue.get("card_name"),
            "description": issue.get("description"),
            "recommendation": _rec_map.get(code, "Review and correct."),
        })

    # Completeness check: flag if purchase volume is suspiciously low relative to sales
    sales_count = len(invoices)
    purchase_count = len(purchases)
    # 10% heuristic — one purchase per ten sales is suspiciously low for most businesses
    if sales_count > 0 and purchase_count / sales_count < 0.1:
        issues.append({
            "severity": "MEDIUM",
            "error_code": "COMPLETENESS",
            "doc_num": None,
            "doc_date": None,
            "card_name": None,
            "description": (
                f"Suspiciously low purchase volume — {purchase_count} purchase invoice(s) vs "
                f"{sales_count} sales invoice(s) — input tax may be understated."
            ),
            "recommendation": "Verify all supplier invoices for the period have been entered in SAP B1.",
        })

    # NO_GST_REG: flag first occurrence per unregistered CardCode with input tax.
    # Covers both purchase invoices and purchase credit notes.
    # Cache avoids redundant /BusinessPartners API calls for the same CardCode
    bp_cache: dict = {}
    # Emit only one NO_GST_REG issue per supplier, not one per document
    flagged_suppliers: set = set()
    # T2.12 slice 2B: NO_GST_REG is load-bearing on FederalTaxID (the supplier GST
    # registration number). When the reader declares that surface unavailable (column
    # absent / 0%-populated), the check CANNOT run — emit NO issues here (no degraded
    # variant); the chain surfaces the data-coverage caveat instead. Readers without a
    # coverage() seam (live SAP, frozen replay) report covered → unchanged behaviour.
    # Surface/field are plain strings (mirroring schema.BUSINESS_PARTNERS_SHEET) so the
    # live server takes no dependency on feeders.
    _no_gst_reg_docs = (
        list(purchases) + list(purchase_credits)
        if _reader_field_covered(reader, "business_partners", "FederalTaxID")
        else []
    )
    for doc in _no_gst_reg_docs:
        card_code = doc.get("CardCode", "")
        if not card_code or card_code in flagged_suppliers:
            continue
        has_input_tax = any(_safe_float(ln.get("TaxTotal")) > 0.01 for ln in doc.get("DocumentLines", []))
        if not has_input_tax:
            continue
        if card_code not in bp_cache:
            try:
                bp = reader.get_business_partner(card_code)
                bp_cache[card_code] = (bp.get("FederalTaxID") or "").strip()
            except Exception:
                bp_cache[card_code] = ""
        if not bp_cache.get(card_code):
            flagged_suppliers.add(card_code)
            issues.append({
                "severity": "HIGH",
                "error_code": "NO_GST_REG",
                "doc_num": doc.get("DocNum"),
                "doc_date": str(doc.get("DocDate", ""))[:10],
                "card_name": doc.get("CardName", ""),
                "description": (
                    f"Input tax claimed from supplier {card_code} ({doc.get('CardName', '')}) "
                    "without a GST registration number — may not be claimable."
                ),
                "recommendation": "Obtain a valid tax invoice with the supplier's GST registration number, or reverse the input tax claim.",
            })

    # --- Sort and count by severity ---
    # Maps severity strings to integer sort keys so HIGH appears before MEDIUM/LOW
    _severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    issues.sort(key=lambda x: (
        _severity_order.get(x.get("severity", "LOW"), 2),
        x.get("doc_date") or "",
    ))

    severity_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for issue in issues:
        sev = issue.get("severity", "LOW")
        if sev in severity_counts:
            severity_counts[sev] += 1

    return _fmt({
        "period": {"start": period_start, "end": period_end},
        "severity_counts": severity_counts,
        "issues": issues,
    })


def main():
    """Entry point for the MCP stdio server process.

    Logs the configured SAP connection parameters for diagnostics, then starts
    the FastMCP event loop which reads JSON-RPC messages from stdin and writes
    responses to stdout.  This function blocks indefinitely until the process
    is terminated.

    Note:
        Do not call this when importing the module into an orchestrator chain.
        Use configure_client() and call the tool functions directly instead.
    """
    logger.info("Starting SAP B1 MCP Server (FastMCP stdio)")
    logger.info(f"  SAP_BASE_URL: {sap.base_url}")
    logger.info(f"  SAP_COMPANY_DB: {sap.company_db}")
    logger.info(f"  SAP_USERNAME: {sap.username}")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
