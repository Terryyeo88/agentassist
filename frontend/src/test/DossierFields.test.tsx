import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FindingDetail } from "../components/FindingDetail";
import type { QueueItem } from "../api";

/**
 * Bucket-B wiring: surface the dossier fields (completeness + inputs_hash) as reviewer-facing
 * UI in <FindingDetail>, instead of leaving them only inside the collapsed technical block.
 *
 * These fields already ship in QUEUE_ITEM_KEYS (populated on Xero uploads by #133) — this is a
 * pure display wiring, no contract change. Honest-by-rule: an INCOMPLETE dossier must read
 * "incomplete" and name what is missing (never hidden); a complete one reads "complete"; and
 * the frozen path (no completeness data) shows no completeness block rather than noise.
 */

const BASE: Omit<QueueItem, "completeness" | "inputs_hash"> = {
  finding_id: "detect:E1:958",
  check_id: "E1",
  finding_type: "deterministic",
  error_code: "E1",
  group: "needs_review",
  vendor: "SG Electronics",
  severity: "MEDIUM",
  description: "A candidate for reviewer adjudication.",
  recommendation: "Review and decide.",
  doc_num: 958 as unknown as number,
  doc_date: "2024-07-02",
  display_name: "Standard-rated sales on likely export/overseas supply",
  iras_basis: "IRAS GST Act s21(3).",
  iras_basis_caveat: "Illustrative citation — the IRAS basis shown is itself UNVALIDATED.",
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: "sha256:fcc8439a",
  candidate_framing_text: "Candidate for review: possible export treatment mismatch.",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

describe("FindingDetail dossier-field wiring (bucket B)", () => {
  it("surfaces an INCOMPLETE completeness state and names the missing inputs", () => {
    const item: QueueItem = {
      ...BASE,
      completeness: {
        required: ["invoice", "tax_code", "gst_amount"],
        present: ["invoice"],
        missing: ["tax_code (not on export)", "gst_amount (absent)"],
        satisfied: false,
      },
      inputs_hash: "sha256:deadbeef",
    };
    const { container } = render(<FindingDetail item={item} />);

    // Honest incomplete state is visible in the card body (not only the collapsed <details>).
    expect(screen.getByText(/Completeness: incomplete/i)).toBeInTheDocument();
    // Both missing inputs are named.
    expect(container.textContent).toMatch(/tax_code \(not on export\)/);
    expect(container.textContent).toMatch(/gst_amount \(absent\)/);
    // Present/required counts are shown.
    expect(container.textContent).toMatch(/1 of\s+3 required inputs present/i);
    // inputs_hash surfaced as a reviewer-facing provenance line.
    expect(container.textContent).toMatch(/Inputs hash/i);
    expect(container.textContent).toMatch(/sha256:deadbeef/);
  });

  it("shows a COMPLETE state when all required inputs are present", () => {
    const item: QueueItem = {
      ...BASE,
      completeness: {
        required: ["invoice", "tax_code"],
        present: ["invoice", "tax_code"],
        missing: [],
        satisfied: true,
      },
      inputs_hash: "sha256:cafe",
    };
    render(<FindingDetail item={item} />);
    expect(screen.getByText(/Completeness: complete/i)).toBeInTheDocument();
    expect(screen.queryByText(/Completeness: incomplete/i)).not.toBeInTheDocument();
  });

  it("omits the completeness block and the inputs-hash line when there is no dossier data (frozen path)", () => {
    const item: QueueItem = {
      ...BASE,
      completeness: { required: [], present: [], missing: [], satisfied: true },
      inputs_hash: "—",
    };
    const { container } = render(<FindingDetail item={item} />);
    expect(screen.queryByText(/Completeness:/i)).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Inputs hash/i);
  });
});
