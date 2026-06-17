"""feeders/ — alternate ChainReader feeders for the deterministic GST chain (T2.12).

"One machine, two feeders": the deterministic checking core (orchestrator/ + the
mcp-servers/custom/sap_b1_server.py tool functions) reads SAP only through the
``ChainReader`` per-surface contract (T2.23). ``SapChainReader`` is the live-SAP
feeder; this package supplies a feeder that reads a client Excel/CSV GST export
instead — normalising AT THE FEEDER and handing the SAME shaped records to the SAME
unchanged core. No check logic is ever forked per feeder.

The feeders here satisfy ``ChainReader`` STRUCTURALLY (duck-typing) — they do not
import or widen the Protocol, so nothing in the deterministic path changes. Pure
stdlib (+ openpyxl, lazily, for .xlsx); no SAP machinery, no anthropic.
"""
