import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DocumentViewer } from "../components/DocumentViewer";

/**
 * DocumentViewer (C1 frontend) — the split-pane source-document viewer must be HONEST about
 * every backend state of GET /document/{doc_num} (PR #146):
 *   * 404 (no invoice on file) → an explicit "No source document on file" note, NOT a blank
 *     frame or a broken PDF embed.
 *   * 200 (PDF bytes) → an <object> PDF embed, labelled "Invoice <n>".
 *
 * jsdom implements neither URL.createObjectURL nor URL.revokeObjectURL, so both are stubbed;
 * fetch is stubbed per-test with a minimal response object ({status, ok, blob}) — enough for
 * the component's status/ok/blob() branch, without depending on a real Response/Blob.
 */
describe("DocumentViewer (C1) — honest states over GET /document/{doc_num}", () => {
  beforeEach(() => {
    // jsdom has no object-URL support; the component creates/revokes one on the ready path.
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => "blob:mock-url");
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the honest 'No source document on file' note on a 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ status: 404, ok: false, blob: () => Promise.resolve(new Blob()) }))
    );

    render(<DocumentViewer docNum={9999} onClose={() => {}} />);

    expect(await screen.findByText(/No source document on file/i)).toBeInTheDocument();
    // No PDF embed on the absent path.
    expect(screen.queryByLabelText("Invoice 9999")).not.toBeInTheDocument();
  });

  it("renders the <object> PDF embed labelled 'Invoice <n>' on a 200", async () => {
    const pdfBlob = new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46])], { type: "application/pdf" });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ status: 200, ok: true, blob: () => Promise.resolve(pdfBlob) }))
    );

    render(<DocumentViewer docNum={3001} onClose={() => {}} />);

    const embed = await screen.findByLabelText("Invoice 3001");
    expect(embed).toBeInTheDocument();
    expect(embed.tagName.toLowerCase()).toBe("object");
    expect(embed).toHaveAttribute("data", "blob:mock-url");
    expect(embed).toHaveAttribute("type", "application/pdf");
  });
});
