import { useState, type ChangeEvent } from "react";
import { uploadExtract, type UploadCoverageResponse } from "../api";

/**
 * XeroUploadPanel — the source-selector's Xero branch. Upload a client .xlsx GST export and
 * see a per-check DATA-COVERAGE preview (which canonical fields the export carried).
 *
 * COVERAGE-ONLY by contract: the engine is never run here. This panel only ever hits
 * POST /review/upload — never GET /review and never POST /command — so choosing Xero cannot
 * run the B1 review (box-isolation). Producing a real review from an uploaded extract is a
 * separate later task (deferred). Coverage is data-presence, honestly framed
 * (validation_status unvalidated), never a validated review or a compliance verdict.
 */
export function XeroUploadPanel({ onChangeSource }: { onChangeSource: () => void }) {
  const [coverage, setCoverage] = useState<UploadCoverageResponse | null>(null);
  const [err, setErr] = useState<string>("");
  const [busy, setBusy] = useState(false);

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr("");
    uploadExtract(file)
      .then(setCoverage)
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  }

  return (
    <div className="xero-upload">
      <img className="aa-logo" src="/agentassist-logo.png" alt="AgentAssist" />
      <button type="button" className="source-back" onClick={onChangeSource}>
        ← Change source
      </button>
      <h1 className="source-title">Xero export — coverage preview</h1>
      <p className="source-sub">
        Upload a client .xlsx GST export. Coverage only — the engine is not run; this is a
        data-presence preview, not a validated review.
      </p>

      <label className="xero-file-label">
        Upload .xlsx GST export
        <input className="xero-file-input" type="file" accept=".xlsx" onChange={onFile} />
      </label>

      {busy && <div className="loading">Reading export…</div>}
      {err && <div className="errorbox">{err}</div>}

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
          <footer className="xero-disclaimer">{coverage.disclaimer}</footer>
        </section>
      )}
    </div>
  );
}
