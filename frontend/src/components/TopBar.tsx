import type { ReviewPayload } from "../api";

export type View = "review" | "findings" | "audit";

interface Props {
  review: ReviewPayload;
  reviewerName: string;
  view: View;
  setView: (v: View) => void;
  onToggleSidebar: () => void;
  onOpenSign: () => void;
}

const VIEWS: { key: View; label: string }[] = [
  { key: "review", label: "Review" },
  { key: "findings", label: "Findings" },
  { key: "audit", label: "Audit" },
];

/**
 * TopBar — the dark header bar: a sidebar toggle, the F5·Review wordmark, the three view tabs,
 * the loud UNVALIDATED trust badge (carried through verbatim — T2.11 is the binding gate), and
 * the reviewer-of-record pill (or "Sign in"). View switching is mutually-exclusive on `view`.
 */
export function TopBar({ review, reviewerName, view, setView, onToggleSidebar, onOpenSign }: Props) {
  return (
    <header className="topbar">
      <button className="hamburger" aria-label="Toggle sidebar" onClick={onToggleSidebar}>
        <span aria-hidden="true">≡</span>
      </button>

      <div className="brand">
        <span className="brand-f5">F5</span>
        <span className="brand-review">Review</span>
      </div>

      <nav aria-label="Primary" className="header-nav">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            className={`nav-tab${view === v.key ? " active" : ""}`}
            aria-current={view === v.key ? "page" : undefined}
            onClick={() => setView(v.key)}
          >
            {v.label}
          </button>
        ))}
      </nav>

      <span className="spacer" />

      <span className="badge unvalidated" title="T2.11 is the binding gate">
        {review.validation_status} — pending specialist review
      </span>

      <button className="bell" aria-label="Notifications">
        <span className="bell-dot" aria-hidden="true" />
        <span aria-hidden="true">◔</span>
      </button>

      <button className="reviewer-pill" onClick={onOpenSign}>
        {reviewerName || "Sign in"}
      </button>
    </header>
  );
}
