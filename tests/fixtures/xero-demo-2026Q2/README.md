Xero demo company, 2026 Q2, exported 2026-07-28.
74 transaction rows. Ground truth: fixture_manifest.csv (38 baits).
Read by NO test — demo and provenance only.
The 11-row corpus in xero-real-format/ is UNCHANGED and remains the test substrate.
Measured 2026-07-28: 9 of 9 line-level baits fired, 20 clean controls silent.
No DUP row appeared in the queue — by design: DUP_WINDOW surfaces in the
signed paper's window section only, never in the response body
(tests/test_dup_window_paper.py). At the then-configured 7-day window
BILL-3004/3005 was inside the window and Q-4417/INV-8823 (8 days) was not;
at 92 (D-2026-07-29) both are.

Provenance note: AgentAssist_-_Account_Transactions.xlsx and Contacts.csv were
re-exported 2026-07-29 (originals lost to an uncommitted-overwrite + reset on
2026-07-28; one contact renamed before the Contacts re-export). The F5 workbook,
_ADD import CSVs, and fixture_manifest.csv are the 2026-07-28 originals.
