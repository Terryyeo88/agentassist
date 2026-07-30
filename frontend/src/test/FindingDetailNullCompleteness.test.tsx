import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FindingDetail } from "../components/FindingDetail";
import type { QueueItem } from "../api";

/**
 * D-47 defence-in-depth (T7): a null completeness must not white-screen the app.
 * The PRIMARY fix is the backend contract (test_queue_item_contract.py T1 binds it);
 * this guard is the client-side belt for any future projection that slips a null
 * through — the block is omitted, never a crash.
 */
const ITEM = {
  finding_id: "doccheck:gst_amount_mismatch:BILL-3002",
  check_id: "gst_amount_mismatch",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "OldRate Supplies Pte Ltd",
  severity: "MEDIUM",
  description: "Consider reviewing whether the GST amount agrees.",
  recommendation: null,
  doc_num: "BILL-3002",
  doc_date: "2026-04-22",
  error_code: "gst_amount_mismatch",
  display_name: "GST amount on invoice PDF differs from SAP line item",
  iras_basis: null,
  iras_basis_caveat: "Illustrative citation — unvalidated.",
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: null,
  candidate_framing_text: "Candidate, not a verdict.",
  completeness: null,
  inputs_hash: "sha256:0",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
} as unknown as QueueItem;

describe("FindingDetail — null completeness guard (D-47)", () => {
  it("renders without crashing and omits the completeness block", () => {
    render(<FindingDetail item={ITEM} onViewDocument={() => {}} />);
    expect(screen.getByText(/GST amount on invoice PDF differs/i)).toBeInTheDocument();
    expect(screen.queryByText(/Completeness:/i)).not.toBeInTheDocument();
  });
});
