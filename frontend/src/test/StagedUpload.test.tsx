import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { XeroUploadPanel } from "../components/XeroUploadPanel";

/**
 * Slice A / A1 — STAGED UPLOAD.
 *
 * Before this build the primary file input uploaded as a side effect of its own onChange:
 * selecting the F5 was the run. That made the ledger and the source documents second-class —
 * they had to be attached BEFORE the primary or they were silently left out of the request —
 * and it gave the reviewer no moment to check what was about to be sent.
 *
 * After: selecting any file only STAGES it. Nothing reaches the network until the reviewer
 * presses "Run review", which sends the primary, the ledger and every document together in
 * ONE request, under ONE freshly created session.
 *
 * Every call here is selected BY URL, never by position — `calls[0]` is a filed brittleness
 * pattern in this tree (see LedgerUpload.test.tsx's AMENDED header).
 */

const RID_1 = "r_stagedrun0001";
const RID_2 = "r_stagedrun0002";

const UPLOAD_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags — you decide.",
  coverage_status: [],
  queue: [],
};

/** Records every request by URL so tests never index into fetch.mock.calls positionally. */
function stagingFetch() {
  const sessions: string[] = [];
  const uploads: FormData[] = [];
  let issued = 0;
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/review-session")) {
      issued += 1;
      const rid = issued === 1 ? RID_1 : RID_2;
      sessions.push(rid);
      return Promise.resolve(new Response(JSON.stringify({ review_id: rid }), { status: 200 }));
    }
    if (url.includes("/review/upload")) {
      uploads.push(init?.body as FormData);
      return Promise.resolve(new Response(JSON.stringify(UPLOAD_BODY), { status: 200 }));
    }
    if (url.includes("/decisions/")) {
      return Promise.resolve(new Response(JSON.stringify({ entries: [] }), { status: 200 }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
  return { mock, sessions, uploads };
}

function xlsx(name: string) {
  return new File([new Uint8Array([1, 2, 3])], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

function pdf(name: string) {
  return new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], name, { type: "application/pdf" });
}

function stagePrimary(name = "f5.xlsx") {
  const input = screen.getByLabelText(/upload .xlsx gst export/i) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [xlsx(name)] } });
}

function stageLedger(name = "ledger.xlsx") {
  const input = screen.getByLabelText(/820 account-transactions/i) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [xlsx(name)] } });
}

function stageDocuments(names: string[]) {
  const input = screen.getByLabelText(/source-document PDFs/i) as HTMLInputElement;
  fireEvent.change(input, { target: { files: names.map(pdf) } });
}

function runButton() {
  return screen.getByRole("button", { name: /run review/i });
}

function urlsOf(mock: ReturnType<typeof vi.fn>) {
  return mock.mock.calls.map((c) => String(c[0]));
}

describe("Slice A / A1 — staged upload, then an explicit Run review", () => {
  afterEach(() => vi.restoreAllMocks());

  it("A1-T1: selecting files fires NO network request", async () => {
    const { mock } = stagingFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stageLedger();
    stageDocuments(["BILL-3002.pdf", "BILL-3003.pdf"]);
    stagePrimary();

    // Not "no upload" — NO request at all. Staging is inert.
    expect(mock).not.toHaveBeenCalled();
  });

  it("A1-T2: the staged manifest names the primary, the ledger and every document", async () => {
    const { mock } = stagingFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    const manifest = () => screen.getByRole("region", { name: /staged for this run/i });

    stagePrimary("AgentAssist_IRAS_F5.xlsx");
    expect(manifest()).toHaveTextContent("AgentAssist_IRAS_F5.xlsx");
    // With nothing attached the manifest says so rather than hiding the row.
    expect(manifest()).toHaveTextContent(/ledger[\s\S]*none/i);

    stageLedger("AgentAssist_Account_Transactions.xlsx");
    expect(manifest()).toHaveTextContent("AgentAssist_Account_Transactions.xlsx");

    stageDocuments(["BILL-3002.pdf", "BILL-3003.pdf", "INV-2003.pdf"]);
    expect(manifest()).toHaveTextContent(/3 source documents/i);
    expect(manifest()).toHaveTextContent("BILL-3002.pdf");
    expect(manifest()).toHaveTextContent("BILL-3003.pdf");
    expect(manifest()).toHaveTextContent("INV-2003.pdf");
  });

  it("A1-T3: a staged item can be removed, and the primary can be replaced", async () => {
    const { mock } = stagingFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stagePrimary("first.xlsx");
    stageLedger("ledger.xlsx");
    stageDocuments(["BILL-3002.pdf"]);

    const manifest = () => screen.getByRole("region", { name: /staged for this run/i });
    expect(manifest()).toHaveTextContent("ledger.xlsx");

    fireEvent.click(screen.getByRole("button", { name: /remove the staged ledger/i }));
    expect(manifest()).not.toHaveTextContent("ledger.xlsx");
    expect(manifest()).toHaveTextContent(/ledger[\s\S]*none/i);

    fireEvent.click(screen.getByRole("button", { name: /remove the staged source documents/i }));
    expect(manifest()).not.toHaveTextContent("BILL-3002.pdf");

    // Replacing the primary swaps the name; it never appends a second primary.
    stagePrimary("second.xlsx");
    expect(manifest()).toHaveTextContent("second.xlsx");
    expect(manifest()).not.toHaveTextContent("first.xlsx");

    expect(mock).not.toHaveBeenCalled();
  });

  it("A1-T4: Run review is disabled until a primary is staged", async () => {
    const { mock } = stagingFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    expect(runButton()).toBeDisabled();

    // A ledger alone is not a run — the primary export is the required part.
    stageLedger();
    expect(runButton()).toBeDisabled();

    stagePrimary();
    expect(runButton()).toBeEnabled();
  });

  it("A1-T5: one click = exactly ONE session and ONE upload carrying all three parts", async () => {
    const { mock, sessions, uploads } = stagingFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stagePrimary("f5.xlsx");
    stageLedger("ledger.xlsx");
    stageDocuments(["BILL-3002.pdf", "BILL-3003.pdf"]);
    fireEvent.click(runButton());

    await waitFor(() => expect(uploads).toHaveLength(1));

    // Selected by URL, not by position.
    const sessionCalls = urlsOf(mock).filter((u) => u.includes("/review-session"));
    const uploadCalls = urlsOf(mock).filter((u) => u.includes("/review/upload"));
    expect(sessionCalls).toHaveLength(1);
    expect(uploadCalls).toHaveLength(1);

    const form = uploads[0];
    expect((form.get("file") as File).name).toBe("f5.xlsx");
    expect((form.get("ledger") as File).name).toBe("ledger.xlsx");
    expect(form.get("review_id")).toBe(sessions[0]);
    const docs = form.getAll("documents") as File[];
    expect(docs.map((d) => d.name)).toEqual(["BILL-3002.pdf", "BILL-3003.pdf"]);
  });

  it("A1-T6: Run review is disabled while a run is in flight (no double submit)", async () => {
    const releases: Array<() => void> = [];
    const uploads: FormData[] = [];
    const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/review-session")) {
        return Promise.resolve(new Response(JSON.stringify({ review_id: RID_1 }), { status: 200 }));
      }
      if (url.includes("/review/upload")) {
        uploads.push(init?.body as FormData);
        return new Promise<Response>((resolve) => {
          releases.push(() => resolve(new Response(JSON.stringify(UPLOAD_BODY), { status: 200 })));
        });
      }
      if (url.includes("/decisions/")) {
        return Promise.resolve(new Response(JSON.stringify({ entries: [] }), { status: 200 }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stagePrimary();
    fireEvent.click(runButton());

    await waitFor(() => expect(uploads).toHaveLength(1));
    expect(runButton()).toBeDisabled();

    // A second click while in flight must not queue another upload.
    fireEvent.click(runButton());
    expect(uploads).toHaveLength(1);

    releases.forEach((r) => r());
    await waitFor(() => expect(runButton()).toBeEnabled());
    expect(uploads).toHaveLength(1);
  });

  it("A1-T7: re-staging after a completed run does NOT auto-run, and says so", async () => {
    const { mock, uploads } = stagingFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stagePrimary("first.xlsx");
    fireEvent.click(runButton());
    await waitFor(() => expect(uploads).toHaveLength(1));

    // Change the staging after the run: nothing may fire on its own.
    stagePrimary("second.xlsx");
    stageDocuments(["BILL-3002.pdf"]);
    expect(uploads).toHaveLength(1);

    // And the panel must SAY the screen is now behind the staging, rather than leave a
    // stale result looking current.
    expect(screen.getByText(/not been run yet/i)).toBeInTheDocument();
  });

  it("A1-T8: pressing Run review again starts a NEW session (PROPOSED: new run = new session)", async () => {
    const { mock, sessions, uploads } = stagingFetch();
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stagePrimary("first.xlsx");
    fireEvent.click(runButton());
    await waitFor(() => expect(uploads).toHaveLength(1));

    stagePrimary("second.xlsx");
    fireEvent.click(runButton());
    await waitFor(() => expect(uploads).toHaveLength(2));

    // Accumulating BOTH runs into one session is G-8 (the accumulated-sign wiring) and is
    // deliberately out of this slice's scope. Recorded as a PROPOSED decision for Terry.
    expect(sessions).toEqual([RID_1, RID_2]);
    expect(uploads[1].get("review_id")).toBe(RID_2);
    expect((uploads[1].get("file") as File).name).toBe("second.xlsx");

    // The stale-staging notice clears once the staging has actually been run.
    expect(screen.queryByText(/not been run yet/i)).not.toBeInTheDocument();
  });

  it("A1-T9: a failed session is still non-fatal when no documents are staged", async () => {
    // Load-bearing compatibility (D-43 / T8): six existing test files reject POST
    // /review-session and stay green only because a session failure is tolerated when no
    // documents are attached. Staging must not harden that into a fatal error.
    const uploads: FormData[] = [];
    const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/review-session")) return Promise.reject(new Error("session backend down"));
      if (url.includes("/review/upload")) {
        uploads.push(init?.body as FormData);
        return Promise.resolve(new Response(JSON.stringify(UPLOAD_BODY), { status: 200 }));
      }
      if (url.includes("/decisions/")) {
        return Promise.resolve(new Response(JSON.stringify({ entries: [] }), { status: 200 }));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    stagePrimary();
    fireEvent.click(runButton());

    await waitFor(() => expect(uploads).toHaveLength(1));
    expect(uploads[0].get("review_id")).toBeNull();
  });
});
