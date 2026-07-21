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

// POST /decision (t-decision-persistence). Mirrors api/app.py DECISION_KEYS — a recorded
// human adjudication over a finding fingerprint, persisted to AgentAssist's OWN
// append-only store (never a write to client data, never a verdict).
export interface DecisionRequest {
  client_id: string;
  finding_id: string;
  fingerprint: string;
  action: string;
  note?: string;
  reviewer_name: string;
  period?: string;
}

export interface DecisionResponse {
  client_id: string;
  finding_id: string;
  action: string;
  disposition: string;
  fingerprint: string;
  entry_id: string;
  entry_hash: string;
  chain_length: number;
  validation_status: string;
  disclaimer: string;
}

/*
 * Source-selector Xero branch. Two honest response shapes from POST /review/upload, keyed by
 * `source_kind` (mirrors api/app.py's UPLOAD_COVERAGE_KEYS / XERO_UPLOAD_KEYS / COVERAGE_ROW_KEYS,
 * the single source of truth):
 *   - "extract_upload"  → COVERAGE-ONLY (no `queue`); the engine is not run.
 *   - "xero_f5_upload"  → the engine IS run; `queue` carries the real (but UNVALIDATED)
 *                          findings projected into the SHARED central-screen QueueItem shape
 *                          (BUILD 2, A1). Coverage is data-presence; findings are candidates,
 *                          never a validated review or a compliance verdict.
 */
export interface CoverageStatusRow {
  check: string;
  level: string; // "full" | "degraded" | "unavailable"
  reason: string;
}

export interface UploadCoverageResponse {
  source_kind: string;
  validation_status: string;
  disclaimer: string;
  coverage_status: CoverageStatusRow[];
  // Present on the engine branches ("xero_f5_upload" and "extract_review") — the shared queue.
  queue?: QueueItem[];
  // Present only on the general-extract engine branch ("extract_review", BUILD 3): the marker
  // that the run used a DEFAULT DEMO config (not the uploader's). Drives the LOUD default-config
  // caveat. Value: "default_demo".
  config_scope?: string;
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

// Persist one reviewer adjudication (t-decision-persistence). Mirrors the postSign
// pattern: JSON POST, throws the server's `detail` on non-2xx — a failed persist is
// surfaced, never a silent success.
export async function postDecision(req: DecisionRequest): Promise<DecisionResponse> {
  const resp = await fetch(`${BASE}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || `Decision failed: ${resp.status}`);
  }
  return (await resp.json()) as DecisionResponse;
}

/*
 * Faceted-filter types (T6.3). The RUN_REVIEW execution `data` carries a data-derived
 * filter menu + a VIEW over the findings; the SERVER does the filtering (agent/facets.py
 * via agent/dispatch_exec.py:_findings_view) — these types only describe what it returns.
 *
 * A facet map is `{facet_name: {value: count}}`. JSON object keys are always strings, so a
 * numeric facet (doc_num) arrives keyed by string (e.g. {"958": 1}); counts stay numbers.
 */
export type FacetMap = Record<string, Record<string, number>>;

/** filter_rejection — the ⊆-menu twin of NeedsClarification (dispatch_exec.py:84-86). */
export type FilterRejection =
  | {
      reason: "not_in_domain";
      facet: string;
      value: string | number;
      domain: (string | number)[];
      requested_filters: Record<string, string | string[]>;
      message: string;
    }
  | {
      reason: "unknown_facet";
      requested_filters: Record<string, string | string[]>;
      available_facets: string[];
      message: string;
    }
  | {
      reason: "unsupported_intent";
      requested_filters: Record<string, string | string[]>;
      message: string;
    };

/**
 * A canonical finding (raw dossier) as RUN_REVIEW returns it in `dossiers`/`findings`.
 * NOT the rich GET /review QueueItem — only the fields the dossier reliably carries.
 */
export interface FindingRow {
  finding_id: string;
  check_id: string;
  finding_type: string;
  candidate_framing_text?: string;
  [k: string]: unknown;
}

/** RUN_REVIEW's execution.data shape (agent/dispatch_exec.py:395-404). */
export interface RunReviewData {
  review_result?: Record<string, unknown>;
  dossiers: FindingRow[];
  f5_summary: F5Summary;
  available_facets: FacetMap;
  findings: FindingRow[];
  remaining_facets: FacetMap;
  applied_filters: Record<string, string | string[]>;
  filter_rejection: FilterRejection | null;
}

/*
 * POST /command (T6.2). Mirrors api/app.py's response-shape contracts
 * (COMMAND_*_KEYS / EXECUTION_KEYS) — keep these in lockstep with that single source.
 * ExecutionResult.data varies by intent; it is left open (Record) and rendered defensively.
 */
export interface ExecutionResult {
  intent: string;
  outcome: string;
  sequence: string[];
  tiers: number[];
  params: Record<string, string>;
  data: Record<string, unknown>;
  notes: string[];
}

export type CommandResponse =
  | {
      kind: "result";
      classifier_mode: string;
      disclaimer: string;
      intent: string;
      execution: ExecutionResult;
    }
  | {
      kind: "out_of_scope";
      classifier_mode: string;
      disclaimer: string;
      message: string;
      buttons: string[];
    }
  | {
      kind: "needs_clarification";
      classifier_mode: string;
      disclaimer: string;
      intent: string;
      missing: string[];
      message: string;
    };

/**
 * uploadExtract — POST a client .xlsx GST export to the source-selector Xero upload route.
 * Multipart upload: the required primary `file` + an OPTIONAL `ledger` (the Xero 820
 * account-transactions export). The multipart filename drives the server's `.xlsx` gate.
 * The server FORMAT-ROUTES:
 * a real Xero IRAS-F5 export runs the engine and returns `queue` (real, UNVALIDATED findings
 * in the shared central-screen shape); any other .xlsx stays coverage-only (no `queue`).
 * Never hits GET /review or POST /command — it never touches the frozen B1 review (box-isolation).
 */
export async function uploadExtract(
  file: File,
  ledger?: File | null,
): Promise<UploadCoverageResponse> {
  // Multipart: the required primary `file` + an OPTIONAL `ledger` (the Xero 820
  // account-transactions export). The server runs the ledger↔declared-return
  // reconciliation only when a ledger is attached AND the primary is a Xero F5 export.
  const form = new FormData();
  form.append("file", file);
  if (ledger) form.append("ledger", ledger);
  const resp = await fetch(`${BASE}/review/upload`, {
    method: "POST",
    body: form,
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || `Upload failed: ${resp.status}`);
  }
  return (await resp.json()) as UploadCoverageResponse;
}

export async function postCommand(
  utterance: string,
  client_id: string,
  period: string,
  filters?: Record<string, string | string[]>
): Promise<CommandResponse> {
  const resp = await fetch(`${BASE}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // `filters` is a VIEW parameter (T6.3 Slice 3a/3b): never identity, never sent
    // unless present. Domain validation stays the engine's job — we only narrow a view.
    body: JSON.stringify(filters ? { utterance, client_id, period, filters } : { utterance, client_id, period }),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || `Command failed: ${resp.status}`);
  }
  return (await resp.json()) as CommandResponse;
}
