import type { Source } from "../Root";

/**
 * SourceSelector — the empty-state chooser shown before any feeder is bound. Two explicit
 * choices, no default: "SAP B1 (demo)" (the frozen oracle review) or "Xero export (upload)"
 * (a coverage-only preview over an uploaded client export). Nothing is fetched until a choice
 * is made — this is what replaces the old auto-bind-to-B1-on-mount behaviour.
 */
export function SourceSelector({ onPick }: { onPick: (source: Source) => void }) {
  return (
    <div className="source-selector">
      <img className="aa-logo" src="/agentassist-logo.png" alt="AgentAssist" />
      <h1 className="source-title">Choose an input source</h1>
      <p className="source-sub">
        No source is bound yet — pick where this review reads from. Nothing runs until you choose.
      </p>
      <div className="source-cards">
        <button type="button" className="source-card" onClick={() => onPick("b1_demo")}>
          <span className="source-card-title">SAP B1 (demo)</span>
          <span className="source-card-desc">
            The frozen SBODEMOSG engine output (2024Q3). Illustrative demo —
            validation_status&nbsp;unvalidated.
          </span>
        </button>
        <button type="button" className="source-card" onClick={() => onPick("xero_upload")}>
          <span className="source-card-title">Xero export (upload)</span>
          {/* C-3: the previous line said "Coverage only — the engine is not run", which is FALSE
              — a committed F5 + 820 upload returns six findings. Wording is adapted from the
              panel's own already-shipped sentence (XeroUploadPanel's "A real IRAS-F5 export is
              reviewed and its findings are shown below as candidates — unvalidated, for a human
              to adjudicate") rather than invented here, so the chooser and the surface the
              reviewer lands on say the same thing. */}
          <span className="source-card-desc">
            Upload a client .xlsx GST export. A real IRAS-F5 export is reviewed and its findings
            are surfaced as candidates — unvalidated, for a human to adjudicate — alongside a
            data-coverage preview.
          </span>
        </button>
      </div>
    </div>
  );
}
