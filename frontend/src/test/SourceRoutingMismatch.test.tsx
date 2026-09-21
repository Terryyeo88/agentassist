import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";

/**
 * D6 (UI half) — R-3 / G-5: the chosen source is stated, and a mismatch is surfaced.
 *
 * D-2026-09-21-unmapped-codes. The server used to route uploads on FILE SHAPE alone: a
 * workbook matching neither Xero detector fell through to the general-extract branch and
 * was reviewed under `extract_demo` — a config with a tax-code vocabulary and an expected
 * rate that are not the uploader's — with nothing on screen saying so.
 *
 *   T1  The panel STATES its source. Every POST /review/upload from this surface carries
 *       `source=xero`, on the run and on the re-apply alike.
 *   T2  The server's mismatch message is surfaced VERBATIM. The wording is mechanical —
 *       what was expected, what arrived — and the UI must not soften, summarise or
 *       replace it, because the real message is the only thing that says what went wrong.
 *
 * The 422 body below is the REAL `detail` string this endpoint now raises, copied from the
 * API-level test in tests/test_source_routing_and_paper.py — nothing invented.
 */

const MISMATCH_DETAIL =
  "Expected a Xero export (the 'Transactions by box number' F5 workbook or a Xero " +
  "sales-invoice export); the uploaded file 'extract.xlsx' is neither.";

function fetchMock(status: number, body: unknown) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    const url = String(input);
    if (url.includes("/review-session"))
      return Promise.resolve(
        new Response(JSON.stringify({ review_id: "r_abc" }), { status: 200 })
      );
    if (url.includes("/decisions/"))
      return Promise.resolve(
        new Response(
          JSON.stringify({ client_id: "xero_demo", entries: [], chain_length: 0 }),
          { status: 200 }
        )
      );
    if (url.includes("/review/upload"))
      return Promise.resolve(new Response(JSON.stringify(body), { status }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

function stageAndRun(name = "extract.xlsx") {
  const input = document.querySelector(
    "input.xero-file-input:not(.xero-ledger-input)"
  ) as HTMLInputElement | null;
  expect(input).not.toBeNull();
  const file = new File([new Uint8Array([1, 2, 3])], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  Object.defineProperty(input as HTMLInputElement, "files", { value: [file] });
  fireEvent.change(input as HTMLInputElement);
  fireEvent.click(screen.getByRole("button", { name: /run review/i }));
}

describe("R-3 — the chosen source is stated and a mismatch is surfaced", () => {
  afterEach(() => vi.restoreAllMocks());

  it("T1: the upload carries source=xero", async () => {
    const mock = fetchMock(200, {
      source_kind: "xero_f5_upload",
      validation_status: "unvalidated",
      disclaimer: "AgentAssist flags — you decide.",
      coverage_status: [],
      queue: [],
    });
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    stageAndRun("AgentAssist_IRAS_F5.xlsx");

    await waitFor(() => {
      const call = mock.mock.calls.find(([u]) => String(u).includes("/review/upload"));
      expect(call).toBeTruthy();
    });
    const call = mock.mock.calls.find(([u]) => String(u).includes("/review/upload"))!;
    const form = (call[1] as RequestInit).body as FormData;
    expect(form.get("source")).toBe("xero");
  });

  it("T2: a mismatched file surfaces the server's mechanical message verbatim", async () => {
    vi.stubGlobal("fetch", fetchMock(422, { detail: MISMATCH_DETAIL }));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    stageAndRun("extract.xlsx");

    expect(await screen.findByText(MISMATCH_DETAIL)).toBeInTheDocument();
  });

  it("T2b: the message is not softened or replaced", async () => {
    vi.stubGlobal("fetch", fetchMock(422, { detail: MISMATCH_DETAIL }));
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    stageAndRun("extract.xlsx");

    await screen.findByText(MISMATCH_DETAIL);
    for (const invented of [/try again/i, /something went wrong/i, /unsupported/i]) {
      expect(screen.queryByText(invented)).toBeNull();
    }
  });
});
