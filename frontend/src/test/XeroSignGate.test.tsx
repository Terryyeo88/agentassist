import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * Xero sign-gate regression fix — FAILING-FIRST.
 *
 * Written BEFORE the implementation; MUST fail today for the RIGHT reason.
 *
 * REGRESSION (landed in PR #155, "Xero shell parity"): the shared <TopBar> reviewer pill is
 * wired to `onOpenSign` UNCONDITIONALLY at XeroUploadPanel's TopBar call site, while the
 * pre-existing in-panel ReviewScreen path deliberately gates the same action on `canSign`
 * (`coverage?.source_kind === "xero_f5_upload" && uploadedFile !== null`). Because the modal's
 * own render gate is `signOpen && uploadedFile` — it checks the FILE, never the source_kind —
 * the unconditional pill produced two wrong states:
 *
 *   1. PRE-UPLOAD: clicking the pill sets signOpen=true but `uploadedFile` is null, so nothing
 *      renders. A silent dead control (the repo's shell-parity rule is explicit that a control
 *      is either live or visibly disabled-with-reason, never silently inert).
 *   2. NON-F5 UPLOAD: `setUploadedFile(file)` runs on EVERY branch, so after an extract_review
 *      or xero_sales_upload the pill OPENS SignModal — offering sign-off for a format that
 *      POST /sign/upload rejects with 422 ("Xero F5 exports only this slice"). That is a fake
 *      affordance for an action the backend refuses.
 *
 * The existing pin (XeroPanelAdjudication.test.tsx C2) still passed through the regression
 * because it queries `/Sign working paper/i` — the name of the IN-PANEL button and of the modal
 * heading — whereas the TopBar pill is named `reviewerName || "Sign in"`. Sign eligibility was
 * enforced at one of two entry points, and the test pinning it did not cover the new one.
 *
 * FIX SHAPE: `onOpenSign` becomes OPTIONAL on TopBar — exactly the pattern PR #155 itself
 * established for `view`/`setView` — and the pill renders as a non-interactive identity chip
 * when it is omitted. XeroUploadPanel passes it only when `canSign`.
 *
 * THREE-TIMES RULE: "sign is F5-only, and EVERY sign entry point is gated on canSign — a
 * non-signable state exposes no interactive sign control anywhere" is stated in the TopBar prop
 * contract, enforced in TopBar + XeroUploadPanel code, and asserted here.
 */

const XERO_E2: QueueItem = {
  finding_id: "detect:E2:INV-2003",
  check_id: "E2",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "Cresco Pte Ltd",
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
  fingerprint: "sha256:5cd691d294bd411f03cc3036ada3f3b0766d37308a293f4d85434acc296ac39d",
  candidate_framing_text: "",
  completeness: { required: [], present: [], missing: [], satisfied: false },
  inputs_hash: "—",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

const DISCLAIMER =
  "Real-Xero-FORMAT findings over synthetic data — validation_status=unvalidated; candidates not verdicts.";

function uploadBody(sourceKind: string) {
  return {
    source_kind: sourceKind,
    validation_status: "unvalidated",
    disclaimer: DISCLAIMER,
    coverage_status: [{ check: "E2", level: "full", reason: "" }],
    queue: [XERO_E2],
  };
}

// /review/upload succeeds; every SAP endpoint stays rejected (§2 box-isolation).
function panelFetch(body: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload")) {
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    }
    if (url.includes("/command")) return Promise.reject(new Error(`Xero must not POST /command: ${url}`));
    if (url.includes("/audit")) return Promise.reject(new Error(`Xero must not GET /audit: ${url}`));
    if (url.includes("/review/")) return Promise.reject(new Error(`Xero must not GET the B1 review: ${url}`));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

// Copied VERBATIM from XeroPanelAdjudication.test.tsx's uploadPrimary().
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

// The TopBar reviewer pill, pre-sign, is named "Sign in" (reviewerName is empty).
function pillButton() {
  return screen.queryByRole("button", { name: /^Sign in$/i });
}

// The MODAL specifically — scoped to its <h3> heading, because the in-panel ReviewScreen button
// carries the same "Sign working paper" name and would otherwise match too.
function signModalOpen() {
  return screen.queryByRole("heading", { name: /Sign working paper/i });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Xero sign gate — every sign entry point obeys canSign (F5-only)", () => {
  it("PRE-UPLOAD: the TopBar reviewer pill is not an interactive sign control", async () => {
    vi.stubGlobal("fetch", panelFetch(uploadBody("xero_f5_upload")));
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    // Nothing uploaded yet ⇒ canSign is false ⇒ no clickable pill. It may still render as an
    // inert identity chip, but it must not be a button that leads nowhere.
    expect(pillButton()).toBeNull();
  });

  it("PRE-UPLOAD: no silently-dead control — clicking anything named 'Sign in' cannot no-op", async () => {
    vi.stubGlobal("fetch", panelFetch(uploadBody("xero_f5_upload")));
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    const pill = pillButton();
    // If a pill button exists at all pre-upload it MUST open something; the regression made it
    // set state that no render gate consumed. Assert the dead-end state is unreachable.
    if (pill) {
      fireEvent.click(pill);
      expect(signModalOpen()).not.toBeNull();
    } else {
      expect(signModalOpen()).toBeNull();
    }
  });

  it("xero_sales_upload: the TopBar pill exposes NO sign affordance (backend 422s the format)", async () => {
    vi.stubGlobal("fetch", panelFetch(uploadBody("xero_sales_upload")));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    expect(await screen.findByText("GST charged on a non-taxable (zero-rated) supply")).toBeInTheDocument();
    // A file IS uploaded now, so the modal's `signOpen && uploadedFile` gate would pass —
    // source_kind is the only thing standing between the user and a 422.
    expect(pillButton()).toBeNull();
    expect(signModalOpen()).toBeNull();
  });

  it("extract_review: the TopBar pill exposes NO sign affordance", async () => {
    vi.stubGlobal("fetch", panelFetch({ ...uploadBody("extract_review"), config_scope: "default_demo" }));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    expect(await screen.findByText("GST charged on a non-taxable (zero-rated) supply")).toBeInTheDocument();
    expect(pillButton()).toBeNull();
    expect(signModalOpen()).toBeNull();
  });

  it("xero_f5_upload: the TopBar pill IS live and opens the sign modal (positive case preserved)", async () => {
    vi.stubGlobal("fetch", panelFetch(uploadBody("xero_f5_upload")));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    expect(await screen.findByText("GST charged on a non-taxable (zero-rated) supply")).toBeInTheDocument();

    const pill = await waitFor(() => {
      const p = pillButton();
      expect(p).not.toBeNull();
      return p as HTMLElement;
    });

    fireEvent.click(pill);
    expect(signModalOpen()).not.toBeNull();
  });

  it("the UNVALIDATED trust badge survives the gate change on a non-signable branch (T2.11)", async () => {
    vi.stubGlobal("fetch", panelFetch(uploadBody("xero_sales_upload")));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    expect(await screen.findByText(/unvalidated — pending specialist review/i)).toBeInTheDocument();
  });
});
