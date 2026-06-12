"""
agent/ — T5.2a action-tier enforcement core.

Pure stdlib. Zero anthropic import. No live SAP. No network.

Honest status: built + hermetically unit-tested; NOT demo-validated (no live
agent loop yet); seal/emit executor handlers and PDF appendix rendering
deferred to T5.3.

CheckSpec is v0/PROVISIONAL: not wired into any consumer. check_id/iras_basis
reconcile against Collin's canonical IRAS VatGroup remap and T2.18 config_keys
when those land. Collin ratifies schema before building deterministic checks
against it.
"""
