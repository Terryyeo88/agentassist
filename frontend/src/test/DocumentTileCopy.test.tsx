import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { XeroUploadPanel } from "../components/XeroUploadPanel";

/**
 * Slice A / A4 — G-3: the Audit view must not deny a feature the panel ships.
 *
 * At eba8aeb a disabled tile on the Audit view read:
 *
 *   "A Xero export carries no source-document PDFs, which is also why four coverage
 *    checks could not run."
 *
 * Both clauses are false since C-8 / T-E(1)/(2): the same component renders a documents
 * input, and with documents attached the four checks DO run (measured 2026-09-20: 4/4 baits
 * fired, coverage `degraded … 12 of 36 documents`). The sentence was unpinned by any test,
 * which is how it survived the features that falsified it.
 *
 * Replacement rule (D-40): the panel may show the backend's coverage `reason` VERBATIM, or
 * show nothing. It must never parse that prose for counts — the reason is prose, not a
 * contract (feeders/coverage_status.py:109-118).
 */

const RID = "r_tilecopy00001";

const DOC_CHECKS = [
  "gst_amount_mismatch",
  "correct_period",
  "total_inconsistency",
  "reg11_supplier_gst_absent",
];

const DEGRADED_REASON = (check: string) =>
  `source documents partial — ${check} ran over 12 of 36 documents; items without a supplied document were not examined by this check.`;

function panelFetch(withDocuments: boolean) {
  const mock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review-session")) {
      return Promise.resolve(new Response(JSON.stringify({ review_id: RID }), { status: 200 }));
    }
    if (url.includes("/decisions/")) {
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
    }
    if (url.includes("/review/upload")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            source_kind: "xero_f5_upload",
            validation_status: "unvalidated",
            disclaimer: "AgentAssist flags — you decide.",
            coverage_status: DOC_CHECKS.map((check) =>
              withDocuments
                ? { check, level: "degraded", reason: DEGRADED_REASON(check) }
                : { check, level: "unavailable", reason: `no source documents supplied — ${check} cannot run.` }
            ),
            queue: [],
          }),
          { status: 200 }
        )
      );
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
  return mock;
}

function xlsx(name: string) {
  return new File([new Uint8Array([1, 2, 3])], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

async function runReview() {
  fireEvent.change(screen.getByLabelText(/upload .xlsx gst export/i), {
    target: { files: [xlsx("f5.xlsx")] },
  });
  fireEvent.click(screen.getByRole("button", { name: /run review/i }));
}

async function openAudit() {
  const nav = screen.getByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: "Audit" }));
}

const FALSE_SENTENCE = /carries no source-document PDFs/i;

describe("Slice A / A4 — G-3: the source-document tile tells the truth", () => {
  afterEach(() => vi.restoreAllMocks());

  it("A4-T1: the false sentence is gone before any upload", async () => {
    vi.stubGlobal("fetch", panelFetch(true));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await openAudit();
    expect(screen.queryByText(FALSE_SENTENCE)).not.toBeInTheDocument();
  });

  it("A4-T2: the false sentence is gone after a run WITH documents", async () => {
    vi.stubGlobal("fetch", panelFetch(true));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await runReview();
    await waitFor(() => expect(screen.queryByText(/Reading export/i)).not.toBeInTheDocument());
    await openAudit();
    expect(screen.queryByText(FALSE_SENTENCE)).not.toBeInTheDocument();
  });

  it("A4-T3: the false sentence is gone after a run WITHOUT documents", async () => {
    vi.stubGlobal("fetch", panelFetch(false));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await runReview();
    await waitFor(() => expect(screen.queryByText(/Reading export/i)).not.toBeInTheDocument());
    await openAudit();
    expect(screen.queryByText(FALSE_SENTENCE)).not.toBeInTheDocument();
  });

  it("A4-T4: what it shows instead is the backend reason, VERBATIM", async () => {
    vi.stubGlobal("fetch", panelFetch(true));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await runReview();
    await waitFor(() => expect(screen.queryByText(/Reading export/i)).not.toBeInTheDocument());
    await openAudit();

    // Verbatim: the exact server string, not a summary and not a re-worded gloss.
    for (const check of DOC_CHECKS) {
      expect(screen.getByText(DEGRADED_REASON(check))).toBeInTheDocument();
    }
  });

  it("A4-T5: it shows nothing at all when there is no coverage to quote", async () => {
    vi.stubGlobal("fetch", panelFetch(true));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await openAudit();
    // Pre-upload there is no honest thing to say about document coverage, so the panel
    // says nothing rather than inventing a cause.
    expect(screen.queryByRole("region", { name: /source-document coverage/i })).not.toBeInTheDocument();
  });
});
