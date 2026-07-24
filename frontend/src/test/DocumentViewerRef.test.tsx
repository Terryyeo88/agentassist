import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DocumentViewer } from "../components/DocumentViewer";

/**
 * DocumentViewerRef (C1 follow-up) — the viewer must accept a non-numeric Xero DocNum
 * (e.g. "BILL-3003") and fetch it as a STRING reference, not coerce it through Number()
 * (which would produce NaN and a broken request). The backend /document/{doc_ref} route
 * resolves the digits to the INV-<n>.pdf fixture.
 *
 * jsdom implements neither URL.createObjectURL nor URL.revokeObjectURL, so both are stubbed;
 * fetch is stubbed with a minimal 200 response object carrying a blob.
 */
describe("DocumentViewer (C1) — Xero string document references", () => {
  beforeEach(() => {
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => "blob:mock-url");
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it("fetches the raw string ref (BILL-3003) and renders the <object> on a 200 blob", async () => {
    const pdfBlob = new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46])], { type: "application/pdf" });
    const fetchMock = vi.fn((_url: string) =>
      Promise.resolve({ status: 200, ok: true, blob: () => Promise.resolve(pdfBlob) })
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentViewer docNum="BILL-3003" onClose={() => {}} />);

    // The request carries the string ref verbatim — never Number("BILL-3003") === NaN.
    const embed = await screen.findByLabelText("Invoice BILL-3003");
    expect(embed.tagName.toLowerCase()).toBe("object");
    expect(embed).toHaveAttribute("data", "blob:mock-url");

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/document/BILL-3003");
    expect(url).not.toContain("NaN");
  });
});
