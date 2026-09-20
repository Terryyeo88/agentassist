import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * Slice A / A2 — G-1: the re-apply must re-submit what the RUN submitted.
 *
 * The defect this pins (measured 2026-09-20, frontend recon §3 C7b): after recording ONE
 * decision the panel re-uploaded with `uploadExtract(uploadedFile, ledgerFile)` — dropping
 * `review_id` and `documents`. The backend resolves attached documents from the session
 * (api/app.py:1244-1252 returns (None, None, None) when rid is falsy), so the re-applied
 * response came back with the four document-derived findings GONE and their four coverage
 * rows regressed from degraded to `unavailable`. The reviewer adjudicated one finding and
 * silently lost four others; the signed paper still contained them, because the sign path
 * DID thread review_id.
 *
 * The mock below deliberately behaves like the real backend — it drops the document rows when
 * `review_id` is absent — so this test fails for the RIGHT reason on the unpatched code, and
 * cannot pass by accident.
 */

const RID = "r_reapply000001";
const FP = "sha256:a6a758ae79fa77c26f3ebf773784074a7bc67f9a8eb7a67e96cec8bfa3c54edf";

function row(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    finding_id: "detect:E4:BILL-3002",
    check_id: "E4",
    finding_type: "deterministic",
    group: "needs_review",
    vendor: "OldRate Supplies Pte Ltd",
    severity: "MEDIUM",
    description: "GST rate 8.00% deviates from expected 9%.",
    recommendation: "Confirm the applicable rate for this supply.",
    doc_num: "BILL-3002" as unknown as number,
    doc_date: "2026-05-11",
    error_code: "E4",
    display_name: "Stale GST rate applied",
    iras_basis: "IRAS e-Tax Guide — GST rate (registry citation).",
    iras_basis_caveat: "Illustrative citation — the IRAS basis shown is itself UNVALIDATED.",
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

/** 12 deterministic rows (the adjudicable one first) + 4 document-derived rows = 16, as C7a. */
function deterministicRows(): QueueItem[] {
  const rows = [row()];
  for (let i = 1; i < 12; i += 1) {
    rows.push(
      row({
        finding_id: `detect:E3:INV-${2000 + i}`,
        check_id: "E3",
        error_code: "E3",
        display_name: "Standard-rated line carrying zero tax",
        doc_num: `INV-${2000 + i}` as unknown as number,
        fingerprint: `sha256:det${i}`,
      })
    );
  }
  return rows;
}

const DOC_CHECKS = [
  "gst_amount_mismatch",
  "correct_period",
  "total_inconsistency",
  "reg11_supplier_gst_absent",
];

function documentRows(): QueueItem[] {
  return DOC_CHECKS.map((check, i) =>
    row({
      finding_id: `doccheck:${check}:BILL-300${i + 2}`,
      check_id: check,
      error_code: check,
      display_name: `Document check — ${check}`,
      doc_num: `BILL-300${i + 2}` as unknown as number,
      // Document rows are non-adjudicable today (no fingerprint) — that is G-4, not G-1.
      fingerprint: null,
    })
  );
}

function coverageRows(withDocuments: boolean) {
  const base = [{ check: "E4", level: "full", reason: "" }];
  return base.concat(
    DOC_CHECKS.map((check) =>
      withDocuments
        ? {
            check,
            level: "degraded",
            reason: `source documents partial — ${check} ran over 12 of 36 documents; items without a supplied document were not examined by this check.`,
          }
        : {
            check,
            level: "unavailable",
            reason: `no source documents supplied — ${check} cannot run.`,
          }
    )
  );
}

/**
 * Backend-faithful mock: the document surface exists only when the request carried a
 * review_id, exactly as `_xero_document_context` decides it server-side.
 */
function reapplyFetch() {
  const uploads: FormData[] = [];
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
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
    if (url.includes("/decision")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            client_id: "xero_demo",
            finding_id: "detect:E4:BILL-3002",
            action: "Mark known",
            disposition: "KNOWN_ACCEPTED",
            fingerprint: FP,
            entry_id: "e1",
            entry_hash: "sha256:e1",
            chain_length: 1,
            validation_status: "unvalidated",
            disclaimer: "AgentAssist flags — you decide.",
          }),
          { status: 200 }
        )
      );
    }
    if (url.includes("/review/upload")) {
      const form = init?.body as FormData;
      uploads.push(form);
      const hasRid = Boolean(form.get("review_id"));
      const adjudicated = uploads.length > 1;
      const deterministic = deterministicRows().map((r, i) =>
        i === 0 && adjudicated
          ? row({ demoted: true, prior_dispositions: ["KNOWN_ACCEPTED"], annotation: "Set aside by a prior adjudication." })
          : r
      );
      return Promise.resolve(
        new Response(
          JSON.stringify({
            source_kind: "xero_f5_upload",
            validation_status: "unvalidated",
            disclaimer: "AgentAssist flags — you decide.",
            coverage_status: coverageRows(hasRid),
            queue: hasRid ? [...deterministic, ...documentRows()] : deterministic,
          }),
          { status: 200 }
        )
      );
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
  return { mock, uploads };
}

function xlsx(name: string) {
  return new File([new Uint8Array([1, 2, 3])], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

function pdf(name: string) {
  return new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], name, { type: "application/pdf" });
}

const DOC_NAMES = ["BILL-3002.pdf", "BILL-3003.pdf", "BILL-3004.pdf", "BILL-3005.pdf"];

async function runWithEverything() {
  fireEvent.change(screen.getByLabelText(/source-document PDFs/i), {
    target: { files: DOC_NAMES.map(pdf) },
  });
  fireEvent.change(screen.getByLabelText(/820 account-transactions/i), {
    target: { files: [xlsx("ledger.xlsx")] },
  });
  fireEvent.change(screen.getByLabelText(/upload .xlsx gst export/i), {
    target: { files: [xlsx("f5.xlsx")] },
  });
  fireEvent.click(screen.getByRole("button", { name: /run review/i }));
}

async function openFindings() {
  const nav = screen.getByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: "Findings" }));
}

/** Scoped to the queue list — the detail card repeats the same check_id text. */
async function findInQueue(text: string) {
  return waitFor(() => {
    const list = document.querySelector(".queue-list") as HTMLElement | null;
    expect(list).not.toBeNull();
    const hit = within(list as HTMLElement).getByText(text);
    expect(hit).toBeInTheDocument();
    return hit;
  });
}

describe("Slice A / A2 — G-1: adjudicating must not delete the document findings", () => {
  afterEach(() => vi.restoreAllMocks());

  it("A2-T1: the re-apply carries the same review_id and the same documents as the run", async () => {
    const { mock, uploads } = reapplyFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    await runWithEverything();
    await waitFor(() => expect(uploads).toHaveLength(1));

    fireEvent.change(await screen.findByLabelText(/reviewer of record/i), {
      target: { value: "Recon Session" },
    });
    await openFindings();
    fireEvent.click(await screen.findByRole("button", { name: /Mark known/i }));
    fireEvent.change(await screen.findByPlaceholderText(/required for/i), {
      target: { value: "Standing accepted treatment." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));

    await waitFor(() => expect(uploads).toHaveLength(2));

    const run = uploads[0];
    const reapply = uploads[1];

    // The identity that decides whether the document surface exists at all.
    expect(reapply.get("review_id")).toBe(run.get("review_id"));
    expect(reapply.get("review_id")).toBe(RID);

    // The same documents, in the same order, as the run.
    const runDocs = (run.getAll("documents") as File[]).map((d) => d.name);
    const reapplyDocs = (reapply.getAll("documents") as File[]).map((d) => d.name);
    expect(runDocs).toEqual(DOC_NAMES);
    expect(reapplyDocs).toEqual(runDocs);

    // The primary and the ledger are the run's, too.
    expect((reapply.get("file") as File).name).toBe("f5.xlsx");
    expect((reapply.get("ledger") as File).name).toBe("ledger.xlsx");
  });

  it("A2-T2: the document findings survive one adjudication (16 rows before, 16 after)", async () => {
    const { mock, uploads } = reapplyFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    await runWithEverything();
    await waitFor(() => expect(uploads).toHaveLength(1));

    // The reviewer-of-record input is Review-home furniture, so it is filled before
    // navigating to Findings (the decision controls live there).
    fireEvent.change(await screen.findByLabelText(/reviewer of record/i), {
      target: { value: "Recon Session" },
    });

    await openFindings();
    // All four document-derived findings are in the QUEUE after the run. The queue row renders
    // the check_id (Queue.tsx `qr-check`), so that is what identifies the row; the query is
    // scoped to the queue list because the selected finding's card repeats the same id.
    for (const check of DOC_CHECKS) {
      expect(await findInQueue(check)).toBeTruthy();
    }
    fireEvent.click(await screen.findByRole("button", { name: /Mark known/i }));
    fireEvent.change(await screen.findByPlaceholderText(/required for/i), {
      target: { value: "Standing accepted treatment." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));

    await waitFor(() => expect(uploads).toHaveLength(2));

    // ...and all four are STILL in the queue after it. This is the assertion the old code
    // failed: pre-fix the re-applied queue came back with every document row gone.
    await openFindings();
    for (const check of DOC_CHECKS) {
      expect(await findInQueue(check)).toBeTruthy();
    }

    // The adjudicated row is demoted but PRESENT — cardinality is preserved, never filtered.
    expect(await screen.findByText("Stale GST rate applied")).toBeInTheDocument();
  });
});
