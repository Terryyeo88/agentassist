import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * Bucket-B wiring: surface the `out_of_scope` note on the Xero sales-invoice upload branch.
 *
 * The backend already returns `out_of_scope` ({count, by_code, reason}) on the
 * "xero_sales_upload" branch (OUT_OF_SCOPE_KEYS, api/app.py) — the visible note for lines
 * carrying an accepted-but-set-aside TaxType (e.g. "No Tax"). The frontend type didn't read it
 * and the panel didn't render it. This is a pure display wiring: read a field the backend
 * already sends; no backend / contract change. Honest by rule — set-aside lines are surfaced,
 * not silently dropped.
 */

async function openFindings() {
  const nav = screen.getByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: "Findings" }));
}

async function openReview() {
  const nav = screen.getByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: "Review" }));
}

const item: QueueItem = {
  finding_id: "detect:E1:958",
  check_id: "E1",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "SG Electronics",
  severity: "MEDIUM",
  description: "Standard-rated sales on a likely export/overseas supply.",
  recommendation: "Confirm export documentation.",
  doc_num: 958,
  doc_date: "2024-07-02",
  error_code: "E1",
  display_name: "Standard-rated sales on likely export/overseas supply",
  iras_basis: "IRAS GST Act s21(3)",
  iras_basis_caveat: "Illustrative citation — the IRAS basis shown is itself UNVALIDATED.",
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: "sha256:abc",
  candidate_framing_text: "",
  completeness: { required: [], present: [], missing: [], satisfied: false },
  inputs_hash: "—",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

const SALES_BODY_WITH_OOS = {
  source_kind: "xero_sales_upload",
  validation_status: "unvalidated",
  disclaimer: "Xero sales review — unvalidated.",
  coverage_status: [{ check: "E1", level: "full", reason: "" }],
  queue: [item],
  config_scope: "xero_sales_demo",
  out_of_scope: {
    count: 3,
    by_code: { "No Tax": 2, "BAS Excluded": 1 },
    reason: "Lines carrying an out-of-scope TaxType per the client config were set aside.",
  },
};

const SALES_BODY_NO_OOS = {
  source_kind: "xero_sales_upload",
  validation_status: "unvalidated",
  disclaimer: "Xero sales review — unvalidated.",
  coverage_status: [{ check: "E1", level: "full", reason: "" }],
  queue: [item],
  config_scope: "xero_sales_demo",
  out_of_scope: { count: 0, by_code: {}, reason: "No out-of-scope lines." },
};

function fetchReturning(body: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload"))
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

async function upload() {
  const input =
    (screen.queryByLabelText(/upload .* export/i) as HTMLInputElement | null) ??
    (document.querySelector("input[type=file]") as HTMLInputElement | null);
  const file = new File([new Uint8Array([1, 2, 3])], "sales.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  Object.defineProperty(input as HTMLInputElement, "files", { value: [file] });
  fireEvent.change(input as HTMLInputElement);
}

describe("Xero sales out-of-scope note (bucket B)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("surfaces the out-of-scope note with count, reason, and per-code breakdown", async () => {
    vi.stubGlobal("fetch", fetchReturning(SALES_BODY_WITH_OOS));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await upload();

    expect(await screen.findByLabelText(/out-of-scope lines/i)).toBeInTheDocument();
    const note = screen.getByLabelText(/out-of-scope lines/i);
    expect(note.textContent).toMatch(/3 lines set aside \(out of scope\)/i);
    expect(note.textContent).toMatch(/set aside/i);
    expect(note.textContent).toMatch(/No Tax \(2\)/);
    expect(note.textContent).toMatch(/BAS Excluded \(1\)/);
  });

  it("shows no out-of-scope note when the count is zero", async () => {
    vi.stubGlobal("fetch", fetchReturning(SALES_BODY_NO_OOS));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await upload();
    await openFindings();

    // The finding still renders, but no set-aside note when nothing was held out of scope.
    expect(await screen.findByText(item.display_name!)).toBeInTheDocument();

    
    // D-16: the out-of-scope callout is Review furniture. Return to Review to assert its
    // absence on the view where a non-zero count WOULD render it — and only after the
    // findByText above has proven the response landed, so this cannot pass on an empty tree.
    await openReview();
    expect(screen.queryByLabelText(/out-of-scope lines/i)).toBeNull();
  });
});
