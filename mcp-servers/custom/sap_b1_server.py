#!/usr/bin/env python3
"""
SAP Business One MCP Server for Claude Desktop (FastMCP + stdio)
Uses the recommended FastMCP pattern from the official MCP docs.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Any, Optional
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
        self.base_url = config.service_layer_url
        self.company_db = config.company_db
        self.username = config.username
        self.password = config.password
        self.ssl_verify = config.ssl_verify
        self.session_id: Optional[str] = None
        self.session_timeout: Optional[datetime] = None
        self.http = httpx.Client(verify=self.ssl_verify, timeout=30.0)
        logger.info(
            f"SAP B1 Client initialised for {self.base_url} "
            f"(company_db={self.company_db}, client={config.client_id})"
        )

    def login(self) -> dict:
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
            timeout_mins = data.get("SessionTimeout", 30)
            self.session_timeout = datetime.now() + timedelta(minutes=timeout_mins)
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
        if self.session_id and self.session_timeout and datetime.now() < self.session_timeout:
            return
        logger.info("Session expired or missing — re-authenticating")
        self.login()

    def request(self, method: str, endpoint: str, **kwargs) -> Any:
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
        return self.request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: dict = None) -> Any:
        return self.request("POST", endpoint, json=data)

    def patch(self, endpoint: str, data: dict = None) -> Any:
        return self.request("PATCH", endpoint, json=data)

    def delete(self, endpoint: str) -> Any:
        return self.request("DELETE", endpoint)

    def logout(self) -> dict:
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
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# --- Shared helpers for accounting tools ---

def _safe_float(val) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_sgd(doc: dict) -> bool:
    currency = (doc.get("DocCurrency") or "SGD").strip().upper()
    return currency in ("SGD", "S$", "")


# VatGroup → F5 box routing. lt_box = line total destination, tt_box = tax total destination.
F5_BOX_MAPPING = {
    "SO":     {"lt_box": "box_1_standard_rated_sales", "tt_box": "box_6_output_tax",  "side": "sales"},
    "DS":     {"lt_box": "box_1_standard_rated_sales", "tt_box": "box_6_output_tax",  "side": "sales"},
    "ZR":     {"lt_box": "box_2_zero_rated_sales",     "tt_box": None,                "side": "sales"},
    "ES33":   {"lt_box": "box_3_exempt_sales",         "tt_box": None,                "side": "sales"},
    "ESN33":  {"lt_box": "box_3_exempt_sales",         "tt_box": None,                "side": "sales"},
    "OS":     {"lt_box": None,                         "tt_box": None,                "side": "sales"},
    "SI":     {"lt_box": "box_5_taxable_purchases",    "tt_box": "box_7_input_tax",   "side": "purchase"},
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
_E2_ZERO_RATE_CODES = {"ZR", "OS", "ES33", "ESN33", "BL", "NR"}
_STANDARD_RATE_SALES = {"SO", "DS"}


# ── Module-level initialisation ───────────────────────────────────────────────

def _load_sap_config() -> ClientConfig:
    """
    Load client config from YAML. CLIENT_ID must be set — no silent fallback.

    Correction 2: if CLIENT_ID is absent we refuse to guess the target instance.
    A misconfigured MCP server silently pointed at the wrong SAP company database
    is a hard-to-detect, hard-to-undo data integrity risk.
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


try:
    _client_config = _load_sap_config()
    # Merge client-specific VatGroup codes into the standard mapping (additive only).
    # Collision with standard codes is already rejected by load_client_config, so
    # this loop can only add new codes — never overwrite existing ones.
    for _code, _mapping in _client_config.custom_vat_groups.items():
        F5_BOX_MAPPING[_code] = _mapping
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
) -> None:
    """
    Override the module-level SAP client for orchestrator chain use.
    Accepts primitives only — no ClientConfig import; keeps dependency direction one-way.
    Call once before invoking any step function. Does not affect MCP tool signatures.
    """
    global sap

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

    logger.info(
        f"configure_client: SAP client set for {company_db} at {service_layer_url}"
    )


def _fetch_invoices_paginated(entity: str, period_start: str, period_end: str) -> list:
    """Fetch all records with DocumentLines for the period, paginating 20 at a time."""
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
        if len(page) < 20:
            break
        skip += 20
    return results


def _fetch_credit_notes_paginated(entity_type: str, period_start: str, period_end: str) -> list:
    """Fetch all credit notes with DocumentLines for the period, paginating 20 at a time.
    entity_type: 'sales' → CreditNotes, 'purchases' → PurchaseCreditNotes.
    Returned dicts are tagged is_credit_note=True; callers must negate LineTotal/TaxTotal.
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
        if len(page) < 20:
            break
        skip += 20
    return results


def _classify_line(line: dict, doc: dict, entity_type: str = "sales", expected_rate: float = 0.07, credit_note: bool = False) -> list:
    """Check one document line for E1–E4 issues. Returns a list of issue dicts."""
    issues = []
    vg = (line.get("VatGroup") or "").strip()
    line_total = _safe_float(line.get("LineTotal"))
    tax_total = _safe_float(line.get("TaxTotal"))
    currency = (doc.get("DocCurrency") or "SGD").strip().upper()
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
    if tax_total > 0.01 and vg in _E2_ZERO_RATE_CODES:
        issues.append({**base, "error_code": "E2",
            "description": f"{prefix}Tax {tax_total:.2f} charged on non-taxable supply (VatGroup={vg})"})

    # E3: Standard-rated code with zero tax
    if entity_type == "sales" and vg in _STANDARD_RATE_SALES and line_total > 0.01 and tax_total < 0.01:
        issues.append({**base, "error_code": "E3",
            "description": f"{prefix}Standard-rated line (VatGroup={vg}) with zero tax on {line_total:.2f}"})
    if entity_type == "purchase" and vg == "SI" and line_total > 0.01 and tax_total < 0.01:
        issues.append({**base, "error_code": "E3",
            "description": f"{prefix}Standard-rated purchase (VatGroup=SI) with zero tax on {line_total:.2f}"})

    # E4: GST rate deviates from expected (SO and SI only per spec)
    if vg in {"SO", "SI"} and line_total > 0.01 and tax_total > 0.01:
        ratio = tax_total / line_total
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
    if key.isdigit():
        endpoint = f"/{entity}({key})"
    else:
        endpoint = f"/{entity}('{key}')"
    result = sap.delete(endpoint)
    return _fmt(result)


@mcp.tool()
def calculate_f5_return(period_start: str, period_end: str) -> str:
    """Calculate GST F5 return boxes 1–8 for a period. Dates must be ISO format YYYY-MM-DD. SGD invoices and credit notes contribute to box totals; credit note amounts are subtracted. FX documents are listed separately for manual conversion."""
    invoices = _fetch_invoices_paginated("Invoices", period_start, period_end)
    purchases = _fetch_invoices_paginated("PurchaseInvoices", period_start, period_end)
    sales_credits = _fetch_credit_notes_paginated("sales", period_start, period_end)
    purchase_credits = _fetch_credit_notes_paginated("purchases", period_start, period_end)

    sgd_sales = [d for d in invoices if _is_sgd(d)]
    fx_sales = [d for d in invoices if not _is_sgd(d)]
    sgd_purchases = [d for d in purchases if _is_sgd(d)]
    fx_purchases = [d for d in purchases if not _is_sgd(d)]
    sgd_sales_credits = [d for d in sales_credits if _is_sgd(d)]
    fx_sales_credits = [d for d in sales_credits if not _is_sgd(d)]
    sgd_purchase_credits = [d for d in purchase_credits if _is_sgd(d)]
    fx_purchase_credits = [d for d in purchase_credits if not _is_sgd(d)]

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
    seen_unknown: set = set()
    credit_notes_applied = []

    for doc in sgd_sales:
        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
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

    for doc in sgd_purchases:
        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
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
    for doc in sgd_sales_credits:
        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
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

    for doc in sgd_purchase_credits:
        for line in doc.get("DocumentLines", []):
            vg = (line.get("VatGroup") or "").strip()
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

    boxes["box_4_total_sales"] = (
        boxes["box_1_standard_rated_sales"]
        + boxes["box_2_zero_rated_sales"]
        + boxes["box_3_exempt_sales"]
    )
    boxes["box_8_net_gst"] = boxes["box_6_output_tax"] - boxes["box_7_input_tax"]
    boxes = {k: round(v, 2) for k, v in boxes.items()}

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
    """Return a human-readable GST category label for a VatGroup code."""
    _categories = {
        "SO":     "Standard-rated output (sales)",
        "DS":     "Standard-rated output (sales)",
        "ZR":     "Zero-rated supply (sales)",
        "ES33":   "Exempt supply — Reg 33 (sales)",
        "ESN33":  "Exempt supply — non-Reg 33 (sales)",
        "OS":     "Out-of-scope supply (sales)",
        "SI":     "Standard-rated input (purchases)",
        "ZP":     "Zero-rated purchase (purchases)",
        "IM":     "Import GST (purchases)",
        "IGDS":   "Import GST — IGDS scheme (purchases)",
        "ME":     "Minor/miscellaneous exempt (purchases)",
        "NR":     "Non-recoverable input (purchases)",
        "BL":     "Blocked input — Reg 26/27 (purchases)",
        "EP":     "Exempt purchase (purchases)",
        "OP":     "Out-of-scope purchase (purchases)",
        "TX-E33": "Tourist refund — Reg 33 (purchases)",
        "TX-N33": "Tourist refund — non-Reg 33 (purchases)",
        "TX-RE":  "Tourist refund — retail (purchases)",
    }
    return _categories.get(vg, f"Unknown VatGroup '{vg}'")


@mcp.tool()
def validate_invoice_tax_codes(period_start: str, period_end: str, expected_rate: float = 0.07) -> str:
    """Check all invoice and credit note lines in a period for E1–E4 tax code errors. expected_rate defaults to 0.07 (7%); pass 0.09 for post-2024 production data."""
    invoices = _fetch_invoices_paginated("Invoices", period_start, period_end)
    purchases = _fetch_invoices_paginated("PurchaseInvoices", period_start, period_end)

    issues = []
    vg_inventory: dict[str, dict] = {}

    for doc in invoices:
        for line in doc.get("DocumentLines", []):
            issues.extend(_classify_line(line, doc, entity_type="sales", expected_rate=expected_rate))
            vg = (line.get("VatGroup") or "").strip()
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

    for doc in _fetch_credit_notes_paginated("sales", period_start, period_end):
        for line in doc.get("DocumentLines", []):
            issues.extend(_classify_line(line, doc, entity_type="sales", expected_rate=expected_rate, credit_note=True))
            vg = (line.get("VatGroup") or "").strip()
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

    for doc in _fetch_credit_notes_paginated("purchases", period_start, period_end):
        for line in doc.get("DocumentLines", []):
            issues.extend(_classify_line(line, doc, entity_type="purchase", expected_rate=expected_rate, credit_note=True))
            vg = (line.get("VatGroup") or "").strip()
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


@mcp.tool()
def detect_gst_errors(period_start: str, period_end: str, expected_rate: float = 0.07) -> str:
    """Audit GST compliance: E1–E4 line errors on invoices and credit notes, purchase completeness check, and supplier GST registration validation. Issues sorted HIGH → MEDIUM → LOW. expected_rate defaults to 0.07; pass 0.09 for post-2024 production data."""
    invoices = _fetch_invoices_paginated("Invoices", period_start, period_end)
    purchases = _fetch_invoices_paginated("PurchaseInvoices", period_start, period_end)
    purchase_credits = _fetch_credit_notes_paginated("purchases", period_start, period_end)

    _severity_map = {"E1": "HIGH", "E2": "MEDIUM", "E3": "HIGH", "E4": "MEDIUM"}
    _rec_map = {
        "E1": "Reclassify as ZR (zero-rated) if this is an export sale.",
        "E2": "Remove the GST charge or correct the tax code to a standard-rated code.",
        "E3": "Apply GST at the applicable rate, or reclassify if the supply is exempt or zero-rated.",
        "E4": "Review the GST rate — demo data uses 7%, production uses 9% from 1 Jan 2024.",
    }

    raw_issues = []
    for doc in invoices:
        for line in doc.get("DocumentLines", []):
            raw_issues.extend(_classify_line(line, doc, entity_type="sales", expected_rate=expected_rate))
    for doc in purchases:
        for line in doc.get("DocumentLines", []):
            raw_issues.extend(_classify_line(line, doc, entity_type="purchase", expected_rate=expected_rate))
    for doc in _fetch_credit_notes_paginated("sales", period_start, period_end):
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
    bp_cache: dict = {}
    flagged_suppliers: set = set()
    for doc in list(purchases) + list(purchase_credits):
        card_code = doc.get("CardCode", "")
        if not card_code or card_code in flagged_suppliers:
            continue
        has_input_tax = any(_safe_float(ln.get("TaxTotal")) > 0.01 for ln in doc.get("DocumentLines", []))
        if not has_input_tax:
            continue
        if card_code not in bp_cache:
            try:
                bp = sap.get(f"/BusinessPartners('{card_code}')")
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
    logger.info("Starting SAP B1 MCP Server (FastMCP stdio)")
    logger.info(f"  SAP_BASE_URL: {sap.base_url}")
    logger.info(f"  SAP_COMPANY_DB: {sap.company_db}")
    logger.info(f"  SAP_USERNAME: {sap.username}")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
