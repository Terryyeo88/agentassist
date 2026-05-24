#!/usr/bin/env python3
"""
SAP Business One MCP Server for Claude Desktop (FastMCP + stdio)
Uses the recommended FastMCP pattern from the official MCP docs.
"""

import os
import sys
import json
import logging
from typing import Any, Optional
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment variables
load_dotenv()

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

    def __init__(self):
        self.base_url = os.getenv("SAP_BASE_URL", "").rstrip("/")
        self.company_db = os.getenv("SAP_COMPANY_DB", "")
        self.username = os.getenv("SAP_USERNAME", "")
        self.password = os.getenv("SAP_PASSWORD", "")
        self.session_id: Optional[str] = None
        self.session_timeout: Optional[datetime] = None
        self.http = httpx.Client(verify=False, timeout=30.0)
        logger.info(f"SAP B1 Client initialized for {self.base_url}")

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


# Global SAP client
sap = SAPB1Client()


def _fmt(data: Any) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


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


def main():
    logger.info("Starting SAP B1 MCP Server (FastMCP stdio)")
    logger.info(f"  SAP_BASE_URL: {os.getenv('SAP_BASE_URL', 'NOT SET')}")
    logger.info(f"  SAP_COMPANY_DB: {os.getenv('SAP_COMPANY_DB', 'NOT SET')}")
    logger.info(f"  SAP_USERNAME: {os.getenv('SAP_USERNAME', 'NOT SET')}")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
