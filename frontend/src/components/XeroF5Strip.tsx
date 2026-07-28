import type { RecomputedF5Boxes } from "../api";
import { boxDescription, boxNumber } from "../lib/f5";

/**
 * XeroF5Strip — the recomputed GST F5 boxes from an uploaded Xero export.
 *
 * The backend has emitted `recomputed_client_coded_f5_boxes` on the xero_f5_upload branch
 * since PR #151; until now the key arrived and nothing rendered it.
 *
 * DELIBERATELY NOT THE SAP TREATMENT (D-12). This does not reuse `.f5-strip` / `.f5-table`.
 * The SAP figures are computed from the books; these are the client's OWN tax-code
 * classification with AgentAssist's arithmetic applied — agreement with the filed return is
 * tautological, not confirmatory. That is the whole reason `basis` is stamped server-side
 * where no caller can omit it. If the two tables looked identical, the distinction would be
 * lost on the one screen where somebody signs, so this renders as its own `.xf5-*` panel.
 * Only the box LABELS are shared (lib/f5).
 *
 * Three rules hold here:
 *   * NO BOXES KEY -> RENDER NOTHING. Sales and extract uploads genuinely omit the key
 *     (#48 not widened — they are one-sided). Absent renders an absent panel; never a zeroed
 *     fallback and never a placeholder row.
 *   * CURRENCY IS CONDITIONAL. The builder omits `currency` when the export states none
 *     (omit-never-default); the symbol appears only when the payload carries it, and its
 *     absence is stated out loud rather than assumed to be SGD.
 *   * BASIS IS VERBATIM. The payload's own string, never abbreviated, never hardcoded here.
 *
 * There is no "not fed" state (D-10): the chain initialises all eight boxes to 0.0, so a null
 * box is not a thing this backend can emit, and #48 ruled that on this source a genuinely-zero
 * box IS its 0.00 figure. Box isolation is unaffected — this only renders figures the chain
 * already computed on this upload; nothing here recomputes a box.
 */
export function XeroF5Strip({ boxes }: { boxes?: RecomputedF5Boxes }) {
  if (!boxes) return null;

  const currency = boxes.currency;
  const entries = Object.entries(boxes.boxes ?? {});
  if (entries.length === 0) return null;

  return (
    <section className="xf5-panel" aria-label="Recomputed GST F5 boxes">
      <div className="xf5-head">
        <span className="xf5-kicker">Recomputed GST F5 boxes</span>
        <span className="mono xf5-file">{boxes.source_file?.filename}</span>
        <span className="xf5-period">
          {boxes.period?.start} → {boxes.period?.end}
        </span>
        <span className="mono xf5-sha">{(boxes.source_file?.sha256 ?? "").slice(0, 23)}…</span>
      </div>

      <table className="xf5-table">
        <thead>
          <tr>
            <th>Box</th>
            <th>Description</th>
            {/* Conditional by rule: a currency is stated or it is not — it is never assumed. */}
            <th className="num">{currency ? `Amount (${currency})` : "Amount"}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, value]) => {
            const isNet = /net/i.test(key);
            return (
              <tr key={key} className={isNet ? "xf5-net" : ""}>
                <td className="mono xf5-box">{boxNumber(key)}</td>
                <td>{boxDescription(key)}</td>
                <td className={`mono num xf5-amt${isNet ? " net" : ""}`}>
                  {currency && <span className="xf5-cur">{currency}</span>}
                  <span className="xf5-val">
                    {value.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {!currency && (
        <p className="xf5-no-currency">
          Currency is not stated in this export. Amounts are shown without a symbol — a currency
          is never assumed.
        </p>
      )}

      {/* Mandatory, and verbatim from the payload: the basis is the whole point of this table. */}
      <div className="xf5-basis">
        <strong>Basis.</strong> {boxes.basis}
      </div>
    </section>
  );
}
