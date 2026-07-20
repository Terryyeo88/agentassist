"""tests/test_motorcar_statute_source.py — failing-first guard for
D-2026-07-20-source-motorcar (sourcing the GST (General) Regulations motor-car
provisions into the knowledge-base).

This guard is RED on purpose: the build has not happened yet. It pins the three
outcomes the build must produce:

  1. The GST (General) Regulations PDF is tracked in the corpus at PDF_PATH and its
     bytes hash to PDF_SHA256 (the two corpus-membership tests may already be GREEN
     because the PDF is on disk in the worktree).
  2. A VERBATIM excerpt .md (reg 25(1) definitions, reg 26, reg 27(1)-(8)) lands at
     MD_PATH carrying every anchor in ANCHORS, and contains NO interpretive gloss
     (transcription-only — see the tripwire in TestTranscriptionOnly).
  3. knowledge-base/sources.md flips the GST (General) Regulations row from
     ABSENT/UNVERIFIED to a cloned VERIFIED (status CURRENT) row, and the excerpt .md
     gets its own manifest row whose recorded sha256 self-consistently attests the
     transcription file it describes.

Ruling M3(c): flipping the manifest row makes the two strict=False xfail nodes in
tests/test_citation_manifest.py ("GST (General) Regulations" via TestVerifiedB and
TestTwoCorporaA8) report XPASS. The locked test is NOT edited by this build; a later
rule-author hand-pass removes the now-dead XFAIL_REASONS["GST (General) Regulations"]
entry. This guard never touches that file.

The excerpt is transcription-only: it carries no tax semantics, no interpretation —
just the words of the instrument.

Hermetic: no network, no ``anthropic`` import, no git subprocess. The manifest is
parsed with a tiny LOCAL helper (reimplemented below — NOT imported from
test_citation_manifest, which is locked).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
SOURCES_MD = REPO_ROOT / "knowledge-base" / "sources.md"

PDF_PATH = "knowledge-base/statute/gst-general-regulations-1993-2026ed.pdf"
MD_PATH = "knowledge-base/statute/gst-general-regulations-motorcar.md"
PDF_SHA256 = "d7534d60cede936bcce127e55759b5d72523f5b44835779c23f4a68109253e85"

# Verbatim anchors the excerpt .md must contain, character-for-character. This list
# contains em-dashes (U+2014), a non-breaking hyphen (U+2011), and the curly
# typographic quotes (U+201C/U+201D) the PDF renders around defined lemmas;
# preserve exactly.
ANCHORS = [
    '“motor car” means a motor car which is constructed or adapted',
    'for the carriage of not more than 7 passengers exclusive of the driver',
    'does not exceed 3,000 kilograms but does not include —',
    '(a) a motor car registered before 1 April 1998 as a business service passenger vehicle',
    '(b) a taxi;',
    '(c) a motor car registered as a private car (school transport);',
    '(d) an unused motor car which has not been previously registered under the Road Traffic Act 1961',
    '(e) a motor car supplied to a financial institution',
    '(f) a motor car supplied to or imported by a taxable person for the purposes of being let on hire or sold',
    '(g) a used motor car supplied or imported for the purpose of being let on hire; and',
    '(h) a motor car used for instructional purposes for reward',
    '“chauffeured private hire car” means a motor car that —',
    '“chauffeur service” means —',
    'Disallowance of input tax relating to motor car',
    '26. Input tax incurred by a taxable person in respect of any of the following:',
    '27.—(1) Subject to paragraphs (2) to (8), input tax incurred by a taxable person',
    '(8) In this regulation, a person (A) is a connected person of another person (B)',
    '[2026 Ed.]',
    'version in force from 15/7/2026',
]

# ---------------------------------------------------------------------------
# Tiny LOCAL manifest parser (reimplemented — NOT imported from the locked
# test_citation_manifest). Take lines starting with "|"; the first is the header;
# skip the "---" separator row (cells whose chars are only "-: "); split on "|",
# strip cells, zip with the header into dicts.
# ---------------------------------------------------------------------------
def _cells(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(cells):
    return all(c and set(c) <= set("-: ") for c in cells)


def load_rows():
    """Data rows of sources.md as dicts keyed by the header cells.

    Missing file -> [] so tests fail on explicit assertions rather than erroring.
    """
    if not SOURCES_MD.is_file():
        return []
    lines = [
        ln for ln in SOURCES_MD.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("|")
    ]
    if not lines:
        return []
    header = _cells(lines[0])
    rows = []
    for ln in lines[1:]:
        cells = _cells(ln)
        if _is_separator(cells):
            continue
        d = dict(zip(header, cells))
        d["_cells"] = cells
        rows.append(d)
    return rows


def _rows_where(key: str, value: str):
    return [r for r in load_rows() if r.get(key) == value]


# ---------------------------------------------------------------------------
class TestCorpusMembership:
    """A: the GST (General) Regulations PDF is tracked and hashes as recorded."""

    def test_pdf_file_exists(self):
        assert (REPO_ROOT / PDF_PATH).is_file(), f"expected PDF at {PDF_PATH}"

    def test_pdf_sha256_matches(self):
        digest = hashlib.sha256((REPO_ROOT / PDF_PATH).read_bytes()).hexdigest()
        assert digest == PDF_SHA256, f"PDF sha256 {digest!r} != {PDF_SHA256!r}"


# ---------------------------------------------------------------------------
class TestManifestPdfRow:
    """B: the flipped manifest row for the PDF is present, unique, and VERIFIED."""

    def _row(self):
        rows = _rows_where("local_path", PDF_PATH)
        assert len(rows) == 1, f"expected exactly one row for {PDF_PATH}, got {len(rows)}"
        return rows[0]

    def test_instrument_names_the_regulations(self):
        assert "GST (General) Regulations" in self._row()["instrument"]

    def test_edition(self):
        assert self._row()["edition"] == "[2026 Ed.]"

    def test_status_current(self):
        assert self._row()["status"] == "CURRENT"

    def test_pages(self):
        assert self._row()["pages"] == "227"

    def test_sha256(self):
        assert self._row()["sha256"] == PDF_SHA256

    def test_verified_by(self):
        assert self._row()["verified_by"] == "rule-author"

    def test_verified_on(self):
        assert self._row()["verified_on"] == "2026-07-20"

    def test_verified_from(self):
        assert self._row()["verified_from"] == PDF_PATH

    def test_evidence_records_in_force_stamp_and_provision(self):
        evidence = self._row()["evidence"]
        assert "15/7/2026" in evidence
        assert "25(1)" in evidence


# ---------------------------------------------------------------------------
class TestNoLingeringAbsentRow:
    """C: no ABSENT row survives for the (exactly-named) instrument."""

    def test_no_absent_regulations_row(self):
        exact = [
            r for r in load_rows()
            if r.get("instrument") == "GST (General) Regulations"
        ]
        assert exact, "no row whose instrument is exactly 'GST (General) Regulations'"
        assert all(r.get("local_path") != "ABSENT" for r in exact), (
            "an ABSENT row still lingers for 'GST (General) Regulations'"
        )


# ---------------------------------------------------------------------------
class TestExcerptAnchors:
    """D: the excerpt .md exists and carries every verbatim anchor."""

    def test_excerpt_md_exists(self):
        assert (REPO_ROOT / MD_PATH).is_file(), f"expected excerpt at {MD_PATH}"

    def test_all_anchors_present(self):
        text = (REPO_ROOT / MD_PATH).read_text(encoding="utf-8")
        missing = [a for a in ANCHORS if a not in text]
        assert not missing, f"excerpt is missing {len(missing)} anchor(s): {missing!r}"


# ---------------------------------------------------------------------------
class TestTranscriptionOnly:
    """E: transcription, not interpretation — no gloss phrases."""

    def test_no_gloss_phrases(self):
        lowered = (REPO_ROOT / MD_PATH).read_text(encoding="utf-8").lower()
        assert "this means" not in lowered, "excerpt contains gloss phrase 'this means'"
        assert "in other words" not in lowered, "excerpt contains gloss phrase 'in other words'"


# ---------------------------------------------------------------------------
class TestManifestExcerptRow:
    """F: the excerpt .md has its own row that self-consistently attests it."""

    def _row(self):
        rows = _rows_where("local_path", MD_PATH)
        assert len(rows) == 1, f"expected exactly one row for {MD_PATH}, got {len(rows)}"
        return rows[0]

    def test_verified_from_is_the_pdf(self):
        assert self._row()["verified_from"] == PDF_PATH

    def test_status_current(self):
        assert self._row()["status"] == "CURRENT"

    def test_verified_by(self):
        assert self._row()["verified_by"] == "rule-author"

    def test_sha256_self_consistent(self):
        recorded = self._row()["sha256"]
        actual = hashlib.sha256((REPO_ROOT / MD_PATH).read_bytes()).hexdigest()
        assert recorded == actual, (
            f"manifest sha256 {recorded!r} != excerpt file digest {actual!r}"
        )


# ---------------------------------------------------------------------------
class TestTableWidth:
    """G: every data row is still exactly 13 cells wide."""

    def test_every_row_has_13_cells(self):
        rows = load_rows()
        assert rows, "no data rows found in sources.md"
        for r in rows:
            cells = r["_cells"]
            assert len(cells) == 13, f"row is not 13 cells wide: {cells!r}"
