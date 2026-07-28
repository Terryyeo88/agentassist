/**
 * coverageLabels.ts — reviewer-facing names for the coverage-status check ids.
 *
 * `coverage_status[]` carries `{check, level, reason}` only; the ids alone ("reg11_supplier_
 * gst_absent") are unreadable to a reviewer. This mirrors the existing precedent at
 * `report/render.py::_coverage_label` — a SELF-CONTAINED map with a raw-id fallback, and no
 * coupling to the registry — so the same treatment reads the same way on the paper and on the
 * screen.
 *
 * A self-contained map is a set of hardcoded strings, and hardcoded strings drift. This one is
 * BOUND by `tests/test_xero_coverage_labels_binding.py`, which asserts from Python that every
 * id here exists in CHECK_REGISTRY (no invented checks) and that every id a REAL upload emits
 * appears here (no unlabelled rows on the live path). If the backend adds a check, that test
 * goes red rather than the panel quietly degrading to a raw id.
 *
 * The label TEXT is presentation and is deliberately NOT bound — the report/render.py
 * precedent likewise words its labels differently from `CheckSpec.display_name`. The ID is the
 * contract. The `reason` string is never mapped: it renders verbatim from the payload.
 */
export const COVERAGE_CHECK_LABELS: Record<string, string> = {
  "DUP_CLAIM": "Duplicate input-tax claims",
  "SEQ_GAP": "Invoice sequence gaps",
  "NO_GST_REG": "Supplier GST registration",
  "E1": "Standard-rated sales on likely exports",
  "E2": "GST charged on a non-taxable supply",
  "E3": "Standard-rated supply with no GST",
  "E4": "GST rate deviation",
  "gst_amount_mismatch": "Invoice GST vs ledger GST",
  "correct_period": "Invoice date within the period",
  "total_inconsistency": "Invoice totals add up",
  "reg11_supplier_gst_absent": "Supplier GST number on the invoice face",
};

/** Friendly label for a coverage check; raw-id fallback keeps it honest (never blank). */
export function coverageLabel(check: string): string {
  return COVERAGE_CHECK_LABELS[check] ?? check;
}
