"""
agent/dossier.py — DossierArtifact schema + finding extraction for the case-file loop.

T5.3 Slice 2 (behavior). A DossierArtifact is the per-finding case file the agent
assembles during the gather step: the deterministic finding, the Tier-0 evidence
gathered around it, the agent's candidate framing text, and a CODE-DEFINED
completeness block. It is the agent-layer contribution that, post human approval, is
sealed into the FINAL reviewed bundle alongside the engine's deterministic bundle.

``extract_findings`` flattens a ReviewResult (object or serialised dict) into a
uniform list of ``Finding`` records across the three finding surfaces:
  * compile_output.detect.issues   — deterministic (E1-E4 / NO_GST_REG / COMPLETENESS)
  * document_candidates            — probabilistic (PDF cross-reference checks)
  * reasoning_artefact.candidates  — probabilistic (Reg 26/27 judgement candidates)

The dossier's ``inputs_hash`` is anchored through ``agent.proposals.compute_inputs_hash``
— the SAME primitive ``build_proposal`` uses — so a dossier and the proposal that
stages it share one hash (dossier ⇄ proposal ⇄ run state).

Every read PDF is UNTRUSTED input: the evidence map records what was read; it confers
no trust. Completeness is structural (see agent/completeness.py), never the model's
self-assessment.

Zero anthropic import. Zero SDK import. Stdlib only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from agent.proposals import compute_inputs_hash


@dataclass(frozen=True)
class Finding:
    """One normalised finding extracted from a ReviewResult.

    Attributes:
        finding_id:   Stable id derived from source + key fields (unique per run).
        check_id:     CheckSpec id (e.g. "NO_GST_REG", "gst_amount_mismatch"). For
                      reasoning candidates this is the artefact check name, which may
                      not be a registered CheckSpec (the loop skips findings without
                      a registered completeness checklist).
        finding_type: "deterministic" or "probabilistic".
        source:       Origin marker (e.g. "compile_output.detect").
        payload:      The raw finding dict as emitted by the engine.
    """
    finding_id: str
    check_id: str
    finding_type: str
    source: str
    payload: dict


@dataclass
class DossierArtifact:
    """Per-finding case file assembled by the agent during gather.

    Attributes:
        finding_id:             Id of the finding this dossier covers.
        check_id:               CheckSpec id of the finding.
        finding_type:           "deterministic" or "probabilistic".
        evidence:               Evidence map (slot name -> evidence value). Slots are
                                seeded from the engine finding and/or gathered via
                                Tier-0 reads. All read PDFs are UNTRUSTED input.
        candidate_framing_text: The agent's candidate framing for a human reviewer.
                                Passed through agent.lint.lint_framing before staging.
        completeness:           CODE-DEFINED completeness block
                                {check_id/required/present/missing/satisfied}.
        inputs_hash:            sha256 anchoring over dossier_inputs(...) via
                                compute_inputs_hash — shared with the staging proposal.
    """
    finding_id: str
    check_id: str
    finding_type: str
    evidence: dict
    candidate_framing_text: str
    completeness: dict
    inputs_hash: str = field(default="")


def _as_dict(obj: Any) -> dict:
    """Return a plain dict for a finding item (dataclass or dict)."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return dict(obj)


def _get(result: Any, name: str) -> Any:
    """Read *name* from a ReviewResult object or a serialised dict, tolerating None."""
    if result is None:
        return None
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def extract_findings(result: Any) -> list[Finding]:
    """Flatten a ReviewResult (object or serialised dict) into a uniform finding list.

    A halted review (compile_output/document_candidates/reasoning_artefact all None)
    yields an empty list — there is nothing for the agent layer to dossier.
    """
    findings: list[Finding] = []

    compile_output = _get(result, "compile_output") or {}
    detect_issues = (compile_output.get("detect") or {}).get("issues") or []
    for issue in detect_issues:
        issue = _as_dict(issue)
        code = str(issue.get("error_code", "UNKNOWN"))
        findings.append(Finding(
            finding_id=f"detect:{code}:{issue.get('doc_num')}",
            check_id=code,
            finding_type="deterministic",
            source="compile_output.detect",
            payload=issue,
        ))

    for cand in (_get(result, "document_candidates") or []):
        cand = _as_dict(cand)
        findings.append(Finding(
            finding_id=f"doc:{cand.get('check_id')}:{cand.get('doc_num')}",
            check_id=str(cand.get("check_id", "UNKNOWN")),
            finding_type="probabilistic",
            source="document_candidates",
            payload=cand,
        ))

    reasoning = _get(result, "reasoning_artefact") or {}
    for cand in (reasoning.get("candidates") or []):
        cand = _as_dict(cand)
        findings.append(Finding(
            finding_id=f"reg2627:{cand.get('doc_num')}:{cand.get('line_index', 0)}",
            check_id=str(reasoning.get("check", "reg-26-27-disallowed-input-tax")),
            finding_type="probabilistic",
            source="reasoning_artefact",
            payload=cand,
        ))

    return findings


def dossier_inputs(
    finding: Finding,
    evidence: dict,
    candidate_framing_text: str,
    completeness: dict,
) -> dict:
    """Build the canonical inputs dict that anchors a dossier (and its proposal).

    Anchored over the finding identity, the gathered evidence, the framing text, and
    the completeness block — the full agent-layer state for this finding at stage time.
    """
    return {
        "finding_id": finding.finding_id,
        "check_id": finding.check_id,
        "finding_type": finding.finding_type,
        "source": finding.source,
        "evidence": evidence,
        "candidate_framing_text": candidate_framing_text,
        "completeness": completeness,
    }


def build_dossier(
    finding: Finding,
    evidence: dict,
    candidate_framing_text: str,
    completeness: dict,
) -> DossierArtifact:
    """Assemble a DossierArtifact with an inputs_hash anchored via compute_inputs_hash."""
    inputs = dossier_inputs(finding, evidence, candidate_framing_text, completeness)
    return DossierArtifact(
        finding_id=finding.finding_id,
        check_id=finding.check_id,
        finding_type=finding.finding_type,
        evidence=evidence,
        candidate_framing_text=candidate_framing_text,
        completeness=completeness,
        inputs_hash=compute_inputs_hash(inputs),
    )
