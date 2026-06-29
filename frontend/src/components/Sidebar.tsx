import type { QueueItem, ReviewPayload } from "../api";

interface Props {
  review: ReviewPayload;
  decided: Record<string, { action: string; note: string }>;
  onSelectFinding: (id: string) => void;
}

const SEV_ORDER: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };

/**
 * Sidebar — the collapsible left rail: a "This period" tally + a "Open findings" shortlist.
 * Pure presentation over the queue + recorded decisions; selecting a finding jumps to the
 * Findings view. Carries no tax conclusion — it counts and links the existing rows only.
 */
export function Sidebar({ review, decided, onSelectFinding }: Props) {
  const q = review.queue;
  const sev = (s: string) => q.filter((it) => it.severity === s).length;
  const recorded = Object.keys(decided).length;

  const open: QueueItem[] = q
    .filter((it) => !it.demoted && !decided[it.finding_id])
    .sort((a, b) => (SEV_ORDER[a.severity ?? "LOW"] ?? 3) - (SEV_ORDER[b.severity ?? "LOW"] ?? 3));

  return (
    <aside className="sidebar" aria-label="Overview">
      <div className="sidebar-title">Overview</div>

      <div className="search-pill" aria-hidden="true">
        Look up a vendor or doc
      </div>

      <div className="side-card">
        <div className="side-card-title">This period</div>
        <div className="stat-row">
          <span>Findings</span>
          <span className="stat-val">{q.length}</span>
        </div>
        <div className="stat-row">
          <span>High</span>
          <span className="stat-val sev-HIGH">{sev("HIGH")}</span>
        </div>
        <div className="stat-row">
          <span>Medium</span>
          <span className="stat-val sev-MEDIUM">{sev("MEDIUM")}</span>
        </div>
        <div className="stat-row">
          <span>Low</span>
          <span className="stat-val sev-LOW">{sev("LOW")}</span>
        </div>
        <div className="stat-row">
          <span>Marked known</span>
          <span className="stat-val sev-known">{q.filter((it) => it.demoted).length}</span>
        </div>
        <div className="progress-label">
          Decisions recorded {recorded} / {q.length}
        </div>
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: q.length ? `${(recorded / q.length) * 100}%` : "0%" }}
          />
        </div>
      </div>

      <div className="side-card">
        <div className="side-card-title">Open findings</div>
        {open.length === 0 && <div className="side-empty">Nothing open.</div>}
        {open.map((it) => (
          <button key={it.finding_id} className="open-row" onClick={() => onSelectFinding(it.finding_id)}>
            <span className={`sev-dot sev-${it.severity}`} aria-hidden="true" />
            <span className="open-vendor">
              {it.vendor || "—"}
              <span className="mono open-check">{it.check_id}</span>
            </span>
            <span className={`sev-label sev-${it.severity}`}>{it.severity}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
