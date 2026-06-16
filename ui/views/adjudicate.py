"""ui/views/adjudicate.py — per-finding reviewer adjudication panel.

Per-finding dossier → Accept / Edit / Reject (required note) → Sign → working-paper PDF.

The panel is a VIEW: adjudication decisions/notes attach to the dossier/proposal in
session state; they never mutate the ReviewResult or recompute F5 boxes. Candidate copy
is surfaced with a validation_status badge and candidate framing — never as a verdict.
"""
from __future__ import annotations

import streamlit as st

from agent.lint import lint_framing
from ui.artifacts import DemoArtifacts, adjudication_items
from ui.sign import sign_working_paper


def _decision_key(finding_id: str) -> str:
    return f"decision::{finding_id}"


def render(artifacts: DemoArtifacts) -> None:
    st.subheader("Reviewer adjudication panel")
    st.caption(
        "Per-finding case file for the reviewer of record. Surfaced items are "
        "CANDIDATES for review, not compliance verdicts. Accept / Edit / Reject each, "
        "then Sign to emit the working-paper PDF."
    )

    items = adjudication_items(artifacts)
    if not items:
        st.info("No dossiers in the frozen demo artifacts.")
        return

    labels = [f"{it['finding_id']}  ·  {it['check_id']}" for it in items]
    idx = st.selectbox("Finding", range(len(items)), format_func=lambda i: labels[i])
    item = items[idx]

    # --- Validation badge + candidate framing (never a verdict) ---
    st.markdown(
        f"**Finding:** `{item['finding_id']}`  ·  **Check:** `{item['check_id']}`  "
        f"·  **Type:** {item['finding_type']}"
    )
    st.warning(
        f"validation_status: **{item['validation_status']}** — candidate for review only "
        "(T2.11 is the binding gate; nothing here is a confirmed compliance verdict)."
    )

    framing = item["candidate_framing_text"]
    lint = lint_framing(framing)
    if not lint.passed:
        # Defensive reuse of the language-lint: a non-candidate-framed string should
        # never reach the reviewer. Frozen fixtures are lint-clean; this guards regressions.
        st.error(f"Candidate framing failed the language-lint ({lint.reasons}); held back.")
    else:
        st.info(f"**Candidate framing:** {framing}")

    # --- Tier-0 evidence + CODE-DEFINED completeness ---
    with st.expander("Tier-0 evidence map (untrusted input)", expanded=False):
        st.json(item["evidence"])
    comp = item["completeness"]
    st.write(
        f"**Completeness (code-defined):** {'✅ satisfied' if comp['satisfied'] else '⚠️ incomplete'}"
        f"  ·  required={comp['required']}  ·  present={comp['present']}  ·  missing={comp['missing']}"
    )
    if item.get("proposal_id"):
        st.caption(f"Staging proposal: {item['proposal_id']} ({item.get('proposal_status')})")

    st.divider()

    # --- Accept / Edit / Reject (note required for Edit + Reject) ---
    action = st.radio("Adjudication", ["Accept", "Edit", "Reject"], horizontal=True, key=f"act::{item['finding_id']}")
    note = ""
    if action in ("Edit", "Reject"):
        note = st.text_area(
            f"Reviewer note (required for {action})",
            key=f"note::{item['finding_id']}",
            placeholder="Record your reasoning; this attaches to the dossier, not to box values.",
        )

    if st.button("Record adjudication", key=f"record::{item['finding_id']}"):
        if action in ("Edit", "Reject") and not note.strip():
            st.error(f"{action} requires a non-empty reviewer note.")
        else:
            st.session_state[_decision_key(item["finding_id"])] = {
                "finding_id": item["finding_id"],
                "action": action,
                "note": note.strip(),
            }
            st.success(f"Recorded: {action} for {item['finding_id']}.")

    recorded = st.session_state.get(_decision_key(item["finding_id"]))
    if recorded:
        st.caption(f"Current decision: **{recorded['action']}**" + (f" — {recorded['note']}" if recorded["note"] else ""))

    st.divider()

    # --- Sign → working-paper PDF (reviewer name required) ---
    st.markdown("#### Sign working paper")
    st.caption(
        "Signing renders the working-paper PDF through the existing report path. "
        "show_ai_candidates stays False (T2.11) — the AI-candidates subsection is "
        "disabled in the signed PDF."
    )
    reviewer_name = st.text_input("Reviewer name (required to sign)", key="reviewer_name")
    firm_name = st.text_input("Firm name (optional)", key="firm_name")

    if st.button("Sign and emit working paper", type="primary", key="sign_button"):
        if not reviewer_name.strip():
            st.error("Sign requires a non-empty reviewer name.")
        else:
            try:
                pdf_path = sign_working_paper(
                    artifacts.review_result,
                    reviewer_name=reviewer_name.strip(),
                    firm_name=firm_name.strip(),
                )
            except Exception as exc:  # surface render errors in-UI
                st.error(f"Working-paper render failed: {exc}")
            else:
                st.success(f"Signed working paper written to: {pdf_path}")
                # Record the executor dispatch for the executor view (session-only).
                st.session_state.setdefault("dispatches", []).append({
                    "action": "emit_final_pdf",
                    "outcome": "executed",
                    "justification": f"Reviewer {reviewer_name.strip()} signed the working paper.",
                    "timestamp": "",
                    "source": "session",
                })
                with open(pdf_path, "rb") as fh:
                    st.download_button(
                        "Download working-paper PDF", fh.read(),
                        file_name=pdf_path.name, mime="application/pdf",
                    )
