import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * Xero three-view shell + Audit (t-xero-views, STEPS 3a-3e) — FAILING-FIRST.
 *
 * D-13 REVERSES the locked "the Xero surface is a single non-tab-gated flow" decision. The
 * surface gains Review / Findings / Audit behind the SHARED TopBar nav, exactly as the SAP
 * surface has had since T6.3 Slice 4.
 *
 * What is pinned here:
 *   * THREE TABS, MUTUALLY EXCLUSIVE — one tab is current at a time; the views do not co-exist.
 *   * FINDINGS LIVE ON THEIR OWN VIEW — queue + detail, and the persist note is NOT a grid
 *     child (D-19: a live browser measurement showed the note taking grid cell 1 and pushing
 *     the detail card into the 320px column on row 2).
 *   * LEDGER-RECON ROWS ARE DISTINGUISHABLE (D-18). Measured: of the six fields Queue.tsx
 *     renders, the two ledger_recon rows differ in NONE. Only finding_id, description and
 *     recommendation differ at all. So the queue shows finding_id's terminal segment. It must
 *     NOT be derived by parsing "Box 6"/"Box 7" out of prose — that would be fabrication.
 *   * LEDGER-RECON ROWS STAY NON-ADJUDICABLE — fingerprint is null, so the decision controls
 *     stay disabled with their honest per-cause reason. Never hidden, never a dead button.
 *   * AUDIT IS EMPTY ON LOAD (D-17). There is NO read endpoint for the decision store, so no
 *     prior decision can be listed. A seeded row would be an invented backend state.
 *   * THE EXTRACT CAVEAT IS ON ALL THREE VIEWS (D-15). It says findings "should not be relied
 *     on"; a warning about findings must be visible wherever findings are.
 *
 * FIXTURE PROVENANCE: every row below is verbatim from a real POST /review/upload over the
 * committed F5 fixture WITH the committed ledger fixture
 * (tests/fixtures/xero-real-format/AgentAssist_-_Account_Transactions.xlsx). Nothing invented.
 */

const CAVEAT = "Illustrative citation — the IRAS basis shown is itself UNVALIDATED (T2.11 gates customer-facing claims); verify against the e-Tax Guides before any customer use.";

// Verbatim from the real run — a fingerprinted E3 row.
const E3: QueueItem = {
  finding_id: "detect:E3:INV-2002",
  check_id: "E3",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "Borealis Pte Ltd",
  severity: "HIGH",
  description: "Standard-rated line (VatGroup=SR) with zero tax on 5000.00",
  recommendation: "Apply GST at the applicable rate, or reclassify if the supply is exempt or zero-rated.",
  doc_num: "INV-2002" as unknown as number,
  doc_date: "2026-04-15",
  error_code: "E3",
  display_name: "Standard-rated supply with zero or missing GST amount",
  iras_basis: "IRAS GST Act s10 / applicable output and input tax provisions",
  iras_basis_caveat: CAVEAT,
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: "sha256:52563359fec47778f0ec32e6fe327d3208cfc4caf391bb9ba909adb91736c5b3",
  candidate_framing_text: "Document INV-2002 (E3 - Standard-rated supply with zero or missing GST amount) appears to be a candidate for reviewer attention; consider reviewing the GST treatment for this item. This is a candidate, not a verdict.",
  completeness: {
    required: ["sales_invoices", "purchase_invoices", "vat_group_mapping"],
    present: ["sales_invoices", "purchase_invoices", "vat_group_mapping"],
    missing: [],
    satisfied: true,
  },
  inputs_hash: "sha256:a18afe7b968181f0218933bdec9c70bbd73ed979556674c0772b7f0bc1dcbcce",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

// The two ledger-reconciliation rows, verbatim. They appear ONLY when the 820 ledger export is
// attached. Measured: the ONLY fields that differ between them are finding_id, description and
// recommendation — every other field, including all six the queue renders, is identical.
const LEDGER_BASE = {
  check_id: "GST_LEDGER_RECON",
  finding_type: "deterministic",
  group: "needs_review" as const,
  vendor: null,
  severity: null,
  doc_num: null,
  doc_date: null,
  error_code: "LEDGER_RECON",
  display_name: "Ledger vs declared-return divergence",
  iras_basis: "Internal-consistency check — ledger-derived GST versus the declared F5 return. Not an IRAS-cited finding: it flags a divergence between two derivations of the same source for reviewer adjudication, never a verdict that either side is correct.",
  iras_basis_caveat: CAVEAT,
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: null,
  candidate_framing_text: "Internal-consistency candidate — a reviewer adjudicates whether the divergence is an error in the return; this is not a verdict.",
  completeness: { required: [], present: [], missing: [], satisfied: false },
  inputs_hash: "—",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

const RECON_OUTPUT: QueueItem = {
  ...LEDGER_BASE,
  finding_id: "ledger_recon:ledger_recon_divergence:output",
  description: "Ledger-derived output GST (990.0) exceeds declared Box 6 (900.0) by 90.0. If a reviewer adjudicates this divergence as an error in the return, net GST payable would change by 90.0. This is an internal-consistency observation between two derivations of the same source, not a verdict that either side is correct.",
  recommendation: "Candidate for reviewer adjudication. Reconcile the 820 control-account postings for this side against the declared return box. (Ledger transaction reference: output-side 820 control-account aggregate; GST box: Box 6; impact on GST payable if adjudicated as an error: 90.0.)",
} as QueueItem;

const RECON_INPUT: QueueItem = {
  ...LEDGER_BASE,
  finding_id: "ledger_recon:ledger_recon_divergence:input",
  description: "Ledger-derived input GST (1277.6) exceeds declared Box 7 (1265.0) by 12.6. If a reviewer adjudicates this divergence as an error in the return, net GST payable would change by 12.6. This is an internal-consistency observation between two derivations of the same source, not a verdict that either side is correct.",
  recommendation: "Candidate for reviewer adjudication. Reconcile the 820 control-account postings for this side against the declared return box. (Ledger transaction reference: input-side 820 control-account aggregate; GST box: Box 7; impact on GST payable if adjudicated as an error: 12.6.)",
} as QueueItem;

const F5_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags — you decide. Recomputed from transactions your uploaded Xero export already grouped by your own tax-code assignments — the arithmetic is AgentAssist's, the classification is yours; validation_status=unvalidated (T2.11 is the binding gate). Findings are unvalidated candidates — not a compliance verdict.",
  coverage_status: [
    { check: "NO_GST_REG", level: "unavailable", reason: "FederalTaxID absent — NO_GST_REG cannot run; require supplier-master sheet at onboarding." },
    { check: "E3", level: "full", reason: "" },
  ],
  queue: [E3, RECON_OUTPUT, RECON_INPUT],
};

// The extract branch, which carries the mandatory three-clause caveat.
const EXTRACT_BODY = {
  ...F5_BODY,
  source_kind: "extract_review",
  config_scope: "default_demo",
  queue: [{ ...E3 }],
};

function uploadFetch(body: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload")) {
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

async function uploadAndSettle() {
  await upload();
  // The upload fetch resolves asynchronously — wait for the landed response to render on the
  // Review view before switching tabs, or the Findings view mounts with an empty queue.
  await screen.findByLabelText(/Coverage preview/i);
}

async function upload() {
  const input = document.querySelector(
    "input.xero-file-input:not(.xero-ledger-input)"
  ) as HTMLInputElement | null;
  expect(input).not.toBeNull();
  const file = new File([new Uint8Array([1, 2, 3])], "AgentAssist_IRAS_F5.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  Object.defineProperty(input as HTMLInputElement, "files", { value: [file] });
  fireEvent.change(input as HTMLInputElement);
  // AMENDED (Slice A, staged upload): staging no longer runs; the run is an explicit press.
  fireEvent.click(screen.getByRole("button", { name: /run review/i }));
}

const nav = () => screen.getByRole("navigation", { name: /Primary/i });
const tab = (name: string) =>
  within(nav()).getByRole("button", { name: new RegExp(`^${name}$`, "i") });
const go = (name: string) => fireEvent.click(tab(name));

describe("Xero three-view shell (D-13)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("1: three tabs render, and exactly one is current at a time", async () => {
    vi.stubGlobal("fetch", uploadFetch(F5_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    expect(tab("Review")).toBeInTheDocument();
    expect(tab("Findings")).toBeInTheDocument();
    expect(tab("Audit")).toBeInTheDocument();
    expect(nav().querySelectorAll('[aria-current="page"]')).toHaveLength(1);

    go("Findings");
    expect(nav().querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(tab("Findings")).toHaveAttribute("aria-current", "page");
    expect(tab("Review")).not.toHaveAttribute("aria-current");
  });

  it("2: the views are mutually exclusive — Review furniture is gone on Findings", async () => {
    vi.stubGlobal("fetch", uploadFetch(F5_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await upload();
    expect(await screen.findByLabelText(/Coverage preview/i)).toBeInTheDocument();

    go("Findings");
    // The upload/coverage furniture belongs to Review only.
    expect(screen.queryByLabelText(/Coverage preview/i)).toBeNull();
    expect(document.querySelector("input.xero-file-input")).toBeNull();
  });

  it("3: the Findings view carries the queue AND the detail card", async () => {
    vi.stubGlobal("fetch", uploadFetch(F5_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadAndSettle();
    go("Findings");

    expect(document.querySelector(".queue-list")).not.toBeNull();
    expect(await screen.findByText(E3.display_name!)).toBeInTheDocument();
    expect(screen.getByText(/candidate for review only/i)).toBeInTheDocument();
  });

  it("4 (D-19): the persist note is NOT a grid child — the grid holds queue + detail only", async () => {
    vi.stubGlobal("fetch", uploadFetch(F5_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadAndSettle();
    go("Findings");

    const grid = document.querySelector(".findings-view") as HTMLElement | null;
    expect(grid).not.toBeNull();
    // Exactly two grid children: the queue panel and the detail column. A third child is what
    // pushed the detail card into the 320px column (measured in a real browser).
    expect(grid!.children).toHaveLength(2);
    expect(grid!.querySelector(":scope > .xero-persist-note")).toBeNull();
    expect(grid!.querySelector(":scope > .queue-panel")).not.toBeNull();
    expect(grid!.querySelector(":scope > .detail-col")).not.toBeNull();
    // The note is still on the page — relocated, not deleted.
    expect(document.querySelector(".xero-persist-note")).not.toBeNull();
  });
});

describe("ledger-recon rows (D-18)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("5: the two rows are distinguishable in the queue by their own identity", async () => {
    vi.stubGlobal("fetch", uploadFetch(F5_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadAndSettle();
    go("Findings");

    const list = document.querySelector(".queue-list") as HTMLElement;
    // Measured: check_id / vendor / severity / doc_num / doc_date / demoted are IDENTICAL on
    // both rows, so identity must come from finding_id's terminal segment.
    expect(within(list).getByText("output")).toBeInTheDocument();
    expect(within(list).getByText("input")).toBeInTheDocument();
  });

  it("6: they stay NON-adjudicable, with the honest per-cause reason", async () => {
    vi.stubGlobal("fetch", uploadFetch(F5_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadAndSettle();
    go("Findings");

    const list = document.querySelector(".queue-list") as HTMLElement;
    fireEvent.click(within(list).getByText("output").closest("button")!);

    expect(await screen.findByText(/ledger-reconciliation finding carries no deterministic fingerprint/i))
      .toBeInTheDocument();
    for (const label of ["Accept", "Decline", "Not an issue", "Mark known"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${label}$`) })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: /Record decision/i })).toBeDisabled();
  });
});

describe("Audit view (D-17)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("7: EMPTY on load — no seeded row, and it says why", async () => {
    vi.stubGlobal("fetch", uploadFetch(F5_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    go("Audit");

    expect(screen.getByRole("heading", { name: /^Decisions$/i })).toBeInTheDocument();
    expect(screen.queryByText(/this session/i)).toBeNull();
    expect(screen.queryByRole("region", { name: /this session/i })).toBeNull();
    expect(screen.getByText(/No decision has been recorded against this export yet/i))
      .toBeInTheDocument();
    // Zero rows — a seeded entry would be an invented backend state.
    expect(document.querySelectorAll(".xaudit-row")).toHaveLength(0);
    // The honest callout names all three limits.
    const callout = screen.getByTestId("xaudit-limits");
    // "no read endpoint" and "re-upload" are resolved by C-6(b) populate-on-load; only the
    // still-true limitation remains.
    expect(callout).not.toHaveTextContent(/no read endpoint/i);
    expect(callout).toHaveTextContent(/no agent/i);
  });

  it("8: after a real decision, the row is built from the POST response's own fields", async () => {
    // The decision response shape is verbatim from a real POST /decision.
    const decisionResponse = {
      client_id: "xero_demo",
      finding_id: E3.finding_id,
      action: "Mark known",
      disposition: "KNOWN_ACCEPTED",
      fingerprint: E3.fingerprint,
      entry_id: "c314720a-8937-40e3-83d7-df80fef1f6d5",
      entry_hash: "sha256:89fc842b006e2709b484b951a1d10b83cec988af45eeee2b188ed962af17abd6",
      chain_length: 1,
      validation_status: "unvalidated",
      disclaimer: "AgentAssist flags — you decide.",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/decisions/")) {
          return Promise.resolve(new Response(JSON.stringify({
            client_id: "xero_demo",
            entries: [],
            chain_length: 0,
            validation_status: "unvalidated",
            disclaimer: "AgentAssist flags — you decide.",
          }), { status: 200 }));
        }
        if (url.includes("/decision")) {
          return Promise.resolve(new Response(JSON.stringify(decisionResponse), { status: 200 }));
        }
        if (url.includes("/review/upload")) {
          return Promise.resolve(new Response(JSON.stringify(F5_BODY), { status: 200 }));
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`));
      })
    );
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadAndSettle();

    const reviewer = await screen.findByLabelText(/reviewer of record/i);
    fireEvent.change(reviewer, { target: { value: "Collin Tan" } });

    go("Findings");
    const list = document.querySelector(".queue-list") as HTMLElement;
    fireEvent.click(within(list).getByText("E3").closest("button")!);
    fireEvent.click(await screen.findByRole("button", { name: /^Mark known$/ }));
    fireEvent.change(await screen.findByPlaceholderText(/required for/i), {
      target: { value: "Standing treatment." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));

    go("Audit");
    await waitFor(() => expect(document.querySelectorAll(".xaudit-row")).toHaveLength(1));
    const row = document.querySelector(".xaudit-row") as HTMLElement;
    expect(row).toHaveTextContent("KNOWN_ACCEPTED");
    expect(row).toHaveTextContent(E3.finding_id);
    expect(row).toHaveTextContent(decisionResponse.entry_hash.slice(0, 20));
    // chain_length is shown prominently, from the response.
    expect(screen.getByTestId("xaudit-chain-length")).toHaveTextContent("1");
  });
});

describe("extract caveat on every view (D-15)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("9: the three-clause caveat is present on Review, Findings AND Audit", async () => {
    vi.stubGlobal("fetch", uploadFetch(EXTRACT_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await upload();

    // A warning that findings "should not be relied on" must be wherever findings are.
    expect(await screen.findByText(/default demo configuration/i)).toBeInTheDocument();
    go("Findings");
    expect(screen.getByText(/default demo configuration/i)).toBeInTheDocument();
    go("Audit");
    expect(screen.getByText(/default demo configuration/i)).toBeInTheDocument();
  });

  it("10: the F5 branch never shows the default-config clause on any view", async () => {
    vi.stubGlobal("fetch", uploadFetch(F5_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await upload();

    for (const v of ["Review", "Findings", "Audit"]) {
      go(v);
      expect(screen.queryByText(/default demo configuration/i)).toBeNull();
    }
  });
});
