import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import type { ReviewPayload } from "../api";
import { App } from "../App";

/**
 * Phase-2 (T6.3 Slice 4) — facets RELOCATED onto the review queue, still SERVER-DRIVEN.
 *
 * The facet model is unchanged from T6.3 (agent/facets.py: error_code / counterparty / doc_num;
 * OR-within-a-facet, AND-across-facets; drill-down counts from the server's `remaining_facets`).
 * Only the UI placement moves: the existing FacetFilter now sits under the queue tabs, fed by a
 * RUN_REVIEW POST /command that App fires (the same endpoint, no new backend). A chip click
 * re-POSTs /command with that filter — the SERVER does the filtering; the browser never filters
 * client-side and never recomputes a count. The queue rows are the rich GET /review items
 * narrowed to the finding_ids the server returns (a join over the shared finding_id space).
 * Filtering the queue NEVER changes an F5 box value (box-isolation, preserved).
 */

// A 3-item needs-review fixture (all in one tab) so narrowing is observable in the list.
const REVIEW: ReviewPayload = {
  client: { client_id: "sbodemosg", client_name: "SAP B1 Demo (SBODEMOSG)", company_db: "SBODEMOSG" },
  period: { start: "2024-07-01", end: "2024-09-30", label: "2024Q3" },
  validation_status: "unvalidated",
  f5_summary: { currency: "SGD", boxes: { box_1_standard_rated_sales: 369589.97, box_8_net_gst: 12663.87 } },
  disclaimer: "AgentAssist flags — you decide. validation_status=unvalidated.",
  queue: [
    mkQueueItem("detect:E1:958", "E1", "SG Electronics", 958),
    mkQueueItem("detect:E2:101", "E2", "SG Electronics", 101),
    mkQueueItem("detect:NO_GST_REG:592", "NO_GST_REG", "Far East Imports", 592),
  ],
};

function mkQueueItem(finding_id: string, check_id: string, vendor: string, doc_num: number) {
  return {
    finding_id,
    check_id,
    finding_type: "deterministic",
    group: "needs_review" as const,
    vendor,
    severity: "MEDIUM",
    description: `desc for ${check_id}`,
    recommendation: "—",
    doc_num,
    doc_date: "2024-07-02",
    error_code: check_id,
    display_name: `Finding ${check_id}`,
    iras_basis: "IRAS basis",
    iras_basis_caveat: "Illustrative citation — the IRAS basis shown is itself UNVALIDATED.",
    demoted: false,
    annotation: null,
    prior_dispositions: [],
    fingerprint: null,
    candidate_framing_text: "Candidate for review.",
    completeness: { required: [], present: [], missing: [], satisfied: true },
    inputs_hash: "sha256:x",
    proposal_id: null,
    proposal_status: null,
    validation_status: "unvalidated",
  };
}

// The full, unfiltered finding set the server faceting works over (raw dossier rows).
const ALL = [
  { finding_id: "detect:E1:958", check_id: "E1", finding_type: "deterministic", counterparty: "SG Electronics" },
  { finding_id: "detect:E2:101", check_id: "E2", finding_type: "deterministic", counterparty: "SG Electronics" },
  { finding_id: "detect:NO_GST_REG:592", check_id: "NO_GST_REG", finding_type: "deterministic", counterparty: "Far East Imports" },
];

const F5 = REVIEW.f5_summary;

function countBy(rows: typeof ALL, key: "check_id" | "counterparty") {
  const out: Record<string, number> = {};
  for (const r of rows) out[r[key]] = (out[r[key]] ?? 0) + 1;
  return out;
}

const AVAILABLE = { error_code: countBy(ALL, "check_id"), counterparty: countBy(ALL, "counterparty") };

// Emulate the server seam: narrow ALL by `filters` (OR-within-facet, AND-across-facets) and
// recompute remaining counts over the narrowed set. The CLIENT does none of this — it only
// sends the filter request and renders what comes back.
function runReviewFor(filters: Record<string, string | string[]>) {
  const norm = (v: string | string[]) => (Array.isArray(v) ? v : [v]);
  const narrowed = ALL.filter((row) =>
    Object.entries(filters).every(([facet, v]) => {
      const allowed = norm(v);
      const field = facet === "error_code" ? row.check_id : row.counterparty;
      return allowed.includes(field);
    })
  );
  return {
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
        dossiers: ALL,
        f5_summary: F5,
        available_facets: AVAILABLE,
        findings: narrowed,
        remaining_facets: { error_code: countBy(narrowed, "check_id"), counterparty: countBy(narrowed, "counterparty") },
        applied_filters: filters,
        filter_rejection: null,
      },
      notes: [],
    },
  };
}

function mockFetch() {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/review/")) {
      return Promise.resolve(new Response(JSON.stringify(REVIEW), { status: 200 }));
    }
    if (url.includes("/audit")) {
      return Promise.resolve(new Response(JSON.stringify({ entries: [] }), { status: 200 }));
    }
    if (url.includes("/command")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve(new Response(JSON.stringify(runReviewFor(body.filters ?? {})), { status: 200 }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

async function gotoFindings() {
  const nav = await screen.findByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: /Findings/i }));
}
async function gotoReview() {
  const nav = await screen.findByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: /Review/i }));
}

describe("Queue facets (T6.3 Slice 4) — server-driven, relocated onto the queue", () => {
  beforeEach(() => vi.stubGlobal("fetch", mockFetch()));
  afterEach(() => vi.restoreAllMocks());

  it("renders the data-derived facet menu under the queue tabs with server drill-down counts", async () => {
    render(<App />);
    await gotoFindings();

    const panel = await screen.findByLabelText(/Filter findings/i);
    // Data-derived facet names (NOT hardcoded Severity/Check/Type — the server's real facets).
    expect(within(panel).getByText(/error code/i)).toBeInTheDocument();
    expect(within(panel).getByText(/counterparty/i)).toBeInTheDocument();
    // value:count chips, count from the server's remaining_facets.
    expect(within(within(panel).getByRole("button", { name: /^E1/ })).getByText("1")).toBeInTheDocument();
    expect(within(within(panel).getByRole("button", { name: /SG Electronics/ })).getByText("2")).toBeInTheDocument();
    // "N of M shown" — the server findings (3) of the full set (3).
    expect(screen.getByText(/3 of 3 shown/i)).toBeInTheDocument();
  });

  it("a chip click re-POSTs /command with that filter and the SERVER-narrowed rows render", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await gotoFindings();

    const panel = await screen.findByLabelText(/Filter findings/i);
    fireEvent.click(within(panel).getByRole("button", { name: /^E1/ }));

    await waitFor(() => expect(screen.getByText(/1 of 3 shown/i)).toBeInTheDocument());
    // The narrowed view: only the E1 row stands in the queue list (E2 / NO_GST_REG drop out).
    const list = document.querySelector(".queue-list")!;
    expect(within(list as HTMLElement).getByText("E1")).toBeInTheDocument();
    expect(within(list as HTMLElement).queryByText("E2")).toBeNull();
    expect(within(list as HTMLElement).queryByText("NO_GST_REG")).toBeNull();
    // The re-POST carried the filter (server does the filtering, not the browser).
    const filtered = fetchMock.mock.calls.find((c) => {
      const b = JSON.parse(String((c[1] as RequestInit)?.body ?? "{}"));
      return b.filters && JSON.stringify(b.filters).includes("E1");
    });
    expect(filtered).toBeTruthy();
  });

  it("drill-down counts come from remaining_facets — a chip can read 0", async () => {
    render(<App />);
    await gotoFindings();
    const panel = await screen.findByLabelText(/Filter findings/i);
    fireEvent.click(within(panel).getByRole("button", { name: /^E1/ }));
    await waitFor(() => expect(screen.getByText(/1 of 3 shown/i)).toBeInTheDocument());

    const panel2 = screen.getByLabelText(/Filter findings/i);
    expect(within(within(panel2).getByRole("button", { name: /^E1/ })).getByText("1")).toBeInTheDocument();
    expect(within(within(panel2).getByRole("button", { name: /^E2/ })).getByText("0")).toBeInTheDocument();
  });

  it("builds OR-within-a-facet (array) and AND-across-facets (multiple keys) filter REQUESTS", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await gotoFindings();
    const panel = await screen.findByLabelText(/Filter findings/i);

    // OR within error_code: E1 then E2 → one facet, two values.
    fireEvent.click(within(panel).getByRole("button", { name: /^E1/ }));
    await waitFor(() => expect(screen.getByText(/1 of 3 shown/i)).toBeInTheDocument());
    fireEvent.click(within(screen.getByLabelText(/Filter findings/i)).getByRole("button", { name: /^E2/ }));
    await waitFor(() => expect(screen.getByText(/2 of 3 shown/i)).toBeInTheDocument());

    const lastBody = (m: typeof fetchMock) => m.mock.calls[m.mock.calls.length - 1][1] as RequestInit;
    const last = JSON.parse(String(lastBody(fetchMock).body));
    expect(last.filters.error_code).toEqual(expect.arrayContaining(["E1", "E2"]));

    // AND across facets: add a counterparty value → a second facet key in the request.
    fireEvent.click(within(screen.getByLabelText(/Filter findings/i)).getByRole("button", { name: /SG Electronics/ }));
    await waitFor(() => {
      const b = JSON.parse(String(lastBody(fetchMock).body));
      expect(b.filters.error_code).toBeTruthy();
      expect(b.filters.counterparty).toBeTruthy();
    });
  });

  it("filtering the queue NEVER changes an F5 box value (box-isolation, preserved)", async () => {
    render(<App />);
    // F5 box value is shown on the Review screen (GET /review, box-isolated).
    expect(await screen.findByText("12,663.87")).toBeInTheDocument();
    const f5Before = document.querySelector(".f5-table")!.textContent;

    await gotoFindings();
    const panel = await screen.findByLabelText(/Filter findings/i);
    fireEvent.click(within(panel).getByRole("button", { name: /^E1/ }));
    await waitFor(() => expect(screen.getByText(/1 of 3 shown/i)).toBeInTheDocument());

    await gotoReview();
    const f5After = document.querySelector(".f5-table")!.textContent;
    expect(f5After).toBe(f5Before);
    expect(f5After).toContain("12,663.87");
  });

  it("Clear resets to the full view (re-POST filters={})", async () => {
    render(<App />);
    await gotoFindings();
    const panel = await screen.findByLabelText(/Filter findings/i);
    fireEvent.click(within(panel).getByRole("button", { name: /^E1/ }));
    await waitFor(() => expect(screen.getByText(/1 of 3 shown/i)).toBeInTheDocument());

    fireEvent.click(within(screen.getByLabelText(/Filter findings/i)).getByRole("button", { name: /Clear/i }));
    await waitFor(() => expect(screen.getByText(/3 of 3 shown/i)).toBeInTheDocument());
    const list = document.querySelector(".queue-list")!;
    expect(within(list as HTMLElement).getByText("E2")).toBeInTheDocument();
  });
});
