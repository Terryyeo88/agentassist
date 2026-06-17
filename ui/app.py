"""
ui/app.py — T5.8 demo showcase Streamlit entry point.

Task-oriented navigation over the MockEngine / RealEngine seam. The PRIMARY (default)
surface is the reviewer Review queue (T5.8d); the original four system views are kept
under a secondary "Audit trail / developer" group. NOT an intent router — fixed nav.
Default engine is Mock, loading FROZEN deterministic artifacts; no live SAP, no live
model, no tokens.

Run:
    streamlit run ui/app.py
    AGENT_UI_ENGINE=mock streamlit run ui/app.py   # explicit (default)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `streamlit run ui/app.py` work from a fresh checkout. Streamlit puts the
# entrypoint's own directory (ui/) on sys.path[0], not the repo root, so the
# `from ui...` package imports below fail unless we add the repo root first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from ui.artifacts import load_demo_artifacts
from ui.engine_seam import select_engine
from ui.views import adjudicate, executor, ledger, proposals, review

_BANNER = (
    "Mock demo. Not customer-facing. Candidates are unvalidated (T2.11 pending)."
)

# Task-oriented primary surface for the accountant audience.
_PRIMARY_VIEW = "Review queue"

# Original system-layer views — kept for the developer/audit-trail audience.
_AUDIT_VIEWS = {
    "Justification ledger": ledger.render,
    "PENDING proposals": proposals.render,
    "Executor dispatch log": executor.render,
    "Adjudication panel": adjudicate.render,
}


def main() -> None:
    st.set_page_config(page_title="AgentAssist demo", layout="wide")

    # Honest banner — surfaces the mock/unvalidated status on every view.
    st.warning(f"⚠️ {_BANNER}")
    st.title("AgentAssist — reviewer demo")

    engine = select_engine()
    artifacts = load_demo_artifacts()

    with st.sidebar:
        st.header("Demo")
        st.write(f"**Engine:** `{engine.name}`")
        st.caption(
            "MockEngine renders frozen deterministic artifacts. RealEngine is a "
            "drop-in over engine.review.review — NOT wired live in this slice."
        )
        review_status = artifacts.review_result.get("status", "—")
        st.write(f"**Review status:** `{review_status}`")
        st.write(f"**Dossiers:** {len(artifacts.dossiers)}  ·  **Proposals:** {len(artifacts.proposals)}")
        st.divider()

        # Review queue is primary + default; the four system views are demoted into a
        # secondary audit/developer group.
        section = st.radio("Section", ["Review", "Audit trail / developer"], index=0)
        audit_choice = None
        if section == "Audit trail / developer":
            audit_choice = st.radio("View", list(_AUDIT_VIEWS), index=0)

    if section == "Review":
        review.render(artifacts)
    else:
        _AUDIT_VIEWS[audit_choice](artifacts)


if __name__ == "__main__":
    main()
