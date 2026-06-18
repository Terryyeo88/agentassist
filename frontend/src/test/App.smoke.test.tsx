import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { App } from "../App";
import { AUDIT_FIXTURE, REVIEW_FIXTURE } from "./fixtures";

/**
 * Render smoke test over a REAL-SHAPED fixture: the queue + finding detail render, the
 * UNVALIDATED trust badge is present, the genuinely-seeded demoted doc-592 entry appears,
 * and NO fictional check types (DUP_CLAIM / SEQ_GAP / FLUX) are anywhere in the DOM.
 */
function mockFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/review/")) {
      return Promise.resolve(new Response(JSON.stringify(REVIEW_FIXTURE), { status: 200 }));
    }
    if (url.includes("/audit")) {
      return Promise.resolve(
        new Response(JSON.stringify({ entries: AUDIT_FIXTURE }), { status: 200 })
      );
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

describe("App review surface (render smoke)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch());
  });

  it("renders the queue, detail card, and the UNVALIDATED badge", async () => {
    render(<App />);

    // Queue renders the real check types (E1 is in the default Needs-review tab;
    // the demoted NO_GST_REG entry lives under Marked known — covered separately).
    await waitFor(() => expect(screen.getAllByText("E1").length).toBeGreaterThan(0));

    // UNVALIDATED trust badge present (loud).
    expect(screen.getAllByText(/unvalidated/i).length).toBeGreaterThan(0);

    // Detail card shows the selected finding's vendor + IRAS caveat.
    const detail = await screen.findByText(/Standard-rated sales on likely export/i);
    expect(detail).toBeInTheDocument();
    expect(screen.getAllByText(/Illustrative citation/i).length).toBeGreaterThan(0);

    // Sign action present.
    expect(screen.getByRole("button", { name: /Sign working paper/i })).toBeInTheDocument();
  });

  it("surfaces the genuinely-seeded demoted doc-592 entry in 'Marked known'", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("E1").length).toBeGreaterThan(0));

    const knownTab = screen.getByRole("tab", { name: /Marked known/i });
    knownTab.click();

    await waitFor(() => {
      const list = screen.getByRole("tablist").parentElement!;
      expect(within(list).getByText("Far East Imports")).toBeInTheDocument();
    });
  });

  it("never renders the mock's fictional check types", async () => {
    const { container } = render(<App />);
    await waitFor(() => expect(screen.getAllByText("E1").length).toBeGreaterThan(0));
    for (const fictional of ["DUP_CLAIM", "SEQ_GAP", "FLUX"]) {
      expect(container.innerHTML).not.toContain(fictional);
    }
  });

  it("command bar is live (enabled input + Ask + intent buttons)", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("E1").length).toBeGreaterThan(0));
    const input = screen.getByPlaceholderText(/Ask the assistant/i);
    expect(input).not.toBeDisabled();
    expect(screen.getByRole("button", { name: /^Ask$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Prior decisions/i })).toBeInTheDocument();
    // It mentions surface-context identity (one way in), not the old inert-shell copy.
    expect(screen.getByText(/identity comes from the surface context/i)).toBeInTheDocument();
  });
});
