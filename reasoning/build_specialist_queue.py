"""reasoning/build_specialist_queue.py — Compile the specialist review queue.

Selects every indeterminate line from the latest Opus labelling-pass artefact,
joins it to the DRAFT fixture, and writes:
  - exploration-notes/t2.7-measurement/specialist-queue-<UTCdate>.xlsx
  - exploration-notes/t2.7-measurement/specialist-queue-<UTCdate>.md

No API calls, no SAP, no orchestrator imports.

Usage::
    python -m reasoning.build_specialist_queue
    python -m reasoning.build_specialist_queue --artefact <path> --fixture <path>
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT      = Path(__file__).resolve().parent.parent
_ARTEFACT_GLOB  = "labelling-pass-*.json"
_DEFAULT_ART_DIR  = _REPO_ROOT / "exploration-notes" / "t2.7-measurement"
_DEFAULT_FIXTURE  = _REPO_ROOT / "tests" / "fixtures" / "reg2627-labelled-lines.DRAFT.json"
_DEFAULT_OUT_DIR  = _REPO_ROOT / "exploration-notes" / "t2.7-measurement"

_PROVISIONAL_HEADER = (
    "Specialist review queue — provisional Opus labels, validation_status: unvalidated. "
    "Reviewer adjudicates; do not treat as a result until reconciled."
)

# Excel column definitions: (header label, width, data key or callable(row))
# 'row' is the assembled queue row dict.
_COLUMNS: list[tuple[str, int, str]] = [
    # Observable fields
    ("doc_num",              10, "doc_num"),
    ("line_index",           10, "line_index"),
    ("doc_date",             12, "doc_date"),
    ("card_name",            28, "card_name"),
    ("line_description",     30, "line_description"),
    ("line_total",           12, "line_total"),
    ("tax_total",            10, "tax_total"),
    # Model reconciled label
    ("model_disposition",    16, "model_disposition"),
    ("model_category",       22, "model_category"),
    ("confidence",           12, "confidence"),
    ("contested",            10, "contested"),
    ("iras_basis",           40, "iras_basis"),
    ("model_rationale",      48, "model_rationale"),
    # Per-pass detail for disagreement review
    ("pass1_disposition",    18, "pass1_disposition"),
    ("pass1_determinability",22, "pass1_determinability"),
    ("pass1_rationale",      48, "pass1_rationale"),
    ("pass2_disposition",    18, "pass2_disposition"),
    ("pass2_determinability",22, "pass2_determinability"),
    ("pass2_rationale",      48, "pass2_rationale"),
    # Blank specialist columns
    ("specialist_disposition",20, "specialist_disposition"),
    ("specialist_category",  22, "specialist_category"),
    ("specialist_notes",     50, "specialist_notes"),
]

_SPECIALIST_COLS = {"specialist_disposition", "specialist_category", "specialist_notes"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _find_latest_artefact(artefact_dir: Path) -> Path:
    """Return the newest labelling-pass-*.json in artefact_dir (by filename sort)."""
    files = sorted(artefact_dir.glob(_ARTEFACT_GLOB))
    if not files:
        raise FileNotFoundError(
            f"No labelling-pass artefact found in {artefact_dir}. "
            "Run 'python -m reasoning.label_fixture --write-fixture' first."
        )
    return files[-1]


def _load_artefact(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_fixture(path: Path) -> dict[tuple[int, int], dict]:
    """Return fixture lines indexed by (doc_num, line_index)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        (int(ln["doc_num"]), int(ln["line_index"])): ln
        for ln in data["lines"]
    }


# ---------------------------------------------------------------------------
# Queue assembly
# ---------------------------------------------------------------------------

def _safe_parsed(pass_dict: dict) -> dict:
    """Return parsed label or empty dict if the pass errored."""
    return pass_dict.get("parsed") or {}


def assemble_queue(artefact: dict, fixture_index: dict[tuple, dict]) -> list[dict]:
    """Select indeterminate lines and join artefact ↔ fixture.

    Returns one dict per queued line, sorted by model_category then doc_num.
    """
    rows: list[dict] = []
    for art_line in artefact.get("lines", []):
        fl = art_line.get("final_label", {})
        if fl.get("determinability") != "indeterminate":
            continue

        key = (int(art_line["doc_num"]), int(art_line["line_index"]))
        fix_line = fixture_index.get(key, {})
        p1 = _safe_parsed(art_line.get("pass_1", {}))
        p2 = _safe_parsed(art_line.get("pass_2", {}))

        rows.append({
            # Observable fields from fixture
            "doc_num":           key[0],
            "line_index":        key[1],
            "doc_date":          fix_line.get("doc_date", ""),
            "card_name":         fix_line.get("card_name", ""),
            "line_description":  art_line.get("line_description") or fix_line.get("line_description", ""),
            "line_total":        fix_line.get("line_total", ""),
            "tax_total":         fix_line.get("tax_total", ""),
            # Reconciled model label
            "model_disposition":  fl.get("disposition", ""),
            "model_category":     fl.get("category", ""),
            "confidence":         fl.get("confidence", ""),
            "contested":          fl.get("contested", False),
            "iras_basis":         fl.get("iras_basis", ""),
            "model_rationale":    fl.get("rationale", ""),
            # Per-pass detail
            "pass1_disposition":      p1.get("disposition", ""),
            "pass1_determinability":  p1.get("determinability", ""),
            "pass1_rationale":        p1.get("rationale", ""),
            "pass2_disposition":      p2.get("disposition", ""),
            "pass2_determinability":  p2.get("determinability", ""),
            "pass2_rationale":        p2.get("rationale", ""),
            # Blank specialist columns
            "specialist_disposition": "",
            "specialist_category":    "",
            "specialist_notes":       "",
        })

    rows.sort(key=lambda r: (r["model_category"], r["doc_num"], r["line_index"]))
    return rows


# ---------------------------------------------------------------------------
# Excel writer
# ---------------------------------------------------------------------------

def _write_xlsx(rows: list[dict], out_path: Path) -> None:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Specialist queue"

    # Row 1: provisional header (merged across all columns)
    n_cols = len(_COLUMNS)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
    hdr_cell = ws.cell(row=1, column=1, value=_PROVISIONAL_HEADER)
    hdr_cell.font = Font(bold=True, italic=True, color="9C0006")
    hdr_cell.fill = PatternFill("solid", fgColor="FFC7CE")
    hdr_cell.alignment = Alignment(wrap_text=True)
    ws.row_dimensions[1].height = 30

    # Row 2: column headers
    specialist_fill = PatternFill("solid", fgColor="FFEB9C")
    for col_idx, (label, width, _) in enumerate(_COLUMNS, start=1):
        cell = ws.cell(row=2, column=col_idx, value=label)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = width
        if label in _SPECIALIST_COLS:
            cell.fill = specialist_fill

    # Row 3+: data rows
    contested_fill = PatternFill("solid", fgColor="FCE4D6")
    for row_idx, row in enumerate(rows, start=3):
        for col_idx, (label, _, key) in enumerate(_COLUMNS, start=1):
            val = row.get(key, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if label in _SPECIALIST_COLS:
                cell.fill = specialist_fill
        # Highlight contested rows
        if row.get("contested"):
            for col_idx in range(1, n_cols + 1):
                ws.cell(row=row_idx, column=col_idx).fill = contested_fill

    # Freeze header rows
    ws.freeze_panes = "A3"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


# ---------------------------------------------------------------------------
# Markdown summary writer
# ---------------------------------------------------------------------------

def _write_md(
    rows: list[dict],
    by_cat: dict[str, int],
    artefact_path: Path,
    out_path: Path,
) -> None:
    lines = [
        f"# Specialist Review Queue",
        "",
        f"> {_PROVISIONAL_HEADER}",
        "",
        f"**Artefact:** `{artefact_path.name}`  ",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}  ",
        f"**Total queued:** {len(rows)} lines  ",
        "",
        "## Counts by category",
        "",
        "| Category | Lines |",
        "|---|---|",
    ]
    for cat, count in sorted(by_cat.items()):
        lines.append(f"| {cat} | {count} |")

    contested = [r for r in rows if r.get("contested")]
    lines += [
        "",
        f"- **Contested** (both passes disagreed): {len(contested)}",
        f"- **Low-confidence** (all indeterminate lines have confidence=low by construction)",
        "",
        "## Queue",
        "",
        "| doc_num | desc | category | contested | model_disposition | pass1 | pass2 | iras_basis |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        p1 = f"{row['pass1_disposition']}/{row['pass1_determinability']}"
        p2 = f"{row['pass2_disposition']}/{row['pass2_determinability']}"
        lines.append(
            f"| {row['doc_num']} | {row['line_description'][:28]} "
            f"| {row['model_category']} | {row['contested']} "
            f"| {row['model_disposition']} | {p1} | {p2} "
            f"| {row['iras_basis'][:35]} |"
        )

    lines += [
        "",
        "## How to fill in",
        "",
        "For each row in the Excel worksheet, complete three columns:",
        "- **specialist_disposition:** `disallowed` | `claimable` | `unclear`",
        "- **specialist_category:** one of the §6.1.6 Reg 26/27 categories, "
          "`entertainment`, or `n/a`",
        "- **specialist_notes:** one sentence — the IRAS reference or context needed.",
        "",
        "Return the completed worksheet to be reconciled into the promoted fixture.",
        "",
        "_validation_status remains 'unvalidated' until this reconciliation is done._",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def build_queue(
    artefact_path: Path,
    fixture_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Build and write the specialist review queue.

    Returns:
        {
            'queue':       list of row dicts (one per indeterminate line),
            'by_category': Counter of model_category → count,
            'xlsx_path':   Path written,
            'md_path':     Path written,
        }
    """
    artefact     = _load_artefact(artefact_path)
    fixture_idx  = _load_fixture(fixture_path)
    rows         = assemble_queue(artefact, fixture_idx)
    by_cat: dict = dict(Counter(r["model_category"] for r in rows))

    date_str  = datetime.now(timezone.utc).strftime("%Y%m%d")
    xlsx_path = output_dir / f"specialist-queue-{date_str}.xlsx"
    md_path   = output_dir / f"specialist-queue-{date_str}.md"

    _write_xlsx(rows, xlsx_path)
    _write_md(rows, by_cat, artefact_path, md_path)

    return {
        "queue":       rows,
        "by_category": by_cat,
        "xlsx_path":   xlsx_path,
        "md_path":     md_path,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m reasoning.build_specialist_queue",
        description=(
            "Compile indeterminate labelling-pass lines into a specialist review worksheet.\n\n"
            "Reads the latest exploration-notes/t2.7-measurement/labelling-pass-*.json "
            "and tests/fixtures/reg2627-labelled-lines.DRAFT.json by default."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--artefact", type=Path, default=None, metavar="PATH",
        help="Path to a specific labelling-pass JSON (default: newest in the output dir)",
    )
    parser.add_argument(
        "--fixture", type=Path, default=_DEFAULT_FIXTURE, metavar="PATH",
        help=f"DRAFT fixture JSON (default: {_DEFAULT_FIXTURE.relative_to(_REPO_ROOT)})",
    )
    parser.add_argument(
        "--out", type=Path, default=_DEFAULT_OUT_DIR, metavar="DIR",
        help=f"Output directory for .xlsx and .md (default: {_DEFAULT_OUT_DIR.relative_to(_REPO_ROOT)})",
    )
    args = parser.parse_args()

    art_path = args.artefact or _find_latest_artefact(_DEFAULT_ART_DIR)
    result   = build_queue(art_path, args.fixture, args.out)

    n = len(result["queue"])
    print(
        f"{n} lines need specialist sign-off; "
        "validation_status remains 'unvalidated' until returned and reconciled."
    )
    print(f"  xlsx → {result['xlsx_path']}")
    print(f"  md   → {result['md_path']}")
    print(f"  By category: " +
          ", ".join(f"{cat}={cnt}" for cat, cnt in sorted(result["by_category"].items())))
