"""tests/test_report_signable_guard.py — BUILD ID t-xero-signoff, FAILING-FIRST (Contract B).

The #43 guard: when a report is rendered as an AI-CANDIDATE PREVIEW
(``show_ai_candidates=True``) it must NOT present a signable declaration page — an
AI-candidate preview is not a signable working paper. Written BEFORE the implementation;
MUST fail today for the RIGHT reason — the feature is absent:

  * ``report.report.ReportModel`` has no ``show_ai_candidates`` field yet;
  * ``report.render._signature`` renders the SAME signable block regardless of the flag;
  * ``report.render.render_pdf`` prepends no banner.

HARD INVARIANTS PINNED HERE (three-times rule — prompt + code + THIS test):
  * GUARD KEYS ON ``show_ai_candidates`` ONLY, NEVER ``validation_status`` — the flag-False
    render is byte-identical to today's signable block EVEN THOUGH ``validation_status`` is
    "unvalidated" everywhere. The suppression/banner text must NOT mention
    ``validation_status`` and must NOT claim the deterministic findings are invalid; it
    speaks only to the signability of an AI-candidate preview render.
  * SYSTEM-NEVER-SIGNS-A-PREVIEW — flag True SUPPRESSES the ruled signature line and the
    "Signature … Date:" line, replacing them with explicit text ("signature suppressed" /
    "not a signable" preview). Flag True also PREPENDS a loud report-level UNVALIDATED banner
    before the cover; flag False starts with the cover exactly as today.

Mirrors tests/test_sections.py (build_report + a minimal ClientConfig) and
tests/test_reasoning_shell_seal_render.py (assert on the story flowable list, not PDF bytes).
Hermetic: no anthropic, no tokens.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from config.loader import ClientConfig
from report.contract import load_compile_output
from report.render import _signature, render_pdf
from report.report import build_report

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"
_COVER_TITLE = "AgentAssist GST Compliance Review"


def _make_cfg(**overrides) -> ClientConfig:
    base = dict(
        client_id="sbodemosg",
        client_name="SBODEMOSG Demo",
        gst_registration_number="M12345678X",
        applicable_gst_rate=0.07,
        service_layer_url="https://fake",
        company_db="SBODEMOSG",
        username="manager",
        password="manager",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.1,
        reviewer_name="Terry Yeo",
        firm_name="AgentAssist Pte Ltd",
    )
    base.update(overrides)
    return ClientConfig(**base)


def _raw() -> dict:
    return load_compile_output(FIXTURE)


def _para_texts(story: list) -> list[str]:
    """Plain-text of every Paragraph flowable in `story` (non-Paragraph flowables skipped)."""
    out: list[str] = []
    for f in story:
        if hasattr(f, "getPlainText"):
            try:
                out.append(f.getPlainText())
            except Exception:
                pass
    return out


def _is_signature_line(text: str) -> bool:
    return text.startswith("Signature") and "Date:" in text


# ── B1. build_report threads config.show_ai_candidates onto the model ─────────────────

def test_build_report_show_ai_false_by_default():
    m = build_report(_raw(), _make_cfg(show_ai_candidates=False), generated_at=_GENERATED_AT)
    assert getattr(m, "show_ai_candidates", "MISSING") is False


def test_build_report_show_ai_true_when_config_true():
    m = build_report(_raw(), _make_cfg(show_ai_candidates=True), generated_at=_GENERATED_AT)
    assert getattr(m, "show_ai_candidates", "MISSING") is True


# ── B2. _signature: flag False → today's signable block (validation_status is unvalidated) ──

def test_signature_signable_when_flag_false():
    m = build_report(_raw(), _make_cfg(show_ai_candidates=False), generated_at=_GENERATED_AT)
    story: list = []
    _signature(m, story)
    texts = _para_texts(story)

    # The ruled "Signature … Date:" line is present — a signable declaration page.
    assert any(_is_signature_line(t) for t in texts), (
        f"signable signature line missing when flag False; texts={texts}"
    )
    joined = " ".join(texts).lower()
    assert "signature suppressed" not in joined
    assert "not a signable" not in joined


# ── B3. _signature: flag True → suppressed (no signable line); keys on show_ai only ───

def test_signature_suppressed_when_flag_true():
    m = build_report(_raw(), _make_cfg(show_ai_candidates=True), generated_at=_GENERATED_AT)
    story: list = []
    _signature(m, story)
    texts = _para_texts(story)
    joined = " ".join(texts).lower()

    # Explicit suppression text speaking to signability of an AI-candidate preview.
    assert "signature suppressed" in joined
    assert "not a signable" in joined
    # The ruled signature line is GONE.
    assert not any(_is_signature_line(t) for t in texts), (
        f"signature line must be suppressed when flag True; texts={texts}"
    )
    # The guard keys on show_ai_candidates ONLY — the suppression text never mentions
    # validation_status and never claims the deterministic findings are invalid.
    assert "validation_status" not in joined


# ── B4. render_pdf: flag True PREPENDS a banner before the cover; False starts at cover ──

def _render_story(model, tmp_path: Path) -> list:
    """Capture the story render_pdf hands to the doc builder, without writing a PDF."""
    captured: dict = {}

    class _Doc:
        def __init__(self, *a, **kw):
            pass

        def build(self, story, **kw):
            captured["story"] = list(story)

    with patch("report.render.SimpleDocTemplate", _Doc):
        render_pdf(model, tmp_path / "capture.pdf")
    return captured["story"]


def _cover_title_index(story: list) -> int:
    for i, f in enumerate(story):
        if hasattr(f, "getPlainText"):
            try:
                if f.getPlainText() == _COVER_TITLE:
                    return i
            except Exception:
                pass
    raise AssertionError("cover title flowable not found in story")


def test_render_no_banner_before_cover_when_flag_false(tmp_path):
    m = build_report(_raw(), _make_cfg(show_ai_candidates=False), generated_at=_GENERATED_AT)
    story = _render_story(m, tmp_path)
    idx = _cover_title_index(story)
    # Nothing but the cover's own leading Spacer precedes the title — no banner paragraphs.
    assert _para_texts(story[:idx]) == []


def test_render_prepends_unvalidated_banner_when_flag_true(tmp_path):
    m = build_report(_raw(), _make_cfg(show_ai_candidates=True), generated_at=_GENERATED_AT)
    story = _render_story(m, tmp_path)
    idx = _cover_title_index(story)
    before = _para_texts(story[:idx])
    assert before, "a report-level banner must precede the cover when flag True"
    joined = " ".join(before).lower()
    assert "unvalidated" in joined
    # The banner speaks to the AI-candidate PREVIEW, not to the deterministic findings.
    assert ("candidate" in joined) or ("preview" in joined) or ("not a signable" in joined)
