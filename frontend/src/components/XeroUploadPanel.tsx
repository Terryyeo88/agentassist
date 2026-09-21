import { useEffect, useState, type ChangeEvent } from "react";
import {
  createReviewSession,
  getDecisions,
  postDecision,
  postSignUpload,
  uploadExtract,
  type DecisionEntry,
  type DecisionResponse,
  type Group,
  type UploadCoverageResponse,
} from "../api";
import { ReviewScreen, type Adjudication } from "./ReviewScreen";
import { SignModal } from "./SignModal";
import { TopBar, type View } from "./TopBar";
import { XeroAuditView } from "./XeroAuditView";
import { Sidebar } from "./Sidebar";
import { XeroF5Strip } from "./XeroF5Strip";
import { XeroCoveragePanel } from "./XeroCoveragePanel";
import { coverageLabel } from "../lib/coverageLabels";

// G-3: the four document-pre-pass checks, mirroring feeders/coverage_status.py:93-98. A fixed
// id set, so membership never depends on reading the coverage prose (D-40).
const DOCUMENT_PREPASS_CHECKS = [
  "gst_amount_mismatch",
  "correct_period",
  "total_inconsistency",
  "reg11_supplier_gst_absent",
];

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
 * C-2: the server's own words, with nothing added. `api.ts` throws the response body's `detail`
 * verbatim, so an Error's `.message` IS the server message — while `String(e)` on an Error
 * prepends "Error: ", which put a synthetic token in front of real server copy. Anything that is
 * not an Error is stringified unchanged rather than guessed at: an unrecognised failure is
 * surfaced as-is, never replaced with a friendlier invention.
 */
function serverMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

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
  // C-2 (Q1): the reviewer-of-record PROMPT is not a failure and no longer shares the `err`
  // channel with real server 422s. Separate state, separate treatment, and rendered on the
  // Findings view — the panel mounts exactly one <ReviewScreen>, inside `view === "findings"`,
  // so that is the only view whose controls can raise this prompt. Left on the Review view it
  // would have been a message the reviewer could never see.
  const [notice, setNotice] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Group>("needs_review");
  // Optional 820 account-transactions (ledger) export. Attach it BEFORE uploading the F5
  // export to run the ledger↔declared-return reconciliation (T2.24). Stored, not submitted;
  // the primary upload carries it. Only used when the primary is a Xero F5 export.
  const [ledgerFile, setLedgerFile] = useState<File | null>(null);
  // C-8: source-document PDFs attached BEFORE uploading (like the ledger). Sent as repeated
  // "documents" multipart parts (D-38); the backend persists them under the review session
  // (reviews/<rid>/documents/, D-36) and serves them to the viewer via the review-scoped
  // route (D-42). Server caps apply (D-39): 10 MiB/file, 50 MiB/upload, 50 files.
  const [documentFiles, setDocumentFiles] = useState<File[]>([]);
  // Slice C: the Xero Contacts export — the SUPPLIER MASTER. An F5 export carries no
  // supplier registration numbers, so without this the supplier-registration check
  // (NO_GST_REG) reports `unavailable` and produces nothing. Staged like the ledger.
  const [contactsFile, setContactsFile] = useState<File | null>(null);
  // C-8 (D-43): the review session, created LAZILY ON UPLOAD, ALWAYS — one session per
  // upload flow. Threaded to ReviewScreen -> DocumentViewer, which SELECTS the
  // review-scoped document route when present (surface selection, not fallback).
  const [reviewId, setReviewId] = useState<string | null>(null);
  // Slice A (A1): STAGED, not yet run. Selecting a file only stages it; nothing reaches the
  // network until "Run review" is pressed. Kept apart from the RAN-WITH set below so that
  // re-staging after a run cannot retroactively change what the last run is said to have sent.
  const [primaryFile, setPrimaryFile] = useState<File | null>(null);
  // True when the staging has moved on from the result currently on screen. Purely a
  // statement about freshness — it never triggers a run on its own (A1-T7).
  const [stagedDirty, setStagedDirty] = useState(false);
  // B3a-2: the primary workbook is RETAINED so a decision can re-apply (re-upload the same
  // file) and sign-off can re-POST it to /sign/upload — the server is stateless per upload.
  // Slice A: this is now the RAN-WITH primary, captured at run time.
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  // Slice A (G-1): the ledger and documents AS RUN. The re-apply and the sign must re-submit
  // what the RUN submitted, not whatever happens to be staged now — otherwise recording a
  // decision silently re-runs against a different input set. Before this, the re-apply passed
  // neither review_id nor documents, so the backend (which resolves attached documents from
  // the session) returned a queue with every document-derived finding missing and four
  // coverage rows regressed to `unavailable`: one adjudication deleted four findings from
  // the screen while the signed paper still contained them.
  const [ranLedger, setRanLedger] = useState<File | null>(null);
  const [ranDocuments, setRanDocuments] = useState<File[]>([]);
  // Slice C (G-1): the contacts export AS RUN. The re-apply and the sign both read THIS,
  // never `contactsFile` — re-staging a different Contacts file after a run must not
  // change the inputs behind a decision already recorded against the result on screen.
  const [ranContacts, setRanContacts] = useState<File | null>(null);
  // B3a-2 adjudication state — mirrors App's: the local map drives immediate button state;
  // persistence is the POST + re-upload round trip.
  const [decided, setDecided] = useState<Record<string, { action: string; note: string }>>({});
  // Reviewer of record — panel-local input, SAME identity concept as App's (B4/M3): one
  // free-text name attributed to decisions AND the sign-off. The SAP surface and this panel
  // never co-exist (Root switches sources), so the two input sites cannot diverge live.
  const [reviewerName, setReviewerName] = useState<string>("");
  const [signOpen, setSignOpen] = useState(false);
  // Shell chrome (shell parity with the SAP surface): the collapsible left rail.
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // D-13: the three mutually-exclusive views, mirroring App.tsx. "review" is home — the upload
  // controls, the F5 strip and the coverage panel live there; findings and the session decision
  // list get their own views.
  const [view, setView] = useState<View>("review");
  // D-17: the decisions THIS SESSION recorded, captured from the POST /decision responses.
  // They are kept even though the store now returns prior decisions too: a POST response is
  // the FRESHER fact (the load happened before it) and it carries finding_id + the action
  // verb, which the stored record does not.
  const [sessionDecisions, setSessionDecisions] = useState<DecisionResponse[]>([]);
  // C-6b: the store's OWN records for this upload's client, loaded on arrival. Held apart from
  // sessionDecisions rather than merged into it — a later re-load returning [] must never be
  // able to erase what this browser recorded.
  const [priorDecisions, setPriorDecisions] = useState<DecisionEntry[]>([]);

  function selectFromSidebar(id: string) {
    setSelectedId(id);
    setView("findings");
  }

  // Slice A (A1): the three inputs STAGE and nothing else. `markStaged` records that the
  // staging has moved past whatever result is on screen — only once a run has produced one,
  // so the pre-run state never shows a "not been run yet" notice about nothing.
  function markStaged() {
    if (coverage) setStagedDirty(true);
  }

  function onLedger(event: ChangeEvent<HTMLInputElement>) {
    setLedgerFile(event.target.files?.[0] ?? null);
    markStaged();
  }

  function onDocuments(event: ChangeEvent<HTMLInputElement>) {
    setDocumentFiles(Array.from(event.target.files ?? []));
    markStaged();
  }

  function onContacts(event: ChangeEvent<HTMLInputElement>) {
    setContactsFile(event.target.files?.[0] ?? null);
    markStaged();
  }

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setPrimaryFile(file);
    markStaged();
  }

  function clearLedger() {
    setLedgerFile(null);
    markStaged();
  }

  function clearDocuments() {
    setDocumentFiles([]);
    markStaged();
  }

  function clearContacts() {
    setContactsFile(null);
    markStaged();
  }

  /**
   * Slice A (A1): the ONE place an upload starts. Everything the run needs is already
   * staged, so the request carries the primary, the ledger and every document TOGETHER —
   * the previous flow uploaded from the primary input's onChange, which meant anything
   * attached afterwards was simply left out of the request.
   *
   * Each press creates a NEW session (PROPOSED — Terry ratifies): accumulating successive
   * runs into one session is the accumulated-sign work (G-8) and is out of this slice.
   */
  async function runReview() {
    const file = primaryFile;
    if (!file || busy) return;
    setBusy(true);
    setErr("");
    setNotice("");
    setUploadedFile(file);
    setDecided({});
    try {
      // C-8 (D-43): create the session on EVERY upload — lazily here, never on mount
      // (POST /review-session writes reviews/<rid>/ to disk; a session per page view
      // litters the store) and never conditionally on documents (one button must not do
      // two different things). Failure handling is asymmetric on purpose: with documents
      // attached a failed session is FATAL (they need the session — the backend would
      // 422 them, and dropping them silently is the D-37 sin); with none, the upload
      // proceeds stateless, byte-identical to the pre-session flow.
      let rid: string | undefined;
      try {
        rid = await createReviewSession();
        setReviewId(rid);
      } catch (sessionErr) {
        if (documentFiles.length > 0) throw sessionErr;
        rid = undefined;
        setReviewId(null);
      }
      const resp = await uploadExtract(
        file,
        ledgerFile,
        rid,
        documentFiles.length > 0 ? documentFiles : undefined,
        contactsFile,
      );
      setCoverage(resp);
      // G-1: capture what this run actually sent. The re-apply and the sign re-submit THESE,
      // never the live staging, so a later re-stage cannot change the inputs behind a
      // decision that was recorded against this result.
      setRanLedger(ledgerFile);
      setRanDocuments(documentFiles);
      setRanContacts(contactsFile);
      setStagedDirty(false);
      // Default the selection to the first finding so its case-file card renders.
      setSelectedId(resp.queue && resp.queue.length ? resp.queue[0].finding_id : null);
    } catch (e) {
      setErr(serverMessage(e));
    } finally {
      setBusy(false);
    }
  }

  // The coverage-degrade ASK (Decision 4, B1): a companion (supplier-master) sheet is needed
  // to enable the checks a Xero export cannot run. Coverage FACT only — no IRAS rationale.
  const degraded = (coverage?.coverage_status ?? []).filter((r) => r.level !== "full");
  // G-3: the four document-pre-pass checks, in the backend's own order. Membership is by
  // check id (a fixed, code-level set — feeders/coverage_status.py:93-98), never by reading
  // the prose. Empty until a run has produced coverage, which is what keeps the replacement
  // tile silent rather than speculative before the first run.
  const documentCoverage = (coverage?.coverage_status ?? []).filter((r) =>
    DOCUMENT_PREPASS_CHECKS.includes(r.check)
  );
  const findings = coverage?.queue ?? [];
  // BUILD 3: the general-extract engine path ran under a DEFAULT DEMO config, not the uploader's.
  // The LOUD three-clause caveat below is MANDATORY on this path (the honesty line) and is SCOPED
  // to it — the Xero path (xero_f5_upload) must never show the default-config clause.
  const isExtractReview =
    coverage?.source_kind === "extract_review" || coverage?.config_scope === "default_demo";

  const clientId = coverage ? CLIENT_ID_BY_SOURCE_KIND[coverage.source_kind] : undefined;

  // C-6b populate-on-load. The store is keyed by client_id, and a client_id only exists once an
  // upload has named a source_kind — so before an upload there is deliberately NO request:
  // asking the server about a client we cannot name would be a guess, and the empty Audit view
  // is the honest state until then. A failed load surfaces on the error channel rather than
  // silently leaving the list looking complete.
  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    getDecisions(clientId)
      .then((entries) => {
        if (!cancelled) setPriorDecisions(entries);
      })
      .catch((e) => {
        if (!cancelled) setErr(serverMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  // The Audit view's rows: the store's records UNIONED with this session's, deduped on
  // entry_id — the store's own per-append identity. A decision recorded here is also IN the
  // store, so it arrives down both paths; counted twice it would put the row count at odds
  // with the chain length printed beside it. The session copy wins the collision because it
  // carries finding_id and the action verb the stored record cannot supply.
  const recordedThisSession = new Set(sessionDecisions.map((d) => d.entry_id));
  const auditDecisions = [
    ...priorDecisions.filter((e) => !recordedThisSession.has(e.entry_id)),
    ...sessionDecisions,
  ];
  // The envelope's chain_length is computed as len(entries) (api/app.py), so the loaded array's
  // own length IS that number — read off the same data, not a second guess at it.
  const priorChainLength = clientId ? priorDecisions.length : null;
  // Sign is F5-only: POST /sign/upload 422s on any other export format. Decisions and sign
  // have DIFFERENT eligibility — extract/sales get decisions, never a Sign button.
  const canSign = coverage?.source_kind === "xero_f5_upload" && uploadedFile !== null;

  const adjudication: Adjudication | undefined =
    findings.length > 0 && clientId
      ? {
          decided,
          onRecord: (id, action, note) => {
            setDecided((d) => ({ ...d, [id]: { action, note } }));
            // A fresh attempt clears the previous prompt, so a stale one cannot linger past the
            // condition that caused it.
            setNotice("");
            const row = findings.find((it) => it.finding_id === id);
            // Defensive only: un-fingerprinted rows render DISABLED controls in
            // FindingDetail (no-silent-dead-buttons), so this cannot swallow a
            // persistable decision.
            if (!row?.fingerprint) return;
            const reviewer = reviewerName.trim();
            if (!reviewer) {
              // Q1: a PROMPT, not a failure — nothing was rejected, the reviewer just has one
              // more thing to supply. Same words, its own non-error channel.
              setNotice(
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
              .then((recorded) => {
                // D-17: keep the server's own response — entry_id / entry_hash / chain_length /
                // disposition are the Audit view's only honest material.
                setSessionDecisions((ds) => [...ds, recorded]);
                // Re-apply: re-submit EXACTLY what the run submitted, so the persisted
                // demotion / annotation re-renders from the server (decisions survive
                // refresh) WITHOUT changing the input set underneath the reviewer.
                //
                // G-1: this previously passed only (uploadedFile, ledgerFile) — no
                // review_id, no documents. The backend resolves attached documents from the
                // session, so the re-applied response came back missing every
                // document-derived finding and with four coverage rows regressed to
                // `unavailable`. Recording one decision silently deleted four other findings
                // from the screen, while the signed paper — which did thread review_id —
                // still contained them.
                //
                // Re-sending the documents is not strictly required (the backend reads them
                // from reviews/<rid>/documents/ once review_id is present), but re-submitting
                // the run's own set keeps re-apply a faithful repeat of the run rather than a
                // subtly different request. The server de-duplicates by content hash, and the
                // session slice is an idempotent no-op on identical primary bytes.
                return uploadedFile
                  ? uploadExtract(
                      uploadedFile,
                      ranLedger,
                      reviewId ?? undefined,
                      ranDocuments.length > 0 ? ranDocuments : undefined,
                      ranContacts,
                    )
                  : null;
              })
              .then((resp) => {
                if (resp) setCoverage(resp);
              })
              .catch((e) => setErr(serverMessage(e)));
          },
          ...(canSign ? { onOpenSign: () => setSignOpen(true) } : {}),
        }
      : undefined;

  // D-15: the mandatory three-clause caveat renders on ALL THREE views, not just the one the
  // findings happen to be on. Its third clause says findings "should not be relied on" — a
  // warning about findings has to be visible wherever findings are, and splitting the surface
  // into views is exactly what would otherwise have stranded it on the Review tab.
  const extractCaveat = isExtractReview ? (
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
  ) : null;

  const persistNote = adjudication
    ? canSign
      ? "Decisions persist to AgentAssist's own append-only store and re-apply when this " +
        "workbook is re-submitted. Sign-off re-runs the review over the retained workbook " +
        "and emits the signed working paper — a human signs; the system never does."
      : "Decisions persist to AgentAssist's own append-only store and re-apply on " +
        "re-upload. Sign-off is available for Xero F5 exports only in this slice."
    : undefined;

  return (
    <div className="layout">
      {sidebarOpen && (
        // Shell parity: the shared Sidebar tallies the UPLOAD findings (not a SAP review).
        // Selecting a finding focuses it AND switches to the Findings view — the same
        // behaviour as App.tsx's selectFromSidebar, now that this surface has views.
        <Sidebar queue={findings} decided={decided} onSelectFinding={selectFromSidebar} />
      )}

      <div className="main-col">
        <TopBar
          // D-13 REVERSES the previous "no view-tabs on Xero" decision: this surface now has
          // the same three mutually-exclusive views as the SAP one, so view/setView are passed
          // and TopBar renders the nav (it renders it only when BOTH are supplied). The tabs
          // are live controls, not dead ones — which is what the old rule was protecting.
          // Badge text is the upload's own validation_status (unvalidated until then).
          validationStatus={coverage?.validation_status ?? "unvalidated"}
          reviewerName={reviewerName}
          view={view}
          setView={setView}
          onToggleSidebar={() => setSidebarOpen((s) => !s)}
          // Sign is F5-only and needs the retained file — the SAME `canSign` gate the in-panel
          // ReviewScreen path uses. Ungated, this pill opened SignModal after an extract/sales
          // upload (the modal's own gate checks `uploadedFile`, not source_kind) and no-oped
          // pre-upload. Both entry points must agree; neither may outrun POST /sign/upload.
          {...(canSign ? { onOpenSign: () => setSignOpen(true) } : {})}
        />

        {view === "review" && (
        <main className="view xero-upload">
          <img className="aa-logo" src="/agentassist-logo.png" alt="AgentAssist" />
          <button type="button" className="source-back" onClick={onChangeSource}>
            ← Change source
          </button>

          {/* Branch-aware scripted-mode banner: Xero copy, never the SAP "Live SAP Business One
              access" prose. The two surfaces are separate (Root gates), so each carries its own. */}
          <div className="banner" role="note">
            <div className="banner-body">
              <strong>Uploaded Xero export.</strong> The findings shown are review candidates over
              a copy of your file — for a human to adjudicate; AgentAssist never writes back to Xero.
            </div>
          </div>

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

          {/* SAP-only surfaces, present but DISABLED with an honest reason. They are STATIC
              placeholders — never the live AuditTrail/CommandBar/FacetFilter — so the Xero page
              fires no SAP fetch (§2 box-isolation) and shows no dead affordance without a cause. */}
          <section className="disabled-surfaces" aria-label="Unavailable on uploads">
            <div className="disabled-surface">
              <button type="button" disabled>Command bar</button>
              <span className="disabled-reason">
                The assistant command bar is available on the SAP review only; an uploaded export
                has no agent to command.
              </span>
            </div>
            <div className="disabled-surface">
              <button type="button" disabled>Audit trail</button>
              <span className="disabled-reason">
                The audit trail covers the SAP agent run; an uploaded export has no agent audit chain.
              </span>
            </div>
            <div className="disabled-surface">
              <button type="button" disabled>Filters</button>
              <span className="disabled-reason">
                Server-driven filters come from a SAP review run; they are not available for uploads.
              </span>
            </div>
          </section>

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
            Optional — Contacts export (supplier master, .csv)
            {/* Deliberately NOT class "xero-file-input" (the documents input at the next
                label explains why): every existing helper selects the primary input via
                `input.xero-file-input:not(.xero-ledger-input)`, and a fourth input carrying
                that class would match first and swallow their upload. */}
            <input
              className="xero-contacts-input"
              type="file"
              accept=".csv"
              onChange={onContacts}
            />
          </label>
          {contactsFile && (
            <p className="xero-contacts-attached">
              Contacts attached: <span className="mono">{contactsFile.name}</span> — the
              supplier-registration check reads the <span className="mono">TaxNumber</span>{" "}
              column. It checks only that a number is PRESENT; it does not validate it.
            </p>
          )}

          <label className="xero-file-label">
            Optional — source-document PDFs (attach before uploading)
            {/* Deliberately NOT class "xero-file-input": existing helpers select the primary
                input via `input.xero-file-input:not(.xero-ledger-input)`, and a third input
                carrying that class would match first and swallow their upload. */}
            <input
              className="xero-documents-input"
              type="file"
              accept=".pdf"
              multiple
              onChange={onDocuments}
            />
          </label>
          {documentFiles.length > 0 && (
            <p className="xero-documents-attached">
              {documentFiles.length} source document{documentFiles.length === 1 ? "" : "s"}{" "}
              attached — each is kept with this review session and shown beside the finding
              that carries its reference. Filename is the reference:{" "}
              <span className="mono">BILL-3002.pdf</span> attaches to finding{" "}
              <span className="mono">BILL-3002</span>.
            </p>
          )}

          <label className="xero-file-label">
            Upload .xlsx GST export
            <input className="xero-file-input" type="file" accept=".xlsx" onChange={onFile} />
          </label>

          {/* Slice A (A1): everything staged, named, before anything is sent. The previous
              flow ran the moment the primary input changed, which made the ledger and the
              documents order-dependent — attach them after the export and they were simply
              absent from the request, with nothing on screen to say so. */}
          <section className="staged-manifest" aria-label="Staged for this run">
            <h3>Staged for this run</h3>
            <ul>
              <li>
                <span className="staged-label">GST export</span>{" "}
                {primaryFile ? (
                  <span className="mono">{primaryFile.name}</span>
                ) : (
                  <span className="staged-none">none — required</span>
                )}
              </li>
              <li>
                <span className="staged-label">Ledger</span>{" "}
                {ledgerFile ? (
                  <>
                    <span className="mono">{ledgerFile.name}</span>{" "}
                    <button type="button" onClick={clearLedger} aria-label="Remove the staged ledger">
                      Remove
                    </button>
                  </>
                ) : (
                  <span className="staged-none">none</span>
                )}
              </li>
              <li>
                <span className="staged-label">Contacts (supplier master)</span>{" "}
                {contactsFile ? (
                  <>
                    <span className="mono">{contactsFile.name}</span>{" "}
                    <button
                      type="button"
                      onClick={clearContacts}
                      aria-label="Remove the staged contacts export"
                    >
                      Remove
                    </button>
                  </>
                ) : (
                  <span className="staged-none">none</span>
                )}
              </li>
              <li>
                <span className="staged-label">Source documents</span>{" "}
                {documentFiles.length > 0 ? (
                  <>
                    {documentFiles.length} source document{documentFiles.length === 1 ? "" : "s"}{" "}
                    <button
                      type="button"
                      onClick={clearDocuments}
                      aria-label="Remove the staged source documents"
                    >
                      Remove
                    </button>
                    <ul className="staged-documents">
                      {documentFiles.map((d) => (
                        <li key={d.name} className="mono">
                          {d.name}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <span className="staged-none">none</span>
                )}
              </li>
            </ul>
            <button
              type="button"
              className="run-review"
              onClick={runReview}
              disabled={!primaryFile || busy}
            >
              Run review
            </button>
            {stagedDirty && (
              <p className="staged-dirty" role="status">
                The staging above has changed and has <strong>not been run yet</strong>. What is
                shown below is the previous run. Press Run review to run the current staging.
              </p>
            )}
          </section>

          {busy && <div className="loading">Reading export…</div>}
          {/* C-2: house style, borrowed from App.tsx's error branch — a plain-words lead
              sentence, then the SERVER'S OWN message verbatim in a <small>. The lead says only
              what is certainly true of every 422 this endpoint raises (bad suffix, empty file,
              unreadable workbook, bad ledger, reconciliation halt): the upload did not complete.
              It never diagnoses the cause and never substitutes a friendlier summary — the real
              message is the only thing that says why. `.errorbox-upload` carries the error
              colour; the shared `.errorbox` base is left exactly as App.tsx and AuditTrail.tsx
              use it. */}
          {err && (
            <div className="errorbox errorbox-upload" role="alert">
              The upload did not complete. The server reported:
              <br />
              <small>{err}</small>
            </div>
          )}

          {extractCaveat}

          {/* The recomputed F5 boxes, on the ONE branch that carries them. Absent key ->
              nothing renders (the component's own rule): sales and extract uploads are
              one-sided and deliberately ship no boxes, and a zeroed fallback there would be
              a fabricated eight-box artefact (#48 not widened). */}
          <XeroF5Strip boxes={coverage?.recomputed_client_coded_f5_boxes} />

          {coverage && (
            <section className="xero-coverage" aria-label="Coverage preview">
              <div className="xero-coverage-head">
                Data coverage · <strong>{coverage.validation_status}</strong>
              </div>
              {/* The grouped panel replaces the raw check/level/reason table: not-examined
                  first, ids labelled, levels worded, counts computed, reasons verbatim. */}
              <XeroCoveragePanel rows={coverage.coverage_status} />
              {degraded.length > 0 && (
                <div className="xero-companion-ask callout info">
                  Some checks are limited or unavailable on a Xero export alone. To enable them,
                  provide the missing companion inputs at onboarding: a supplier-master sheet
                  (for <span className="mono">NO_GST_REG</span>) and the source-document PDFs
                  (for the invoice-face checks).
                </div>
              )}
              {coverage.out_of_scope && coverage.out_of_scope.count > 0 && (
                <div className="xero-out-of-scope callout info" aria-label="Out-of-scope lines">
                  <strong>
                    {coverage.out_of_scope.count} line
                    {coverage.out_of_scope.count === 1 ? "" : "s"} set aside (out of scope).
                  </strong>{" "}
                  {coverage.out_of_scope.reason}
                  {Object.keys(coverage.out_of_scope.by_code).length > 0 && (
                    <>
                      {" "}
                      · by code:{" "}
                      {Object.entries(coverage.out_of_scope.by_code)
                        .map(([code, n]) => `${code} (${n})`)
                        .join(", ")}
                    </>
                  )}
                </div>
              )}
              <footer className="xero-disclaimer">{coverage.disclaimer}</footer>
            </section>
          )}
        </main>
        )}

        {view === "findings" && (
          <main className="view xero-findings-view">
            {extractCaveat}
            {/* Q1: the reviewer-of-record prompt, on the view whose controls raise it. role
                ="status" not "alert" — nothing failed, so it is announced politely. It is
                deliberately NOT inside .errorbox: a prompt that reads as an error teaches the
                reviewer to distrust the error state. */}
            {notice && (
              <p className="xero-reviewer-prompt callout info" role="status">
                {notice}
              </p>
            )}
            {/* D-19: the persist note sits ABOVE the grid, not inside it. A live browser
                measurement showed it taking grid cell 1 (320px) with the queue beside it,
                which pushed the detail card onto row 2 in the 320px column while the right
                half of the page stayed empty. The grid holds exactly two children. */}
            {findings.length > 0 && persistNote && (
              <p className="xero-persist-note">{persistNote}</p>
            )}
            {findings.length > 0 ? (
              <section className="xero-findings findings-view" aria-label="Review findings">
                <ReviewScreen
                  queue={findings}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  activeTab={activeTab}
                  setActiveTab={setActiveTab}
                  adjudication={adjudication}
                  reviewOnlyNote={adjudication ? undefined : REVIEW_ONLY_NOTE}
                  // §2 source-tag guard: this is the Xero upload surface. The source identity is
                  // intrinsic to the upload response (source_kind); the shared screen refuses any
                  // non-Xero payload here (defence-in-depth behind Root's mount separation).
                  expectedSource="xero"
                  sourceKind={coverage?.source_kind}
                  // C-8: the session this upload created (D-43); DocumentViewer selects the
                  // review-scoped route with it. null -> omitted (prop is string | undefined).
                  reviewId={reviewId ?? undefined}
                />
              </section>
            ) : (
              <p className="xero-empty-view">
                No findings yet — upload a .xlsx GST export on the <strong>Review</strong> tab.
              </p>
            )}
          </main>
        )}

        {view === "audit" && (
          <main className="view xero-audit-view">
            {extractCaveat}
            <XeroAuditView decisions={auditDecisions} storedChainLength={priorChainLength} />
            {/* SAP-only surfaces, present but DISABLED with an honest reason — they belong with
                the audit story, which is where a reviewer looks for them. */}
            <section className="disabled-surfaces" aria-label="Unavailable on uploads">
              <div className="disabled-surface">
                <button type="button" disabled>Agent tool chain</button>
                <span className="disabled-reason">
                  An uploaded export runs no agent, so there is no Tier-1/Tier-2 tool chain to
                  hash-chain — only your own decisions.
                </span>
              </div>
              <div className="disabled-surface">
                <button type="button" disabled>Server-driven facets</button>
                <span className="disabled-reason">
                  The facet menu comes from a SAP review run; an upload returns no facet menu.
                </span>
              </div>
            </section>

            {/* G-3: a disabled "Source documents" tile used to sit here, asserting that a
                Xero export cannot carry source-document PDFs at all and blaming that for the
                four document checks not running. Both clauses have been false since
                C-8 / T-E(1)/(2): this very panel ships a documents input, and with documents
                attached the four checks DO run (measured 2026-09-20 — 4/4 baits fired,
                coverage `degraded`). No test pinned that sentence, which is how it outlived
                the features that falsified it; DocumentTileCopy.test.tsx now pins its absence.

                What replaces it asserts nothing of its own: it quotes the backend's per-check
                coverage `reason` VERBATIM. Per D-40 that prose is prose, not a contract — it
                is never parsed for counts here, and the count beside the heading is derived
                from the ROW ARRAY, never from the text. With no coverage yet there is nothing
                honest to say, so nothing renders. */}
            {documentCoverage.length > 0 && (
              <section className="doc-coverage" aria-label="Source-document coverage">
                <h3>Source-document checks</h3>
                <ul>
                  {documentCoverage.map((row) => (
                    <li key={row.check}>
                      <span className="doc-coverage-check">{coverageLabel(row.check)}</span>{" "}
                      <span className={`doc-coverage-level level-${row.level}`}>{row.level}</span>
                      <span className="doc-coverage-reason">{row.reason}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </main>
        )}
      </div>

      {signOpen && uploadedFile && (
        <SignModal
          onClose={() => setSignOpen(false)}
          onSigned={(name) => setReviewerName(name)}
          initialReviewer={reviewerName}
          // G-1 (same class): the sign re-runs review() server-side, so it must re-submit the
          // RUN's ledger, not whatever is staged now. reviewId was already threaded here
          // (D-45) — that is precisely why the signed paper kept the document findings the
          // re-apply had dropped from the screen.
          sign={(reviewer, firm) =>
            postSignUpload(
              uploadedFile, ranLedger, reviewer, firm, reviewId ?? undefined, ranContacts,
            )
          }
        />
      )}
    </div>
  );
}
