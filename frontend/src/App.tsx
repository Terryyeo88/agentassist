import { useEffect, useMemo, useState } from "react";
import { fetchReview, type Group, type ReviewPayload } from "./api";
import { TopBar } from "./components/TopBar";
import { CommandBar } from "./components/CommandBar";
import { Queue } from "./components/Queue";
import { FindingDetail } from "./components/FindingDetail";
import { AuditTrail } from "./components/AuditTrail";
import { SignModal } from "./components/SignModal";

const CLIENT = "sbodemosg";
const PERIOD = "2024Q3";

type Decision = { action: string; note: string };

/**
 * App — the review surface shell: TopBar → inert CommandBar → (Queue | FindingDetail) →
 * AuditTrail, with the SignModal over the top. Renders ONLY the real frozen rows the API
 * serves; decisions are held in component state until a sign (the API has no decision
 * store in this slice). All four trust signals are carried through verbatim.
 */
export function App() {
  const [review, setReview] = useState<ReviewPayload | null>(null);
  const [err, setErr] = useState<string>("");
  const [activeTab, setActiveTab] = useState<Group>("needs_review");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [decided, setDecided] = useState<Record<string, Decision>>({});
  const [signOpen, setSignOpen] = useState(false);
  const [reviewerName, setReviewerName] = useState("");

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
  }, []);

  const selected = useMemo(
    () => review?.queue.find((it) => it.finding_id === selectedId) ?? null,
    [review, selectedId]
  );

  if (err) {
    return (
      <div className="errorbox">
        Could not load the review. Is the backend running? <code>uvicorn api.app:app</code>
        <br />
        <small>{err}</small>
      </div>
    );
  }
  if (!review) return <div className="loading">Loading frozen review…</div>;

  return (
    <>
      <TopBar review={review} reviewerName={reviewerName} />
      <div className="app-shell">
        <CommandBar clientId={CLIENT} period={PERIOD} />

        <div className="f5">
          {Object.entries(review.f5_summary.boxes).map(([k, v]) => (
            <div className="box" key={k}>
              <div className="k">{k.replace(/_/g, " ")}</div>
              <div className="v">
                {review.f5_summary.currency} {v.toLocaleString()}
              </div>
            </div>
          ))}
        </div>

        <div className="work">
          <Queue
            items={review.queue}
            decided={decided}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          {selected ? (
            <FindingDetail
              item={selected}
              decision={decided[selected.finding_id]}
              onRecord={(action, note) =>
                setDecided((d) => ({ ...d, [selected.finding_id]: { action, note } }))
              }
              onOpenSign={() => setSignOpen(true)}
            />
          ) : (
            <div className="panel detail">Select a finding from the queue.</div>
          )}
        </div>

        <AuditTrail />

        <footer className="footer">
          {review.disclaimer}
          <br />
          Demo / illustrative only — frozen {review.client.company_db} engine output, not a
          real client's real numbers. The command bar classifies + runs reads over the frozen
          artifacts (scripted by default — no tokens; live opt-in). Built ≠ demo-validated ≠
          accuracy-validated.
        </footer>
      </div>

      {signOpen && (
        <SignModal
          onClose={() => setSignOpen(false)}
          onSigned={(name) => setReviewerName(name)}
        />
      )}
    </>
  );
}
