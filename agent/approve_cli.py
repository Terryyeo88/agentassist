"""
agent/approve_cli.py — CLI and library functions for the Tier-2 approval workflow.

Public library API (used directly by tests and T5.3):
    list_pending(store)                       -> list[dict]
    show_proposal(store, proposal_id)         -> dict | None
    approve_proposal(store, executor, id)     -> dict
    reject_proposal(store, id)                -> dict

CLI usage (python -m agent.approve_cli):
    list                    — list all pending proposals
    show <id>               — show one proposal by id
    approve <id>            — approve and execute (test_noop or registered handler)
    reject <id>             — reject without executing

All functions are thin wrappers over agent.proposals.StagingStore and
agent.executor.Executor.  No SDK import.  No live model.  No network.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from agent.executor import Executor, ExecutorError
from agent.proposals import StagingStore


# ---------------------------------------------------------------------------
# Library functions — used by tests and T5.3 agent loop
# ---------------------------------------------------------------------------

def list_pending(store: StagingStore) -> list[dict[str, Any]]:
    """Return all pending proposals as plain dicts (status='pending')."""
    return [asdict(a) for a in store.list_pending()]


def show_proposal(store: StagingStore, proposal_id: str) -> dict[str, Any] | None:
    """Return one proposal as a plain dict, or None if not found."""
    artifact = store.get(proposal_id)
    if artifact is None:
        return None
    return asdict(artifact)


def approve_proposal(
    store: StagingStore,
    executor: Executor,
    proposal_id: str,
) -> dict[str, Any]:
    """Approve a proposal and dispatch it to the executor.

    Returns a dict with the approved artifact fields plus an 'execution' sub-dict
    from the ExecutionResult.

    Raises:
        KeyError:       If proposal_id is not found in the store.
        ExecutorError:  If the executor cannot dispatch (wrong status, no handler).
        NotImplementedError: Propagated from deferred T5.3 handlers (seal_bundle,
                             emit_final_pdf).
    """
    artifact = store.approve(proposal_id)
    result = executor.execute(proposal_id)
    d = asdict(artifact)
    d["execution"] = {
        "proposal_id": result.proposal_id,
        "action": result.action,
        "success": result.success,
        "detail": result.detail,
    }
    return d


def reject_proposal(store: StagingStore, proposal_id: str) -> dict[str, Any]:
    """Reject a proposal.  Returns the updated artifact as a plain dict.

    Raises:
        KeyError: If proposal_id is not found in the store.
    """
    artifact = store.reject(proposal_id)
    return asdict(artifact)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent.approve_cli",
        description="Tier-2 proposal approval CLI (AgentAssist T5.2b).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all pending proposals.")

    show_p = sub.add_parser("show", help="Show a proposal by ID.")
    show_p.add_argument("proposal_id", help="UUID of the proposal.")

    approve_p = sub.add_parser("approve", help="Approve and execute a proposal.")
    approve_p.add_argument("proposal_id", help="UUID of the proposal.")

    reject_p = sub.add_parser("reject", help="Reject a proposal.")
    reject_p.add_argument("proposal_id", help="UUID of the proposal.")

    return p


def _run_cli(store: StagingStore, executor: Executor, args: list[str] | None = None) -> int:
    """Run the CLI with the given store/executor; return exit code."""
    parsed = _build_parser().parse_args(args)

    if parsed.command == "list":
        pending = list_pending(store)
        if not pending:
            print("No pending proposals.")
        for item in pending:
            print(f"  {item['proposal_id']}  action={item['action']}  created={item['created_at']}")
        return 0

    if parsed.command == "show":
        item = show_proposal(store, parsed.proposal_id)
        if item is None:
            print(f"Not found: {parsed.proposal_id}", file=sys.stderr)
            return 1
        print(json.dumps(item, indent=2))
        return 0

    if parsed.command == "approve":
        try:
            result = approve_proposal(store, executor, parsed.proposal_id)
            print(f"Approved and executed: action={result['action']}")
            print(f"  detail: {result['execution']['detail']}")
            return 0
        except KeyError:
            print(f"Not found: {parsed.proposal_id}", file=sys.stderr)
            return 1
        except (ExecutorError, NotImplementedError) as exc:
            print(f"Execution failed: {exc}", file=sys.stderr)
            return 1

    if parsed.command == "reject":
        try:
            result = reject_proposal(store, parsed.proposal_id)
            print(f"Rejected: {result['proposal_id']}")
            return 0
        except KeyError:
            print(f"Not found: {parsed.proposal_id}", file=sys.stderr)
            return 1

    return 1  # unreachable — argparse enforces required subcommand


if __name__ == "__main__":
    # Module-level singletons for live CLI use.
    # Tests inject their own store/executor directly via the library functions.
    _store = StagingStore()
    _executor = Executor(_store)
    sys.exit(_run_cli(_store, _executor))
