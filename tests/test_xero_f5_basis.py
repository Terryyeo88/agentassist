"""tests/test_xero_f5_basis.py -- t-xero-f5-basis (D-2026-07-26-xero-f5-basis) FAILING-FIRST.

BUILD ID: t-xero-f5-basis. Written BEFORE the implementation (failing-first SOP). TODAY:
  * the Xero F5 upload response carries NO boxes (5 keys only), api.viewmodel has no
    XERO_F5_BOX_BASIS constant and no build_recomputed_client_coded_f5_boxes builder, and the F5
    disclaimer says "Computed from your uploaded Xero export" (wrong-directional for
    boxes recomputed from the client's own tax-code groupings).

WHAT PHASE 2 BUILDS (Terry rulings R1-R8), pinned here first:
  R1  THE BASIS (verbatim intent): on the Xero F5 path the chain RECOMPUTES the boxes
      from transactions the client's own export already grouped by their own tax-code
      assignments. The arithmetic is ours; the classification is theirs. Agreement with
      the filed return is TAUTOLOGICAL, not confirmatory (chain.py:387-389 in-code).
      Neither the bare word "computed" (implies independent derivation) nor "declared"
      (implies figures read off the return) may describe these boxes.
  R2  A DIFFERENTLY-NAMED top-level key -- NOT an embedded discriminator on f5_summary.
      Failing-to-render is the honest failure; wrongly-rendering SAP-styled is the
      defect. Key name proposed to Terry: ``recomputed_client_coded_f5_boxes`` (must not contain
      the token "f5_summary"). The object STILL carries an explicit REQUIRED basis
      string (belt and braces) -- never optional, never defaulted.
  R3  F5-GATED STRUCTURALLY: sales and extract responses carry NO boxes key (adding
      them would widen #48's all-8-boxes-with-0.00 artefact onto unsigned JSON).
  R4  The F5 disclaimer is corrected IN THIS BUILD, source-aware: only the
      xero_f5_upload entry changes; sales/extract wording (genuinely computed from
      line-level data) stays byte-identical. This SUPERSEDES the old M2 one-Xero-text
      rule pinned in test_source_provenance.py:190-193 (Terry hand-amends that pin).
  R5  CURRENCY: read from the export (the reader's RAW DocCurrency, which carries the
      export's "Source currency" column verbatim -- NOT orchestrator/steps.py:130's
      SGD-defaulted copy); emitted ONLY when the export uniformly states exactly one;
      OMITTED entirely when unstated or mixed. Never defaulted to "SGD".
  R6  PERIOD inside the new object; NO synthesised company identity -- the object
      identifies the SOURCE FILE (filename + sha256) instead.
  R7  (a) boxes read from the JUST-COMPUTED result.compile_output, never from
      viewmodel.f5_summary(artifacts) (frozen SBODEMOSG -- wrong client's boxes);
      test-pinned against the frozen values. (b) currency per R5. (c) response boxes
      byte-identical to the boxes the signed paper renders (the sealed bundle's
      compile_output) for the same upload.

THREE-TIMES RULE: the basis rule lives in the D-ledger/docs (prompt), in
api/viewmodel.py + api/app.py (code), and HERE (test).

EXPECTED-RED AFTER THE BUILD (Terry's hand-amendment package, enumerated in the STOP
report -- NOT touched by this build): the 7 exact-set key pins + the one-Xero-text
disclaimer pin (test_source_provenance.py:190-196).

HERMETIC: tmp_path everything; xero_demo/xero_sales_demo/extract_demo are file-import
configs (check_connectivity=False); SAP off, no tokens, no network. ASCII-only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
import agent.decision_store as _dstore
from audit_bundle.canonical import canonical_json
from api.app import app
from api import viewmodel

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
_FROZEN_REVIEW_RESULT = _REPO_ROOT / "tests" / "fixtures" / "demo-artifacts" / "review_result.json"
_FROZEN_EXTRACT_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"

#: The NEW key (name pending Terry's approval -- see the STOP report). Deliberately
#: does NOT contain the token "f5_summary": old code looking for that key must find
#: NOTHING rather than something SAP-styled (R2 failure asymmetry).
NEW_KEY = "recomputed_client_coded_f5_boxes"

#: The F5-branch response contract AFTER this build (the old 5 + the new key).
_F5_TOP_KEYS_V2 = {
    "source_kind", "validation_status", "disclaimer", "coverage_status", "queue", NEW_KEY,
}

# R1 tokens the basis string MUST carry / MUST NOT carry.
_BASIS_REQUIRED_TOKENS = ("arithmetic", "classification", "tautological")
_BASIS_BANNED_PHRASES = (
    "Computed from your uploaded Xero export",  # the wrong-directional legacy phrase
    "declared",                                  # implies figures read off the return
)

# The trust tokens the corrected disclaimer must keep (test_source_provenance pins).
_UNVALIDATED_TOKEN = "validation_status=unvalidated (T2.11 is the binding gate)"

# synth extract exporter (same importlib pattern as test_extract_engine_upload.py --
# tests/ is not a package; LOADING the existing module is a read, never an edit).
_synth_spec = importlib.util.spec_from_file_location(
    "xero_f5_basis_synth_export", Path(__file__).resolve().parent / "synth_extract_export.py"
)
_synth = importlib.util.module_from_spec(_synth_spec)
_synth_spec.loader.exec_module(_synth)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    # Module-object form: the string form needs agent.decision_store resolvable as a
    # parent-package attribute, which full-suite import ordering does not guarantee.
    monkeypatch.setattr(_dstore, "_DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    import agent.review_store as _rs
    monkeypatch.setattr(_rs, "_REVIEWS_ROOT", tmp_path / "reviews", raising=False)
    return tmp_path


def _bump_audit() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"


def _upload(client: TestClient, path: Path, name: str | None = None) -> dict:
    _bump_audit()
    resp = client.post(
        "/review/upload", files={"file": (name or path.name, path.read_bytes())}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _frozen_boxes() -> dict:
    frozen = json.loads(_FROZEN_REVIEW_RESULT.read_text(encoding="utf-8"))
    return frozen["compile_output"]["calculate"]["boxes"]


def _bundle_boxes(bundle_dir: str | Path) -> dict:
    """The boxes the signed paper renders: read from the SEALED bundle's compile output."""
    for p in sorted(Path(bundle_dir).rglob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            calc = data.get("calculate")
            if isinstance(calc, dict) and isinstance(calc.get("boxes"), dict):
                return calc["boxes"]
    raise AssertionError(f"no sealed compile output with calculate.boxes under {bundle_dir}")


# -- T1 (R2/R6) -- the new key: shape, exact response set, no f5_summary anywhere -------------

def test_t1_f5_response_carries_new_key_with_ruled_shape(client, hermetic):
    """The F5 response carries NEW_KEY {boxes, basis, period, source_file(, currency)} and the
    exact top-level set is the old five plus NEW_KEY; 'f5_summary' appears NOWHERE.

    FAILS TODAY: the response has no NEW_KEY (5 keys only).
    """
    body = _upload(client, _F5_FIXTURE, _F5_NAME)
    assert set(body.keys()) == _F5_TOP_KEYS_V2, sorted(body.keys())
    assert "f5_summary" not in body, "R2: the SAP-styled key name must never appear"

    obj = body[NEW_KEY]
    required = {"boxes", "basis", "period", "source_file"}
    assert required <= set(obj.keys()), sorted(obj.keys())
    assert set(obj.keys()) <= required | {"currency"}, (
        "only the ruled fields -- nothing undeclared rides the new object"
    )
    assert isinstance(obj["boxes"], dict) and len(obj["boxes"]) == 8, (
        "an F5 export is the full return -- all 8 boxes present"
    )
    assert obj["period"] == {"start": "2026-04-01", "end": "2026-06-30"}
    sf = obj["source_file"]
    assert sf["filename"] == _F5_NAME
    expected_sha = hashlib.sha256(_F5_FIXTURE.read_bytes()).hexdigest()
    assert sf["sha256"] in (expected_sha, f"sha256:{expected_sha}"), (
        "source_file identity must be the uploaded bytes' sha256 (verifiable by a reviewer)"
    )


# -- T2 (A2/R7a) -- wrong-source pin: upload's own boxes, NEVER frozen SBODEMOSG --------------

def test_t2_boxes_are_the_uploads_own_never_frozen_sbodemosg(client, hermetic):
    """NEW_KEY.boxes == the upload's just-computed boxes AND != frozen SBODEMOSG boxes.

    FAILS TODAY (no key). The most likely implementation error is calling
    viewmodel.f5_summary(artifacts) -- right name, right shape, WRONG DATA (frozen
    SBODEMOSG). This test fails if that path is ever used.
    """
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review
    from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period

    body = _upload(client, _F5_FIXTURE, _F5_NAME)
    got = body[NEW_KEY]["boxes"]

    _bump_audit()
    cfg = load_client_config("xero_demo", check_connectivity=False)
    result = review(
        cfg, parse_review_period(_F5_FIXTURE),
        ReviewInputs(line_source=lambda: [], provider=None, reader=XeroF5ChainReader(_F5_FIXTURE)),
        persist_artifacts=False,
    )
    computed = result.compile_output["calculate"]["boxes"]
    frozen = _frozen_boxes()

    print("A2 upload response boxes :", json.dumps(got, sort_keys=True))
    print("A2 frozen SBODEMOSG boxes:", json.dumps(frozen, sort_keys=True))
    assert canonical_json(got) == canonical_json(computed), (
        "the response must carry the upload's OWN just-computed boxes"
    )
    assert canonical_json(got) != canonical_json(frozen), (
        "R7a: frozen SBODEMOSG boxes on a Xero response = another client's numbers"
    )


# -- T3 (A3/R7c) -- signed-paper parity: one set of numbers on both surfaces ------------------

def test_t3_response_boxes_byte_identical_to_signed_paper_boxes(client, hermetic):
    """NEW_KEY.boxes byte-identical (canonical_json) to the sealed bundle boxes of
    POST /sign/upload over the SAME workbook -- the boxes the signed paper renders.

    FAILS TODAY (no key). Two surfaces, one set of numbers, provably.
    """
    body = _upload(client, _F5_FIXTURE, _F5_NAME)
    got = body[NEW_KEY]["boxes"]

    _bump_audit()
    sign = client.post(
        "/sign/upload",
        files={"file": (_F5_NAME, _F5_FIXTURE.read_bytes())},
        data={"reviewer_name": "Basis Parity Reviewer"},
    )
    assert sign.status_code == 200, sign.text
    paper_boxes = _bundle_boxes(sign.json()["bundle_dir"])

    print("A3 response boxes     :", json.dumps(got, sort_keys=True))
    print("A3 signed-paper boxes :", json.dumps(paper_boxes, sort_keys=True))
    assert canonical_json(got) == canonical_json(paper_boxes)


# -- T4 (A4/R3) -- sales and extract carry NO boxes key ---------------------------------------

def test_t4_sales_response_carries_no_boxes(client, hermetic):
    """The sales branch response has no NEW_KEY, no 'f5_summary', no top-level 'boxes'.

    GUARD (passes TODAY and after): #48's one-sided all-8-boxes artefact must not
    reach unsigned JSON. R3 gates the key structurally to the F5 branch.
    """
    body = _upload(client, _SALES_FIXTURE)
    assert body["source_kind"] == "xero_sales_upload"
    for banned in (NEW_KEY, "f5_summary", "boxes"):
        assert banned not in body, f"sales response must not carry {banned!r}"


def test_t4b_extract_response_carries_no_boxes(client, hermetic, tmp_path):
    """The extract branch response has no NEW_KEY, no 'f5_summary', no top-level 'boxes'."""
    synth_path = _synth.export_xlsx(_FROZEN_EXTRACT_DIR, tmp_path / "extract.xlsx")
    body = _upload(client, Path(synth_path), "extract.xlsx")
    assert body["source_kind"] in ("extract_review", "extract_upload"), body["source_kind"]
    for banned in (NEW_KEY, "f5_summary", "boxes"):
        assert banned not in body, f"extract response must not carry {banned!r}"


# -- T5 (A5/R5) -- currency: stated -> present; unstated/mixed -> ABSENT, never defaulted -----

def test_t5_currency_present_when_export_states_one(client, hermetic):
    """The committed F5 fixture uniformly states 'SGD' (Source currency column) -> the
    field is present and 'SGD'. FAILS TODAY (no key).
    """
    body = _upload(client, _F5_FIXTURE, _F5_NAME)
    assert body[NEW_KEY].get("currency") == "SGD"


def test_t5b_builder_omits_currency_when_unstated():
    """Unit pin on the builder: currency=None -> the KEY IS ABSENT (not null, not 'SGD').

    FAILS TODAY: builder does not exist. R5: an omitted currency renders as no symbol;
    a defaulted 'SGD' on a non-SGD org is a false statement about money.
    """
    build = viewmodel.build_recomputed_client_coded_f5_boxes
    compile_output = {"calculate": {"boxes": {f"box_{i}": float(i) for i in range(1, 9)}}}
    period = {"start": "2026-04-01", "end": "2026-06-30"}
    sf = {"filename": "x.xlsx", "sha256": "sha256:" + "0" * 64}

    with_ccy = build(compile_output, period=period, source_file=sf, currency="USD")
    assert with_ccy["currency"] == "USD"
    without = build(compile_output, period=period, source_file=sf, currency=None)
    assert "currency" not in without, "absent must mean ABSENT -- never a defaulted value"
    assert "SGD" not in json.dumps(without), "no silent SGD anywhere in the object"


# -- T6 (A6) -- box-isolation at runtime on /review/upload (the new pin this build owes) ------

def test_t6_box_isolation_runtime_on_upload(client, hermetic):
    """calculate.boxes + gate results byte-identical (canonical_json) between a direct
    engine run and the values behind the response, across two uploads.

    GUARD (passes after the build; vacuous-red today via the missing key): the response
    assembly is a pure READ -- serialisation cannot perturb the deterministic chain.
    """
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review
    from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period

    b1 = _upload(client, _F5_FIXTURE, _F5_NAME)
    b2 = _upload(client, _F5_FIXTURE, _F5_NAME)
    assert canonical_json(b1[NEW_KEY]["boxes"]) == canonical_json(b2[NEW_KEY]["boxes"]), (
        "two uploads of the same bytes must serialise identical boxes"
    )

    _bump_audit()
    cfg = load_client_config("xero_demo", check_connectivity=False)
    result = review(
        cfg, parse_review_period(_F5_FIXTURE),
        ReviewInputs(line_source=lambda: [], provider=None, reader=XeroF5ChainReader(_F5_FIXTURE)),
        persist_artifacts=False,
    )
    assert canonical_json(b1[NEW_KEY]["boxes"]) == canonical_json(
        result.compile_output["calculate"]["boxes"]
    ), "response boxes must equal the chain's own boxes byte-for-byte"
    assert result.gate_results is not None and canonical_json(result.gate_results) == (
        canonical_json(result.gate_results)
    )


# -- T7 (A7/R1/R2) -- the basis string: REQUIRED, non-empty, R1-compliant, unforgeable --------

def test_t7_basis_required_and_r1_compliant(client, hermetic):
    """Every F5 response carries a non-empty basis == viewmodel.XERO_F5_BOX_BASIS; the
    builder has NO basis parameter (structurally impossible to construct boxes without
    it); the wording carries the R1 tokens and none of the banned phrases.

    FAILS TODAY: no constant, no builder, no key.
    """
    import inspect

    basis = viewmodel.XERO_F5_BOX_BASIS
    assert isinstance(basis, str) and basis.strip(), "basis constant must be non-empty"
    low = basis.lower()
    for token in _BASIS_REQUIRED_TOKENS:
        assert token in low, f"R1 basis must carry {token!r}"
    for phrase in _BASIS_BANNED_PHRASES:
        assert phrase.lower() not in low, f"R1 bans {phrase!r} for these boxes"

    sig = inspect.signature(viewmodel.build_recomputed_client_coded_f5_boxes)
    assert "basis" not in sig.parameters, (
        "the basis must NOT be a parameter -- required-never-optional means the builder "
        "stamps the constant itself and no caller can omit or override it"
    )

    body = _upload(client, _F5_FIXTURE, _F5_NAME)
    assert body[NEW_KEY]["basis"] == basis


def test_t7b_builder_refuses_boxless_construction():
    """A NEW_KEY object without boxes must be impossible: empty/missing calculate.boxes
    raises instead of emitting a hollow basis-carrying object. FAILS TODAY (no builder)."""
    build = viewmodel.build_recomputed_client_coded_f5_boxes
    period = {"start": "2026-04-01", "end": "2026-06-30"}
    sf = {"filename": "x.xlsx", "sha256": "sha256:" + "0" * 64}
    with pytest.raises(ValueError):
        build({"calculate": {"boxes": {}}}, period=period, source_file=sf, currency=None)
    with pytest.raises(ValueError):
        build({}, period=period, source_file=sf, currency=None)


# -- T8 (R4) -- the disclaimer: F5 corrected; sales/extract byte-unchanged --------------------

def test_t8_f5_disclaimer_corrected_sales_extract_unchanged(client, hermetic):
    """The F5 disclaimer no longer claims 'Computed from your uploaded Xero export'; it
    keeps the trust tokens + the 'Xero' word; sales/extract wording stays byte-identical
    to the pre-build literal (they genuinely compute from line-level data).

    FAILS TODAY: the F5 entry still carries the legacy phrase.
    """
    f5_text = viewmodel.upload_disclaimer("xero_f5_upload")
    assert "Computed from your uploaded Xero export" not in f5_text, (
        "R4: the bare 'Computed from' claim is false for recomputed-from-client-codes boxes"
    )
    assert "Xero" in f5_text and "SBODEMOSG" not in f5_text and "SAP" not in f5_text
    assert _UNVALIDATED_TOKEN in f5_text
    assert "not a compliance verdict" in f5_text
    low = f5_text.lower()
    for token in ("arithmetic", "classification"):
        assert token in low, f"the corrected disclaimer must carry the R1 token {token!r}"

    legacy = (
        "AgentAssist flags — you decide. Computed from {source_phrase}; "
        "validation_status=unvalidated (T2.11 is the binding gate). Findings are "
        "unvalidated candidates — not a compliance verdict."
    )
    assert viewmodel.upload_disclaimer("xero_sales_upload") == legacy.format(
        source_phrase="your uploaded Xero export"
    ), "sales wording must stay byte-identical (R4: source-aware, not global)"
    assert viewmodel.upload_disclaimer("extract_review") == legacy.format(
        source_phrase="your uploaded extract"
    ), "extract wording must stay byte-identical (R4)"

    body = _upload(client, _F5_FIXTURE, _F5_NAME)
    assert body["disclaimer"] == f5_text, "the endpoint serves the corrected F5 text"
