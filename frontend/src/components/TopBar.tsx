export type View = "review" | "findings" | "audit";

interface Props {
  /** The trust badge text source. Takes the raw status string (SAP: review.validation_status;
   *  Xero: the upload response's validation_status) — TopBar no longer needs the whole payload,
   *  so it is shareable across the SAP and Xero surfaces (shell parity). */
  validationStatus: string;
  reviewerName: string;
  /** The three-view nav is OPTIONAL: it renders only when BOTH view and setView are supplied
   *  (the SAP surface). The Xero surface is a single non-tab-gated flow, so it omits them and
   *  no view-tabs render — no dead/fake affordances. */
  view?: View;
  setView?: (v: View) => void;
  onToggleSidebar: () => void;
  /** The sign entry point is OPTIONAL, on the same pattern as view/setView above: it renders as a
   *  live control only when a handler is supplied. Sign is F5-only (POST /sign/upload 422s any
   *  other export format), so a surface that is not currently signable OMITS it and the pill
   *  degrades to an inert identity chip — never a button that opens nothing, and never a sign
   *  affordance for a format the backend refuses. Callers gate this; TopBar only honours it. */
  onOpenSign?: () => void;
}

const VIEWS: { key: View; label: string }[] = [
  { key: "review", label: "Review" },
  { key: "findings", label: "Findings" },
  { key: "audit", label: "Audit" },
];

/**
 * TopBar — the dark header bar: a sidebar toggle, the F5·Review wordmark, the three view tabs
 * (SAP surface only), the loud UNVALIDATED trust badge (carried through verbatim — T2.11 is the
 * binding gate), and the reviewer-of-record pill (or "Sign in"). Shared by both surfaces; view
 * switching is mutually-exclusive on `view` where the nav is shown.
 */
export function TopBar({ validationStatus, reviewerName, view, setView, onToggleSidebar, onOpenSign }: Props) {
  return (
    <header className="topbar">
      <button className="hamburger" aria-label="Toggle sidebar" onClick={onToggleSidebar}>
        <span aria-hidden="true">≡</span>
      </button>

      <div className="brand">
        <span className="brand-f5">F5</span>
        <span className="brand-review">Review</span>
      </div>

      {view !== undefined && setView && (
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
      )}

      <span className="spacer" />

      <span className="badge unvalidated" title="T2.11 is the binding gate">
        {validationStatus} — pending specialist review
      </span>

      {/* C-5: a notifications bell used to sit here. It had no onClick, no state, and no prop
          feeding it — and nothing to feed it: `api.ts` exposes no notifications field and the
          backend serves no notifications route. §8 forbids a control that silently does nothing,
          and its always-on `.bell-dot` was worse than dead — a permanent "you have unread items"
          signal with no data behind it. §8's other outcome (disable + a visible specific reason)
          was rejected because there is no honest reason text for a feature that does not exist.
          Do not re-add a bell until a real notifications source exists to drive it. */}
      {onOpenSign ? (
        <button className="reviewer-pill" onClick={onOpenSign}>
          {reviewerName || "Sign in"}
        </button>
      ) : (
        // Not signable here: show the reviewer of record if one exists, but expose no control.
        <span className="reviewer-pill inert">{reviewerName || "—"}</span>
      )}
    </header>
  );
}
