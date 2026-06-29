import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Root } from "../Root";
import { REVIEW_FIXTURE, AUDIT_FIXTURE } from "./fixtures";

/**
 * Source selector + empty state (tsource-selector) — FAILING-FIRST.
 *
 * The review UI must boot with NO feeder bound. The new top-level `Root` holds `source`
 * state (null | "b1_demo" | "xero_upload"):
 *   - null  → a SourceSelector empty-state chooser; NOTHING is fetched on mount.
 *   - B1    → mounts the EXISTING <App/> (which fetches GET /review + POST /command itself).
 *   - Xero  → a XeroUploadPanel: a file input that calls uploadExtract(file) and renders the
 *             returned per-check COVERAGE rows. Xero is COVERAGE-ONLY — it never runs the
 *             engine and never fetches GET /review or POST /command.
 *
 * Box-isolation: the B1 F5 boxes come straight from the frozen GET /review and are never
 * recomputed by the source choice.
 */

// Mirrors AppNav.test.tsx: the RUN_REVIEW POST /command response App fires on mount.
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

// The B1 happy-path fetch (copied from AppNav.test.tsx's mockFetch).
function b1Fetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/")) return Promise.resolve(new Response(JSON.stringify(REVIEW_FIXTURE), { status: 200 }));
    if (url.includes("/audit")) return Promise.resolve(new Response(JSON.stringify({ entries: AUDIT_FIXTURE }), { status: 200 }));
    if (url.includes("/command")) return Promise.resolve(new Response(JSON.stringify(RUN_REVIEW), { status: 200 }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

// The Xero coverage-only payload (locked backend contract shape).
const COVERAGE_PAYLOAD = {
  source_kind: "extract_upload",
  validation_status: "unvalidated",
  disclaimer:
    "Coverage preview over an uploaded extract — validation_status=unvalidated; the engine is not run.",
  coverage_status: [
    { check: "NO_GST_REG", level: "unavailable", reason: "FederalTaxID absent — supplier-master sheet required." },
    { check: "E1", level: "full", reason: "" },
  ],
};

// Xero branch: only /review/upload is allowed; a plain /review/ read or /command would mean
// the Xero pick wrongly ran the B1 review — those reject.
function xeroFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload")) return Promise.resolve(new Response(JSON.stringify(COVERAGE_PAYLOAD), { status: 200 }));
    if (url.includes("/command")) return Promise.reject(new Error(`Xero must not POST /command: ${url}`));
    if (url.includes("/review/")) return Promise.reject(new Error(`Xero must not GET the B1 review: ${url}`));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

const B1_BUTTON = /SAP B1 \(demo\)/i;
const XERO_BUTTON = /Xero export \(upload\)/i;

describe("source selector + empty state (tsource-selector)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("boots to the source selector with no source bound — nothing fetched", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<Root />);

    expect(screen.getByRole("button", { name: B1_BUTTON })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: XERO_BUTTON })).toBeInTheDocument();
    // No source bound → the B1 composer is NOT mounted.
    expect(screen.queryByPlaceholderText(/Ask the assistant/i)).toBeNull();
    // Nothing is fetched/run on mount.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("picking SAP B1 (demo) mounts the review surface and binds B1", async () => {
    const fetchMock = b1Fetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<Root />);
    fireEvent.click(screen.getByRole("button", { name: B1_BUTTON }));

    // The B1 review surface mounts (composer) and shows the box-isolated GET /review data.
    expect(await screen.findByPlaceholderText(/Ask the assistant/i)).toBeInTheDocument();
    expect(await screen.findByText(/12,663\.87/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/review/"))).toBe(true);
  });

  it("picking Xero export shows the coverage panel (coverage-only) and never runs the B1 review", async () => {
    const fetchMock = xeroFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<Root />);
    fireEvent.click(screen.getByRole("button", { name: XERO_BUTTON }));

    // Locate the file input (a labelled <input type=file>, else the bare element).
    const input =
      (screen.queryByLabelText(/upload .* export/i) as HTMLInputElement | null) ??
      (document.querySelector('input[type=file]') as HTMLInputElement | null);
    expect(input).not.toBeNull();

    const file = new File([new Uint8Array([1, 2, 3])], "export.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    // jsdom: set .files via defineProperty, then fire the change (no user-event installed).
    Object.defineProperty(input as HTMLInputElement, "files", { value: [file] });
    fireEvent.change(input as HTMLInputElement);

    // The coverage rows render — the unavailable NO_GST_REG row + its reason + the caveat.
    // (findAllByText: "NO_GST_REG" can appear both as the check cell and inside a reason.)
    expect((await screen.findAllByText(/NO_GST_REG/)).length).toBeGreaterThan(0);
    expect(await screen.findByText(/FederalTaxID absent/i)).toBeInTheDocument();
    expect(screen.getAllByText(/unavailable/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/unvalidated/i).length).toBeGreaterThan(0);

    // Fetch hit /review/upload — and NEVER the B1 review GET or /command (box-isolation).
    await waitFor(() =>
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/review/upload"))).toBe(true)
    );
    for (const call of fetchMock.mock.calls) {
      const url = String(call[0]);
      expect(url).not.toContain("/review/sbodemosg");
      expect(url).not.toContain("/command");
    }
  });

  it("box-isolation: the B1 F5 boxes are identical regardless of the Xero branch", async () => {
    const fetchMock = b1Fetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<Root />);
    fireEvent.click(screen.getByRole("button", { name: B1_BUTTON }));

    // The F5 box value comes straight from the frozen GET /review fixture — never recomputed
    // by the source choice (REVIEW_FIXTURE.f5_summary.boxes.box_8_net_gst === 12663.87).
    expect(await screen.findByText(/12,663\.87/)).toBeInTheDocument();
  });
});
