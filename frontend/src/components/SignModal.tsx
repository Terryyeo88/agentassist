import { useState } from "react";
import { postSign, type SignResponse } from "../api";

interface Props {
  onClose: () => void;
  onSigned: (reviewerName: string) => void;
}

/**
 * SignModal — collect the reviewer name (required) + firm, then POST /sign. The backend
 * reproduces ui.sign.sign_working_paper, carries the reviewer name onto the working paper,
 * and is box-isolated (F5 boxes are never recomputed). Sign refuses an empty reviewer.
 */
export function SignModal({ onClose, onSigned }: Props) {
  const [reviewer, setReviewer] = useState("");
  const [firm, setFirm] = useState("");
  const [err, setErr] = useState("");
  const [result, setResult] = useState<SignResponse | null>(null);
  const [busy, setBusy] = useState(false);

  async function sign() {
    if (!reviewer.trim()) {
      setErr("Sign requires a non-empty reviewer name.");
      return;
    }
    setErr("");
    setBusy(true);
    try {
      const res = await postSign(reviewer.trim(), firm.trim());
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
