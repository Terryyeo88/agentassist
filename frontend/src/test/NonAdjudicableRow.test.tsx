import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FindingDetail } from "../components/FindingDetail";
import type { QueueItem } from "../api";

/**
 * No-silent-dead-buttons on the shared <FindingDetail> (B3a-2) -- FAILING-FIRST.
 *
 * Written BEFORE the implementation; MUST fail today for the RIGHT reason -- FindingDetail has
 * NO disabled state: whenever `onRecord` is provided (adjudication active) it renders the four
 * decision buttons ENABLED and the "Record decision" button fires `onRecord` for ANY row,
 * including rows that cannot be persisted (fingerprint null). B3a-2's rule: when a row's
 * `fingerprint` is null AND adjudication is active, the decision buttons render DISABLED with a
 * VISIBLE honest reason keyed per cause -- never hidden, never a no-op button. This covers BOTH
 * the Xero upload panel and the SAP App surface (the frozen SAP queue carries a probabilistic
 * row doc:gst_amount_mismatch:958 with fingerprint null).
 *
 * THREE-TIMES RULE: the "no persistable fingerprint -> disabled + honest reason, never a dead
 * button" invariant is pinned in the panel prompt/spec, will be enforced in FindingDetail code,
 * and is asserted here. The backend half (detect rows fingerprinted, ledger-recon rows None)
 * lives in tests/test_b3a2_fingerprint_always_uploads.py.
 *
 *   B1 -- ledger-recon row (finding_id "ledger_recon:*", fingerprint null): the four decision
 *         buttons are PRESENT but DISABLED, an honest reason matching
 *         /not persistable[\s\S]*ledger[- ]reconciliation/i is visible, and the Record control
 *         cannot fire onRecord. FAILS TODAY (buttons enabled; Record fires onRecord).
 *   B2 -- probabilistic row (finding_type "probabilistic", fingerprint null): same disabled
 *         state, reason matching /not persistable[\s\S]*probabilistic/i. FAILS TODAY.
 *   B3 -- fingerprinted detect row: buttons ENABLED (control case -- passes today and after).
 */

const BASE: Omit<QueueItem, "finding_id" | "check_id" | "finding_type" | "error_code" |
  "display_name" | "vendor" | "fingerprint"> = {
  group: "needs_review",
  severity: "MEDIUM",
  description: "A candidate for reviewer adjudication.",
  recommendation: "Review and decide.",
  doc_num: 958 as unknown as number,
  doc_date: "2024-07-02",
  iras_basis: "Internal-consistency check -- not an IRAS-cited finding.",
  iras_basis_caveat: "Illustrative citation -- the IRAS basis shown is itself UNVALIDATED.",
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  candidate_framing_text: "Candidate for review only.",
  completeness: { required: [], present: [], missing: [], satisfied: false },
  inputs_hash: "-",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

// A ledger-recon row: no counterparty, deliberately un-fingerprinted (#46). finding_id prefix
// "ledger_recon:" is the per-cause key the disabled reason is chosen from.
const LEDGER_ROW: QueueItem = {
  ...BASE,
  finding_id: "ledger_recon:ledger_recon_divergence:output",
  check_id: "GST_LEDGER_RECON",
  finding_type: "deterministic",
  error_code: "LEDGER_RECON",
  display_name: "Ledger vs declared-return divergence",
  vendor: null,
  fingerprint: null,
};

// A probabilistic row (the frozen SAP doc:gst_amount_mismatch:958): finding_type
// "probabilistic" is the per-cause key; fingerprint null -> not persistable.
const PROBABILISTIC_ROW: QueueItem = {
  ...BASE,
  finding_id: "doc:gst_amount_mismatch:958",
  check_id: "gst_amount_mismatch",
  finding_type: "probabilistic",
  error_code: "gst_amount_mismatch",
  display_name: "GST amount mismatch (probabilistic)",
  vendor: "SG Electronics",
  fingerprint: null,
};

// A normal fingerprinted detect row -- persistable; buttons must stay enabled.
const DETECT_ROW: QueueItem = {
  ...BASE,
  finding_id: "detect:E4:BILL-3002",
  check_id: "E4",
  finding_type: "deterministic",
  error_code: "E4",
  display_name: "Stale GST rate applied",
  vendor: "OldRate Supplies Pte Ltd",
  fingerprint: "sha256:265e9b4e92baa689143df7f1384560a0f337d325105d38c8499c6595c42b159e",
};

const DECISION_NAMES = ["Accept", "Decline", "Not an issue", "Mark known"] as const;

describe("FindingDetail no-silent-dead-buttons (B3a-2)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("B1: a ledger-recon row disables the decision buttons with an honest reason", () => {
    const onRecord = vi.fn();
    const { container } = render(
      <FindingDetail item={LEDGER_ROW} onRecord={onRecord} onOpenSign={() => {}} />
    );

    // Present but DISABLED -- never hidden.
    for (const name of DECISION_NAMES) {
      const btn = screen.getByRole("button", { name });
      expect(btn).toBeInTheDocument();
      expect(btn).toBeDisabled();
    }

    // A visible honest reason keyed to the ledger-reconciliation cause.
    expect(container.textContent).toMatch(/not persistable[\s\S]*ledger[- ]reconciliation/i);

    // The Record control cannot fire onRecord (never a no-op button that silently does nothing
    // useful, and never a live persist on an un-persistable row).
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));
    expect(onRecord).not.toHaveBeenCalled();
  });

  it("B2: a probabilistic row disables the decision buttons with an honest reason", () => {
    const onRecord = vi.fn();
    const { container } = render(
      <FindingDetail item={PROBABILISTIC_ROW} onRecord={onRecord} onOpenSign={() => {}} />
    );

    for (const name of DECISION_NAMES) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(container.textContent).toMatch(/not persistable[\s\S]*probabilistic/i);

    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));
    expect(onRecord).not.toHaveBeenCalled();
  });

  it("B3 (control): a fingerprinted detect row keeps the decision buttons enabled", () => {
    const onRecord = vi.fn();
    render(<FindingDetail item={DETECT_ROW} onRecord={onRecord} onOpenSign={() => {}} />);

    for (const name of DECISION_NAMES) {
      expect(screen.getByRole("button", { name })).toBeEnabled();
    }
    // A persistable row records normally (default "Accept" needs no note).
    fireEvent.click(screen.getByRole("button", { name: /Record decision/i }));
    expect(onRecord).toHaveBeenCalledTimes(1);
  });
});
