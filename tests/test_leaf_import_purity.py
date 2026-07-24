"""tests/test_leaf_import_purity.py -- R5(a) of D-2026-07-24-decision-render.

CLOSES A REAL GAP: the CI import-scan (docs/merge-gates.md Gate a) greps orchestrator/ ONLY,
so a report/ -> agent/ import -- the exact temptation of the decision-render build, where
report/ renders adjudication data that LIVES in agent/ -- would land SILENTLY. This test makes
leaf purity a committed assertion (the same AST-scan shape as
tests/test_t59d_dispatch_exec.py's _BANNED_IMPORT_ROOTS).

PINS REALITY, not aspiration (verified against master 6a506a3 before authoring):
  * report/ imports orchestrator.schemas (contract.py) and config.* -- LEGAL, not banned here.
    It must never import agent, reasoning, documents, or anthropic: the decision view reaches
    build_report AS DATA (the accumulated= precedent), never via an import.
  * engine/ composes the pipeline and ALREADY legally imports reasoning.* and documents.*
    (engine/review.py:51-52, :303 -- the T5.1 seam). It must never import agent (the
    decision layer -- Terry R1 Branch B: the ReviewInputs pass-through carries ZERO logic and
    ZERO decision-layer imports) or anthropic.

Scans EVERY .py file in each package, INCLUDING function-level (lazy) imports -- a lazy
`from agent.decision_ledger import ...` inside a render helper is exactly the failure mode.

THREE-TIMES RULE: the leaf-purity rule lives in CLAUDE.md/merge-gates (prompt), is enforced
by the import structure itself (code), and is asserted HERE (test). Passes TODAY and after --
a guard, not failing-first; it goes red the moment anyone crosses the boundary.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Banned import ROOTS per leaf package (the first dotted segment of the module path).
_LEAF_BANS: dict[str, frozenset[str]] = {
    "report": frozenset({"agent", "reasoning", "documents", "anthropic"}),
    "engine": frozenset({"agent", "anthropic"}),
}


def _import_roots(path: Path) -> set[tuple[str, int]]:
    """Every imported module ROOT in a file, at any nesting depth (lazy imports included)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import (stays inside the package) -- not a boundary
            # crossing; module=None covers `from . import x`.
            if node.level == 0 and node.module:
                roots.add((node.module.split(".")[0], node.lineno))
    return roots


@pytest.mark.parametrize("package", sorted(_LEAF_BANS))
def test_leaf_package_never_imports_banned_roots(package: str):
    """No .py file under the leaf package imports a banned root -- even lazily."""
    banned = _LEAF_BANS[package]
    pkg_dir = _REPO_ROOT / package
    assert pkg_dir.is_dir(), f"{package}/ must exist at the repo root"

    violations: list[str] = []
    for py in sorted(pkg_dir.rglob("*.py")):
        for root, lineno in _import_roots(py):
            if root in banned:
                violations.append(f"{py.relative_to(_REPO_ROOT)}:{lineno} imports {root!r}")
    assert not violations, (
        f"{package}/ must stay a pure leaf w.r.t. {sorted(banned)} -- the decision view "
        "travels AS DATA, never via an import (Gate-a is scoped to orchestrator/ only, so "
        "CI cannot catch this):\n" + "\n".join(violations)
    )
