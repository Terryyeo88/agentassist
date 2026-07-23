import { useState } from "react";
import type { QueueItem } from "../api";

interface Props {
  item: QueueItem;
  decision?: { action: string; note: string };
  // The adjudication capability, DECOUPLED (B3a-2): `onRecord` alone renders the decision
  // controls; `onOpenSign` alone gates the Sign button (the upload panel passes it only for
  // Xero F5 — POST /sign/upload serves no other source_kind). Neither → review-only with
  // `reviewOnlyNote` — never a dead control (no-fake-affordances rule).
  onRecord?: (action: string, note: string) => void;
  onOpenSign?: () => void;
  reviewOnlyNote?: string;
}

// "Decline" is a distinct adjudication from "Not an issue": Decline disputes the
// finding (the reviewer disagrees with the flag), while "Not an issue" sets it
// aside as known/acceptable. Both require a reviewer note. Decline records through
// the existing onRecord → sign flow — no new endpoint, no QUEUE_ITEM_KEYS change.
const DECISIONS = ["Accept", "Decline", "Not an issue", "Mark known"] as const;
const NOTE_REQUIRED = new Set(["Decline", "Not an issue", "Mark known"]);

/**
 * FindingDetail — the per-finding case-file card: vendor · what we found · why it matters
 * (the rule) · suggested action → decision → sign. Trust signals are preserved verbatim:
 * the UNVALIDATED badge, the candidate framing line, the "illustrative citation" caveat on
 * the IRAS basis, and the demoted-but-present note. Nothing here asserts a verdict.
 *
 * The decision + sign section is an INJECTED capability (`onRecord`/`onOpenSign`): the SAP
 * path supplies it; the Xero upload path (no server-side sign store) omits it and the card
 * shows an honest review-only note. The candidate framing above is identical on both paths.
 */
export function FindingDetail({ item, decision, onRecord, onOpenSign, reviewOnlyNote }: Props) {
  const [action, setAction] = useState<string>(decision?.action ?? "Accept");
  const [note, setNote] = useState<string>(decision?.note ?? "");
  const [err, setErr] = useState<string>("");

  // No-silent-dead-buttons (B3a-2): a row without a deterministic fingerprint cannot be
  // persisted (POST /decision keys on the fingerprint), so its decision controls render
  // DISABLED with an honest per-cause reason — never hidden, never a button whose decision
  // evaporates into local state. Ledger-recon findings have no counterparty (a
  // counterparty-free fingerprint composition is #46 territory); probabilistic findings
  // are not detect-joinable. Shared component → the rule holds on BOTH the SAP surface
  // and the upload panel.
  const notPersistable = item.fingerprint
    ? null
    : item.finding_id.startsWith("ledger_recon:")
      ? "Not persistable — a ledger-reconciliation finding carries no deterministic fingerprint, so a decision cannot be recorded against it."
      : item.finding_type === "probabilistic"
        ? "Not persistable — a probabilistic finding carries no deterministic fingerprint, so a decision cannot be recorded against it."
        : "Not persistable — this finding carries no deterministic fingerprint, so a decision cannot be recorded against it.";

  // Dossier completeness (bucket-B wiring): surface the {required, present, missing, satisfied}
  // status as reviewer-facing UI instead of burying it in the technical block. Honest by rule —
  // an incomplete dossier reads "incomplete" and names what is missing; it is never hidden.
  // Value-only field already in QUEUE_ITEM_KEYS (populated on Xero uploads by #133); no contract
  // change. Empty on the frozen path → the block is omitted rather than shown as noise.
  const comp = item.completeness;
  const completenessHasData =
    comp.required.length > 0 || comp.present.length > 0 || comp.missing.length > 0;
  const completenessIncomplete =
    completenessHasData && (!comp.satisfied || comp.missing.length > 0);

  // Prior-decision history (bucket-B): the decision-ledger memory (annotation + prior_dispositions)
  // was previously shown ONLY on demoted rows. Surface it on ANY row that carries prior history, so
  // a non-demoted finding still shows what was decided before — while staying an active candidate.
  const hasPriorHistory =
    (item.prior_dispositions?.length ?? 0) > 0 || !!item.annotation;

  function record() {
    if (notPersistable) return;
    if (NOTE_REQUIRED.has(action) && !note.trim()) {
      setErr(`“${action}” requires a non-empty reviewer note.`);
      return;
    }
    setErr("");
    onRecord?.(action, note.trim());
  }

  return (
    <div className="panel detail">
      <span className="badge unvalidated">{item.validation_status} — candidate for review only</span>

      <div className="title serif">{item.display_name || item.check_id}</div>
      <div className="meta">
        Vendor <span className="mono">{item.vendor || "—"}</span> · Document{" "}
        <span className="mono">{item.doc_num ?? "—"}</span>
        {item.doc_date ? (
          <>
            {" "}
            (<span className="mono">{item.doc_date}</span>)
          </>
        ) : null}{" "}
        · Severity <span className="mono">{item.severity || "—"}</span>
        {item.error_code ? (
          <>
            {" "}
            · Code <span className="mono">{item.error_code}</span>
          </>
        ) : null}
      </div>

      <h4>What we found</h4>
      <p>{item.description || "—"}</p>

      <h4>Why it matters · the rule</h4>
      <p>{item.iras_basis || "—"}</p>
      <div className="caveat">{item.iras_basis_caveat}</div>

      <h4>Suggested action</h4>
      <p>{item.recommendation || "—"}</p>

      <div className="callout info">
        <strong>AgentAssist flags — you decide.</strong> Candidate framing:{" "}
        {item.candidate_framing_text || "—"}
      </div>

      {completenessHasData &&
        (completenessIncomplete ? (
          <div className="callout warn completeness">
            <strong>Completeness: incomplete.</strong> {comp.present.length} of{" "}
            {comp.required.length} required inputs present
            {comp.missing.length > 0 && <> · missing: {comp.missing.join(", ")}</>}. Shown
            honestly — an incomplete dossier is surfaced, never hidden.
          </div>
        ) : (
          <div className="callout info completeness">
            <strong>Completeness: complete.</strong> All {comp.required.length} required inputs
            present.
          </div>
        ))}

      {item.demoted && (
        <div className="callout known">
          Marked known from a prior period (decision-ledger memory):{" "}
          {item.annotation || "previously accepted"} · prior dispositions:{" "}
          {(item.prior_dispositions || []).join(", ") || "—"}. Still surfaced for review —
          demotion lowers prominence, it never drops a finding.
        </div>
      )}

      {!item.demoted && hasPriorHistory && (
        <div className="callout info prior-decisions">
          Prior decisions on file:{" "}
          {(item.prior_dispositions || []).join(", ") || "—"}
          {item.annotation ? <> · {item.annotation}</> : null}. Surfaced for context — this
          finding is still an active candidate for review.
        </div>
      )}

      {onRecord ? (
        <>
          <h4>Your decision</h4>
          {notPersistable && (
            <div className="callout warn not-persistable">{notPersistable}</div>
          )}
          <div className="decide">
            {DECISIONS.map((d) => (
              <button
                key={d}
                disabled={!!notPersistable}
                className={action === d ? "selected" : ""}
                onClick={() => setAction(d)}
              >
                {d}
              </button>
            ))}
          </div>
          {!notPersistable && NOTE_REQUIRED.has(action) && (
            <textarea
              placeholder={`Record your reasoning (required for “${action}”). Attaches to the finding, not to box values.`}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
          {err && <div className="callout warn">{err}</div>}
          <div className="decide">
            <button disabled={!!notPersistable} onClick={record}>
              Record decision
            </button>
            {onOpenSign && (
              <button className="primary" onClick={onOpenSign}>
                Sign working paper
              </button>
            )}
          </div>
          {decision && (
            <div className="recorded">
              Current decision: <strong>{decision.action}</strong>
              {decision.note ? ` — ${decision.note}` : ""}
            </div>
          )}
        </>
      ) : (
        reviewOnlyNote && (
          <div className="callout warn review-only">{reviewOnlyNote}</div>
        )
      )}

      {item.inputs_hash && item.inputs_hash !== "—" && item.inputs_hash !== "-" && (
        <div className="meta provenance">
          Inputs hash <span className="mono">{item.inputs_hash}</span>
        </div>
      )}

      <details className="tech">
        <summary>Technical details (ids · hashes · evidence)</summary>
        <pre>
          {JSON.stringify(
            {
              finding_id: item.finding_id,
              check_id: item.check_id,
              finding_type: item.finding_type,
              inputs_hash: item.inputs_hash,
              fingerprint: item.fingerprint,
              proposal: item.proposal_id
                ? `${item.proposal_id} (${item.proposal_status})`
                : null,
              completeness: item.completeness,
            },
            null,
            2
          )}
        </pre>
      </details>
    </div>
  );
}
