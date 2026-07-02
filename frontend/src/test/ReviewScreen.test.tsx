import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReviewScreen } from "../components/ReviewScreen";
import { REVIEW_FIXTURE } from "./fixtures";

/**
 * ReviewScreen (BUILD 2, A1) — FAILING-FIRST.
 *
 * The Queue+FindingDetail pair is extracted into a shared <ReviewScreen> that BOTH the SAP
 * path (App) and the Xero upload path mount. The extraction must be behavior-preserving:
 *   - WITH an injected `adjudication` capability (the SAP path) → findings render as
 *     candidates AND the decision + sign controls appear, exactly as before.
 *   - WITHOUT `adjudication` (the Xero upload — no server-side store to sign) → findings
 *     still render as candidates, but the decision/sign controls are ABSENT and an honest
 *     review-only note is surfaced. No dead controls (no-fake-affordances rule).
 */
describe("ReviewScreen (BUILD 2 A1 — shared central screen)", () => {
  const q = REVIEW_FIXTURE.queue;

  it("FT3: SAP path (adjudication injected) renders findings as candidates with decision + sign", () => {
    render(
      <ReviewScreen
        queue={q}
        selectedId={q[0].finding_id}
        onSelect={() => {}}
        activeTab="needs_review"
        setActiveTab={() => {}}
        adjudication={{ decided: {}, onRecord: vi.fn(), onOpenSign: vi.fn() }}
      />
    );

    // Candidate framing preserved verbatim.
    expect(screen.getByText(/candidate for review only/i)).toBeInTheDocument();
    expect(screen.getByText(/AgentAssist flags/i)).toBeInTheDocument();
    // The finding itself renders.
    expect(screen.getByText(q[0].display_name!)).toBeInTheDocument();
    // Decision + sign controls present (the SAP capability).
    expect(screen.getByRole("button", { name: /^Accept$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Record decision/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sign working paper/i })).toBeInTheDocument();
  });

  it("review-only (no adjudication) renders candidates but NO decision/sign controls", () => {
    render(
      <ReviewScreen
        queue={q}
        selectedId={q[0].finding_id}
        onSelect={() => {}}
        activeTab="needs_review"
        setActiveTab={() => {}}
        reviewOnlyNote="Review-only — sign-off for uploads not yet available."
      />
    );

    // Findings still framed as candidates.
    expect(screen.getByText(/candidate for review only/i)).toBeInTheDocument();
    expect(screen.getByText(/AgentAssist flags/i)).toBeInTheDocument();
    // Honest review-only note surfaced.
    expect(screen.getByText(/sign-off for uploads not yet available/i)).toBeInTheDocument();
    // No dead controls.
    expect(screen.queryByRole("button", { name: /Record decision/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Sign working paper/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Accept$/ })).toBeNull();
  });
});
