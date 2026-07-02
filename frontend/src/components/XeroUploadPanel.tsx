import { useState, type ChangeEvent } from "react";
import { uploadExtract, type Group, type UploadCoverageResponse } from "../api";
import { ReviewScreen } from "./ReviewScreen";

const REVIEW_ONLY_NOTE = "Review-only — sign-off for uploads not yet available.";

/**
 * XeroUploadPanel — the source-selector's Xero branch. Upload a client .xlsx GST export; a
 * real Xero IRAS-F5 export runs the engine and its findings render in the SHARED central
 * review screen as CANDIDATES (BUILD 2, A1), alongside a per-check DATA-COVERAGE preview.
 *
 * REVIEW-ONLY by capability: there is no server-side store to sign an uploaded review
 * against, so the shared screen omits the decision/sign controls and surfaces an honest
 * review-only note (no dead controls). This panel only ever hits POST /review/upload — never
 * GET /review and never POST /command — so choosing Xero never touches the frozen B1 review
 * (box-isolation). Everything is honestly framed (validation_status unvalidated); findings
 * are candidates, never a validated review or a compliance verdict.
 */
export function XeroUploadPanel({ onChangeSource }: { onChangeSource: () => void }) {
  const [coverage, setCoverage] = useState<UploadCoverageResponse | null>(null);
  const [err, setErr] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Group>("needs_review");

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr("");
    uploadExtract(file)
      .then((resp) => {
        setCoverage(resp);
        // Default the selection to the first finding so its case-file card renders.
        setSelectedId(resp.queue && resp.queue.length ? resp.queue[0].finding_id : null);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  }

  // The coverage-degrade ASK (Decision 4, B1): a companion (supplier-master) sheet is needed
  // to enable the checks a Xero export cannot run. Coverage FACT only — no IRAS rationale.
  const degraded = (coverage?.coverage_status ?? []).filter((r) => r.level !== "full");
  const findings = coverage?.queue ?? [];

  return (
    <div className="xero-upload">
      <img className="aa-logo" src="/agentassist-logo.png" alt="AgentAssist" />
      <button type="button" className="source-back" onClick={onChangeSource}>
        ← Change source
      </button>
      <h1 className="source-title">Xero export — review</h1>
      <p className="source-sub">
        Upload a client .xlsx GST export. A real IRAS-F5 export is reviewed and its findings are
        shown below as candidates — unvalidated, for a human to adjudicate.
      </p>

      <label className="xero-file-label">
        Upload .xlsx GST export
        <input className="xero-file-input" type="file" accept=".xlsx" onChange={onFile} />
      </label>

      {busy && <div className="loading">Reading export…</div>}
      {err && <div className="errorbox">{err}</div>}

      {findings.length > 0 && (
        <section className="xero-findings findings-view" aria-label="Review findings">
          <ReviewScreen
            queue={findings}
            selectedId={selectedId}
            onSelect={setSelectedId}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            reviewOnlyNote={REVIEW_ONLY_NOTE}
          />
        </section>
      )}

      {coverage && (
        <section className="xero-coverage" aria-label="Coverage preview">
          <div className="xero-coverage-head">
            Data coverage · <strong>{coverage.validation_status}</strong>
          </div>
          <table className="xero-coverage-table">
            <thead>
              <tr>
                <th>Check</th>
                <th>Coverage</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {coverage.coverage_status.map((row) => (
                <tr key={row.check} className={`cov-${row.level}`}>
                  <td className="mono">{row.check}</td>
                  <td>{row.level}</td>
                  <td>{row.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {degraded.length > 0 && (
            <div className="xero-companion-ask callout info">
              Some checks are limited or unavailable on a Xero export alone. To enable them
              (e.g. <span className="mono">NO_GST_REG</span>), provide a supplier-master
              (companion) sheet at onboarding.
            </div>
          )}
          <footer className="xero-disclaimer">{coverage.disclaimer}</footer>
        </section>
      )}
    </div>
  );
}
