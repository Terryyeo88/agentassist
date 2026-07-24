import { useEffect, useState } from "react";
import { fetchAudit, type AuditRow } from "../api";

/**
 * AuditTrail — the hash-chained justification ledger as a read-only table (GET /audit).
 * Read-only: it shows what the deterministic chain recorded; it never mutates anything.
 */
export function AuditTrail() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    fetchAudit()
      .then(setRows)
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <section className="audit panel">
      <h3>Audit trail — justification ledger</h3>
      <div style={{ padding: "0 16px 16px" }}>
        {err && <div className="callout warn">{err}</div>}
        {!rows && !err && <div className="loading">Loading audit trail…</div>}
        {rows && (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Tier</th>
                <th>Tool</th>
                <th>Outcome</th>
                <th>Justification</th>
                <th>Blocked reason</th>
                <th>When</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.seq}>
                  <td className="mono">{r.seq}</td>
                  <td>{r.tier_label}</td>
                  <td className="mono">{r.tool_name}</td>
                  <td>{r.outcome}</td>
                  <td>{r.justification}</td>
                  <td>{r.blocked_reason || "—"}</td>
                  <td className="mono">{r.timestamp}</td>
                  <td className="mono">{r.entry_hash}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
