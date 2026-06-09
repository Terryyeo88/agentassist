#!/usr/bin/env python3
"""
Export specialist-facing copies of the Reg 26/27 validation fixtures.

PURPOSE — validation-integrity guard
--------------------------------------
resolution_hint encodes the case-writer's intended resolution direction
(claimable / blocked) and exists only so the test suite can enforce the
two-direction hard_determinable floor.  If the specialist sees it, it
pre-labels the line and recreates circular validation in human form.

This script produces stripped copies with resolution_hint removed
entirely.  The specialist labels the stripped copy; their label is the
ground truth.  resolution_hint is build metadata only and must never
appear in anything handed to the labeller.

Usage
------
    python tests/fixtures/export_specialist_copy.py
    # writes:
    #   tests/fixtures/reg2627-representative-v1-specialist.json
    #   tests/fixtures/reg2627-adversarial-v1-specialist.json

The output files are gitignored (*.specialist.json).  Re-generate them
from source before each labelling session.
"""

import copy
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent

SOURCE_FILES = [
    "reg2627-representative-v1.json",
    "reg2627-adversarial-v1.json",
]

# Fields that encode case-writer intent and must be stripped before the
# specialist sees the fixture.  Extend this list if new construction-intent
# fields are added to future schema versions.
CONSTRUCTION_INTENT_FIELDS = ("resolution_hint",)


def strip_construction_intent(fixture: dict) -> dict:
    """Return a deep copy of fixture with all construction-intent fields removed.

    Removes each field in CONSTRUCTION_INTENT_FIELDS from every line object.
    The key is deleted entirely — it must not appear as null either, because
    a null key still signals the field's existence to an attentive labeller.
    """
    result = copy.deepcopy(fixture)
    for line in result["lines"]:
        for field in CONSTRUCTION_INTENT_FIELDS:
            line.pop(field, None)
    result["_meta"]["specialist_copy"] = True
    result["_meta"]["construction_intent_stripped"] = list(CONSTRUCTION_INTENT_FIELDS)
    return result


def export_specialist_copies(
    fixtures_dir: Path = FIXTURES_DIR,
    source_files: list[str] | None = None,
) -> list[Path]:
    """Strip construction-intent fields and write specialist-facing copies.

    Returns the list of written output paths.
    """
    if source_files is None:
        source_files = SOURCE_FILES
    written: list[Path] = []
    for source_name in source_files:
        src = fixtures_dir / source_name
        with open(src, encoding="utf-8") as f:
            fixture = json.load(f)
        stripped = strip_construction_intent(fixture)
        dest_name = source_name.replace("-v1.json", "-v1-specialist.json")
        dest = fixtures_dir / dest_name
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(stripped, f, indent=2)
        written.append(dest)
    return written


if __name__ == "__main__":
    paths = export_specialist_copies()
    for p in paths:
        print(f"Written: {p}")
