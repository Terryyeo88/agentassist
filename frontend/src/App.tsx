import { useEffect, useState } from "react";
import { fetchReview, postCommand, postDecision, type CommandResponse, type Group, type ReviewPayload } from "./api";
import { TopBar, type View } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { CommandBar } from "./components/CommandBar";
import { ReviewScreen } from "./components/ReviewScreen";
import { AuditTrail } from "./components/AuditTrail";
import { SignModal } from "./components/SignModal";
import { RUN_REVIEW_UTTERANCE, asRunReviewData, normalizeFilters, toggleFilter } from "./lib/runReview";

const CLIENT = "sbodemosg";
const PERIOD = "2024Q3";

// Reviewer of record sent with each persisted decision. The demo surface collects a
// reviewer name only at SIGN time; capturing identity at decision time is a filed
// open item (t-decision-persistence) — until then decisions are attributed to the
// demo surface, honestly labelled.
const WEB_REVIEWER = "web-demo-reviewer";

type Decision = { action: string; note: string };

// Humanise an F5 box key for the returns table: "box_8_net_gst" → "Box 8" + "Net gst".
function boxNumber(key: string): string {
  const m = key.match(/box_(\d+)/i);
  return m ? `Box ${m[1]}` : key;
}
function boxDescription(key: string): string {
  const rest = key.replace(/^box_\d+_/i, "").replace(/_/g, " ");
  return rest.charAt(0).toUpperCase() + rest.slice(1);
}

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
        <Sidebar review={review} decided={decided} onSelectFinding={selectFromSidebar} />
      )}

      <div className="main-col">
        <TopBar
          review={review}
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

            <CommandBar
              clientId={CLIENT}
              period={PERIOD}
              onOpenQueue={() => setView("findings")}
              onOpenAudit={() => setView("audit")}
              onOpenSign={() => setSignOpen(true)}
            />

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
              adjudication={{
                decided,
                // t-decision-persistence: a decision PERSISTS via POST /decision (append-only
                // server store), then the review is re-fetched so the persisted demotion /
                // annotation re-renders from the server — decisions survive refresh. The
                // local `decided` map still drives immediate button state. A row without a
                // fingerprint (probabilistic/unjoinable) records locally only — nothing to
                // key persistence on; a failed POST surfaces in the error banner.
                onRecord: (id, action, note) => {
                  setDecided((d) => ({ ...d, [id]: { action, note } }));
                  const row = review.queue.find((it) => it.finding_id === id);
                  if (!row?.fingerprint) return;
                  postDecision({
                    client_id: CLIENT,
                    finding_id: id,
                    fingerprint: row.fingerprint,
                    action,
                    note,
                    reviewer_name: WEB_REVIEWER,
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
        <SignModal onClose={() => setSignOpen(false)} onSigned={(name) => setReviewerName(name)} />
      )}
    </div>
  );
}
