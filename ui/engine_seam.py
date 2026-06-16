"""
ui/engine_seam.py — MockEngine / RealEngine seam for the T5.8 demo.

A minimal protocol with ``review(...) -> ReviewResult`` and two implementations:

  * MockEngine — DEFAULT. Loads the FROZEN deterministic ReviewResult from
    tests/fixtures/demo-artifacts/review_result.json. No SAP, no model, no tokens.
  * RealEngine — a drop-in that delegates to ``engine.review.review``. NOT wired live
    in this slice; ``engine.review`` is imported LAZILY inside ``review`` so importing
    this module (the default Mock path) never pulls the engine pipeline.

Engine selection is explicit via the ``AGENT_UI_ENGINE`` env var (``mock`` | ``real``),
defaulting to ``mock``. Nothing here imports ``anthropic`` or runs the case-file loop.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# Frozen demo artifacts produced once by tests/fixtures/demo_artifacts_builder.py.
DEMO_ARTIFACTS_DIR: Path = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "demo-artifacts"
)

ENGINE_ENV_VAR = "AGENT_UI_ENGINE"


@runtime_checkable
class Engine(Protocol):
    """A review engine the UI renders over. The Mock path returns frozen artifacts."""

    name: str

    def review(self, client_config: Any, period: Any, inputs: Any) -> Any:
        """Return a ReviewResult (object) or its serialised dict form."""
        ...


class MockEngine:
    """Loads the frozen deterministic ReviewResult. Hermetic: no SAP/model/tokens."""

    name = "mock"

    def __init__(self, artifacts_dir: Path | str = DEMO_ARTIFACTS_DIR) -> None:
        self.artifacts_dir = Path(artifacts_dir)

    def review(self, client_config: Any = None, period: Any = None, inputs: Any = None) -> dict:
        """Return the frozen ReviewResult dict. Arguments are ignored (mock)."""
        path = self.artifacts_dir / "review_result.json"
        return json.loads(path.read_text(encoding="utf-8"))


class RealEngine:
    """Drop-in over the deterministic pipeline. NOT wired live in T5.8.

    Delegates to ``engine.review.review`` with the SAME signature, so wiring it live
    later is a configuration change, not a rewrite. The import is deferred so the
    default Mock path never loads the engine/orchestrator pipeline.
    """

    name = "real"

    def review(self, client_config: Any, period: Any, inputs: Any) -> Any:
        from engine.review import review  # lazy import — keeps the Mock path import-clean
        return review(client_config, period, inputs)


def select_engine(name: str | None = None) -> Engine:
    """Return the selected engine. Default Mock; ``real`` only when explicitly chosen.

    Args:
        name: Optional explicit engine name; falls back to the ``AGENT_UI_ENGINE`` env
              var, then to ``mock``.
    """
    choice = (name or os.environ.get(ENGINE_ENV_VAR, "mock")).strip().lower()
    if choice == "real":
        return RealEngine()
    return MockEngine()
