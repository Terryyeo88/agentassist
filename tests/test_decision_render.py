"""tests/test_decision_render.py -- t-decision-render (D-2026-07-24-decision-render) FAILING-FIRST.

BUILD ID: t-decision-render. Written BEFORE the implementation (failing-first SOP). TODAY:
  * api.viewmodel has NO build_adjudication_view; report.sections has NO
    build_adjudication_section / AdjudicationSection; ReportModel has NO adjudications field;
    ReviewInputs has NO adjudications field; and NO sign path loads decisions (run-proven in
    the Phase-1 recon: 0 calls to annotate_and_demote / load_decision_entries on all three).

WHAT PHASE 2 BUILDS (Terry rulings R1-R7 + binding constraints), pinned here first:
  1. BRANCH B path scope: POST /sign/upload AND POST /review-session/{id}/sign render
     reviewer adjudications; frozen POST /sign stays SILENT (pinned in T9 -- honesty parity).
  2. The decision view is built in api/ (build_adjudication_view, plain data out) and passed
     into build_report AS DATA -- the accumulated= kwarg precedent. report/ stays a pure leaf
     (see tests/test_leaf_import_purity.py, R5a).
  3. The engine touch is a BOUNDED pass-through: ReviewInputs gains an optional DEFAULTED
     `adjudications` data field threaded verbatim into build_report -- zero logic, zero
     decision-layer imports in engine/.
  4. R4: the paper renders the FULL ORDERED disposition history per finding (append-ordered,
     last = most recent -- run-proven) with reviewer + timestamp from AdjudicationEntry rows;
     NEVER the latest-only annotation string.
  5. R3: the paper states DISPOSITIONS (ACCEPTED / REJECTED / KNOWN_ACCEPTED as set-aside),
     never the UI verb ("Not an issue" / "Mark known" must not appear; free text not parsed).
  6. R2: superseded v0 entries surface as an AGGREGATE count line, rendered only when > 0,
     with the ruled wording; per-finding attribution is structurally impossible and NOT
     attempted.
  7. R5(b) NO-FILTERING: a REJECTED (declined) finding STILL RENDERS -- demote is not drop;
     the bundle seals unfiltered detect.issues, and the paper must not contradict it.
  8. Box-isolation: boxes/gates byte-identical with and without a decision store (T8 guard).
  9. Wording avoids the four unamendable negative pdfplumber pins: "AI-Surfaced Candidates",
     "AI-surfaced candidates", "Signature suppressed", "Do not sign" (R5c).

THREE-TIMES RULE: "signed papers render adjudications as data-passed dispositions; declined
findings still render; superseded decisions surface as an aggregate count" lives in the
D-ledger/docs (prompt), api/viewmodel.py + report/sections.py + engine/review.py (code), and
HERE (test).

HERMETIC: tmp_path everything (mirrors tests/test_fingerprint_v1.py); xero_demo is a
file-import client; SAP off, no tokens, no network. ASCII-only.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from audit_bundle.canonical import canonical_json
from agent.decision_ledger import KNOWN_ACCEPTED, compute_finding_fingerprint
from api.app import app

_UPLOAD_SEQ = itertools.count()

_REPO_ROOT = Path(__file__).resolve().parents[1]
_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_F5_NAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

# The four unamendable negative pins (R5c) -- the new section's wording must avoid them ON a
# signable paper. Their home files (test_t58_mock_engine.py, test_accumulated_sign.py) are
# append-only territory; this build passes them by wording choice, asserted in T4/T6/T7.
_BANNED_PAPER_LITERALS = (
    "AI-Surfaced Candidates",
    "AI-surfaced candidates",
    "Signature suppressed",
    "Do not sign",
)

# The UI verbs that collapse to KNOWN_ACCEPTED -- must NEVER appear on the paper (R3).
_BANNED_VERBS = ("Not an issue", "Mark known")

# R2 ruled wording (aggregate superseded line) -- substring pin, count prefix varies.
_SUPERSEDED_WORDING = (
    "do not apply to this review because they were recorded under a "
    "superseded finding-identity version"
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Engine PDF dir + audit root + decision store + review store redirected to tmp."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    import agent.review_store as _rs
    monkeypatch.setattr(_rs, "_REVIEWS_ROOT", tmp_path / "reviews", raising=False)
    return tmp_path


def _bump_audit() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"


def _pdf_text(pdf_path: str | Path) -> str:
    """Full text of every page (pdfplumber -- the same extractor the suite already uses)."""
    import pdfplumber

    out = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    # reportlab wraps long paragraphs, so extract_text() breaks lines mid-sentence;
    # normalizing to single spaces lets multi-word wording pins match reliably.
    return " ".join("\n".join(out).split())


def _upload(client: TestClient, review_id=None) -> dict:
    _bump_audit()
    data = {"review_id": review_id} if review_id is not None else None
    resp = client.post(
        "/review/upload", files={"file": (_F5_NAME, _F5_FIXTURE.read_bytes())}, data=data
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _decide(client: TestClient, row: dict, action: str, note: str, reviewer: str) -> dict:
    resp = client.post("/decision", json={
        "client_id": "xero_demo", "finding_id": row["finding_id"],
        "fingerprint": row["fingerprint"], "action": action,
        "note": note, "reviewer_name": reviewer,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


# Raw detect-issue shapes (counterparty-bearing payloads the fingerprint keys on).
_ISSUE_A = {"error_code": "E4", "card_name": "OldRate Supplies Pte Ltd", "doc_num": "BILL-3002",
            "description": "Tax code at superseded 7% rate"}
_ISSUE_B = {"error_code": "E2", "card_name": "Harbour Trading", "doc_num": "BILL-1001",
            "description": "GST amount off expected"}


def _entry(fp: str, disposition: str, reviewer: str, ts: str, period=None, version="v1") -> dict:
    """A stored-entry dict in the JSONL shape load_decision_entries returns."""
    d = {
        "disposition": disposition, "entry_hash": "sha256:" + "1" * 64,
        "entry_id": f"e-{reviewer}-{ts}", "fingerprint": fp, "period": period,
        "prev_hash": "sha256:" + "0" * 64, "reason": f"[recorded] by {reviewer}",
        "reviewer": reviewer, "timestamp": ts,
    }
    if version is not None:
        d["fingerprint_version"] = version
    return d


# -- T1 (R4) -- the view: full ordered history, reviewer+timestamp, join by fingerprint ------

def test_t1_view_full_ordered_history_and_join():
    """build_adjudication_view joins entries to findings and carries the FULL ordered history.

    FAILS TODAY: api.viewmodel has no build_adjudication_view (ImportError/AttributeError).
    After the build: only adjudicated findings appear; history is append-ordered (last = most
    recent) carrying disposition + reviewer + timestamp + period per row (AdjudicationEntry
    fields as data -- R4, never the annotation string); demoted follows the ANY-KNOWN_ACCEPTED
    rule (agent.decision_ledger.DEMOTE_DISPOSITIONS, not re-derived); doc_num renders
    str-canonical (the #34 pattern: no int() anywhere).
    """
    from api.viewmodel import build_adjudication_view

    fp_a = compute_finding_fingerprint(_ISSUE_A)
    entries = [
        _entry(fp_a, "ACCEPTED", "First Reviewer", "2026-07-01T00:00:00+00:00", period="2026Q2"),
        _entry(fp_a, "REJECTED", "Second Reviewer", "2026-07-02T00:00:00+00:00"),
        _entry(fp_a, KNOWN_ACCEPTED, "Third Reviewer", "2026-07-03T00:00:00+00:00"),
    ]
    view = build_adjudication_view([
        {"client_id": "xero_demo", "issues": [_ISSUE_A, _ISSUE_B], "entries": entries},
    ])
    assert view is not None and view.get("clients"), "adjudicated issues must produce a view"
    block = view["clients"][0]
    assert block["client_id"] == "xero_demo"
    assert block["superseded_count"] == 0

    findings = block["findings"]
    assert len(findings) == 1, "only ADJUDICATED findings appear (issue B has no entries)"
    f = findings[0]
    assert f["check_id"] == "E4"
    assert f["doc_num"] == "BILL-3002" and isinstance(f["doc_num"], str)
    assert f["fingerprint"] == fp_a
    assert f["demoted"] is True, "any KNOWN_ACCEPTED in history demotes (ledger rule reused)"

    hist = f["history"]
    assert [h["disposition"] for h in hist] == ["ACCEPTED", "REJECTED", KNOWN_ACCEPTED], (
        "history must be the FULL ordered record, append-ordered, last = most recent"
    )
    assert hist[0]["reviewer"] == "First Reviewer"
    assert hist[0]["timestamp"] == "2026-07-01T00:00:00+00:00"
    assert hist[0]["period"] == "2026Q2"
    assert hist[2]["reviewer"] == "Third Reviewer"


def test_t1b_view_empty_store_is_none_and_int_doc_num_canonical():
    """No entries anywhere -> view is None (legacy renders stay byte-identical); int doc_num -> str.

    FAILS TODAY (import). The int-doc_num case pins the #34 rule at the view layer: an extract
    finding with doc_num 605 (int) must produce a STRING "605" in the view -- no int() coercion,
    no crash downstream.
    """
    from api.viewmodel import build_adjudication_view

    assert build_adjudication_view([
        {"client_id": "xero_demo", "issues": [_ISSUE_A], "entries": []},
    ]) is None

    int_issue = {"error_code": "E9", "card_name": "Extract Vendor", "doc_num": 605}
    fp = compute_finding_fingerprint(int_issue)
    view = build_adjudication_view([
        {"client_id": "extract_demo", "issues": [int_issue],
         "entries": [_entry(fp, "ACCEPTED", "R", "2026-07-01T00:00:00+00:00")]},
    ])
    f = view["clients"][0]["findings"][0]
    assert f["doc_num"] == "605" and isinstance(f["doc_num"], str)


def test_t2_view_superseded_v0_aggregate_only():
    """A v0-only store yields NO finding blocks and superseded_count=1 (R2: aggregate, never
    per-finding).

    FAILS TODAY (import). The v0 entry's stored 2-key hash can never equal a recomputed v1 key
    (inert by construction), so no finding matches; the count is the ONLY surfaced trace, and a
    client with ONLY superseded entries still produces a view (the count line must render).
    """
    from api.viewmodel import build_adjudication_view

    v0 = _entry("sha256:" + "a" * 64, KNOWN_ACCEPTED, "Legacy Reviewer",
                "2024-06-30T00:00:00+00:00", period="2024Q2", version=None)
    view = build_adjudication_view([
        {"client_id": "xero_demo", "issues": [_ISSUE_A], "entries": [v0]},
    ])
    assert view is not None, "superseded-only stores still surface (the count line)"
    block = view["clients"][0]
    assert block["findings"] == [], "an inert v0 entry matches nothing -- no finding block"
    assert block["superseded_count"] == 1


def test_t2b_view_stored_rows_join_without_recompute():
    """Stored slice rows (accumulated path) join by their STORED fingerprint -- no recompute.

    FAILS TODAY (import). Stored rows carry 'vendor' not 'card_name', so a recompute would be
    wrong-by-construction; the view must use row['fingerprint'] as-is. Rows without a
    fingerprint (ledger-recon rows) are skipped, never crashed on.
    """
    from api.viewmodel import build_adjudication_view

    fp = compute_finding_fingerprint(_ISSUE_B)
    stored_row = {"finding_id": "detect:E2:BILL-1001", "check_id": "E2",
                  "vendor": "Harbour Trading", "doc_num": "BILL-1001", "fingerprint": fp}
    no_fp_row = {"finding_id": "ledger-recon:1", "check_id": "LR1"}
    view = build_adjudication_view([
        {"client_id": "xero_sales_demo", "stored_rows": [stored_row, no_fp_row],
         "entries": [_entry(fp, "REJECTED", "Sales Reviewer", "2026-07-04T00:00:00+00:00")]},
    ])
    f = view["clients"][0]["findings"][0]
    assert f["fingerprint"] == fp and f["vendor"] == "Harbour Trading"
    assert [h["disposition"] for h in f["history"]] == ["REJECTED"]
    assert f["demoted"] is False


# -- T3 (R2/R3) -- the section: show semantics + ruled wording -------------------------------

def test_t3_section_show_semantics_and_superseded_wording():
    """build_adjudication_section: show=False on None; True on findings OR count>0; R2 wording.

    FAILS TODAY: report.sections has no build_adjudication_section. The superseded line uses
    Terry's ruled wording shape and renders ONLY when count > 0.
    """
    from report.sections import build_adjudication_section

    hidden = build_adjudication_section(None)
    assert hidden.show is False

    count_only = build_adjudication_section(
        {"clients": [{"client_id": "xero_demo", "superseded_count": 2, "findings": []}]}
    )
    assert count_only.show is True, "a superseded count > 0 alone must render (R2)"

    zero = build_adjudication_section(
        {"clients": [{"client_id": "xero_demo", "superseded_count": 0, "findings": []}]}
    )
    assert zero.show is False, "nothing to say -> nothing renders"


# -- T4 (R3/R4/R5b/R5c) -- the rendered paper over a direct build_report call ----------------

def _demo_view() -> dict:
    fp_a = compute_finding_fingerprint(_ISSUE_A)
    fp_b = compute_finding_fingerprint(_ISSUE_B)
    return {
        "clients": [{
            "client_id": "xero_demo",
            "superseded_count": 1,
            "findings": [
                {"finding_id": "detect:E4:BILL-3002", "check_id": "E4",
                 "vendor": "OldRate Supplies Pte Ltd", "doc_num": "BILL-3002",
                 "fingerprint": fp_a, "demoted": True,
                 "history": [
                     {"disposition": "ACCEPTED", "reviewer": "First Reviewer",
                      "timestamp": "2026-07-01T00:00:00+00:00", "period": "2026Q2"},
                     {"disposition": KNOWN_ACCEPTED, "reviewer": "Third Reviewer",
                      "timestamp": "2026-07-03T00:00:00+00:00", "period": None},
                 ]},
                {"finding_id": "detect:E2:BILL-1001", "check_id": "E2",
                 "vendor": "Harbour Trading", "doc_num": "BILL-1001",
                 "fingerprint": fp_b, "demoted": False,
                 "history": [
                     {"disposition": "REJECTED", "reviewer": "Second Reviewer",
                      "timestamp": "2026-07-02T00:00:00+00:00", "period": None},
                 ]},
            ],
        }],
    }


def test_t4_rendered_paper_dispositions_history_no_verbs(tmp_path):
    """A paper rendered with adjudications= carries the full history; R3/R4/R5b/R5c wording.

    FAILS TODAY: build_report has no adjudications kwarg (TypeError). After the build the PDF
    text must carry: both findings (REJECTED one STILL RENDERS -- no-filtering, R5b), every
    disposition in each history (full record, R4), reviewer names + timestamps, the set-aside
    framing for the demoted finding, the R2 superseded line (count 1 here), and NONE of the UI
    verbs or the four banned literals (R3/R5c).
    """
    from config.loader import load_client_config
    from report.report import build_report
    from report.render import render_pdf

    compile_output = json.loads(
        (_REPO_ROOT / "tests" / "fixtures" / "demo-artifacts" / "review_result.json")
        .read_text(encoding="utf-8")
    )["compile_output"]
    cfg = load_client_config("xero_demo", check_connectivity=False)

    model = build_report(
        compile_output, cfg,
        generated_at=compile_output["fetch_manifest"]["fetched_at"],
        adjudications=_demo_view(),
    )
    text = _pdf_text(render_pdf(model, tmp_path / "adjudicated.pdf"))

    assert "BILL-3002" in text and "BILL-1001" in text, (
        "every adjudicated finding renders -- including the REJECTED one (no-filtering, R5b)"
    )
    for token in ("ACCEPTED", "REJECTED", KNOWN_ACCEPTED,
                  "First Reviewer", "Second Reviewer", "Third Reviewer",
                  "2026-07-01", "2026-07-02", "2026-07-03"):
        assert token in text, f"full ordered history must render (R4): missing {token!r}"
    assert "set aside" in text.lower(), "KNOWN_ACCEPTED renders as set-aside/demoted (R3)"
    assert _SUPERSEDED_WORDING in text, "R2 aggregate superseded line (count=1) must render"
    for verb in _BANNED_VERBS:
        assert verb not in text, f"the UI verb {verb!r} must never reach the paper (R3)"
    for lit in _BANNED_PAPER_LITERALS:
        assert lit not in text, f"wording must avoid the unamendable negative pin {lit!r}"


def test_t4b_legacy_render_byte_identical_without_adjudications(tmp_path):
    """No adjudications -> the model renders EXACTLY as before (None field, hidden section).

    FAILS TODAY only on the kwarg's absence (the explicit adjudications=None call raises
    TypeError). After the build: passing adjudications=None and omitting the kwarg produce
    byte-identical PDFs, and neither carries the section heading.
    """
    from config.loader import load_client_config
    from report.report import build_report
    from report.render import render_pdf

    compile_output = json.loads(
        (_REPO_ROOT / "tests" / "fixtures" / "demo-artifacts" / "review_result.json")
        .read_text(encoding="utf-8")
    )["compile_output"]
    cfg = load_client_config("xero_demo", check_connectivity=False)
    kw = dict(generated_at=compile_output["fetch_manifest"]["fetched_at"])

    m_omitted = build_report(compile_output, cfg, **kw)
    m_none = build_report(compile_output, cfg, adjudications=None, **kw)
    t_omitted = _pdf_text(render_pdf(m_omitted, tmp_path / "omitted.pdf"))
    t_none = _pdf_text(render_pdf(m_none, tmp_path / "none.pdf"))
    assert t_omitted == t_none
    assert "adjudication" not in t_omitted.lower(), (
        "a decision-free render must stay SILENT on adjudications"
    )


# -- T5 -- the bounded engine pass-through -----------------------------------------------------

def test_t5_engine_passthrough_reviewinputs_field(hermetic):
    """ReviewInputs.adjudications threads into review()'s own render -- data in, section out.

    FAILS TODAY: ReviewInputs has no adjudications field (TypeError). After the build: a
    review() run given the view renders the adjudication text on its OWN paper (the
    /sign/upload renderer); a default-constructed run stays silent AND box-identical
    (bounded pass-through: zero engine logic, so the deterministic chain cannot move).
    """
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review
    from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period

    cfg = load_client_config("xero_demo", check_connectivity=False)
    period = parse_review_period(_F5_FIXTURE)

    def _run(adjudications):
        _bump_audit()
        # Per-run REPORTS dir: review()'s pdf_path is seconds-resolution (from the
        # chain's fetched_at), so two persist runs in one second OVERWRITE one PDF --
        # the same same-second collision family #132 fixed for the seal dir and
        # ui/sign.py, still unfixed on the engine path (FILED as an open item, out of
        # scope here). Isolating the dir keeps this test honest either way.
        import engine.review as _rev
        _rev._REPORTS_DIR = hermetic / f"reports-{next(_UPLOAD_SEQ)}"
        kwargs = {} if adjudications is None else {"adjudications": adjudications}
        inputs = ReviewInputs(
            line_source=lambda: [], provider=None,
            reader=XeroF5ChainReader(_F5_FIXTURE), **kwargs,
        )
        result = review(cfg, period, inputs)
        assert result.status == "completed"
        return result

    silent = _run(None)
    with_view = _run(_demo_view())

    assert canonical_json(silent.compile_output["calculate"]["boxes"]) == canonical_json(
        with_view.compile_output["calculate"]["boxes"]
    ), "the pass-through must not perturb the deterministic chain (box-isolation)"

    assert "adjudication" not in _pdf_text(silent.report_pdf_path).lower()
    text = _pdf_text(with_view.report_pdf_path)
    assert "First Reviewer" in text and "REJECTED" in text, (
        "the view handed through ReviewInputs must render on review()'s own paper"
    )


# -- T6 -- POST /sign/upload end-to-end (Branch B primary demo path) -------------------------

def test_t6_sign_upload_renders_adjudications(client, hermetic):
    """Decide via POST /decision, then POST /sign/upload: the signed paper carries the history.

    FAILS TODAY (run-proven loading gap): the sign path never loads decisions, so the paper is
    silent. After the build: the paper renders the recorded REJECTED disposition with reviewer
    + timestamp (R4), still renders the finding row (R5b), avoids verbs + banned literals, and
    the response key set is UNCHANGED (no new response keys).
    """
    up = _upload(client)
    row = next(r for r in up["queue"] if r["check_id"] == "E4")
    _decide(client, row, "Decline", "recon says false positive", "Paper Reviewer")

    _bump_audit()
    resp = client.post(
        "/sign/upload",
        files={"file": (_F5_NAME, _F5_FIXTURE.read_bytes())},
        data={"reviewer_name": "Signing Reviewer"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "source_kind", "reviewer_name", "firm_name", "working_paper_path",
        "bundle_dir", "validation_status", "disclaimer",
    }, "response contract unchanged -- rendering is a paper concern, not an API-shape concern"

    text = _pdf_text(body["working_paper_path"])
    assert "REJECTED" in text and "Paper Reviewer" in text, (
        "the signed upload paper must render the stored adjudication (Branch B wiring)"
    )
    assert row["doc_num"] in text, "the declined finding still renders (no-filtering, R5b)"
    for verb in _BANNED_VERBS:
        assert verb not in text
    for lit in _BANNED_PAPER_LITERALS:
        assert lit not in text


def test_t6b_sign_upload_empty_store_single_run_silent(client, hermetic):
    """An empty decision store signs exactly as before -- silent paper, no decision text.

    Passes TODAY and after (guard): the zero-decision path must stay byte-equivalent in
    behaviour (single review() run, no view, no section).
    """
    _bump_audit()
    resp = client.post(
        "/sign/upload",
        files={"file": (_F5_NAME, _F5_FIXTURE.read_bytes())},
        data={"reviewer_name": "Silent Reviewer"},
    )
    assert resp.status_code == 200, resp.text
    assert "adjudication" not in _pdf_text(resp.json()["working_paper_path"]).lower()


# -- T7 -- POST /review-session/{id}/sign end-to-end ------------------------------------------

def test_t7_accumulated_sign_renders_adjudications_and_superseded(client, hermetic, tmp_path):
    """The accumulated paper renders the primary slice's adjudications + the superseded line.

    FAILS TODAY (loading gap). Seeds one REAL decision (ACCEPTED via the endpoint) plus one
    hand-written v0-style entry (no fingerprint_version, 2-key-era hash that matches nothing);
    the paper must carry the ACCEPTED history row AND the R2 aggregate line for the v0 entry,
    while the ACCUMULATED_SIGN_KEYS response contract stays unchanged.
    """
    import agent.review_store as rs

    rid = rs.create_review("decision-render-t7")["review_id"]
    up = _upload(client, review_id=rid)
    row = next(r for r in up["queue"] if r["check_id"] == "E4")
    _decide(client, row, "Accept", "", "Accum Reviewer")

    # A v0-era entry: absent fingerprint_version, stored key from the RETIRED 2-key algorithm
    # (matches nothing under v1 -- inert by construction; only the count may surface).
    store = hermetic / "decisions" / "xero_demo" / "ledger.jsonl"
    entries = [json.loads(ln) for ln in store.read_text(encoding="utf-8").splitlines()]
    v0 = _entry("sha256:265e9b4e92baa689143df7f1384560a0f337d325105d38c8499c6595c42b159e",
                KNOWN_ACCEPTED, "Legacy Reviewer", "2024-06-30T00:00:00+00:00",
                period="2024Q2", version=None)
    v0["prev_hash"] = entries[-1]["entry_hash"]
    with store.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(v0, sort_keys=True) + "\n")

    _bump_audit()
    resp = client.post(
        f"/review-session/{rid}/sign", json={"reviewer_name": "Accum Signer"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "review_id", "reviewer_name", "firm_name", "working_paper_path", "bundle_dir",
        "primary_sha256", "primary_source_kind", "source_kind", "slices_signed",
        "validation_status", "disclaimer",
    }, "ACCUMULATED_SIGN_KEYS unchanged -- no new response keys"

    text = _pdf_text(body["working_paper_path"])
    assert "ACCEPTED" in text and "Accum Reviewer" in text, (
        "the accumulated paper must render the stored adjudication history"
    )
    assert _SUPERSEDED_WORDING in text, (
        "the v0 entry surfaces ONLY as the aggregate superseded line (R2)"
    )
    for verb in _BANNED_VERBS:
        assert verb not in text
    for lit in _BANNED_PAPER_LITERALS:
        assert lit not in text


# -- T8 (guard) -- box-isolation across the whole decision stream ----------------------------

def test_t8_boxes_identical_with_and_without_decisions(client, hermetic):
    """F5 boxes byte-identical (canonical_json) across sign runs with an empty vs seeded store.

    Passes TODAY and after (guard): rendering adjudications is presentation over passed data;
    the deterministic chain and its boxes never move.
    """
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review
    from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period

    cfg = load_client_config("xero_demo", check_connectivity=False)
    period = parse_review_period(_F5_FIXTURE)

    def _boxes():
        _bump_audit()
        result = review(cfg, period, ReviewInputs(
            line_source=lambda: [], provider=None, reader=XeroF5ChainReader(_F5_FIXTURE),
        ), persist_artifacts=False)
        return canonical_json(result.compile_output["calculate"]["boxes"])

    empty = _boxes()
    up = _upload(client)
    row = next(r for r in up["queue"] if r["check_id"] == "E4")
    _decide(client, row, "Mark known", "standing treatment", "Guard Reviewer")
    assert _boxes() == empty


# -- T9 (guard) -- frozen POST /sign stays SILENT (honest-status parity) ---------------------

def test_t9_frozen_sign_path_still_silent(client, tmp_path, monkeypatch):
    """The frozen POST /sign paper renders NO adjudication text -- the unwired path is honest.

    Passes TODAY and after (guard): R1 rules the reduced-arg ui/sign.py path OUT of this build;
    the honest-status requirement is that the paper stays silent rather than half-wired.
    """
    resp = client.post(
        "/sign", params={"out_dir": str(tmp_path)},
        json={"reviewer_name": "Frozen Reviewer", "firm_name": ""},
    )
    assert resp.status_code == 200, resp.text
    text = _pdf_text(resp.json()["working_paper_path"])
    assert "adjudication" not in text.lower()
    assert _SUPERSEDED_WORDING not in text
