import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../App";
import { XeroUploadPanel } from "../components/XeroUploadPanel";
import { REVIEW_FIXTURE } from "./fixtures";

/**
 * C-5 — the dead notifications bell is GONE from the shared TopBar. FAILING-FIRST: written
 * before the deletion, so it must go RED today for the right reason (the bell still renders).
 *
 * What was removed and why (§8 — no dead controls). TopBar carried:
 *
 *     <button className="bell" aria-label="Notifications">
 *       <span className="bell-dot" aria-hidden="true" />
 *       <span aria-hidden="true">◔</span>
 *     </button>
 *
 * with NO onClick, NO state, and NO prop feeding it — while its three sibling controls
 * (`onToggleSidebar`, `setView`, `onOpenSign`) all carry handlers. Nothing fed it on either
 * side of the wire: `api.ts` exposes no notifications field and `api/app.py` serves no
 * notifications route. So it was a control that silently did nothing. Worse, `.bell-dot`
 * rendered UNCONDITIONALLY — a permanent "you have unread notifications" signal with no data
 * behind it, on a surface whose rule is that trust signals are carried through from the server
 * verbatim. §8 allows remove OR disable-with-a-visible-reason; the removal is the decision here,
 * because there is no reason text to give that is not itself an invention.
 *
 * D-16 — an absence is only meaningful after a presence assertion, on a surface where the thing
 * WOULD render. TopBar is shared and mounts on BOTH surfaces (App.tsx:125 for SAP,
 * XeroUploadPanel.tsx:267 for Xero), outside the view branches, so the bell would render on
 * every view of both. Each case below therefore asserts a REAL, staying TopBar control first —
 * the sidebar toggle (`aria-label="Toggle sidebar"`) and the loud UNVALIDATED trust badge —
 * proving the header actually rendered, and only then asserts the bell's absence.
 *
 * THREE-TIMES RULE: "no dead notifications bell, and no fabricated unread dot" is stated in the
 * TopBar source comment where the control used to sit, enforced by its deletion from TopBar.tsx
 * (and of the orphaned `.bell` / `.bell-dot` rules from app.css), and asserted here.
 */

const RUN_REVIEW = {
  kind: "result",
  classifier_mode: "scripted",
  disclaimer: "read-only over frozen artifacts — never writes back to SAP.",
  intent: "RUN_REVIEW",
  execution: {
    intent: "RUN_REVIEW",
    outcome: "executed",
    sequence: ["run_review_chain"],
    tiers: [1],
    params: { client_id: "sbodemosg", period: "2024Q3" },
    data: {
      review_result: {},
      dossiers: [],
      f5_summary: REVIEW_FIXTURE.f5_summary,
      available_facets: {},
      findings: [],
      remaining_facets: {},
      applied_filters: {},
      filter_rejection: null,
    },
    notes: [],
  },
};

// The SAP surface holds its TopBar behind a loaded GET /review, so that one call is stubbed.
// The Xero surface needs no stub at all — XeroUploadPanel has no mount-time effect (§2
// box-isolation: mounting it fires no SAP fetch), so its TopBar renders on a bare mount.
function mockFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/command")) {
      return Promise.resolve(new Response(JSON.stringify(RUN_REVIEW), { status: 200 }));
    }
    if (url.includes("/review/")) {
      return Promise.resolve(new Response(JSON.stringify(REVIEW_FIXTURE), { status: 200 }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

/** The absence half, shared by both surfaces — every trace of the control, not just its role. */
function expectNoBell(container: HTMLElement) {
  // The control itself: an accessible <button> named "Notifications".
  expect(screen.queryByRole("button", { name: /notifications/i })).not.toBeInTheDocument();
  // ...and its markup, since the dot is aria-hidden and so invisible to a role query.
  expect(container.querySelector(".bell")).toBeNull();
  expect(container.querySelector(".bell-dot")).toBeNull();
  // The fabricated unread signal, and the glyph it was drawn with.
  expect(container.innerHTML).not.toContain("◔");
}

describe("C-5: the dead notifications bell is removed from the shared TopBar", () => {
  beforeEach(() => vi.stubGlobal("fetch", mockFetch()));
  afterEach(() => vi.restoreAllMocks());

  it("SAP surface: the top bar renders its real controls, and carries no notifications bell", async () => {
    const { container } = render(<App />);

    // PRESENCE FIRST (D-16): the header really rendered on this surface.
    expect(await screen.findByRole("button", { name: /toggle sidebar/i })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: /primary/i })).toBeInTheDocument();
    expect(screen.getAllByText(/unvalidated/i).length).toBeGreaterThan(0);

    expectNoBell(container);
  });

  it("Xero surface: the top bar renders its real controls, and carries no notifications bell", async () => {
    // `onChangeSource` is required here (C-3: Root always supplies it); the bar under test
    // does not use it, so a noop is enough to mount the surface.
    const { container } = render(<XeroUploadPanel onChangeSource={() => {}} />);

    // PRESENCE FIRST (D-16): the shared header rendered here too, pre-upload.
    expect(await screen.findByRole("button", { name: /toggle sidebar/i })).toBeInTheDocument();
    expect(screen.getAllByText(/unvalidated/i).length).toBeGreaterThan(0);

    expectNoBell(container);
  });
});
