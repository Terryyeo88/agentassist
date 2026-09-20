import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { XeroUploadPanel } from "../components/XeroUploadPanel";

/**
 * C-8 upload flow: the session is created LAZILY, ON UPLOAD, ALWAYS (D-43) — one
 * POST /review-session per upload flow, its review_id carried on the upload's
 * FormData, and N attached source documents sent as N repeated "documents" parts
 * (D-38). T8 pins the compatibility decision that keeps every pre-session test
 * green: session creation is ATTEMPTED always, but a creation failure is fatal
 * ONLY when documents are attached (they need the session — D-37's no-silent-drop);
 * with no documents the upload proceeds stateless, exactly the pre-C-8 shape.
 */

const RID = "r_c8session001";

const UPLOAD_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags — you decide.",
  coverage_status: [],
  queue: [],
};

function sessionAwareFetch(opts?: { failSession?: boolean }) {
  const uploads: FormData[] = [];
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/review-session")) {
      if (opts?.failSession) {
        return Promise.reject(new Error("session backend down"));
      }
      return Promise.resolve(
        new Response(JSON.stringify({ review_id: RID }), { status: 200 })
      );
    }
    if (url.includes("/review/upload")) {
      uploads.push(init?.body as FormData);
      return Promise.resolve(new Response(JSON.stringify(UPLOAD_BODY), { status: 200 }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
  return { mock, uploads };
}

function attachDocuments(files: File[]) {
  const input = screen.getByLabelText(/source-document PDFs/i) as HTMLInputElement;
  fireEvent.change(input, { target: { files } });
}

async function uploadPrimary() {
  const input = screen.getByLabelText(/upload .xlsx gst export/i) as HTMLInputElement;
  const file = new File([new Uint8Array([1, 2, 3])], "f5.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  fireEvent.change(input, { target: { files: [file] } });
  // AMENDED (Slice A, staged upload): selecting a file now only STAGES it — the run is an
  // explicit button press, so the primary, the ledger and the documents go in ONE request.
  // Mechanical step only; every assertion in this file keeps its original meaning.
  fireEvent.click(screen.getByRole("button", { name: /run review/i }));
  await waitFor(() => expect(screen.queryByText(/Reading export/i)).not.toBeInTheDocument());
}

function pdf(name: string) {
  return new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], name, { type: "application/pdf" });
}

describe("XeroUploadPanel — session-on-upload (C-8 / D-43)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("T6: creates the session EXACTLY once per upload and carries its review_id", async () => {
    const { mock, uploads } = sessionAwareFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    attachDocuments([pdf("BILL-3002.pdf")]);
    await uploadPrimary();

    const sessionCalls = mock.mock.calls.filter((c) => String(c[0]).includes("/review-session"));
    expect(sessionCalls).toHaveLength(1);
    expect(uploads).toHaveLength(1);
    expect(uploads[0].get("review_id")).toBe(RID);
  });

  it("T7: N attached documents send N repeated 'documents' parts", async () => {
    const { mock, uploads } = sessionAwareFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    attachDocuments([pdf("BILL-3001.pdf"), pdf("BILL-3002.pdf"), pdf("INV-2001.pdf")]);
    await uploadPrimary();

    expect(uploads).toHaveLength(1);
    const parts = uploads[0].getAll("documents");
    expect(parts).toHaveLength(3);
    expect(parts.map((p) => (p as File).name)).toEqual([
      "BILL-3001.pdf",
      "BILL-3002.pdf",
      "INV-2001.pdf",
    ]);
  });

  it("T8: no documents attached — no 'documents' parts, same rendering; a session failure is non-fatal", async () => {
    // Half 1: working backend — session still created (D-43 ALWAYS), no documents parts.
    const { mock, uploads } = sessionAwareFetch();
    vi.stubGlobal("fetch", mock);
    const first = render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    expect(uploads).toHaveLength(1);
    expect(uploads[0].getAll("documents")).toHaveLength(0);
    expect(uploads[0].get("review_id")).toBe(RID);
    expect(screen.getByText(/Data coverage/i)).toBeInTheDocument();
    first.unmount();
    vi.restoreAllMocks();

    // Half 2: session creation FAILS with no documents attached — the upload proceeds
    // stateless (the pre-C-8 shape; what every pre-session test's fetch mock exercises).
    const failing = sessionAwareFetch({ failSession: true });
    vi.stubGlobal("fetch", failing.mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    await uploadPrimary();

    expect(failing.uploads).toHaveLength(1);
    expect(failing.uploads[0].get("review_id")).toBeNull();
    expect(failing.uploads[0].getAll("documents")).toHaveLength(0);
    expect(screen.getByText(/Data coverage/i)).toBeInTheDocument();
  });
});
