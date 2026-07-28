/**
 * f5.ts — the IRAS F5 box labels, shared by BOTH box tables.
 *
 * `boxNumber` / `boxDescription` derive a reviewer-facing label from a box KEY
 * ("box_8_net_gst" → "Box 8" / "Net gst"). They were previously private to App.tsx; the Xero
 * strip needs the same labels, and one source beats two — these are IRAS's own box numbers,
 * so a second hand-written copy could only drift away from the first (D-12).
 *
 * SHARED LABELS, DISTINCT TREATMENT. Only the labels are common. The SAP table renders figures
 * computed from the books; the Xero table renders the client's own classification with
 * AgentAssist's arithmetic applied — which is why its `basis` is stamped server-side. The two
 * tables must not look alike, so nothing about presentation is shared here.
 */

/** "box_8_net_gst" → "Box 8"; an unrecognised key falls back to itself, never to a guess. */
export function boxNumber(key: string): string {
  const m = key.match(/box_(\d+)/i);
  return m ? `Box ${m[1]}` : key;
}

/** "box_8_net_gst" → "Net gst". */
export function boxDescription(key: string): string {
  const rest = key.replace(/^box_\d+_/i, "").replace(/_/g, " ");
  return rest.charAt(0).toUpperCase() + rest.slice(1);
}
