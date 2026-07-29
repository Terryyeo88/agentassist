import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { XeroAuditView } from "../components/XeroAuditView";
import type { DecisionResponse } from "../api";

/**
 * C-6(a) frontend — the session decision list gains a When and a Reviewer column.
 *
 * FAILING-FIRST: written before the columns exist, against the twelve-key POST /decision
 * contract Collin hand-authored in tests/test_decision_endpoint_contract.py (the backend RED
 * that precedes this one). Both new keys are REAL ledger values, not derived here:
 * `reviewer` is agent/decision_ledger.py's `reviewer: str` and `timestamp` its `timestamp: str`
 * ("ISO-8601 timestamp of the adjudication"), and BOTH are hashed into the append-only chain
 * (decision_ledger.py:335-336), so what renders is a tamper-evident record.
 *
 * THE POINT OF THE VERBATIM ASSERTION (§8, no fabricated values). The reason this view carried
 * no When column before was not laziness — it was honesty: with no timestamp on the response, a
 * column could only have been filled from `new Date()`, i.e. this page's GUESS at when the
 * adjudication happened rather than the ledger's record of it. So the test does not merely check
 * that a cell is non-empty; it pins the rendered text to the payload string EXACTLY. A browser
 * clock, a re-format, or a locale render would all fail here — which is the whole point.
 * Likewise the reviewer must come from the response, not from the locally-held reviewer-of-record
 * input (those can differ: the response reports who the ledger actually recorded).
 *
 * D-16: presence before absence — the row and the pre-existing columns are asserted first, so a
 * view that silently failed to render could not pass by having "no wrong columns".
 *
 * THREE-TIMES RULE: the twelve-key contract is stated in api/app.py's DECISION_KEYS comment,
 * enforced by the api/app.py return dict + frontend DecisionResponse type, and asserted here
 * (frontend) and in tests/test_decision_endpoint_contract.py (backend).
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
    // reformat, not the locally-typed reviewer name.
    expect(within(row).getByText(RECORDED_AT)).toBeInTheDocument();
    expect(within(row).getByText(RECORDED_BY)).toBeInTheDocument();
  });

  it("still tells the truth about session scope — there is STILL no decision read endpoint", () => {
    render(<XeroAuditView decisions={[DECISION]} />);

    // Surfacing when/who does NOT make the list complete: POST /decision returning two more
    // keys is not a GET /decisions. The honest scope callout must survive this change intact.
    const callout = screen.getByTestId("xaudit-limits");
    expect(callout).toHaveTextContent(/no read endpoint/i);
    expect(callout).toHaveTextContent(/only the decisions made in this browser session/i);
  });
});
