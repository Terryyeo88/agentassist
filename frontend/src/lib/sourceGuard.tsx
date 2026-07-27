import type { ReactElement } from "react";

/*
 * sourceGuard — the source-tag guard (Commit 1; defence-in-depth for §2).
 *
 * The §2 invariant: SAP-sourced data must never appear on a Xero-labelled surface. Today that
 * isolation rests ENTIRELY on Root.tsx mounting the SAP surface (<App/>) and the Xero surface
 * (<XeroUploadPanel/>) mutually-exclusively. This guard adds a second line of defence INSIDE the
 * shared components (ReviewScreen / Queue / FindingDetail): a mount declares the source it is FOR
 * (`expectedSource`), and if the payload it is handed carries a different source identity
 * (`sourceKind`), the component WITHHOLDS the data and renders an honest mismatch state instead.
 *
 * Honest-failure-wins (the §2 tiebreak): a component that visibly refuses foreign data is broken
 * in a way that gets noticed and fixed; one that renders the wrong source convincingly is
 * believed. So an absent or unrecognised sourceKind is treated as a MISMATCH, never as a pass.
 *
 * OPT-IN: the guard only engages when a caller passes `expectedSource`. Components mounted
 * without it (every pre-existing call site and test) render exactly as before — this guard is
 * purely additive and changes no response-key contract (it reads the existing source identity).
 */

/** The coarse source family a surface is labelled for. */
export type ExpectedSource = "sap" | "xero";

// The SAP review surface (App / GET /review) is the b1_demo source — Root.tsx's Source type
// names it. ReviewPayload carries no source_kind key, so App declares this tag explicitly.
const SAP_SOURCE_KINDS = new Set<string>(["b1_demo"]);

// Every source_kind the upload backend (POST /review/upload) emits on its engine/coverage
// branches — the Xero family. Mirrors api/app.py's per-branch source_kind values.
const XERO_SOURCE_KINDS = new Set<string>([
  "xero_f5_upload",
  "extract_review",
  "extract_upload",
  "xero_sales_upload",
]);

/** Map a raw source identity to its family. Unrecognised / absent → "unknown". */
export function sourceFamily(kind: string | null | undefined): ExpectedSource | "unknown" {
  if (kind && SAP_SOURCE_KINDS.has(kind)) return "sap";
  if (kind && XERO_SOURCE_KINDS.has(kind)) return "xero";
  return "unknown";
}

/**
 * True when a surface labelled `expected` was handed a payload whose source family differs.
 * "unknown" (absent or unrecognised sourceKind) always counts as a mismatch — fail visibly.
 */
export function isSourceMismatch(
  expected: ExpectedSource,
  kind: string | null | undefined,
): boolean {
  return sourceFamily(kind) !== expected;
}

/**
 * The honest mismatch state: names both the surface's expected source and the foreign tag it
 * received, and states plainly that the data is withheld. role="alert" so it is announced, not
 * silently swapped for the real findings.
 */
export function SourceMismatch({
  expected,
  got,
}: {
  expected: ExpectedSource;
  got: string | null | undefined;
}): ReactElement {
  return (
    <div className="panel detail source-mismatch" role="alert">
      <strong>Data source mismatch — data withheld.</strong> This surface is labelled{" "}
      <span className="mono">{expected}</span> but received a payload tagged{" "}
      <span className="mono">{got ?? "unknown"}</span>. The findings are not shown here: a
      cross-source mismatch is surfaced honestly, never rendered as if it belonged to this page.
    </div>
  );
}
