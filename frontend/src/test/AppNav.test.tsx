import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { App } from "../App";
import { REVIEW_FIXTURE, AUDIT_FIXTURE } from "./fixtures";

/**
 * Phase-2 (T6.3 Slice 4) — the three-view shell (Review · Findings · Audit) + sidebar + banner.
 *
 * The single scrolling column splits into three mutually-exclusive views gated on `view`.
 * The scripted-mode banner renders the SERVER's classifier_mode (from a RUN_REVIEW POST
 * /command App fires on mount) — never a hardcoded "scripted" (it would lie in live mode).
 * The UNVALIDATED trust badge stays visible in the header across all views.
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

describe("App three-view nav + sidebar + banner (T6.3 Slice 4)", () => {
  beforeEach(() => vi.stubGlobal("fetch", mockFetch()));
  afterEach(() => vi.restoreAllMocks());

  it("opens on the Review home: logo, scripted-mode banner (server-driven), composer, F5 table", async () => {
    render(<App />);
    expect(await screen.findByAltText(/AgentAssist/i)).toBeInTheDocument();
    // Banner mode comes from the server response, not a hardcoded string.
    expect(await screen.findByText(/scripted mode/i)).toBeInTheDocument();
    expect(screen.getByText(/opt-in/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Ask the assistant/i)).toBeInTheDocument();
    expect(document.querySelector(".f5-table")).not.toBeNull();
    // UNVALIDATED trust badge in the header (loud, all views).
    expect(screen.getAllByText(/unvalidated/i).length).toBeGreaterThan(0);
    // The queue is NOT on the review home.
    expect(document.querySelector(".queue-list")).toBeNull();
  });

  it("switches to the Findings view (queue + facets) and away from the Review composer", async () => {
    render(<App />);
    await screen.findByAltText(/AgentAssist/i);
    fireEvent.click(within(nav()).getByRole("button", { name: /Findings/i }));

    await waitFor(() => expect(document.querySelector(".queue-list")).not.toBeNull());
    expect(await screen.findByLabelText(/Filter findings/i)).toBeInTheDocument();
    // The composer belongs to the Review home only.
    expect(screen.queryByPlaceholderText(/Ask the assistant/i)).toBeNull();
  });

  it("switches to the Audit view (audit table) and away from the queue", async () => {
    render(<App />);
    await screen.findByAltText(/AgentAssist/i);
    fireEvent.click(within(nav()).getByRole("button", { name: /Audit/i }));

    expect(await screen.findByText(/Audit trail/i)).toBeInTheDocument();
    expect(document.querySelector(".queue-list")).toBeNull();
  });

  it("collapses the sidebar via the header toggle", async () => {
    render(<App />);
    await screen.findByAltText(/AgentAssist/i);
    expect(screen.getByText(/This period/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Toggle sidebar/i }));
    await waitFor(() => expect(screen.queryByText(/This period/i)).toBeNull());
  });

  it("dismisses the scripted-mode banner for the session", async () => {
    render(<App />);
    expect(await screen.findByText(/scripted mode/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Dismiss banner/i }));
    await waitFor(() => expect(screen.queryByText(/scripted mode/i)).toBeNull());
  });
});
