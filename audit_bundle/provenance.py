"""provenance.py — gather chain-run provenance metadata for manifest.json.

Builds the "provenance" block that is embedded in every sealed bundle's
manifest.json.  The block records everything needed to understand the
conditions under which a run was produced and whether the results could
be re-derived:

    - Which version of the code ran (repo_commit, chain_version).
    - Whether any LLM sat on the arithmetic path (llm_in_run_path).
    - Hashes of the exact system prompt and knowledge-base slice in effect,
      so any post-run edit to those files is detectable.
    - The expected GST rate used for all classification and detection checks.
    - A rederivation_grade indicating the conditions required to reproduce
      the same output.

rederivation_grade "same-SAP-state" means: re-running the chain against
the same SAP database at the same data state will produce an identical
CompileOutput.  This is the strongest reproducibility guarantee available
for a live-database audit tool.

Public API:
    gather_provenance(expected_rate) -> dict

Dependencies:
    subprocess              Git short-SHA probe (stdlib).
    audit_bundle.canonical  sha256_file — hashes system prompt and KB slice.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from audit_bundle.canonical import sha256_file

# audit_bundle/ is at <repo>/audit_bundle/; parent.parent = repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _git_short_sha() -> str:
    """Return the short HEAD commit SHA of the current git repository.

    Used to record which exact code revision produced a bundle, so a reviewer
    can check out that commit and verify the chain logic that was in effect.

    Returns:
        str: 7–12 character abbreviated commit SHA (e.g. "a1b2c3d"), or
             "unknown" if git is unavailable, the command times out, or the
             working directory is not inside a git repository.  Returning
             "unknown" rather than raising ensures a git failure never aborts
             the seal operation.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,   # stdout/stderr captured as strings, not printed
            text=True,
            # 5-second ceiling prevents the seal from hanging if git is slow
            # or unavailable (e.g. in a containerised environment without git).
            timeout=5,
        )
        sha = result.stdout.strip()
        # git may succeed (exit 0) but produce empty stdout in edge cases such
        # as a brand-new repository with no commits yet.
        return sha if sha else "unknown"
    except Exception:
        # Broad catch is intentional: OSError (git not installed), TimeoutExpired,
        # and any other failure all fall back to "unknown" rather than crashing seal.
        return "unknown"


def gather_provenance(expected_rate: float) -> dict:
    """Return the provenance block for manifest.json.

    llm_in_run_path is False for the T1.6 chain: no LLM inference sits on
    the arithmetic path.  model_id is None accordingly.

    Hashes the system prompt and knowledge-base slice at call time so the
    bundle records exactly which inputs were in effect.  If either file is
    edited after sealing, the stored hash will no longer match the file on
    disk, making the change detectable during verification.

    Args:
        expected_rate: The GST rate (as a decimal fraction, e.g. 0.09) that
                       was passed to the classify and detect steps.  Recorded
                       here so a reviewer can confirm the correct rate was
                       applied without re-reading the client config.

    Returns:
        dict: Provenance block with the following keys:
            - "llm_in_run_path" (bool):   False for the deterministic chain.
            - "model_id" (None):          None when no LLM is in the run path.
            - "repo_commit" (str):        Short HEAD SHA or "unknown".
            - "chain_version" (str):      Milestone label for this chain build.
            - "report_template_version" (str): Milestone label for the PDF template.
            - "system_prompt_hash" (str): "sha256:<hex>" of system-prompts/base.md.
            - "kb_slice_hash" (str):      "sha256:<hex>" of the active KB slice.
            - "expected_rate" (float):    GST rate used during this run.
            - "rederivation_grade" (str): Reproducibility classification;
                                         "same-SAP-state" means re-running the
                                         chain against the same SAP data state
                                         produces an identical CompileOutput.
    """
    return {
        "llm_in_run_path": False,
        "model_id": None,
        "repo_commit": _git_short_sha(),
        "chain_version": "t1.6",
        "report_template_version": "t1.4",
        # Hash the system prompt so any edit after sealing is detectable during
        # bundle verification — the stored hash will diverge from the file on disk.
        "system_prompt_hash": sha256_file(_REPO_ROOT / "system-prompts" / "base.md"),
        # Hash the active knowledge-base slice for the same reason — the KB drives
        # VatGroup classification rules and must be pinned to a specific revision.
        "kb_slice_hash": sha256_file(_REPO_ROOT / "knowledge-base" / "sg-tax-code-mappings.md"),
        "expected_rate": expected_rate,
        "rederivation_grade": "same-SAP-state",
    }
