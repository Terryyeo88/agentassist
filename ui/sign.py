"""
ui/sign.py — the adjudication-panel Sign action: render the working-paper PDF.

On Sign, the reviewer's name is populated and the EXISTING report path is invoked
(report.report.build_report → report.render.render_pdf) to emit the signed working
paper. The ``show_ai_candidates`` gate is RESPECTED, not bypassed: it is read from the
client config (default False), so the AI-candidates subsection stays disabled in the
signed PDF while T2.11 remains the binding gate.

This module is a VIEW boundary: it renders from the frozen ReviewResult's compile_output
(BOX-ISOLATION — it never recomputes or mutates F5 boxes). Adjudication decisions/notes
attach to the dossier/proposal in the UI layer; they do not alter box values here.

No secrets: the demo ClientConfig is constructed directly from the committed client
YAML with EMPTY credential fields — load_client_config (which resolves env-var secrets
and may probe SAP) is intentionally not used.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from config.loader import ClientConfig
from report.render import render_pdf
from report.report import build_report

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLIENT_YAML = _REPO_ROOT / "config" / "clients" / "sbodemosg.yaml"
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "exploration-notes" / "t5.8-demo-reports"


def demo_client_config(
    *,
    reviewer_name: str,
    firm_name: str,
    client_yaml: Path | str = _CLIENT_YAML,
) -> ClientConfig:
    """Construct a hermetic demo ClientConfig from the client YAML + reviewer identity.

    Credentials are EMPTY (no secrets); SAP is never contacted on the Sign path.
    ``show_ai_candidates`` is taken from the YAML report block (default False) so the
    signed PDF respects the frozen gate.
    """
    raw = yaml.safe_load(Path(client_yaml).read_text(encoding="utf-8")) or {}
    sap = raw.get("sap_b1", {}) or {}
    report_block = raw.get("report", {}) or {}
    period_defaults = raw.get("period_defaults", {}) or {}

    return ClientConfig(
        client_id=str(raw.get("client_id", "sbodemosg")),
        client_name=str(raw.get("client_name", "")),
        gst_registration_number=str(raw.get("gst_registration_number", "") or ""),
        applicable_gst_rate=float(raw.get("applicable_gst_rate", 0.0)),
        service_layer_url=str(sap.get("service_layer_url", "")),
        company_db=str(sap.get("company_db", "")),
        username="",            # no secrets in the demo
        password="",            # no secrets in the demo
        ssl_verify=bool(sap.get("ssl_verify", False)),
        fiscal_year_start_month=int(period_defaults.get("fiscal_year_start_month", 1)),
        custom_vat_groups=dict(raw.get("custom_vat_groups", {}) or {}),
        completeness_threshold=float(raw.get("completeness_threshold", 0.10)),
        reviewer_name=str(reviewer_name or ""),
        firm_name=str(firm_name or ""),
        # Frozen gate: default False; only ever True if the YAML explicitly sets it
        # (it does not — T2.11 keeps it off). Read, not hard-coded, so the gate is
        # respected rather than bypassed.
        show_ai_candidates=bool(report_block.get("show_ai_candidates", False)),
    )


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "reviewer").strip()).strip("-").lower()
    return s or "reviewer"


def sign_working_paper(
    review_result: dict,
    *,
    reviewer_name: str,
    firm_name: str = "",
    out_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> Path:
    """Render the signed working-paper PDF from the frozen ReviewResult.

    Args:
        review_result: The frozen ReviewResult dict (MockEngine output).
        reviewer_name: Reviewer of record; populated onto the cover + signature.
                       Must be non-empty (the panel enforces this before calling).
        firm_name:     Reviewer's firm (optional).
        out_dir:       Destination directory for the PDF.

    Returns:
        Path to the written working-paper PDF.

    Raises:
        ValueError: if reviewer_name is empty or the review halted (no compile_output).
    """
    if not reviewer_name or not reviewer_name.strip():
        raise ValueError("Sign requires a non-empty reviewer name.")

    compile_output = review_result.get("compile_output")
    if not compile_output:
        raise ValueError("Cannot sign a halted/empty review (no compile_output).")

    cfg = demo_client_config(reviewer_name=reviewer_name, firm_name=firm_name)
    generated_at = compile_output["fetch_manifest"]["fetched_at"]

    model = build_report(
        compile_output,
        cfg,
        generated_at=generated_at,
        judgment_artefact=review_result.get("reasoning_artefact"),
        document_candidates=review_result.get("document_candidates"),
        analytical_review_data=review_result.get("analytical_review_data"),
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(out_dir)
    out_path = out_dir / f"working-paper-{cfg.client_id}-{_slug(reviewer_name)}-{ts}.pdf"
    return render_pdf(model, out_path)
