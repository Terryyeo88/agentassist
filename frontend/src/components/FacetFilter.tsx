import type { FacetMap } from "../api";

/**
 * FacetFilter — the data-derived facet menu (T6.3 Slice 3b).
 *
 * Renders whatever facets `available_facets` contains — NOTHING about error_code /
 * counterparty / doc_num is hardcoded, so the menu stays source-agnostic and future-proof
 * for when proposals/ledger facets land. Each facet is a row of `value:count` chips.
 *
 * The chip COUNT is the post-filter `remaining_facets` count (drill-down): a chip not in
 * the current view shows 0. The MENU (which facets/values exist) comes from the full
 * `available_facets`, so a narrowed view never hides a value you might still want.
 *
 * Clicking a chip is a REQUEST, not a local edit: the parent re-POSTs to /command and the
 * validated server result (echoed `applied_filters`) drives which chips read as selected.
 * The browser never filters client-side.
 */
interface Props {
  available: FacetMap; // the full menu (which facets + values exist) — always present
  remaining: FacetMap; // post-filter counts (recomputed over the narrowed view)
  selected: Record<string, string[]>; // server-echoed active selection per facet
  onToggle: (facet: string, value: string) => void;
  onClear: () => void;
  busy: boolean;
}

export function FacetFilter({ available, remaining, selected, onToggle, onClear, busy }: Props) {
  const facetNames = Object.keys(available);
  const hasActive = Object.values(selected).some((vs) => vs.length > 0);

  if (facetNames.length === 0) return null;

  return (
    <div className="facets" aria-label="Filter findings">
      <div className="facets-head">
        <span className="facets-title">Filter findings</span>
        {hasActive && (
          <button className="ghost facets-clear" disabled={busy} onClick={onClear}>
            Clear filters
          </button>
        )}
      </div>

      {facetNames.map((facet) => {
        const sel = selected[facet] ?? [];
        return (
          <div className="facet-group" key={facet}>
            <div className="facet-name">{facet.replace(/_/g, " ")}</div>
            <div className="facet-chips">
              {Object.keys(available[facet]).map((value) => {
                const count = remaining[facet]?.[value] ?? 0;
                const isOn = sel.includes(value);
                return (
                  <button
                    key={value}
                    className={`chip${isOn ? " on" : ""}`}
                    aria-pressed={isOn}
                    disabled={busy}
                    onClick={() => onToggle(facet, value)}
                  >
                    {value}
                    <span className="chip-count">{count}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
