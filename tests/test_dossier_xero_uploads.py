"""tests/test_dossier_xero_uploads.py -- t-dossier-xero (D-2026-07-23-dossier-xero) FAILING-FIRST.

BUILD ID: t-dossier-xero. Written BEFORE the implementation; these MUST fail today for the
RIGHT reason. Phase 2 will:

  1. ADD a NEW module ``agent/upload_dossiers.py`` (stdlib-only, hermetic, no model/network):
       * ``_MAX_DOSSIER_FINDINGS`` -- a bounded-work cap (monkeypatchable module constant);
       * ``UNGATHERABLE_ON_UPLOAD = frozenset({"supplier_catalog", "document_pdfs"})``;
       * ``generate_upload_dossiers(review_result)`` -> object with ``.dossiers`` (dict
         finding_id -> DossierArtifact), ``.capped`` (bool) and ``.proposals`` (list, ALL
         status "pending" -- the cage never approves/seals/emits);
       * ``dossier_queue_fields(dossier)`` -> dict with EXACTLY the three keys
         candidate_framing_text / completeness / inputs_hash, where completeness.missing
         entries are REASON-SUFFIXED PLAIN STRINGS (Terry R5 Option 1): a slot in
         UNGATHERABLE_ON_UPLOAD renders "<slot> -- not gatherable on this source ..." and any
         other missing slot renders "<slot> -- ... gathering failed". Strings only (the
         frontend Completeness type pins missing: string[]).
       * candidate_framing_text is a DETERMINISTIC template derived from CHECK_REGISTRY
         (display_name), candidate-shaped, asserting NO verdict, MUST pass agent.lint.lint_framing.
  2. WIRE api/app.py: the xero_f5 and xero_sales upload branches call the helper after
     review() and thread dossiers into serialize_xero_queue via a NEW OPTIONAL kwarg
     ``dossiers=None`` (default -> byte-identical to today). The EXTRACT branch is DEFERRED
     under Terry's wiring-scope fallback ruling (not trivially symmetric: NO_GST_REG needs
     an honest supplier catalog the reader cannot yet key — see T2's docstring); its rows
     keep today's defaults, pinned by T2. Cap exceeded -> generation skipped, queue fields
     stay at today's defaults, and a coverage row {"check": "case_file_dossiers", "level":
     "degraded", "reason": <non-empty>} is APPENDED to ``coverage_status``.
  3. Zero key churn: QUEUE_ITEM_KEYS unchanged; the 5-key top-level upload literals unchanged.

THREE-TIMES RULE (prompt + code + THIS test): the "upload dossiers surface candidate framing +
CODE-DEFINED completeness, never a verdict, bounded, cage always PENDING" invariant is pinned in
the panel spec, will be enforced in agent/upload_dossiers.py + api/app.py, and is asserted here.

WHY EACH TEST FAILS TODAY (failing-first, per test docstring):
  * ENDPOINT tests (T1/T2/T4/T8 + the endpoint half of T3) do NOT import the new module -- they
    run today and fail on FIELD-VALUE assertions (candidate_framing_text is ""/inputs_hash is the
    em-dash default), because serialize_xero_queue has no dossiers kwarg and app.py does not yet
    call generate_upload_dossiers.
  * MODULE tests (T5/T6/T7 + the serializer half of T3) import agent.upload_dossiers INSIDE the
    test, so today they fail at that import (the module does not exist) -- collection of the
    endpoint tests is unaffected.

HERMETIC: tmp_path everything; engine PDF dir + audit root + decision store redirected to tmp;
the per-upload fresh-audit-subdir trick (seal.run_ts has seconds resolution -> two uploads in one
second collide on one read-only bundle dir; sidestepped per-call, NEVER patched in the engine).
xero_demo / extract_demo / xero_sales_demo are file-import (non-SAP) clients loaded with
check_connectivity=False, so NO SAP creds are set -- keeping T4's delenv/no-network posture clean.
Pure stdlib + pytest + fastapi.testclient. No anthropic import. SAP off, no tokens.
"""
from __future__ import annotations

import importlib.util
import itertools
import re
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from agent.lint import lint_framing  # exists today
from agent.registry import CHECK_REGISTRY
from api.app import app, XERO_SALES_REVIEW_KEYS
from api.viewmodel import QUEUE_ITEM_KEYS, serialize_xero_queue

# Each upload gets its OWN audit subdir (seal.run_ts seconds resolution -> per-call bump).
_UPLOAD_SEQ = itertools.count()

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

_FROZEN_EXTRACT_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"

# The 5-key top-level upload literals the three branches share (F5 branch shape).
_F5_TOP_KEYS = {"source_kind", "validation_status", "disclaimer", "coverage_status", "queue"}

# The em-dash inputs_hash default serialize_queue_item stamps when no dossier is threaded.
# Built via chr() to keep this file ASCII-safe (the codebase literal is U+2014, an em-dash).
_INPUTS_HASH_DEFAULT = chr(0x2014)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Engine PDF dir + audit root + decision store redirected to tmp.

    NO SAP creds: xero_demo / extract_demo / xero_sales_demo are file-import (non-SAP) clients
    loaded with check_connectivity=False (DEBT-9 resolved), so no SAP_USERNAME/SAP_PASSWORD is
    needed. Deliberately unset here so T4's "no network / no model" posture is not masked.
    """
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path / "decisions")
    return tmp_path


def _synth_extract_bytes(tmp_path: Path) -> bytes:
    """A synthetic (NON-Xero) extract .xlsx -- local importlib load of the committed exporter
    (tests/ is not a package). Mirrors test_extract_engine_upload.py / test_b3a2_*.py."""
    spec = importlib.util.spec_from_file_location(
        "dossier_xero_synth_export", _REPO_ROOT / "tests" / "synth_extract_export.py"
    )
    synth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(synth)
    out = tmp_path / "synthetic_export.xlsx"
    synth.export_xlsx(_FROZEN_EXTRACT_DIR, out)
    return out.read_bytes()


def _post_upload(client: TestClient, files: dict) -> dict:
    """POST /review/upload with a fresh audit subdir (per-upload; see module docstring)."""
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"
    resp = client.post("/review/upload", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _detect_rows(queue: list) -> list:
    return [r for r in queue if str(r.get("finding_id", "")).startswith("detect:")]


def _assert_populated_dossier_row(row: dict) -> None:
    """The t-dossier-xero enabler, asserted on ONE detect row.

    FAILS TODAY: candidate_framing_text is "" (empty), inputs_hash is the em-dash default, and
    completeness is the empty {required:[],present:[],missing:[],satisfied:False} default --
    serialize_xero_queue has no dossiers kwarg and app.py does not build dossiers yet.
    """
    text = row["candidate_framing_text"]
    assert isinstance(text, str) and text, "candidate_framing_text must be a non-empty str"
    assert re.search(r"candidate", text, re.I), "framing must be candidate-shaped"
    assert re.search(r"consider reviewing", text, re.I), "framing carries the review invite"
    # It must pass the deterministic language-lint (no verdict; candidate marker present).
    assert lint_framing(text).passed is True, f"framing must pass lint_framing: {text!r}"

    check_id = row["check_id"]
    expected_inputs = list(CHECK_REGISTRY[check_id].inputs_needed)
    # E2/E3/E4 need only engine-seeded slots (none in UNGATHERABLE_ON_UPLOAD), so the engine
    # having produced the finding means every required slot is present -> satisfied, missing [].
    assert row["completeness"] == {
        "required": expected_inputs,
        "present": expected_inputs,
        "missing": [],
        "satisfied": True,
    }
    assert isinstance(row["inputs_hash"], str) and row["inputs_hash"].startswith("sha256:")


# -- T1 -- F5 upload populates the dossier fields on every detect row -----------------------

def test_t1_f5_upload_populates_dossier_fields(client, hermetic):
    """F5 endpoint upload -> every detect row carries populated dossier fields.

    FAILS TODAY: the F5 branch returns rows whose candidate_framing_text is "", inputs_hash is
    the em-dash default and completeness is the empty default -- app.py does not yet call
    generate_upload_dossiers and serialize_xero_queue has no dossiers kwarg. The 200 + shape
    pass today; the FIELD-VALUE assertions in _assert_populated_dossier_row are the red half.
    """
    assert _F5_FIXTURE.is_file(), f"committed Xero F5 fixture missing: {_F5_FIXTURE}"
    body = _post_upload(client, {"file": (_F5_NAME, _F5_FIXTURE.read_bytes())})

    assert body["source_kind"] == "xero_f5_upload"
    assert body["validation_status"] == "unvalidated"
    rows = _detect_rows(body["queue"])
    assert rows, "the F5 fixture must yield detect rows (E2/E3/E4)"
    for row in rows:
        assert row["check_id"] in {"E2", "E3", "E4"}
        _assert_populated_dossier_row(row)


# -- T2 -- general-extract upload: dossiers DEFERRED (pinned honest) -------------------------

def test_t2_extract_upload_dossiers_deferred_rows_keep_defaults(client, hermetic, monkeypatch):
    """The extract branch is DELIBERATELY NOT wired for dossiers in this build — pinned.

    SCOPE RULING (Terry, wiring-scope fallback): "if the branches aren't trivially
    symmetric, do F5 and REPORT why". The extract branch is NOT symmetric: its uploads
    yield NO_GST_REG detect findings (7 on the synthetic fixture) whose required
    supplier_catalog slot is AGENT-GATHERED, and the extract SOURCE genuinely carries the
    supplier data (FederalTaxID sheet) — so an unwired gather could not honestly claim
    "not gatherable on this source" (false: it is on the source) nor "gathering failed"
    (false: nothing was attempted). The reader's canonical BP projection also carries no
    CardName to key an honest vendor catalog. Until the catalog plumbing follow-up lands,
    extract rows keep TODAY'S defaults — this test pins that deferred state so a partial
    wiring (dossiers without the catalog, emitting a false reason) cannot slip in silently.

    This test PASSES today and after the build (a deferral guard, like T8): the extract
    branch's behaviour is unchanged by t-dossier-xero.
    """
    monkeypatch.delenv("AGENTASSIST_EXTRACT_ENGINE", raising=False)  # default = ON
    body = _post_upload(client, {"file": ("export.xlsx", _synth_extract_bytes(hermetic))})

    assert body["source_kind"] == "extract_review"
    assert body["validation_status"] == "unvalidated"
    rows = _detect_rows(body["queue"])
    assert rows, "the synthetic extract must yield detect rows"
    assert any(r["check_id"] == "NO_GST_REG" for r in rows), (
        "the asymmetry premise: extract uploads yield NO_GST_REG findings"
    )
    for row in rows:
        assert row["candidate_framing_text"] == "", "extract dossiers deferred -> default framing"
        assert row["inputs_hash"] == _INPUTS_HASH_DEFAULT, "extract dossiers deferred -> default hash"
        assert row["completeness"]["satisfied"] is False and row["completeness"]["missing"] == []


# -- T3 -- sales symmetry (clean fixture is vacuous; symmetry pinned at the serializer) ------

def test_t3_sales_upload_shape_and_serializer_symmetry(client, hermetic):
    """Sales upload symmetry -- ENDPOINT half + SERIALIZER half.

    HONEST VACUITY: the committed synthetic Xero SALES fixture yields NO detect findings (see
    tests/test_xero_sales_upload.py), so per-row endpoint population would be VACUOUS. The sales
    ENDPOINT population is therefore exercised only INDIRECTLY here: we assert the response SHAPE
    is intact (source_kind xero_sales_upload, top-level keys unchanged). A finding-bearing sales
    fixture is a filed follow-up.

    The dossier-population symmetry is driven at the SERIALIZER level instead -- serialize_xero_queue
    over a synthetic sales-like issue PLUS a dossier for it must populate the three fields.
    FAILS TODAY on the serializer half: ``from agent.upload_dossiers import dossier_queue_fields``
    is an ImportError (the module does not exist yet). The endpoint half passes today.
    """
    # -- ENDPOINT half (passes today; shape guard) --
    body = _post_upload(client, {"file": (_SALES_NAME, _SALES_FIXTURE.read_bytes())})
    assert body["source_kind"] == "xero_sales_upload"
    assert set(body.keys()) == set(XERO_SALES_REVIEW_KEYS)
    assert body["validation_status"] == "unvalidated"
    assert isinstance(body["queue"], list)  # clean fixture -> no detect rows (vacuous)

    # -- SERIALIZER half (RED today: ImportError on the new module) --
    from agent.dossier import DossierArtifact  # exists today
    from agent.upload_dossiers import dossier_queue_fields  # ImportError today

    issue = {
        "error_code": "E2", "doc_num": "INV-2003", "card_name": "Overseas Buyer Pte Ltd",
        "description": "ZR carrying tax", "doc_date": "2026-05-03",
    }
    fid = f"detect:{issue['error_code']}:{issue['doc_num']}"
    required = list(CHECK_REGISTRY["E2"].inputs_needed)
    dossier = DossierArtifact(
        finding_id=fid,
        check_id="E2",
        finding_type="deterministic",
        evidence={},
        candidate_framing_text=(
            "Candidate for review: GST charged on non-taxable or zero-rated supply -- "
            "consider reviewing document INV-2003. This is not a verdict."
        ),
        completeness={"required": required, "present": required, "missing": [], "satisfied": True},
        inputs_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )

    # dossier_queue_fields yields EXACTLY the three keys the serializer threads onto the row.
    fields = dossier_queue_fields(dossier)
    assert set(fields.keys()) == {"candidate_framing_text", "completeness", "inputs_hash"}

    rows = serialize_xero_queue([issue], dossiers={fid: dossier})
    assert len(rows) == 1, "cardinality preserved -- one issue, one row"
    row = rows[0]
    assert isinstance(row["candidate_framing_text"], str) and row["candidate_framing_text"]
    assert row["inputs_hash"].startswith("sha256:")
    assert row["completeness"]["missing"] == [] and row["completeness"]["satisfied"] is True


# -- T4 -- hermetic default: no network, no model, still populated --------------------------

def test_t4_hermetic_no_network_no_model_still_populated(client, hermetic, monkeypatch):
    """The populated F5 upload runs with NO network and NO model.

    Monkeypatches socket so any NON-LOOPBACK connect raises, + delenvs ANTHROPIC_API_KEY /
    AGENT_LIVE_TRANSPORT. Loopback is deliberately ALLOWED: on Windows, asyncio's Proactor
    event loop creates an internal 127.0.0.1 socketpair (the self-pipe) just to run the
    TestClient, and blocking it kills the ASGI plumbing itself, not a network egress. A real
    model/API call must reach a non-loopback host and trips the guard.
    HONEST split: the 200 half PASSES today (the F5 path is already hermetic); the populated-
    field half FAILS TODAY (candidate_framing_text is "" -- the dossier surface is not built).
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

    body = _post_upload(client, {"file": (_F5_NAME, _F5_FIXTURE.read_bytes())})  # 200 half (passes today)

    rows = _detect_rows(body["queue"])
    assert rows, "the F5 fixture must yield detect rows"
    for row in rows:
        # RED today: "" is not a populated framing string.
        assert row["candidate_framing_text"], "detect rows must carry populated framing hermetically"


# -- T5 -- cage: every proposal is PENDING; nothing approved/executed -----------------------

def test_t5_generate_upload_dossiers_is_pending_only(hermetic):
    """generate_upload_dossiers over a real F5 ReviewResult -> cage never advances a proposal.

    Drives review() directly the way api/app.py does (load_client_config xero_demo,
    XeroF5ChainReader, parse_review_period, ReviewInputs(line_source=lambda: [], provider=None,
    reader=...), review(..., persist_artifacts=False)), then calls generate_upload_dossiers.

    FAILS TODAY: ``from agent.upload_dossiers import generate_upload_dossiers`` is an ImportError
    (the module does not exist yet).
    """
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review
    from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period
    from agent.upload_dossiers import generate_upload_dossiers  # ImportError today

    cfg = load_client_config("xero_demo", check_connectivity=False)
    reader = XeroF5ChainReader(_F5_FIXTURE)
    period = parse_review_period(_F5_FIXTURE)
    inputs = ReviewInputs(line_source=lambda: [], provider=None, reader=reader)
    result = review(cfg, period, inputs, persist_artifacts=False)
    assert result.status == "completed" and result.compile_output is not None

    res = generate_upload_dossiers(result)

    assert res.capped is False
    assert res.proposals, "expected staged proposals over the F5 findings"
    for proposal in res.proposals:
        assert proposal.status == "pending", "cage never approves/seals/emits -- PENDING only"
        assert proposal.status not in {"approved", "executed"}

    assert res.dossiers, "expected per-finding dossiers keyed by finding_id"
    for finding_id in res.dossiers:
        assert re.fullmatch(r"detect:.+:.+", finding_id), (
            f"dossier key must be detect:{{code}}:{{doc_num}}, got {finding_id!r}"
        )


# -- T6 -- bounded guard: cap exceeded degrades, keeps defaults, appends coverage row --------

def test_t6_bounded_cap_degrades_and_keeps_defaults(client, hermetic, monkeypatch):
    """A finding count above _MAX_DOSSIER_FINDINGS skips generation, keeps today's defaults, and
    APPENDS a degraded coverage row (append, never replace).

    FAILS TODAY: ``import agent.upload_dossiers`` is an ImportError (the module does not exist),
    so the test errors at the import line -- failing-first for the right reason (NOT skipped:
    pytest.importorskip is deliberately avoided).
    """
    import agent.upload_dossiers  # noqa: F401 -- ImportError today (failing-first)

    # Cap below the 3 findings the F5 fixture yields (E2/E3/E4) -> cap exceeded.
    monkeypatch.setattr("agent.upload_dossiers._MAX_DOSSIER_FINDINGS", 2, raising=False)

    body = _post_upload(client, {"file": (_F5_NAME, _F5_FIXTURE.read_bytes())})

    rows = _detect_rows(body["queue"])
    assert len(rows) >= 3, "the F5 fixture yields E2/E3/E4 -- more than the cap of 2"
    for row in rows:
        assert row["candidate_framing_text"] == "", "cap exceeded -> framing stays at default"
        assert row["inputs_hash"] == _INPUTS_HASH_DEFAULT, "cap exceeded -> inputs_hash stays default"

    coverage = body["coverage_status"]
    degraded = [r for r in coverage if r.get("check") == "case_file_dossiers"]
    assert degraded, "cap exceeded must APPEND a case_file_dossiers coverage row"
    assert degraded[0]["level"] == "degraded"
    assert degraded[0]["reason"].strip(), "the degraded row must carry a non-empty reason"

    # Append, not replace: the pre-existing coverage rows survive.
    checks = {r["check"] for r in coverage}
    assert "NO_GST_REG" in checks, "pre-existing coverage rows must still be present (append)"


# -- T7 -- qualifier unit (Terry R5 Option 1): reason-suffixed PLAIN-STRING missing entries ---

def test_t7_dossier_queue_fields_missing_are_reason_suffixed_strings():
    """dossier_queue_fields renders completeness.missing as reason-suffixed PLAIN STRINGS.

    A missing slot in UNGATHERABLE_ON_UPLOAD renders "<slot> -- not gatherable on this source ...";
    any other missing slot renders "<slot> -- ... gathering failed". All entries are str (the
    frontend Completeness type pins missing: string[]).

    TERRY'S R5 CONDITION (pinned before it is needed): this qualifier currently fires for ZERO
    finding types on Xero -- E2/E3/E4 have no missing slots -- so the distinction is exercised
    here on a crafted NO_GST_REG-shaped dossier only, so it is locked before any finding type
    needs it on this path.

    FAILS TODAY: ``from agent.upload_dossiers import dossier_queue_fields`` is an ImportError.
    """
    from agent.dossier import DossierArtifact  # exists today
    from agent.upload_dossiers import dossier_queue_fields  # ImportError today

    dossier = DossierArtifact(
        finding_id="detect:NO_GST_REG:BILL-1",
        check_id="NO_GST_REG",
        finding_type="deterministic",
        evidence={},
        candidate_framing_text=(
            "Candidate for review: input tax claimed from a supplier with no GST registration "
            "number -- consider reviewing document BILL-1. This is not a verdict."
        ),
        completeness={
            "required": ["purchase_invoices", "supplier_catalog", "sales_invoices"],
            "present": ["purchase_invoices"],
            "missing": ["supplier_catalog", "sales_invoices"],
            "satisfied": False,
        },
        inputs_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
    )

    fields = dossier_queue_fields(dossier)
    assert set(fields.keys()) == {"candidate_framing_text", "completeness", "inputs_hash"}

    missing = fields["completeness"]["missing"]
    assert missing and all(isinstance(m, str) for m in missing), "missing entries must be plain strings"

    supplier = next(m for m in missing if m.startswith("supplier_catalog"))
    sales = next(m for m in missing if m.startswith("sales_invoices"))
    assert re.search(r"not gatherable on this source", supplier, re.I), (
        "an UNGATHERABLE_ON_UPLOAD slot renders the 'not gatherable on this source' reason"
    )
    assert re.search(r"gathering failed", sales, re.I), (
        "any other missing slot renders the 'gathering failed' reason"
    )


# -- T8 -- zero key churn (guard pin: passes today AND after) --------------------------------

def test_t8_zero_key_churn(client, hermetic):
    """A populated F5 upload does not churn any key set.

    GUARD PIN -- this PASSES today and after the build: it locks that threading dossiers changes
    only VALUES, never the QUEUE_ITEM_KEYS row contract nor the 5-key top-level upload literal.
    """
    body = _post_upload(client, {"file": (_F5_NAME, _F5_FIXTURE.read_bytes())})
    assert set(body.keys()) == _F5_TOP_KEYS
    for row in body["queue"]:
        assert set(row.keys()) == set(QUEUE_ITEM_KEYS), f"queue row keys drifted: {set(row.keys())}"
