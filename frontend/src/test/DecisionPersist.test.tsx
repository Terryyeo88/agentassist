import { describe, it, expect, afterEach, vi } from "vitest";
import { postDecision } from "../api";

/**
 * Decision-persistence api helper (postDecision) — FAILING-FIRST.
 *
 * BUILD ID: t-decision-persistence. Written BEFORE the implementation; MUST fail today for
 * the RIGHT reason — `postDecision` does not exist in ../api yet (import resolves to
 * undefined / the module has no such export). Passes once the helper is added, mirroring
 * the existing `postSign` pattern (JSON POST, throws on non-2xx).
 *
 * Front-end contract this pins (three-times rule — mirrors the backend POST /decision +
 * DECISION_KEYS): recording a decision issues a single POST to /api/decision whose JSON
 * body carries {client_id, finding_id, fingerprint, action, note, reviewer_name}; a failed
 * POST surfaces an error (never a silent success). Robust to component wiring — it exercises
 * the api.ts helper the App's onRecord path calls.
 */

const DECISION_RESPONSE = {
  client_id: "sbodemosg",
  finding_id: "detect:E1:958",
  action: "Mark known",
  disposition: "KNOWN_ACCEPTED",
  fingerprint: "sha256:abc",
  entry_id: "b986d57f",
  entry_hash: "sha256:def",
  chain_length: 1,
  validation_status: "unvalidated",
  disclaimer: "AgentAssist flags — you decide.",
};

describe("postDecision (decision-persistence api helper)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("POSTs /api/decision with the action, note and fingerprint in the body", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(DECISION_RESPONSE), { status: 200 }))
    );
    vi.stubGlobal("fetch", fetchMock);

    await postDecision({
      client_id: "sbodemosg",
      finding_id: "detect:E1:958",
      fingerprint: "sha256:abc",
      action: "Mark known",
      note: "Known treatment carried from a prior period.",
      reviewer_name: "Collin",
      period: "2024Q3",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/decision");
    expect(init.method).toBe("POST");

    const body = JSON.parse(init.body as string);
    expect(body.client_id).toBe("sbodemosg");
    expect(body.finding_id).toBe("detect:E1:958");
    expect(body.fingerprint).toBe("sha256:abc");
    expect(body.action).toBe("Mark known");
    expect(body.note).toBe("Known treatment carried from a prior period.");
    expect(body.reviewer_name).toBe("Collin");
  });

  it("throws when the POST fails (non-2xx surfaces an error, never a silent success)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(new Response(JSON.stringify({ detail: "note required" }), { status: 422 }))
      )
    );

    await expect(
      postDecision({
        client_id: "sbodemosg",
        finding_id: "detect:E1:958",
        fingerprint: "sha256:abc",
        action: "Decline",
        note: "",
        reviewer_name: "Collin",
      })
    ).rejects.toThrow();
  });
});
