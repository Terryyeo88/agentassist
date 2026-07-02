import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * Extract-engine review surface (BUILD 3) — FAILING-FIRST.
 *
 * Turning the general-extract path ON returns `source_kind:"extract_review"` with a `queue`
 * and a `config_scope:"default_demo"` marker. The upload panel (the surface a non-Xero .xlsx
 * reaches, since the backend format-routes) must render those findings in the shared
 * <ReviewScreen> AND surface the LOUD three-clause caveat — including the mandatory
 * default-config clause. The caveat is SCOPED to extract_review: the Xero path must NOT show it.
 */

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
  fingerprint: null,
  candidate_framing_text: "",
  completeness: { required: [], present: [], missing: [], satisfied: false },
  inputs_hash: "—",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

const EXTRACT_REVIEW_BODY = {
  source_kind: "extract_review",
  validation_status: "unvalidated",
  disclaimer: "Demo extract review — validation_status=unvalidated.",
  coverage_status: [{ check: "E1", level: "full", reason: "" }],
  queue: [item],
  config_scope: "default_demo",
};

const XERO_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer: "Xero review — unvalidated.",
  coverage_status: [{ check: "E1", level: "full", reason: "" }],
  queue: [item],
};

function fetchReturning(body: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload")) return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

async function upload() {
  const input =
    (screen.queryByLabelText(/upload .* export/i) as HTMLInputElement | null) ??
    (document.querySelector("input[type=file]") as HTMLInputElement | null);
  const file = new File([new Uint8Array([1, 2, 3])], "export.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  Object.defineProperty(input as HTMLInputElement, "files", { value: [file] });
  fireEvent.change(input as HTMLInputElement);
}

describe("extract-engine review surface (BUILD 3)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("FT1: extract findings render as candidates with the LOUD three-clause caveat", async () => {
    vi.stubGlobal("fetch", fetchReturning(EXTRACT_REVIEW_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await upload();

    // Findings render as candidates in the shared screen.
    expect(await screen.findByText(/candidate for review only/i)).toBeInTheDocument();
    expect(await screen.findByText(item.display_name!)).toBeInTheDocument();

    // Three-clause caveat visible: unvalidated + synthetic-format + default-config.
    expect(await screen.findByText(/unvalidated candidates/i)).toBeInTheDocument();
    expect(screen.getByText(/synthetic sample/i)).toBeInTheDocument();
    expect(screen.getByText(/default demo configuration/i)).toBeInTheDocument();
    expect(screen.getByText(/should not be relied on/i)).toBeInTheDocument();
  });

  it("FT2: the Xero path renders findings but NOT the extract default-config caveat", async () => {
    vi.stubGlobal("fetch", fetchReturning(XERO_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await upload();

    expect(await screen.findByText(item.display_name!)).toBeInTheDocument();
    // The default-config clause is SCOPED to extract_review — it must not leak onto the Xero path.
    expect(screen.queryByText(/default demo configuration/i)).toBeNull();
  });
});
