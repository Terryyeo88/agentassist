import { useEffect, useState } from "react";

/**
 * SURFACE SELECTION (C-8), not fallback. Two corpora, two routes, no shared resolver —
 * D-42's structure applied at the client:
 *   - reviewId present  (the Xero surface, which creates a session on every upload, D-43)
 *     -> GET /api/review/{reviewId}/document/{ref} — the review's own uploaded documents.
 *   - reviewId absent   (the SAP surface)
 *     -> GET /api/document/{ref} — the SAP fixture corpus, today's behaviour unchanged.
 * ONE attempt per request, chosen by which surface is mounted. A FALLBACK (try the review
 * route, then reach into the SAP corpus on a 404) is banned and test-pinned out
 * (DocumentViewerReviewRoute T9: with a reviewId, a 404 is FINAL): a viewer that silently
 * tries a second corpus reintroduces the D-34 substitution at the client.
 *
 * The selector infers the surface from the ABSENCE of reviewId. That inference is
 * load-bearing: a Xero surface that failed to thread its reviewId degrades silently onto
 * the SAP route — harmless only because D-34 makes that route REFUSE a cross-namespace
 * reference (honest 404 -> the absent state below) rather than substitute a
 * digit-colliding document. A mis-selection is merely wrong, not dangerous.
 *
 * The reference is passed VERBATIM (encodeURIComponent is transport encoding, not
 * parsing) — the client never strips, uppercases, or pattern-matches a reference.
 */
export function DocumentViewer({ docNum, reviewId, onClose }: { docNum: string | number; reviewId?: string; onClose: () => void }) {
  const [state, setState] = useState<"loading" | "ready" | "absent" | "error">("loading");
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let objUrl: string | null = null;
    let cancelled = false;
    setState("loading"); setUrl(null);
    const ref = encodeURIComponent(String(docNum));
    fetch(reviewId
      ? `/api/review/${encodeURIComponent(reviewId)}/document/${ref}`
      : `/api/document/${ref}`)
      .then(async (r) => {
        if (cancelled) return;
        if (r.status === 404) return setState("absent");
        if (!r.ok) return setState("error");
        const blob = await r.blob();
        if (cancelled) return;
        objUrl = URL.createObjectURL(blob);
        setUrl(objUrl); setState("ready");
      })
      .catch(() => { if (!cancelled) setState("error"); });
    return () => { cancelled = true; if (objUrl) URL.revokeObjectURL(objUrl); };
  }, [docNum, reviewId]);
  return (
    <aside className="doc-viewer" aria-label="Source document">
      <div className="doc-viewer-head">
        Source document · <span className="mono">Doc {String(docNum)}</span>
        <button className="link" onClick={onClose}>Close</button>
      </div>
      {state === "loading" && <div className="loading">Loading source document…</div>}
      {state === "absent" && <div className="callout warn">No source document on file for this finding.</div>}
      {state === "error" && <div className="callout warn">Couldn’t load the source document.</div>}
      {state === "ready" && url && (
        <object data={url} type="application/pdf" className="doc-frame" aria-label={`Invoice ${String(docNum)}`} />
      )}
    </aside>
  );
}
