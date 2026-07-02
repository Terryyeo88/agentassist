import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * Xero → shared central review screen (BUILD 2, A1) — FAILING-FIRST.
 *
 * The defect: a real Xero F5 upload computes findings server-side, but the panel dropped
 * them (coverage-only). A1 reshapes the response to carry `queue: QueueItem[]` and the panel
 * mounts the shared <ReviewScreen> (review-only — no sign store for uploads).
 *
 *   FT1  — a xero_f5_upload response with a queue renders findings AS CANDIDATES.
 *   FT2  — Decision-4 honesty: an absent companion sheet surfaces the degraded/unavailable
 *          coverage status AND fabricates NO finding into the queue.
 *   caveat — the Xero QueueItem carries the constant iras_basis_caveat, so FindingDetail's
 *          no-fallback caveat line never renders bare on the Xero path.
 */

// A real-FORMAT Xero E2 finding, projected to the shared QueueItem shape by the backend.
const XERO_E2: QueueItem = {
  finding_id: "detect:E2:INV-2003",
  check_id: "E2",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "Overseas Buyer Pte Ltd",
  severity: null,
  description: "Tax 700.00 charged on non-taxable supply (VatGroup=ZR)",
  recommendation: null,
  doc_num: "INV-2003" as unknown as number,
  doc_date: "2026-05-11",
  error_code: "E2",
  display_name: "GST charged on a non-taxable (zero-rated) supply",
  iras_basis: "IRAS e-Tax Guide — zero-rated supplies (registry citation)",
  iras_basis_caveat: "Illustrative citation — the IRAS basis shown is itself UNVALIDATED.",
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: null,
  candidate_framing_text: "",
  completeness: { required: [], present: [], missing: [], satisfied: false },
  inputs_hash: "—",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

const DISCLAIMER =
  "Real-Xero-FORMAT findings over synthetic data — validation_status=unvalidated; candidates not verdicts.";

// The reshaped xero_f5_upload body: queue REPLACES the flat findings; dark checks live only
// in coverage_status (NO_GST_REG unavailable — no supplier master), never as a queue finding.
const XERO_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer: DISCLAIMER,
  coverage_status: [
    {
      check: "NO_GST_REG",
      level: "unavailable",
      reason: "FederalTaxID absent — NO_GST_REG cannot run; require supplier-master sheet at onboarding.",
    },
    { check: "E2", level: "full", reason: "" },
  ],
  queue: [XERO_E2],
};

function xeroFetch(body: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload")) return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    // The Xero path must NEVER hit the B1 review GET or /command.
    if (url.includes("/command")) return Promise.reject(new Error(`Xero must not POST /command: ${url}`));
    if (url.includes("/review/")) return Promise.reject(new Error(`Xero must not GET the B1 review: ${url}`));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

async function uploadA() {
  const input =
    (screen.queryByLabelText(/upload .* export/i) as HTMLInputElement | null) ??
    (document.querySelector("input[type=file]") as HTMLInputElement | null);
  expect(input).not.toBeNull();
  const file = new File([new Uint8Array([1, 2, 3])], "AgentAssist_IRAS_F5.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  Object.defineProperty(input as HTMLInputElement, "files", { value: [file] });
  fireEvent.change(input as HTMLInputElement);
}

describe("Xero → shared central review screen (BUILD 2 A1)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("FT1: a xero_f5_upload response with findings renders them as candidates", async () => {
    vi.stubGlobal("fetch", xeroFetch(XERO_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadA();

    // The finding renders through the shared screen, framed as a candidate.
    expect(await screen.findByText(/candidate for review only/i)).toBeInTheDocument();
    expect(await screen.findByText(/AgentAssist flags/i)).toBeInTheDocument();
    expect(await screen.findByText(XERO_E2.display_name!)).toBeInTheDocument();
    // Review-only (no sign store for uploads) — no dead sign/decision controls.
    expect(screen.queryByRole("button", { name: /Sign working paper/i })).toBeNull();
    expect(screen.getByText(/sign-off for uploads not yet available/i)).toBeInTheDocument();
  });

  it("caveat: the Xero QueueItem supplies the constant iras_basis_caveat (never bare)", async () => {
    vi.stubGlobal("fetch", xeroFetch(XERO_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadA();
    expect(await screen.findByText(/Illustrative citation/i)).toBeInTheDocument();
  });

  it("FT2: absent companion sheet surfaces degraded coverage AND fabricates no finding", async () => {
    vi.stubGlobal("fetch", xeroFetch(XERO_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadA();

    // Half 1 — the degraded/unavailable coverage status is SURFACED (with its reason).
    await waitFor(() => expect(screen.getAllByText(/unavailable/i).length).toBeGreaterThan(0));
    expect(screen.getByText(/FederalTaxID absent/i)).toBeInTheDocument();

    // Half 2 — the T2.11-adjacent proof: NO_GST_REG appears ONLY in coverage, never as a
    // fabricated queue finding. Scope the assertion to the queue list.
    const list = document.querySelector(".queue-list") as HTMLElement | null;
    expect(list).not.toBeNull();
    expect(within(list as HTMLElement).queryByText(/NO_GST_REG/)).toBeNull();
    // The one real finding IS present in the queue.
    expect(within(list as HTMLElement).getByText("E2")).toBeInTheDocument();
  });
});
