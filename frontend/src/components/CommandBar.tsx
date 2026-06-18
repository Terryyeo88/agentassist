import { useState } from "react";
import { postCommand, type CommandResponse, type ExecutionResult } from "../api";

/**
 * CommandBar — T6.2 LIVE command bar (Lane A + B + C1 join).
 *
 * "One way in": a free-text utterance is classified by the env-selected backend (scripted
 * by default — no tokens; live opt-in), routed to an intent, and executed over the FROZEN
 * artifacts via POST /command. The four buttons dispatch the four intents directly (a
 * canned curated utterance each). The review surface below stays the home; this only
 * classifies + runs reads. Identity (client/period) comes from the surface context, never
 * guessed by the model. Trust signals (mode + disclaimer) stay visible on every result.
 */
interface Props {
  clientId: string;
  period: string;
}

// Each button → a curated scripted utterance (agent/intent_curated.py) so the default
// scripted backend routes it deterministically. Surface context overrides the identity.
const BUTTON_UTTERANCES: { label: string; utterance: string }[] = [
  { label: "Run a review", utterance: "Run the GST review for Acme for 2024-Q1" },
  { label: "Show ledger", utterance: "Show me the justification ledger for Acme" },
  { label: "Show proposals", utterance: "What proposals are pending for Acme?" },
  { label: "Prior decisions", utterance: "Show prior decisions for Far East Imports, 2023-Q3" },
];

function ExecutionView({ execution }: { execution: ExecutionResult }) {
  const data = execution.data as Record<string, unknown>;
  const ledger = data.ledger as unknown[] | undefined;
  const proposals = data.proposals as unknown[] | undefined;
  const adjudications = data.adjudications as Record<string, unknown>[] | undefined;
  const dossiers = data.dossiers as unknown[] | undefined;
  const f5 = data.f5_summary as { boxes?: Record<string, number> } | undefined;

  return (
    <div className="cmd-result">
      <div className="cmd-result-head">
        Ran <strong>{execution.intent}</strong> · outcome {execution.outcome}
      </div>

      {ledger && <div>Justification ledger — {ledger.length} entries.</div>}
      {proposals && (
        <div>
          Pending proposals — {proposals.length}
          {proposals.length === 0 ? " (none staged in a fresh mock run)." : "."}
        </div>
      )}
      {adjudications && (
        <div>
          Prior adjudications — {adjudications.length}:
          <ul>
            {adjudications.map((a, i) => (
              <li key={i}>
                <span className="badge demoted">{String(a.disposition)}</span> by{" "}
                {String(a.reviewer)} ({String(a.period)})
                {a.reason ? ` — ${String(a.reason)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {dossiers && f5?.boxes && (
        <div>
          Frozen review — {dossiers.length} dossiers; F5 net GST{" "}
          <span className="mono">{f5.boxes.box_8_net_gst}</span>.
        </div>
      )}

      {execution.notes.length > 0 && (
        <div className="caveat">{execution.notes.join(" ")}</div>
      )}
    </div>
  );
}

function CommandResult({ response }: { response: CommandResponse }) {
  if (response.kind === "out_of_scope") {
    return <div className="callout info">{response.message}</div>;
  }
  if (response.kind === "needs_clarification") {
    return (
      <div className="callout warn">
        {response.message} <span className="mono">(missing: {response.missing.join(", ")})</span>
      </div>
    );
  }
  return <ExecutionView execution={response.execution} />;
}

export function CommandBar({ clientId, period }: Props) {
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
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
      setResponse(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="commandbar" aria-label="Command bar">
      <div className="row">
        <input
          type="text"
          placeholder="Ask the assistant…  e.g. Show prior decisions for Far East Imports, 2023-Q3"
          value={utterance}
          onChange={(e) => setUtterance(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") run(utterance);
          }}
          disabled={busy}
        />
        <button className="primary" disabled={busy} onClick={() => run(utterance)}>
          {busy ? "Running…" : "Ask"}
        </button>
        {BUTTON_UTTERANCES.map((b) => (
          <button key={b.label} className="ghost" disabled={busy} onClick={() => run(b.utterance)}>
            {b.label}
          </button>
        ))}
      </div>

      <div className="deferred-note">
        One way in — the assistant only classifies + runs reads over the frozen artifacts; it
        never acts on the text, and identity comes from the surface context ({clientId} /{" "}
        {period}), never a model guess. Review still happens in the queue below.
      </div>

      {err && <div className="callout warn">{err}</div>}
      {response && (
        <>
          <CommandResult response={response} />
          <div className="cmd-mode">
            classifier: <span className="mono">{response.classifier_mode}</span> · {response.disclaimer}
          </div>
        </>
      )}
    </section>
  );
}
