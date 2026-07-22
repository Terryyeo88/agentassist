import { useState, type ChangeEvent } from "react";
import {
  postDecision,
  postSignUpload,
  uploadExtract,
  type Group,
  type UploadCoverageResponse,
} from "../api";
import { ReviewScreen, type Adjudication } from "./ReviewScreen";
import { SignModal } from "./SignModal";

// B3a-2: decisions persist via POST /decision keyed on the backend config's client_id for
// each engine branch (mirrors api/app.py's load_decision_entries call sites — app.py runs
// xero_f5 uploads under xero_demo, general extracts under extract_demo, sales exports under
// xero_sales_demo). The upload response deliberately carries NO client_id (its top-level key
// set is frozen), so this map is the frontend half of that contract. An unmapped source_kind
// gets no adjudication capability — review-only, never a dead control.
const CLIENT_ID_BY_SOURCE_KIND: Record<string, string> = {
  xero_f5_upload: "xero_demo",
  extract_review: "extract_demo",
  xero_sales_upload: "xero_sales_demo",
};

const REVIEW_ONLY_NOTE = "Review-only — decisions are not persistable for this export.";

/**
 * XeroUploadPanel — the source-selector's Xero branch. Upload a client .xlsx GST export; a
 * real Xero IRAS-F5 export runs the engine and its findings render in the SHARED central
 * review screen as CANDIDATES (BUILD 2, A1), alongside a per-check DATA-COVERAGE preview.
 *
 * ADJUDICABLE (B3a-2): the reviewer of record can Accept / Decline / Not an issue /
 * Mark known on upload findings; decisions persist via POST /decision to AgentAssist's OWN
 * append-only store (read-never-write-on-source) and re-apply when the retained workbook is
 * re-submitted. Un-fingerprinted rows (ledger-reconciliation findings) render DISABLED with
 * an honest reason — never a silent dead button. Sign-off routes to POST /sign/upload and is
 * gated to Xero F5 exports ONLY (the endpoint serves no other source_kind); a human signs —
 * the paper carries the reviewer's identity above an empty ruled line, never a system
 * signature. This panel never hits GET /review or POST /command — choosing Xero never
 * touches the frozen B1 review (box-isolation). Everything stays honestly framed
 * (validation_status unvalidated); findings are candidates, never a compliance verdict.
 */
export function XeroUploadPanel({ onChangeSource }: { onChangeSource: () => void }) {
  const [coverage, setCoverage] = useState<UploadCoverageResponse | null>(null);
  const [err, setErr] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Group>("needs_review");
  // Optional 820 account-transactions (ledger) export. Attach it BEFORE uploading the F5
  // export to run the ledger↔declared-return reconciliation (T2.24). Stored, not submitted;
  // the primary upload carries it. Only used when the primary is a Xero F5 export.
  const [ledgerFile, setLedgerFile] = useState<File | null>(null);
  // B3a-2: the primary workbook is RETAINED so a decision can re-apply (re-upload the same
  // file) and sign-off can re-POST it to /sign/upload — the server is stateless per upload.
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  // B3a-2 adjudication state — mirrors App's: the local map drives immediate button state;
  // persistence is the POST + re-upload round trip.
  const [decided, setDecided] = useState<Record<string, { action: string; note: string }>>({});
  // Reviewer of record — panel-local input, SAME identity concept as App's (B4/M3): one
  // free-text name attributed to decisions AND the sign-off. The SAP surface and this panel
  // never co-exist (Root switches sources), so the two input sites cannot diverge live.
  const [reviewerName, setReviewerName] = useState<string>("");
  const [signOpen, setSignOpen] = useState(false);

  function onLedger(event: ChangeEvent<HTMLInputElement>) {
    setLedgerFile(event.target.files?.[0] ?? null);
  }

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr("");
    setUploadedFile(file);
    setDecided({});
    uploadExtract(file, ledgerFile)
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
  // BUILD 3: the general-extract engine path ran under a DEFAULT DEMO config, not the uploader's.
  // The LOUD three-clause caveat below is MANDATORY on this path (the honesty line) and is SCOPED
  // to it — the Xero path (xero_f5_upload) must never show the default-config clause.
  const isExtractReview =
    coverage?.source_kind === "extract_review" || coverage?.config_scope === "default_demo";

  const clientId = coverage ? CLIENT_ID_BY_SOURCE_KIND[coverage.source_kind] : undefined;
  // Sign is F5-only: POST /sign/upload 422s on any other export format. Decisions and sign
  // have DIFFERENT eligibility — extract/sales get decisions, never a Sign button.
  const canSign = coverage?.source_kind === "xero_f5_upload" && uploadedFile !== null;

  const adjudication: Adjudication | undefined =
    findings.length > 0 && clientId
      ? {
          decided,
          onRecord: (id, action, note) => {
            setDecided((d) => ({ ...d, [id]: { action, note } }));
            const row = findings.find((it) => it.finding_id === id);
            // Defensive only: un-fingerprinted rows render DISABLED controls in
            // FindingDetail (no-silent-dead-buttons), so this cannot swallow a
            // persistable decision.
            if (!row?.fingerprint) return;
            const reviewer = reviewerName.trim();
            if (!reviewer) {
              setErr(
                "Decision recorded locally only — enter the reviewer of record above " +
                  "to persist decisions under a real name."
              );
              return;
            }
            postDecision({
              client_id: clientId,
              finding_id: id,
              fingerprint: row.fingerprint,
              action,
              note,
              reviewer_name: reviewer,
            })
              .then(() =>
                // Re-apply: re-submit the retained workbook so the persisted demotion /
                // annotation re-renders from the server (decisions survive refresh).
                uploadedFile ? uploadExtract(uploadedFile, ledgerFile) : null
              )
              .then((resp) => {
                if (resp) setCoverage(resp);
              })
              .catch((e) => setErr(String(e)));
          },
          ...(canSign ? { onOpenSign: () => setSignOpen(true) } : {}),
        }
      : undefined;

  const persistNote = adjudication
    ? canSign
      ? "Decisions persist to AgentAssist's own append-only store and re-apply when this " +
        "workbook is re-submitted. Sign-off re-runs the review over the retained workbook " +
        "and emits the signed working paper — a human signs; the system never does."
      : "Decisions persist to AgentAssist's own append-only store and re-apply on " +
        "re-upload. Sign-off is available for Xero F5 exports only in this slice."
    : undefined;

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

      <label className="xero-file-label reviewer-label">
        Reviewer of record
        <input
          className="reviewer-input"
          value={reviewerName}
          onChange={(e) => setReviewerName(e.target.value)}
          placeholder="Your name — decisions and sign-off are attributed to this reviewer"
        />
      </label>

      <label className="xero-file-label">
        Optional — 820 account-transactions (ledger) export
        <input
          className="xero-file-input xero-ledger-input"
          type="file"
          accept=".xlsx"
          onChange={onLedger}
        />
      </label>
      {ledgerFile && (
        <p className="xero-ledger-attached">
          Ledger attached: <span className="mono">{ledgerFile.name}</span> — the
          ledger↔declared-return reconciliation will run when you upload a Xero F5 export.
        </p>
      )}

      <label className="xero-file-label">
        Upload .xlsx GST export
        <input className="xero-file-input" type="file" accept=".xlsx" onChange={onFile} />
      </label>

      {busy && <div className="loading">Reading export…</div>}
      {err && <div className="errorbox">{err}</div>}

      {isExtractReview && (
        <section className="extract-caveat callout warn" aria-label="Demo review caveat">
          <strong>Demo review — read before relying on anything below.</strong>
          <ol className="extract-caveat-clauses">
            <li>Findings are <strong>unvalidated candidates</strong> for human review — not a verdict.</li>
            <li>
              Computed on an export format <strong>proven only against a synthetic sample</strong>;
              real-client-export validation is open (GTM-gated).
            </li>
            <li>
              This run used a <strong>default demo configuration, not your organisation's tax
              settings</strong>. Any finding that depends on GST <strong>rate or tax-code mapping</strong>
              is computed under the demo's settings and <strong>should not be relied on</strong> until
              your real config is wired in. The structural/arithmetic checks stand on their own.
            </li>
          </ol>
        </section>
      )}

      {findings.length > 0 && (
        <section className="xero-findings findings-view" aria-label="Review findings">
          {persistNote && <p className="xero-persist-note">{persistNote}</p>}
          <ReviewScreen
            queue={findings}
            selectedId={selectedId}
            onSelect={setSelectedId}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            adjudication={adjudication}
            reviewOnlyNote={adjudication ? undefined : REVIEW_ONLY_NOTE}
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

      {signOpen && uploadedFile && (
        <SignModal
          onClose={() => setSignOpen(false)}
          onSigned={(name) => setReviewerName(name)}
          initialReviewer={reviewerName}
          sign={(reviewer, firm) => postSignUpload(uploadedFile, ledgerFile, reviewer, firm)}
        />
      )}
    </div>
  );
}
