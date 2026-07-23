"""tests/test_sign_upload_sales.py -- t-demo-prep-xero (D-2026-07-23-demo-prep-xero) FAILING-FIRST.

BUILD ID: t-demo-prep-xero. Written BEFORE the implementation; these MUST fail today for the
RIGHT reason. Phase 2 will extend ``POST /sign/upload`` with a SALES branch:

  After the existing Xero-F5 gate fails (``is_xero_f5_workbook(dest)`` is False), a new
  ``is_xero_sales_invoice_workbook(dest)`` check routes to the sales path:
    * ``_build_xero_sales_reader(dest)`` (the same reader the plain sales upload builds);
    * ``load_client_config("xero_sales_demo")`` with the reviewer stamped via
      ``dataclasses.replace`` (SAME stamp-before-render posture as the F5 branch, so review()'s
      own full-argument Phase-5 render produces the signed-identity working paper);
    * period from ``_derive_extract_period(reader)`` (a sales export carries no period line);
    * ``ReviewInputs(line_source=lambda: [], provider=None, reader=reader,
      sales_line_source=lambda: xero_sales_lines(reader, start, end))`` -- the sales_line_source
      is what makes the engine run the Phase-2b exempt pass and pack + seal its extra artefact;
    * ``review(...)`` with ``persist_artifacts`` default True -> renders the PDF + seals the bundle.
  Response: the SAME 7-key SIGN_UPLOAD_KEYS, with ``source_kind == "xero_sales_signed"`` (a VALUE
  change only). Neither-format uploads still 422. The F5 path stays byte-identical.

THREE-TIMES RULE (prompt + code + THIS test): "an uploaded Xero SALES export can be signed into a
working paper + sealed bundle under the xero_sales_demo config, unvalidated, exempt pass sealed,
without weakening the F5-only-or-422 guard" is pinned in the panel spec, will be enforced in
api/app.py, and is asserted here.

WHY EACH TEST FAILS TODAY (failing-first, per-test docstring): the sales workbook is not the
Xero-F5 format, so today the ``is_xero_f5_workbook`` gate at api/app.py:882-889 rejects it and the
endpoint returns 422 ("Sign-off supports Xero IRAS-F5 exports only ..."). The sales branch does not
exist yet, so T1/T2/T3/T6 (which POST the sales fixture and expect 200) go red on the 422. T4/T5 are
GUARD PINS that pass today AND after.

DOES NOT edit any existing test. In particular Terry's F5-only 422 pin at
tests/test_sign_upload_endpoint.py:140-144 is left UNAMENDED -- T4 here re-pins the SAME spirit
(garbage .xlsx -> 422) from this NEW file so the sales branch is provably not weakening it (verified:
the garbage blob fails the sales detector too, so it stays a 422 after the sales branch lands).

HERMETIC: tmp_path everything; engine PDF dir + audit root + decision store redirected to tmp; the
per-call fresh-audit-subdir trick (seal.run_ts has seconds resolution -> two seals in one second
collide on one read-only bundle dir; sidestepped per-call, NEVER patched in the engine). The
committed sales fixture has ZERO ES33/ESN33 lines, so the exempt pass short-circuits ok/0-candidates
with NO LLM call (pinned by tests/test_xero_exempt_adapter.py:282-288) -- no key, no token, no
network. xero_sales_demo is a file-import (non-SAP) client; NO SAP creds are needed. Pure stdlib +
pytest + fastapi.testclient. No anthropic import. ASCII-safe.
"""
from __future__ import annotations

import itertools
import json
import socket
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from api.app import app, SIGN_UPLOAD_KEYS

# Each engine-running request gets its OWN audit root (seal's run_ts is seconds-resolution; two
# seals in one second collide on one read-only bundle dir). Pre-existing engine property,
# sidestepped per-call -- never patched in the engine. Mirrors
# tests/test_sign_upload_endpoint.py:41-44.
_UPLOAD_SEQ = itertools.count()

_REPO_ROOT = Path(__file__).resolve().parents[1]

_SALES_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
    / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
)
_SALES_FILENAME = "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"

_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_F5_FILENAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Engine PDF dir + audit root + decision store redirected to tmp; dummy SAP creds.

    Mirrors tests/test_sign_upload_endpoint.py:68-76. The dummy SAP creds are harmless here
    (xero_sales_demo is a file-import non-SAP client loaded with check_connectivity=False); they
    are set only to mirror the F5 sign fixture exactly and never reach a network.
    """
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    return tmp_path


def _bump_audit() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"


def _sign_upload(
    client: TestClient,
    reviewer_name: str = "Collin Tan",
    firm_name: Optional[str] = None,
    file_bytes: Optional[bytes] = None,
    filename: str = _SALES_FILENAME,
    file_path: Path = _SALES_FIXTURE,
):
    """POST a workbook to /sign/upload with a fresh audit subdir.

    Mirrors tests/test_sign_upload_endpoint.py:91-106 (multipart reviewer_name/firm_name), but
    defaults to the committed Xero SALES fixture rather than the F5 fixture.
    """
    _bump_audit()
    data = {"reviewer_name": reviewer_name}
    if firm_name is not None:
        data["firm_name"] = firm_name
    body = file_bytes if file_bytes is not None else file_path.read_bytes()
    return client.post(
        "/sign/upload",
        data=data,
        files={"file": (filename, body)},
    )


# -- T1 -- sales sign succeeds: 200, exact key set, real signed artefacts on disk -------------

def test_t1_sales_sign_succeeds(client, hermetic):
    """POST the committed Xero SALES fixture -> 200 signed working paper + sealed bundle.

    FAILS TODAY: 422 ("Sign-off supports Xero IRAS-F5 exports only ...") -- the sales workbook is
    not the F5 format, so today's is_xero_f5_workbook gate rejects it and the sales branch does
    not exist yet.
    """
    assert _SALES_FIXTURE.is_file(), f"committed Xero sales fixture missing: {_SALES_FIXTURE}"
    resp = _sign_upload(client, reviewer_name="Collin Tan", firm_name="")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert set(body.keys()) == set(SIGN_UPLOAD_KEYS)
    assert body["source_kind"] == "xero_sales_signed"
    assert body["reviewer_name"] == "Collin Tan"
    assert body["firm_name"] == ""
    assert body["validation_status"] == "unvalidated"

    wp = Path(body["working_paper_path"])
    assert wp.suffix.lower() == ".pdf"
    assert wp.is_file()

    bundle_dir = Path(body["bundle_dir"])
    assert bundle_dir.is_dir()
    assert (bundle_dir / "manifest.json").is_file()
    assert (bundle_dir / "compile-output.json").is_file()


# -- T2 -- sales sign is hermetic: no key, no network -----------------------------------------

def test_t2_sales_sign_is_hermetic_no_key_no_network(client, hermetic, monkeypatch):
    """The sales sign runs with NO ANTHROPIC key and NO non-loopback network.

    Monkeypatches socket so any NON-LOOPBACK connect raises, + delenvs ANTHROPIC_API_KEY /
    AGENT_LIVE_TRANSPORT. Loopback is deliberately ALLOWED: on Windows, asyncio's Proactor event
    loop creates an internal 127.0.0.1 socketpair (the self-pipe) just to run the TestClient, and
    blocking it kills the ASGI plumbing itself, not a network egress. A real model/API call must
    reach a non-loopback host and trips the guard. (Pattern copied from
    tests/test_dossier_xero_uploads.py test_t4.)

    The committed sales fixture has ZERO ES33/ESN33 lines, so the exempt pass short-circuits
    ok/0-candidates with NO LLM call -- so the sales sign never needs a key or network.

    FAILS TODAY: 422 -- the sales branch does not exist yet (the socket guard is never reached
    because the F5 gate rejects the sales workbook before review() runs).
    """
    _LOOPBACK = {"127.0.0.1", "::1", "localhost"}
    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def _host_of(address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, (bytes, bytearray)):
            host = host.decode(errors="replace")
        return str(host)

    def _guarded_connect(self, address, *a, **k):
        if _host_of(address) in _LOOPBACK:
            return real_connect(self, address, *a, **k)
        raise AssertionError(f"network attempted: {address!r}")

    def _guarded_create_connection(address, *a, **k):
        if _host_of(address) in _LOOPBACK:
            return real_create_connection(address, *a, **k)
        raise AssertionError(f"network attempted: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_LIVE_TRANSPORT", raising=False)

    resp = _sign_upload(client, reviewer_name="Collin Tan", firm_name="")
    assert resp.status_code == 200, resp.text
    assert resp.json()["source_kind"] == "xero_sales_signed"


# -- T3 -- exempt artefact is sealed on the sales sign ----------------------------------------

def test_t3_exempt_artefact_sealed_on_sales_sign(client, hermetic):
    """The sealed bundle carries steps/exempt-supply-candidates.json (clean/ok/0 candidates).

    The sales branch supplies a sales_line_source, so the engine runs the Phase-2b exempt pass
    and the T2.27 extra-stream seal packs its artefact into the bundle (engine/review.py:294-296
    -> seal_bundle(extra_reasoning_artefacts=...) -> steps/exempt-supply-candidates.json, the same
    path pinned by tests/test_exempt_wiring.py:259-263). Over the clean committed fixture (zero
    ES33 lines) the artefact is status "ok" with an empty candidate list.

    FAILS TODAY: 422 before any bundle is sealed (the sales branch does not exist yet).

    GAP NOTE (per the brief): if a future run shows the extra-stream seal does NOT fire for the
    exempt artefact on this branch, the true sealed location must be re-pinned after checking
    engine/review.py's extra_artefacts packing (:294-296) and the seal wiring -- do not silently
    relax this assertion.
    """
    resp = _sign_upload(client, reviewer_name="Collin Tan", firm_name="")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    bundle_dir = Path(body["bundle_dir"])
    artefact_path = bundle_dir / "steps" / "exempt-supply-candidates.json"
    assert artefact_path.is_file(), f"exempt artefact not sealed at {artefact_path}"

    artefact = json.loads(artefact_path.read_text(encoding="utf-8"))
    assert artefact["status"] == "ok"
    assert artefact["candidates"] == []
    assert artefact["candidate_count"] == 0
    assert artefact["provenance"]["validation_status"] == "unvalidated"


# -- T4 -- garbage still 422 (guard pin: passes today AND after) ------------------------------

def test_t4_garbage_xlsx_still_422(client, hermetic):
    """A .xlsx-suffixed garbage blob -> 422 (both detectors self-guard to False).

    GUARD PIN -- passes today AND after the sales branch lands. This intentionally DUPLICATES the
    spirit of Terry's hand-pin at tests/test_sign_upload_endpoint.py:140-144 from this NEW file, so
    the sales-branch addition is provably NOT weakening it: after Phase 2, the blob fails BOTH the
    is_xero_f5_workbook AND the is_xero_sales_invoice_workbook detectors, so a neither-format upload
    stays a 422 client-input error, never a sign.
    """
    resp = _sign_upload(
        client, reviewer_name="Collin Tan", file_bytes=b"not a real workbook",
        filename="garbage.xlsx",
    )
    assert resp.status_code == 422, resp.text


# -- T5 -- F5 sign unchanged (guard pin: passes today AND after) ------------------------------

def test_t5_f5_sign_unchanged(client, hermetic):
    """POST the committed Xero F5 fixture -> 200 with source_kind "xero_f5_signed".

    GUARD PIN -- passes today AND after the sales branch lands: the F5 sign path stays
    byte-identical, so adding the sales branch below the F5 gate does not disturb the F5 outcome.
    """
    assert _F5_FIXTURE.is_file(), f"committed Xero F5 fixture missing: {_F5_FIXTURE}"
    resp = _sign_upload(
        client, reviewer_name="Collin Tan", firm_name="",
        filename=_F5_FILENAME, file_path=_F5_FIXTURE,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["source_kind"] == "xero_f5_signed"


# -- T6 -- default render carries NO candidates section flag (honest response-level pin) ------

def test_t6_default_render_no_candidates_flag(client, hermetic):
    """Over the clean sales fixture with the committed xero_sales_demo config
    (show_ai_candidates default False), the sign response stays validation_status "unvalidated".

    Rendering internals are not inspectable from the endpoint, so this is the HONEST response-level
    pin: the deterministic paper is human-signed regardless, and the AI-candidate layer stays gated
    (frozen flag). NOTE: the #43 banner/suppression behaviour is pinned by the existing B4 report
    tests keyed on show_ai_candidates and is deliberately NOT re-tested here.

    FAILS TODAY: 422 -- the sales branch does not exist yet.
    """
    resp = _sign_upload(client, reviewer_name="Collin Tan", firm_name="")
    assert resp.status_code == 200, resp.text
    assert resp.json()["validation_status"] == "unvalidated"


# -- T7 -- string doc_num candidates RENDER (the INV-INV trap's render-layer cousin) ---------

def test_t7_string_doc_num_candidate_renders_in_ai_section():
    """build_ai_candidates_section tolerates Xero STRING doc_nums (e.g. "INV-9001").

    FOUND BY the pre-capture mechanism verification of the demo centrepiece (added
    mid-build, reported to Terry): the AI-candidates render section coerced doc_num with
    int(), which crashed (ValueError) on the FIRST Xero-sourced candidate ever rendered
    -- SAP candidates carry int doc_nums, Xero candidates carry strings verbatim. The
    fix keeps numerics as ints and passes strings through (same tolerant-doc_num class
    as orchestrator/steps.py's _coerce_doc_num from PR-B). Without it, a sales sign with
    show_ai_candidates=True and a real candidate 500s -- the demo's centrepiece path.

    Value-only render tolerance: no box math, no chain step, no schema change.
    """
    from report.sections import build_ai_candidates_section

    artefact = {
        "status": "ok",
        "disclaimer": "AI-surfaced candidates for human review only.",
        "candidates": [{
            "doc_num": "INV-9001",          # Xero string doc_num, verbatim
            "line_index": 0,
            "doc_date": "2026-04-15",
            "card_name": "Demo Tenant Pte Ltd",
            "line_description": "OFFICE UNIT LEASE Q3",
            "suspected_category": "commercial_property",
            "confidence": "high",
            "phrasing": "Consider reviewing whether this office lease is commercial property",
        }],
    }
    section = build_ai_candidates_section(artefact, show=True)
    assert section.status == "ok" and section.candidate_count == 1
    row = section.candidates[0]
    assert row.doc_num == "INV-9001", "string doc_num must pass through verbatim, not crash"
    # SAP int doc_nums keep working, and numeric strings stay numeric.
    artefact["candidates"][0]["doc_num"] = 958
    assert build_ai_candidates_section(artefact, show=True).candidates[0].doc_num == 958
    artefact["candidates"][0]["doc_num"] = "958"
    assert build_ai_candidates_section(artefact, show=True).candidates[0].doc_num == 958
