"""ui/views/executor.py — executor dispatch log (fires only after human approval)."""
from __future__ import annotations

import streamlit as st

from ui.artifacts import DemoArtifacts, executor_dispatch_rows


def render(artifacts: DemoArtifacts) -> None:
    st.subheader("Executor dispatch log")
    st.caption(
        "What the deterministic executor fired — and it fires ONLY after a human "
        "approves a proposal. In a fresh mock run nothing has been approved, so the "
        "log is empty until you Sign a working paper in the adjudication panel."
    )

    session_dispatches = st.session_state.get("dispatches", [])
    rows = executor_dispatch_rows(artifacts.ledger, session_dispatches)

    if not rows:
        st.info(
            "No executor dispatches yet. All proposals are PENDING — sealing/emitting "
            "happens only after human approval (the agent never executes Tier-2)."
        )
        return

    st.dataframe(
        [
            {
                "Action": r["action"],
                "Outcome": r["outcome"],
                "Justification": r["justification"],
                "Timestamp": r.get("timestamp", ""),
                "Source": r["source"],
            }
            for r in rows
        ],
        use_container_width=True,
        hide_index=True,
    )
