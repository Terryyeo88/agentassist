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
  // Xero findings carry a non-numeric DocNum (e.g. "BILL-3003"); the SAP path sends an int.
  // Widened to match reality — no contract/key change, the backend returns whatever the
  // source provides. NOTE (D-34): GET /document/{doc_ref} resolves the SAP corpus ONLY and
  // REFUSES a Xero reference — it 404s rather than substituting a digit-colliding document.
  // Uploaded documents are served by GET /review/{review_id}/document/{doc_ref} (D-42).
  doc_num: number | string | null;
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
  // C-6(a): who adjudicated, and WHEN — both read off the appended ledger record by the
  // endpoint, never derived client-side. `timestamp` is the store's own ISO-8601 append-time
  // stamp and `reviewer` the recorded reviewer; both are hashed into the append-only chain.
  // A surface renders these verbatim — a browser clock would be a guess, not the record.
  reviewer: string;
  timestamp: string;
  chain_length: number;
  validation_status: string;
  disclaimer: string;
}

/*
 * GET /decisions/{client_id} (C-6b) — the READ half of the decision store. Mirrors
 * DECISIONS_READ_KEYS in api/app.py and, for the rows, dataclasses.asdict(AdjudicationEntry)
 * in agent/decision_ledger.py.
 *
 * A stored entry is NOT a DecisionResponse. It carries what the LEDGER records; the write
 * response additionally echoes what the CALLER supplied. Two differences matter to any
 * surface rendering these:
 *   - no `finding_id` — the record is keyed on the deterministic fingerprint alone, so a
 *     prior-decision row cannot name the finding. Render the absence, never infer it.
 *   - no `action` — the UI verb rides inside `reason` as "[Mark known] <note>" (api/app.py
 *     writes it there so the two KNOWN_ACCEPTED-mapped verbs stay distinguishable forever).
 */
export interface DecisionEntry {
  entry_id: string;
  fingerprint: string;
  disposition: string;
  reviewer: string;
  reason: string | null;
  period: string | null;
  timestamp: string;
  prev_hash: string;
  entry_hash: string;
  fingerprint_version: string | null;
}

export interface DecisionsEnvelope {
  client_id: string;
  entries: DecisionEntry[];
  chain_length: number;
  validation_status: string;
  disclaimer: string;
}

/*
 * Source-selector Xero branch. Honest response shapes from POST /review/upload, keyed by
 * `source_kind`. The contract authority is the exact-set key pins in the backend tests
 * (tests/test_upload_keys_binding.py binds each branch's live response to its api/app.py
 * constant; the per-branch upload tests pin the same sets) — NOT the api/app.py constants
 * alone, which are documentation the binding test keeps honest:
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

// Present only on the Xero sales-invoice branch ("xero_sales_upload"): lines carrying an
// accepted-but-set-aside TaxType (e.g. "No Tax") held OUT OF SCOPE. Shape mirrors the backend
// OUT_OF_SCOPE_KEYS (api/app.py). Reading it is frontend-only — the backend already returns it.
export interface OutOfScope {
  count: number;
  by_code: Record<string, number>;
  reason: string;
}

// The Xero-F5 box object (backend shape: api/viewmodel.py build_recomputed_client_coded_f5_boxes,
// emitted since PR #151 at api/app.py's xero_f5_upload branch). Deliberately NOT named or shaped
// like f5_summary — failing-to-render is the honest failure (R2). `currency` is optional because
// the builder OMITS the key entirely when the export doesn't uniformly state one — it is never
// defaulted to "SGD" (viewmodel.py: omit-never-default).
export interface RecomputedF5Boxes {
  boxes: Record<string, number>;
  basis: string;
  period: { start: string | null; end: string | null };
  source_file: { filename: string; sha256: string };
  currency?: string;
}

export interface UploadCoverageResponse {
  source_kind: string;
  validation_status: string;
  disclaimer: string;
  coverage_status: CoverageStatusRow[];
  // Present on the three engine branches ("xero_f5_upload", "xero_sales_upload",
  // "extract_review") — the shared queue.
  queue?: QueueItem[];
  // Present ONLY on the "xero_f5_upload" branch — sales and extract are one-sided and
  // deliberately carry no boxes (#48 not widened).
  recomputed_client_coded_f5_boxes?: RecomputedF5Boxes;
  // Present only on the general-extract engine branch ("extract_review", BUILD 3): the marker
  // that the run used a DEFAULT DEMO config (not the uploader's). Drives the LOUD default-config
  // caveat. Value: "default_demo".
  config_scope?: string;
  // Present only on the Xero sales-invoice branch: the visible out-of-scope-lines note.
  out_of_scope?: OutOfScope;
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

// POST /sign/upload (B4; wired to the panel in B3a-2). Xero F5 ONLY — the endpoint 422s
// on any other export format, so the panel gates the Sign affordance on
// source_kind === "xero_f5_upload". Mirrors api/app.py SIGN_UPLOAD_KEYS.
export interface SignUploadResponse {
  source_kind: string;
  reviewer_name: string;
  firm_name: string;
  working_paper_path: string;
  bundle_dir: string;
  validation_status: string;
  disclaimer: string;
}

/**
 * postSignUpload — re-POST the RETAINED workbook (+ optional ledger) with the reviewer's
 * identity to /sign/upload. Stateless on the server: review() re-runs over the workbook and
 * its OWN full-arg render emits the signed working paper. The system never signs — the
 * paper carries the reviewer's identity above an empty ruled line.
 */
export async function postSignUpload(
  file: File,
  ledger: File | null | undefined,
  reviewer_name: string,
  firm_name: string,
  reviewId?: string,
  contacts?: File | null,
): Promise<SignUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  if (ledger) form.append("ledger", ledger);
  // Slice C: the supplier master the review ran with. Without it the sign re-runs
  // review() WITHOUT the Contacts export and the signed paper silently drops every
  // supplier-registration finding the reviewer just adjudicated on screen.
  if (contacts) form.append("contacts", contacts);
  form.append("reviewer_name", reviewer_name);
  form.append("firm_name", firm_name);
  // D-45: the sign path re-runs review() over the re-posted workbook. Without the
  // review_id it cannot reach reviews/<rid>/documents/, so the four document checks
  // are skipped and the SIGNED PAPER OMITS FINDINGS THE SCREEN SHOWED. A paper that
  // omits what the reviewer adjudicated is the failure this architecture exists to
  // prevent.
  if (reviewId) form.append("review_id", reviewId);
  const resp = await fetch(`${BASE}/sign/upload`, { method: "POST", body: form });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || `Sign failed: ${resp.status}`);
  }
  return (await resp.json()) as SignUploadResponse;
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

/**
 * Every decision recorded for `client_id`, oldest first (C-6b). Mirrors fetchAudit: envelope
 * in, `.entries` out. An empty store is a 200 with `entries: []` — the absence of decisions
 * is a fact, so it needs no special-casing here.
 */
export async function getDecisions(client_id: string): Promise<DecisionEntry[]> {
  const body = await getJSON<DecisionsEnvelope>(`/decisions/${client_id}`);
  // A body without an `entries` array is a broken response, not an empty store. Coercing it
  // to [] would render "no decisions recorded" over a client whose decisions we simply failed
  // to read — a false completeness claim, which is the one thing this list must never make.
  // Throw instead: the caller surfaces it on the error channel.
  if (!Array.isArray(body?.entries)) {
    throw new Error(`GET /decisions/${client_id} returned no entries array.`);
  }
  return body.entries;
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

/**
 * createReviewSession — POST /review-session -> { review_id }.
 *
 * D-43: the session is created LAZILY, ON UPLOAD, and ALWAYS. Not eagerly on mount
 * (POST /review-session writes reviews/<rid>/ to disk, so a session per page view
 * litters the store), and not conditionally on documents being attached (that makes one
 * button do two things and 422s anyone who attaches files in the wrong order).
 *
 * The review_id is the key for everything session-scoped: retained upload bytes,
 * accumulated slices, and — since T-E(1) / PR #166 — uploaded source documents at
 * reviews/<rid>/documents/, served by GET /review/{review_id}/document/{doc_ref}.
 */
export async function createReviewSession(): Promise<string> {
  const resp = await fetch(`${BASE}/review-session`, { method: "POST" });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(
      (detail as { detail?: string }).detail || `Review session failed: ${resp.status}`,
    );
  }
  const body = (await resp.json()) as { review_id: string };
  return body.review_id;
}

export async function uploadExtract(
  file: File,
  ledger?: File | null,
  reviewId?: string,
  documents?: File[],
  contacts?: File | null,
  source?: string,
): Promise<UploadCoverageResponse> {
  // Multipart: the required primary `file` + an OPTIONAL `ledger` (the Xero 820
  // account-transactions export). The server runs the ledger↔declared-return
  // reconciliation only when a ledger is attached AND the primary is a Xero F5 export.
  const form = new FormData();
  form.append("file", file);
  if (ledger) form.append("ledger", ledger);
  // D-37: review_id is REQUIRED by the backend whenever `documents` are supplied. Without
  // a session the upload is stateless and the documents would be discarded with the
  // request, so the backend 422s naming review_id rather than dropping them silently.
  if (reviewId) form.append("review_id", reviewId);
  // D-38: source documents arrive as a REPEATED multipart part — the backend takes
  // `documents: Optional[List[UploadFile]]`, one append per file, never a zip. Caps are
  // the server's (D-39): 10 MiB per file, 50 MiB per upload, 50 files, each an honest 413.
  for (const d of documents ?? []) form.append("documents", d);
  // Slice C: the OPTIONAL Xero Contacts export (the supplier master). Omitted entirely
  // when none is staged — the backend's no-contacts path is byte-identical to before, and
  // it is only reachable if this field is genuinely absent from the request.
  if (contacts) form.append("contacts", contacts);
  // R-3 / G-5 (D-2026-09-21-unmapped-codes): the source the REVIEWER chose, stated. The
  // server used to route on file shape alone, so a file matching neither Xero detector
  // fell through to the general-extract branch and was reviewed under a demo config that
  // was not the uploader's — silently. Stating the source turns that into a refusal that
  // names what was expected and what arrived.
  if (source) form.append("source", source);
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
