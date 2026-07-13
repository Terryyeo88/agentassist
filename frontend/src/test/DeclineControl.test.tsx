import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FindingDetail } from "../components/FindingDetail";
import { REVIEW_FIXTURE } from "./fixtures";

/**
 * DECLINE adjudication control (review surface) — FAILING-FIRST.
 *
 * Front-end only. "Decline" is a DISTINCT decision (separate from "Not an issue"),
 * it REQUIRES a reviewer note, and it records through the EXISTING `onRecord` path
 * (no new endpoint, no QUEUE_ITEM_KEYS change). Renders only where `onRecord` is
 * injected (the demo/SAP path) — this test injects it.
 */
describe("Decline adjudication control (FindingDetail)", () => {
  const item = REVIEW_FIXTURE.queue[0];

  it("renders 'Decline' as a distinct decision, separate from 'Not an issue'", () => {
    render(<FindingDetail item={item} onRecord={vi.fn()} onOpenSign={vi.fn()} />);

    const decline = screen.getByRole("button", { name: /^Decline$/ });
    const notAnIssue = screen.getByRole("button", { name: /^Not an issue$/ });
    expect(decline).toBeInTheDocument();
    expect(notAnIssue).toBeInTheDocument();
    // Distinct controls, not the same button relabelled.
    expect(decline).not.toBe(notAnIssue);
    // The other two decisions still present (no regression to the decision set).
    expect(screen.getByRole("button", { name: /^Accept$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Mark known$/ })).toBeInTheDocument();
  });

  it("selecting Decline requires a note — empty note blocks record and does NOT call onRecord", () => {
    const onRecord = vi.fn();
    render(<FindingDetail item={item} onRecord={onRecord} onOpenSign={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /^Decline$/ }));
    // A note field appears because Decline is note-required.
    expect(screen.getByPlaceholderText(/required for/i)).toBeInTheDocument();

    // Record with an empty note → blocked, error shown, onRecord never fires.
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));
    expect(screen.getByText(/requires a non-empty reviewer note/i)).toBeInTheDocument();
    expect(onRecord).not.toHaveBeenCalled();
  });

  it("records via onRecord with the Decline decision and the reviewer note", () => {
    const onRecord = vi.fn();
    render(<FindingDetail item={item} onRecord={onRecord} onOpenSign={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /^Decline$/ }));
    fireEvent.change(screen.getByPlaceholderText(/required for/i), {
      target: { value: "Disagree — invoice is a valid zero-rated export." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));

    expect(onRecord).toHaveBeenCalledTimes(1);
    expect(onRecord).toHaveBeenCalledWith(
      "Decline",
      "Disagree — invoice is a valid zero-rated export."
    );
  });
});
