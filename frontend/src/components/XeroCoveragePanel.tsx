import type { CoverageStatusRow } from "../api";
import { coverageLabel } from "../lib/coverageLabels";

/**
 * XeroCoveragePanel — "what was examined", grouped so a reviewer can read it.
 *
 * Replaces the raw three-column coverage table (bare ids, bare `full`/`degraded`/
 * `unavailable`). The point of this panel is the checks that did NOT run: an absent finding
 * from a check that never ran is not evidence of absence, so the not-examined group LEADS and
 * the lede says how many there were.
 *
 * What is data and what is presentation:
 *   * COUNTS are computed from the rows — never written down. A hardcoded figure would keep
 *     rendering confidently after the data changed underneath it.
 *   * REASONS render VERBATIM from the payload. They carry the data-coverage fact and are
 *     never mapped, abbreviated or summarised here.
 *   * LEVELS are worded ("NOT examined") because the wire vocabulary is jargon; the mapping is
 *     the same three-state one report/render.py already uses.
 *   * IDS are labelled via lib/coverageLabels, which falls back to the raw id and is bound to
 *     CHECK_REGISTRY by tests/test_xero_coverage_labels_binding.py.
 *
 * A `full` row carries an empty reason by design (the fact is the absence of a caveat), so it
 * gets a stated positive rather than a blank cell — visible, not invisible.
 */

// Not-examined FIRST: the order is the point, not an aesthetic. Wire level -> reviewer wording.
const SECTIONS: { level: string; title: string; rowWord: string }[] = [
  { level: "unavailable", title: "Not examined", rowWord: "NOT examined" },
  { level: "degraded", title: "Examined · reduced coverage", rowWord: "Examined · reduced" },
  { level: "full", title: "Examined", rowWord: "Examined" },
];

const FULL_COVERAGE_REASON = "Ran over every line the export supplied for this check.";

export function XeroCoveragePanel({ rows }: { rows: CoverageStatusRow[] }) {
  if (!rows || rows.length === 0) return null;

  const countOf = (level: string) => rows.filter((r) => r.level === level).length;
  const notExamined = countOf("unavailable");
  const total = rows.length;

  // Any level the backend adds that this panel has no section for still renders — grouped
  // last under its own raw level, never dropped on the floor.
  const known = new Set(SECTIONS.map((s) => s.level));
  const unknownLevels = Array.from(
    new Set(rows.filter((r) => !known.has(r.level)).map((r) => r.level))
  );
  const sections = [
    ...SECTIONS,
    ...unknownLevels.map((level) => ({ level, title: level, rowWord: level })),
  ];

  return (
    <section className="xcov-panel" aria-label="What was examined">
      <div className="xcov-head">
        <h3 className="xcov-title serif">What was examined</h3>
        <span className="xcov-summary" data-testid="xcov-summary">
          {countOf("full")} examined · {countOf("degraded")} reduced · {notExamined} not examined
        </span>
      </div>

      <p className="xcov-lede" data-testid="xcov-lede">
        {total} checks exist. A Xero export alone does not carry the inputs every check needs,
        so {notExamined} of them never ran against your data. An absent finding from a check
        that never ran is not evidence of absence.
      </p>

      {sections.map((section) => {
        const inSection = rows.filter((r) => r.level === section.level);
        if (inSection.length === 0) return null;
        return (
          <div
            key={section.level}
            className={`xcov-section xcov-${section.level}`}
            data-level={section.level}
          >
            <div className="xcov-section-head">
              <span className="xcov-dot" aria-hidden="true" />
              <span className="xcov-section-title">{section.title}</span>
              <span className="mono xcov-section-count">
                {inSection.length} of {total}
              </span>
            </div>

            {inSection.map((row) => (
              <div
                key={row.check}
                className="xcov-row"
                data-testid={`xcov-row-${row.check}`}
              >
                <div className="xcov-check">
                  <span className="mono xcov-id">{row.check}</span>
                  <span className="xcov-name">{coverageLabel(row.check)}</span>
                </div>
                <div className="xcov-level">{section.rowWord}</div>
                {/* Verbatim. A `full` row's reason is empty by design — state the positive. */}
                <div className="xcov-reason">
                  {row.reason ? row.reason : FULL_COVERAGE_REASON}
                </div>
              </div>
            ))}
          </div>
        );
      })}
    </section>
  );
}
