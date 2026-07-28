import type { QueueItem } from "../api";

/*
 * rowIdentity — the shared last-resort row identifier (D-18).
 *
 * Lifted verbatim out of Queue.tsx (PR #159) so the review queue and the Sidebar's "Open
 * findings" rail surface the SAME token for the same row. Behaviour is unchanged for the queue;
 * this move only gives the second surface something to call rather than reimplement.
 *
 * Both surfaces render a small fixed set of fields per row, and on the ledger-reconciliation
 * rows those fields are all identical: the live 820 path returns THREE `ledger_recon:*` rows
 * (two per-side divergences plus the Signal-B "not included" drop) whose vendor, severity,
 * doc_num, doc_date, check_id and demoted flag match exactly. Of their 24 fields only
 * finding_id, description, recommendation, display_name and error_code differ at all — and
 * between the two divergence rows, only the first three. So without this the rail and the queue
 * each show the same row two or three times and a reviewer cannot tell which they are looking at.
 *
 * The token is finding_id's terminal segment. It is NOT scraped out of description /
 * recommendation prose ("Box 6" / "Box 7"): the identifier is data, the prose is not.
 */

/**
 * The trailing segment of `finding_id`, but ONLY for a row that would otherwise render
 * identically to its siblings. Returns "" for any row that already has a vendor, severity,
 * document number or date, so ordinary rows are untouched on both surfaces.
 *
 * NOTE on the guard: `doc_num` / `doc_date` are fields the QUEUE renders; the Sidebar rail
 * renders only vendor, check_id and severity. A row carrying a doc number but no vendor and no
 * severity would therefore still read bare in the rail while this helper returns "". No such row
 * exists in the live 820 response (all three colliding rows are null on all four fields), and
 * both surfaces sharing one rule is what keeps them consistent — so the guard is deliberately
 * NOT specialised per surface. Widening it is a backend-display-field question, filed already:
 * these rows need a distinguishing display field of their own.
 */
export function rowIdentitySuffix(item: QueueItem): string {
  const distinguishable =
    item.vendor || item.severity || item.doc_num != null || item.doc_date;
  if (distinguishable) return "";
  const tail = item.finding_id.split(":").pop() ?? "";
  return tail && tail !== item.finding_id ? tail : "";
}
