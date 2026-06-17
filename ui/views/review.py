"""ui/views/review.py — T5.8d task-oriented review surface (PRIMARY view).

A reviewer funnel over the UNCHANGED artifacts.py view-models:

    queue (needs review / marked known / decided)
      -> finding detail card (vendor · what we found · why it matters · the rule ·
         suggested action)
      -> decide (accept / not an issue / mark known)
      -> sign working paper.

This is a PRESENTATION-LAYER rebuild: it reuses ``annotated_adjudication_items`` (so the
T5.5b decision-ledger demotion shows as "marked known", cardinality preserved), the two
PURE accessors (``flatten_finding_card`` / ``check_reference``), the EXISTING session
decide/record mechanism, and ``sign_working_paper`` UNCHANGED. No engine call, no F5
recompute, no new write-wiring.

Trust signals are preserved verbatim from the adjudication panel: the VALIDATION_STATUS
badge, the ``lint_framing`` candidate-framing guard, and reviewer-name-required Sign. Raw
ids / hashes / json sit behind a "Technical details" expander only.
"""
from __future__ import annotations

import streamlit as st

from agent.lint import lint_framing
from ui.artifacts import (
    DemoArtifacts,
    VALIDATION_STATUS,
    annotated_adjudication_items,
    check_reference,
    flatten_finding_card,
)
from ui.sign import sign_working_paper

# Plain-language decision vocabulary. "Accept" needs no note; the two dispositions away
# from accept require the reviewer to record their reasoning.
_DECISIONS = ["Accept", "Not an issue", "Mark known"]
_NOTE_REQUIRED = {"Not an issue", "Mark known"}

_GROUP_LABELS = {
    "needs_review": "Needs review",
    "marked_known": "Marked known",
    "decided": "Decided",
}


def _decision_key(finding_id: str) -> str:
    # SAME session key the adjudication panel uses — the two views share decisions.
    return f"decision::{finding_id}"


def build_queue(items: list[dict], decisions: dict[str, dict]) -> dict[str, list[dict]]:
    """Group review items into needs-review / marked-known / decided buckets.

    PURE: list + decisions in, grouped dict out. Precedence is decided > marked-known >
    needs-review, so a recorded decision always wins. Cardinality is preserved — every
    item lands in exactly one bucket; the T5.5b-demoted items surface under "marked known"
    (present, never dropped).
    """
    decisions = decisions or {}
    queue: dict[str, list[dict]] = {"needs_review": [], "marked_known": [], "decided": []}
    for it in items:
        fid = it.get("finding_id")
        if fid in decisions:
            queue["decided"].append(it)
        elif it.get("demoted"):
            queue["marked_known"].append(it)
        else:
            queue["needs_review"].append(it)
    return queue


def _current_decisions(items: list[dict]) -> dict[str, dict]:
    """Read recorded decisions for the panel's findings out of session state."""
    out: dict[str, dict] = {}
    for it in items:
        rec = st.session_state.get(_decision_key(it["finding_id"]))
        if rec:
            out[it["finding_id"]] = rec
    return out


def _ordered(queue: dict[str, list[dict]]) -> list[dict]:
    """Flatten the queue for selection: needs review first, then known, then decided."""
    return queue["needs_review"] + queue["marked_known"] + queue["decided"]


def _group_of(finding_id: str, queue: dict[str, list[dict]]) -> str:
    for group, rows in queue.items():
        if any(it["finding_id"] == finding_id for it in rows):
            return group
    return "needs_review"


def render(artifacts: DemoArtifacts) -> None:
    st.subheader("Review queue")
    st.caption(
        "Task view for the reviewer of record. Each row is a CANDIDATE for review, not a "
        "compliance verdict. Work the queue: read what we found, why it matters and the "
        "rule, then record your decision and sign the working paper."
    )

    items = annotated_adjudication_items(artifacts)
    if not items:
        st.info("No findings in the frozen demo artifacts.")
        return

    decisions = _current_decisions(items)
    queue = build_queue(items, decisions)

    # --- Queue summary (three plain-language buckets) ---
    c1, c2, c3 = st.columns(3)
    c1.metric("Needs review", len(queue["needs_review"]))
    c2.metric("Marked known", len(queue["marked_known"]))
    c3.metric("Decided", len(queue["decided"]))

    ordered = _ordered(queue)

    def _label(it: dict) -> str:
        flat = flatten_finding_card(it)
        group = _GROUP_LABELS[_group_of(it["finding_id"], queue)]
        vendor = flat["vendor"] or "—"
        doc = flat["doc_num"] if flat["doc_num"] is not None else "—"
        return f"[{group}]  {it['check_id']} · doc {doc} · {vendor}"

    idx = st.selectbox(
        "Finding", range(len(ordered)), format_func=lambda i: _label(ordered[i])
    )
    item = ordered[idx]
    flat = flatten_finding_card(item)
    ref = check_reference(item["check_id"])

    st.divider()

    # --- Trust signal: validation badge (verbatim copy) ---
    st.warning(
        f"validation_status: **{VALIDATION_STATUS}** — candidate for review only "
        "(T2.11 is the binding gate; nothing here is a confirmed compliance verdict)."
    )

    # --- Finding detail card (plain language) ---
    st.markdown(f"### {ref['display_name']}")
    vendor = flat["vendor"] or "—"
    doc = flat["doc_num"] if flat["doc_num"] is not None else "—"
    sev = flat["severity"] or "—"
    st.markdown(
        f"**Vendor:** {vendor}  ·  **Document:** {doc}  ·  **Severity:** {sev}"
    )

    st.markdown("**What we found**")
    st.write(flat["description"] or "—")

    st.markdown("**Why it matters · the rule**")
    st.write(ref["iras_basis"] or "—")

    st.markdown("**Suggested action**")
    st.write(flat["recommendation"] or "—")

    # --- Trust signal: candidate framing through the language-lint guard (verbatim) ---
    framing = item["candidate_framing_text"]
    lint = lint_framing(framing)
    if not lint.passed:
        st.error(f"Candidate framing failed the language-lint ({lint.reasons}); held back.")
    else:
        st.info(f"**Candidate framing:** {framing}")

    # --- Marked-known memory (T5.5b): present-but-demoted, shown not hidden ---
    if item.get("demoted"):
        priors = ", ".join(item.get("prior_dispositions") or ()) or "—"
        st.caption(
            "Marked known from a prior period (decision-ledger memory): "
            f"{item.get('annotation') or 'previously accepted'} · prior dispositions: {priors}. "
            "Still surfaced for review — demotion lowers prominence, it never drops a finding."
        )

    st.divider()

    # --- Your decision (reuses the SAME session record mechanism) ---
    st.markdown("#### Your decision")
    action = st.radio(
        "Decision", _DECISIONS, horizontal=True, key=f"act::{item['finding_id']}"
    )
    note = ""
    if action in _NOTE_REQUIRED:
        note = st.text_area(
            f"Reviewer note (required for “{action}”)",
            key=f"note::{item['finding_id']}",
            placeholder="Record your reasoning; this attaches to the finding, not to box values.",
        )

    if st.button("Record decision", key=f"record::{item['finding_id']}"):
        if action in _NOTE_REQUIRED and not note.strip():
            st.error(f"“{action}” requires a non-empty reviewer note.")
        else:
            st.session_state[_decision_key(item["finding_id"])] = {
                "finding_id": item["finding_id"],
                "action": action,
                "note": note.strip(),
            }
            st.success(f"Recorded: {action} for this finding.")

    recorded = st.session_state.get(_decision_key(item["finding_id"]))
    if recorded:
        st.caption(
            f"Current decision: **{recorded['action']}**"
            + (f" — {recorded['note']}" if recorded["note"] else "")
        )

    # --- Technical details (raw ids / hashes / json) behind an expander only ---
    with st.expander("Technical details", expanded=False):
        st.write(
            f"**finding_id:** `{item['finding_id']}`  ·  **check_id:** `{item['check_id']}`  "
            f"·  **type:** {item['finding_type']}"
        )
        st.write(f"**inputs_hash:** `{item.get('inputs_hash', '—')}`")
        if item.get("fingerprint"):
            st.write(f"**decision-ledger fingerprint:** `{item['fingerprint']}`")
        if item.get("proposal_id"):
            st.write(f"**staging proposal:** {item['proposal_id']} ({item.get('proposal_status')})")
        comp = item["completeness"]
        st.write(
            f"**Completeness (code-defined):** "
            f"{'satisfied' if comp['satisfied'] else 'incomplete'} · "
            f"required={comp['required']} · present={comp['present']} · missing={comp['missing']}"
        )
        st.json(item["evidence"])

    st.divider()

    # --- Sign working paper (reviewer name required; clay-accent primary action) ---
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
                # Same session dispatch-record side-effect as the adjudication panel, so
                # the audit/developer executor view stays consistent across both surfaces.
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
