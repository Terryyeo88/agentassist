import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Sidebar } from "../components/Sidebar";
import type { QueueItem } from "../api";

/**
 * C-1 — the Sidebar's "Open findings" list must distinguish the ledger-recon rows.
 * FAILING-FIRST.
 *
 * THE BUG. Sidebar.tsx renders exactly three things per open row: `vendor || "—"`, `check_id`,
 * and `severity` (twice — the dot and the label). On the ledger-recon rows ALL THREE are
 * identical: vendor null, severity null, check_id "GST_LEDGER_RECON". So the rail shows
 * "— GST_LEDGER_RECON" three times over and a reviewer cannot tell which row they are clicking.
 *
 * THREE rows, not two. The earlier write-up of this defect said the 820 path returns two
 * ledger-recon rows; the live endpoint returns THREE (the two per-side divergences plus the
 * Signal-B "not included" drop). All three collide in the rail.
 *
 * THE FIX PINNED HERE. `finding_id`'s terminal segment is surfaced as a secondary line — the
 * SAME treatment PR #159 applied to the review queue (Queue.tsx `rowIdentitySuffix`). It is
 * NOT parsed out of `description` / `recommendation`: the identifier is data, the prose is not.
 *
 * FIXTURE PROVENANCE. Every value below is verbatim from a real
 * `POST /review/upload` with `file=` the committed F5 workbook and `ledger=` the committed 820
 * export, both from `tests/fixtures/xero-real-format/`
 * (AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx + AgentAssist_-_Account_Transactions.xlsx),
 * run 2026-07-28 → `source_kind: "xero_f5_upload"`, a 6-row queue. Nothing here is invented.
 * `description` / `recommendation` are deliberately NOT reproduced: the Sidebar renders no
 * prose, and their embedded figures move with the fixture's declared boxes.
 */

// The fields the three real ledger-recon rows share — identical across all three in the live
// response. `severity: null` and `vendor: null` are the collision; `fingerprint: null` is why
// these rows stay non-adjudicable (#46) and is carried so the row is a truthful QueueItem.
const LEDGER_BASE: Omit<QueueItem, "finding_id" | "error_code" | "display_name"> = {
  check_id: "GST_LEDGER_RECON",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: null,
  severity: null,
  description: null,
  recommendation: null,
  doc_num: null,
  doc_date: null,
  iras_basis:
    "Internal-consistency check — ledger-derived GST versus the declared F5 return. Not an " +
    "IRAS-cited finding: it flags a divergence between two derivations of the same source for " +
    "reviewer adjudication, never a verdict that either side is correct.",
  iras_basis_caveat:
    "Illustrative citation — the IRAS basis shown is itself UNVALIDATED (T2.11 gates " +
    "customer-facing claims); verify against the e-Tax Guides before any customer use.",
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: null,
  candidate_framing_text:
    "Internal-consistency candidate — a reviewer adjudicates whether the divergence is an " +
    "error in the return; this is not a verdict.",
  completeness: { required: [], present: [], missing: [], satisfied: false },
  inputs_hash: "—",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

// Terminal segment "output" — api/viewmodel.py builds `ledger_recon:{finding_type}:{side}`.
const RECON_OUTPUT: QueueItem = {
  ...LEDGER_BASE,
  finding_id: "ledger_recon:ledger_recon_divergence:output",
  error_code: "LEDGER_RECON",
  display_name: "Ledger vs declared-return divergence",
};

// Terminal segment "input" — the sibling side. Differs from RECON_OUTPUT in finding_id,
// description and recommendation ONLY; display_name and error_code are identical too.
const RECON_INPUT: QueueItem = {
  ...LEDGER_BASE,
  finding_id: "ledger_recon:ledger_recon_divergence:input",
  error_code: "LEDGER_RECON",
  display_name: "Ledger vs declared-return divergence",
};

// The Signal-B row. Its terminal segment is the real ledger reference "#14", not a side —
// api/viewmodel.py keys this finding_type on `reference or account`.
const RECON_NOT_INCLUDED: QueueItem = {
  ...LEDGER_BASE,
  finding_id: "ledger_recon:not_included_gst_drop:#14",
  error_code: "NOT_INCLUDED",
  display_name: "GST posting not included in the F5 return",
};

// A fingerprinted detect row from the SAME response — the CONTROL case. It already has a vendor
// and a severity, so it must NOT gain a secondary identity line (ordinary rows untouched).
const DETECT_E3: QueueItem = {
  finding_id: "detect:E3:INV-2002",
  check_id: "E3",
  finding_type: "deterministic",
  group: "needs_review",
  vendor: "Borealis Pte Ltd",
  severity: "HIGH",
  description: null,
  recommendation: null,
  doc_num: "INV-2002",
  doc_date: "2026-04-15",
  error_code: "E3",
  display_name: "Standard-rated supply with zero or missing GST amount",
  iras_basis: "IRAS GST Act s10 / applicable output and input tax provisions",
  iras_basis_caveat: LEDGER_BASE.iras_basis_caveat,
  demoted: false,
  annotation: null,
  prior_dispositions: [],
  fingerprint: "sha256:52563359fec47778f0ec32e6fe327d3208cfc4caf391bb9ba909adb91736c5b3",
  candidate_framing_text:
    "Document INV-2002 (E3 - Standard-rated supply with zero or missing GST amount) appears to " +
    "be a candidate for reviewer attention; consider reviewing the GST treatment for this item. " +
    "This is a candidate, not a verdict.",
  completeness: {
    required: ["sales_invoices", "purchase_invoices", "vat_group_mapping"],
    present: ["sales_invoices", "purchase_invoices", "vat_group_mapping"],
    missing: [],
    satisfied: true,
  },
  inputs_hash: "sha256:a18afe7b968181f0218933bdec9c70bbd73ed979556674c0772b7f0bc1dcbcce",
  proposal_id: null,
  proposal_status: null,
  validation_status: "unvalidated",
};

const QUEUE: QueueItem[] = [DETECT_E3, RECON_OUTPUT, RECON_INPUT, RECON_NOT_INCLUDED];

/**
 * The Sidebar is NOT view-gated — App.tsx and XeroUploadPanel.tsx both mount it outside every
 * `view === …` branch, gated only by `sidebarOpen` (default true). So it renders on all three
 * views and there is no view to switch to; it is rendered directly here, the same way
 * ReviewScreen.test.tsx renders its component under test. Every assertion below therefore runs
 * on the one surface where these rows appear (D-16), presence first.
 */
function renderSidebar() {
  const onSelectFinding = vi.fn();
  render(<Sidebar queue={QUEUE} decided={{}} onSelectFinding={onSelectFinding} />);
  // Sidebar's only <button>s are the "Open findings" rows (the search pill is an aria-hidden div).
  const rows = screen.getAllByRole("button");
  return { onSelectFinding, rows };
}

/** Map each rendered row to the finding_id it selects — read from the component's own callback,
 *  never from row order, so a sort change cannot silently mislabel an assertion. */
function idOf(row: HTMLElement, onSelectFinding: ReturnType<typeof vi.fn>): string {
  onSelectFinding.mockClear();
  row.click();
  expect(onSelectFinding).toHaveBeenCalledTimes(1);
  return onSelectFinding.mock.calls[0][0] as string;
}

describe("C-1: the Sidebar distinguishes the GST_LEDGER_RECON rows", () => {
  it("1 (presence): all four open rows render, three of them GST_LEDGER_RECON", () => {
    const { rows } = renderSidebar();
    expect(rows).toHaveLength(4);
    const recon = rows.filter((r) => r.textContent?.includes("GST_LEDGER_RECON"));
    expect(recon).toHaveLength(3);
  });

  it("2: the three GST_LEDGER_RECON rows are not the same row three times", () => {
    const { rows } = renderSidebar();
    const recon = rows.filter((r) => r.textContent?.includes("GST_LEDGER_RECON"));
    expect(recon).toHaveLength(3); // presence before distinctness
    // FAILS TODAY: every one of them reads "—GST_LEDGER_RECON", so the set collapses to 1.
    const texts = new Set(recon.map((r) => r.textContent));
    expect(texts.size).toBe(3);
  });

  it("3: each GST_LEDGER_RECON row shows its own finding_id token", () => {
    const { rows, onSelectFinding } = renderSidebar();
    const recon = rows.filter((r) => r.textContent?.includes("GST_LEDGER_RECON"));
    expect(recon).toHaveLength(3); // presence before per-row content

    // The real terminal segment of each real finding_id — the only non-prose differentiator.
    const expected: Record<string, string> = {
      "ledger_recon:ledger_recon_divergence:output": "output",
      "ledger_recon:ledger_recon_divergence:input": "input",
      "ledger_recon:not_included_gst_drop:#14": "#14",
    };

    const seen: string[] = [];
    for (const row of recon) {
      const id = idOf(row, onSelectFinding);
      expect(Object.keys(expected)).toContain(id);
      // FAILS TODAY: the row renders no part of its finding_id.
      expect(row.textContent).toContain(expected[id]);
      seen.push(id);
    }
    expect(seen.sort()).toEqual(Object.keys(expected).sort());
  });

  it("4 (control): an ordinary detect row gains no identity line", () => {
    const { rows, onSelectFinding } = renderSidebar();
    const detect = rows.filter((r) => r.textContent?.includes("Borealis Pte Ltd"));
    expect(detect).toHaveLength(1); // presence first, then the absence check (D-16)
    expect(idOf(detect[0], onSelectFinding)).toBe("detect:E3:INV-2002");
    // A row already distinguishable by vendor/severity must not sprout its finding_id tail.
    expect(detect[0].textContent).not.toContain("INV-2002");
  });
});
