"""tests/test_xero_coverage_labels_binding.py — bind the frontend coverage-label map to reality.

WHY THIS FILE EXISTS (D-11). The Xero coverage panel labels each check id with a friendly
name, mirroring the long-standing precedent at ``report/render.py::_coverage_label`` (a
self-contained map + raw-id fallback, no registry import). A self-contained map is eleven
hardcoded strings, and hardcoded strings drift: the id set could gain a check the map never
learns about, or acquire an id no check has ever emitted. Either way the drift is silent —
the panel just renders a raw id, or a label for a check that does not exist.

So the map is BOUND here, from Python, in two directions:

  * NO INVENTED IDS — every id in the TypeScript map must exist in ``CHECK_REGISTRY``. An id
    that is not a real check cannot survive in the map.
  * NO UNLABELLED ROWS — every check id a REAL ``POST /review/upload`` run emits must be in
    the map, so the panel never falls back to a raw id on the live path. When the backend
    adds a check, this goes red instead of the UI quietly degrading.

The label TEXT is deliberately not bound: the report/render.py precedent already uses friendly
labels that differ from ``CheckSpec.display_name`` (e.g. "Duplicate input-tax claims
(DUP_CLAIM)"). Text is presentation; the ID is the contract.

The raw-id FALLBACK is asserted at source level here (the accessor must fall back to the id
itself rather than an empty string); its BEHAVIOURAL assertion — that an unknown id renders as
the id — lives in ``frontend/src/test/XeroCoveragePanel.test.tsx`` test 6, because only the
browser test can actually execute the TypeScript.

Hermetic: reads the .ts file as text and runs one upload through TestClient. Pure stdlib +
pytest + fastapi.testclient; no anthropic import, no node.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.registry import CHECK_REGISTRY
from api.app import app

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LABELS_TS = _REPO_ROOT / "frontend" / "src" / "lib" / "coverageLabels.ts"
_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)

# Matches the map entries:  "DUP_CLAIM": "Duplicate input-tax claims (DUP_CLAIM)",
_ENTRY_RE = re.compile(r'^\s*"([A-Za-z0-9_]+)"\s*:\s*"(.*?)",?\s*$', re.MULTILINE)


def _map_ids() -> dict[str, str]:
    """Parse the TypeScript label map's id -> label entries."""
    assert _LABELS_TS.is_file(), f"frontend coverage-label map missing: {_LABELS_TS}"
    src = _LABELS_TS.read_text(encoding="utf-8")
    body = src.split("COVERAGE_CHECK_LABELS", 1)[-1]
    body = body.split("{", 1)[-1].split("};", 1)[0]
    entries = dict(_ENTRY_RE.findall(body))
    assert entries, f"no label entries parsed out of {_LABELS_TS}"
    return entries


@pytest.fixture()
def hermetic_engine(tmp_path, monkeypatch):
    """Redirect the engine's PDF dir + bundle audit root to tmp; dummy SAP creds."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")


def test_every_labelled_id_is_a_real_check():
    """No invented ids: the map may only name checks that exist in the registry."""
    unknown = sorted(set(_map_ids()) - set(CHECK_REGISTRY))
    assert not unknown, (
        f"frontend coverage-label map names {unknown} — not in CHECK_REGISTRY. "
        "A label for a check that does not exist is a fabricated backend value."
    )


def test_every_check_a_real_run_emits_is_labelled(hermetic_engine):
    """No unlabelled rows on the live path: a real upload's ids must all be in the map."""
    assert _F5_FIXTURE.is_file(), f"committed Xero F5 fixture missing: {_F5_FIXTURE}"
    client = TestClient(app)
    resp = client.post(
        "/review/upload", files={"file": (_F5_FIXTURE.name, _F5_FIXTURE.read_bytes())}
    )
    assert resp.status_code == 200, resp.text
    emitted = {row["check"] for row in resp.json()["coverage_status"]}
    assert emitted, "the F5 upload emitted no coverage rows — fixture or route changed"

    missing = sorted(emitted - set(_map_ids()))
    assert not missing, (
        f"a real F5 upload emits {missing}, which the frontend label map does not carry — "
        "those rows would render as raw ids. Add them to frontend/src/lib/coverageLabels.ts."
    )


def test_the_accessor_falls_back_to_the_raw_id_not_to_blank():
    """Source-level: the label accessor's fallback must be the id itself, never "".

    The behavioural assertion is XeroCoveragePanel.test.tsx test 6 — only the browser test can
    execute the TypeScript. This one guards the idiom against being edited into a blank.
    """
    src = _LABELS_TS.read_text(encoding="utf-8")
    accessor = src.split("export function coverageLabel", 1)
    assert len(accessor) == 2, "coverageLabel accessor not found in coverageLabels.ts"
    body = accessor[1]
    assert re.search(r"COVERAGE_CHECK_LABELS\[[^\]]+\]\s*(\?\?|\|\|)\s*check", body), (
        "coverageLabel must fall back to the raw `check` id (?? check / || check) so an "
        "unlabelled check renders as its id rather than blank"
    )
