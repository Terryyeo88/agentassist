import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { CommandBar } from "../components/CommandBar";

/**
 * T6.3 Slice 3b — the React facet UI over the SERVER filter seam.
 *
 * Everything is mocked at `fetch`: the menu is data-derived from `available_facets`, a chip
 * click triggers a `/command` re-POST carrying that filter (the SERVER does the filtering —
 * the browser never filters client-side), the narrowed `findings` + "X of Y shown" +
 * `remaining_facets` chip counts render, clear resets, `filter_rejection` renders honestly,
 * the F5 boxes are unchanged under a filter, and a read (SHOW_LEDGER) shows no facet panel.
 *
 * vitest is NOT the merge gate (CI is pytest-only — T6.1 toolchain separation); the binding
 * check is the live browser smoke. These tests pin the contract over the mocked api.
 */

// ── Fixtures (real-shaped: only the frozen check types; raw-dossier findings) ──────────
const F5 = {
  currency: "SGD",
  boxes: { box_1_standard_rated_sales: 369589.97, box_8_net_gst: 12663.87 },
};

function mkFindings(code: string, n: number) {
  return Array.from({ length: n }, (_, i) => ({
    finding_id: `detect:${code}:${i + 1}`,
    check_id: code,
    finding_type: "deterministic",
  }));
}

// The canonical 21-finding SBODEMOSG set, mixed across the four real check types.
const ALL_FINDINGS = [
  ...mkFindings("E1", 8),
  ...mkFindings("NO_GST_REG", 7),
  ...mkFindings("E2", 5),
  ...mkFindings("gst_amount_mismatch", 1),
];

const AVAILABLE = {
  error_code: { E1: 8, NO_GST_REG: 7, E2: 5, gst_amount_mismatch: 1 },
  counterparty: { "SG Electronics": 2, "Far East Imports": 1 },
};

function runReviewResponse(data: Record<string, unknown>) {
  return {
    kind: "result",
    classifier_mode: "scripted",
    disclaimer: "Demo / illustrative — validation_status=unvalidated.",
    intent: "RUN_REVIEW",
    execution: {
      intent: "RUN_REVIEW",
      outcome: "executed",
      sequence: ["run_review_chain"],
      tiers: [1],
      params: { client_id: "sbodemosg", period: "2024Q3" },
      data,
      notes: [],
    },
  };
}

const FULL_REVIEW = runReviewResponse({
  dossiers: ALL_FINDINGS,
  findings: ALL_FINDINGS,
  f5_summary: F5,
  available_facets: AVAILABLE,
  remaining_facets: AVAILABLE,
  applied_filters: {},
  filter_rejection: null,
});

const E1_REVIEW = runReviewResponse({
  dossiers: ALL_FINDINGS, // the FULL canonical set is unchanged (Y)
  findings: mkFindings("E1", 8), // the narrowed VIEW (X)
  f5_summary: F5, // identical boxes — box-isolation
  available_facets: AVAILABLE, // the full menu always
  remaining_facets: { error_code: { E1: 8 }, counterparty: { "SG Electronics": 2 } },
  applied_filters: { error_code: ["E1"] },
  filter_rejection: null,
});

const REJECTION_REVIEW = runReviewResponse({
  dossiers: ALL_FINDINGS,
  findings: ALL_FINDINGS, // full rows still stand on a rejection
  f5_summary: F5,
  available_facets: AVAILABLE,
  remaining_facets: AVAILABLE,
  applied_filters: {},
  filter_rejection: {
    reason: "not_in_domain",
    facet: "error_code",
    value: "E9",
    domain: ["E1", "NO_GST_REG", "E2", "gst_amount_mismatch"],
    requested_filters: { error_code: ["E9"] },
    message:
      "value 'E9' is not in the 'error_code' domain; real values: ['E1', 'NO_GST_REG', 'E2', 'gst_amount_mismatch'].",
  },
});

const LEDGER_RESULT = {
  kind: "result",
  classifier_mode: "scripted",
  disclaimer: "Demo / illustrative.",
  intent: "SHOW_LEDGER",
  execution: {
    intent: "SHOW_LEDGER",
    outcome: "executed",
    sequence: ["read_ledger"],
    tiers: [0],
    params: { client_id: "sbodemosg", period: "2024Q3" },
    data: { ledger: [{ a: 1 }, { a: 2 }] }, // a read — NO facets
    notes: [],
  },
};

// fetch that routes by the request body's `filters` — mirrors the server seam: a filter in,
// a narrowed view out. Default RUN_REVIEW with no filter → the full set.
function reviewFetch() {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/command")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const ec = body.filters?.error_code;
      const wantsE1 = Array.isArray(ec) ? ec.includes("E1") : ec === "E1";
      return Promise.resolve(
        new Response(JSON.stringify(wantsE1 ? E1_REVIEW : FULL_REVIEW), { status: 200 })
      );
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

function staticFetch(payload: unknown) {
  return vi.fn(() => Promise.resolve(new Response(JSON.stringify(payload), { status: 200 })));
}

async function runReview() {
  fireEvent.click(screen.getByRole("button", { name: /Run a review/i }));
  await waitFor(() => expect(screen.getByText("21 of 21")).toBeInTheDocument());
}

describe("FacetFilter / CommandBar (T6.3 Slice 3b)", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("renders the data-derived facet menu with value:count from available_facets", async () => {
    vi.stubGlobal("fetch", reviewFetch());
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    await runReview();

    expect(screen.getByText(/Filter findings/i)).toBeInTheDocument();
    // Whatever keys available_facets carries — error_code AND counterparty, not hardcoded.
    expect(screen.getByText("error code")).toBeInTheDocument();
    expect(screen.getByText("counterparty")).toBeInTheDocument();

    // value:count chip — E1 with its count of 8 (from remaining = full when unfiltered).
    const e1 = screen.getByRole("button", { name: /E1/ });
    expect(within(e1).getByText("8")).toBeInTheDocument();
    // A counterparty value chip is present (data-derived, not hardcoded).
    expect(screen.getByRole("button", { name: /SG Electronics/ })).toBeInTheDocument();
  });

  it("a chip click re-POSTs /command with that filter and renders the narrowed view", async () => {
    const fetchMock = reviewFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    await runReview();
    expect(screen.getAllByText(/detect:/).length).toBe(21);

    fireEvent.click(screen.getByRole("button", { name: /E1/ }));

    // "X of Y shown" reflects findings (8) vs dossiers (21).
    await waitFor(() => expect(screen.getByText("8 of 21")).toBeInTheDocument());
    // The narrowed findings render (8 E1 rows; no NO_GST_REG/E2 rows).
    expect(screen.getAllByText(/detect:E1:/).length).toBe(8);
    expect(screen.queryByText(/detect:NO_GST_REG:/)).toBeNull();
    // The re-POST carried the filter (server does the filtering).
    const filteredCall = fetchMock.mock.calls.find((c) => {
      const b = JSON.parse(String((c[1] as RequestInit)?.body ?? "{}"));
      return b.filters && JSON.stringify(b.filters).includes("E1");
    });
    expect(filteredCall).toBeTruthy();
    // Active-filters display.
    expect(screen.getByText(/error_code=E1/)).toBeInTheDocument();
  });

  it("remaining_facets drive the post-filter chip counts (drill-down)", async () => {
    vi.stubGlobal("fetch", reviewFetch());
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    await runReview();
    fireEvent.click(screen.getByRole("button", { name: /E1/ }));
    await waitFor(() => expect(screen.getByText("8 of 21")).toBeInTheDocument());

    // E1 still counts 8 over the narrowed view; E2 drops to 0 (not in the view).
    expect(within(screen.getByRole("button", { name: /E1/ })).getByText("8")).toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: /E2/ })).getByText("0")).toBeInTheDocument();
  });

  it("clear-filters resets to the full view (re-POST filters={})", async () => {
    vi.stubGlobal("fetch", reviewFetch());
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    await runReview();
    fireEvent.click(screen.getByRole("button", { name: /E1/ }));
    await waitFor(() => expect(screen.getByText("8 of 21")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Clear filters/i }));
    await waitFor(() => expect(screen.getByText("21 of 21")).toBeInTheDocument());
    expect(screen.queryByText(/error_code=E1/)).toBeNull();
  });

  it("the F5 summary is unchanged under a filter (box-isolation, visible)", async () => {
    vi.stubGlobal("fetch", reviewFetch());
    const { container } = render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    await runReview();
    const f5Before = container.querySelector(".cmd-f5")!.textContent;

    fireEvent.click(screen.getByRole("button", { name: /E1/ }));
    await waitFor(() => expect(screen.getByText("8 of 21")).toBeInTheDocument());
    const f5After = container.querySelector(".cmd-f5")!.textContent;

    expect(f5After).toBe(f5Before);
    expect(f5Before).toContain("12,663.87"); // the real box_8 net GST
  });

  it("renders filter_rejection as an honest message (never a silent empty / crash)", async () => {
    vi.stubGlobal("fetch", staticFetch(REJECTION_REVIEW));
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    fireEvent.click(screen.getByRole("button", { name: /Run a review/i }));

    await waitFor(() =>
      expect(screen.getByText(/is not in the 'error_code' domain/i)).toBeInTheDocument()
    );
    // The full rows still stand alongside the rejection (not an empty set).
    expect(screen.getByText("21 of 21")).toBeInTheDocument();
  });

  it("shows NO facet panel for a SHOW_LEDGER (read) result", async () => {
    vi.stubGlobal("fetch", staticFetch(LEDGER_RESULT));
    render(<CommandBar clientId="sbodemosg" period="2024Q3" />);
    fireEvent.click(screen.getByRole("button", { name: /Show ledger/i }));

    await waitFor(() =>
      expect(screen.getByText(/Justification ledger/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/Filter findings/i)).toBeNull();
  });
});
