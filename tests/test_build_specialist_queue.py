"""Tests for reasoning/build_specialist_queue.py — no API, no SAP, fully deterministic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reasoning.build_specialist_queue import (
    _SPECIALIST_COLS,
    assemble_queue,
    build_queue,
    _find_latest_artefact,
    _load_fixture,
)


# ---------------------------------------------------------------------------
# Synthetic test data builders
# ---------------------------------------------------------------------------

def _art_line(
    doc_num: int,
    line_index: int = 0,
    description: str = "TEST LINE",
    determinability: str = "determinable",
    disposition: str = "disallowed",
    category: str = "medical_expenses",
    contested: bool = False,
    confidence: str = "high",
    p1_disposition: str = "disallowed",
    p1_determinability: str = "determinable",
    p2_disposition: str = "disallowed",
    p2_determinability: str = "determinable",
) -> dict:
    return {
        "doc_num": doc_num,
        "line_index": line_index,
        "line_description": description,
        "final_label": {
            "disposition": disposition,
            "determinability": determinability,
            "contested": contested,
            "category": category,
            "iras_basis": f"§6.1.6 item 2, General Guide",
            "rationale": f"Test rationale for {description}.",
            "confidence": confidence,
        },
        "pass_1": {
            "raw": "{}",
            "parsed": {
                "disposition": p1_disposition,
                "determinability": p1_determinability,
                "category": category,
                "iras_basis": "§6.1.6 item 2",
                "rationale": f"Pass 1 rationale for {description}.",
                "confidence": confidence,
            },
            "error": None,
        },
        "pass_2": {
            "raw": "{}",
            "parsed": {
                "disposition": p2_disposition,
                "determinability": p2_determinability,
                "category": category,
                "iras_basis": "§6.1.6 item 2",
                "rationale": f"Pass 2 rationale for {description}.",
                "confidence": confidence,
            },
            "error": None,
        },
        "fixture_mapping": {
            "expected_candidate": disposition == "disallowed",
            "expected_category": category if category != "n/a" else None,
            "determinability": determinability,
            "needs_human_review": True,
        },
    }


def _fix_line(
    doc_num: int,
    line_index: int = 0,
    description: str = "TEST LINE",
    card_name: str = "Test Supplier",
    line_total: float = 500.0,
    tax_total: float = 45.0,
) -> dict:
    return {
        "doc_num": doc_num,
        "line_index": line_index,
        "doc_type": "purchase_invoice",
        "doc_date": "2024-07-01",
        "card_name": card_name,
        "vat_group": "SI",
        "line_description": description,
        "line_total": line_total,
        "tax_total": tax_total,
        "expected_candidate": True,
        "expected_category": "medical_expenses",
        "determinability": "indeterminate",
        "needs_human_review": True,
        "iras_basis": "§6.1.6 item 2",
        "rationale": "Test rationale.",
        "confidence": "low",
        "contested": False,
        "proposed": True,
        "label_source": "opus-4-8",
    }


def _make_artefact(art_lines: list[dict]) -> dict:
    return {
        "_provisional_header": "PROVISIONAL — test",
        "run_metadata": {"model": "claude-opus-4-8", "line_count": len(art_lines)},
        "lines": art_lines,
    }


def _make_fixture_index(fix_lines: list[dict]) -> dict:
    return {(ln["doc_num"], ln["line_index"]): ln for ln in fix_lines}


# ---------------------------------------------------------------------------
# Standard 3-line test fixture:
#   line 1 (doc 1): determinable/disallowed — must NOT be in queue
#   line 2 (doc 2): indeterminate/claimable — MUST be in queue
#   line 3 (doc 3): indeterminate/disallowed + contested — MUST be in queue
# ---------------------------------------------------------------------------

@pytest.fixture
def three_line_artefact() -> dict:
    return _make_artefact([
        _art_line(1, description="OFFICE SUPPLIES",
                  determinability="determinable", disposition="claimable",
                  category="n/a", contested=False, confidence="high"),
        _art_line(2, description="STAFF MED CHECKUP",
                  determinability="indeterminate", disposition="disallowed",
                  category="medical_expenses", contested=False, confidence="low"),
        _art_line(3, description="WORK INJURY TREAT",
                  determinability="indeterminate", disposition="disallowed",
                  category="medical_expenses", contested=True, confidence="low",
                  p1_disposition="disallowed", p1_determinability="determinable",
                  p2_disposition="claimable", p2_determinability="indeterminate"),
    ])


@pytest.fixture
def three_line_fixture_idx() -> dict:
    return _make_fixture_index([
        _fix_line(1, description="OFFICE SUPPLIES", card_name="PopularBooks"),
        _fix_line(2, description="STAFF MED CHECKUP", card_name="Raffles Medical",
                  line_total=890.0, tax_total=80.1),
        _fix_line(3, description="WORK INJURY TREAT", card_name="SingHealth",
                  line_total=680.0, tax_total=61.2),
    ])


# ---------------------------------------------------------------------------
# T1 — Only indeterminate lines are selected
# ---------------------------------------------------------------------------

class TestSelection:

    def test_determinable_line_excluded(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        doc_nums = [r["doc_num"] for r in rows]
        assert 1 not in doc_nums, "Determinable line (doc 1) must not appear in queue"

    def test_indeterminate_lines_included(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        doc_nums = [r["doc_num"] for r in rows]
        assert 2 in doc_nums
        assert 3 in doc_nums

    def test_queue_length_equals_indeterminate_count(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        assert len(rows) == 2

    def test_empty_artefact_gives_empty_queue(self):
        rows = assemble_queue(_make_artefact([]), {})
        assert rows == []

    def test_all_determinable_gives_empty_queue(self, three_line_fixture_idx):
        art = _make_artefact([
            _art_line(1, determinability="determinable"),
            _art_line(2, determinability="determinable"),
        ])
        rows = assemble_queue(art, three_line_fixture_idx)
        assert rows == []


# ---------------------------------------------------------------------------
# T2 — (doc_num, line_index) join correctness
# ---------------------------------------------------------------------------

class TestJoin:

    def test_card_name_joined_from_fixture(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        row2 = next(r for r in rows if r["doc_num"] == 2)
        assert row2["card_name"] == "Raffles Medical"

    def test_line_total_joined_from_fixture(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        row2 = next(r for r in rows if r["doc_num"] == 2)
        assert row2["line_total"] == 890.0

    def test_tax_total_joined_from_fixture(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        row3 = next(r for r in rows if r["doc_num"] == 3)
        assert row3["tax_total"] == 61.2

    def test_line_description_from_artefact(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        row2 = next(r for r in rows if r["doc_num"] == 2)
        assert row2["line_description"] == "STAFF MED CHECKUP"

    def test_missing_fixture_line_gives_empty_strings(self):
        art = _make_artefact([_art_line(99, determinability="indeterminate")])
        rows = assemble_queue(art, {})   # empty fixture index
        assert len(rows) == 1
        assert rows[0]["card_name"] == ""
        assert rows[0]["line_total"] == ""

    def test_doc_num_and_line_index_correct(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        for row in rows:
            assert isinstance(row["doc_num"], int)
            assert isinstance(row["line_index"], int)


# ---------------------------------------------------------------------------
# T3 — Blank specialist columns present
# ---------------------------------------------------------------------------

class TestSpecialistColumns:

    def test_specialist_disposition_present_and_blank(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        for row in rows:
            assert "specialist_disposition" in row
            assert row["specialist_disposition"] == ""

    def test_specialist_category_present_and_blank(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        for row in rows:
            assert "specialist_category" in row
            assert row["specialist_category"] == ""

    def test_specialist_notes_present_and_blank(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        for row in rows:
            assert "specialist_notes" in row
            assert row["specialist_notes"] == ""

    def test_specialist_cols_constant_matches_row_keys(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        for row in rows:
            for col in _SPECIALIST_COLS:
                assert col in row, f"Specialist column {col!r} missing from row"


# ---------------------------------------------------------------------------
# T4 — Contested and confidence appear as display columns
# ---------------------------------------------------------------------------

class TestDisplayColumns:

    def test_contested_flag_present(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        for row in rows:
            assert "contested" in row

    def test_contested_true_for_disagreement_line(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        row3 = next(r for r in rows if r["doc_num"] == 3)
        assert row3["contested"] is True

    def test_contested_false_for_agreement_line(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        row2 = next(r for r in rows if r["doc_num"] == 2)
        assert row2["contested"] is False

    def test_confidence_present(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        for row in rows:
            assert "confidence" in row
            assert row["confidence"] in ("low", "medium", "high")

    def test_both_pass_dispositions_present(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        row3 = next(r for r in rows if r["doc_num"] == 3)
        assert row3["pass1_disposition"] == "disallowed"
        assert row3["pass2_disposition"] == "claimable"

    def test_both_pass_determinabilities_present(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        row3 = next(r for r in rows if r["doc_num"] == 3)
        assert row3["pass1_determinability"] == "determinable"
        assert row3["pass2_determinability"] == "indeterminate"

    def test_iras_basis_present(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        for row in rows:
            assert "iras_basis" in row
            assert row["iras_basis"] != ""

    def test_model_rationale_present(self, three_line_artefact, three_line_fixture_idx):
        rows = assemble_queue(three_line_artefact, three_line_fixture_idx)
        for row in rows:
            assert "model_rationale" in row


# ---------------------------------------------------------------------------
# T5 — Sorting: by model_category then doc_num
# ---------------------------------------------------------------------------

class TestSorting:

    def test_sorted_by_category_then_doc_num(self):
        art = _make_artefact([
            _art_line(10, determinability="indeterminate", category="other_disallowed"),
            _art_line(5,  determinability="indeterminate", category="club_subscriptions"),
            _art_line(7,  determinability="indeterminate", category="club_subscriptions"),
        ])
        fix = _make_fixture_index([_fix_line(i) for i in [5, 7, 10]])
        rows = assemble_queue(art, fix)
        cats = [r["model_category"] for r in rows]
        assert cats == ["club_subscriptions", "club_subscriptions", "other_disallowed"]
        doc_nums = [r["doc_num"] for r in [r for r in rows if r["model_category"] == "club_subscriptions"]]
        assert doc_nums == [5, 7]


# ---------------------------------------------------------------------------
# T6 — build_queue integration (writes xlsx + md)
# ---------------------------------------------------------------------------

class TestBuildQueue:

    @pytest.fixture
    def tmp_artefact(self, tmp_path):
        art = _make_artefact([
            _art_line(1, determinability="determinable", category="n/a"),
            _art_line(2, determinability="indeterminate", category="medical_expenses",
                      description="STAFF MED CHECKUP", contested=False),
            _art_line(3, determinability="indeterminate", category="club_subscriptions",
                      description="GOLF CLIENT GUEST", contested=True,
                      p1_disposition="disallowed", p1_determinability="determinable",
                      p2_disposition="disallowed", p2_determinability="indeterminate"),
        ])
        p = tmp_path / "labelling-pass-20260101.json"
        p.write_text(json.dumps(art), encoding="utf-8")
        return p

    @pytest.fixture
    def tmp_fixture(self, tmp_path):
        data = {
            "_meta": {},
            "lines": [
                _fix_line(1, description="OFFICE SUPPLIES"),
                _fix_line(2, description="STAFF MED CHECKUP", card_name="Raffles"),
                _fix_line(3, description="GOLF CLIENT GUEST",  card_name="Sentosa GC"),
            ],
        }
        p = tmp_path / "reg2627-labelled-lines.DRAFT.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_queue_has_two_indeterminate_lines(self, tmp_artefact, tmp_fixture, tmp_path):
        result = build_queue(tmp_artefact, tmp_fixture, tmp_path)
        assert len(result["queue"]) == 2

    def test_xlsx_written(self, tmp_artefact, tmp_fixture, tmp_path):
        result = build_queue(tmp_artefact, tmp_fixture, tmp_path)
        assert result["xlsx_path"].exists()
        assert result["xlsx_path"].suffix == ".xlsx"

    def test_md_written(self, tmp_artefact, tmp_fixture, tmp_path):
        result = build_queue(tmp_artefact, tmp_fixture, tmp_path)
        assert result["md_path"].exists()
        md = result["md_path"].read_text(encoding="utf-8")
        assert "unvalidated" in md.lower()
        assert "Specialist" in md

    def test_by_category_counts(self, tmp_artefact, tmp_fixture, tmp_path):
        result = build_queue(tmp_artefact, tmp_fixture, tmp_path)
        assert result["by_category"]["medical_expenses"] == 1
        assert result["by_category"]["club_subscriptions"] == 1

    def test_xlsx_has_correct_row_count(self, tmp_artefact, tmp_fixture, tmp_path):
        import openpyxl
        result = build_queue(tmp_artefact, tmp_fixture, tmp_path)
        wb = openpyxl.load_workbook(result["xlsx_path"])
        ws = wb.active
        # Row 1 = header text, row 2 = col headers, rows 3+ = data
        data_rows = ws.max_row - 2
        assert data_rows == 2

    def test_xlsx_provisional_header_in_row1(self, tmp_artefact, tmp_fixture, tmp_path):
        import openpyxl
        result = build_queue(tmp_artefact, tmp_fixture, tmp_path)
        wb = openpyxl.load_workbook(result["xlsx_path"])
        ws = wb.active
        assert "unvalidated" in str(ws.cell(row=1, column=1).value).lower()

    def test_xlsx_specialist_cols_in_headers(self, tmp_artefact, tmp_fixture, tmp_path):
        import openpyxl
        result = build_queue(tmp_artefact, tmp_fixture, tmp_path)
        wb = openpyxl.load_workbook(result["xlsx_path"])
        ws = wb.active
        headers = [ws.cell(row=2, column=c).value for c in range(1, ws.max_column + 1)]
        for col in _SPECIALIST_COLS:
            assert col in headers, f"Specialist column {col!r} not in xlsx headers"

    def test_md_contains_provisional_header(self, tmp_artefact, tmp_fixture, tmp_path):
        result = build_queue(tmp_artefact, tmp_fixture, tmp_path)
        md = result["md_path"].read_text(encoding="utf-8")
        assert "provisional" in md.lower()

    def test_determinable_line_absent_from_xlsx(self, tmp_artefact, tmp_fixture, tmp_path):
        import openpyxl
        result = build_queue(tmp_artefact, tmp_fixture, tmp_path)
        wb = openpyxl.load_workbook(result["xlsx_path"])
        ws = wb.active
        all_values = " ".join(
            str(ws.cell(row=r, column=c).value or "")
            for r in range(3, ws.max_row + 1)
            for c in range(1, ws.max_column + 1)
        )
        assert "OFFICE SUPPLIES" not in all_values


# ---------------------------------------------------------------------------
# T7 — _find_latest_artefact
# ---------------------------------------------------------------------------

class TestFindLatestArtefact:

    def test_finds_newest_by_filename(self, tmp_path):
        (tmp_path / "labelling-pass-20260101.json").write_text("{}", encoding="utf-8")
        (tmp_path / "labelling-pass-20260603.json").write_text("{}", encoding="utf-8")
        latest = _find_latest_artefact(tmp_path)
        assert latest.name == "labelling-pass-20260603.json"

    def test_raises_when_no_artefact(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No labelling-pass artefact"):
            _find_latest_artefact(tmp_path)

    def test_single_file_returned(self, tmp_path):
        p = tmp_path / "labelling-pass-20260101.json"
        p.write_text("{}", encoding="utf-8")
        assert _find_latest_artefact(tmp_path) == p


# ---------------------------------------------------------------------------
# T8 — Dependency invariants
# ---------------------------------------------------------------------------

class TestInvariants:

    def _source(self) -> str:
        import reasoning.build_specialist_queue as mod
        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_no_orchestrator_import(self):
        src = self._source()
        assert "from orchestrator" not in src
        assert "import orchestrator" not in src

    def test_no_anthropic_import(self):
        src = self._source()
        assert "import anthropic" not in src
        assert "from anthropic" not in src

    def test_no_audit_bundle_import(self):
        src = self._source()
        assert "from audit_bundle" not in src
        assert "import audit_bundle" not in src
