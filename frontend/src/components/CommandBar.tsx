import { useState } from "react";
import {
  postCommand,
  type CommandResponse,
  type ExecutionResult,
  type RunReviewData,
} from "../api";
import { FacetFilter } from "./FacetFilter";

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

      {execution.notes.length > 0 && (
        <div className="caveat">{execution.notes.join(" ")}</div>
      )}
    </div>
  );
}

// applied_filters echoed by the server is the SINGLE SOURCE OF TRUTH for what is selected.
// Normalise its scalar-or-array values into a uniform {facet: string[]}.
function normalizeFilters(applied: Record<string, string | string[]>): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(applied)) {
    out[k] = Array.isArray(v) ? v.map(String) : [String(v)];
  }
  return out;
}

// Toggle one value within a facet (OR within a facet, AND across facets — the engine's
// semantics). Pure: returns the next filter REQUEST; the server still does the filtering.
function toggleFilter(
  current: Record<string, string[]>,
  facet: string,
  value: string
): Record<string, string[]> {
  const next: Record<string, string[]> = {};
  for (const [k, vs] of Object.entries(current)) next[k] = [...vs];
  const cur = next[facet] ?? [];
  if (cur.includes(value)) {
    const kept = cur.filter((v) => v !== value);
    if (kept.length) next[facet] = kept;
    else delete next[facet];
  } else {
    next[facet] = [...cur, value];
  }
  return next;
}

/**
 * RunReviewResult — the RUN_REVIEW execution rendered as a filterable view (T6.3 Slice 3b).
 *
 * Thin view over the validated server seam: the facet menu, the narrowed findings, the
 * "X of Y shown" count, the active-filters line and any filter_rejection all read straight
 * off the response `data` — nothing is recomputed in the browser. The F5 boxes come from
 * the FULL result and do NOT move under a filter (box-isolation, made visible).
 */
function RunReviewResult({
  data,
  busy,
  onToggle,
  onClear,
}: {
  data: RunReviewData;
  busy: boolean;
  onToggle: (facet: string, value: string) => void;
  onClear: () => void;
}) {
  const selected = normalizeFilters(data.applied_filters);
  const shown = data.findings.length;
  const total = data.dossiers.length;
  const rejection = data.filter_rejection;
  const activeFacets = Object.entries(selected).filter(([, vs]) => vs.length > 0);

  return (
    <div className="cmd-result">
      <div className="cmd-result-head">
        Frozen review — <strong>{shown} of {total}</strong> findings shown.
      </div>

      {/* F5 boxes from the FULL result — box-isolation made visible (never change on filter). */}
      <div className="f5 cmd-f5" aria-label="F5 summary">
        {Object.entries(data.f5_summary.boxes).map(([k, v]) => (
          <div className="box" key={k}>
            <div className="k">{k.replace(/_/g, " ")}</div>
            <div className="v">
              {data.f5_summary.currency} {Number(v).toLocaleString()}
            </div>
          </div>
        ))}
      </div>

      <FacetFilter
        available={data.available_facets}
        remaining={data.remaining_facets}
        selected={selected}
        onToggle={onToggle}
        onClear={onClear}
        busy={busy}
      />

      {rejection && (
        <div className="callout warn" role="alert">
          {rejection.message}
        </div>
      )}

      {activeFacets.length > 0 && (
        <div className="active-filters">
          Filtering by{" "}
          {activeFacets.map(([f, vs]) => (
            <span key={f} className="mono active-filter">
              {f}={vs.join(" | ")}
            </span>
          ))}
        </div>
      )}

      <ul className="facet-findings">
        {data.findings.length === 0 && (
          <li className="facet-empty">No findings match this filter (an honest empty set).</li>
        )}
        {data.findings.map((f) => (
          <li key={f.finding_id} className="facet-finding">
            <span className="qr-check">{f.check_id}</span>
            <span className="mono finding-id">{f.finding_id}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// A RUN_REVIEW result is the only one carrying a facet menu (reads carry no facets).
function asRunReviewData(response: CommandResponse | null): RunReviewData | null {
  if (response && response.kind === "result" && "available_facets" in response.execution.data) {
    return response.execution.data as unknown as RunReviewData;
  }
  return null;
}

function CommandResult({
  response,
  busy,
  onToggle,
  onClear,
}: {
  response: CommandResponse;
  busy: boolean;
  onToggle: (facet: string, value: string) => void;
  onClear: () => void;
}) {
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
  const runReview = asRunReviewData(response);
  if (runReview) {
    return (
      <RunReviewResult data={runReview} busy={busy} onToggle={onToggle} onClear={onClear} />
    );
  }
  return <ExecutionView execution={response.execution} />;
}

export function CommandBar({ clientId, period }: Props) {
  const [utterance, setUtterance] = useState("");
  const [response, setResponse] = useState<CommandResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // The utterance that produced the current RUN_REVIEW result. Filtering re-POSTs THIS
  // utterance (with the chosen filters + the surface identity) — never a model guess.
  // null for reads / no result, which is what hides the facet panel.
  const [reviewUtterance, setReviewUtterance] = useState<string | null>(null);

  async function run(text: string) {
    if (!text.trim()) return;
    setBusy(true);
    setErr("");
    try {
      const res = await postCommand(text.trim(), clientId, period);
      setResponse(res);
      // Remember the utterance only when this is a filterable RUN_REVIEW result.
      setReviewUtterance(asRunReviewData(res) ? text.trim() : null);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
      setResponse(null);
      setReviewUtterance(null);
    } finally {
      setBusy(false);
    }
  }

  // Re-run the last RUN_REVIEW with a new filter set. Always sends `filters` (even {} on a
  // clear) so the validated, box-isolated server result stays the single source of truth —
  // we never filter client-side.
  async function changeFilters(next: Record<string, string[]>) {
    if (reviewUtterance === null) return;
    setBusy(true);
    setErr("");
    try {
      const res = await postCommand(reviewUtterance, clientId, period, next);
      setResponse(res);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  // Build the next filter request from the server-echoed selection + the toggle.
  function handleToggle(facet: string, value: string) {
    const current = asRunReviewData(response);
    const selection = current ? normalizeFilters(current.applied_filters) : {};
    changeFilters(toggleFilter(selection, facet, value));
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
          <CommandResult
            response={response}
            busy={busy}
            onToggle={handleToggle}
            onClear={() => changeFilters({})}
          />
          <div className="cmd-mode">
            classifier: <span className="mono">{response.classifier_mode}</span> · {response.disclaimer}
          </div>
        </>
      )}
    </section>
  );
}
