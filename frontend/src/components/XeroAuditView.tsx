import type { DecisionResponse } from "../api";

/**
 * XeroAuditView — the decisions recorded against this export, THIS SESSION.
 *
 * SESSION-SCOPED BY NECESSITY, NOT BY CHOICE (D-17). There is no read endpoint for the
 * decision store: the API exposes GET /health, /working-paper, /document/{ref},
 * /review/{client}/{period}, /review-session[/{id}] and /audit — and nothing that returns
 * decision entries. `load_decision_entries` is called server-side only to fold decisions into
 * some other artefact. So the only decisions this view can name are the ones this browser made,
 * from the POST /decision responses it received.
 *
 * EMPTY ON LOAD, ALWAYS. A seeded "prior" row would be an invented backend state — the exact
 * thing the no-fabricated-values rule forbids. The empty state is the honest state.
 *
 * WHAT A ROW MAY CONTAIN. Measured from a real POST /decision response, whose TWELVE keys are:
 * client_id, finding_id, action, disposition, fingerprint, entry_id, entry_hash, reviewer,
 * timestamp, chain_length, validation_status, disclaimer.
 *
 * C-6(a) ADDED `reviewer` + `timestamp`, so the "When" and "Reviewer" columns are now honest and
 * are shown. They were previously absent for a reason worth keeping in mind: the response did not
 * carry them, and filling the cells from `new Date()` or from the locally-typed reviewer-of-record
 * would have been this page's GUESS at what happened rather than the ledger's record of it. Both
 * values now render VERBATIM from the response — the store's own ISO-8601 append-time stamp and
 * the reviewer it actually recorded, both hashed into the append-only chain. Do not reformat,
 * localise, or substitute either one: the point is that the cell IS the record.
 *
 * `/audit` is deliberately not called: it returns the SAP agent's Tier-1/Tier-2 justification
 * ledger, and an uploaded export runs no agent, so there is no tool chain to show.
 */
export function XeroAuditView({ decisions }: { decisions: DecisionResponse[] }) {
  const chainLength = decisions.length ? decisions[decisions.length - 1].chain_length : null;

  return (
    <section className="xaudit" aria-label="Decisions this session">
      <div className="xaudit-head">
        <h3 className="serif">Decisions — this session</h3>
        {chainLength !== null && (
          <span className="xaudit-chain" data-testid="xaudit-chain-length">
            append-only chain length <strong>{chainLength}</strong>
          </span>
        )}
      </div>

      <div className="callout warn xaudit-limits" data-testid="xaudit-limits">
        <strong>This lists only the decisions made in this browser session.</strong> There is
        no read endpoint for the decision store, so decisions recorded earlier — or by anyone
        else — cannot be listed here, even though they were saved. They resurface as the
        per-finding “previously adjudicated” annotation after you re-upload the same workbook.
        Separately: an uploaded export runs no agent tool chain, so there is no Tier-1/Tier-2
        justification ledger for this source — only your decisions.
      </div>

      {decisions.length === 0 ? (
        <p className="xaudit-empty">No decision has been recorded against this export yet.</p>
      ) : (
        <div className="xaudit-table" role="table" aria-label="Decisions recorded this session">
          {/* The header is NOT a .xaudit-row — that class means "one recorded decision", so a
              count of it is a count of decisions. */}
          <div className="xaudit-header" role="row">
            <span role="columnheader">#</span>
            <span role="columnheader">Finding</span>
            <span role="columnheader">Action</span>
            <span role="columnheader">Disposition</span>
            <span role="columnheader">When</span>
            <span role="columnheader">Reviewer</span>
            <span role="columnheader">Entry hash</span>
          </div>
          {decisions.map((d, i) => (
            <div className="xaudit-row" role="row" key={d.entry_id}>
              <span className="mono xaudit-seq" role="cell">{i + 1}</span>
              <span className="mono xaudit-finding" role="cell">{d.finding_id}</span>
              <span className="xaudit-action" role="cell">{d.action}</span>
              <span className="xaudit-disp" role="cell">{d.disposition}</span>
              {/* Verbatim, both of them — the ledger's own stamp and recorded reviewer. */}
              <span className="mono xaudit-when" role="cell">{d.timestamp}</span>
              <span className="xaudit-reviewer" role="cell">{d.reviewer}</span>
              <span className="mono xaudit-hash" role="cell" title={d.entry_hash}>
                {d.entry_hash}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
