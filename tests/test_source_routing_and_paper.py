"""
tests/test_source_routing_and_paper.py — Slice D: D4, D6 and D8.

D-2026-09-21-unmapped-codes (PROPOSED).

D4 — THE GUARD IS SOURCE-AGNOSTIC. R-2 is a property of the box projection, not of a
reader. The same synthetic unmapped code on the XERO F5 path must blank the boxes exactly
as it does on the extract path. The Xero fixture carries no unrecognised code of its own
(measured: SR/ZR/TX only), so the trigger has to be injected through the CONFIG — the same
door a real mis-declaration would come through.

D6 — R-3 / G-5: THE CHOSEN SOURCE GOVERNS. The extract branch used to be reachable purely
by elimination: a file matching neither Xero detector was reviewed under `extract_demo` —
someone else's config, someone else's rate — with nothing on screen saying so. A stated
source that disagrees with the file is now refused, naming both sides mechanically.

D8 — THE PAPER, BOTH DIRECTIONS. An incomplete box shows NO figure and says why; a genuine
0.00 still shows 0.00. This is the capability-not-emptiness distinction (#48) applied to a
new cause, and both directions are pinned because getting only one right is the bug.

APPEND-ONLY BOUNDARY: NEW file. No existing test file is modified.
Hermetic: no network, no anthropic, no live SAP/Xero. SAP off, dummy creds only.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import itertools
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

import audit_bundle.seal as _seal  # noqa: E402
from api.app import app  # noqa: E402
from config.loader import load_client_config  # noqa: E402
from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period  # noqa: E402
from orchestrator.chain import run_chain  # noqa: E402

_XERO_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-demo-2026Q2"
_XERO_F5 = _XERO_DIR / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_XERO_NAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_FROZEN = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"

_SEQ = itertools.count()


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    import agent.decision_store as _ds
    import agent.review_store as _rs
    import audit_bundle.seal as _sl
    import engine.review as _rev

    monkeypatch.setattr(_rev, "_REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(_sl, "_AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr(_ds, "_DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setattr(_rs, "_REVIEWS_ROOT", tmp_path / "reviews", raising=False)
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    return tmp_path


def _bump() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_SEQ)}"


@pytest.fixture(scope="module")
def synth_xlsx(tmp_path_factory) -> Path:
    synth = _load("routing_synth", "tests/synth_extract_export.py")
    return synth.export_xlsx(_FROZEN, tmp_path_factory.mktemp("d6") / "extract.xlsx")


# ══ D4 — the guard is a property of the projection, not of a reader ═════════════════


class TestD4SourceAgnostic:

    def _xero_run(self, mappings: dict | None = None):
        cfg = load_client_config("xero_demo", check_connectivity=False)
        if mappings is not None:
            cfg = dataclasses.replace(cfg, tax_code_mappings=mappings)
        reader = XeroF5ChainReader(_XERO_F5)
        return run_chain(cfg, parse_review_period(_XERO_F5), reader=reader)[0]

    def test_the_xero_fixture_has_no_unrecognised_code_of_its_own(self):
        """The control. If this ever fails, the D5 byte-identity pins are measuring the
        wrong thing."""
        out = self._xero_run()
        assert out["calculate"]["anomalies"] == []
        assert "box_completeness" not in out

    def test_an_unmapped_code_blanks_the_xero_boxes_the_same_way(self):
        """SR is the Xero F5 export's own standard-rated code. Declared onto a target no
        box recognises, it must produce the SAME incomplete-box behaviour the extract path
        produces — same key, same blanking, same finding."""
        cfg = load_client_config("xero_demo", check_connectivity=False)
        out = self._xero_run({**cfg.tax_code_mappings, "SR": "ZZ_UNRECOGNISED"})
        bc = out.get("box_completeness")
        assert bc is not None and bc["status"] == "incomplete"
        assert set(bc["blanked_boxes"]) == set(out["calculate"]["boxes"])
        codes = {c["code"]: c for c in bc["excluded_codes"]}
        assert "SR" in codes and codes["SR"]["line_count"] > 0
        assert codes["SR"]["declared_as"] == "ZZ_UNRECOGNISED"
        assert [i for i in out["detect"]["issues"] if i["error_code"] == "UNMAPPED_TAX_CODE"]

    def test_the_raw_figures_still_reach_the_seal_on_the_xero_path(self):
        cfg = load_client_config("xero_demo", check_connectivity=False)
        out = self._xero_run({**cfg.tax_code_mappings, "SR": "ZZ_UNRECOGNISED"})
        assert isinstance(out["calculate"]["boxes"]["box_1_standard_rated_sales"], float)


# ══ D6 — R-3: the chosen source governs ═════════════════════════════════════════════


class TestD6Routing:

    def test_a_non_xero_file_under_a_xero_source_is_refused(self, client, hermetic, synth_xlsx):
        _bump()
        r = client.post(
            "/review/upload",
            files={"file": ("extract.xlsx", synth_xlsx.read_bytes())},
            data={"source": "xero"},
        )
        assert r.status_code == 422
        detail = r.json()["detail"]
        # Mechanical: what was expected, what arrived. No advice, no tax claim.
        assert "Expected a Xero export" in detail
        assert "extract.xlsx" in detail

    def test_a_xero_file_under_the_extract_source_is_refused(self, client, hermetic):
        _bump()
        r = client.post(
            "/review/upload",
            files={"file": (_XERO_NAME, _XERO_F5.read_bytes())},
            data={"source": "extract"},
        )
        assert r.status_code == 422
        assert "Expected a general extract workbook" in r.json()["detail"]
        assert "xero_f5" in r.json()["detail"]

    def test_the_extract_branch_is_not_reachable_by_elimination(self, client, hermetic, synth_xlsx):
        """G-5 itself: with no source stated, a file that is not a Xero export no longer
        falls through to someone else's config — it is refused."""
        _bump()
        r = client.post("/review/upload", files={"file": ("extract.xlsx", synth_xlsx.read_bytes())})
        assert r.status_code == 422
        assert "no source was stated" in r.json()["detail"]

    def test_stating_the_source_makes_the_extract_review_run(self, client, hermetic, synth_xlsx):
        _bump()
        r = client.post(
            "/review/upload",
            files={"file": ("extract.xlsx", synth_xlsx.read_bytes())},
            data={"source": "extract"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["source_kind"] == "extract_review"

    def test_an_unknown_source_word_is_refused(self, client, hermetic, synth_xlsx):
        _bump()
        r = client.post(
            "/review/upload",
            files={"file": ("extract.xlsx", synth_xlsx.read_bytes())},
            data={"source": "quickbooks"},
        )
        assert r.status_code == 422
        assert "Unknown source" in r.json()["detail"]

    def test_a_xero_upload_is_unchanged_with_and_without_the_source_field(self, client, hermetic):
        """The Xero path routes itself by POSITIVE detection, as before: stating the source
        must not change a single byte of the response."""
        import hashlib, json

        _bump()
        a = client.post("/review/upload", files={"file": (_XERO_NAME, _XERO_F5.read_bytes())})
        _bump()
        b = client.post(
            "/review/upload",
            files={"file": (_XERO_NAME, _XERO_F5.read_bytes())},
            data={"source": "xero"},
        )
        assert a.status_code == b.status_code == 200
        dig = lambda o: hashlib.sha256(
            json.dumps(o, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert dig(a.json()) == dig(b.json())


# ══ D8 — the paper, both directions ═════════════════════════════════════════════════


class TestD8ThePaper:

    def test_incomplete_box_shows_no_figure_and_says_why(self):
        from report.render import _INCOMPLETE_MARKER, _box_value_flowables
        from report.sections import F5BoxAttribution

        row = F5BoxAttribution(
            box_name="box_5_taxable_purchases",
            box_value=11400.0,          # a REAL partial figure — must not be rendered
            vat_groups=[],
            status="incomplete",
            exclusion_reason="3 line(s) carrying unrecognised tax code(s) 'SO' were excluded.",
        )
        rendered = " ".join(str(getattr(f, "text", f)) for f in _box_value_flowables(row))
        assert _INCOMPLETE_MARKER in rendered
        assert "SO" in rendered
        assert "11,400" not in rendered and "11400" not in rendered

    def test_a_genuine_zero_still_shows_zero(self):
        """The other direction, and the one that is easy to break: a box the source COULD
        populate but for which the period simply had nothing is a real 0.00, not a gap."""
        from report.render import _INCOMPLETE_MARKER, _box_value_flowables
        from report.sections import F5BoxAttribution

        row = F5BoxAttribution(
            box_name="box_3_exempt_sales", box_value=0.0, vat_groups=[], status="available"
        )
        rendered = " ".join(str(getattr(f, "text", f)) for f in _box_value_flowables(row))
        assert "0.00" in rendered
        assert _INCOMPLETE_MARKER not in rendered

    def test_an_absent_box_is_still_an_em_dash_never_a_fabricated_zero(self):
        from report.render import _box_value_flowables
        from report.sections import F5BoxAttribution

        row = F5BoxAttribution(
            box_name="box_3_exempt_sales", box_value=None, vat_groups=[], status="available"
        )
        rendered = " ".join(str(getattr(f, "text", f)) for f in _box_value_flowables(row))
        assert "0.00" not in rendered
