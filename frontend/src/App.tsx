import { useEffect, useState } from "react";
import { fetchReview, postCommand, postDecision, type CommandResponse, type Group, type ReviewPayload } from "./api";
import { TopBar, type View } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { CommandBar } from "./components/CommandBar";
import { ReviewScreen } from "./components/ReviewScreen";
import { AuditTrail } from "./components/AuditTrail";
import { SignModal } from "./components/SignModal";
import { RUN_REVIEW_UTTERANCE, asRunReviewData, normalizeFilters, toggleFilter } from "./lib/runReview";
// The F5 box labels moved to lib/f5 so the Xero strip renders the SAME IRAS box numbers from
// ONE source (D-12). Only the labels are shared — the two tables' treatments stay distinct.
import { boxDescription, boxNumber } from "./lib/f5";

const CLIENT = "sbodemosg";
const PERIOD = "2024Q3";

type Decision = { action: string; note: string };

/**
 * App — the dark AgentAssist review surface (T6.3 Slice 4). A collapsible sidebar + a header
 * with three mutually-exclusive views (Review · Findings · Audit). The Review home carries the
 * scripted-mode banner (mode + disclaimer read from the SERVER, never hardcoded), the command
 * composer + result card, and the F5 returns table. The Findings view carries the queue with
 * the SERVER-driven facet menu (a RUN_REVIEW POST /command fired here, re-POSTed on each toggle)
 * and the per-finding detail. All trust signals carry through verbatim; F5 boxes are
 * box-isolated — filtering the queue never recomputes a box value.
 */
export function App() {
  const [review, setReview] = useState<ReviewPayload | null>(null);
  const [err, setErr] = useState<string>("");
  const [view, setView] = useState<View>("review");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [bannerOpen, setBannerOpen] = useState(true);
  const [activeTab, setActiveTab] = useState<Group>("needs_review");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [decided, setDecided] = useState<Record<string, Decision>>({});
  const [signOpen, setSignOpen] = useState(false);
  const [reviewerName, setReviewerName] = useState("");
  // The RUN_REVIEW response — source of the banner's classifier_mode/disclaimer AND the
  // server-driven queue facet menu. Re-POSTed (with `filters`) on each facet toggle.
  const [reviewRun, setReviewRun] = useState<CommandResponse | null>(null);
  const [facetBusy, setFacetBusy] = useState(false);

  function runReview(filters?: Record<string, string[]>) {
    setFacetBusy(true);
    postCommand(RUN_REVIEW_UTTERANCE, CLIENT, PERIOD, filters)
      .then(setReviewRun)
      .catch((e) => setErr(String(e)))
      .finally(() => setFacetBusy(false));
  }

  useEffect(() => {
    fetchReview(CLIENT, PERIOD)
      .then((r) => {
        setReview(r);
        if (r.queue.length) {
          const firstNeeds = r.queue.find((it) => !it.demoted) ?? r.queue[0];
          setSelectedId(firstNeeds.finding_id);
        }
      })
      .catch((e) => setErr(String(e)));
    // Server facets + banner mode come from a RUN_REVIEW over the frozen artifacts (no tokens).
    runReview(undefined);
  }, []);

  const runData = asRunReviewData(reviewRun);
  const selectedFilters = runData ? normalizeFilters(runData.applied_filters) : {};
  const filterActive = Object.values(selectedFilters).some((vs) => vs.length > 0);

  const facetProps = runData
    ? {
        available: runData.available_facets,
        remaining: runData.remaining_facets,
        selected: selectedFilters,
        onToggle: (facet: string, value: string) =>
          runReview(toggleFilter(selectedFilters, facet, value)),
        onClear: () => runReview({}),
        busy: facetBusy,
        shown: runData.findings.length,
        total: runData.dossiers.length,
        visibleIds: filterActive
          ? new Set(runData.findings.map((f) => f.finding_id))
          : null,
      }
    : undefined;

  if (err && !review) {
    return (
      <div className="errorbox">
        Could not load the review. Is the backend running? <code>uvicorn api.app:app</code>
        <br />
        <small>{err}</small>
      </div>
    );
  }
  if (!review) return <div className="loading">Loading frozen review…</div>;

  const bannerMode = reviewRun?.classifier_mode;
  const bannerDisclaimer = reviewRun?.disclaimer;

  function selectFromSidebar(id: string) {
    setSelectedId(id);
    setView("findings");
  }

  return (
    <div className="layout">
      {sidebarOpen && (
        <Sidebar queue={review.queue} decided={decided} onSelectFinding={selectFromSidebar} />
      )}

      <div className="main-col">
        <TopBar
          validationStatus={review.validation_status}
          reviewerName={reviewerName}
          view={view}
          setView={setView}
          onToggleSidebar={() => setSidebarOpen((s) => !s)}
          onOpenSign={() => setSignOpen(true)}
        />

        {view === "review" && (
          <main className="view review-home">
            <img className="aa-logo" src="/agentassist-logo.png" alt="AgentAssist" />

            {bannerOpen && (
              <div className="banner" role="note">
                <div className="banner-body">
                  {bannerMode && <strong>{bannerMode} mode.</strong>} Live SAP Business One access
                  is opt-in — no tokens are used in this session.{" "}
                  <a className="learn" href="#learn">
                    Learn more
                  </a>
                  {bannerDisclaimer && <span className="banner-disc">{bannerDisclaimer}</span>}
                </div>
                <button className="banner-x" aria-label="Dismiss banner" onClick={() => setBannerOpen(false)}>
                  ×
                </button>
              </div>
            )}

            {/* t-xero-signoff (M3): reviewer identity is captured ONCE, up front, and
                attributes BOTH persisted decisions and the signature — the old
                web-demo-reviewer placeholder constant is retired (closes open item #2).
                Empty → decisions record locally only (never a placeholder attribution). */}
            <div className="reviewer-identity" role="group" aria-label="Reviewer of record">
              <label htmlFor="reviewer-of-record">Reviewer of record</label>
              <input
                id="reviewer-of-record"
                aria-label="Reviewer of record"
                placeholder="Your name — attributed to decisions and the signed paper"
                value={reviewerName}
                onChange={(e) => setReviewerName(e.target.value)}
              />
            </div>

            <CommandBar
              clientId={CLIENT}
              period={PERIOD}
              onOpenQueue={() => setView("findings")}
              onOpenAudit={() => setView("audit")}
              onOpenSign={() => setSignOpen(true)}
            />

            {/* Defensive empty-state guard: the F5 strip dereferences review.f5_summary.boxes /
                .currency. A payload without an f5_summary (e.g. an upload-shaped body reaching
                this shell) would throw; render the strip only when boxes are present so the
                Review home degrades to no-strip rather than crashing. */}
            {review.f5_summary?.boxes && (
            <section className="f5-strip" aria-label="F5 summary">
              <div className="f5-strip-head">
                <span className="f5-dot" aria-hidden="true" />
                {review.client.company_db} · GST F5 return · {review.period.label} ▾
              </div>
              <table className="f5-table">
                <thead>
                  <tr>
                    <th>Box</th>
                    <th>Description</th>
                    <th className="num">Amount ({review.f5_summary.currency})</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(review.f5_summary.boxes).map(([k, v]) => {
                    const isNet = /net/i.test(k);
                    return (
                      <tr key={k} className={isNet ? "f5-net" : ""}>
                        <td className="mono">{boxNumber(k)}</td>
                        <td>{boxDescription(k)}</td>
                        <td className={`mono num f5-amt${isNet ? " net" : ""}`}>
                          <span className="f5-cur">{review.f5_summary.currency}</span>{" "}
                          <span className="f5-val">{v.toLocaleString()}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
            )}
          </main>
        )}

        {view === "findings" && (
          <main className="view findings-view">
            <ReviewScreen
              queue={review.queue}
              selectedId={selectedId}
              onSelect={setSelectedId}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              facets={facetProps}
              // §2 source-tag guard: this is the SAP (b1_demo) surface. ReviewPayload carries NO
              // source_kind key, so App declares BOTH sides here — which means this particular
              // pairing is tautological and can never trip. It is a declaration of intent, not an
              // observation: the tag is asserted by the mount, not read off the payload. The
              // guard does real work only where the tag is payload-derived (the Xero mount, which
              // passes the response's own source_kind). Mount separation in Root remains the
              // actual structural guarantee on this surface. To make this observed rather than
              // declared, ReviewPayload would need a source_kind key — a key-set change, Terry-only.
              expectedSource="sap"
              sourceKind="b1_demo"
              adjudication={{
                decided,
                // t-decision-persistence: a decision PERSISTS via POST /decision (append-only
                // server store), then the review is re-fetched so the persisted demotion /
                // annotation re-renders from the server — decisions survive refresh. The
                // local `decided` map still drives immediate button state; a failed POST
                // surfaces in the error banner.
                // t-xero-signoff (M3): the decision is attributed to the reviewer of record
                // the user entered — never a placeholder. No name entered → local-only
                // record with a visible hint (persistence needs a real attributable name).
                onRecord: (id, action, note) => {
                  setDecided((d) => ({ ...d, [id]: { action, note } }));
                  const row = review.queue.find((it) => it.finding_id === id);
                  // B3a-2: un-fingerprinted rows (here: the probabilistic finding — no
                  // deterministic fingerprint) render DISABLED controls in the shared
                  // FindingDetail (no-silent-dead-buttons), so this guard is defensive
                  // only — it can no longer swallow a reviewer's decision silently.
                  if (!row?.fingerprint) return;
                  const reviewer = reviewerName.trim();
                  if (!reviewer) {
                    setErr(
                      "Decision recorded locally only — enter the reviewer of record " +
                        "(Review tab) to persist decisions under a real name."
                    );
                    return;
                  }
                  postDecision({
                    client_id: CLIENT,
                    finding_id: id,
                    fingerprint: row.fingerprint,
                    action,
                    note,
                    reviewer_name: reviewer,
                    period: PERIOD,
                  })
                    .then(() => fetchReview(CLIENT, PERIOD))
                    .then(setReview)
                    .catch((e) => setErr(String(e)));
                },
                onOpenSign: () => setSignOpen(true),
              }}
            />
          </main>
        )}

        {view === "audit" && (
          <main className="view audit-view">
            <AuditTrail />
            <footer className="footer">
              {review.disclaimer}
              <br />
              Demo / illustrative only — frozen {review.client.company_db} engine output, not a
              real client's real numbers. The command bar classifies + runs reads over the frozen
              artifacts (scripted by default — no tokens; live opt-in). Built ≠ demo-validated ≠
              accuracy-validated.
            </footer>
          </main>
        )}
      </div>

      {signOpen && (
        <SignModal
          onClose={() => setSignOpen(false)}
          onSigned={(name) => setReviewerName(name)}
          initialReviewer={reviewerName}
        />
      )}
    </div>
  );
}
