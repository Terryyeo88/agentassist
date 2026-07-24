import { useState } from "react";
import type { Group, QueueItem } from "../api";
import { Queue, type FacetProps } from "./Queue";
import { FindingDetail } from "./FindingDetail";
import { DocumentViewer } from "./DocumentViewer";

/**
 * The adjudication capability the review surface needs to let a reviewer decide + sign.
 * Injected by the SAP path (client-side decisions + POST /sign over the frozen artifacts).
 * OMITTED by the Xero upload path — there is no server-side store to sign an uploaded review
 * against — so the screen falls back to a review-only surface (no dead controls).
 */
export interface Adjudication {
  decided: Record<string, { action: string; note: string }>;
  onRecord: (findingId: string, action: string, note: string) => void;
  /** Sign capability, gated separately (B3a-2): the SAP path always passes it; the upload
   *  panel passes it only for Xero F5 (POST /sign/upload serves no other source_kind).
   *  Omitted → decisions render without a Sign button — no dead control. */
  onOpenSign?: () => void;
}

interface Props {
  queue: QueueItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  activeTab: Group;
  setActiveTab: (g: Group) => void;
  /** SERVER-driven facet menu (SAP path only). Omitted → no facet block. */
  facets?: FacetProps;
  /** Injected decision + sign capability. Omitted → review-only. */
  adjudication?: Adjudication;
  /** Shown in the detail card when `adjudication` is omitted (review-only paths). */
  reviewOnlyNote?: string;
}

/**
 * ReviewScreen — the SHARED central review surface (BUILD 2, A1). The Queue + FindingDetail
 * pair, extracted so BOTH the SAP path (App, with facets + the sign capability) and the Xero
 * upload path (review-only) render the SAME candidate-adjudication UI over the SAME QueueItem
 * shape. Behaviour-preserving: with `adjudication` injected it is byte-for-byte the prior SAP
 * findings view; without it, findings still render as candidates but the decision/sign
 * controls are replaced by an honest review-only note. Box-isolation is unaffected — this
 * screen only renders a queue; it never computes an F5 box.
 */
export function ReviewScreen({
  queue,
  selectedId,
  onSelect,
  activeTab,
  setActiveTab,
  facets,
  adjudication,
  reviewOnlyNote,
}: Props) {
  const selected = queue.find((it) => it.finding_id === selectedId) ?? null;

  // C1 source-document viewer: opened by the FindingDetail trigger, rendered as a THIRD pane
  // BESIDE the detail (a flex column inside the grid's detail cell) — never a full-page
  // takeover, and the queue stays visible in its own grid column. Reset when the finding
  // changes so the viewer never shows a stale doc for a different finding.
  const [openDoc, setOpenDoc] = useState<number | null>(null);

  return (
    <>
      <Queue
        items={queue}
        decided={adjudication?.decided ?? {}}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        selectedId={selectedId}
        onSelect={onSelect}
        facets={facets}
      />
      <div className="detail-col">
        {selected ? (
          <FindingDetail
            item={selected}
            decision={adjudication?.decided[selected.finding_id]}
            onRecord={
              adjudication
                ? (action, note) => adjudication.onRecord(selected.finding_id, action, note)
                : undefined
            }
            onOpenSign={adjudication?.onOpenSign}
            reviewOnlyNote={reviewOnlyNote}
            onViewDocument={setOpenDoc}
          />
        ) : (
          <div className="panel detail">Select a finding from the queue.</div>
        )}
        {openDoc != null && (
          <DocumentViewer docNum={openDoc} onClose={() => setOpenDoc(null)} />
        )}
      </div>
    </>
  );
}
