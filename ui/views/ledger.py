"""ui/views/ledger.py — justification-ledger timeline (read-only)."""
from __future__ import annotations

import streamlit as st

from ui.artifacts import DemoArtifacts, ledger_timeline_rows


def render(artifacts: DemoArtifacts) -> None:
    st.subheader("Justification ledger — hash-chained timeline")
    st.caption(
        "Read-only view of the append-only, hash-chained justification ledger. "
        "Tier-0 reads and Tier-1 staging justifications appear in chain order; the UI "
        "never reorders or mutates entries."
    )

    rows = ledger_timeline_rows(artifacts.ledger)
    if not rows:
        st.info("No ledger entries in the frozen demo artifacts.")
        return

    counts = {}
    for r in rows:
        counts[r["tier_label"]] = counts.get(r["tier_label"], 0) + 1
    cols = st.columns(len(counts) or 1)
    for col, (label, n) in zip(cols, sorted(counts.items())):
        col.metric(label, n)

    st.dataframe(
        [
            {
                "#": r["seq"],
                "Tier": r["tier_label"],
                "Tool": r["tool_name"],
                "Outcome": r["outcome"],
                "Justification": r["justification"],
                "Timestamp": r["timestamp"],
                "Entry hash": r["entry_hash"],
            }
            for r in rows
        ],
        use_container_width=True,
        hide_index=True,
    )
