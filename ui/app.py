"""
ui/app.py — T5.8 demo showcase Streamlit entry point.

Fixed navigation (NOT an intent router) across the four demo views, rendered over the
MockEngine / RealEngine seam. Default engine is Mock, loading FROZEN deterministic
artifacts; no live SAP, no live model, no tokens.

Run:
    streamlit run ui/app.py
    AGENT_UI_ENGINE=mock streamlit run ui/app.py   # explicit (default)
"""
from __future__ import annotations

import streamlit as st

from ui.artifacts import load_demo_artifacts
from ui.engine_seam import select_engine
from ui.views import adjudicate, executor, ledger, proposals

_BANNER = (
    "Mock demo. Not customer-facing. Candidates are unvalidated (T2.11 pending)."
)

_VIEWS = {
    "Justification ledger": ledger.render,
    "PENDING proposals": proposals.render,
    "Executor dispatch log": executor.render,
    "Adjudication panel": adjudicate.render,
}


def main() -> None:
    st.set_page_config(page_title="AgentAssist T5.8 demo", layout="wide")

    # Honest banner — surfaces the mock/unvalidated status on every view.
    st.warning(f"⚠️ {_BANNER}")
    st.title("AgentAssist — Tier-5 demo showcase")

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
        choice = st.radio("View", list(_VIEWS), index=0)

    _VIEWS[choice](artifacts)


if __name__ == "__main__":
    main()
