import type { FacetMap, Group, QueueItem } from "../api";
import { FacetFilter } from "./FacetFilter";
import { type ExpectedSource, isSourceMismatch, SourceMismatch } from "../lib/sourceGuard";
import { rowIdentitySuffix } from "../lib/rowIdentity";

/**
 * Facet props (T6.3 Slice 4) — the SERVER-driven facet menu, relocated onto the queue. The
 * menu / counts / selection all come from a RUN_REVIEW POST /command response held in App;
 * `visibleIds` is the set of finding_ids the server returned for the current filter (null when
 * no filter is active → show every row). The browser never filters or counts locally.
 */
export interface FacetProps {
  available: FacetMap;
  remaining: FacetMap;
  selected: Record<string, string[]>;
  onToggle: (facet: string, value: string) => void;
  onClear: () => void;
  busy: boolean;
  shown: number; // server findings count (N)
  total: number; // full server set (M)
  visibleIds: Set<string> | null; // server-narrowed view; null = no active filter
}

interface Props {
  items: QueueItem[];
  decided: Record<string, { action: string; note: string }>;
  activeTab: Group;
  setActiveTab: (g: Group) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  facets?: FacetProps;
  /** Source-tag guard (§2 defence-in-depth); OPT-IN. See lib/sourceGuard. */
  expectedSource?: ExpectedSource;
  sourceKind?: string | null;
}

const TAB_LABELS: Record<Group, string> = {
  needs_review: "Needs review",
  marked_known: "Marked known",
  decided: "Decided",
};

/**
 * Effective bucket for an item: a recorded decision wins (→ decided); otherwise the
 * server-assigned group (demoted → marked_known, else needs_review). Cardinality is
 * preserved — every item lands in exactly one bucket; demoted items are shown, not hidden.
 */
function bucketOf(item: QueueItem, decided: Props["decided"]): Group {
  if (decided[item.finding_id]) return "decided";
  return item.demoted ? "marked_known" : "needs_review";
}

// rowIdentitySuffix (D-18) now lives in lib/rowIdentity — the Sidebar's "Open findings" rail hits
// the SAME collision on the SAME rows (C-1), so both surfaces share one rule. Behaviour here is
// unchanged; see that module for why the guard is not specialised per surface.

export function Queue({
  items,
  decided,
  activeTab,
  setActiveTab,
  selectedId,
  onSelect,
  facets,
  expectedSource,
  sourceKind,
}: Props) {
  // §2 source-tag guard: withhold foreign-source rows and surface an honest mismatch. Opt-in
  // (inert unless expectedSource is set). Queue has no hooks, so the check can lead.
  if (expectedSource && isSourceMismatch(expectedSource, sourceKind)) {
    return <SourceMismatch expected={expectedSource} got={sourceKind} />;
  }

  // Narrow to the SERVER's filtered finding_ids when a filter is active; else keep every row.
  const narrowed =
    facets?.visibleIds ? items.filter((it) => facets.visibleIds!.has(it.finding_id)) : items;

  const counts: Record<Group, number> = { needs_review: 0, marked_known: 0, decided: 0 };
  for (const it of narrowed) counts[bucketOf(it, decided)]++;

  const visible = narrowed.filter((it) => bucketOf(it, decided) === activeTab);

  return (
    <div className="panel queue-panel">
      <div className="tabs" role="tablist">
        {(Object.keys(TAB_LABELS) as Group[]).map((g) => (
          <button
            key={g}
            role="tab"
            aria-selected={activeTab === g}
            className={activeTab === g ? "active" : ""}
            onClick={() => setActiveTab(g)}
          >
            {TAB_LABELS[g]}
            <span className="count">{counts[g]}</span>
          </button>
        ))}
      </div>

      {facets && Object.keys(facets.available).length > 0 && (
        <div className="facet-block">
          <div className="facet-block-head">
            <span className="facet-block-label">
              Filter · {facets.shown} of {facets.total} shown
            </span>
          </div>
          <FacetFilter
            available={facets.available}
            remaining={facets.remaining}
            selected={facets.selected}
            onToggle={facets.onToggle}
            onClear={facets.onClear}
            busy={facets.busy}
          />
        </div>
      )}

      <ul className="queue-list">
        {visible.length === 0 && (
          <li className="queue-empty">Nothing in “{TAB_LABELS[activeTab]}”.</li>
        )}
        {visible.map((it) => (
          <li key={it.finding_id}>
            <button
              className={`queue-row${selectedId === it.finding_id ? " active" : ""}`}
              onClick={() => onSelect(it.finding_id)}
            >
              <div className="qr-check">{it.check_id}</div>
              <div className="qr-top">
                <span className="qr-vendor">{it.vendor || "—"}</span>
                {it.severity && <span className={`sev-label sev-${it.severity}`}>{it.severity}</span>}
                {it.demoted && <span className="badge demoted">known</span>}
              </div>
              <div className="qr-doc">
                doc {it.doc_num ?? "—"} · {it.doc_date ?? "—"}
              </div>
              {/* D-18: a row with no vendor, severity, doc_num OR doc_date is indistinguishable
                  from its siblings here — measured on the two ledger-recon rows, which are
                  IDENTICAL in every field this list renders. Their finding_id's terminal
                  segment ("output"/"input") is the only non-prose thing that separates them, so
                  it is surfaced. NOT parsed out of description/recommendation text — the
                  identifier is data; the prose is not. */}
              {rowIdentitySuffix(it) && (
                <div className="mono qr-identity">{rowIdentitySuffix(it)}</div>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
