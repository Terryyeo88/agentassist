"""provenance.py — gather chain-run provenance metadata for manifest.json."""

from __future__ import annotations

import subprocess
from pathlib import Path

from audit_bundle.canonical import sha256_file

# audit_bundle/ is at <repo>/audit_bundle/; parent.parent = repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _git_short_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        sha = result.stdout.strip()
        return sha if sha else "unknown"
    except Exception:
        return "unknown"


def gather_provenance(expected_rate: float) -> dict:
    """Return the provenance block for manifest.json.

    llm_in_run_path is False for the T1.6 chain: no LLM inference sits on
    the arithmetic path.  model_id is None accordingly.
    """
    return {
        "llm_in_run_path": False,
        "model_id": None,
        "repo_commit": _git_short_sha(),
        "chain_version": "t1.6",
        "report_template_version": "t1.4",
        "system_prompt_hash": sha256_file(_REPO_ROOT / "system-prompts" / "base.md"),
        "kb_slice_hash": sha256_file(_REPO_ROOT / "knowledge-base" / "sg-tax-code-mappings.md"),
        "expected_rate": expected_rate,
        "rederivation_grade": "same-SAP-state",
    }
