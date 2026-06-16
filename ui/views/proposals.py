"""ui/views/proposals.py — PENDING proposals queue (awaiting human approval)."""
from __future__ import annotations

import streamlit as st

from ui.artifacts import DemoArtifacts, pending_proposal_rows


def render(artifacts: DemoArtifacts) -> None:
    st.subheader("PENDING proposals — awaiting human approval")
    st.caption(
        "Tier-2 ProposalArtifacts staged by the case-file loop. Each is PENDING: the "
        "deterministic executor fires ONLY after a human approves. The agent never "
        "executes a Tier-2 action itself."
    )

    rows = pending_proposal_rows(artifacts.proposals)
    pending = [r for r in rows if r["status"] == "pending"]
    st.metric("Pending proposals", len(pending))

    if not rows:
        st.info("No proposals in the frozen demo artifacts.")
        return

    for r in rows:
        with st.expander(f"{r['action']} · {r['status'].upper()} · {r['proposal_id'][:8]}…"):
            st.write(f"**Action:** `{r['action']}`  ·  **Tier:** {r['tier']}  ·  **Status:** {r['status']}")
            st.write(f"**Justification:** {r['justification']}")
            st.write("**Evidence refs:**")
            st.write(r["evidence_refs"] or "—")
            st.caption(f"inputs_hash: {r['inputs_hash']}  ·  created_at: {r['created_at']}")
