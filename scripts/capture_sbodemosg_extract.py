#!/usr/bin/env python3
"""scripts/capture_sbodemosg_extract.py — T2.12a SBODEMOSG ground-truth capture.

Freezes the six SAP read surfaces the deterministic chain consumes (recon S0–S5,
see exploration-notes/t2.12a-read-surface-inventory.md) **verbatim**, plus a
same-session compiled replay oracle, into tests/fixtures/sbodemosg-extract/.

Read-only against SAP — performs ZERO SAP writes (no create/cancel/delete).
Idempotent and re-runnable: every run overwrites the fixtures from the current
live data state and rewrites capture-manifest.json with fresh counts + hashes.

The faithfulness contract this enables (tested by a separate follow-on prompt):
    adapter(extract) == frozen_ground_truth
and, for the compiled oracle:
    run_chain(off frozen raw) == _replay-oracle.compiled.json

Surfaces (verbatim function output, no transform):
    S0  inline-counts.json          @odata.count per entity (+ the @-prefix key)
    S1  invoices.raw.json           _fetch_invoices_paginated("Invoices")
    S1  purchase-invoices.raw.json  _fetch_invoices_paginated("PurchaseInvoices")
    S2  credit-notes.raw.json       _fetch_credit_notes_paginated("sales")
    S2  purchase-credit-notes.raw.json _fetch_credit_notes_paginated("purchases")
    S3  business-partners.raw.json  GET /BusinessPartners('{CardCode}') per supplier
    S4  si-purchase-lines.json      fetch_si_purchase_lines (CN unflipped, as returned)
    S5  listing-headers.json        fetch_listing_data (incl. company-wide)
    oracle  _replay-oracle.compiled.json  run_chain -> CompileOutput + gate_results

The period is pinned from tests/fixtures/chain-run-sample.json — never hardcoded.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Path setup: make repo modules importable regardless of caller cwd ---
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_CUSTOM = _REPO_ROOT / "mcp-servers" / "custom"
for _p in (str(_MCP_CUSTOM), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv  # noqa: E402

# Load the repo-root .env (gitignored); fall back to a cwd-upward search.
if not load_dotenv(_REPO_ROOT / ".env"):
    load_dotenv()

from config.loader import load_client_config  # noqa: E402
from audit_bundle.canonical import canonical_json, sha256_file  # noqa: E402
import sap_b1_server as sap_server  # noqa: E402
from reasoning.sap_lines import fetch_si_purchase_lines  # noqa: E402
from orchestrator.steps import fetch_listing_data  # noqa: E402
from orchestrator.chain import run_chain  # noqa: E402

CLIENT_ID = "sbodemosg"
OUT_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
# v2 Service Layer returns the inline count under this key (note the @ prefix).
# orchestrator/steps.py reads "odata.count" (no @) — the Gate-1 latent bug,
# operational-backlog item 5. Recording the key here makes a future fix testable.
INLINECOUNT_KEY = "@odata.count"
ENTITIES = ("Invoices", "PurchaseInvoices", "CreditNotes", "PurchaseCreditNotes")


def _set_default(obj):
    """json.dump default: sets -> sorted lists (mirrors audit_bundle.canonical)."""
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _write_pretty(path: Path, obj) -> None:
    """Write a verbatim surface fixture as indented, diff-friendly JSON."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, default=_set_default)
        fh.write("\n")


def _pin_period() -> dict:
    """Pin the capture period from the existing compiled fixture (never hardcode)."""
    sample = _REPO_ROOT / "tests" / "fixtures" / "chain-run-sample.json"
    return json.load(open(sample, encoding="utf-8"))["period"]


def _inline_count(entity: str, start: str, end: str) -> int | None:
    """Read the @odata.count for one entity over the period (read-only probe)."""
    resp = sap_server.sap.get(f"/{entity}", params={
        "$filter": f"DocDate ge '{start}' and DocDate le '{end}'",
        "$top": 0,
        "$inlinecount": "allpages",
    })
    raw = resp.get(INLINECOUNT_KEY)
    return int(raw) if raw is not None else None


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_client_config(CLIENT_ID, check_connectivity=True)
    sap_server.configure_client(
        cfg.service_layer_url, cfg.company_db, cfg.username, cfg.password,
        cfg.ssl_verify, cfg.custom_vat_groups, cfg.effective_tax_code_mappings,
    )

    period = _pin_period()
    start, end = period["start"], period["end"]
    print(f"capture: client={CLIENT_ID} period={period} sl={cfg.service_layer_url}")

    # --- S1: period line-level invoices (full payloads, verbatim) ---
    invoices = sap_server._fetch_invoices_paginated("Invoices", start, end)
    purchases = sap_server._fetch_invoices_paginated("PurchaseInvoices", start, end)

    # --- S2: credit notes (tagged is_credit_note=True, as the helper returns) ---
    sales_cn = sap_server._fetch_credit_notes_paginated("sales", start, end)
    purch_cn = sap_server._fetch_credit_notes_paginated("purchases", start, end)

    # --- S3: BusinessPartners for every distinct purchase supplier in period ---
    supplier_codes = sorted({
        (d.get("CardCode") or "").strip()
        for d in (purchases + purch_cn)
        if (d.get("CardCode") or "").strip()
    })
    business_partners: dict[str, dict] = {}
    for code in supplier_codes:
        business_partners[code] = sap_server.sap.get(f"/BusinessPartners('{code}')")

    # --- S4: SI purchase lines (reduced 9-key; CN unflipped, exactly as returned) ---
    si_lines = fetch_si_purchase_lines(start, end)

    # --- S5: listing headers (period-scoped + company-wide), verbatim ---
    listing = fetch_listing_data(cfg, period)

    # --- S0: @odata.count per entity (+ record the @-prefix key) ---
    inline_counts = {
        "_note": (
            "v2 Service Layer returns the period record count under the "
            "'@odata.count' key (with @ prefix). orchestrator/steps.py reads "
            "'odata.count' (no @), so Gate 1 warn-passes unconditionally — "
            "operational-backlog item 5. Freezing both the values and the key "
            "name makes the future Gate-1 fix testable."
        ),
        "inlinecount_key": INLINECOUNT_KEY,
        "counts": {e: _inline_count(e, start, end) for e in ENTITIES},
    }

    # --- Write the eight surface fixtures (verbatim) ---
    surfaces = {
        "invoices.raw.json": ("_fetch_invoices_paginated(\"Invoices\")", invoices, len(invoices)),
        "purchase-invoices.raw.json": ("_fetch_invoices_paginated(\"PurchaseInvoices\")", purchases, len(purchases)),
        "credit-notes.raw.json": ("_fetch_credit_notes_paginated(\"sales\")", sales_cn, len(sales_cn)),
        "purchase-credit-notes.raw.json": ("_fetch_credit_notes_paginated(\"purchases\")", purch_cn, len(purch_cn)),
        "business-partners.raw.json": ("GET /BusinessPartners('{CardCode}') per supplier", business_partners, len(business_partners)),
        "si-purchase-lines.json": ("reasoning.sap_lines.fetch_si_purchase_lines", si_lines, len(si_lines)),
        "listing-headers.json": ("orchestrator.steps.fetch_listing_data", listing, None),
        "inline-counts.json": ("@odata.count probe per entity", inline_counts, None),
    }
    for fname, (_src, obj, _count) in surfaces.items():
        _write_pretty(OUT_DIR / fname, obj)

    # --- Same-session compiled replay oracle (read-only live chain run) ---
    compile_output, gate_results = run_chain(cfg, period)
    oracle = {"period": period, "compile_output": compile_output, "gate_results": gate_results}
    # canonical_json: sorted keys, sets->sorted lists, compact — the byte-stable
    # target the offline replay test asserts against.
    (OUT_DIR / "_replay-oracle.compiled.json").write_bytes(canonical_json(oracle))

    # --- Provenance sidecar (keeps the raw fixtures pure) ---
    manifest_fixtures: dict[str, dict] = {}
    for fname, (src, _obj, count) in surfaces.items():
        entry = {"source_function": src, "sha256": sha256_file(OUT_DIR / fname)}
        if count is not None:
            entry["record_count"] = count
        if fname == "listing-headers.json":
            entry["counts"] = {k: len(v) for k, v in listing.items()}
        if fname == "inline-counts.json":
            entry["counts"] = inline_counts["counts"]
        if fname == "business-partners.raw.json":
            entry["card_codes"] = supplier_codes
        manifest_fixtures[fname] = entry
    manifest_fixtures["_replay-oracle.compiled.json"] = {
        "source_function": "orchestrator.chain.run_chain (CompileOutput + gate_results)",
        "serialisation": "audit_bundle.canonical.canonical_json",
        "sha256": sha256_file(OUT_DIR / "_replay-oracle.compiled.json"),
    }

    manifest = {
        "_note": (
            "SBODEMOSG is SAP B1 demo/synthetic data — no PDPA constraint; fixtures "
            "are committable. Verbatim freeze of recon surfaces S0–S5 + same-session "
            "compiled replay oracle. Raw fixtures carry no injected provenance; all "
            "provenance lives here."
        ),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "instance": cfg.company_db,
        "service_layer_url": cfg.service_layer_url,
        "service_layer_version": "v2 (b1s/v2)",
        "client_id": CLIENT_ID,
        "period": period,
        "fixtures": manifest_fixtures,
    }
    with open(OUT_DIR / "capture-manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print("capture: wrote", len(surfaces) + 2, "files to", OUT_DIR)
    for fname, (_src, _obj, count) in surfaces.items():
        print(f"  {fname}: count={count}")
    print(f"  _replay-oracle.compiled.json: gate all_passed={gate_results.get('all_passed')}")
    print("capture: DONE (read-only; no SAP writes)")


if __name__ == "__main__":
    main()
