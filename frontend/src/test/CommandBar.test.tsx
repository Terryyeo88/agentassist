import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { CommandBar } from "../components/CommandBar";

/**
 * T6.2 command-bar render smoke: a mocked POST /command `result` renders the execution,
 * and an `out_of_scope` reply renders the polite message (buttons remain available). All
 * over mocked fetch — no backend, no tokens.
 */
const PRIOR_RESULT = {
  kind: "result",
  classifier_mode: "scripted",
  disclaimer: "Demo / illustrative — validation_status=unvalidated.",
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
          entry_id: "b986",
          fingerprint: "sha256:3d87",
          disposition: "KNOWN_ACCEPTED",
          reviewer: "Prior-Period Reviewer",
          reason: "supplier confirmed not GST-registered",
          period: "2024Q2",
          timestamp: "2024-06-30T00:00:00+00:00",
        },
      ],
    },
    notes: ["SHOW_PRIOR_ADJUDICATIONS menu gap (v0/PROVISIONAL): list-all."],
  },
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

describe("CommandBar (T6.2)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("renders a /command result execution", async () => {
    mockCommand(PRIOR_RESULT);
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);

    fireEvent.click(screen.getByRole("button", { name: /Prior decisions/i }));

    await waitFor(() =>
      expect(screen.getAllByText(/SHOW_PRIOR_ADJUDICATIONS/).length).toBeGreaterThan(0)
    );
    expect(screen.getByText("KNOWN_ACCEPTED")).toBeInTheDocument();
    expect(screen.getByText(/Prior-Period Reviewer/)).toBeInTheDocument();
    // The classifier mode is shown (trust signal).
    expect(screen.getByText(/scripted/)).toBeInTheDocument();
  });

  it("renders an out_of_scope reply; intent buttons remain available", async () => {
    mockCommand(OUT_OF_SCOPE);
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);

    // Type an off-menu utterance, then ask.
    fireEvent.change(screen.getByPlaceholderText(/Ask the assistant/i), {
      target: { value: "what's the weather" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Ask$/ }));

    await waitFor(() =>
      expect(screen.getByText(/I can help with reviews/i)).toBeInTheDocument()
    );
    // The four intent buttons are still present (a tool never ran).
    expect(screen.getByRole("button", { name: /Run a review/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Prior decisions/i })).toBeInTheDocument();
  });
});
