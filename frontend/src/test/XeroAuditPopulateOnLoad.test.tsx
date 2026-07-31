import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * C-6(b) frontend — the Audit view populates PRIOR decisions on load. FAILING-FIRST.
 *
 * WHAT CHANGED UNDERNEATH. Until C-6(b) the decision store had a write half and no read half,
 * so this view could only ever list what THIS browser had just POSTed (D-17). `GET
 * /decisions/{client_id}` (api/app.py, merged in PR #175) returns the stored records, so a
 * decision recorded yesterday — or by someone else — can finally be shown. This file pins the
 * three behaviours the hand-edited tests do not reach.
 *
 * 1. POPULATE-ON-LOAD, AND ONLY WITH A CLIENT. `client_id` is derived from the upload
 *    response's `source_kind` (XeroUploadPanel.tsx CLIENT_ID_BY_SOURCE_KIND) — there is no
 *    client identity before an upload, so the pre-upload Audit view must fire NO request and
 *    stay honestly empty. Asking the server about a client we cannot name would be a guess.
 *
 * 2. THE "—" PLACEHOLDER (§8, no fabricated values). A stored entry has no `finding_id`: the
 *    record is keyed on the deterministic fingerprint alone (agent/decision_ledger.py's
 *    AdjudicationEntry). So a prior-decision row CANNOT name the finding, and the honest
 *    render is a visible dash — not a blank cell (which reads as a rendering bug), and not
 *    the fingerprint moved into the Finding column (which would assert an identity the
 *    record does not carry).
 *
 * 3. DEDUPE BY entry_id. A decision recorded in this session is ALSO in the store, so it
 *    comes back in the GET. Union without dedupe double-counts it, and the chain-length chip
 *    beside the table would then disagree with the rows underneath it. `entry_id` is the
 *    store's own per-append identity, so it is the correct key; the row `key` already uses it.
 *
 * FIXTURE PROVENANCE: the entry fixtures carry exactly the ten keys
 * `dataclasses.asdict(AdjudicationEntry)` writes, and the upload/decision bodies mirror the
 * shapes the real endpoints return. Nothing invented.
 */

const RECORDED_AT = "2026-07-29T08:31:24.512874+00:00";
const RECORDED_BY = "Collin Tan";
const EARLIER_AT = "2026-07-28T04:15:09.100002+00:00";
const EARLIER_BY = "Avinash R";

const FP_A = "sha256:" + "a".repeat(64);
const FP_B = "sha256:" + "b".repeat(64);

/** One stored record, exactly the ten keys the store writes. NOTE: no `finding_id`. */
const STORED_A = {
  entry_id: "c314720a-8937-40e3-83d7-df80fef1f6d5",
  fingerprint: FP_A,
  disposition: "KNOWN_ACCEPTED",
  reviewer: RECORDED_BY,
  reason: "[Mark known] Standing accepted treatment.",
  period: "2026Q2",
  timestamp: RECORDED_AT,
  prev_hash: "sha256:" + "0".repeat(64),
  entry_hash: "sha256:89fc842b006e2709b484b951a1d10b83cec988af45eeee2b188ed962af17abd6",
  fingerprint_version: "v1",
};

const STORED_B = {
  ...STORED_A,
  entry_id: "9f2b1d40-77aa-4c11-9f0e-2b6c3d5e8a71",
  fingerprint: FP_B,
  disposition: "REJECTED",
  reviewer: EARLIER_BY,
  reason: "[Decline] Disputed — the tax code is correct.",
  timestamp: EARLIER_AT,
  entry_hash: "sha256:1122334455667788990011223344556677889900112233445566778899001122",
};

function envelope(entries: unknown[]) {
  return {
    client_id: "xero_demo",
    entries,
    chain_length: entries.length,
    validation_status: "unvalidated",
    disclaimer: "AgentAssist flags — you decide.",
  };
}

// A fingerprinted E3 row — the only thing needed to make a decision recordable.
const E3: QueueItem = {
  finding_id: "detect:E3:INV-2002",
  check_id: "E3",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "Borealis Pte Ltd",
  severity: "HIGH",
  description: "Standard-rated line (VatGroup=SR) with zero tax on 5000.00",
  recommendation: "Apply GST at the applicable rate, or reclassify if the supply is exempt or zero-rated.",
  doc_num: "INV-2002",
  doc_date: "2026-04-15",
  error_code: "E3",
  display_name: "Standard-rated supply with zero or missing GST amount",
  iras_basis: "IRAS GST Act s10 / applicable output and input tax provisions",
  iras_basis_caveat: "Illustrative citation — the IRAS basis shown is itself UNVALIDATED.",
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: FP_A,
  candidate_framing_text: "This is a candidate, not a verdict.",
  completeness: { required: [], present: [], missing: [], satisfied: true },
  inputs_hash: "sha256:a18afe7b968181f0218933bdec9c70bbd73ed979556674c0772b7f0bc1dcbcce",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

const F5_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags — you decide.",
  coverage_status: [
    { check: "E3", level: "full", reason: "" },
    {
      check: "NO_GST_REG",
      level: "unavailable",
      reason: "FederalTaxID absent — NO_GST_REG cannot run; require supplier-master sheet at onboarding.",
    },
  ],
  queue: [E3],
};

/**
 * The route-shaped mock. `/decisions/` is matched BEFORE `/decision` on purpose: the write
 * path is a strict substring of the read path, so the loose branch would swallow both.
 */
function mockFetch(opts: { entries?: unknown[]; decisionResponse?: unknown } = {}) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/decisions/")) {
      return Promise.resolve(
        new Response(JSON.stringify(envelope(opts.entries ?? [])), { status: 200 }),
      );
    }
    if (url.includes("/decision")) {
      return Promise.resolve(
        new Response(JSON.stringify(opts.decisionResponse ?? {}), { status: 200 }),
      );
    }
    if (url.includes("/review/upload")) {
      return Promise.resolve(new Response(JSON.stringify(F5_BODY), { status: 200 }));
    }
    if (url.includes("/review-session")) {
      return Promise.resolve(new Response(JSON.stringify({ review_id: "r-1" }), { status: 200 }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

async function upload() {
  const input = document.querySelector(
    "input.xero-file-input:not(.xero-ledger-input)",
  ) as HTMLInputElement | null;
  expect(input).not.toBeNull();
  const file = new File([new Uint8Array([1, 2, 3])], "AgentAssist_IRAS_F5.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  Object.defineProperty(input as HTMLInputElement, "files", { value: [file] });
  fireEvent.change(input as HTMLInputElement);
  // Wait for the landed response — the Audit view cannot know a client before it arrives.
  await screen.findByLabelText(/Coverage preview/i);
}

const nav = () => screen.getByRole("navigation", { name: /Primary/i });
const go = (name: string) =>
  fireEvent.click(within(nav()).getByRole("button", { name: new RegExp(`^${name}$`, "i") }));

const rows = () => document.querySelectorAll(".xaudit-row");

describe("C-6(b): the Audit view populates prior decisions on load", () => {
  afterEach(() => vi.restoreAllMocks());

  it("fires NO decisions request before an upload — there is no client to ask about", async () => {
    const fetchMock = mockFetch({ entries: [STORED_A] });
    vi.stubGlobal("fetch", fetchMock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    go("Audit");

    // Pre-upload there is no source_kind, so no client_id — asking anyway would be a guess.
    const called = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(called.some((u) => u.includes("/decisions/"))).toBe(false);
    expect(rows()).toHaveLength(0);
    expect(screen.getByText(/No decision has been recorded against this export yet/i))
      .toBeInTheDocument();
  });

  it("loads prior decisions for the upload's client and renders them with When + Reviewer", async () => {
    const fetchMock = mockFetch({ entries: [STORED_A, STORED_B] });
    vi.stubGlobal("fetch", fetchMock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    await upload();
    go("Audit");

    // Two PRIOR decisions, with nothing recorded in this session.
    await waitFor(() => expect(rows()).toHaveLength(2));

    // The read went to the upload's client_id, derived from source_kind — not a hardcoded one.
    const called = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(called.some((u) => u.includes("/decisions/xero_demo"))).toBe(true);

    // VERBATIM (§8): the ledger's own stamp and recorded reviewer, character for character.
    // A browser clock or a locale re-format would fail here — which is the point.
    const first = rows()[0] as HTMLElement;
    expect(within(first).getByText(RECORDED_AT)).toBeInTheDocument();
    expect(within(first).getByText(RECORDED_BY)).toBeInTheDocument();
    expect(first).toHaveTextContent("KNOWN_ACCEPTED");

    const second = rows()[1] as HTMLElement;
    expect(within(second).getByText(EARLIER_AT)).toBeInTheDocument();
    expect(within(second).getByText(EARLIER_BY)).toBeInTheDocument();
    expect(second).toHaveTextContent("REJECTED");

    // The UI verb survives in the stored reason ("[Mark known] …") and is read back from it,
    // never re-derived from the disposition (two verbs map to KNOWN_ACCEPTED — that is why
    // the verb is stored verbatim in the first place).
    expect(first).toHaveTextContent("Mark known");
    expect(second).toHaveTextContent("Decline");
  });

  it("renders a muted — in the Finding cell of a stored entry, which carries no finding_id", async () => {
    vi.stubGlobal("fetch", mockFetch({ entries: [STORED_A] }));
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    await upload();
    go("Audit");
    await waitFor(() => expect(rows()).toHaveLength(1));

    const cell = (rows()[0] as HTMLElement).querySelector(".xaudit-finding") as HTMLElement;
    expect(cell).not.toBeNull();
    // A visible dash: not blank (which reads as a broken render), and NOT the fingerprint
    // relocated into this column (which would assert an identity the record does not carry).
    expect(cell.textContent?.trim()).toBe("—");
    expect(cell.textContent).not.toContain("sha256:");
  });

  it("dedupes by entry_id — a decision in BOTH the store and this session is ONE row", async () => {
    // The POST response and the stored record are the SAME append: same entry_id, same hash.
    const decisionResponse = {
      client_id: "xero_demo",
      finding_id: E3.finding_id,
      action: "Mark known",
      disposition: "KNOWN_ACCEPTED",
      fingerprint: FP_A,
      entry_id: STORED_A.entry_id,
      entry_hash: STORED_A.entry_hash,
      reviewer: RECORDED_BY,
      timestamp: RECORDED_AT,
      chain_length: 1,
      validation_status: "unvalidated",
      disclaimer: "AgentAssist flags — you decide.",
    };
    vi.stubGlobal("fetch", mockFetch({ entries: [STORED_A], decisionResponse }));
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    await upload();

    const reviewer = await screen.findByLabelText(/reviewer of record/i);
    fireEvent.change(reviewer, { target: { value: RECORDED_BY } });

    go("Findings");
    const list = document.querySelector(".queue-list") as HTMLElement;
    fireEvent.click(within(list).getByText("E3").closest("button")!);
    fireEvent.click(await screen.findByRole("button", { name: /^Mark known$/ }));
    fireEvent.change(await screen.findByPlaceholderText(/required for/i), {
      target: { value: "Standing accepted treatment." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));

    go("Audit");

    // ONE row, not two — the same append must not be counted twice just because it arrived
    // down two paths. Left undeduped, the chain-length chip would contradict the rows below it.
    await waitFor(() => expect(rows()).toHaveLength(1));
    const only = rows()[0] as HTMLElement;
    expect(within(only).getByText(RECORDED_AT)).toBeInTheDocument();
    expect(within(only).getByText(RECORDED_BY)).toBeInTheDocument();
  });
});
