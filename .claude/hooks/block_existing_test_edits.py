#!/usr/bin/env python3
"""Append-only-test guard (PreToolUse hook).

Blocks any Edit/Write on a file that ALREADY EXISTS under tests/, so no agent can
weaken a test to make the suite go green. NEW files (e.g. a fresh test_*.py) pass
through untouched — Write on a path that does not yet exist is allowed; Edit always
targets an existing file, so any Edit under tests/ is blocked.

Backstop: CI re-runs the full suite on the PR, so a test deleted out-of-band (e.g.
`rm` via Bash, which this hook does not see) is still caught there.

Contract: reads the PreToolUse JSON payload on stdin, emits a permission decision on
stdout. Deny == block. Anything else (no file_path, not under tests/, file absent) ==
allow by staying silent (exit 0, no output).
"""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed payload: do not block, let the harness handle it

    tool_input = payload.get("tool_input", {}) or {}
    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw_path:
        return 0  # tool has no file target (e.g. a Bash read) — nothing to guard

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    target = Path(raw_path)
    if not target.is_absolute():
        target = Path(project_dir) / target
    target = target.resolve()

    try:
        rel = target.relative_to(Path(project_dir).resolve())
    except ValueError:
        return 0  # outside the project: not our concern

    under_tests = len(rel.parts) >= 1 and rel.parts[0] == "tests"
    if not under_tests:
        return 0  # not a test file — allow

    if not target.exists():
        return 0  # NEW test file — allow creation (append-only is the whole point)

    # Existing file under tests/ being edited or overwritten — block it.
    decision = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Append-only-test guard: '{rel.as_posix()}' already exists under tests/. "
                "Agents may CREATE new test files but must never modify or delete an existing "
                "one (no weakening a test to go green). If the test is genuinely wrong, FLAG it "
                "for the human instead of editing it. CI re-runs the suite as the backstop."
            ),
        }
    }
    print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    sys.exit(main())
