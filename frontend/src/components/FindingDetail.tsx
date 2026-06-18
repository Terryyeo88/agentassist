import { useState } from "react";
import type { QueueItem } from "../api";

interface Props {
  item: QueueItem;
  decision: { action: string; note: string } | undefined;
  onRecord: (action: string, note: string) => void;
  onOpenSign: () => void;
}

const DECISIONS = ["Accept", "Not an issue", "Mark known"] as const;
const NOTE_REQUIRED = new Set(["Not an issue", "Mark known"]);

/**
 * FindingDetail — the per-finding case-file card: vendor · what we found · why it matters
 * (the rule) · suggested action → decision → sign. Trust signals are preserved verbatim:
 * the UNVALIDATED badge, the candidate framing line, the "illustrative citation" caveat on
 * the IRAS basis, and the demoted-but-present note. Nothing here asserts a verdict.
 */
export function FindingDetail({ item, decision, onRecord, onOpenSign }: Props) {
  const [action, setAction] = useState<string>(decision?.action ?? "Accept");
  const [note, setNote] = useState<string>(decision?.note ?? "");
  const [err, setErr] = useState<string>("");

  function record() {
    if (NOTE_REQUIRED.has(action) && !note.trim()) {
      setErr(`“${action}” requires a non-empty reviewer note.`);
      return;
    }
    setErr("");
    onRecord(action, note.trim());
  }

  return (
    <div className="panel detail">
      <span className="badge unvalidated">{item.validation_status} — candidate for review only</span>

      <div className="title serif">{item.display_name || item.check_id}</div>
      <div className="meta">
        Vendor <span className="mono">{item.vendor || "—"}</span> · Document{" "}
        <span className="mono">{item.doc_num ?? "—"}</span> · Severity{" "}
        <span className="mono">{item.severity || "—"}</span>
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

      {item.demoted && (
        <div className="callout known">
          Marked known from a prior period (decision-ledger memory):{" "}
          {item.annotation || "previously accepted"} · prior dispositions:{" "}
          {(item.prior_dispositions || []).join(", ") || "—"}. Still surfaced for review —
          demotion lowers prominence, it never drops a finding.
        </div>
      )}

      <h4>Your decision</h4>
      <div className="decide">
        {DECISIONS.map((d) => (
          <button
            key={d}
            className={action === d ? "selected" : ""}
            onClick={() => setAction(d)}
          >
            {d}
          </button>
        ))}
      </div>
      {NOTE_REQUIRED.has(action) && (
        <textarea
          placeholder={`Record your reasoning (required for “${action}”). Attaches to the finding, not to box values.`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      )}
      {err && <div className="callout warn">{err}</div>}
      <div className="decide">
        <button onClick={record}>Record decision</button>
        <button className="primary" onClick={onOpenSign}>
          Sign working paper
        </button>
      </div>
      {decision && (
        <div className="recorded">
          Current decision: <strong>{decision.action}</strong>
          {decision.note ? ` — ${decision.note}` : ""}
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
