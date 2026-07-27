"""tests/test_dup_window_section.py -- D-2026-07-27-dup-window FAILING-FIRST (unit layer).

BUILD ID: t-dup-window. Written BEFORE the implementation; these MUST fail today for
the RIGHT reason (the section/builder/renderer do not exist), then pass.

THE INVARIANT (three-times rule: prompt + code + THIS file): the DUP_WINDOW findings
stream gains a working-paper section mirroring DUP_SAME_DAY's, carrying FOUR states
(G5, as amended by Terry's A3/A5 ruling):

    None (no section)  -- the client config declares NO dup_window position; the
                          paper renders NOTHING (absence of input = silent omission;
                          the SAP paper stays byte-identical, A5).
    "not_enabled"      -- the config DECLARES a position with the check off; the
                          paper SAYS so, distinguishably from not_examined.
    "examined" / "unavailable" / "not_examined" -- the DUP_SAME_DAY three-state
                          model, driven from the chain's own keys.

ENABLE STATE COMES FROM client_config, NEVER from compile_output -- the chain's
silence when off is what keeps the frozen replay oracle re-freeze-free (G5).

DECLARED-POSITION PROXY (flagged to Terry, not silent): with NO loader change
permitted, ClientConfig cannot distinguish a declared `dup_window_enabled: false`
from a silent config (both load as False/None). The mechanical proxy is
"enabled OR days is not None" -- a declared-false config demonstrates its position
by parking days (loader-legal, pinned by tests/test_dup_window_config.py). A config
declaring bare `false` with no days renders nothing under this proxy.

G6: the DUP_SAME_DAY caveat "same-day only pending a worksheet-derived window"
becomes conditional -- BYTE-IDENTICAL on papers with no active window section (so
the locked pin in tests/test_document_dup_section.py passes UNAMENDED), replaced by
a true-of-both-checks line when the window section is active.

G2: the section prose carries the ASK Step 3D.1.1(d) cite AND the OURS label in the
SAME paragraph -- the cite never travels without the label.

HERMETIC: pure section/renderer units over dict fixtures; no network, no anthropic,
no chain run. DOES NOT edit any existing test file.
"""
from __future__ import annotations

import copy
from pathlib import Path

from report.contract import load_compile_output
from report.sections import build_document_dup_window_section
import report.render as R

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHAIN_SAMPLE = _REPO_ROOT / "tests" / "fixtures" / "chain-run-sample.json"

# The BILL-3004/3005 pair finding exactly as detect_window_dups emits it (shape
# pinned by tests/test_check_document_dup_window.py; restated here as a fixture).
_PAIR_FINDING = {
    "check": "DUP_WINDOW",
    "card_name": "DupSupplier Pte Ltd",
    "doc_total": 2725.0,
    "doc_dates": ["2026-05-12", "2026-05-19"],
    "delta_days": 7,
    "doc_nums": ["BILL-3004", "BILL-3005"],
    "description": (
        "Consider reviewing whether DocNums BILL-3004 and BILL-3005 (same supplier, "
        "same total, 7 days apart) represent the same purchase entered twice."
    ),
    "note": "candidate for reviewer attention",
}

# The locked caveat string (pinned verbatim by tests/test_document_dup_section.py) --
# must stay byte-identical on every paper with NO active window section (G6/A4).
_LOCKED_SAMEDAY_CAVEAT = "same-day only pending a worksheet-derived window"


def _walk_text(node, out: list) -> None:
    """Collect Paragraph plain text from a story (mirrors the locked walker shape)."""
    from reportlab.platypus import Paragraph, Table
    from reportlab.platypus.flowables import KeepTogether

    if isinstance(node, Paragraph):
        out.append(node.getPlainText())
    elif isinstance(node, Table):
        for row in node._cellvalues:
            for cell in row:
                _walk_text(cell, out)
    elif isinstance(node, KeepTogether):
        for c in node._content:
            _walk_text(c, out)
    elif isinstance(node, (list, tuple)):
        for c in node:
            _walk_text(c, out)
    elif isinstance(node, str):
        out.append(node)


def _render_window_story(section) -> str:
    """Render _document_dup_window over a minimal model; return joined text."""
    import types

    story: list = []
    R._document_dup_window(types.SimpleNamespace(document_dup_window=section), story)
    texts: list = []
    _walk_text(story, texts)
    return " ".join(" ".join(texts).split())


# -- U1..U5 -- the builder's four states + the None gate ------------------------------


def test_u1_undeclared_position_builds_no_section():
    """No declared position (enabled False, days None) -> None -> the paper renders
    NOTHING (A5: the SAP paper stays byte-identical). FAILS TODAY: builder absent."""
    co = load_compile_output(_CHAIN_SAMPLE)
    assert build_document_dup_window_section(
        co, dup_window_enabled=False, dup_window_days=None
    ) is None


def test_u2_declared_false_builds_not_enabled():
    """A config DECLARING the check off (position via parked days) -> "not_enabled"."""
    co = load_compile_output(_CHAIN_SAMPLE)
    section = build_document_dup_window_section(
        co, dup_window_enabled=False, dup_window_days=7
    )
    assert section is not None
    assert section.status == "not_enabled"
    assert section.findings is None
    assert section.reason == ""
    assert section.window_days == 7


def test_u3_enabled_with_findings_is_examined():
    co = copy.deepcopy(load_compile_output(_CHAIN_SAMPLE))
    co["document_dup_window_findings"] = [dict(_PAIR_FINDING)]
    section = build_document_dup_window_section(
        co, dup_window_enabled=True, dup_window_days=7
    )
    assert section.status == "examined"
    assert section.findings == [_PAIR_FINDING]

    co["document_dup_window_findings"] = []
    empty = build_document_dup_window_section(
        co, dup_window_enabled=True, dup_window_days=7
    )
    assert empty.status == "examined" and empty.findings == []


def test_u4_enabled_thrown_is_unavailable():
    co = copy.deepcopy(load_compile_output(_CHAIN_SAMPLE))
    co["document_dup_window_findings"] = None
    co["document_dup_window_status"] = {
        "level": "unavailable", "reason": "window dup check failed to run: boom"
    }
    section = build_document_dup_window_section(
        co, dup_window_enabled=True, dup_window_days=7
    )
    assert section.status == "unavailable"
    assert "boom" in section.reason
    assert section.findings is None


def test_u5_enabled_legacy_compile_is_not_examined():
    """Enabled config over a compile_output that predates the check (neither key) --
    the FOURTH-state cousin: the check is on but THIS review never ran it."""
    co = load_compile_output(_CHAIN_SAMPLE)
    assert "document_dup_window_findings" not in co
    section = build_document_dup_window_section(
        co, dup_window_enabled=True, dup_window_days=7
    )
    assert section.status == "not_examined"
    assert section.findings is None


# -- U6 -- not_enabled and not_examined are TEXTUALLY distinct on the page ------------


def test_u6_not_enabled_vs_not_examined_render_distinct_text():
    co = load_compile_output(_CHAIN_SAMPLE)
    not_enabled = _render_window_story(build_document_dup_window_section(
        co, dup_window_enabled=False, dup_window_days=7
    ))
    not_examined = _render_window_story(build_document_dup_window_section(
        co, dup_window_enabled=True, dup_window_days=7
    ))
    assert not_enabled and not_examined
    assert not_enabled != not_examined, "the two off-states must not read identically"
    assert "NOT ENABLED" in not_enabled
    assert "NOT ENABLED" not in not_examined
    assert "NOT performed for this review" in not_examined


# -- U7 (G6/A4) -- the conditional same-day caveat ------------------------------------


def _sameday_caveat_text(window_section) -> str:
    """Render _document_dup with a live document_dup section + the given window
    section; return the joined caveat-area text."""
    import types

    from report.sections import DocumentDupSection

    story: list = []
    model = types.SimpleNamespace(
        document_dup=DocumentDupSection(findings=[], status="examined", reason=""),
        document_dup_window=window_section,
    )
    R._document_dup(model, story)
    texts: list = []
    _walk_text(story, texts)
    return " ".join(" ".join(texts).split())


def test_u7_sameday_caveat_conditional_byte_identical_when_inactive():
    """No window section (None) OR not_enabled -> the LOCKED caveat string renders
    byte-identical; any enabled-state window section -> replaced by a line that is
    true of both checks, and the locked string is ABSENT."""
    co = load_compile_output(_CHAIN_SAMPLE)

    for inactive in (
        None,
        build_document_dup_window_section(co, dup_window_enabled=False, dup_window_days=7),
    ):
        text = _sameday_caveat_text(inactive)
        assert _LOCKED_SAMEDAY_CAVEAT in text, (
            "the disabled path must keep the locked caveat BYTE-IDENTICAL "
            "(tests/test_document_dup_section.py passes UNAMENDED)"
        )

    for enabled_state in ("examined", "unavailable", "not_examined"):
        co2 = copy.deepcopy(co)
        if enabled_state == "examined":
            co2["document_dup_window_findings"] = []
        elif enabled_state == "unavailable":
            co2["document_dup_window_findings"] = None
            co2["document_dup_window_status"] = {"level": "unavailable", "reason": "x"}
        section = build_document_dup_window_section(
            co2, dup_window_enabled=True, dup_window_days=7
        )
        assert section.status == enabled_state
        text = _sameday_caveat_text(section)
        assert _LOCKED_SAMEDAY_CAVEAT not in text, (
            f"with the window check {enabled_state}, the 'pending a worksheet-derived "
            "window' claim is FALSE and must not render"
        )
        assert "same-day pairs only in this section" in text, (
            "the replacement caveat must scope the same-day check truthfully"
        )


# -- U8 (G2) -- the cite and the OURS label travel together ---------------------------


def test_u8_cite_never_travels_without_ours_label():
    co = copy.deepcopy(load_compile_output(_CHAIN_SAMPLE))
    co["document_dup_window_findings"] = [dict(_PAIR_FINDING)]
    section = build_document_dup_window_section(
        co, dup_window_enabled=True, dup_window_days=7
    )
    text = _render_window_story(section)
    assert "3D.1.1(d)" in text, "the ASK cite must be on the page"
    assert "non-regulatory tuning parameter" in text
    assert "not an IRAS rule" in text
    # Same paragraph: locate the flowable carrying the cite and assert the label
    # is in THAT paragraph, not merely somewhere on the page.
    import types
    story: list = []
    R._document_dup_window(
        types.SimpleNamespace(document_dup_window=section), story
    )
    texts: list = []
    _walk_text(story, texts)
    cite_paras = [t for t in texts if "3D.1.1(d)" in t]
    assert cite_paras, "cite paragraph must exist"
    for para in cite_paras:
        assert "non-regulatory" in para, (
            "G2: the cite must never appear in a paragraph without the OURS label"
        )


# -- U9 -- every new prose string clears the negative-pin literals --------------------

_NEGATIVE_LITERALS = (
    "Severity", "HIGH", "MEDIUM", "LOW",
    "AI-Surfaced Candidates", "AI-surfaced candidates",
    "Signature suppressed", "Do not sign",
    "Not an issue", "Mark known",
    "adjudication", "Adjudication",
    "SAP", "SBODEMOSG",
)


def test_u9_new_prose_clears_negative_literals_all_states():
    co = load_compile_output(_CHAIN_SAMPLE)
    variants = [
        build_document_dup_window_section(co, dup_window_enabled=False, dup_window_days=7),
    ]
    for state_co, kwargs in (
        ({}, {}),  # not_examined
        ({"document_dup_window_findings": [dict(_PAIR_FINDING)]}, {}),  # examined+row
        ({"document_dup_window_findings": []}, {}),  # examined clean
        ({"document_dup_window_findings": None,
          "document_dup_window_status": {"level": "unavailable", "reason": "x"}}, {}),
    ):
        co2 = copy.deepcopy(co)
        co2.update(state_co)
        variants.append(build_document_dup_window_section(
            co2, dup_window_enabled=True, dup_window_days=7
        ))
    for section in variants:
        text = _render_window_story(section)
        for banned in _NEGATIVE_LITERALS:
            assert banned not in text, (
                f"section prose (state {section.status}) must not carry {banned!r}"
            )
    # The conditional replacement caveat too.
    co3 = copy.deepcopy(co)
    co3["document_dup_window_findings"] = []
    active = build_document_dup_window_section(
        co3, dup_window_enabled=True, dup_window_days=7
    )
    caveat_text = _sameday_caveat_text(active)
    for banned in _NEGATIVE_LITERALS:
        assert banned not in caveat_text, f"replacement caveat must not carry {banned!r}"


# -- U10 (H1) -- the not_enabled render carries neither cite nor parameters -----------


def test_u10_not_enabled_renders_heading_and_statement_only():
    """H1 (Terry ruling): on "not_enabled" the section is the heading and the
    not-enabled statement ONLY. No ASK cite, no window number, no honest-status
    caveats — those describe a check that did not run, and six lines of
    check-properties before "there was no check" builds a model the last line has
    to demolish. G2 is not weakened: the cite travels with the check's OUTPUT, and
    there is none."""
    co = load_compile_output(_CHAIN_SAMPLE)
    section = build_document_dup_window_section(
        co, dup_window_enabled=False, dup_window_days=7
    )
    text = _render_window_story(section)
    assert "Windowed Duplicate-Purchase Review" in text
    assert "NOT ENABLED" in text
    assert "3D.1.1(d)" not in text, "no output -> nothing to cite (H1/G2)"
    assert "7" not in text, "the never-applied window number must not render"
    assert "non-regulatory" not in text
    assert "Honest status of this check" not in text
    assert "Basis:" not in text
    # The enabled states keep the full framing (contrast pin, not_examined).
    enabled = _render_window_story(build_document_dup_window_section(
        co, dup_window_enabled=True, dup_window_days=7
    ))
    assert "3D.1.1(d)" in enabled and "Honest status of this check" in enabled


# -- U11 (auditor must-fix) -- the G4b demo-parameter caveat is PINNED to the page ----


def test_u11_fixture_fitted_window_caveat_is_pinned():
    """Auditor Inv-7 gap: without this pin, the 'demo parameter fitted to the
    committed fixture' honesty caveat could silently vanish from the paper while
    all other tests stay green. Pinned for every enabled-state render."""
    co = load_compile_output(_CHAIN_SAMPLE)
    for state_co in (
        {},  # not_examined
        {"document_dup_window_findings": [dict(_PAIR_FINDING)]},
        {"document_dup_window_findings": []},
        {"document_dup_window_findings": None,
         "document_dup_window_status": {"level": "unavailable", "reason": "x"}},
    ):
        co2 = copy.deepcopy(co)
        co2.update(state_co)
        text = _render_window_story(build_document_dup_window_section(
            co2, dup_window_enabled=True, dup_window_days=7
        ))
        assert (
            "window value is a demo parameter fitted to the committed fixture, "
            "not a validated threshold"
        ) in text, "the G4b honesty caveat must be on every enabled-state page"
