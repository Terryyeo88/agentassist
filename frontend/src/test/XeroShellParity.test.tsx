import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, within, waitFor, fireEvent } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import { App } from "../App";
import { AUDIT_FIXTURE, REVIEW_FIXTURE } from "./fixtures";
import type { QueueItem } from "../api";

/**
 * Xero shell parity + empty-state guard (Commit 2) — FAILING-FIRST.
 *
 * Written BEFORE the implementation; MUST fail today for the RIGHT reason. Commit 2 wraps the
 * Xero surface (XeroUploadPanel) in the SAME shared shell chrome the SAP surface (App) already
 * uses — a shared <TopBar> (brand + loud UNVALIDATED badge + reviewer pill) and a shared
 * <Sidebar aria-label="Overview"> whose tallies count the upload findings. The bare
 * <h1 className="source-title"> is REMOVED, the reviewer-of-record input is RELOCATED
 * (not duplicated), the branch-aware banner carries Xero copy (never the SAP "Live SAP Business
 * One access" prose), and the SAP-only surfaces (Command bar / Audit trail / Filters) render as
 * DISABLED buttons with an honest reason. Mounting the panel fires NO SAP fetch (§2 box-isolation:
 * no /command, no /audit, no GET /review). Separately, the SAP surface (App) gets a defensive
 * empty-state guard: an F5-less payload renders the Review home WITHOUT the F5 strip and does not
 * crash.
 *
 * AMENDED (D-13). Commit 2 deliberately kept the Xero surface NON-tab-gated — no view-tabs, a
 * single upload flow — because un-editable tests assumed single-flow content. That decision was
 * REVERSED by D-13: the Xero surface now carries the same three mutually-exclusive view tabs
 * (Review / Findings / Audit) the SAP surface has, and findings live on their own view.
 * Assertions that read finding content switch first via openFindings(); none was weakened.
 *
 * THREE-TIMES RULE: the "Xero surface wears the shared shell chrome, is tab-gated into
 * Review / Findings / Audit, exposes exactly one reviewer input, shows SAP-only surfaces as
 * disabled-with-reason, and fires no SAP fetch; App tolerates an F5-less payload" contract is
 * pinned in the shell/panel spec, enforced in XeroUploadPanel + App code, and asserted here.
 */

async function openFindings() {
  const nav = screen.getByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: "Findings" }));
}

// A real-FORMAT Xero E2 finding, projected to the shared QueueItem shape by the backend
// (mirrors XeroFindings.test.tsx's XERO_E2 so the shell wraps the SAME single-flow content).
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

// The reshaped xero_f5_upload body (one real finding in the queue), mirroring XeroFindings.
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

// Tests 1–4: nothing is uploaded, so the shell chrome must render immediately WITHOUT any SAP
// fetch. Any hit to /command, /audit, or the B1 review GET (/review/) fails the test.
function rejectSapFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/command")) return Promise.reject(new Error(`Xero must not POST /command: ${url}`));
    if (url.includes("/audit")) return Promise.reject(new Error(`Xero must not GET /audit: ${url}`));
    if (url.includes("/review/")) return Promise.reject(new Error(`Xero must not GET the B1 review: ${url}`));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

// Tests 5–6: a real upload succeeds (/review/upload), while SAP endpoints stay rejected. Order
// matters — /review/upload is matched before the generic /review/ B1-review reject.
function xeroUploadFetch(body: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload")) return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    if (url.includes("/command")) return Promise.reject(new Error(`Xero must not POST /command: ${url}`));
    if (url.includes("/audit")) return Promise.reject(new Error(`Xero must not GET /audit: ${url}`));
    if (url.includes("/review/")) return Promise.reject(new Error(`Xero must not GET the B1 review: ${url}`));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

// The file-upload helper — copied VERBATIM from XeroPanelAdjudication.test.tsx's uploadPrimary().
async function uploadA() {
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

// App empty-state guard (test 7): the RUN_REVIEW command response + mock pattern from
// App.smoke.test.tsx, but the GET /review payload has f5_summary OMITTED.
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
      ],
      f5_summary: REVIEW_FIXTURE.f5_summary,
      available_facets: { error_code: { E1: 1 } },
      findings: [
        { finding_id: "detect:E1:958", check_id: "E1", finding_type: "deterministic" },
      ],
      remaining_facets: { error_code: { E1: 1 } },
      applied_filters: {},
      filter_rejection: null,
    },
    notes: [],
  },
};

function appFetchNoF5() {
  // A review payload with f5_summary OMITTED — the defensive guard must not crash on it.
  const noF5: unknown = { ...REVIEW_FIXTURE };
  delete (noF5 as { f5_summary?: unknown }).f5_summary;
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/")) return Promise.resolve(new Response(JSON.stringify(noF5), { status: 200 }));
    if (url.includes("/audit")) return Promise.resolve(new Response(JSON.stringify({ entries: AUDIT_FIXTURE }), { status: 200 }));
    if (url.includes("/command")) return Promise.resolve(new Response(JSON.stringify(RUN_REVIEW), { status: 200 }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

describe("Xero shell parity + empty-state guard (Commit 2)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("1: fresh Xero page — shell chrome present, bare h1 gone, three live tabs", async () => {
    vi.stubGlobal("fetch", rejectSapFetch());
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    // The loud UNVALIDATED badge renders immediately (no upload needed).
    expect(screen.getByText(/pending specialist review/i)).toBeInTheDocument();
    expect(screen.getAllByText(/unvalidated/i).length).toBeGreaterThan(0);

    // The shared Sidebar is present.
    expect(document.querySelector("aside.sidebar")).not.toBeNull();

    // The old bare <h1 className="source-title"> is REMOVED.
    expect(document.querySelector(".source-title")).toBeNull();
    expect(screen.queryByText("Xero export — review")).toBeNull();

    // D-13: the Xero surface is now tab-gated — three live views, mutually exclusive.
    const nav = screen.getByRole("navigation", { name: /Primary/i });
    for (const label of ["Review", "Findings", "Audit"]) {
      expect(within(nav).getByRole("button", { name: label })).toBeInTheDocument();
    }
    // Mutually exclusive: exactly one tab is current at a time.
    expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  });

  it("2: reviewer-of-record input renders exactly once (relocated, not duplicated)", () => {
    vi.stubGlobal("fetch", rejectSapFetch());
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    // The reviewer PILL is a <button>, not a labelled textbox, so it must NOT be picked up here.
    expect(screen.getAllByLabelText(/reviewer of record/i)).toHaveLength(1);
  });

  it("3: branch-aware banner carries Xero copy, never the SAP prose", () => {
    vi.stubGlobal("fetch", rejectSapFetch());
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    expect(screen.getByText(/never writes back to Xero/i)).toBeInTheDocument();
    expect(screen.queryByText(/Live SAP Business One access/i)).toBeNull();
  });

  it("4: SAP-only surfaces render disabled with an honest reason, and fire no SAP fetch", () => {
    const fetchMock = rejectSapFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    const cmd = screen.getByRole("button", { name: /^Command bar$/ });
    expect(cmd).toBeDisabled();
    expect(screen.getByText(/available on the SAP review only/i)).toBeInTheDocument();

    const audit = screen.getByRole("button", { name: /^Audit trail$/ });
    expect(audit).toBeDisabled();
    expect(screen.getByText(/no agent audit chain/i)).toBeInTheDocument();

    const filters = screen.getByRole("button", { name: /^Filters$/ });
    expect(filters).toBeDisabled();
    expect(screen.getByText(/not available for uploads/i)).toBeInTheDocument();

    // §2 box-isolation: mounting the panel + its disabled surfaces touches NO SAP endpoint.
    const forbidden = fetchMock.mock.calls.filter(([u]) => {
      const url = String(u);
      return url.includes("/command") || url.includes("/audit") || url.includes("/review/");
    });
    expect(forbidden).toHaveLength(0);
  });

  it("5: upload still works through the shell (regression guard)", async () => {
      vi.stubGlobal("fetch", xeroUploadFetch(XERO_BODY));
      render(<XeroUploadPanel onChangeSource={() => {}} />);
      await uploadA();
      await openFindings();

      // Findings now live on their own view — the chrome did not hide them.
      expect(await screen.findByText(/candidate for review only/i)).toBeInTheDocument();
      expect(await screen.findByText(XERO_E2.display_name!)).toBeInTheDocument();
    });

  it("6: the Sidebar tallies count the upload findings", async () => {
    vi.stubGlobal("fetch", xeroUploadFetch(XERO_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadA();
    await openFindings();

    // Wait for the uploaded finding to render through the shell.
    expect(await screen.findByText(XERO_E2.display_name!)).toBeInTheDocument();

    const sidebar = document.querySelector("aside.sidebar") as HTMLElement | null;
    expect(sidebar).not.toBeNull();
    // The uploaded queue carries ONE finding — the sidebar tally reflects that count.
    await waitFor(() =>
      expect(within(sidebar as HTMLElement).getAllByText("1").length).toBeGreaterThan(0)
    );
  });

  it("7: App empty-state guard — an F5-less payload does not crash", async () => {
    vi.stubGlobal("fetch", appFetchNoF5());
    render(<App />);

    // The Review home still renders live (command bar present).
    const input = await screen.findByPlaceholderText(/Ask the assistant/i);
    expect(input).not.toBeDisabled();

    // The F5 strip is ABSENT (guarded off) — no throw on the missing f5_summary.
    expect(screen.queryByText(/GST F5 return/i)).toBeNull();
  });
});
