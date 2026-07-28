import type { AuditRow, ReviewPayload } from "../api";

/**
 * A small REAL-SHAPED fixture mirroring the frozen API payload: two real check types and
 * the genuinely-seeded doc-592 NO_GST_REG "Far East Imports" demoted entry. No fictional
 * DUP_CLAIM / SEQ_GAP / FLUX — the render smoke test asserts they never appear.
 */
export const REVIEW_FIXTURE: ReviewPayload = {
  client: { client_id: "sbodemosg", client_name: "SAP B1 Demo (SBODEMOSG)", company_db: "SBODEMOSG" },
  period: { start: "2024-07-01", end: "2024-09-30", label: "2024Q3" },
  validation_status: "unvalidated",
  f5_summary: { currency: "SGD", boxes: { box_1_standard_rated_sales: 369589.97, box_8_net_gst: 12663.87 } },
  disclaimer:
    "AgentAssist flags — you decide. Demo over FROZEN SBODEMOSG engine output; validation_status=unvalidated.",
  queue: [
    {
      finding_id: "detect:E1:958",
      check_id: "E1",
      finding_type: "deterministic",
      group: "needs_review",
      vendor: "SG Electronics",
      severity: "MEDIUM",
      description: "Standard-rated sales on a likely export/overseas supply.",
      recommendation: "Confirm export documentation or re-classify as zero-rated.",
      doc_num: 958,
      doc_date: "2024-07-02",
      error_code: "E1",
      display_name: "Standard-rated sales on likely export/overseas supply",
      iras_basis: "IRAS GST Act s21(3) — zero-rating of exports / international services",
      iras_basis_caveat: "Illustrative citation — the IRAS basis shown is itself UNVALIDATED.",
      demoted: false,
      annotation: null,
      prior_dispositions: [],
      // B3a-2 fixture refresh (authorized, item f): the server fingerprints detect rows;
      // this is E1/SG Electronics' real computed value — a null here would falsely render
      // the row non-adjudicable under the no-silent-dead-buttons rule.
      fingerprint: "sha256:fcc8439a400439ad83b7299b57c5ad45f761cc1435d7269e573a3df9f8e5cd73",
      candidate_framing_text: "Candidate for review: possible export treatment mismatch.",
      completeness: { required: [], present: [], missing: [], satisfied: true },
      inputs_hash: "sha256:abc",
      proposal_id: null,
      proposal_status: null,
      validation_status: "unvalidated",
    },
    {
      finding_id: "detect:NO_GST_REG:592",
      check_id: "NO_GST_REG",
      finding_type: "deterministic",
      group: "marked_known",
      vendor: "Far East Imports",
      severity: "HIGH",
      // #50 / D-26 — these three strings are HAND-COPIES of backend values with no
      // binding test. All three were divergent before this build; :53 and :54 had
      // been silently stale against production since they were written. Sources:
      //   description    <- mcp-servers/custom/sap_b1_server.py:1510-1512
      //   recommendation <- mcp-servers/custom/sap_b1_server.py:1514
      //   iras_basis     <- agent/registry.py:250 (CHECK_REGISTRY["NO_GST_REG"])
      // If you change any of them, change the source first and copy from it.
      description:
        "Input tax claimed from supplier V1010 (Far East Imports) without a GST registration number — may not be claimable.",
      recommendation:
        "Obtain a valid tax invoice bearing the supplier's GST registration number; whether the conditions for claiming input tax are met is for the reviewer to determine.",
      doc_num: 592,
      doc_date: "2024-07-16",
      error_code: "NO_GST_REG",
      display_name: "Input tax claimed from supplier with no GST registration number",
      iras_basis: "GST (General) Regulations [2026 Ed.], reg 11 — Conditions for claiming input tax",
      iras_basis_caveat: "Illustrative citation — the IRAS basis shown is itself UNVALIDATED.",
      demoted: true,
      annotation:
        "Previously adjudicated 1 time(s); most recent: KNOWN_ACCEPTED by Prior-Period Reviewer (2024Q2).",
      prior_dispositions: ["KNOWN_ACCEPTED"],
      fingerprint: "sha256:3d87ffc0",
      candidate_framing_text: "Candidate for review: supplier GST registration absent.",
      completeness: { required: [], present: [], missing: [], satisfied: true },
      inputs_hash: "sha256:def",
      proposal_id: null,
      proposal_status: null,
      validation_status: "unvalidated",
    },
  ],
};

export const AUDIT_FIXTURE: AuditRow[] = [
  {
    seq: 0,
    tier: 1,
    tier_label: "Tier 1 · work in staging",
    tool_name: "run_review_chain",
    outcome: "allowed",
    justification: "Gather the deterministic GST review findings.",
    blocked_reason: "",
    timestamp: "2026-06-16T10:11:13Z",
    entry_hash: "sha256:a819abe3…",
  },
];
