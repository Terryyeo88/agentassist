import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { XeroAuditView } from "../components/XeroAuditView";
import type { DecisionResponse } from "../api";

/**
 * C-6(a) frontend — the session decision list gains a When and a Reviewer column.
 *
 * FAILING-FIRST: written before the columns existed, against the twelve-key POST /decision
 * contract (the backend RED). Both new keys are REAL ledger values, not derived here:
 * `reviewer` is agent/decision_ledger.py's `reviewer: str` and `timestamp` its `timestamp: str`
 * ("ISO-8601 timestamp of the adjudication"), and BOTH are hashed into the append-only chain
 * (decision_ledger.py:335-336), so what renders is a tamper-evident record.
 *
 * THE POINT OF THE VERBATIM ASSERTION (§8, no fabricated values): the rendered cell text is
 * pinned to the payload string EXACTLY. A browser clock, a re-format, or a locale render would
 * all fail here — which is the whole point. Likewise the reviewer must come from the response,
 * not the locally-held reviewer-of-record input.
 *
 * C-6(b) update: the read endpoint (GET /decisions) now exists, so the old "no read endpoint /
 * session-only" scope callout would be a false statement — test 2 now pins its ABSENCE.
 */

const RECORDED_AT = "2026-07-29T08:31:24.512874+00:00";
const RECORDED_BY = "Collin Tan";

const DECISION: DecisionResponse = {
  client_id: "xero_demo",
  finding_id: "detect:E2:INV-2003",
  action: "Mark known",
  disposition: "KNOWN_ACCEPTED",
  fingerprint: "sha256:" + "a".repeat(64),
  entry_id: "entry-0001",
  entry_hash: "sha256:c0ffee1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
  reviewer: RECORDED_BY,
  timestamp: RECORDED_AT,
  chain_length: 1,
  validation_status: "unvalidated",
  disclaimer: "Candidates, not verdicts.",
};

describe("C-6(a): the session decision list carries When + Reviewer from the ledger", () => {
  it("renders a When and a Reviewer column, each carrying the response value verbatim", () => {
    render(<XeroAuditView decisions={[DECISION]} />);

    // PRESENCE FIRST (D-16): the table and its pre-existing columns really rendered.
    const rows = document.querySelectorAll(".xaudit-row");
    expect(rows).toHaveLength(1);
    const row = rows[0] as HTMLElement;
    expect(screen.getByRole("columnheader", { name: /^finding$/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /^action$/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /^disposition$/i })).toBeInTheDocument();
    expect(row).toHaveTextContent("KNOWN_ACCEPTED");

    // The two new columns exist...
    expect(screen.getByRole("columnheader", { name: /^when$/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /^reviewer$/i })).toBeInTheDocument();

    // ...and carry the LEDGER's values, character for character. Not a browser clock, not a
    // reformat, not the locally-typed reviewer name. (§8 — restored: these are the verbatim pins.)
    expect(within(row).getByText(RECORDED_AT)).toBeInTheDocument();
    expect(within(row).getByText(RECORDED_BY)).toBeInTheDocument();
  });

  it("no longer claims session-only scope — the decision read endpoint now exists (C-6b)", () => {
    render(<XeroAuditView decisions={[DECISION]} />);

    // GET /decisions shipped in C-6(b). The old "no read endpoint / only this browser session"
    // scope claim would now be a false statement, so it must be gone from the (slimmed) callout.
    const callout = screen.queryByTestId("xaudit-limits");
    if (callout) {
      expect(callout).not.toHaveTextContent(/no read endpoint/i);
      expect(callout).not.toHaveTextContent(/only the decisions made in this browser session/i);
    }
  });
});
