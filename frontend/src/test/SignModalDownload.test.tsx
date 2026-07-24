import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SignModal } from "../components/SignModal";

/**
 * SignModalDownload (C2 frontend) — after a working paper is signed, the modal must offer a
 * DOWNLOAD of the PDF via the read-only backend route GET /working-paper?path=… (PR #144),
 * not just print the server-side path string.
 *
 * Pinned here (mirrors the backend route contract):
 *   * The success state renders a Download link whose href is `/api/working-paper?path=` +
 *     encodeURIComponent(working_paper_path). This covers BOTH sign transports — /sign and
 *     /sign/upload — because SignModal takes the sign call as an injected transport and both
 *     return working_paper_path (the injected transport here stands in for either).
 *
 * SignModal's inputs are not label-associated, so the reviewer field is addressed by role index
 * (it is the first/autoFocus textbox). The injected transport ignores its args and resolves with
 * a fixed result, so a non-empty reviewer is all that's needed to reach the success state.
 */
describe("SignModal working-paper download (C2)", () => {
  it("renders a Download link to GET /working-paper with the encoded path after sign-off", async () => {
    const wpPath = "/repo/exploration-notes/t1.4-reports/working paper 2024Q3.pdf";
    const signTransport = () =>
      Promise.resolve({
        reviewer_name: "Collin Tan",
        firm_name: "Acme LLP",
        working_paper_path: wpPath,
      });

    render(<SignModal onClose={() => {}} onSigned={() => {}} sign={signTransport} />);

    // Reviewer is the first textbox (autoFocus); firm is the second. Only reviewer is required.
    const reviewer = screen.getAllByRole("textbox")[0];
    fireEvent.change(reviewer, { target: { value: "Collin Tan" } });
    fireEvent.click(screen.getByRole("button", { name: /sign and emit working paper/i }));

    const link = await screen.findByRole("link", { name: /download working paper/i });
    const href = link.getAttribute("href") ?? "";
    expect(href).toContain("/api/working-paper?path=");
    expect(href).toContain(encodeURIComponent(wpPath));
    // The raw server path is still shown as text (honest provenance is preserved).
    expect(screen.getByText(wpPath)).toBeInTheDocument();
  });
});
