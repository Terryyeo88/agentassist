"""
ui/ — T5.8 mock-first demo showcase (Streamlit).

A GATED, showcase-not-product local UI that renders the Tier-5 agent artifacts
(justification ledger, PENDING proposals, executor dispatch log) and the reviewer
adjudication panel over a MockEngine / RealEngine seam.

Boundaries (frozen invariants — see the T5.8 prompt):
  * Mock-first: no live SAP, no live model, no tokens. Default engine is MockEngine,
    which loads FROZEN deterministic artifacts from tests/fixtures/demo-artifacts/.
  * The UI is a VIEW: it never recomputes F5 boxes and never mutates a ReviewResult.
    Adjudication edits attach to the dossier/proposal, never to box values.
  * validation_status="unvalidated" and show_ai_candidates=False stay frozen (T2.11 is
    the binding gate). Candidates are surfaced with a validation badge and candidate
    framing — never as a confirmed verdict.
  * Surfaces, never asserts: all candidate-facing copy uses candidate framing.

``ui`` is a top-level consumer package (like run_agent.py): it may import agent/,
engine/, report/, audit_bundle/, config/ but MUST NOT import ``anthropic`` directly,
and the render path does not run the case-file loop (agent.loop) — artifacts are
frozen at build time by tests/fixtures/demo_artifacts_builder.py.
"""
