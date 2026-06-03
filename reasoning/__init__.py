"""reasoning — AI-assisted review passes for AgentAssist.

This package runs BESIDE the deterministic audit chain (orchestrator/).
Dependency invariant: neither this package nor orchestrator/ imports the other.
run_agent.py is the sole coordinator of both.

All outputs are phrased as candidates for human review ("Consider reviewing
whether…"); no pass ever asserts a compliance conclusion.  Every pass emits
a well-formed artefact even on error.  No secrets appear in any artefact.
"""
