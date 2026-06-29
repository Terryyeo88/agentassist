import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { App } from "../App";
import { AUDIT_FIXTURE, REVIEW_FIXTURE } from "./fixtures";

/**
 * Render smoke over a REAL-SHAPED fixture — REWRITTEN for the three-view nav (T6.3 Slice 4).
 *
 * The old single-column "everything on one load" contract becomes the new nav contract:
 *  - the Review home carries the live command bar + the UNVALIDATED badge + the F5 table;
 *  - the Findings view carries the queue, the finding detail (with the illustrative-citation
 *    caveat), and the Sign action;
 *  - the genuinely-seeded demoted doc-592 entry still surfaces under "Marked known";
 *  - NO fictional check types (DUP_CLAIM / SEQ_GAP / FLUX) appear anywhere.
 * Assertions are kept at equal-or-greater strength — a contract update, not a weakening.
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

function mockFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/")) return Promise.resolve(new Response(JSON.stringify(REVIEW_FIXTURE), { status: 200 }));
    if (url.includes("/audit")) return Promise.resolve(new Response(JSON.stringify({ entries: AUDIT_FIXTURE }), { status: 200 }));
    if (url.includes("/command")) return Promise.resolve(new Response(JSON.stringify(RUN_REVIEW), { status: 200 }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

const nav = () => screen.getByRole("navigation", { name: /Primary/i });
function gotoFindings() {
  fireEvent.click(within(nav()).getByRole("button", { name: /Findings/i }));
}

describe("App review surface (render smoke)", () => {
  beforeEach(() => vi.stubGlobal("fetch", mockFetch()));
  afterEach(() => vi.restoreAllMocks());

  it("the Review home is live: command bar, F5 table, UNVALIDATED badge", async () => {
    render(<App />);
    const input = await screen.findByPlaceholderText(/Ask the assistant/i);
    expect(input).not.toBeDisabled();
    expect(screen.getByRole("button", { name: /^Ask$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Prior decisions/i })).toBeInTheDocument();
    // Identity comes from the surface context (one way in), not the old inert-shell copy.
    expect(screen.getByText(/identity comes from the surface context/i)).toBeInTheDocument();
    // UNVALIDATED trust badge present (loud).
    expect(screen.getAllByText(/unvalidated/i).length).toBeGreaterThan(0);
    // F5 box value rendered (box-isolated GET /review data).
    expect(screen.getByText("12,663.87")).toBeInTheDocument();
  });

  it("the Findings view renders the queue, finding detail, and the illustrative-citation caveat", async () => {
    render(<App />);
    await screen.findByPlaceholderText(/Ask the assistant/i);
    gotoFindings();

    await waitFor(() => expect(screen.getAllByText("E1").length).toBeGreaterThan(0));
    // Detail card shows the selected finding + the illustrative-citation caveat (verbatim trust).
    expect(await screen.findByText(/Standard-rated sales on likely export/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Illustrative citation/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Sign working paper/i })).toBeInTheDocument();
  });

  it("surfaces the genuinely-seeded demoted doc-592 entry in 'Marked known'", async () => {
    render(<App />);
    await screen.findByPlaceholderText(/Ask the assistant/i);
    gotoFindings();
    await waitFor(() => expect(screen.getAllByText("E1").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("tab", { name: /Marked known/i }));
    await waitFor(() => {
      const list = document.querySelector(".queue-list")!;
      expect(within(list as HTMLElement).getByText("Far East Imports")).toBeInTheDocument();
    });
  });

  it("never renders the mock's fictional check types", async () => {
    const { container } = render(<App />);
    await screen.findByPlaceholderText(/Ask the assistant/i);
    gotoFindings();
    await waitFor(() => expect(screen.getAllByText("E1").length).toBeGreaterThan(0));
    for (const fictional of ["DUP_CLAIM", "SEQ_GAP", "FLUX"]) {
      expect(container.innerHTML).not.toContain(fictional);
    }
  });
});
