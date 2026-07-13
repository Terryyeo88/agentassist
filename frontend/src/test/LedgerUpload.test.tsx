import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { XeroUploadPanel } from "../components/XeroUploadPanel";

/**
 * PR-3 front-end — optional ledger upload. FAILING-FIRST.
 *
 * The Xero upload panel gains an OPTIONAL second file input (the 820 account-transactions
 * ledger export). uploadExtract switches to multipart FormData carrying the primary `file`
 * plus the optional `ledger`. Omitting the ledger sends only `file`.
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
    calls.push({ url: String(input), body: init?.body });
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

    expect(fn).toHaveBeenCalledTimes(1);
    const { url, body } = calls[0];
    expect(url).toContain("/review/upload");
    expect(body).toBeInstanceOf(FormData);
    const form = body as FormData;
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

    expect(fn).toHaveBeenCalledTimes(1);
    const form = calls[0].body as FormData;
    expect((form.get("file") as File).name).toBe("F5.xlsx");
    expect(form.get("ledger")).toBeNull();
  });
});
