import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { XeroCoveragePanel } from "../components/XeroCoveragePanel";
import { coverageLabel } from "../lib/coverageLabels";
import type { CoverageStatusRow } from "../api";

/**
 * Xero coverage panel (t-xero-f5-render, STEP 2) — FAILING-FIRST.
 *
 * Replaces the raw `.xero-coverage-table` (check / level / reason, verbatim ids and raw
 * `full`/`degraded`/`unavailable` levels) with a grouped panel a reviewer can actually read.
 *
 * The rules pinned here:
 *   * NOT-EXAMINED FIRST. The checks that never ran are the ones a reviewer must see; they
 *     lead, not trail. An absent finding from a check that never ran is not evidence of
 *     absence, and the panel says so.
 *   * COUNTS ARE COMPUTED. Every count in this test is derived from the fixture array, never
 *     written as a literal — a hardcoded "5" would keep passing after the data changed.
 *   * REASONS VERBATIM. The payload's reason string renders exactly as sent; never mapped,
 *     never abbreviated, never summarised.
 *   * LEVELS WORDED. "Examined" / "Examined · reduced" / "NOT examined" — not the raw wire
 *     values, which read as jargon to a reviewer.
 *   * IDS ARE LABELLED, WITH A RAW-ID FALLBACK. An id the label map does not know renders as
 *     the id itself — never blank. (The map's ids are bound to CHECK_REGISTRY by
 *     tests/test_xero_coverage_labels_binding.py; this is the behavioural half.)
 *
 * FIXTURE PROVENANCE: all 11 rows below are verbatim from a real POST /review/upload run over
 * the committed F5 fixture — ids, levels and reason strings alike. Nothing is invented.
 */

const REAL_COVERAGE: CoverageStatusRow[] = [
  { check: "DUP_CLAIM", level: "degraded", reason: "NumAtCard absent or unpopulated — DUP_CLAIM under-detects." },
  { check: "NO_GST_REG", level: "unavailable", reason: "FederalTaxID absent — NO_GST_REG cannot run; require supplier-master sheet at onboarding." },
  { check: "SEQ_GAP", level: "degraded", reason: "company-wide document population absent — SEQ_GAP limited to within-period." },
  { check: "E1", level: "full", reason: "" },
  { check: "E2", level: "full", reason: "" },
  { check: "E3", level: "full", reason: "" },
  { check: "E4", level: "full", reason: "" },
  { check: "gst_amount_mismatch", level: "unavailable", reason: "source documents (document_pdfs) absent — gst_amount_mismatch cannot run; supply source-document PDFs at onboarding." },
  { check: "correct_period", level: "unavailable", reason: "source documents (document_pdfs) absent — correct_period cannot run; supply source-document PDFs at onboarding." },
  { check: "total_inconsistency", level: "unavailable", reason: "source documents (document_pdfs) absent — total_inconsistency cannot run; supply source-document PDFs at onboarding." },
  { check: "reg11_supplier_gst_absent", level: "unavailable", reason: "source documents (document_pdfs) absent — reg11_supplier_gst_absent cannot run; supply source-document PDFs at onboarding." },
];

// Counts DERIVED from the fixture — never literals (a literal would survive a data change).
const countOf = (level: string) => REAL_COVERAGE.filter((r) => r.level === level).length;

describe("Xero coverage panel (STEP 2)", () => {
  it("1: every row the payload carries renders — none silently dropped", () => {
    render(<XeroCoveragePanel rows={REAL_COVERAGE} />);
    const rendered = document.querySelectorAll(".xcov-row");
    expect(rendered).toHaveLength(REAL_COVERAGE.length);
    for (const row of REAL_COVERAGE) {
      expect(screen.getByTestId(`xcov-row-${row.check}`)).toBeInTheDocument();
    }
  });

  it("2: the summary counts are computed from the data", () => {
    render(<XeroCoveragePanel rows={REAL_COVERAGE} />);
    const summary = screen.getByTestId("xcov-summary");
    expect(summary).toHaveTextContent(`${countOf("full")} examined`);
    expect(summary).toHaveTextContent(`${countOf("degraded")} reduced`);
    expect(summary).toHaveTextContent(`${countOf("unavailable")} not examined`);
  });

  it("3: the not-examined group leads, and states how many of the total never ran", () => {
    render(<XeroCoveragePanel rows={REAL_COVERAGE} />);
    const sections = Array.from(document.querySelectorAll(".xcov-section"));
    expect(sections.length).toBeGreaterThan(0);
    expect(sections[0].getAttribute("data-level")).toBe("unavailable");
    // "N of 11" — both numbers derived, not written.
    expect(within(sections[0] as HTMLElement).getByText(
      `${countOf("unavailable")} of ${REAL_COVERAGE.length}`
    )).toBeInTheDocument();
    // The lede names the same computed figure rather than a prose guess.
    expect(screen.getByTestId("xcov-lede")).toHaveTextContent(
      String(countOf("unavailable"))
    );
  });

  it("4: levels are worded for a reviewer, not the raw wire values", () => {
    render(<XeroCoveragePanel rows={REAL_COVERAGE} />);
    const notExamined = screen.getByTestId("xcov-row-NO_GST_REG");
    expect(notExamined).toHaveTextContent("NOT examined");
    expect(screen.getByTestId("xcov-row-DUP_CLAIM")).toHaveTextContent("Examined · reduced");
    expect(screen.getByTestId("xcov-row-E1")).toHaveTextContent("Examined");
    // The raw vocabulary does not leak into the reviewer-facing level cell.
    expect(within(notExamined).queryByText("unavailable")).toBeNull();
  });

  it("5: reason strings render VERBATIM from the payload", () => {
    render(<XeroCoveragePanel rows={REAL_COVERAGE} />);
    for (const row of REAL_COVERAGE.filter((r) => r.reason)) {
      expect(within(screen.getByTestId(`xcov-row-${row.check}`)).getByText(row.reason))
        .toBeInTheDocument();
    }
  });

  it("6: a known id is labelled; an UNKNOWN id falls back to the raw id, never blank", () => {
    // Behavioural half of the D-11 binding (the ids-exist half is the Python test).
    expect(coverageLabel("NO_GST_REG")).not.toBe("");
    expect(coverageLabel("NO_GST_REG")).not.toBe("NO_GST_REG");

    const unknown: CoverageStatusRow[] = [
      { check: "NOT_A_REAL_CHECK", level: "full", reason: "" },
    ];
    render(<XeroCoveragePanel rows={unknown} />);
    const row = screen.getByTestId("xcov-row-NOT_A_REAL_CHECK");
    expect(row).toHaveTextContent("NOT_A_REAL_CHECK");
    expect(coverageLabel("NOT_A_REAL_CHECK")).toBe("NOT_A_REAL_CHECK");
  });

  it("7: no rows — renders nothing rather than an empty shell", () => {
    const { container } = render(<XeroCoveragePanel rows={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
