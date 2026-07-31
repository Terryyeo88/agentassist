import type { DecisionEntry, DecisionResponse } from "../api";

/**
 * XeroAuditView — the decisions recorded against this export.
 *
 * POPULATES ON LOAD (C-6b). This view was session-scoped BY NECESSITY (D-17): the API had no
 * read endpoint for the decision store, so the only decisions it could name were the ones this
 * browser had just made. `GET /decisions/{client_id}` closed that hole, and XeroUploadPanel now
 * loads the store's own records as soon as an upload names a client. Rows therefore arrive down
 * TWO paths — loaded prior decisions and in-session POST responses — and the panel unions them,
 * deduped on `entry_id`, before they reach this (still purely presentational) component.
 *
 * A ROW IS ONE OF TWO SHAPES, and the difference is not cosmetic:
 *   * `DecisionResponse` — a POST response from this session. Echoes what the caller supplied,
 *     so it has `finding_id` and the `action` verb.
 *   * `DecisionEntry` — a record read from the store. Carries what the LEDGER holds, which does
 *     NOT include `finding_id` (the record is keyed on the deterministic fingerprint alone) and
 *     does not include `action` as its own field.
 *
 * WHAT THAT MEANS FOR TWO CELLS (§8, no fabricated values):
 *   * FINDING — a stored entry cannot name one, so it renders a visible "—". Not a blank cell,
 *     which reads as a broken render; and NOT the fingerprint relocated into that column, which
 *     would assert an identity the record does not carry.
 *   * ACTION — read back from `reason`'s "[Mark known] …" prefix, which api/app.py writes
 *     verbatim precisely so the two KNOWN_ACCEPTED-mapped verbs stay distinguishable. Never
 *     re-derived from `disposition`: that mapping is many-to-one and the inverse is a guess.
 *
 * WHEN + REVIEWER (C-6a) render VERBATIM from the record — the store's own ISO-8601 append-time
 * stamp and the reviewer it actually recorded, both hashed into the append-only chain. Do not
 * reformat, localise, or substitute either one: the point is that the cell IS the record. A
 * browser clock would be this page's guess at when the adjudication happened.
 *
 * `/audit` is deliberately not called: it returns the SAP agent's Tier-1/Tier-2 justification
 * ledger, and an uploaded export runs no agent, so there is no tool chain to show.
 */

export type DecisionRow = DecisionResponse | DecisionEntry;

/** A session POST response — the only shape that echoes the caller's `action`/`finding_id`. */
function isSessionDecision(d: DecisionRow): d is DecisionResponse {
  return "action" in d;
}

const ACTION_IN_REASON = /^\s*\[([^\]]+)\]/;

/** The reviewer's verb: echoed by a session response, else read back out of the stored reason. */
function actionOf(d: DecisionRow): string {
  if (isSessionDecision(d)) return d.action;
  const match = d.reason ? ACTION_IN_REASON.exec(d.reason) : null;
  return match ? match[1] : "—";
}

export function XeroAuditView({
  decisions,
  storedChainLength = null,
}: {
  decisions: DecisionRow[];
  /**
   * The store's own chain length for the loaded client, when one has been loaded. Used only
   * when this session has recorded nothing — a session response's `chain_length` is the
   * fresher fact (it is measured AFTER that append), so it wins when present.
   */
  storedChainLength?: number | null;
}) {
  const lastSession = [...decisions].reverse().find(isSessionDecision);
  const chainLength = lastSession ? lastSession.chain_length : storedChainLength;

  return (
    <section className="xaudit" aria-label="Decisions recorded against this export">
      <div className="xaudit-head">
        <h3 className="serif">Decisions</h3>
        {chainLength !== null && (
          <span className="xaudit-chain" data-testid="xaudit-chain-length">
            append-only chain length <strong>{chainLength}</strong>
          </span>
        )}
      </div>

      <div className="callout warn xaudit-limits" data-testid="xaudit-limits">
        <strong>These are the decisions recorded against this export's client.</strong> They come
        from AgentAssist's own append-only store, which is keyed by the client configuration this
        upload ran under — not by a named client, so uploads sharing one demo configuration share
        one store. A decision also re-applies to the finding itself: it resurfaces as the
        per-finding “previously adjudicated” annotation after you re-upload the same workbook.
        Separately: an uploaded export runs no agent tool chain, so there is no Tier-1/Tier-2
        justification ledger for this source — only your decisions.
      </div>

      {decisions.length === 0 ? (
        <p className="xaudit-empty">No decision has been recorded against this export yet.</p>
      ) : (
        <div className="xaudit-table" role="table" aria-label="Decisions recorded">
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
              {/* A stored record has no finding_id — state the absence, never infer one. */}
              <span className="mono xaudit-finding" role="cell">
                {isSessionDecision(d) ? d.finding_id : <span className="xaudit-none">—</span>}
              </span>
              <span className="xaudit-action" role="cell">{actionOf(d)}</span>
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
