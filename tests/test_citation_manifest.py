"""tests/test_citation_manifest.py — failing-first guard for the citation manifest.

The file under test is ``knowledge-base/sources.md`` — a SINGLE markdown table that
resolves every IRAS / statutory instrument cited anywhere in the codebase to the
CLONED artefact (or an explicit ABSENT row) that a rule-author actually read, with a
per-file edition + verification provenance. It DOES NOT EXIST YET; most tests here are
RED via its absence and go GREEN once the manifest lands per the schema below.

Rulings pinned by these tests (embedded so the manifest cannot drift off them):

  γ (gamma) — the publication-history page is the ONLY admissible evidence of an
      edition. Cover pages are structurally unreliable: three confirmed layering
      artifacts (a cover that says one edition while the pub-history page says
      another). ``evidence`` therefore records the page an edition was read FROM
      (e.g. "p.2 publication history"), never a cover.

  α1 (alpha-1) — primary legislation (the GST Act; the GST (General) Regulations) is
      admissible when SSO-hosted and version-pinned, even absent a downloaded copy —
      but it is still only VERIFIED once an SSO-stamped copy is supplied. Until then
      the row is UNVERIFIED / ABSENT (see the xfail params below).

  δ (delta) — NEVER infer an edition from a citation string or from a filename. The
      Reverse-Charge file's former slug said "2nd edition" while the artefact is the
      Tenth Edition; the manifest must say Tenth. An edition may read UNVERIFIED, but
      it is never back-filled from a slug.

  three-meanings-of-"in-the-repo" — a ``local_path`` means the artefact is CLONED into
      the repository tree (bytes on disk under knowledge-base/), NOT merely that the
      instrument is *cited* in the repo, and NOT that an external copy was consulted.
      ABSENT rows and EXTERNAL-COPY verified_from values keep those three meanings
      distinct.

Hermetic: no network, no anthropic import. The manifest is parsed with a tiny local
helper; source-file tokens are read straight off disk / imported module constants.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths. repo_root == the worktree root; local_path values are relative to it.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
SOURCES_MD = REPO_ROOT / "knowledge-base" / "sources.md"

# The header row, verbatim and in order. One row PER FILE (absent-but-cited
# instruments get a row with local_path == "ABSENT").
HEADER = [
    "local_path",
    "instrument",
    "class",
    "edition",
    "pub_date",
    "pages",
    "sha256",
    "status",
    "superseded_by",
    "verified_by",
    "verified_from",
    "verified_on",
    "evidence",
]

# ---------------------------------------------------------------------------
# Frozen citation inventory (Phase-1 recon @ 17af853).
# ---------------------------------------------------------------------------
CUSTOMER_FACING = [
    "IRAS ASK Annual Review Guide",
    "IRAS e-Tax Guide: How do I prepare my GST return?",
    "IRAS GST: General Guide for Businesses",
    "IRAS e-Tax Guide: GST: Reverse Charge",
    "GST Act",
    "GST (General) Regulations",
    "IRAS GST F5 Return form",
    "IRAS e-Tax Guide: GST: Partial Exemption and Input Tax Recovery",
]

INTERNAL_ONLY = [
    "IRAS e-Tax Guide: GST: Digital Payment Tokens",
    "List of International Services (GST Act extract)",
    "GST Guide on Attribution of Input Tax",
]

ALL_INSTRUMENTS = CUSTOMER_FACING + INTERNAL_ONLY

# Instruments that CANNOT yet satisfy the verified/two-corpora acceptance bars —
# each names the specific blocker (rulings δ / α1). strict=False so a future
# supply that flips them GREEN reports as xpass rather than breaking the suite.
XFAIL_REASONS = {
    "IRAS e-Tax Guide: GST: Partial Exemption and Input Tax Recovery": (
        "rule-author does not hold the guide; edition '6th ed' in the banner is "
        "distrusted by ruling (δ); row is UNVERIFIED/ABSENT until supplied"
    ),
    "GST Act": (
        "primary legislation admissible per α1 (SSO-hosted, version-pinned) but no "
        "SSO-stamped copy supplied yet; row UNVERIFIED/ABSENT"
    ),
    "GST (General) Regulations": (
        "primary legislation admissible per α1 (SSO-hosted, version-pinned) but no "
        "SSO-stamped copy supplied yet; row UNVERIFIED/ABSENT"
    ),
    "IRAS GST F5 Return form": (
        "form cited by registry basis but no form artefact supplied; row "
        "UNVERIFIED/ABSENT"
    ),
}


def _cf_params():
    """CUSTOMER_FACING params, with the four blocked instruments marked xfail."""
    out = []
    for inst in CUSTOMER_FACING:
        reason = XFAIL_REASONS.get(inst)
        if reason is not None:
            out.append(pytest.param(inst, marks=pytest.mark.xfail(reason=reason, strict=False)))
        else:
            out.append(pytest.param(inst))
    return out


# ---------------------------------------------------------------------------
# Tiny manifest parser (no network, no third-party markdown lib).
# ---------------------------------------------------------------------------
def _table_lines(text: str):
    return [ln for ln in text.splitlines() if ln.strip().startswith("|")]


def _cells(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(cells):
    return all(c and set(c) <= set("-: ") for c in cells)


def load_table():
    """Return (header_cells, data_rows). data_rows == list of (cells, raw_line).

    Absent file -> ([], []) so tests fail on assertions rather than erroring; the
    existence/parse tests below assert presence explicitly.
    """
    if not SOURCES_MD.is_file():
        return [], []
    text = SOURCES_MD.read_text(encoding="utf-8")
    lines = _table_lines(text)
    if not lines:
        return [], []
    header = _cells(lines[0])
    data = []
    for ln in lines[1:]:
        cells = _cells(ln)
        if _is_separator(cells):
            continue
        data.append((cells, ln))
    return header, data


def load_rows():
    """Data rows as dicts keyed by HEADER, plus ``_raw`` (line) and ``_cells``."""
    _header, data = load_table()
    rows = []
    for cells, raw in data:
        d = dict(zip(HEADER, cells))
        d["_raw"] = raw
        d["_cells"] = cells
        rows.append(d)
    return rows


def _matches(name: str, cell: str) -> bool:
    """Case-insensitive substring match, either direction."""
    n, c = name.lower(), cell.lower()
    return bool(c) and (n in c or c in n)


def _rows_for(instrument: str):
    return [r for r in load_rows() if _matches(instrument, r.get("instrument", ""))]


def _current_rows_for(instrument: str):
    return [r for r in _rows_for(instrument) if r.get("status") == "CURRENT"]


# ---------------------------------------------------------------------------
class TestManifestExists:
    """The manifest is present, is one parseable table, and is 13 columns wide."""

    def test_sources_md_exists(self):
        assert SOURCES_MD.is_file(), f"expected manifest at {SOURCES_MD}"

    def test_table_parses(self):
        header, data = load_table()
        assert header, "no markdown table header found in sources.md"
        assert data, "manifest table has no data rows"

    def test_header_matches_schema_exactly(self):
        header, _data = load_table()
        assert header == HEADER, f"header {header!r} != schema {HEADER!r}"

    def test_every_row_has_13_cells(self):
        _header, data = load_table()
        assert data, "no data rows to check width against"
        for cells, raw in data:
            assert len(cells) == 13, f"row is not 13 cells wide: {raw!r} -> {cells!r}"


# ---------------------------------------------------------------------------
class TestResolutionA:
    """S2(a): every cited instrument resolves to at least one manifest row."""

    @pytest.mark.parametrize("instrument", ALL_INSTRUMENTS)
    def test_instrument_resolves(self, instrument):
        rows = _rows_for(instrument)
        assert rows, f"instrument {instrument!r} matches no row in sources.md"


# ---------------------------------------------------------------------------
class TestVerifiedB:
    """S2(b): each customer-facing instrument has at least one row with a real
    (non-UNVERIFIED) edition AND a non-UNVERIFIED verified_by.

    The four blocked instruments are xfail (δ / α1): the rule-author does not hold
    the Partial-Exemption guide, and no SSO-stamped Act/Regs or F5-form artefact has
    been supplied, so their only honest rows are UNVERIFIED / ABSENT.
    """

    @pytest.mark.parametrize("instrument", _cf_params())
    def test_has_a_verified_row(self, instrument):
        rows = _rows_for(instrument)
        assert rows, f"instrument {instrument!r} matches no row"
        ok = [
            r
            for r in rows
            if r.get("edition") != "UNVERIFIED" and r.get("verified_by") != "UNVERIFIED"
        ]
        assert ok, f"no verified row (edition+verified_by) for {instrument!r}"


# ---------------------------------------------------------------------------
class TestTwoCorporaA8:
    """A8: each customer-facing instrument has at least one row that is a live,
    cloned corpus member — status != SUPERSEDED, local_path != ABSENT, and the
    file is actually on disk.

    REFUTATION: the ruling expected the exempt-supply slice's Digital-Payment-Tokens
    and List-of-International-Services citations to be the FIRST TWO this catches as
    ABSENT. That expectation is REFUTED — both were supplied into knowledge-base/ on
    2026-07-17 / 2026-07-19 and now resolve to cloned files, so they are internal-only
    (not even under test here) and pass resolution. The instruments that genuinely
    fail A8 are the four xfail blockers (Partial-Exemption guide + Act + Regs + F5
    form), not the two the ruling predicted.
    """

    @pytest.mark.parametrize("instrument", _cf_params())
    def test_has_a_cloned_current_corpus_member(self, instrument):
        rows = _rows_for(instrument)
        assert rows, f"instrument {instrument!r} matches no row"
        live = [
            r
            for r in rows
            if r.get("status") != "SUPERSEDED"
            and r.get("local_path") != "ABSENT"
            and (REPO_ROOT / r.get("local_path", "")).is_file()
        ]
        assert live, f"no cloned, non-superseded corpus member for {instrument!r}"


# ---------------------------------------------------------------------------
class TestNoContradictionC:
    """S2(c): where a customer-facing string in the codebase names an explicit
    edition/date, the manifest's CURRENT row for that instrument must carry the
    matching (normalised) edition + pub_date — the code and the manifest may not
    contradict each other.

    NOTE: the token-in-source half of each case reads a real repo file and would
    PASS standalone; the whole test is RED until sources.md supplies the CURRENT row.
    """

    # (source_file, token, instrument, expected_edition, expected_date)
    CASES = [
        (
            "orchestrator/check_partial_exemption.py",
            "Tenth Edition, 30 Jan 2026",
            "IRAS e-Tax Guide: GST: Reverse Charge",
            "Tenth Edition",
            "30 Jan 2026",
        ),
        (
            "report/constants.py",
            "16th Edition (30 Jan 2026)",
            "IRAS ASK Annual Review Guide",
            "Sixteenth Edition",  # 16th == Sixteenth normalisation
            "30 Jan 2026",
        ),
    ]

    @pytest.mark.parametrize(
        "source_file,token,instrument,expected_edition,expected_date", CASES
    )
    def test_code_and_manifest_agree(
        self, source_file, token, instrument, expected_edition, expected_date
    ):
        src = (REPO_ROOT / source_file).read_text(encoding="utf-8")
        assert token in src, f"token {token!r} not found in {source_file}"

        current = _current_rows_for(instrument)
        assert current, f"no CURRENT manifest row for {instrument!r}"
        assert any(
            r.get("edition") == expected_edition and r.get("pub_date") == expected_date
            for r in current
        ), (
            f"no CURRENT row for {instrument!r} with edition {expected_edition!r} "
            f"+ pub_date {expected_date!r}"
        )

    def test_no_current_row_is_unverified_for_an_edition_named_in_code(self):
        # Negative: RC + ASK are both named WITH an explicit edition token in code,
        # so their CURRENT manifest rows must not read UNVERIFIED in the edition cell.
        for instrument in (
            "IRAS e-Tax Guide: GST: Reverse Charge",
            "IRAS ASK Annual Review Guide",
        ):
            current = _current_rows_for(instrument)
            assert current, f"no CURRENT row for {instrument!r}"
            for r in current:
                assert "UNVERIFIED" not in r.get("edition", ""), (
                    f"CURRENT row for {instrument!r} has UNVERIFIED edition while "
                    f"code names an explicit edition"
                )


# ---------------------------------------------------------------------------
class TestNoFilenameSourcingD:
    """S2(d): editions are never sourced from filenames (ruling δ), and no citation
    string leaks a ``.pdf`` filename to a customer.
    """

    def test_no_pdf_in_partial_exemption_constants(self):
        # Reads module constants; would PASS standalone (no manifest dependency).
        import orchestrator.check_partial_exemption as m

        assert ".pdf" not in m._RC_OVR_CAVEAT, "_RC_OVR_CAVEAT leaks a .pdf filename"
        assert ".pdf" not in m._BASIS, "_BASIS leaks a .pdf filename"

    def test_no_pdf_in_registry_iras_basis(self):
        # Reads registry specs; would PASS standalone (no manifest dependency).
        import agent.registry as reg

        for key, spec in reg.CHECK_REGISTRY.items():
            basis = getattr(spec, "iras_basis", "") or ""
            assert ".pdf" not in basis, f"CheckSpec {key!r} iras_basis leaks a .pdf: {basis!r}"

    def test_tenth_row_edition_is_tenth_not_slug(self):
        # Anti-slug pin: the file whose former slug said "2nd" must read Tenth Edition.
        target = "knowledge-base/gst-reverse-charge-10th-2026-01-30.pdf"
        rows = [r for r in load_rows() if r.get("local_path") == target]
        assert rows, f"no manifest row for {target}"
        for r in rows:
            assert r.get("edition") == "Tenth Edition", (
                f"row {target} edition {r.get('edition')!r} != 'Tenth Edition'"
            )

    def test_second_row_is_superseded_by_tenth(self):
        target = "knowledge-base/gst-reverse-charge-02nd-2019-08-22-SUPERSEDED.pdf"
        successor = "knowledge-base/gst-reverse-charge-10th-2026-01-30.pdf"
        rows = [r for r in load_rows() if r.get("local_path") == target]
        assert rows, f"no manifest row for {target}"
        for r in rows:
            assert r.get("edition") == "Second Edition", (
                f"row {target} edition {r.get('edition')!r} != 'Second Edition'"
            )
            assert r.get("status") == "SUPERSEDED", (
                f"row {target} status {r.get('status')!r} != 'SUPERSEDED'"
            )
            assert r.get("superseded_by") == successor, (
                f"row {target} superseded_by {r.get('superseded_by')!r} != {successor!r}"
            )


# ---------------------------------------------------------------------------
class TestCollisionA10:
    """A10: within one instrument, no two CURRENT rows may carry DIFFERENT editions.

    The Reverse-Charge pair (Tenth vs Second, whose filenames were formerly
    indistinguishable) is the motivating hazard. The 'How do I prepare my GST return?'
    pair (two files, BOTH Eleventh Edition) must PASS this test — the same edition
    appearing twice is a duplicate, not a collision.
    """

    def test_no_current_edition_collision(self):
        current = [r for r in load_rows() if r.get("status") == "CURRENT"]
        assert current, "no CURRENT rows to check for edition collisions"
        by_instrument: dict[str, set] = {}
        for r in current:
            by_instrument.setdefault(r.get("instrument", ""), set()).add(r.get("edition", ""))
        collisions = {k: v for k, v in by_instrument.items() if len(v) > 1}
        assert not collisions, f"instrument(s) with >1 CURRENT edition: {collisions!r}"


# ---------------------------------------------------------------------------
class TestSupersededTeachingRow:
    """The SUPERSEDED Reverse-Charge row must carry the teaching note explaining WHY
    the wrong copy is a coherent-looking wrong answer: the footnote renumbering
    ("fn 9" in the Second Edition became "fn 12" in the Tenth) is what makes citing
    the superseded copy look internally consistent.
    """

    def test_superseded_rc_row_mentions_fn_renumbering(self):
        target = "knowledge-base/gst-reverse-charge-02nd-2019-08-22-SUPERSEDED.pdf"
        rows = [r for r in load_rows() if r.get("local_path") == target]
        assert rows, f"no manifest row for {target}"
        for r in rows:
            raw = r.get("_raw", "")
            assert "fn 9" in raw, f"SUPERSEDED RC row does not mention 'fn 9': {raw!r}"
            assert "fn 12" in raw, f"SUPERSEDED RC row does not mention 'fn 12': {raw!r}"
