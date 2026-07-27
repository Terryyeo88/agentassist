import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReviewScreen } from "../components/ReviewScreen";
import { Queue } from "../components/Queue";
import { FindingDetail } from "../components/FindingDetail";
import { REVIEW_FIXTURE } from "./fixtures";

/**
 * Source-tag guard (Commit 1 — defence-in-depth for §2) — FAILING-FIRST.
 *
 * Two NEW optional props are added to each of ReviewScreen, Queue, and FindingDetail:
 *   - expectedSource?: "sap" | "xero"  — the source this mount is FOR. OPT-IN: when omitted,
 *     the guard is inert and the component renders exactly as today.
 *   - sourceKind?: string | null       — the source identity of the payload being rendered.
 *
 * Source families:
 *   "b1_demo" → sap
 *   "xero_f5_upload" | "extract_review" | "extract_upload" | "xero_sales_upload" → xero
 *   anything else (incl. undefined/null/unrecognised) → unknown (always a mismatch).
 *
 * If expectedSource is set AND the sourceKind family !== expectedSource, the component renders
 * an honest mismatch state (role="alert", text /data source mismatch/i) and WITHHOLDS the data.
 *
 * These props don't exist yet, so until implemented the components ignore them and render the
 * data / show no alert. That RED state is correct and intended. Tested through the component
 * public props only — no sourceGuard module is imported.
 */

// SAP-shaped queue / item from the frozen fixture.
const SAP_QUEUE = REVIEW_FIXTURE.queue;
const SAP_ITEM = REVIEW_FIXTURE.queue[0];
// The E1 / SG Electronics finding's display name — the data that must be WITHHELD on mismatch.
const SAP_DISPLAY_NAME = "Standard-rated sales on likely export/overseas supply";
const SAP_VENDOR = "SG Electronics";

describe("Source-tag guard (Commit 1 — defence-in-depth for §2)", () => {
  // 1) Core guard — each shared component refuses SAP data on a Xero-labelled mount.
  it("ReviewScreen refuses SAP data on a Xero-labelled mount (withholds + alerts)", () => {
    render(
      <ReviewScreen
        queue={SAP_QUEUE}
        selectedId={SAP_ITEM.finding_id}
        onSelect={() => {}}
        activeTab="needs_review"
        setActiveTab={() => {}}
        expectedSource="xero"
        sourceKind="b1_demo"
      />
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/data source mismatch/i);
    // The SAP finding data must NOT render.
    expect(screen.queryByText(SAP_DISPLAY_NAME)).toBeNull();
  });

  it("Queue refuses SAP data on a Xero-labelled mount (withholds + alerts)", () => {
    render(
      <Queue
        items={SAP_QUEUE}
        decided={{}}
        activeTab="needs_review"
        setActiveTab={() => {}}
        selectedId={SAP_ITEM.finding_id}
        onSelect={() => {}}
        expectedSource="xero"
        sourceKind="b1_demo"
      />
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/data source mismatch/i);
    // The SAP vendor row must NOT render.
    expect(screen.queryByText(SAP_VENDOR)).toBeNull();
  });

  it("FindingDetail refuses SAP data on a Xero-labelled mount (withholds + alerts)", () => {
    render(<FindingDetail item={SAP_ITEM} expectedSource="xero" sourceKind="b1_demo" />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/data source mismatch/i);
    // The SAP finding data must NOT render.
    expect(screen.queryByText(SAP_DISPLAY_NAME)).toBeNull();
  });

  // 2) Matching source renders normally (no regression).
  it("ReviewScreen renders normally when a Xero mount receives a Xero payload", () => {
    render(
      <ReviewScreen
        queue={SAP_QUEUE}
        selectedId={SAP_ITEM.finding_id}
        onSelect={() => {}}
        activeTab="needs_review"
        setActiveTab={() => {}}
        expectedSource="xero"
        sourceKind="xero_f5_upload"
      />
    );

    expect(screen.getByText(SAP_DISPLAY_NAME)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ReviewScreen renders normally when a SAP mount receives a SAP payload", () => {
    render(
      <ReviewScreen
        queue={SAP_QUEUE}
        selectedId={SAP_ITEM.finding_id}
        onSelect={() => {}}
        activeTab="needs_review"
        setActiveTab={() => {}}
        expectedSource="sap"
        sourceKind="b1_demo"
      />
    );

    expect(screen.getByText(SAP_DISPLAY_NAME)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  // 3) Absent / unknown sourceKind → mismatch.
  it("ReviewScreen treats an absent sourceKind as a mismatch (withholds + alerts)", () => {
    render(
      <ReviewScreen
        queue={SAP_QUEUE}
        selectedId={SAP_ITEM.finding_id}
        onSelect={() => {}}
        activeTab="needs_review"
        setActiveTab={() => {}}
        expectedSource="xero"
        sourceKind={undefined}
      />
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/data source mismatch/i);
    expect(screen.queryByText(SAP_DISPLAY_NAME)).toBeNull();
  });

  it("ReviewScreen treats an unrecognised sourceKind as a mismatch (withholds + alerts)", () => {
    render(
      <ReviewScreen
        queue={SAP_QUEUE}
        selectedId={SAP_ITEM.finding_id}
        onSelect={() => {}}
        activeTab="needs_review"
        setActiveTab={() => {}}
        expectedSource="xero"
        sourceKind="something_unrecognised"
      />
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/data source mismatch/i);
    expect(screen.queryByText(SAP_DISPLAY_NAME)).toBeNull();
  });

  // 4) Opt-in / backward-compat — no expectedSource renders normally.
  it("ReviewScreen renders normally when the guard is opt-out (no expectedSource/sourceKind)", () => {
    render(
      <ReviewScreen
        queue={SAP_QUEUE}
        selectedId={SAP_ITEM.finding_id}
        onSelect={() => {}}
        activeTab="needs_review"
        setActiveTab={() => {}}
      />
    );

    expect(screen.getByText(SAP_DISPLAY_NAME)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
