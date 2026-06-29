import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { App } from "../App";
import type { ReviewPayload } from "../api";
import { FacetFilter } from "../components/FacetFilter";

/**
 * FacetFilter — REWRITTEN for T6.3 Slice 4 (facets relocated onto the queue, still SERVER-DRIVEN).
 *
 * The first block pins the FacetFilter CONTRACT directly: the menu is data-derived and
 * source-agnostic (no hardcoded Severity/Check/Type), the chip count is the SERVER's
 * `remaining_facets` drill-down (a chip can read 0), the selected state is the SERVER-echoed
 * selection (OR-within-a-facet = several pressed chips in one facet), and a chip click is a
 * REQUEST (onToggle) — the component never filters locally. The final test asserts the
 * relocation: the same FacetFilter now renders on the Findings queue, not the command result.
 */

describe("FacetFilter contract (server-driven, drill-down)", () => {
  const base = {
    available: {
      error_code: { E1: 8, NO_GST_REG: 7, E2: 5 },
      counterparty: { "SG Electronics": 2 },
      proposal_status: { staged: 0 }, // a future facet — proves nothing is hardcoded
    },
    remaining: {
      error_code: { E1: 8, NO_GST_REG: 0, E2: 0 },
      counterparty: { "SG Electronics": 2 },
      proposal_status: { staged: 0 },
    },
    onToggle: vi.fn(),
    onClear: vi.fn(),
    busy: false,
  };

  it("renders whatever facets `available` carries — source-agnostic, not hardcoded", () => {
    render(<FacetFilter {...base} selected={{}} />);
    expect(screen.getByText(/error code/i)).toBeInTheDocument();
    expect(screen.getByText(/counterparty/i)).toBeInTheDocument();
    expect(screen.getByText(/proposal status/i)).toBeInTheDocument();
  });

  it("chip counts come from `remaining_facets` (drill-down) — a chip can read 0", () => {
    render(<FacetFilter {...base} selected={{ error_code: ["E1"] }} />);
    expect(within(screen.getByRole("button", { name: /^E1/ })).getByText("8")).toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: /^E2/ })).getByText("0")).toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: /NO_GST_REG/ })).getByText("0")).toBeInTheDocument();
  });

  it("selection is the SERVER echo (OR-within-a-facet = multiple pressed in one facet)", () => {
    render(<FacetFilter {...base} selected={{ error_code: ["E1", "E2"] }} />);
    expect(screen.getByRole("button", { name: /^E1/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^E2/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /NO_GST_REG/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("a chip click is a REQUEST (onToggle), Clear calls onClear, and never filters locally", () => {
    const onToggle = vi.fn();
    const onClear = vi.fn();
    render(<FacetFilter {...base} selected={{ error_code: ["E1"] }} onToggle={onToggle} onClear={onClear} />);
    fireEvent.click(screen.getByRole("button", { name: /^E2/ }));
    expect(onToggle).toHaveBeenCalledWith("error_code", "E2");
    fireEvent.click(screen.getByRole("button", { name: /Clear/i }));
    expect(onClear).toHaveBeenCalled();
  });

  it("Clear is shown only when a selection is active", () => {
    const { rerender } = render(<FacetFilter {...base} selected={{}} />);
    expect(screen.queryByRole("button", { name: /Clear/i })).toBeNull();
    rerender(<FacetFilter {...base} selected={{ error_code: ["E1"] }} />);
    expect(screen.getByRole("button", { name: /Clear/i })).toBeInTheDocument();
  });

  it("renders nothing when there are no facets", () => {
    const { container } = render(<FacetFilter {...base} available={{}} remaining={{}} selected={{}} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("FacetFilter placement (relocated onto the queue)", () => {
  const REVIEW: ReviewPayload = {
    client: { client_id: "sbodemosg", client_name: "SAP B1 Demo", company_db: "SBODEMOSG" },
    period: { start: "2024-07-01", end: "2024-09-30", label: "2024Q3" },
    validation_status: "unvalidated",
    f5_summary: { currency: "SGD", boxes: { box_8_net_gst: 12663.87 } },
    disclaimer: "validation_status=unvalidated.",
    queue: [
      {
        finding_id: "detect:E1:958", check_id: "E1", finding_type: "deterministic", group: "needs_review",
        vendor: "SG Electronics", severity: "MEDIUM", description: "d", recommendation: "r", doc_num: 958,
        doc_date: "2024-07-02", error_code: "E1", display_name: "E1", iras_basis: "b",
        iras_basis_caveat: "Illustrative citation — UNVALIDATED.", demoted: false, annotation: null,
        prior_dispositions: [], fingerprint: null, candidate_framing_text: "c",
        completeness: { required: [], present: [], missing: [], satisfied: true }, inputs_hash: "h",
        proposal_id: null, proposal_status: null, validation_status: "unvalidated",
      },
    ],
  };
  const RUN_REVIEW = {
    kind: "result", classifier_mode: "scripted", disclaimer: "never writes back to SAP.", intent: "RUN_REVIEW",
    execution: {
      intent: "RUN_REVIEW", outcome: "executed", sequence: [], tiers: [1], params: {},
      data: {
        review_result: {}, dossiers: [{ finding_id: "detect:E1:958", check_id: "E1", finding_type: "deterministic" }],
        f5_summary: REVIEW.f5_summary, available_facets: { error_code: { E1: 1 } },
        findings: [{ finding_id: "detect:E1:958", check_id: "E1", finding_type: "deterministic" }],
        remaining_facets: { error_code: { E1: 1 } }, applied_filters: {}, filter_rejection: null,
      },
      notes: [],
    },
  };

  beforeEach(() =>
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/review/")) return Promise.resolve(new Response(JSON.stringify(REVIEW), { status: 200 }));
        if (url.includes("/audit")) return Promise.resolve(new Response(JSON.stringify({ entries: [] }), { status: 200 }));
        if (url.includes("/command")) return Promise.resolve(new Response(JSON.stringify(RUN_REVIEW), { status: 200 }));
        return Promise.reject(new Error(`unexpected fetch: ${url}`));
      })
    )
  );
  afterEach(() => vi.restoreAllMocks());

  it("the facet menu lives on the Findings queue, NOT in the command result", async () => {
    render(<App />);
    await screen.findByAltText(/AgentAssist/i);
    // Not on the Review home.
    expect(screen.queryByLabelText(/Filter findings/i)).toBeNull();

    const navEl = screen.getByRole("navigation", { name: /Primary/i });
    fireEvent.click(within(navEl).getByRole("button", { name: /Findings/i }));
    expect(await screen.findByLabelText(/Filter findings/i)).toBeInTheDocument();
  });
});
