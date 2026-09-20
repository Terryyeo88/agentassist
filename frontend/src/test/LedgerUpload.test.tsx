import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";

/**
 * PR-3 front-end — optional ledger upload. FAILING-FIRST.
 *
 * The Xero upload panel gains an OPTIONAL second file input (the 820 account-transactions
 * ledger export). uploadExtract switches to multipart FormData carrying the primary `file`
 * plus the optional `ledger`. Omitting the ledger sends only `file`.
 *
 * AMENDED (C-8 / D-43, 2026-07-29). The upload flow now makes TWO requests: POST
 * /review-session, then POST /review/upload — the session is created lazily, on upload,
 * always. Two assertions here selected the upload as calls[0] and pinned
 * toHaveBeenCalledTimes(1); both were POSITIONAL PROXIES for the property this file
 * actually protects, which is that the ledger part rides on the upload request. They now
 * select by URL, which is what they always meant. Nothing is weakened: the route
 * assertion has not been dropped, it has become the selector.
 */

const OK_BODY = {
  source_kind: "xero_f5_upload",
  validation_status: "unvalidated",
  disclaimer: "unvalidated demo",
  coverage_status: [{ check: "E2", level: "full", reason: "" }],
  queue: [],
};

function captureFetch() {
  const calls: { url: string; body: unknown }[] = [];
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body });
    // C-8 (D-43): answer each route with its OWN shape. Before the amendment this mock
    // returned OK_BODY for everything, so the new session POST would have yielded
    // review_id: undefined — a backend that does not exist.
    if (url.includes("/review-session")) {
      return Promise.resolve(
        new Response(JSON.stringify({ review_id: "rev-test-0001" }), { status: 200 }),
      );
    }
    return Promise.resolve(new Response(JSON.stringify(OK_BODY), { status: 200 }));
  });
  return { fn, calls };
}

function xlsx(name: string): File {
  return new File([new Uint8Array([1, 2, 3])], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

describe("Xero upload — optional ledger (PR-3)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders a second, ledger file input distinct from the primary", () => {
    render(<XeroUploadPanel onChangeSource={() => {}} />);
    const primary = screen.getByLabelText(/upload .* export/i);
    const ledger = screen.getByLabelText(/ledger/i);
    expect(primary).not.toBeNull();
    expect(ledger).not.toBeNull();
    expect(primary).not.toBe(ledger);
  });

  it("sends multipart FormData with file + ledger when a ledger is attached", async () => {
    const { fn, calls } = captureFetch();
    vi.stubGlobal("fetch", fn);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    const ledgerInput = screen.getByLabelText(/ledger/i) as HTMLInputElement;
    Object.defineProperty(ledgerInput, "files", { value: [xlsx("Account_Transactions.xlsx")] });
    fireEvent.change(ledgerInput);

    const primaryInput = screen.getByLabelText(/upload .* export/i) as HTMLInputElement;
    Object.defineProperty(primaryInput, "files", { value: [xlsx("F5.xlsx")] });
    fireEvent.change(primaryInput);
    // AMENDED (Slice A, staged upload): staging no longer runs; the run is an explicit press.
    fireEvent.click(screen.getByRole("button", { name: /run review/i }));

    // C-8 (D-43): the upload flow now makes TWO requests — POST /review-session then
    // POST /review/upload. Select the upload call by URL rather than by position: this
    // test protects "the ledger was sent on the upload request", never "the upload was
    // first". The route assertion has not been dropped — it is now the selector.
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/review/upload"))).toBe(true),
    );
    const upload = calls.find((c) => c.url.includes("/review/upload"))!;
    expect(upload.body).toBeInstanceOf(FormData);
    const form = upload.body as FormData;
    expect((form.get("file") as File).name).toBe("F5.xlsx");
    expect((form.get("ledger") as File).name).toBe("Account_Transactions.xlsx");
  });

  it("sends only the file part when no ledger is attached", async () => {
    const { fn, calls } = captureFetch();
    vi.stubGlobal("fetch", fn);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    const primaryInput = screen.getByLabelText(/upload .* export/i) as HTMLInputElement;
    Object.defineProperty(primaryInput, "files", { value: [xlsx("F5.xlsx")] });
    fireEvent.change(primaryInput);
    // AMENDED (Slice A, staged upload): staging no longer runs; the run is an explicit press.
    fireEvent.click(screen.getByRole("button", { name: /run review/i }));

    // Same URL selection as above, same reason.
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/review/upload"))).toBe(true),
    );
    const form = calls.find((c) => c.url.includes("/review/upload"))!.body as FormData;
    expect((form.get("file") as File).name).toBe("F5.xlsx");
    expect(form.get("ledger")).toBeNull();
  });
});
