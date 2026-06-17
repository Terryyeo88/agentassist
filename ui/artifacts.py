"""
ui/artifacts.py — load frozen demo artifacts + build pure view-models.

All functions here are PURE: they read the frozen JSON artifacts and shape them into
plain dicts/lists for the Streamlit views. No Streamlit import, no engine call, no
case-file loop — so the view-model logic is unit-testable headlessly and the UI stays
a view over frozen data.

Frozen invariants surfaced here (never overridden):
  * VALIDATION_STATUS = "unvalidated"  (T2.11 is the binding gate)
  * candidate framing only — copy is shaped as "candidate for review", never a verdict.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.decision_ledger import (
    DecisionLedger,
    annotate_and_demote,
    compute_finding_fingerprint,
)
from ui.engine_seam import DEMO_ARTIFACTS_DIR

# Frozen customer-facing gate state — surfaced as a badge, never flipped by the UI.
VALIDATION_STATUS: str = "unvalidated"

# Human-readable tier labels for the ledger timeline.
_TIER_LABELS: dict[int, str] = {
    0: "Tier 0 · observe (read-only)",
    1: "Tier 1 · work in staging",
    2: "Tier 2 · executed (post-approval)",
    3: "Tier 3 · structurally absent",
}


@dataclass
class DemoArtifacts:
    """The frozen artifact surfaces the UI renders.

    ``decision_ledger`` holds the seeded prior-period reviewer adjudications (T5.5b);
    it is empty when no decision-ledger fixture is present.
    """
    review_result: dict
    dossiers: list[dict]
    proposals: list[dict]
    ledger: list[dict]
    decision_ledger: list[dict] = field(default_factory=list)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_demo_artifacts(artifacts_dir: Path | str = DEMO_ARTIFACTS_DIR) -> DemoArtifacts:
    """Load the frozen review_result / dossiers / proposals / ledger / decision-ledger JSONs."""
    d = Path(artifacts_dir)
    return DemoArtifacts(
        review_result=_read_json(d / "review_result.json", {}),
        dossiers=_read_json(d / "dossiers.json", []),
        proposals=_read_json(d / "proposals.json", []),
        ledger=_read_json(d / "ledger.json", []),
        decision_ledger=_read_json(d / "decision-ledger.json", []),
    )


def tier_label(tier: int) -> str:
    """Return a human-readable label for a ledger entry tier."""
    return _TIER_LABELS.get(int(tier), f"Tier {tier}")


def _short_hash(h: str | None) -> str:
    if not h:
        return "—"
    body = h.split(":", 1)[-1]
    return f"{body[:10]}…" if len(body) > 10 else body


def ledger_timeline_rows(ledger: list[dict]) -> list[dict]:
    """Shape the hash-chained ledger into display rows (read-only view).

    The chain order is preservation order — entries are never reordered here.
    """
    rows: list[dict] = []
    for i, e in enumerate(ledger):
        rows.append({
            "seq": i,
            "tier": int(e.get("tier", 3)),
            "tier_label": tier_label(e.get("tier", 3)),
            "tool_name": e.get("tool_name", "—"),
            "outcome": e.get("outcome", "—"),
            "justification": e.get("justification") or "—",
            "blocked_reason": e.get("blocked_reason") or "",
            "timestamp": e.get("timestamp", ""),
            "entry_hash": _short_hash(e.get("entry_hash")),
        })
    return rows


def pending_proposal_rows(proposals: list[dict]) -> list[dict]:
    """Shape PENDING proposals into display rows. Only ``pending`` are awaiting approval."""
    rows: list[dict] = []
    for p in proposals:
        rows.append({
            "proposal_id": p.get("proposal_id", "—"),
            "action": p.get("action", "—"),
            "tier": int(p.get("tier", 2)),
            "status": p.get("status", "—"),
            "justification": p.get("justification") or "—",
            "evidence_refs": list(p.get("evidence_refs") or []),
            "inputs_hash": p.get("inputs_hash", "—"),
            "created_at": p.get("created_at", ""),
        })
    return rows


def executor_dispatch_rows(ledger: list[dict], session_dispatches: list[dict] | None = None) -> list[dict]:
    """Return executor dispatch records: Tier-2 ``executed`` ledger entries + any
    in-session dispatches recorded by the Sign action.

    In a fresh mock run this is EMPTY — the deterministic executor fires ONLY after a
    human approves a proposal, and nothing has been approved/executed yet.
    """
    rows: list[dict] = []
    for e in ledger:
        if int(e.get("tier", 3)) == 2 and e.get("outcome") == "executed":
            rows.append({
                "action": e.get("tool_name", "—"),
                "outcome": e.get("outcome", "—"),
                "justification": e.get("justification") or "—",
                "timestamp": e.get("timestamp", ""),
                "source": "sealed-ledger",
            })
    for d in (session_dispatches or []):
        rows.append({**d, "source": d.get("source", "session")})
    return rows


def dossier_view(dossier: dict) -> dict:
    """Shape one dossier into the adjudication-panel view-model.

    Carries the Tier-0 evidence map, the candidate framing text (candidate-framed by
    construction), the CODE-DEFINED completeness block, and the frozen
    ``validation_status`` badge. NOTHING here asserts a verdict.
    """
    completeness = dossier.get("completeness") or {}
    return {
        "finding_id": dossier.get("finding_id", "—"),
        "check_id": dossier.get("check_id", "—"),
        "finding_type": dossier.get("finding_type", "—"),
        "candidate_framing_text": dossier.get("candidate_framing_text", ""),
        "evidence": dossier.get("evidence") or {},
        "completeness": {
            "required": list(completeness.get("required") or []),
            "present": list(completeness.get("present") or []),
            "missing": list(completeness.get("missing") or []),
            "satisfied": bool(completeness.get("satisfied", False)),
        },
        "inputs_hash": dossier.get("inputs_hash", "—"),
        "validation_status": VALIDATION_STATUS,
    }


def adjudication_items(artifacts: DemoArtifacts) -> list[dict]:
    """Join dossiers with their staging proposals (shared inputs_hash) for the panel.

    Each item is one per-finding case file: the dossier view plus the PENDING proposal
    that stages it. The proposal is matched by inputs_hash (dossier ⇄ proposal anchor).
    """
    by_hash: dict[str, dict] = {p.get("inputs_hash"): p for p in artifacts.proposals}
    items: list[dict] = []
    for d in artifacts.dossiers:
        view = dossier_view(d)
        view["finding_id"] = d.get("finding_id", "—")
        view["finding_type"] = d.get("finding_type", "—")
        proposal = by_hash.get(d.get("inputs_hash"))
        view["proposal_id"] = proposal.get("proposal_id") if proposal else None
        view["proposal_status"] = proposal.get("status") if proposal else None
        items.append(view)
    return items


def _detect_issues_by_finding_id(review_result: dict) -> dict[str, dict]:
    """Map ``detect:{error_code}:{doc_num}`` -> the detect-issue payload.

    The frozen dossier carries no ``card_name``; the counterparty the decision-ledger
    fingerprint keys on lives only on the compile_output detect-issue. We re-join the two
    by the dossier's finding_id (mirrors agent.dossier's finding_id construction).
    """
    issues = (
        ((review_result or {}).get("compile_output") or {}).get("detect") or {}
    ).get("issues") or []
    out: dict[str, dict] = {}
    for issue in issues:
        code = str(issue.get("error_code", "UNKNOWN"))
        out[f"detect:{code}:{issue.get('doc_num')}"] = issue
    return out


def annotated_adjudication_items(
    artifacts: DemoArtifacts,
    decision_ledger: DecisionLedger | None = None,
) -> list[dict]:
    """The adjudication panel items decorated with decision-ledger memory (T5.5b).

    A PURE view-model READ: runs ``annotate_and_demote`` over the panel's DETERMINISTIC
    findings (re-keyed to their counterparty-bearing detect-issue payloads) and attaches
    ``demoted`` / ``annotation`` / ``fingerprint`` / ``prior_dispositions`` to each item.

    Invariant 5 (never suppress) is STRUCTURAL here: cardinality is preserved — every
    dossier still yields exactly one item; demoted items are merely ordered AFTER
    non-demoted ones (stable). The decision ledger applies to deterministic findings
    only; probabilistic candidates pass through unannotated. Neither the dossiers nor the
    review_result (F5 boxes) are mutated.
    """
    items = adjudication_items(artifacts)
    if decision_ledger is None:
        decision_ledger = DecisionLedger.from_entries(artifacts.decision_ledger or [])

    issues_by_fid = _detect_issues_by_finding_id(artifacts.review_result)

    # Deterministic items we can fingerprint (joined to a detect-issue), in panel order.
    det_positions = [
        i for i, it in enumerate(items)
        if it.get("finding_type") == "deterministic" and it.get("finding_id") in issues_by_fid
    ]
    findings = [issues_by_fid[items[i]["finding_id"]] for i in det_positions]
    annotated = annotate_and_demote(findings, decision_ledger)

    # Default passthrough (probabilistic / unjoinable items): present, never demoted.
    for it in items:
        it["fingerprint"] = None
        it["demoted"] = False
        it["annotation"] = None
        it["prior_dispositions"] = ()

    for pos, i in enumerate(det_positions):
        af = annotated[pos]
        items[i]["fingerprint"] = af.fingerprint
        items[i]["demoted"] = af.demoted
        items[i]["annotation"] = af.annotation
        items[i]["prior_dispositions"] = af.prior_dispositions

    # Demote-to-bottom: stable sort keeps original order within each group. Cardinality
    # is unchanged — demotion lowers prominence, it never drops a finding.
    return sorted(items, key=lambda it: it["demoted"])
