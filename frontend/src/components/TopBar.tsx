import type { ReviewPayload } from "../api";

interface Props {
  review: ReviewPayload;
  reviewerName: string;
}

/**
 * TopBar — brand, the demo client/period context, the UNVALIDATED trust badge, and the
 * reviewer of record. The client display name is the real frozen demo identity
 * ("SAP B1 Demo (SBODEMOSG)"); the UNVALIDATED badge stays loud beside it.
 */
export function TopBar({ review, reviewerName }: Props) {
  return (
    <header className="topbar">
      <div>
        <div className="brand">
          Agent<span className="mark">Assist</span>
        </div>
        <div className="context">
          {review.client.client_name} · {review.period.label} ({review.period.start} →{" "}
          {review.period.end})
        </div>
      </div>
      <span className="badge unvalidated" title="T2.11 is the binding gate">
        {review.validation_status} — pending specialist review
      </span>
      <div className="spacer" />
      <div className="reviewer">
        Reviewer of record
        <br />
        <strong>{reviewerName || "— not signed —"}</strong>
      </div>
    </header>
  );
}
