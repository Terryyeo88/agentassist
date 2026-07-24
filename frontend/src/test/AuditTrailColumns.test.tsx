import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AuditTrail } from "../components/AuditTrail";
import type { AuditRow } from "../api";

/**
 * Bucket-B wiring: the audit-trail table dropped three fields the GET /audit rows already carry —
 * `blocked_reason`, `timestamp` (and it renders tier_label already). Surface `blocked_reason` and
 * `timestamp` as columns. Pure display; no contract change.
 */

const ROWS: AuditRow[] = [
  {
    seq: 0,
    tier: 1,
    tier_label: "Tier 1 · work in staging",
    tool_name: "run_review_chain",
    outcome: "allowed",
    justification: "Gather the deterministic GST review findings.",
    blocked_reason: "",
    timestamp: "2026-06-16T10:11:13Z",
    entry_hash: "sha256:a819abe3",
  },
  {
    seq: 1,
    tier: 3,
    tier_label: "Tier 3 · seal/emit",
    tool_name: "emit_working_paper",
    outcome: "blocked",
    justification: "Attempted emit before human sign-off.",
    blocked_reason: "human sign-off required",
    timestamp: "2026-06-16T10:12:00Z",
    entry_hash: "sha256:bb17",
  },
];

function fetchReturning(entries: AuditRow[]) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/audit"))
      return Promise.resolve(new Response(JSON.stringify({ entries }), { status: 200 }));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

describe("AuditTrail column wiring (bucket B)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the timestamp and blocked_reason for each row", async () => {
    vi.stubGlobal("fetch", fetchReturning(ROWS));
    render(<AuditTrail />);

    // Column headers present.
    expect(await screen.findByRole("columnheader", { name: /When/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Blocked reason/i })).toBeInTheDocument();

    // Timestamps rendered.
    await waitFor(() =>
      expect(screen.getByText("2026-06-16T10:11:13Z")).toBeInTheDocument()
    );
    expect(screen.getByText("2026-06-16T10:12:00Z")).toBeInTheDocument();

    // A blocked row shows its reason; an allowed row shows the em-dash placeholder.
    expect(screen.getByText("human sign-off required")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
