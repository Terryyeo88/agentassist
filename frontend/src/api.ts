/*
 * api.ts — typed client + TS types mirroring the FastAPI contract.
 *
 * The types here are the front-end half of the single-source-of-truth key set defined in
 * api/viewmodel.py (REVIEW_KEYS / QUEUE_ITEM_KEYS / AUDIT_ROW_KEYS / SIGN_KEYS). The
 * pytest contract test pins the backend to those keys; keep these interfaces in lockstep.
 *
 * Only REAL frozen check types appear (E1 / E2 / NO_GST_REG / gst_amount_mismatch). The
 * mock's aspirational DUP_CLAIM / SEQ_GAP / FLUX are not in the engine and never arrive.
 */

export type Group = "needs_review" | "marked_known" | "decided";

export interface Completeness {
  required: string[];
  present: string[];
  missing: string[];
  satisfied: boolean;
}

export interface QueueItem {
  finding_id: string;
  check_id: string;
  finding_type: string;
  group: Group;
  vendor: string | null;
  severity: string | null;
  description: string | null;
  recommendation: string | null;
  doc_num: number | null;
  doc_date: string | null;
  error_code: string | null;
  display_name: string | null;
  iras_basis: string | null;
  iras_basis_caveat: string;
  demoted: boolean;
  annotation: string | null;
  prior_dispositions: string[];
  fingerprint: string | null;
  candidate_framing_text: string;
  completeness: Completeness;
  inputs_hash: string;
  proposal_id: string | null;
  proposal_status: string | null;
  validation_status: string;
}

export interface F5Summary {
  currency: string;
  boxes: Record<string, number>;
}

export interface ReviewPayload {
  client: { client_id: string; client_name: string; company_db: string };
  period: { start: string; end: string; label: string };
  validation_status: string;
  f5_summary: F5Summary;
  queue: QueueItem[];
  disclaimer: string;
}

export interface AuditRow {
  seq: number;
  tier: number;
  tier_label: string;
  tool_name: string;
  outcome: string;
  justification: string;
  blocked_reason: string;
  timestamp: string;
  entry_hash: string;
}

export interface SignResponse {
  reviewer_name: string;
  firm_name: string;
  working_paper_path: string;
  f5_summary: F5Summary;
  validation_status: string;
  disclaimer: string;
}

// Same-origin in dev: Vite proxies `/api/*` → the uvicorn backend (see vite.config.ts).
const BASE = "/api";

async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`);
  if (!resp.ok) {
    throw new Error(`GET ${path} failed: ${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as T;
}

export function fetchReview(client: string, period: string): Promise<ReviewPayload> {
  return getJSON<ReviewPayload>(`/review/${client}/${period}`);
}

export async function fetchAudit(): Promise<AuditRow[]> {
  const body = await getJSON<{ entries: AuditRow[] }>("/audit");
  return body.entries;
}

export async function postSign(reviewer_name: string, firm_name: string): Promise<SignResponse> {
  const resp = await fetch(`${BASE}/sign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewer_name, firm_name }),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || `Sign failed: ${resp.status}`);
  }
  return (await resp.json()) as SignResponse;
}
