import type { CommandResponse, RunReviewData } from "../api";

/**
 * Shared RUN_REVIEW helpers (T6.3 Slice 4).
 *
 * Both the Review-home command bar and the Findings-view queue need the same RUN_REVIEW
 * shape off POST /command. The queue facets are SERVER-driven: App fires this curated
 * utterance (identity comes from the surface context, NOT this text — the scripted backend
 * routes it to RUN_REVIEW), then re-POSTs with `filters` on each facet toggle. The browser
 * never filters client-side and never recomputes a count.
 */

// A curated utterance the scripted classifier routes to RUN_REVIEW (mirrors CommandBar's
// BUTTON_UTTERANCES). The embedded "Acme / 2024-Q1" is ignored — identity is surface-supplied.
export const RUN_REVIEW_UTTERANCE = "Run the GST review for Acme for 2024-Q1";

/** A RUN_REVIEW result is the only response carrying a facet menu (reads carry no facets). */
export function asRunReviewData(response: CommandResponse | null): RunReviewData | null {
  if (response && response.kind === "result" && "available_facets" in response.execution.data) {
    return response.execution.data as unknown as RunReviewData;
  }
  return null;
}

// applied_filters echoed by the server is the SINGLE SOURCE OF TRUTH for what is selected.
// Normalise its scalar-or-array values into a uniform {facet: string[]}.
export function normalizeFilters(
  applied: Record<string, string | string[]>
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(applied)) {
    out[k] = Array.isArray(v) ? v.map(String) : [String(v)];
  }
  return out;
}

// Toggle one value within a facet (OR within a facet, AND across facets — the engine's
// semantics). Pure: returns the next filter REQUEST; the server still does the filtering.
export function toggleFilter(
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
