import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FindingDetail } from "../components/FindingDetail";
import type { QueueItem } from "../api";

/**
 * Bucket-B wiring for FindingDetail:
 *  - B6: surface `doc_date` and `error_code` in the finding meta line (already in the payload,
 *        never shown here before).
 *  - B4: show prior-decision history (annotation + prior_dispositions) on ANY row that carries
 *        it — previously it rendered ONLY on demoted rows, so a non-demoted finding with prior
 *        dispositions showed nothing. Honest: the row stays an active candidate.
 * Pure display; fields already exist in QUEUE_ITEM_KEYS. No contract change.
 */

const BASE: Omit<
  QueueItem,
  "demoted" | "annotation" | "prior_dispositions" | "doc_date" | "error_code"
> = {
  finding_id: "detect:E1:958",
  check_id: "E1",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "SG Electronics",
  severity: "MEDIUM",
  description: "A candidate for reviewer adjudication.",
  recommendation: "Review and decide.",
  doc_num: 958 as unknown as number,
  display_name: "Standard-rated sales on likely export/overseas supply",
  iras_basis: "IRAS GST Act s21(3).",
  iras_basis_caveat: "Illustrative citation — the IRAS basis shown is itself UNVALIDATED.",
  fingerprint: "sha256:abc",
  candidate_framing_text: "Candidate for review.",
  completeness: { required: [], present: [], missing: [], satisfied: true },
  inputs_hash: "—",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

describe("FindingDetail meta + prior-decision wiring (bucket B)", () => {
  it("B6: surfaces doc_date and error_code in the meta line", () => {
    const item: QueueItem = {
      ...BASE,
      doc_date: "2024-07-02",
      error_code: "E1",
      demoted: false,
      annotation: null,
      prior_dispositions: [],
    };
    const { container } = render(<FindingDetail item={item} />);
    expect(container.textContent).toMatch(/2024-07-02/);
    expect(container.textContent).toMatch(/Code\s+E1/);
  });

  it("B4: shows prior-decision history on a NON-demoted row that carries it", () => {
    const item: QueueItem = {
      ...BASE,
      doc_date: "2024-07-02",
      error_code: "E1",
      demoted: false,
      annotation: "Previously adjudicated 1 time(s); most recent: REJECTED by J. Tan (2024Q2).",
      prior_dispositions: ["REJECTED"],
    };
    render(<FindingDetail item={item} />);
    expect(screen.getByText(/Prior decisions on file/i)).toBeInTheDocument();
    expect(screen.getByText(/REJECTED/)).toBeInTheDocument();
    // Still framed as an active candidate, not a verdict.
    expect(screen.getByText(/still an active candidate/i)).toBeInTheDocument();
  });

  it("does not duplicate: a DEMOTED row shows the known callout, not the non-demoted note", () => {
    const item: QueueItem = {
      ...BASE,
      doc_date: "2024-07-16",
      error_code: "NO_GST_REG",
      demoted: true,
      annotation: "Previously adjudicated; most recent: KNOWN_ACCEPTED (2024Q2).",
      prior_dispositions: ["KNOWN_ACCEPTED"],
    };
    render(<FindingDetail item={item} />);
    expect(screen.getByText(/Marked known from a prior period/i)).toBeInTheDocument();
    expect(screen.queryByText(/Prior decisions on file/i)).not.toBeInTheDocument();
  });

  it("shows no prior-decision note when there is no history", () => {
    const item: QueueItem = {
      ...BASE,
      doc_date: null as unknown as string,
      error_code: "E1",
      demoted: false,
      annotation: null,
      prior_dispositions: [],
    };
    render(<FindingDetail item={item} />);
    expect(screen.queryByText(/Prior decisions on file/i)).not.toBeInTheDocument();
  });
});
