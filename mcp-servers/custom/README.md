# SAP B1 MCP Server (Custom — Claude Desktop)

## Why This Exists

The NXr10/MCP-SAP server is built as a **FastAPI HTTP server** for Microsoft Copilot Studio.
Claude Desktop expects **stdio transport** (stdin/stdout), not HTTP. Additionally, MCP-SAP
only exposes 3 tools (connect, status, create sales order) — no read operations.

This custom server:
- Uses **stdio transport** so Claude Desktop can launch it directly
- Uses **async httpx** instead of sync requests (required by MCP stdio)
- Exposes **12 tools** covering login, read, write, and delete across all major B1 entities
- Reuses the authentication patterns from MCP-SAP's sap_client.py
- Handles session expiry and automatic re-authentication

## Tools Available

| Tool | Description |
|------|-------------|
| `sap_login` | Authenticate to SAP B1 |
| `sap_logout` | Close session |
| `sap_query` | Query ANY entity with full OData support ($select, $filter, $top, $orderby) |
| `sap_get_business_partners` | List customers/vendors/leads with search |
| `sap_get_business_partner` | Get single BP by CardCode |
| `sap_create_business_partner` | Create new customer/vendor/lead |
| `sap_get_items` | List products/services |
| `sap_create_document` | Create any document (Invoice, PO, SO, CreditNote, etc.) |
| `sap_get_document` | Get single document by DocEntry |
| `sap_create_journal_entry` | Create manual journal entries |
| `sap_delete` | Delete any record |

The `sap_query` tool is the most powerful — it can query any Service Layer entity
(SalesTaxCodes, ChartOfAccounts, Invoices, JournalEntries, Currencies, etc.)
with full OData filtering. This is essential for the exploration phase.

## Configuration

This server requires environment variables for SAP B1 Service Layer
access. Copy `config/env.example` to `.env` at repo root and fill in
values. The server will refuse to start if any required variable is
missing.

Required variables:
- `SAP_BASE_URL`: full Service Layer URL (e.g. `https://host:50000/b1s/v2`)
- `SAP_COMPANY_DB`: SAP B1 company database name
- `SAP_USERNAME`, `SAP_PASSWORD`: SAP B1 credentials
- `SAP_SSL_VERIFY`: `true` (production) or `false` (demo only — SBODEMOSG uses a self-signed cert)

See `exploration-notes/security-decisions.md` for the current security
posture and deferred items.

## Setup

```bash
cp config/env.example .env   # then edit .env with real values
cd mcp-servers/custom
pip install -r requirements.txt
```

## Claude Desktop Config

Edit `%APPDATA%\Claude\claude_desktop_config.json` and add to mcpServers:

```json
"sap-b1": {
    "command": "python",
    "args": ["C:\\Users\\terry\\Desktop\\AgentAssist\\sap-b1-ai-agent\\mcp-servers\\custom\\sap_b1_server.py"],
    "env": {
        "SAP_BASE_URL": "https://<CAL-IP>:50000/b1s/v2",
        "SAP_COMPANY_DB": "SBODEMOSG",
        "SAP_USERNAME": "manager",
        "SAP_PASSWORD": "<your-password>"
    }
}
```

## Testing Without Claude Desktop

```bash
# Set env vars first
set SAP_BASE_URL=https://<IP>:50000/b1s/v2
set SAP_COMPANY_DB=SBODEMOSG
set SAP_USERNAME=manager
set SAP_PASSWORD=<password>

# Run server (it will wait for MCP protocol messages on stdin)
python sap_b1_server.py
```
