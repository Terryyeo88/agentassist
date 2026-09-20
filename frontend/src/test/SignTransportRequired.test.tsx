import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { XeroUploadPanel } from "../components/XeroUploadPanel";

/**
 * Slice A / A5 — G-6: SignModal must never fall back to the FROZEN sign path.
 *
 * At eba8aeb `sign` was optional (SignModal.tsx:17) and line 57 read
 * `await (signTransport ?? postSign)(...)` — so a mount that forgot the prop signed the
 * FROZEN SBODEMOSG artifacts via POST /sign. That path renders NO adjudications (confirmed
 * live 2026-09-20: the frozen paper contains no "Reviewer adjudications" section), and it
 * would hand a Xero reviewer a working paper for a DIFFERENT COMPANY behind a convincing
 * "Signed by …" success state.
 *
 * Nothing reached it at eba8aeb — but only by convention: the Xero panel happened to pass the
 * prop. This slice makes the type system carry that instead of the convention.
 */

const RID = "r_signtransport1";

const SRC = resolve(__dirname, "../components/SignModal.tsx");

describe("Slice A / A5 — G-6: the frozen sign path is unreachable by omission", () => {
  afterEach(() => vi.restoreAllMocks());

  it("A5-T1: SignModal neither imports nor references the frozen postSign", () => {
    const src = readFileSync(SRC, "utf8");
    expect(src).not.toMatch(/\bpostSign\b/);
  });

  it("A5-T2: the `sign` prop is REQUIRED, so omitting it fails the build", () => {
    const src = readFileSync(SRC, "utf8");
    // `sign?:` would restore the hole; `sign:` is the contract this slice installs.
    expect(src).not.toMatch(/\bsign\?\s*:/);
    expect(src).toMatch(/\bsign\s*:\s*\(/);
    // And no defaulting survives anywhere in the file.
    expect(src).not.toMatch(/signTransport\s*\?\?/);
  });

  it("A5-T3: the Xero panel's sign calls /sign/upload and never the frozen /sign", async () => {
    const signCalls: string[] = [];
    const mock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/review-session")) {
        return Promise.resolve(new Response(JSON.stringify({ review_id: RID }), { status: 200 }));
      }
      if (url.includes("/decisions/")) {
        return Promise.resolve(
          new Response(JSON.stringify({ client_id: "xero_demo", entries: [], chain_length: 0, validation_status: "unvalidated", disclaimer: "d" }), { status: 200 })
        );
      }
      if (url.includes("/review/upload")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              source_kind: "xero_f5_upload",
              validation_status: "unvalidated",
              disclaimer: "AgentAssist flags — you decide.",
              coverage_status: [],
              queue: [],
            }),
            { status: 200 }
          )
        );
      }
      if (url.includes("/sign/upload")) {
        signCalls.push("upload");
        return Promise.resolve(
          new Response(
            JSON.stringify({
              source_kind: "xero_f5_signed",
              reviewer_name: "Recon Session",
              firm_name: "Recon Firm",
              working_paper_path: "C:/tmp/paper.pdf",
              bundle_dir: "C:/tmp/bundle",
              validation_status: "unvalidated",
              disclaimer: "AgentAssist flags — you decide.",
            }),
            { status: 200 }
          )
        );
      }
      if (url.endsWith("/sign") || url.includes("/api/sign?")) {
        signCalls.push("FROZEN");
        return Promise.reject(new Error("the Xero panel must never POST the frozen /sign"));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal("fetch", mock);
    render(<XeroUploadPanel onChangeSource={() => {}} />);

    fireEvent.change(screen.getByLabelText(/upload .xlsx gst export/i), {
      target: {
        files: [
          new File([new Uint8Array([1, 2, 3])], "f5.xlsx", {
            type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          }),
        ],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /run review/i }));
    await waitFor(() => expect(screen.queryByText(/Reading export/i)).not.toBeInTheDocument());

    // The TopBar sign pill is named `reviewerName || "Sign in"`; no name has been entered
    // here, so it is "Sign in". (The in-panel Sign button lives on a finding's card, and this
    // fixture's queue is deliberately empty — the sign entry point is what matters, not which.)
    fireEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

    // SignModal's labels are not htmlFor-associated, so the reviewer field is addressed as
    // the first input WITHIN the dialog (reviewer, then firm) rather than by label text.
    const modal = await screen.findByText("Sign working paper");
    const dialog = modal.closest(".modal") as HTMLElement;
    const reviewerInput = dialog.querySelectorAll("input")[0] as HTMLInputElement;
    fireEvent.change(reviewerInput, { target: { value: "Recon Session" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Sign and emit working paper/i }));

    await waitFor(() => expect(signCalls).toContain("upload"));
    expect(signCalls).not.toContain("FROZEN");
  });
});
