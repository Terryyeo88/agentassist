"""
agent/eval/scenario.py — Scenario format + fixture loaders for the eval harness.

A *scenario* models one scripted agent run against the cage:

    attempts            — ordered agent tool-call attempts, each an
                          {tool_name, tool_input, justification?}. These are fed
                          through the REAL PreToolUse/PostToolUse hooks.
    approved_executions — optional human-approved Tier-2 executions (seal/emit).
                          These are NOT agent attempts; they model the
                          deterministic executor firing AFTER human approval, used
                          to exercise sealed-chain routing integrity. The agent can
                          never reach these — only the approval path can.

Scenarios are plain data and can be authored as Python fixtures or loaded from
JSON. Zero SDK import. Stdlib only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union


@dataclass
class Attempt:
    """One scripted agent tool-call attempt.

    Attributes:
        tool_name:     The tool the agent attempts to call (bare or MCP-namespaced).
        tool_input:    The tool input dict (never mutated by the harness).
        justification: Convenience field merged into tool_input["justification"]
                       at replay time — UNLESS tool_input already carries an
                       explicit justification, which always wins.
        note:          Optional human-readable note for the scorecard.
    """
    tool_name: str
    tool_input: dict = field(default_factory=dict)
    justification: Optional[str] = None
    note: str = ""

    def merged_input(self) -> dict:
        """Return a fresh input dict with the justification convenience applied.

        An explicit tool_input["justification"] is preserved as-is; otherwise the
        ``justification`` field (when set) is merged in. The original tool_input is
        never mutated.
        """
        merged = dict(self.tool_input)
        if self.justification is not None and "justification" not in merged:
            merged["justification"] = self.justification
        return merged


@dataclass
class Tier2Execution:
    """A human-approved Tier-2 execution (NOT an agent attempt).

    Models the deterministic executor firing after a human approves a
    ProposalArtifact. Used by the harness to exercise sealed-chain routing: a
    Tier-2 outcome must land in the SEALED ledger, never the unsealed audit_log.

    Attributes:
        action:        Executor action ("seal_bundle" | "emit_final_pdf").
        justification: The approved proposal's justification.
        evidence_refs: Non-empty evidence pointers for the proposal.
        inputs:        Inputs dict the proposal is anchored to (hashed).
        note:          Optional human-readable note for the scorecard.
    """
    action: str
    justification: str
    evidence_refs: list = field(default_factory=list)
    inputs: dict = field(default_factory=dict)
    note: str = ""


@dataclass
class Scenario:
    """An ordered scripted run: agent attempts + optional approved executions."""
    name: str
    description: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    approved_executions: list[Tier2Execution] = field(default_factory=list)


def _build_attempt(spec: dict[str, Any]) -> Attempt:
    return Attempt(
        tool_name=spec["tool_name"],
        tool_input=dict(spec.get("tool_input") or {}),
        justification=spec.get("justification"),
        note=spec.get("note", ""),
    )


def _build_execution(spec: dict[str, Any]) -> Tier2Execution:
    return Tier2Execution(
        action=spec["action"],
        justification=spec["justification"],
        evidence_refs=list(spec.get("evidence_refs") or []),
        inputs=dict(spec.get("inputs") or {}),
        note=spec.get("note", ""),
    )


def load_scenario(spec: dict[str, Any]) -> Scenario:
    """Build a Scenario from a plain dict (e.g. parsed JSON).

    Required: ``name``. Optional: ``description``, ``attempts`` (list of attempt
    dicts), ``approved_executions`` (list of execution dicts).
    """
    return Scenario(
        name=spec["name"],
        description=spec.get("description", ""),
        attempts=[_build_attempt(a) for a in spec.get("attempts", [])],
        approved_executions=[
            _build_execution(e) for e in spec.get("approved_executions", [])
        ],
    )


def load_scenarios_from_json(path: Union[str, Path]) -> list[Scenario]:
    """Load a list of scenarios from a JSON file.

    The file must contain a JSON array of scenario objects (the same shape
    ``load_scenario`` accepts).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("scenario JSON file must contain a top-level array")
    return [load_scenario(item) for item in data]
