import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DocumentViewer } from "../components/DocumentViewer";

/**
 * C-8: the viewer resolves uploaded documents via the review-scoped route (D-42).
 *
 * SURFACE SELECTION, not fallback (Terry's ruling): the Xero surface passes a
 * reviewId and the viewer uses /api/review/{rid}/document/{ref}; the SAP surface
 * passes none and the viewer uses /api/document/{ref}. One attempt each, chosen by
 * which surface is mounted — D-42's two-routes-two-namespaces structure applied at
 * the client. A FALLBACK (try the review route, then reach into the SAP corpus on
 * failure) is what the ruling bans and T9 makes unwritable: with a reviewId a 404
 * is FINAL — exactly one fetch, and /api/document/ is never called.
 *
 * T2 pins the ruled no-review_id behaviour: WITHOUT a reviewId the viewer never
 * fetches the review route — it keeps today's legacy-route behaviour (the SAP
 * surface's contract, pinned by DocumentViewer.test.tsx / DocumentViewerRef.test.tsx,
 * which pass unamended). Safe for a mis-threaded Xero surface only because D-34
 * makes the legacy route REFUSE cross-namespace references (404, honest body)
 * rather than substitute.
 */

const RID = "r_c8test000001";

function okPdf() {
  const blob = new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46])], { type: "application/pdf" });
  return Promise.resolve({ status: 200, ok: true, blob: () => Promise.resolve(blob) });
}

describe("DocumentViewer — review-scoped route (C-8 / D-42)", () => {
  beforeEach(() => {
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => "blob:mock-url");
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it("T1: with a reviewId, fetches the review-scoped route with the exact URL", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) => okPdf());
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentViewer docNum="BILL-3002" reviewId={RID} onClose={() => {}} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls.map((c) => String(c[0]))[0]).toBe(`/api/review/${RID}/document/BILL-3002`);
  });

  it("T2: without a reviewId, never fetches the review route (surface selection)", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) => okPdf());
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentViewer docNum="BILL-3002" onClose={() => {}} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.every((u) => !u.includes("/api/review/"))).toBe(true);
    expect(urls[0]).toBe("/api/document/BILL-3002");
  });

  it("T3: the reference passes VERBATIM — not stripped to digits, not uppercased", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) => okPdf());
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentViewer docNum="Bill-3002x" reviewId={RID} onClose={() => {}} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls.map((c) => String(c[0]))[0]).toBe(`/api/review/${RID}/document/Bill-3002x`);
  });

  it("T4: a 404 from the review route renders the honest absent state, not an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ status: 404, ok: false, blob: () => Promise.resolve(new Blob()) }))
    );

    render(<DocumentViewer docNum="BILL-3002" reviewId={RID} onClose={() => {}} />);

    expect(await screen.findByText(/No source document on file/i)).toBeInTheDocument();
    expect(screen.queryByText(/Couldn.t load the source document/i)).not.toBeInTheDocument();
  });

  it("T5: a non-404 failure renders the error state, distinct from absent", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ status: 500, ok: false, blob: () => Promise.resolve(new Blob()) }))
    );

    render(<DocumentViewer docNum="BILL-3002" reviewId={RID} onClose={() => {}} />);

    expect(await screen.findByText(/Couldn.t load the source document/i)).toBeInTheDocument();
    expect(screen.queryByText(/No source document on file/i)).not.toBeInTheDocument();
  });

  it("T9: with a reviewId, a 404 is FINAL — exactly one fetch, /api/document/ never called", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) =>
      Promise.resolve({ status: 404, ok: false, blob: () => Promise.resolve(new Blob()) })
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentViewer docNum="BILL-3002" reviewId={RID} onClose={() => {}} />);

    expect(await screen.findByText(/No source document on file/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/api/document/"))).toBe(false);
  });
});
