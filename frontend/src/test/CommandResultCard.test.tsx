import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { CommandBar } from "../components/CommandBar";

/**
 * Phase-2 (T6.3 Slice 4) — the styled command-result CARD.
 *
 * The command bar was already LIVE on POST /command (T6.2); this slice gives its response a
 * dark result card with a status pill that depends on `kind`, an × dismiss, and a footer that
 * renders the SERVER's `classifier_mode` + `disclaimer` (never a hardcoded "scripted", or it
 * would lie in live mode). Intent keys off the REAL intent name (SHOW_PRIOR_ADJUDICATIONS),
 * not the README's `PRIOR_DECISIONS`. All over mocked fetch — no backend, no tokens.
 *
 * vitest is NOT the merge gate (CI is pytest-only); these pin the card contract.
 */

const PRIOR_RESULT = {
  kind: "result",
  classifier_mode: "scripted",
  disclaimer:
    "read-only over frozen artifacts — the assistant classifies intent and runs reads; it never acts on your text and never writes back to SAP.",
  intent: "SHOW_PRIOR_ADJUDICATIONS",
  execution: {
    intent: "SHOW_PRIOR_ADJUDICATIONS",
    outcome: "executed",
    sequence: ["read_decision_ledger"],
    tiers: [0],
    params: { client_id: "sbodemosg", period: "2024Q3" },
    data: {
      adjudications: [
        {
          disposition: "KNOWN_ACCEPTED",
          reviewer: "Prior-Period Reviewer",
          reason: "supplier confirmed not GST-registered",
          period: "2024Q2",
        },
      ],
    },
    notes: [],
  },
};

const NEEDS_CLARIFICATION = {
  kind: "needs_clarification",
  classifier_mode: "scripted",
  disclaimer: "Demo / illustrative.",
  intent: "SHOW_PRIOR_ADJUDICATIONS",
  missing: ["period"],
  message: "Which period should I look at?",
};

const OUT_OF_SCOPE = {
  kind: "out_of_scope",
  classifier_mode: "scripted",
  disclaimer: "Demo / illustrative.",
  message: "I can help with reviews, proposals, or prior decisions. Try one of the buttons.",
  buttons: ["Run a review", "Show ledger", "Show proposals", "Prior decisions"],
};

function mockCommand(payload: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(JSON.stringify(payload), { status: 200 })))
  );
}

describe("CommandBar — styled result card (T6.3 Slice 4)", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("a `result` renders an accent pill `{intent} · {outcome}` keyed on the REAL intent name", async () => {
    mockCommand(PRIOR_RESULT);
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    fireEvent.click(screen.getByRole("button", { name: /Prior decisions/i }));

    const pill = await screen.findByText(/SHOW_PRIOR_ADJUDICATIONS · executed/i);
    expect(pill).toBeInTheDocument();
    // The body renders the adjudication row verbatim (disposition · reviewer · period).
    expect(screen.getByText("KNOWN_ACCEPTED")).toBeInTheDocument();
    expect(screen.getByText(/Prior-Period Reviewer/)).toBeInTheDocument();
    // Footer renders the SERVER classifier_mode + disclaimer (trust signal, server-driven).
    expect(screen.getByText(/scripted/)).toBeInTheDocument();
    expect(screen.getByText(/never writes back to SAP/i)).toBeInTheDocument();
  });

  it("a `needs_clarification` renders an amber 'needs clarification' pill + the missing list", async () => {
    mockCommand(NEEDS_CLARIFICATION);
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    fireEvent.change(screen.getByPlaceholderText(/Ask the assistant/i), {
      target: { value: "show prior decisions" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Ask$/ }));

    expect(await screen.findByText(/needs clarification/i)).toBeInTheDocument();
    expect(screen.getByText(/Which period should I look at\?/i)).toBeInTheDocument();
    expect(screen.getByText(/missing: period/i)).toBeInTheDocument();
  });

  it("an `out_of_scope` renders a muted 'out of scope' pill + the polite message", async () => {
    mockCommand(OUT_OF_SCOPE);
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    fireEvent.change(screen.getByPlaceholderText(/Ask the assistant/i), {
      target: { value: "what's the weather" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Ask$/ }));

    expect(await screen.findByText(/out of scope/i)).toBeInTheDocument();
    expect(screen.getByText(/I can help with reviews/i)).toBeInTheDocument();
  });

  it("the × dismiss button clears the result card", async () => {
    mockCommand(PRIOR_RESULT);
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    fireEvent.click(screen.getByRole("button", { name: /Prior decisions/i }));
    await screen.findByText(/SHOW_PRIOR_ADJUDICATIONS · executed/i);

    fireEvent.click(screen.getByRole("button", { name: /Dismiss result/i }));
    await waitFor(() =>
      expect(screen.queryByText(/SHOW_PRIOR_ADJUDICATIONS · executed/i)).toBeNull()
    );
    // The composer + intent chips remain after dismiss.
    expect(screen.getByRole("button", { name: /Prior decisions/i })).toBeInTheDocument();
  });
});
