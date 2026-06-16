"""
tests/test_t58_mock_engine.py — T5.8 render acceptance + hermetic guards.

Render acceptance (the T5.8 analogue of offline-replay acceptance):
  * the MockEngine seam loads frozen deterministic artifacts;
  * all four view-models build content from those artifacts;
  * adjudicating → Sign produces a working-paper PDF that carries the reviewer name and
    respects show_ai_candidates=False (the AI-candidates subsection stays disabled).

Hermetic guards:
  * candidate framing for every dossier passes the language-lint (no verdict copy);
  * the Mock + Sign path imports neither anthropic, the SDK, nor agent.loop (checked in
    a clean subprocess so the assertion is not polluted by other tests).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pdfplumber
import pytest

from agent.lint import lint_framing
from ui.artifacts import (
    adjudication_items,
    executor_dispatch_rows,
    ledger_timeline_rows,
    load_demo_artifacts,
    pending_proposal_rows,
)
from ui.engine_seam import MockEngine, RealEngine, select_engine
from ui.sign import sign_working_paper

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Engine seam ───────────────────────────────────────────────────────────────────

def test_default_engine_is_mock():
    assert select_engine().name == "mock"
    assert isinstance(select_engine("mock"), MockEngine)
    assert isinstance(select_engine("real"), RealEngine)


def test_mock_engine_returns_completed_review_result():
    rr = MockEngine().review()
    assert rr["status"] == "completed"
    assert rr["compile_output"]["detect"]["issues"], "expected real deterministic findings"
    # Honest: reasoning candidates are empty offline (token-gated), never faked.
    assert rr["reasoning_artefact"]["candidates"] == []


# ── Four views render from artifacts ───────────────────────────────────────────────

def test_all_four_views_build_content():
    arts = load_demo_artifacts()

    ledger_rows = ledger_timeline_rows(arts.ledger)
    assert ledger_rows, "ledger timeline empty"
    assert any(r["tier"] == 0 for r in ledger_rows) and any(r["tier"] == 1 for r in ledger_rows)

    prop_rows = pending_proposal_rows(arts.proposals)
    assert prop_rows and all(r["status"] == "pending" for r in prop_rows)

    # Executor log is EMPTY in a fresh mock — nothing approved/executed yet.
    assert executor_dispatch_rows(arts.ledger) == []

    items = adjudication_items(arts)
    assert len(items) == len(arts.dossiers)
    sample = items[0]
    assert sample["validation_status"] == "unvalidated"
    assert sample["completeness"]["satisfied"] is True
    assert sample.get("proposal_id"), "dossier should join to a staging proposal by inputs_hash"


def test_every_dossier_framing_passes_lint():
    arts = load_demo_artifacts()
    for d in arts.dossiers:
        res = lint_framing(d["candidate_framing_text"])
        assert res.passed, f"framing failed lint for {d['finding_id']}: {res.reasons}"


# ── Sign → working-paper PDF ────────────────────────────────────────────────────────

def test_sign_emits_pdf_with_reviewer_name(tmp_path):
    rr = MockEngine().review()
    pdf = sign_working_paper(
        rr, reviewer_name="Jane Tan", firm_name="Tan & Co", out_dir=tmp_path
    )
    assert pdf.exists() and pdf.stat().st_size > 0

    with pdfplumber.open(pdf) as doc:
        text = "\n".join(page.extract_text() or "" for page in doc.pages)

    # Reviewer name carried on the cover + signature page.
    assert "Jane Tan" in text
    # show_ai_candidates=False ⇒ the AI-candidates subsection is NOT rendered, even
    # though the frozen ReviewResult carries a (crafted) document candidate.
    assert "AI-Surfaced Candidates" not in text
    assert "AI-surfaced candidates" not in text


def test_sign_requires_reviewer_name(tmp_path):
    rr = MockEngine().review()
    with pytest.raises(ValueError):
        sign_working_paper(rr, reviewer_name="   ", out_dir=tmp_path)


def test_demo_client_config_has_no_secrets():
    from ui.sign import demo_client_config
    cfg = demo_client_config(reviewer_name="X", firm_name="Y")
    assert cfg.username == "" and cfg.password == ""
    assert cfg.show_ai_candidates is False  # frozen gate respected


# ── Hermetic import guard (clean subprocess) ────────────────────────────────────────

_GUARD_SNIPPET = """
import sys
from ui.engine_seam import MockEngine
from ui.sign import sign_working_paper
import tempfile, pathlib
rr = MockEngine().review()
sign_working_paper(rr, reviewer_name="Guard", out_dir=pathlib.Path(tempfile.mkdtemp()))
banned = [m for m in ("anthropic", "claude_agent_sdk", "agent.loop") if m in sys.modules]
print("BANNED:" + ",".join(banned))
"""


def test_mock_and_sign_path_imports_nothing_banned():
    """The Mock + Sign render path must not import anthropic, the SDK, or agent.loop."""
    proc = subprocess.run(
        [sys.executable, "-c", _GUARD_SNIPPET],
        cwd=str(_REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"guard subprocess failed: {proc.stderr}"
    out = proc.stdout.strip().splitlines()[-1]
    assert out == "BANNED:", f"render path imported banned modules: {out}"
