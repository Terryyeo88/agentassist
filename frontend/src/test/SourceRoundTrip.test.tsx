import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Root } from "../Root";
import { REVIEW_FIXTURE, AUDIT_FIXTURE } from "./fixtures";

/**
 * C-3 — the source-change ROUND TRIP, driven through the real <Root/>. FAILING-FIRST.
 *
 * WHY THIS FILE EXISTS. Every one of the 40 existing call sites renders the Xero panel as
 * `<XeroUploadPanel onChangeSource={() => {}} />` — a NO-OP stub. So "← Change source" is inert
 * in the test suite while being live in the app, and nothing anywhere proves the real loop
 * (chooser → surface → back → chooser) works. `Root` supplies the only real handler
 * (`Root.tsx:34`), so `Root` is what has to be driven.
 *
 * WHAT IS PINNED:
 *   R1  XERO ROUND TRIP — pick Xero, the panel mounts, "← Change source" returns to the chooser.
 *       Passes today; it is the control that proves the harness drives the real handler.
 *   R2  SAP ROUND TRIP — the same loop for the SAP surface. FAILS TODAY: `.source-back` exists
 *       only on the Xero panel, so picking SAP is a one-way trip out of the chooser.
 *   R3  FIRST-SCREEN HONESTY — the Xero card must not claim the engine is not run. FAILS TODAY:
 *       `SourceSelector.tsx:28-29` reads "Coverage only — the engine is not run", which is false
 *       (a committed F5 + 820 upload returns six findings).
 *   R4  §2 ISOLATION ACROSS A SWITCH — after SAP → chooser → Xero, no SAP furniture survives on
 *       the Xero-labelled surface. The chooser stays the only path between surfaces.
 *
 * R3 asserts the REQUIREMENTS of the copy, not one exact sentence: the wording is customer-facing
 * and Terry finalises it. Pinning his prose verbatim here would make his own reword a test
 * failure. What is pinned is what must be true of any wording — no "engine is not run" claim,
 * findings acknowledged, candidate-framed, still unvalidated.
 */

// Mirrors the RUN_REVIEW POST /command response App fires on mount, as AppNav.test.tsx and
// SourceSelector.test.tsx both construct it (neither exports it, so it is rebuilt here).
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
      dossiers: [{ finding_id: "detect:E1:958", check_id: "E1", finding_type: "deterministic" }],
      f5_summary: REVIEW_FIXTURE.f5_summary,
      available_facets: { error_code: { E1: 1 } },
      findings: [{ finding_id: "detect:E1:958", check_id: "E1", finding_type: "deterministic" }],
      remaining_facets: { error_code: { E1: 1 } },
      applied_filters: {},
      filter_rejection: null,
    },
    notes: [],
  },
};

/**
 * The Xero upload response. Verbatim shape and strings from a real POST /review/upload over the
 * committed fixtures in tests/fixtures/xero-real-format/ (captured 2026-07-28): source_kind
 * xero_f5_upload with a populated queue — i.e. THE ENGINE RAN. That is exactly what makes the
 * old card copy false, so the payload that disproves it is the one used here.
 */
const XERO_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer:
    "AgentAssist flags — you decide. Recomputed from transactions your uploaded Xero export " +
    "already grouped by your own tax-code assignments — the arithmetic is AgentAssist's, the " +
    "classification is yours; validation_status=unvalidated (T2.11 is the binding gate). " +
    "Findings are unvalidated candidates — not a compliance verdict.",
  coverage_status: [{ check: "E4", level: "full", reason: "" }],
  queue: [
    {
      finding_id: "detect:E4:BILL-3002",
      check_id: "E4",
      finding_type: "deterministic",
      group: "needs_review",
      vendor: "OldRate Supplies Pte Ltd",
      severity: "MEDIUM",
      description: "GST rate 8.00% deviates from expected 9%",
      recommendation:
        "Review the GST rate — demo data uses 7%, production uses 9% from 1 Jan 2024.",
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
        "Document BILL-3002 (E4 - GST rate deviation from expected applicable rate) appears to " +
        "be a candidate for reviewer attention; consider reviewing the GST treatment for this " +
        "item. This is a candidate, not a verdict.",
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
    },
  ],
};

/** Serves BOTH surfaces, so one mock survives a source switch mid-test. */
function bothSurfacesFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    // Order matters: /review/upload before the generic /review/.
    if (url.includes("/review/upload"))
      return Promise.resolve(new Response(JSON.stringify(XERO_BODY), { status: 200 }));
    if (url.includes("/review/"))
      return Promise.resolve(new Response(JSON.stringify(REVIEW_FIXTURE), { status: 200 }));
    if (url.includes("/audit"))
      return Promise.resolve(new Response(JSON.stringify({ entries: AUDIT_FIXTURE }), { status: 200 }));
    if (url.includes("/command"))
      return Promise.resolve(new Response(JSON.stringify(RUN_REVIEW), { status: 200 }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

const B1_CARD = /SAP B1 \(demo\)/i;
const XERO_CARD = /Xero export \(upload\)/i;

const chooser = () => document.querySelector(".source-selector");
const xeroSurface = () => document.querySelector("main.xero-upload");
const sapSurface = () => document.querySelector("main.review-home");
const backButton = () => screen.queryByRole("button", { name: /Change source/i });

function pick(card: RegExp) {
  fireEvent.click(screen.getByRole("button", { name: card }));
}

async function uploadToXero() {
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

describe("C-3 source-change round trip (real Root, real handler)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("R1 (control): Xero — chooser → panel → Change source → chooser", async () => {
    vi.stubGlobal("fetch", bothSurfacesFetch());
    render(<Root />);

    // Presence: the chooser is the boot state.
    expect(chooser()).not.toBeNull();

    pick(XERO_CARD);
    expect(xeroSurface()).not.toBeNull();
    // Presence before the absence check below (D-16): the back control is on this surface.
    expect(backButton()).not.toBeNull();
    expect(chooser()).toBeNull();

    fireEvent.click(backButton()!);

    // The loop closes: chooser back, surface gone.
    expect(chooser()).not.toBeNull();
    expect(xeroSurface()).toBeNull();
    expect(screen.getByRole("button", { name: B1_CARD })).toBeInTheDocument();
  });

  it("R1b: the round trip survives real work — an upload, then back, then a clean re-pick", async () => {
    vi.stubGlobal("fetch", bothSurfacesFetch());
    render(<Root />);
    pick(XERO_CARD);
    await uploadToXero();

    // Presence: the upload landed and its finding is on the surface.
    expect(await screen.findByLabelText(/Coverage preview/i)).toBeInTheDocument();
    const reviewer = screen.getByPlaceholderText(/decisions and sign-off are attributed/i);
    fireEvent.change(reviewer, { target: { value: "Round Trip Tester" } });
    expect((reviewer as HTMLInputElement).value).toBe("Round Trip Tester");

    fireEvent.click(backButton()!);
    expect(chooser()).not.toBeNull();

    // Re-pick: the panel remounts with NOTHING carried over (unmount clears all its state).
    pick(XERO_CARD);
    expect(xeroSurface()).not.toBeNull();
    expect(screen.queryByLabelText(/Coverage preview/i)).toBeNull();
    expect(
      (screen.getByPlaceholderText(/decisions and sign-off are attributed/i) as HTMLInputElement)
        .value
    ).toBe("");
  });

  it("R2: SAP — chooser → review surface → Change source → chooser", async () => {
    vi.stubGlobal("fetch", bothSurfacesFetch());
    render(<Root />);

    pick(B1_CARD);

    // Presence first: the SAP surface really mounted (its composer is SAP-only furniture).
    expect(await screen.findByPlaceholderText(/Ask the assistant/i)).toBeInTheDocument();
    expect(sapSurface()).not.toBeNull();

    // FAILS TODAY: there is no back control on the SAP surface — picking SAP is one-way.
    const back = backButton();
    expect(back).not.toBeNull();

    fireEvent.click(back!);

    expect(chooser()).not.toBeNull();
    expect(sapSurface()).toBeNull();
    expect(screen.getByRole("button", { name: XERO_CARD })).toBeInTheDocument();
  });

  it("R3: the Xero card does not claim the engine is not run", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<Root />);

    const card = screen.getByRole("button", { name: XERO_CARD });
    const copy = card.textContent ?? "";

    // FAILS TODAY: the card reads "Coverage only — the engine is not run."
    expect(copy).not.toMatch(/engine is not run/i);
    expect(copy).not.toMatch(/coverage only/i);

    // What any wording must still do: name the source, acknowledge findings, stay a candidate.
    expect(copy).toMatch(/xero/i);
    expect(copy).toMatch(/finding/i);
    expect(copy).toMatch(/candidate/i);
    expect(copy).toMatch(/unvalidated/i);
    // Nothing may imply the source is validated or that a finding is a verdict.
    expect(copy).not.toMatch(/\bverified\b|\bvalidated\b(?!\s*[—-])/i);
  });

  it("R4 (§2): switching SAP → Xero leaves no SAP furniture on the Xero surface", async () => {
    vi.stubGlobal("fetch", bothSurfacesFetch());
    render(<Root />);

    pick(B1_CARD);
    // Presence: SAP furniture is really here before asserting it is gone later.
    expect(await screen.findByPlaceholderText(/Ask the assistant/i)).toBeInTheDocument();

    fireEvent.click(backButton()!);
    pick(XERO_CARD);

    // Presence: we are on the Xero surface — the view that owns the absence checks below.
    expect(xeroSurface()).not.toBeNull();
    // The SAP composer and the SAP review home are gone; the surfaces never co-exist.
    expect(screen.queryByPlaceholderText(/Ask the assistant/i)).toBeNull();
    expect(sapSurface()).toBeNull();
    // And the Xero surface shows no findings from the SAP payload.
    expect(screen.queryByText("Far East Imports")).toBeNull();
  });
});
