import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * C9 — Slice C: the Contacts export as a fourth staged input. FAILING-FIRST.
 *
 * D-2026-09-20-slice-c-contacts-no-gst-reg. The supplier-registration check (NO_GST_REG)
 * cannot run on an F5 export alone — it needs the supplier master, which in Xero is the
 * Contacts export. This pins the UI half:
 *
 *   T1  THE FOURTH INPUT STAGES. A Contacts .csv selected on `input.xero-contacts-input`
 *       appears in "Staged for this run" by name, like the ledger and the documents. It
 *       deliberately does NOT carry class `xero-file-input`: every existing helper selects
 *       the primary via `input.xero-file-input:not(.xero-ledger-input)`, and a fourth input
 *       carrying that class would match first and swallow their upload (the same trap the
 *       documents input documents at XeroUploadPanel.tsx:497-500).
 *   T2  RUN SENDS IT — ONCE. The run's POST /review/upload carries a `contacts` part. The
 *       request is selected BY URL, never by `calls[0]`: the panel also POSTs
 *       /review-session and GETs /decisions/{client_id} on the same press.
 *   T3  NOTHING STAGED, NOTHING SENT. With no Contacts staged the request carries no
 *       `contacts` part at all — the backend's byte-identical no-contacts path (D2/C2) is
 *       only reachable if the browser actually omits the field.
 *   T4  G-1: THE RE-APPLY AND THE SIGN RE-SUBMIT WHAT THE RUN SENT. Both read `ranContacts`
 *       — captured at Run time — never the live staging. Re-staging a different Contacts
 *       file after a run must not change the inputs behind a decision already recorded
 *       against that result, nor what gets signed.
 *
 * Hermetic: `fetch` is stubbed; no network, no backend.
 */

const FP = "sha256:a6a758ae79fa77c26f3ebf773784074a7bc67f9a8eb7a67e96cec8bfa3c54edf";

const NO_GST_REG_ROW: QueueItem = {
  finding_id: "detect:NO_GST_REG:BILL-3003",
  check_id: "NO_GST_REG",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "NoReg Trading",
  severity: "HIGH",
  description:
    "Input tax claimed from supplier NoReg Trading (NoReg Trading) without a GST " +
    "registration number — may not be claimable.",
  recommendation:
    "Obtain a valid tax invoice bearing the supplier's GST registration number; whether the " +
    "conditions for claiming input tax are met is for the reviewer to determine.",
  doc_num: "BILL-3003",
  doc_date: "2026-05-06",
  error_code: "NO_GST_REG",
  display_name: "Supplier GST-registration check",
  iras_basis: "GST (General) Regulations reg 11",
  iras_basis_caveat:
    "Illustrative citation — the IRAS basis shown is itself UNVALIDATED (T2.11 gates " +
    "customer-facing claims); verify against the e-Tax Guides before any customer use.",
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: FP,
  candidate_framing_text:
    "Document BILL-3003 (NO_GST_REG) appears to be a candidate for reviewer attention. " +
    "This is a candidate, not a verdict.",
  completeness: {
    required: ["purchase_invoices", "business_partners"],
    present: ["purchase_invoices", "business_partners"],
    missing: [],
    satisfied: true,
  },
  inputs_hash: "sha256:a8b99891a35b34b986760d0189437158fafb28dd3008c224d708c0f431141e7a",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

const OK_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags — you decide.",
  coverage_status: [
    {
      check: "NO_GST_REG",
      level: "degraded",
      reason:
        "Contacts export supplied — supplier registration checked on 19 of 20 input-tax " +
        "purchase lines; not examined: 0 not found in the Contacts export, 0 ambiguous, " +
        "1 with no supplier on the transaction.",
    },
  ],
  queue: [NO_GST_REG_ROW],
};

const DECISION_RESPONSE = {
  client_id: "xero_demo",
  finding_id: NO_GST_REG_ROW.finding_id,
  fingerprint: FP,
  action: "Mark known",
  note: "Supplier confirmed unregistered.",
  reviewer_name: "Collin Tan",
  entry_id: "b986d57f",
  entry_hash: "sha256:def",
  chain_length: 1,
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags — you decide.",
};

const SIGN_RESPONSE = {
  source_kind: "xero_f5_signed",
  reviewer_name: "Collin Tan",
  firm_name: "",
  working_paper_path: "/tmp/reports/working-paper.pdf",
  bundle_dir: "/tmp/audit/bundle",
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags — you decide.",
};

function panelFetch() {
  // `init` is declared so vitest records it: the assertions below read the FormData off
  // each call's second argument.
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    const url = String(input);
    if (url.includes("/review-session"))
      return Promise.resolve(
        new Response(JSON.stringify({ review_id: "r_abc123" }), { status: 200 })
      );
    if (url.includes("/decisions/"))
      return Promise.resolve(
        new Response(
          JSON.stringify({
            client_id: "xero_demo",
            entries: [],
            chain_length: 0,
            validation_status: "unvalidated",
            disclaimer: "AgentAssist flags — you decide.",
          }),
          { status: 200 }
        )
      );
    if (url.includes("/sign/upload"))
      return Promise.resolve(new Response(JSON.stringify(SIGN_RESPONSE), { status: 200 }));
    if (url.includes("/decision"))
      return Promise.resolve(new Response(JSON.stringify(DECISION_RESPONSE), { status: 200 }));
    if (url.includes("/review/upload"))
      return Promise.resolve(new Response(JSON.stringify(OK_BODY), { status: 200 }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

function stagePrimary() {
  const input = document.querySelector(
    "input.xero-file-input:not(.xero-ledger-input)"
  ) as HTMLInputElement | null;
  expect(input).not.toBeNull();
  const file = new File([new Uint8Array([1, 2, 3])], "AgentAssist_IRAS_F5.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  Object.defineProperty(input as HTMLInputElement, "files", { value: [file] });
  fireEvent.change(input as HTMLInputElement);
}

function stageContacts(name = "Contacts.csv") {
  const input = document.querySelector(
    "input.xero-contacts-input"
  ) as HTMLInputElement | null;
  expect(input).not.toBeNull();
  const file = new File(["*ContactName\r\nAcme Pte Ltd\r\n"], name, { type: "text/csv" });
  Object.defineProperty(input as HTMLInputElement, "files", {
    value: [file],
    configurable: true,
  });
  fireEvent.change(input as HTMLInputElement);
}

function runReview() {
  fireEvent.click(screen.getByRole("button", { name: /run review/i }));
}

/** Every POST /review/upload request body, in order — selected BY URL, never by index. */
function uploadForms(fetchMock: ReturnType<typeof panelFetch>): FormData[] {
  return fetchMock.mock.calls
    .filter(([u]) => String(u).includes("/review/upload"))
    .map(([, init]) => (init as RequestInit).body as FormData);
}

function signForm(fetchMock: ReturnType<typeof panelFetch>): FormData {
  const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/sign/upload"));
  expect(call).toBeTruthy();
  return (call![1] as RequestInit).body as FormData;
}

async function openFindings() {
  const nav = screen.getByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: "Findings" }));
}

describe("Slice C — the Contacts export stages, runs, re-applies and signs", () => {
  afterEach(() => vi.restoreAllMocks());

  it("T1: a staged Contacts export is named in the staged manifest", async () => {
    vi.stubGlobal("fetch", panelFetch());
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    const manifest = screen.getByRole("region", { name: /Staged for this run/i });
    expect(within(manifest).getByText(/Contacts/i)).toBeInTheDocument();

    stageContacts();
    await waitFor(() =>
      expect(within(manifest).getByText("Contacts.csv")).toBeInTheDocument()
    );
    // The fourth input must not answer the primary-input selector every other test uses.
    expect(
      document.querySelectorAll("input.xero-file-input:not(.xero-ledger-input)").length
    ).toBe(1);
  });

  it("T2: Run review sends ONE upload carrying the contacts part", async () => {
    const fetchMock = panelFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stagePrimary();
    stageContacts();
    runReview();

    await waitFor(() => expect(uploadForms(fetchMock).length).toBe(1));
    const form = uploadForms(fetchMock)[0];
    const contacts = form.get("contacts") as File;
    expect(contacts).toBeTruthy();
    expect(contacts.name).toBe("Contacts.csv");
  });

  it("T3: with nothing staged the request carries no contacts part", async () => {
    const fetchMock = panelFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stagePrimary();
    runReview();

    await waitFor(() => expect(uploadForms(fetchMock).length).toBe(1));
    expect(uploadForms(fetchMock)[0].get("contacts")).toBeNull();
  });

  it("T4: the re-apply and the sign re-submit the RUN's contacts, not the live staging", async () => {
    const fetchMock = panelFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stagePrimary();
    stageContacts("Contacts-AS-RUN.csv");
    runReview();
    await waitFor(() => expect(uploadForms(fetchMock).length).toBe(1));

    // Re-stage a DIFFERENT Contacts file AFTER the run. Nothing below may pick it up.
    stageContacts("Contacts-RESTAGED.csv");

    const reviewer = await screen.findByLabelText(/reviewer of record/i);
    fireEvent.change(reviewer, { target: { value: "Collin Tan" } });

    await openFindings();
    fireEvent.click(await screen.findByRole("button", { name: /Mark known/i }));
    const note = await screen.findByPlaceholderText(/required for/i);
    fireEvent.change(note, { target: { value: "Supplier confirmed unregistered." } });
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));

    // Re-apply: the second upload carries the run's OWN contacts file.
    await waitFor(() => expect(uploadForms(fetchMock).length).toBeGreaterThanOrEqual(2));
    const reapply = uploadForms(fetchMock)[1].get("contacts") as File;
    expect(reapply).toBeTruthy();
    expect(reapply.name).toBe("Contacts-AS-RUN.csv");

    // Sign: the same file again — the paper must match the screen (D-45 / ruling 4).
    fireEvent.click(await screen.findByRole("button", { name: /Sign working paper/i }));
    // SignModal's labels are not `htmlFor`-associated, so the reviewer field is taken
    // positionally from inside the modal itself (first input) rather than by label.
    await screen.findByRole("heading", { name: /Sign working paper/i });
    const modalReviewer = document.querySelector(".modal input") as HTMLInputElement;
    expect(modalReviewer).not.toBeNull();
    fireEvent.change(modalReviewer, { target: { value: "Collin Tan" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign and emit working paper/i }));

    await waitFor(() => expect(signForm(fetchMock).get("contacts")).toBeTruthy());
    expect((signForm(fetchMock).get("contacts") as File).name).toBe("Contacts-AS-RUN.csv");
  });
});
