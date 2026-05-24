# SAP B1 AI Agent — Project Directory

## Folder Structure

```
sap-b1-ai-agent/
├── README.md                  ← You are here
├── config/                    ← Claude Desktop config, .env files, connection settings
│   ├── .env.example           ← Template for SAP B1 connection variables
│   └── claude_desktop_config.json.example  ← Template for MCP server config
├── keys/                      ← SSH PEM key from SAP CAL (DO NOT COMMIT TO GIT)
├── mcp-servers/               ← Clone MCP server repos here
│   ├── (NXr10-MCP-SAP/)       ← Primary: git clone https://github.com/NXr10/MCP-SAP.git
│   ├── (sap-odata-mcp-server/) ← Fallback: git clone https://github.com/GutjahrAI/sap-odata-mcp-server.git
│   └── (custom/)              ← If you build your own minimal MCP server
├── skills/                    ← Prompt 3: Structured markdown instruction files for Claude
│   ├── (gst-validation.md)
│   ├── (invoice-creation.md)
│   └── (f5-return.md)
├── knowledge-base/            ← Prompt 3: Singapore accounting compliance reference docs
│   ├── (sg-gst-tax-codes.md)
│   ├── (iras-requirements.md)
│   └── (invoicenow-peppol.md)
├── system-prompts/            ← Prompt 3: System prompts for the AI agent
├── exploration-notes/         ← Prompt 2: Findings from B1 API exploration sessions
│   ├── (session-001.md)
│   └── (data-formats.md)
└── scripts/                   ← Utility scripts (curl tests, automation)
    └── (test-service-layer.sh)
```

## Current Phase: Prompt 1 — Environment Setup

### SAP B1 Instance Details (fill in once deployed)
- **CAL Appliance Name:** 
- **External IP:** 
- **Service Layer URL:** https://<IP>:50000/b1s/v2/
- **Company Database:** SBODEMOSG
- **Username:** manager
- **Password:** (stored in password manager, not here)
- **Localisation:** Singapore
- **License Expiry:** ~30 days from deployment

### Cost Tracking
| Date | Hours Active | Compute Cost (est.) | Notes |
|------|-------------|-------------------|-------|
|      |             |                   | First deployment |

## What Goes Where

- **Cloned repos** → `mcp-servers/` (keep them here, not scattered on your machine)
- **SAP CAL PEM key** → `keys/` (add to .gitignore immediately)
- **Connection credentials** → `config/.env` (add to .gitignore immediately)  
- **Session notes from each work sprint** → `exploration-notes/`
- **Everything from Prompt 3** → `skills/`, `knowledge-base/`, `system-prompts/`
