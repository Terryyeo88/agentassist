import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * Xero upload panel adjudication + F5-only sign (B3a-2) -- FAILING-FIRST.
 *
 * Written BEFORE the implementation; MUST fail today for the RIGHT reason -- XeroUploadPanel
 * mounts <ReviewScreen> WITHOUT an adjudication prop (review-only note only), exposes NO
 * panel-local "Reviewer of record" input, and shows NO sign control anywhere. B3a-2 gives the
 * panel ReviewScreen's adjudication capability: decisions POST /api/decision under a frontend
 * source_kind -> client_id map (xero_f5_upload -> xero_demo, extract_review -> extract_demo,
 * xero_sales_upload -> xero_sales_demo), attributed to the panel-local reviewer of record, then
 * re-upload the retained File to re-apply the persisted demotion. The "Sign working paper"
 * control is gated to source_kind === "xero_f5_upload" ONLY (POST /sign/upload is F5-only).
 *
 * THREE-TIMES RULE: the "panel persists decisions under the source_kind->client_id map + the
 * reviewer of record, then re-applies; sign is F5-only" contract is pinned in the panel spec,
 * will be enforced in XeroUploadPanel code, and is asserted here.
 *
 *   C1 -- F5 upload -> enter reviewer, Mark known + note, record -> POST /api/decision with
 *         {client_id: "xero_demo", fingerprint, action, note, reviewer_name}, then a follow-up
 *         re-upload POST to /review/upload (re-apply). FAILS TODAY (no reviewer input, no
 *         decision POST wired).
 *   C2 -- xero_sales_upload response -> NO "Sign working paper" button (sign is F5-only).
 *   C3 -- xero_f5_upload response -> "Sign working paper" button present. FAILS TODAY (no sign
 *         control on the panel at all).
 */

const FP = "sha256:265e9b4e92baa689143df7f1384560a0f337d325105d38c8499c6595c42b159e";

function fingerprintedRow(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    finding_id: "detect:E4:BILL-3002",
    check_id: "E4",
    finding_type: "deterministic",
    group: "needs_review",
    vendor: "OldRate Supplies Pte Ltd",
    severity: "MEDIUM",
    description: "Stale GST rate applied among 9% peers.",
    recommendation: "Confirm the applicable rate for this supply.",
    doc_num: "BILL-3002" as unknown as number,
    doc_date: "2026-05-11",
    error_code: "E4",
    display_name: "Stale GST rate applied",
    iras_basis: "IRAS e-Tax Guide -- GST rate (registry citation).",
    iras_basis_caveat: "Illustrative citation -- the IRAS basis shown is itself UNVALIDATED.",
    demoted: false,
    annotation: null,
    prior_dispositions: [],
    fingerprint: FP,
    candidate_framing_text: "Candidate for review only.",
    completeness: { required: [], present: [], missing: [], satisfied: false },
    inputs_hash: "-",
    proposal_id: null,
    proposal_status: null,
    validation_status: "unvalidated",
    ...overrides,
  };
}

function uploadBody(source_kind: string): unknown {
  return {
    source_kind,
    validation_status: "unvalidated",
    disclaimer: "Real-Xero-FORMAT findings over synthetic data -- validation_status=unvalidated.",
    coverage_status: [{ check: "E4", level: "full", reason: "" }],
    queue: [fingerprintedRow()],
    ...(source_kind === "xero_sales_upload" ? { config_scope: "xero_sales_demo" } : {}),
  };
}

const DECISION_RESPONSE = {
  client_id: "xero_demo",
  finding_id: "detect:E4:BILL-3002",
  action: "Mark known",
  disposition: "KNOWN_ACCEPTED",
  fingerprint: FP,
  entry_id: "b986d57f",
  entry_hash: "sha256:def",
  chain_length: 1,
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags -- you decide.",
};

function panelFetch(body: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    // Order matters: /decision is checked before the generic /review/upload.
    if (url.includes("/decision"))
      return Promise.resolve(new Response(JSON.stringify(DECISION_RESPONSE), { status: 200 }));
    if (url.includes("/review/upload"))
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    // The panel must NEVER hit the B1 review GET or /command (box-isolation).
    if (url.includes("/command")) return Promise.reject(new Error(`panel must not POST /command: ${url}`));
    if (url.includes("/review/")) return Promise.reject(new Error(`panel must not GET the B1 review: ${url}`));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

async function uploadPrimary() {
  const input =
    (screen.queryByLabelText(/upload .* export/i) as HTMLInputElement | null) ??
    (document.querySelector("input.xero-file-input:not(.xero-ledger-input)") as HTMLInputElement | null);
  expect(input).not.toBeNull();
  const file = new File([new Uint8Array([1, 2, 3])], "AgentAssist_IRAS_F5.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  Object.defineProperty(input as HTMLInputElement, "files", { value: [file] });
  fireEvent.change(input as HTMLInputElement);
}

describe("Xero upload panel adjudication (B3a-2)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("C1: records a decision under client_id xero_demo + reviewer of record, then re-applies", async () => {
    const fetchMock = panelFetch(uploadBody("xero_f5_upload"));
    vi.stubGlobal("fetch", fetchMock);

    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    // The finding renders through the shared screen.
    expect(await screen.findByText("Stale GST rate applied")).toBeInTheDocument();

    // Enter the panel-local reviewer of record (FAILS TODAY: no such input on the panel).
    const reviewer = await screen.findByLabelText(/reviewer of record/i);
    fireEvent.change(reviewer, { target: { value: "Collin Tan" } });

    // Choose "Mark known" (requires a note) and record.
    fireEvent.click(await screen.findByRole("button", { name: /Mark known/i }));
    const note = await screen.findByPlaceholderText(/required for/i);
    fireEvent.change(note, { target: { value: "Standing accepted treatment for this supplier." } });
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));

    // A single decision POST fired with the mapped client_id, the row's fingerprint, the
    // action, the note, and the entered reviewer name.
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/decision"));
      expect(call).toBeTruthy();
    });
    const decisionCall = fetchMock.mock.calls.find(([u]) =>
      String(u).includes("/decision")
    )! as unknown as [string, RequestInit];
    const decisionBody = JSON.parse(decisionCall[1].body as string);
    expect(decisionBody.client_id).toBe("xero_demo");
    expect(decisionBody.fingerprint).toBe(FP);
    expect(decisionBody.action).toBe("Mark known");
    expect(decisionBody.note).toBe("Standing accepted treatment for this supplier.");
    expect(decisionBody.reviewer_name).toBe("Collin Tan");

    // Re-apply: the retained File is re-uploaded (>= 2 POSTs to /review/upload -- initial + re-apply).
    await waitFor(() => {
      const uploads = fetchMock.mock.calls.filter(([u]) => String(u).includes("/review/upload"));
      expect(uploads.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("C2: a xero_sales_upload response shows NO sign control (sign is F5-only)", async () => {
    vi.stubGlobal("fetch", panelFetch(uploadBody("xero_sales_upload")));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    expect(await screen.findByText("Stale GST rate applied")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Sign working paper/i })).toBeNull();
  });

  it("C3: a xero_f5_upload response shows the sign control", async () => {
    vi.stubGlobal("fetch", panelFetch(uploadBody("xero_f5_upload")));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    // FAILS TODAY: the panel exposes no sign control on any source_kind.
    expect(await screen.findByRole("button", { name: /Sign working paper/i })).toBeInTheDocument();
  });
});
