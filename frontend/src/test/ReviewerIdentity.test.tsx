import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { App } from "../App";
import { AUDIT_FIXTURE, REVIEW_FIXTURE } from "./fixtures";

/**
 * ReviewerIdentity — BUILD ID t-xero-signoff, FAILING-FIRST (Contract D).
 *
 * Written BEFORE the implementation; MUST fail today for the RIGHT reason — the App surface
 * has no reviewer-identity input yet, and a recorded decision still POSTs the hardcoded
 * `WEB_REVIEWER = "web-demo-reviewer"` constant.
 *
 * HARD INVARIANT PINNED HERE (three-times rule — mirrors the backend reviewer-of-record):
 *   * REVIEWER-IDENTITY IS COLLECTED, NOT INVENTED — the App exposes a reviewer input (label
 *     containing "Reviewer") whose value feeds postDecision. A recorded decision carries the
 *     name the user entered, and the string "web-demo-reviewer" NEVER appears in any decision
 *     POST body once a name is entered.
 *
 * Mirrors App.smoke.test.tsx's fetch-mock + three-view-nav pattern. The NO_GST_REG:592 row is
 * the one queue finding carrying a fingerprint, so it is the row whose decision persists.
 */

const RUN_REVIEW = {
  kind: "result",
  classifier_mode: "scripted",
  disclaimer: "read-only over frozen artifacts — never writes back to SAP.",
  intent: "RUN_REVIEW",
  execution: {
    intent: "RUN_REVIEW",
    outcome: "executed",
    sequence: ["run_review_chain"],
    tiers: [1],
    params: { client_id: "sbodemosg", period: "2024Q3" },
    data: {
      review_result: {},
      dossiers: [
        { finding_id: "detect:E1:958", check_id: "E1", finding_type: "deterministic" },
        { finding_id: "detect:NO_GST_REG:592", check_id: "NO_GST_REG", finding_type: "deterministic" },
      ],
      f5_summary: REVIEW_FIXTURE.f5_summary,
      available_facets: { error_code: { E1: 1, NO_GST_REG: 1 } },
      findings: [
        { finding_id: "detect:E1:958", check_id: "E1", finding_type: "deterministic" },
        { finding_id: "detect:NO_GST_REG:592", check_id: "NO_GST_REG", finding_type: "deterministic" },
      ],
      remaining_facets: { error_code: { E1: 1, NO_GST_REG: 1 } },
      applied_filters: {},
      filter_rejection: null,
    },
    notes: [],
  },
};

const DECISION_RESPONSE = {
  client_id: "sbodemosg",
  finding_id: "detect:NO_GST_REG:592",
  action: "Accept",
  disposition: "ACCEPTED",
  fingerprint: "sha256:3d87ffc0",
  entry_id: "b986d57f",
  entry_hash: "sha256:def",
  chain_length: 1,
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags — you decide.",
};

function mockFetch() {
  return vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    // Order matters: /decision + /command are checked before the generic /review.
    if (url.includes("/decision")) return Promise.resolve(new Response(JSON.stringify(DECISION_RESPONSE), { status: 200 }));
    if (url.includes("/command")) return Promise.resolve(new Response(JSON.stringify(RUN_REVIEW), { status: 200 }));
    if (url.includes("/audit")) return Promise.resolve(new Response(JSON.stringify({ entries: AUDIT_FIXTURE }), { status: 200 }));
    if (url.includes("/review")) return Promise.resolve(new Response(JSON.stringify(REVIEW_FIXTURE), { status: 200 }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

const nav = () => screen.getByRole("navigation", { name: /Primary/i });

describe("Reviewer identity on the App surface", () => {
  beforeEach(() => vi.stubGlobal("fetch", mockFetch()));
  afterEach(() => vi.restoreAllMocks());

  it("exposes a reviewer-identity input on the review surface", async () => {
    render(<App />);
    await screen.findByPlaceholderText(/Ask the assistant/i);
    // A textbox whose accessible name mentions the reviewer of record.
    expect(screen.getByRole("textbox", { name: /reviewer/i })).toBeInTheDocument();
  });

  it("a recorded decision carries the entered reviewer name, not web-demo-reviewer", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await screen.findByPlaceholderText(/Ask the assistant/i);

    // Enter the reviewer of record.
    const reviewerInput = screen.getByRole("textbox", { name: /reviewer/i });
    fireEvent.change(reviewerInput, { target: { value: "Collin Tan" } });

    // Go to Findings and select the fingerprinted (persistable) NO_GST_REG row.
    fireEvent.click(within(nav()).getByRole("button", { name: /Findings/i }));
    await waitFor(() => expect(screen.getAllByText("E1").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("tab", { name: /Marked known/i }));
    await waitFor(() => {
      const list = document.querySelector(".queue-list")!;
      expect(within(list as HTMLElement).getByText("Far East Imports")).toBeInTheDocument();
    });
    fireEvent.click(
      within(document.querySelector(".queue-list") as HTMLElement).getByText("Far East Imports")
    );

    // Record the default "Accept" decision (no note required).
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));

    // A single decision POST fired carrying the entered name — never the demo constant.
    await waitFor(() => {
      const decisionCall = fetchMock.mock.calls.find(([u]) => String(u).includes("/decision"));
      expect(decisionCall).toBeTruthy();
    });
    const decisionCall = fetchMock.mock.calls.find(([u]) => String(u).includes("/decision"))!;
    const body = JSON.parse((decisionCall[1] as RequestInit).body as string);
    expect(body.reviewer_name).toBe("Collin Tan");

    // "web-demo-reviewer" appears in NO fetch body once a reviewer name is entered.
    for (const [, init] of fetchMock.mock.calls) {
      const raw = (init as RequestInit | undefined)?.body;
      if (typeof raw === "string") expect(raw).not.toContain("web-demo-reviewer");
    }
  });
});
