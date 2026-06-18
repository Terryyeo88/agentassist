"""api/ — thin FastAPI seam over the FROZEN demo artifacts (T6.1, Lane C1).

This package serves the review surface (queue → finding detail → decide → sign →
audit) as JSON for the React front end under ``frontend/``. It is a PRESENTATION /
SERVE layer:

  * It imports ``ui``/``agent``/``engine``/``report`` view-models ONLY — never
    ``anthropic`` or the Claude Agent SDK (mirrors the ``ui/`` no-anthropic posture;
    see docs/merge-gates.md). ``orchestrator/`` and ``engine/`` are untouched.
  * It reads the FROZEN SBODEMOSG artifacts via ``ui.artifacts.load_demo_artifacts``
    (MockEngine path) — no SAP, no model, no tokens.
  * There is NO command/classifier endpoint here; that is Lane C2 (deferred).

``built ≠ demo-validated ≠ accuracy-validated``; the per-finding IRAS citations are
themselves UNVALIDATED (T2.11 gates customer-facing claims).
"""
