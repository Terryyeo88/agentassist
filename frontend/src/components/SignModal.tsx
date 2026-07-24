import { useEffect, useRef, useState } from "react";
import { postSign, type SignResponse } from "../api";

// The subset of the sign response the modal renders — satisfied structurally by BOTH
// SignResponse (POST /sign, frozen SAP review) and SignUploadResponse (POST /sign/upload).
type SignResult = Pick<SignResponse, "reviewer_name" | "firm_name" | "working_paper_path">;

interface Props {
  onClose: () => void;
  onSigned: (reviewerName: string) => void;
  // t-xero-signoff (M3): pre-fill from the up-front reviewer-of-record capture so the
  // signature and the persisted decisions share ONE identity. Still editable here.
  initialReviewer?: string;
  // B3a-2: pluggable sign transport. Default = postSign (the frozen SAP review); the
  // upload panel injects a postSignUpload closure over its RETAINED workbook. Same modal,
  // same identity semantics — only the wire call differs.
  sign?: (reviewer: string, firm: string) => Promise<SignResult>;
}

/**
 * SignModal — collect the reviewer name (required) + firm, then POST /sign. The backend
 * reproduces ui.sign.sign_working_paper, carries the reviewer name onto the working paper,
 * and is box-isolated (F5 boxes are never recomputed). Sign refuses an empty reviewer.
 */
export function SignModal({ onClose, onSigned, initialReviewer, sign: signTransport }: Props) {
  const [reviewer, setReviewer] = useState(initialReviewer ?? "");
  const [firm, setFirm] = useState("");
  const [err, setErr] = useState("");
  const [result, setResult] = useState<SignResult | null>(null);
  const [busy, setBusy] = useState(false);

  // C2 download: the signed working paper is served read-only by GET /working-paper?path=…
  // (path-safe, allowlisted roots). Covers BOTH sign transports — /sign and /sign/upload
  // each return working_paper_path. Best-effort auto-download once; the visible button below
  // is the honest fallback when the browser blocks the programmatic click.
  const autoDownloaded = useRef(false);
  const downloadUrl = result
    ? `/api/working-paper?path=${encodeURIComponent(result.working_paper_path)}`
    : null;
  useEffect(() => {
    if (downloadUrl && !autoDownloaded.current) {
      autoDownloaded.current = true;                 // best-effort auto-download, once
      const a = document.createElement("a");
      a.href = downloadUrl; a.download = "";
      document.body.appendChild(a); a.click(); a.remove();
    }
  }, [downloadUrl]);

  async function sign() {
    if (!reviewer.trim()) {
      setErr("Sign requires a non-empty reviewer name.");
      return;
    }
    setErr("");
    setBusy(true);
    try {
      const res = await (signTransport ?? postSign)(reviewer.trim(), firm.trim());
      setResult(res);
      onSigned(res.reviewer_name);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Sign working paper</h3>
        <p style={{ fontSize: 13, color: "var(--ink-soft)", margin: 0 }}>
          Renders the working-paper PDF through the existing report path. The AI-candidates
          subsection stays disabled (T2.11). F5 boxes are box-isolated — never recomputed.
        </p>

        {!result ? (
          <>
            <label>Reviewer name (required to sign)</label>
            <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} autoFocus />
            <label>Firm name (optional)</label>
            <input value={firm} onChange={(e) => setFirm(e.target.value)} />
            {err && <div className="err">{err}</div>}
            <div className="actions">
              <button className="ghost" onClick={onClose}>
                Cancel
              </button>
              <button className="primary" onClick={sign} disabled={busy}>
                {busy ? "Signing…" : "Sign and emit working paper"}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="ok">
              Signed by <strong>{result.reviewer_name}</strong>
              {result.firm_name ? ` · ${result.firm_name}` : ""}.
            </div>
            <p style={{ fontSize: 12 }} className="mono">
              {result.working_paper_path}
            </p>
            {downloadUrl && (
              <a className="button primary" href={downloadUrl} download>Download working paper (PDF)</a>
            )}
            <div className="actions">
              <button className="primary" onClick={onClose}>
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
