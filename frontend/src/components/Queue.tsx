import type { Group, QueueItem } from "../api";

interface Props {
  items: QueueItem[];
  decided: Record<string, { action: string; note: string }>;
  activeTab: Group;
  setActiveTab: (g: Group) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
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

export function Queue({
  items,
  decided,
  activeTab,
  setActiveTab,
  selectedId,
  onSelect,
}: Props) {
  const counts: Record<Group, number> = { needs_review: 0, marked_known: 0, decided: 0 };
  for (const it of items) counts[bucketOf(it, decided)]++;

  const visible = items.filter((it) => bucketOf(it, decided) === activeTab);

  return (
    <div className="panel">
      <h3>Review queue</h3>
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
      <ul className="queue-list">
        {visible.length === 0 && (
          <li style={{ padding: "16px", color: "var(--ink-faint)" }}>
            Nothing in “{TAB_LABELS[activeTab]}”.
          </li>
        )}
        {visible.map((it) => (
          <li key={it.finding_id}>
            <button
              className={`queue-row${selectedId === it.finding_id ? " active" : ""}`}
              onClick={() => onSelect(it.finding_id)}
            >
              <div className="qr-top">
                <span className="qr-check">{it.check_id}</span>
                {it.severity && <span className={`badge sev-${it.severity}`}>{it.severity}</span>}
                {it.demoted && <span className="badge demoted">known</span>}
              </div>
              <div className="qr-vendor">{it.vendor || "—"}</div>
              <div className="qr-doc">doc {it.doc_num ?? "—"}</div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
