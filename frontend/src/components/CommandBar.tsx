import { useState } from "react";
import { postCommand, type CommandResponse, type ExecutionResult } from "../api";
import { asRunReviewData } from "../lib/runReview";

/**
 * CommandBar — T6.2 LIVE command bar, restyled into the dark composer + result CARD (Slice 4).
 *
 * "One way in": a free-text utterance is classified by the env-selected backend (scripted by
 * default — no tokens; live opt-in), routed to an intent, and executed over the FROZEN
 * artifacts via POST /command. The four chips dispatch the four intents directly (a curated
 * utterance each). Identity (client/period) comes from the surface context, never guessed by
 * the model. The response renders in a styled card whose footer shows the SERVER's
 * classifier_mode + disclaimer verbatim (never a hardcoded "scripted" — it would lie in live
 * mode). The facet menu has MOVED to the Findings queue (Slice 4); a RUN_REVIEW result here is
 * just a summary + a jump to that queue.
 */
interface Props {
  clientId: string;
  period: string;
  onOpenQueue?: () => void;
  onOpenAudit?: () => void;
  onOpenSign?: () => void;
}

// Each chip → a curated scripted utterance (agent/intent_curated.py) so the default scripted
// backend routes it deterministically. Surface context overrides the identity.
const CHIPS: { label: string; utterance: string }[] = [
  { label: "Run a review", utterance: "Run the GST review for Acme for 2024-Q1" },
  { label: "Show ledger", utterance: "Show me the justification ledger for Acme" },
  { label: "Show proposals", utterance: "What proposals are pending for Acme?" },
  { label: "Prior decisions", utterance: "Show prior decisions for Far East Imports, 2023-Q3" },
];

function StatusPill({ response }: { response: CommandResponse }) {
  if (response.kind === "needs_clarification") {
    return <span className="cmd-pill pill-warn">needs clarification</span>;
  }
  if (response.kind === "out_of_scope") {
    return <span className="cmd-pill pill-muted">out of scope</span>;
  }
  const ex = response.execution;
  return (
    <span className="cmd-pill pill-result">
      {ex.intent} · {ex.outcome}
    </span>
  );
}

// The body of a `result` card, by intent. RUN_REVIEW is just a summary + a jump to the queue
// (the facet UI moved there); reads render their own one-liner over the frozen data.
function ResultBody({
  execution,
  onOpenQueue,
  onOpenAudit,
}: {
  execution: ExecutionResult;
  onOpenQueue?: () => void;
  onOpenAudit?: () => void;
}) {
  const data = execution.data as Record<string, unknown>;
  const ledger = data.ledger as unknown[] | undefined;
  const proposals = data.proposals as unknown[] | undefined;
  const adjudications = data.adjudications as Record<string, unknown>[] | undefined;

  if ("available_facets" in data) {
    const findings = (data.findings as unknown[]) ?? [];
    const dossiers = (data.dossiers as unknown[]) ?? [];
    return (
      <>
        <p>
          Frozen review — <strong>{findings.length} of {dossiers.length}</strong> findings shown.
        </p>
        <button className="secondary jump" onClick={() => onOpenQueue?.()}>
          Open review queue →
        </button>
      </>
    );
  }
  if (ledger) {
    return (
      <>
        <p>
          Justification ledger — <strong>{ledger.length}</strong> entries, hash-chained.
        </p>
        <button className="secondary jump" onClick={() => onOpenAudit?.()}>
          View audit trail →
        </button>
      </>
    );
  }
  if (proposals) {
    return (
      <p>
        Pending proposals — <strong>{proposals.length}</strong>
        {proposals.length === 0
          ? " (none staged in this scripted run; nothing writes back to SAP)."
          : "."}
      </p>
    );
  }
  if (adjudications) {
    const vendor = (execution.params?.counterparty as string | undefined) ?? null;
    return (
      <>
        <p>Prior adjudications{vendor ? ` for ${vendor}` : ""}:</p>
        <ul className="adj-list">
          {adjudications.map((a, i) => (
            <li key={i}>
              <span className="disp-pill">{String(a.disposition)}</span>
              <span className="adj-by">by {String(a.reviewer)}</span>
              <span className="mono adj-period">{String(a.period)}</span>
            </li>
          ))}
        </ul>
      </>
    );
  }
  return (
    <p>
      Ran <strong>{execution.intent}</strong> · outcome {execution.outcome}.
      {execution.notes.length > 0 && <span className="caveat"> {execution.notes.join(" ")}</span>}
    </p>
  );
}

function CommandResultCard({
  response,
  onDismiss,
  onOpenQueue,
  onOpenAudit,
}: {
  response: CommandResponse;
  onDismiss: () => void;
  onOpenQueue?: () => void;
  onOpenAudit?: () => void;
}) {
  return (
    <div className={`cmd-card kind-${response.kind}`}>
      <div className="cmd-card-head">
        <span className="cmd-assistant mono">ASSISTANT</span>
        <StatusPill response={response} />
        <span className="spacer" />
        <button className="cmd-dismiss" aria-label="Dismiss result" onClick={onDismiss}>
          ×
        </button>
      </div>

      <div className="cmd-card-body">
        {response.kind === "out_of_scope" && <p>{response.message}</p>}
        {response.kind === "needs_clarification" && (
          <>
            <p>{response.message}</p>
            <p className="mono cmd-missing">missing: {response.missing.join(", ")}</p>
          </>
        )}
        {response.kind === "result" && (
          <ResultBody
            execution={response.execution}
            onOpenQueue={onOpenQueue}
            onOpenAudit={onOpenAudit}
          />
        )}
      </div>

      <div className="cmd-card-foot">
        classifier: <span className="mono">{response.classifier_mode}</span> · {response.disclaimer}
      </div>
    </div>
  );
}

export function CommandBar({ clientId, period, onOpenQueue, onOpenAudit, onOpenSign }: Props) {
  const [utterance, setUtterance] = useState("");
  const [response, setResponse] = useState<CommandResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run(text: string) {
    if (!text.trim()) return;
    setBusy(true);
    setErr("");
    try {
      const res = await postCommand(text.trim(), clientId, period);
      setResponse(res);
      // A RUN_REVIEW here is a summary only — the facet UI lives on the Findings queue.
      void asRunReviewData(res);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
      setResponse(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="commandbar" aria-label="Command bar">
      <div className="composer">
        <textarea
          className="composer-input"
          placeholder="Ask the assistant about this return — a finding, a vendor, or a box value…"
          value={utterance}
          onChange={(e) => setUtterance(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              run(utterance);
            }
          }}
          disabled={busy}
        />
        <div className="composer-foot">
          <button className="composer-add" aria-label="Attach" type="button" disabled>
            +
          </button>
          <span className="spacer" />
          <span className="composer-mode">
            {response && response.classifier_mode !== "scripted"
              ? `${response.classifier_mode} · live tokens in use`
              : "no live tokens"}{" "}
            ▾
          </span>
          <button className="composer-send" aria-label="Ask" disabled={busy} onClick={() => run(utterance)}>
            <span aria-hidden="true">↑</span>
          </button>
        </div>
      </div>

      <div className="chips">
        {CHIPS.map((c) => (
          <button key={c.label} className="intent-chip" disabled={busy} onClick={() => run(c.utterance)}>
            {c.label}
          </button>
        ))}
        <button className="intent-chip" disabled={busy} onClick={() => onOpenSign?.()}>
          Sign working paper
        </button>
      </div>

      <div className="deferred-note">
        One way in — the assistant only classifies + runs reads over the frozen artifacts; it
        never acts on the text, and identity comes from the surface context ({clientId} /{" "}
        {period}), never a model guess. Review still happens in the queue.
      </div>

      {err && <div className="callout warn">{err}</div>}
      {response && (
        <CommandResultCard
          response={response}
          onDismiss={() => setResponse(null)}
          onOpenQueue={onOpenQueue}
          onOpenAudit={onOpenAudit}
        />
      )}
    </section>
  );
}
