import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import type { QueueItem } from "../api";

/**
 * C-2 — pre-upload / busy / error states on the Xero upload panel. FAILING-FIRST.
 *
 * C-2 is EXTEND, not build: four states already shipped. What this pins is the delta.
 *
 *   E1  THE ERROR STATE IS HOUSE STYLE. Today `XeroUploadPanel` renders
 *       `{err && <div className="errorbox">{err}</div>}` where `err` is `String(e)` — so the
 *       reviewer reads a bare `"Error: Empty upload."`. `App.tsx:87-95` already has the right
 *       pattern: a plain-words lead sentence plus the server's real message in `<small>`.
 *       The upload error adopts it, and drops the `Error:` prefix.
 *   E2  THE REAL MESSAGE, VERBATIM, ALWAYS. Never "something went wrong". Every string
 *       asserted below is a real `detail` captured from the endpoint (provenance under
 *       REAL_UPLOAD_ERRORS). The reconciliation-halt 422 flows through this SAME generic
 *       state — no dedicated branch for it.
 *   E3  ERRORS GET THEIR OWN COLOUR, VIA A SCOPED MODIFIER. `.errorbox` is shared with
 *       App.tsx and AuditTrail.tsx and is styled identically to `.loading`, so an error reads
 *       as a status message. A new modifier class carries the colour; the shared base is
 *       NOT touched.
 *   E4  THE REVIEWER-NAME ADVISORY IS NOT AN ERROR. "Decision recorded locally only — enter
 *       the reviewer of record…" is a prompt, not a failure, and today it is written to the
 *       SAME `err` channel as real 422s. It splits out into its own non-error prompt.
 *   E5  THE EXISTING STATES ARE UNTOUCHED — the busy "Reading export…" line and the two
 *       pre-upload empties still render. The Review view's upload form remains the pre-upload
 *       state; no new copy is added there.
 *
 * VIEW OWNERSHIP (D-16): busy and the upload error are Review-view furniture. The reviewer-name
 * advisory can ONLY be triggered from the Findings view — the panel mounts exactly one
 * <ReviewScreen>, inside `view === "findings"` — so that is the view it is asserted on. Every
 * absence check below runs on the view that owns the element, after a presence assertion.
 */

/**
 * Real `detail` strings from `POST /review/upload`, captured 2026-07-28 against the committed
 * fixtures in `tests/fixtures/xero-real-format/`. All are HTTP 422 with a string `detail`.
 * Raise sites in `api/app.py`: 593 (empty), 658-659 (unreadable primary or ledger),
 * 611-613 (ledger suffix), 1120/1244/1328/1521 (reconciliation halt). Nothing invented.
 */
const REAL_UPLOAD_ERRORS = [
  "Empty upload.",
  "Could not read export: File is not a zip file",
  "Could not read export: \"There is no item named '[Content_Types].xml' in the archive\"",
  "The optional ledger must be a .xlsx account-transactions export.",
  // An engine-side halt, not client data. It rides the generic error state (no special branch).
  "Review could not complete over this export (reconciliation halted).",
] as const;

// A real fingerprinted row from the same endpoint run — needed so the adjudication controls are
// live (an un-fingerprinted row renders them DISABLED and could never reach the advisory).
const E4: QueueItem = {
  finding_id: "detect:E4:BILL-3002",
  check_id: "E4",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "OldRate Supplies Pte Ltd",
  severity: "MEDIUM",
  description: "GST rate 8.00% deviates from expected 9%",
  recommendation: "Review the GST rate — demo data uses 7%, production uses 9% from 1 Jan 2024.",
  doc_num: "BILL-3002",
  doc_date: "2026-04-22",
  error_code: "E4",
  display_name: "GST rate deviation from expected applicable rate",
  iras_basis: "IRAS GST Act / applicable rate schedule",
  iras_basis_caveat:
    "Illustrative citation — the IRAS basis shown is itself UNVALIDATED (T2.11 gates " +
    "customer-facing claims); verify against the e-Tax Guides before any customer use.",
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: "sha256:a6a758ae79fa77c26f3ebf773784074a7bc67f9a8eb7a67e96cec8bfa3c54edf",
  candidate_framing_text:
    "Document BILL-3002 (E4 - GST rate deviation from expected applicable rate) appears to be a " +
    "candidate for reviewer attention; consider reviewing the GST treatment for this item. This " +
    "is a candidate, not a verdict.",
  completeness: {
    required: ["sales_invoices", "purchase_invoices", "applicable_gst_rate"],
    present: ["sales_invoices", "purchase_invoices", "applicable_gst_rate"],
    missing: [],
    satisfied: true,
  },
  inputs_hash: "sha256:a8b99891a35b34b986760d0189437158fafb28dd3008c224d708c0f431141e7a",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

// The 200 body's real non-queue shape (same run). source_kind xero_f5_upload is what maps to a
// client_id, which is what makes adjudication available at all.
const OK_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer:
    "AgentAssist flags — you decide. Recomputed from transactions your uploaded Xero export " +
    "already grouped by your own tax-code assignments — the arithmetic is AgentAssist's, the " +
    "classification is yours; validation_status=unvalidated (T2.11 is the binding gate). " +
    "Findings are unvalidated candidates — not a compliance verdict.",
  coverage_status: [
    { check: "E4", level: "full", reason: "" },
    {
      check: "NO_GST_REG",
      level: "unavailable",
      reason:
        "FederalTaxID absent — NO_GST_REG cannot run; require supplier-master sheet at onboarding.",
    },
  ],
  queue: [E4],
};

/** 422 with the server's real string `detail` — the shape api.ts reads. */
function errorFetch(detail: string) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload")) {
      return Promise.resolve(new Response(JSON.stringify({ detail }), { status: 422 }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

function okFetch(body: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload")) {
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

/** A never-settling upload, so the in-flight window can be observed deterministically. */
function pendingFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/upload")) return new Promise<Response>(() => {});
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

// Copied (not imported) from the amended Xero test files — these helpers are local to each.
async function openFindings() {
  const nav = screen.getByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: "Findings" }));
}

async function openReview() {
  const nav = screen.getByRole("navigation", { name: /Primary/i });
  fireEvent.click(within(nav).getByRole("button", { name: "Review" }));
}

async function uploadPrimary() {
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

describe("C-2 error state — house style, real message, scoped colour", () => {
  afterEach(() => vi.restoreAllMocks());

  for (const detail of REAL_UPLOAD_ERRORS) {
    it(`E1/E2: surfaces the real server message verbatim — ${JSON.stringify(detail)}`, async () => {
      vi.stubGlobal("fetch", errorFetch(detail));
      render(<XeroUploadPanel onChangeSource={() => {}} />);
      await uploadPrimary();

      // Presence first: the error container lands on the Review view that owns it.
      const box = await waitFor(() => {
        const el = document.querySelector(".errorbox");
        expect(el).not.toBeNull();
        return el as HTMLElement;
      });

      // The server's own words, verbatim and complete.
      expect(box.textContent).toContain(detail);
      // In a <small>, exactly as App.tsx:87-95 frames its real message.
      const small = box.querySelector("small");
      expect(small).not.toBeNull();
      expect(small!.textContent).toBe(detail);
      // FAILS TODAY: `String(e)` on an Error yields a bare "Error: …" prefix.
      expect(box.textContent).not.toContain("Error:");
      // A plain-words lead sentence — never a generic apology.
      expect(box.textContent).not.toMatch(/something went wrong/i);
      expect(box.textContent!.replace(detail, "").trim().length).toBeGreaterThan(0);
    });
  }

  it("E3: the error carries a scoped modifier class, and the shared .errorbox base is reused", async () => {
    vi.stubGlobal("fetch", errorFetch("Empty upload."));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    const box = await waitFor(() => {
      const el = document.querySelector(".errorbox");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    // FAILS TODAY: the only class is "errorbox".
    expect(box.className).toMatch(/\berrorbox\b/); // shared base kept
    expect(box.className.split(/\s+/).filter((c) => c && c !== "errorbox").length)
      .toBeGreaterThan(0); // a scoped modifier alongside it
  });
});

describe("C-2 reviewer-name advisory is a prompt, not an error", () => {
  afterEach(() => vi.restoreAllMocks());

  it("E4: renders as a non-error prompt, outside the .errorbox error channel", async () => {
    // No /decision handler: the advisory must short-circuit BEFORE any POST is attempted.
    vi.stubGlobal("fetch", okFetch(OK_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();
    expect(await screen.findByLabelText(/Coverage preview/i)).toBeInTheDocument();

    // Reviewer of record deliberately left EMPTY — that is what triggers the advisory.
    await openFindings();
    expect(await screen.findByText(E4.display_name!)).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /Mark known/i }));
    const note = await screen.findByPlaceholderText(/required for/i);
    fireEvent.change(note, { target: { value: "Standing treatment for this supplier." } });
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));

    // Presence first: the prompt is visible on the view where the control that fired it lives.
    // FAILS TODAY: the text goes into `err`, which only renders on the Review view.
    const prompt = await screen.findByText(/enter the reviewer of record/i);
    expect(prompt).toBeInTheDocument();

    // It is NOT in the error channel (that is the whole point of the split).
    expect(prompt.closest(".errorbox")).toBeNull();
    expect(document.querySelector(".errorbox")).toBeNull();
  });
});

describe("C-2 pre-upload and busy states are unchanged", () => {
  afterEach(() => vi.restoreAllMocks());

  it("E5: the busy line renders while the upload is in flight", async () => {
    vi.stubGlobal("fetch", pendingFetch());
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    const busy = await screen.findByText("Reading export…");
    expect(busy).toBeInTheDocument();
    expect(busy.className).toMatch(/\bloading\b/);
    // In flight is not an error: nothing in the error channel yet.
    expect(document.querySelector(".errorbox")).toBeNull();
  });

  it("E5: the pre-upload empties still render, and Review keeps the form as its empty state", async () => {
    vi.stubGlobal("fetch", okFetch(OK_BODY));
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    // Review view: the upload form IS the pre-upload state — presence proves it.
    expect(document.querySelector("input.xero-file-input")).not.toBeNull();

    await openFindings();
    expect(await screen.findByText(/No findings yet/i)).toBeInTheDocument();

    const nav = screen.getByRole("navigation", { name: /Primary/i });
    fireEvent.click(within(nav).getByRole("button", { name: "Audit" }));
    expect(
      await screen.findByText(/No decision has been recorded against this export yet/i)
    ).toBeInTheDocument();

    // Back on the view that owns the form, it is still the only pre-upload affordance.
    await openReview();
    expect(document.querySelector("input.xero-file-input")).not.toBeNull();
  });
});
