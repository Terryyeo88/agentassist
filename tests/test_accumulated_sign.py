"""tests/test_accumulated_sign.py -- t-accumulated-sign (D-2026-07-23-accumulated-sign)
FAILING-FIRST.

BUILD ID: t-accumulated-sign. Written BEFORE the implementation exists; every test below
MUST fail today for the RIGHT reason. Phase 2 will build:

  1. BYTES RETENTION (Terry R1): ``_attach_review_slice`` additionally saves the uploaded
     primary bytes to ``reviews/<review_id>/uploads/<sha256>.xlsx`` via NEW review_store
     helpers ``save_upload_bytes(review_id, sha256, data)`` / ``upload_bytes_path(review_id,
     sha256)``; an F5 upload's ledger companion (when present) saves as
     ``uploads/<sha256>.ledger.xlsx``. Upload responses stay BYTE-IDENTICAL (no new keys).

  2. NEW ``POST /review-session/{review_id}/sign`` (JSON: reviewer_name required non-empty,
     firm_name optional str). Refusals: 404 unknown review; 422 no slices; 422 no ACTIVE F5
     slice (R2 -- message names the reason: the F5 export carries the return figures); 422 if
     any ACTIVE slice's retained bytes file is ABSENT (R1 -- LOUD "predates byte retention"
     + "re-attach"); 422 if two ACTIVE slices carry non-None periods that DISAGREE (R3 --
     message surfaces BOTH periods, never a silent union); 422 empty reviewer. Success:
     re-runs review() over the PRIMARY (F5) slice's retained bytes (with its retained ledger
     when present) under xero_demo with the reviewer stamped; renders ONE accumulated working
     paper (primary's boxes/structure/period; NON-primary slices' findings come from the #136
     STORED serialized rows -- R6 -- as per-slice subsections with visible provenance:
     source_kind + short sha + uploaded_at); seals a bundle whose manifest additionally covers
     an ``accumulated-review.json`` artefact via a NEW NEUTRAL seal seam (NOT
     extra_reasoning_artefacts -- so NO ``llm`` block on it in the manifest); appends a
     type=="signed" record to the session JSONL; GET /review-session/{id} gains an additive
     "signed" list. Response (new route): {source_kind: "review_session_signed", review_id,
     reviewer_name, firm_name, working_paper_path, bundle_dir, primary_source_kind,
     primary_sha256, slices_signed (int), validation_status: "unvalidated", disclaimer}.

  3. BOX-ISOLATION ABSOLUTE: the accumulated bundle's compile-output.json carries
     calculate.boxes byte-identical to a solo POST /sign/upload over the SAME F5 bytes.

THREE-TIMES RULE (prompt + code + THIS test): "an explicit review session can be signed into
ONE accumulated working paper + sealed bundle -- primary F5 re-run, non-primary slices rendered
from STORED rows with visible provenance, forward-only bytes retention, F5-required, no silent
period union, box-isolation absolute, neutral (non-LLM) accumulated-review artefact" is pinned in
the panel spec, will be enforced in agent/review_store.py + api/app.py + the render, and is
asserted here.

WHY EACH TEST FAILS TODAY (per-test docstring). In THIS worktree t-review-accumulation is
already MERGED: POST /review-session, upload-with-review_id slice attachment, and GET
/review-session/{id} all WORK. What is ABSENT (Phase 2) and drives the red:
  * ``POST /review-session/{review_id}/sign`` does NOT exist -> 404 (route absent);
  * ``review_store.save_upload_bytes`` / ``upload_bytes_path`` do NOT exist -> AttributeError;
  * uploads do NOT retain bytes (no reviews/<id>/uploads/ dir);
  * no accumulated-review.json / signed record / "signed" list.

HERMETIC: tmp_path everything; engine PDF dir + audit root + decision store + review store all
redirected to tmp (mirrors tests/test_review_accumulation.py:96-113). Per-sign fresh _AUDIT_ROOT
subdir (seal.run_ts has microsecond resolution now, but the counter bump mirrors the established
per-call sidestep and keeps two seals in one test isolated). xero_demo / xero_sales_demo are
file-import (non-SAP) clients loaded with check_connectivity=False; dummy SAP creds are set
(harmless). No anthropic import; SAP off, no tokens, no network.

GAP REPORTED (honest deviation from the brief): the brief asked for ``pypdf`` to extract PDF
text. ``pypdf`` is NOT in requirements.txt and no existing test imports it; the installed,
requirements-pinned, already-used PDF text extractor is ``pdfplumber`` (tests/test_t58_mock_engine.py:21,
tests/test_documents_legibility_e2e.py:28). To keep these tests SKIP-FREE and failing for the
RIGHT reason (the sign route being 404 -- never a missing-dependency ImportError), the PDF-text
tests (T6/T7) use ``pdfplumber`` instead of ``pypdf``. Flagged, not silently swapped.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from audit_bundle.verify import verify_bundle
from api.app import app

# Each engine-running request gets its OWN audit subdir (mirrors the per-call sidestep in
# tests/test_review_accumulation.py:67-68,116-117 and tests/test_sign_upload_endpoint.py:41-44).
_SIGN_SEQ = itertools.count()

_REPO_ROOT = Path(__file__).resolve().parents[1]

_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_F5_NAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

_SALES_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
    / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
)
_SALES_NAME = "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"

# The EXACT new-route response contract (Phase 2). Pinned as a literal here (three-times rule).
ACCUMULATED_SIGN_KEYS = {
    "source_kind", "review_id", "reviewer_name", "firm_name",
    "working_paper_path", "bundle_dir", "primary_source_kind",
    "primary_sha256", "slices_signed", "validation_status", "disclaimer",
}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Engine PDF dir + audit root + decision store + review store all redirected to tmp.

    Mirrors tests/test_review_accumulation.py:96-113 exactly (the review-store redirect keeps
    the accumulation store hermetic; dummy SAP creds are harmless for the non-SAP demo clients).
    """
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    import agent.review_store as _rs
    monkeypatch.setattr(_rs, "_REVIEWS_ROOT", tmp_path / "reviews", raising=False)
    return tmp_path


def _bump_audit() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_SIGN_SEQ)}"


def _new_review(label: str = "") -> str:
    """Mint a real session via the (existing, merged) store -- POST /review-session also works
    in this worktree, but minting directly isolates the thing under test (the SIGN route)."""
    import agent.review_store as rs
    return rs.create_review(label)["review_id"]


def _upload_resp(client: TestClient, file_bytes: bytes, name: str, review_id: Optional[str] = None):
    """POST /review/upload with a fresh audit subdir; returns the raw Response (no assert)."""
    _bump_audit()
    data = {"review_id": review_id} if review_id is not None else None
    return client.post("/review/upload", files={"file": (name, file_bytes)}, data=data)


def _post_upload(client: TestClient, file_bytes: bytes, name: str, review_id: Optional[str] = None) -> dict:
    resp = _upload_resp(client, file_bytes, name, review_id=review_id)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _accumulated_sign(
    client: TestClient, rid: str, reviewer_name: str = "Collin Tan", firm_name: Optional[str] = None
):
    """POST the NEW /review-session/{id}/sign route with a fresh audit subdir (JSON body)."""
    _bump_audit()
    payload: dict = {"reviewer_name": reviewer_name}
    if firm_name is not None:
        payload["firm_name"] = firm_name
    return client.post(f"/review-session/{rid}/sign", json=payload)


def _solo_sign_upload(client: TestClient, file_bytes: bytes, name: str, reviewer_name: str = "Collin Tan"):
    """POST /sign/upload (existing B4 route) with a fresh audit subdir -- the box-isolation control."""
    _bump_audit()
    return client.post(
        "/sign/upload",
        data={"reviewer_name": reviewer_name},
        files={"file": (name, file_bytes)},
    )


def _pdf_text(pdf_path: Path) -> str:
    """Extract all text from a PDF. Uses pdfplumber (installed / requirements-pinned) -- see the
    module docstring GAP note on the pypdf->pdfplumber deviation."""
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _walk_dicts(obj):
    """Yield every dict in a nested JSON tree (schema-tolerant provenance probe for T7)."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- T1 -- happy path: create + F5 + sales -> ONE accumulated signed paper + sealed bundle -----

def test_t1_accumulated_sign_happy_path(client, hermetic):
    """A session with an F5 + a sales slice signs into ONE accumulated working paper + bundle.

    Pins the whole new surface: the exact 11-key response, source_kind "review_session_signed",
    primary_source_kind "xero_f5_upload", slices_signed == 2, a real .pdf working paper, a bundle
    carrying manifest.json + compile-output.json + accumulated-review.json, a clean
    verify_bundle (mirrors tests/test_audit_seal_verify.py:137-140), and the NEUTRAL-SEAM pin:
    the manifest artefact entry for accumulated-review.json carries NO "llm" key (it is sealed via
    a neutral seam, not the extra_reasoning_artefacts LLM path).

    FAILS TODAY: POST /review-session/{id}/sign does not exist -> 404 (route absent); the first
    assertion (200) is red.
    """
    assert _F5_FIXTURE.is_file(), f"committed Xero F5 fixture missing: {_F5_FIXTURE}"
    assert _SALES_FIXTURE.is_file(), f"committed Xero sales fixture missing: {_SALES_FIXTURE}"

    rid = _new_review("accumulated")
    f5 = _F5_FIXTURE.read_bytes()
    _post_upload(client, f5, _F5_NAME, review_id=rid)
    _post_upload(client, _SALES_FIXTURE.read_bytes(), _SALES_NAME, review_id=rid)

    resp = _accumulated_sign(client, rid, reviewer_name="Collin Tan")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert set(body.keys()) == ACCUMULATED_SIGN_KEYS, (
        f"accumulated-sign response key set mismatch: {sorted(body.keys())}"
    )
    assert body["source_kind"] == "review_session_signed"
    assert body["review_id"] == rid
    assert body["reviewer_name"] == "Collin Tan"
    assert body["validation_status"] == "unvalidated"
    assert body["primary_source_kind"] == "xero_f5_upload"
    assert body["primary_sha256"] == _sha(f5), "primary_sha256 is the F5 slice's file sha256"
    assert body["slices_signed"] == 2, "both active slices (F5 + sales) are covered by the sign"

    wp = Path(body["working_paper_path"])
    assert wp.suffix.lower() == ".pdf" and wp.is_file()

    bundle_dir = Path(body["bundle_dir"])
    assert bundle_dir.is_dir()
    assert (bundle_dir / "manifest.json").is_file()
    assert (bundle_dir / "compile-output.json").is_file()
    assert (bundle_dir / "accumulated-review.json").is_file(), (
        "the accumulated view must be sealed as accumulated-review.json"
    )

    ok, problems = verify_bundle(bundle_dir)
    assert ok is True, f"the accumulated bundle must verify clean; problems: {problems}"
    assert problems == []

    # NEUTRAL-SEAM pin: accumulated-review.json is NOT an LLM/reasoning artefact, so its
    # manifest entry carries no "llm" block (unlike steps/*-candidates.json).
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    entry = next(
        (a for a in manifest["artefacts"] if a["path"] == "accumulated-review.json"), None
    )
    assert entry is not None, "accumulated-review.json must be covered by the manifest"
    assert "llm" not in entry, (
        "accumulated-review.json is sealed via the NEUTRAL seam -- it must carry no llm block"
    )


# -- T2 -- box-isolation absolute: accumulated primary boxes == solo /sign/upload boxes --------

def test_t2_box_isolation_primary_boxes_byte_identical(client, hermetic):
    """The accumulated bundle's calculate.boxes equal a solo /sign/upload over the SAME F5 bytes.

    The accumulated paper re-runs review() over the F5 primary's retained bytes under xero_demo --
    exactly what a solo POST /sign/upload does -- so the deterministic F5 boxes must be
    byte-identical (box-isolation: the accumulation layer NEVER perturbs the primary chain).

    FAILS TODAY: the accumulated sign is a 404 (route absent), so there is no accumulated bundle
    to read; the solo /sign/upload half already works.
    """
    f5 = _F5_FIXTURE.read_bytes()

    rid = _new_review()
    _post_upload(client, f5, _F5_NAME, review_id=rid)
    _post_upload(client, _SALES_FIXTURE.read_bytes(), _SALES_NAME, review_id=rid)
    acc = _accumulated_sign(client, rid, reviewer_name="Collin Tan")
    assert acc.status_code == 200, acc.text
    acc_bundle = Path(acc.json()["bundle_dir"])

    solo = _solo_sign_upload(client, f5, _F5_NAME, reviewer_name="Collin Tan")
    assert solo.status_code == 200, solo.text
    solo_bundle = Path(solo.json()["bundle_dir"])

    acc_boxes = json.loads((acc_bundle / "compile-output.json").read_text(encoding="utf-8"))["calculate"]["boxes"]
    solo_boxes = json.loads((solo_bundle / "compile-output.json").read_text(encoding="utf-8"))["calculate"]["boxes"]
    assert acc_boxes == solo_boxes, (
        "accumulated primary boxes must be byte-identical to a solo /sign/upload (box-isolation)"
    )


# -- T3 -- F5 required: a sales-only session cannot be signed --------------------------------

def test_t3_f5_required_sales_only_session_refused(client, hermetic):
    """A session carrying ONLY a sales slice (no ACTIVE F5) refuses the accumulated sign (422).

    R2: the F5 export carries the return figures -- the accumulated paper's boxes/structure come
    from the F5 primary, so a session with no active F5 slice cannot produce a working paper; the
    422 detail must name the reason (F5).

    FAILS TODAY: the route is a 404 (absent), so `assert 422` is red (never reaches the guard).
    """
    rid = _new_review("sales-only")
    _post_upload(client, _SALES_FIXTURE.read_bytes(), _SALES_NAME, review_id=rid)

    resp = _accumulated_sign(client, rid, reviewer_name="Collin Tan")
    assert resp.status_code == 422, resp.text
    assert "F5" in resp.json()["detail"], "the F5-required refusal must name F5 in its detail"


# -- T4 -- loud forward-only refusal: a slice whose retained bytes are gone cannot be re-run ---

def test_t4_loud_refusal_when_retained_bytes_absent(client, hermetic):
    """Deleting an ACTIVE slice's retained upload bytes forces a LOUD forward-only refusal (422).

    R1: a session created BEFORE bytes-retention landed (or one whose retained file was removed)
    cannot re-run its primary -- the sign must refuse LOUDLY ("predates byte retention" + a
    "re-attach" instruction), never silently sign a partial/stale paper.

    FAILS TODAY: uploads do NOT retain bytes yet, so there is no reviews/<id>/uploads/<sha>.xlsx
    to delete (the unlink is a no-op) AND the sign route is a 404 -> `assert 422` is red. After
    Phase 2 the retained file exists, is deleted here, and the sign refuses 422 for the right reason.
    """
    import agent.review_store as rs

    rid = _new_review()
    f5 = _F5_FIXTURE.read_bytes()
    _post_upload(client, f5, _F5_NAME, review_id=rid)

    # The Phase-2 retention path layout (mirrors the documented uploads/<sha256>.xlsx contract;
    # rs.upload_bytes_path(rid, sha) will locate the same file once it exists). unlink(missing_ok)
    # tolerates today's absence so the FAILING assertion is the 422 below, not an OSError.
    sha = _sha(f5)
    retained = rs._REVIEWS_ROOT / rid / "uploads" / f"{sha}.xlsx"
    retained.unlink(missing_ok=True)

    resp = _accumulated_sign(client, rid, reviewer_name="Collin Tan")
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "predates byte retention" in detail, (
        f"the refusal must LOUDLY explain the missing bytes; got: {detail!r}"
    )
    assert "re-attach" in detail, "the refusal must instruct the reviewer to re-attach the export"


# -- T5 -- synthetic period disagreement: two active slices, non-None periods that DIFFER ------

def test_t5_period_disagreement_never_unioned(client, hermetic):
    """Two ACTIVE slices carrying non-None but DIFFERENT periods refuse the sign (422), surfacing
    BOTH periods -- never a silent union.

    R3 condition (exercised SYNTHETICALLY because real fixtures can't produce it -- non-F5 slices
    record period None today): the session is built via DIRECT review_store calls -- an F5-shaped
    slice with period 2026-04-01..2026-06-30 and a sales-shaped slice with a DIFFERENT non-None
    period 2026-01-01..2026-03-31, both with their upload bytes saved. The sign must refuse and
    name BOTH periods.

    FAILS TODAY: ``review_store.save_upload_bytes`` does not exist -> AttributeError at the first
    save call (a Phase-2 helper being pinned) -- and even past it the sign route is a 404. After
    Phase 2 both the helper and the disagreement guard exist and the 422 fires for the right reason.
    """
    import agent.review_store as rs

    rid = _new_review("period-disagreement")
    f5 = _F5_FIXTURE.read_bytes()
    sales = _SALES_FIXTURE.read_bytes()
    f5_sha, sales_sha = _sha(f5), _sha(sales)

    rs.append_slice(rid, {
        "source_kind": "xero_f5_upload",
        "sha256": f5_sha,
        "client_id": "xero_demo",
        "period": {"start": "2026-04-01", "end": "2026-06-30"},
        "queue": [],
        "coverage_status": [],
    })
    rs.save_upload_bytes(rid, f5_sha, f5)  # Phase-2 helper (AttributeError today)

    rs.append_slice(rid, {
        "source_kind": "xero_sales_upload",
        "sha256": sales_sha,
        "client_id": "xero_sales_demo",
        "period": {"start": "2026-01-01", "end": "2026-03-31"},
        "queue": [],
        "coverage_status": [],
    })
    rs.save_upload_bytes(rid, sales_sha, sales)

    resp = _accumulated_sign(client, rid, reviewer_name="Collin Tan")
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    for token in ("2026-04-01", "2026-06-30", "2026-01-01", "2026-03-31"):
        assert token in detail, (
            f"period disagreement must surface BOTH periods (never a union); missing {token!r} "
            f"in detail: {detail!r}"
        )


# -- T6 -- #43 guard BOTH directions on the accumulated render ------------------------------

def test_t6_hash43_guard_both_directions(client, hermetic, monkeypatch):
    """The accumulated paper obeys the #43 signable-render guard in BOTH directions.

    (a) DEFAULT configs (show_ai_candidates False): the sign is 200 and the PDF carries the
        reviewer name with NO "Signature suppressed"/"Do not sign" text (a signable paper).
    (b) With ``config.loader.load_client_config`` wrapped to flip show_ai_candidates=True for
        "xero_demo" ONLY: the sign is 200 and the PDF now CONTAINS the "UNVALIDATED" banner marker
        AND the "Signature suppressed"/"Do not sign" suppression -- the #43 guard fires on the
        accumulated render exactly as on the solo render.

    FAILS TODAY: the accumulated sign route is a 404 (absent) -> the first 200 assertion in each
    direction is red.
    """
    import dataclasses

    import config.loader as _loader

    f5 = _F5_FIXTURE.read_bytes()

    # (a) default -- signable, no suppression, reviewer present.
    rid_a = _new_review("guard-default")
    _post_upload(client, f5, _F5_NAME, review_id=rid_a)
    resp_a = _accumulated_sign(client, rid_a, reviewer_name="Collin Tan")
    assert resp_a.status_code == 200, resp_a.text
    text_a = _pdf_text(Path(resp_a.json()["working_paper_path"]))
    assert "Collin Tan" in text_a, "the signable accumulated paper carries the reviewer name"
    assert "Signature suppressed" not in text_a
    assert "Do not sign" not in text_a

    # (b) show_ai_candidates flipped True for xero_demo ONLY -> banner + suppressed signature.
    real_load = _loader.load_client_config

    def _wrapped(client_id, *args, **kwargs):
        cfg = real_load(client_id, *args, **kwargs)
        if client_id == "xero_demo":
            cfg = dataclasses.replace(cfg, show_ai_candidates=True)
        return cfg

    monkeypatch.setattr(_loader, "load_client_config", _wrapped)

    rid_b = _new_review("guard-flipped")
    _post_upload(client, f5, _F5_NAME, review_id=rid_b)
    resp_b = _accumulated_sign(client, rid_b, reviewer_name="Collin Tan")
    assert resp_b.status_code == 200, resp_b.text
    text_b = _pdf_text(Path(resp_b.json()["working_paper_path"]))
    assert "UNVALIDATED" in text_b, "the #43 banner marker must appear when show_ai_candidates=True"
    assert ("Signature suppressed" in text_b) or ("Do not sign" in text_b), (
        "the #43 guard must suppress the signature on an AI-candidate-preview accumulated render"
    )


# -- T7 -- provenance + R6: non-primary findings render from STORED rows, not a re-run --------

def test_t7_non_primary_renders_from_stored_rows_with_provenance(client, hermetic):
    """A superseding sales slice's SENTINEL stored row appears in the paper -- proving the
    non-primary slice renders from STORED rows (R6), never a re-run -- with visible provenance.

    Before signing, a superseding sales slice is appended via review_store.append_slice carrying a
    queue row with a SENTINEL description, plus save_upload_bytes for its fresh sha. The non-primary
    slice is NOT re-run, so its bytes content is irrelevant to rendering -- only its STORED rows are.
    The paper must carry: the SENTINEL, the slice's source_kind (source label), and an
    attach-timestamp (the stored slice's uploaded_at date -- vintage visibility). The sealed
    accumulated-review.json must carry per-slice provenance (source_kind + sha256 + uploaded_at).

    FAILS TODAY: ``review_store.save_upload_bytes`` does not exist -> AttributeError (Phase-2 helper),
    and the sign route is a 404 regardless. After Phase 2 both exist and the stored SENTINEL renders.
    """
    import agent.review_store as rs

    rid = _new_review("stored-rows")
    f5 = _F5_FIXTURE.read_bytes()
    sales = _SALES_FIXTURE.read_bytes()
    _post_upload(client, f5, _F5_NAME, review_id=rid)
    _post_upload(client, sales, _SALES_NAME, review_id=rid)  # sales slice v1 (superseded below)

    sentinel = "SENTINEL-STORED-ROW-7f3a"
    fresh_sha = _sha(sales + b"x")  # a genuinely different sha -> supersedes the v1 sales slice
    rs.append_slice(rid, {
        "source_kind": "xero_sales_upload",
        "sha256": fresh_sha,
        "client_id": "xero_sales_demo",
        "period": None,  # non-F5 slices record period None -> no disagreement with the F5 primary
        "queue": [{
            "finding_id": "detect:SENTINEL",
            "check_id": "E2",
            "vendor": "Sentinel Vendor Pte Ltd",
            "description": sentinel,
            "recommendation": sentinel,
            "candidate_framing_text": sentinel,
            "error_code": "E2",
            "demoted": False,
            "prior_dispositions": [],
            "fingerprint": "sha256:sentinel",
            "validation_status": "unvalidated",
        }],
        "coverage_status": [],
    })
    rs.save_upload_bytes(rid, fresh_sha, sales)  # Phase-2 helper (AttributeError today)

    # The uploaded_at the store stamped on the superseding slice (its "vintage").
    stored = next(s for s in rs.load_review(rid)["slices"] if s.get("sha256") == fresh_sha)
    attach_date = stored["uploaded_at"][:10]  # YYYY-MM-DD prefix

    resp = _accumulated_sign(client, rid, reviewer_name="Collin Tan")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    text = _pdf_text(Path(body["working_paper_path"]))
    assert sentinel in text, (
        "the non-primary slice's STORED sentinel row must render (R6 stored-rows, not a re-run)"
    )
    assert "xero_sales_upload" in text, "the per-slice subsection must show its source_kind (provenance)"
    assert attach_date in text, "the per-slice subsection must show the attach timestamp (vintage)"

    acc = json.loads((Path(body["bundle_dir"]) / "accumulated-review.json").read_text(encoding="utf-8"))
    prov = [d for d in _walk_dicts(acc) if {"source_kind", "sha256", "uploaded_at"} <= set(d)]
    assert prov, (
        "accumulated-review.json must carry per-slice provenance (source_kind + sha256 + uploaded_at)"
    )
    assert any(d.get("sha256") == fresh_sha for d in prov), (
        "the superseding sales slice's provenance must be present in accumulated-review.json"
    )


# -- T8 -- signed record + #136 non-regression -----------------------------------------------

def test_t8_signed_record_and_136_non_regression(client, hermetic):
    """A sign appends exactly ONE type=="signed" line; slice lines are unchanged; GET grows a
    "signed" list while the #136 merged-view keys are untouched.

    After a T1-style sign: the on-disk session JSONL carries exactly one type=="signed" record
    (append-only) and the same TWO slice records (the sign never rewrites slices); GET
    /review-session/{id} now carries a "signed" list with one entry (reviewer_name + signed_at)
    while "slices"/"superseded"/"coverage_matrix" remain present (t-review-accumulation intact).

    FAILS TODAY: the accumulated sign route is a 404 (absent) -> the 200 assertion is red; no
    "signed" record is ever written and GET carries no "signed" key.
    """
    import agent.review_store as rs

    rid = _new_review("signed-record")
    _post_upload(client, _F5_FIXTURE.read_bytes(), _F5_NAME, review_id=rid)
    _post_upload(client, _SALES_FIXTURE.read_bytes(), _SALES_NAME, review_id=rid)

    resp = _accumulated_sign(client, rid, reviewer_name="Collin Tan")
    assert resp.status_code == 200, resp.text

    path = rs._REVIEWS_ROOT / rid / "slices.jsonl"
    lines = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    signed = [r for r in lines if r.get("type") == "signed"]
    slices = [r for r in lines if r.get("type") == "slice"]
    assert len(signed) == 1, "exactly one append-only signed record per sign"
    assert len(slices) == 2, "the sign must NOT rewrite or add slice records (#136 append-only)"

    got = client.get(f"/review-session/{rid}")
    assert got.status_code == 200, got.text
    view = got.json()
    assert "signed" in view and len(view["signed"]) == 1, (
        "GET /review-session/{id} gains an additive 'signed' list with one entry"
    )
    entry = view["signed"][0]
    assert entry.get("reviewer_name") == "Collin Tan"
    assert entry.get("signed_at"), "the signed entry must surface signed_at"
    # #136 non-regression: the merged-view keys are still present.
    for key in ("slices", "superseded", "coverage_matrix"):
        assert key in view, f"the t-review-accumulation merged-view key {key!r} must remain present"
