import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { XeroF5Strip } from "../components/XeroF5Strip";
import type { RecomputedF5Boxes } from "../api";

/**
 * Xero F5 box strip (t-xero-f5-render, STEP 1) — FAILING-FIRST.
 *
 * The backend has emitted `recomputed_client_coded_f5_boxes` on the xero_f5_upload branch
 * since PR #151; nothing rendered it. This pins the three rules that make rendering it
 * honest rather than merely present:
 *
 *   (1) NO BOXES KEY -> RENDER NOTHING. The sales and extract branches genuinely omit the
 *       key (verified from a real run: the xero_sales_upload body carries no such key).
 *       Absent must mean an absent strip — never a zeroed fallback, never a placeholder row.
 *   (2) CURRENCY IS CONDITIONAL. `viewmodel.build_recomputed_client_coded_f5_boxes` OMITS
 *       the key entirely when the export does not uniformly state one (omit-never-default);
 *       the symbol therefore renders only when the payload carries it, and its absence is
 *       stated rather than silently papered over with an assumed "SGD".
 *   (3) BASIS RENDERS VERBATIM. `basis` is stamped server-side from XERO_F5_BOX_BASIS where
 *       no caller can forge or omit it — the frontend prints the payload's own string, never
 *       an abbreviation and never a hardcoded copy.
 *
 * D-10: there is deliberately NO test for a null box value. The backend cannot emit one
 * (sap_b1_server.py initialises all eight accumulators to 0.0) and #48 already ruled that on
 * this source a genuinely-zero box IS its 0.00 figure. A "not fed" branch here would be a
 * rendered state no real run can produce.
 *
 * FIXTURE PROVENANCE: every value below was copied from a real
 * `POST /review/upload` run over the committed F5 fixture — no invented figures, no invented
 * strings. The currency-absent case drops the key exactly as the builder does.
 */

// Verbatim from a real run over tests/fixtures/xero-f5-export/AgentAssist_IRAS_F5_*.xlsx.
const REAL_BOXES: RecomputedF5Boxes = {
  boxes: {
    box_1_standard_rated_sales: 15000.0,
    box_2_zero_rated_sales: 3000.0,
    box_3_exempt_sales: 0.0,
    box_4_total_sales: 18000.0,
    box_5_taxable_purchases: 14500.0,
    box_6_output_tax: 900.0,
    box_7_input_tax: 1265.0,
    box_8_net_gst: -365.0,
  },
  basis:
    "Recomputed by AgentAssist from the transactions your Xero export already grouped by your own tax-code assignments. The arithmetic is AgentAssist's; the classification is yours. Agreement with the filed return is tautological, not confirmatory.",
  period: { start: "2026-04-01", end: "2026-06-30" },
  source_file: {
    filename: "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx",
    sha256: "sha256:49f6c07c5535acf11e4866a7f04be0019deae60cbd722466f156afbd2aa1d2e4",
  },
  currency: "SGD",
};

// The SAME object as a real run produces when the export states no single currency: the
// builder omits the key rather than defaulting it (api/viewmodel.py:257-258).
function withoutCurrency(): RecomputedF5Boxes {
  const copy = { ...REAL_BOXES };
  delete (copy as { currency?: string }).currency;
  return copy;
}

describe("Xero F5 strip (STEP 1)", () => {
  it("1: no boxes key — renders nothing at all (no strip, no zeros, no placeholder row)", () => {
    const { container } = render(<XeroF5Strip boxes={undefined} />);
    expect(container).toBeEmptyDOMElement();
    // Nothing that could read as a figure leaks onto the page.
    expect(screen.queryByText(/0\.00/)).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("2: currency present — the symbol renders and no missing-currency note appears", () => {
    render(<XeroF5Strip boxes={REAL_BOXES} />);
    // The amount column is labelled with the payload's own currency.
    expect(screen.getByText(/Amount \(SGD\)/)).toBeInTheDocument();
    // The honest "no currency stated" note must NOT appear when one IS stated.
    expect(screen.queryByText(/Currency is not stated in this export/i)).toBeNull();
  });

  it("3: currency absent — amounts render bare, never defaulted to SGD, and it is said out loud", () => {
    render(<XeroF5Strip boxes={withoutCurrency()} />);
    // Header degrades to a bare "Amount" — no invented symbol anywhere on the strip.
    expect(screen.getByText("Amount")).toBeInTheDocument();
    expect(screen.queryByText(/Amount \(/)).toBeNull();
    expect(screen.queryByText(/SGD/)).toBeNull();
    // The absence is stated, not silently papered over.
    expect(screen.getByText(/Currency is not stated in this export/i)).toBeInTheDocument();
  });

  it("4: basis renders VERBATIM from the payload — never abbreviated, never hardcoded", () => {
    render(<XeroF5Strip boxes={REAL_BOXES} />);
    expect(screen.getByText(REAL_BOXES.basis)).toBeInTheDocument();
  });

  it("5: identity is the source FILE, and every box the payload carries is rendered", () => {
    render(<XeroF5Strip boxes={REAL_BOXES} />);
    // R6/C4: the payload carries no company name — the filename is the identity.
    expect(screen.getByText(REAL_BOXES.source_file.filename)).toBeInTheDocument();
    // All eight boxes render, labelled by the SHARED IRAS box labels.
    for (const n of [1, 2, 3, 4, 5, 6, 7, 8]) {
      expect(screen.getByText(`Box ${n}`)).toBeInTheDocument();
    }
    // A genuinely-zero box shows its figure (#48) — box 3 is 0.0 in this real run.
    expect(screen.getByText("0.00")).toBeInTheDocument();
  });
});
