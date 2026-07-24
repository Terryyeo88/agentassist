"""tests/test_fingerprint_v1.py -- t-fingerprint-v1 (D-2026-07-24-fingerprint-v1) FAILING-FIRST.

BUILD ID: t-fingerprint-v1. Written BEFORE the implementation exists (failing-first SOP); the
v1 tests below MUST fail today for the RIGHT reason -- TODAY:
  * FINGERPRINT_KEYS is the 2-tuple ("error_code", "counterparty"); doc_num is IGNORED;
  * _normalize_counterparty does strip()+casefold() only (NO internal-whitespace collapse);
  * there is NO FINGERPRINT_VERSION constant, NO AdjudicationEntry.fingerprint_version field,
    NO count_superseded_entries helper, and NO "superseded_decisions" view key.

WHAT PHASE 2 BUILDS (Terry rulings R1-R5 + R2b), pinned here BEFORE implementation:
  1. WIDENED v1 key: FINGERPRINT_KEYS becomes ("error_code","counterparty","doc_num").
     doc_num canonical form (R2, named fn _normalize_doc_num): absent/None -> "" (NEVER "None");
     else str(doc_num).strip() -- NO casefold, NO int() coercion. int 605 == str "605".
  2. R2b: _normalize_counterparty ALSO collapses internal whitespace -- " ".join(str(x).split())
     then casefold: "OldRate  Supplies" (2 spaces) == "OldRate Supplies".
  3. FINGERPRINT_VERSION = "v1" module constant; AdjudicationEntry gains
     fingerprint_version: Optional[str] = None; append() stamps "v1" on every NEW entry and the
     stored JSONL line carries it.
  4. R4 ABSENCE-AWARE HASHING: a v0 entry (fingerprint_version None/absent) hashes over the
     HISTORICAL field-set WITHOUT the version key -> historical entry_hash literals UNCHANGED; a
     v1 entry includes fingerprint_version in its hashed fields; verify() passes over a mixed chain.
  5. R1 INERT RULE + count_superseded_entries(entries)->int: a stored v0 entry does NOT apply to
     v1 findings (its stored key was computed under the superseded composition, so the recomputed
     v1 lookup never matches it); a helper counts stored entries whose fingerprint_version is
     absent/pre-current; GET /review-session/{id} gains an ADDITIVE "superseded_decisions":
     {client_id: count} over the active slices' distinct client_ids (data only; nothing renders).

THREE-TIMES RULE: the "v1 widened+versioned fingerprint, absence-aware hashing, v0 inert, historical
literals frozen" invariant lives in the panel/ledger spec (prompt), will be enforced in
agent/decision_ledger.py + agent/decision_store.py + api/app.py (code), and is asserted HERE (test).

CONTRACT PINS (chosen deliberately so the builder conforms -- the test is the third leg):
  * count_superseded_entries takes an iterable of STORED ENTRY DICTS (the JSONL form returned by
    load_decision_entries) and returns an int. Located in decision_ledger OR decision_store -- the
    _count_superseded shim below tolerates either module (flagged in the task report).
  * "superseded_decisions" is an ADDITIVE key on GET /review-session/{id}; existing keys unchanged.

GUARD (non-failing-first) TESTS -- pass TODAY *and* after (stated per-docstring): T8 (A3 crux
regression), T9 (A5 runtime determinism), T10 (R-6 regen-tolerant key-pin).

HERMETIC: tmp_path everything; engine PDF dir + audit root + decision store + review store all
redirected to tmp (mirrors tests/test_review_accumulation.py:96-113). Per-upload fresh audit
subdir (seal.run_ts seconds resolution -> per-call bump). xero_demo is a file-import (non-SAP)
client loaded with check_connectivity=False; dummy SAP creds are harmless. No anthropic import;
SAP off, no tokens, no network. ASCII-only.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from audit_bundle.canonical import canonical_json
from agent.decision_ledger import (
    KNOWN_ACCEPTED,
    AdjudicationEntry,  # noqa: F401  (documents the type under test)
    DecisionLedger,
    FINGERPRINT_KEYS,
    _fingerprint_fields,
    annotate_and_demote,
    compute_finding_fingerprint,
)
from api.app import app

# Each engine-running request gets its OWN audit subdir (seal.run_ts seconds resolution ->
# two uploads in one second collide on one read-only bundle dir; per-call bump sidesteps it).
_UPLOAD_SEQ = itertools.count()

_REPO_ROOT = Path(__file__).resolve().parents[1]

_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_F5_NAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

# The REAL frozen v0 ledger fixture -- its fingerprint AND entry_hash are historical literals.
_FROZEN_LEDGER = _REPO_ROOT / "tests" / "fixtures" / "demo-artifacts" / "decision-ledger.json"

# The known GOLDEN v0 (2-key) fingerprint for E4 / "OldRate Supplies Pte Ltd" -- the same literal
# pinned in tests/test_decision_reapply_upload.py:75-77 as the #46 migration tripwire. Under the
# CURRENT 2-key algorithm compute_finding_fingerprint({error_code:"E4", card_name:"OldRate Supplies
# Pte Ltd"}) == this value; the doc_num is IGNORED today. After the v1 widening the recomputed key
# NO LONGER equals it (doc_num enters the key) -- which is exactly the inert-rule pivot in T6.
_GOLDEN_V0_E4 = "sha256:265e9b4e92baa689143df7f1384560a0f337d325105d38c8499c6595c42b159e"

# The E4 finding whose 2-key fingerprint is _GOLDEN_V0_E4 (card_name is the counterparty source).
_E4_FINDING = {
    "error_code": "E4",
    "card_name": "OldRate Supplies Pte Ltd",
    "doc_num": "BILL-3002",
}

# The v0 base key set the frozen fixture carries today (R-6 regen-tolerant pin; see T10).
_V0_BASE_KEYS = {
    "disposition", "entry_hash", "entry_id", "fingerprint", "period",
    "prev_hash", "reason", "reviewer", "timestamp",
}


def _count_superseded(entries):
    """Resolve count_superseded_entries from decision_ledger OR decision_store (contract shim).

    Pinned contract: takes an iterable of STORED ENTRY DICTS, returns an int count of those whose
    fingerprint_version is absent/pre-current. Absent in BOTH modules today -> the assertion below
    is the (right-reason) failing signal. Location tolerated so the builder may place it in either
    module; the ambiguity is flagged in the task report.
    """
    import agent.decision_ledger as dl
    import agent.decision_store as ds

    fn = getattr(dl, "count_superseded_entries", None) or getattr(
        ds, "count_superseded_entries", None
    )
    assert fn is not None, (
        "count_superseded_entries must exist in agent.decision_ledger or agent.decision_store "
        "(absent today -- this is the failing-first signal)"
    )
    return fn(list(entries))


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Engine PDF dir + audit root + decision store + review store all redirected to tmp."""
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


def _upload_resp(client: TestClient, file_bytes: bytes, name: str, review_id=None):
    _bump_audit()
    data = {"review_id": review_id} if review_id is not None else None
    return client.post("/review/upload", files={"file": (name, file_bytes)}, data=data)


def _post_upload(client: TestClient, file_bytes: bytes, name: str, review_id=None) -> dict:
    resp = _upload_resp(client, file_bytes, name, review_id=review_id)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _new_review(label: str = "") -> str:
    import agent.review_store as rs
    return rs.create_review(label)["review_id"]


# -- T1 (A2) -- the former collision pair is now DISTINCT ------------------------------------

def test_t1_collision_pair_now_distinct():
    """Two E4/"OldRate Supplies" findings differing ONLY in doc_num get DIFFERENT fingerprints.

    FAILS TODAY (run-proven): FINGERPRINT_KEYS is the 2-tuple, doc_num is ignored, so both
    findings hash to the SAME value and `a != b` is red. After the v1 widening doc_num enters the
    key and the two diverge.
    """
    a = compute_finding_fingerprint(
        {"error_code": "E4", "card_name": "OldRate Supplies Pte Ltd", "doc_num": "BILL-3002"}
    )
    b = compute_finding_fingerprint(
        {"error_code": "E4", "card_name": "OldRate Supplies Pte Ltd", "doc_num": "BILL-3999"}
    )
    assert a != b, (
        "doc_num must discriminate the fingerprint (v1 widening): "
        f"BILL-3002={a} vs BILL-3999={b}"
    )


# -- T2 (R2) -- int/str doc_num unify; absent == None; the field is "" never "None" ----------

def test_t2_doc_num_normalization_int_str_and_absence():
    """doc_num canonicalisation: 605 == "605" == " 605 "; absent == None; field value is "".

    FAILS TODAY: doc_num is not in the key at all, so a doc-bearing finding and a doc-LESS finding
    hash EQUAL -- the `doc-bearing != doc-less` assertion bites -- and _fingerprint_fields returns
    no "doc_num" key so `fields["doc_num"] == ""` raises KeyError. After v1 both hold: str(605)
    strips to "605" (NO int() coercion), None/absent canonicalise to "" (NEVER the string "None").
    """
    base = {"error_code": "E4", "card_name": "OldRate Supplies Pte Ltd"}

    fp_int = compute_finding_fingerprint({**base, "doc_num": 605})
    fp_str = compute_finding_fingerprint({**base, "doc_num": "605"})
    fp_ws = compute_finding_fingerprint({**base, "doc_num": " 605 "})
    assert fp_int == fp_str == fp_ws, (
        "int 605, str '605' and ' 605 ' must canonicalise to the SAME doc_num key "
        f"(int={fp_int}, str={fp_str}, ws={fp_ws})"
    )

    fp_absent = compute_finding_fingerprint(base)  # no doc_num key at all
    fp_none = compute_finding_fingerprint({**base, "doc_num": None})
    assert fp_absent == fp_none, "absent doc_num and doc_num=None must produce the SAME fingerprint"

    # The bite: today doc_num is ignored so this is EQUAL (red); v1 makes doc-bearing distinct.
    assert fp_int != fp_absent, (
        "a doc-bearing finding must NOT share a fingerprint with a doc-less one (doc_num in key)"
    )

    # The empty-doc_num field is the empty string, never the literal "None".
    fields_none = _fingerprint_fields({**base, "doc_num": None})
    assert fields_none["doc_num"] == "", "empty doc_num canonicalises to '' (never 'None')"
    fields_absent = _fingerprint_fields(base)
    assert fields_absent["doc_num"] == "", "absent doc_num canonicalises to '' (never 'None')"


# -- T3 (R2b) -- counterparty internal-whitespace collapse -----------------------------------

def test_t3_counterparty_internal_whitespace_collapse():
    """"OldRate  Supplies Pte Ltd" (2 spaces) == "OldRate Supplies Pte Ltd" (1 space); still
    strip + casefold.

    FAILS TODAY (run-proven): _normalize_counterparty only strips + casefolds, so the internal
    double-space survives and the two names hash DIFFERENTLY -- the first assertion is red. After
    R2b the counterparty is `" ".join(str(x).split()).casefold()`, collapsing internal runs.
    """
    base = {"error_code": "E4", "doc_num": "BILL-3002"}

    a = compute_finding_fingerprint({**base, "card_name": "OldRate  Supplies Pte Ltd"})  # 2 spaces
    b = compute_finding_fingerprint({**base, "card_name": "OldRate Supplies Pte Ltd"})   # 1 space
    assert a == b, (
        "internal-whitespace runs must collapse (R2b): "
        f"two-space={a} vs one-space={b}"
    )

    # strip + casefold still hold (this half already passes today -- guards against regression).
    c = compute_finding_fingerprint({**base, "card_name": "  OLDRATE supplies pte ltd "})
    assert b == c, "leading/trailing whitespace + case must still normalise away"


# -- T4 -- FINGERPRINT_VERSION constant + append stamps v1 + JSONL carries it -----------------

def test_t4_fingerprint_version_constant_and_stamp(tmp_path):
    """FINGERPRINT_VERSION == "v1" exists; append() stamps it; append_decision persists it.

    FAILS TODAY: there is no FINGERPRINT_VERSION module constant (getattr -> None), no
    AdjudicationEntry.fingerprint_version field (getattr -> None), and append_decision writes a
    JSONL line WITHOUT that key. All three assertions are red until Phase 2 adds the constant,
    the dataclass field, and the append-time stamp.
    """
    import agent.decision_ledger as dl
    from agent.decision_store import append_decision

    assert getattr(dl, "FINGERPRINT_VERSION", None) == "v1", (
        "module constant FINGERPRINT_VERSION must equal 'v1'"
    )

    entry = dl.DecisionLedger().append(
        fingerprint="sha256:deadbeef", disposition=KNOWN_ACCEPTED, reviewer="Reviewer",
    )
    assert getattr(entry, "fingerprint_version", None) == "v1", (
        "append() must stamp fingerprint_version='v1' on every new entry"
    )

    append_decision(
        "xero_demo", fingerprint="sha256:deadbeef", disposition=KNOWN_ACCEPTED,
        reviewer="Reviewer", root=tmp_path,
    )
    ledger_file = tmp_path / "xero_demo" / "ledger.jsonl"
    lines = [json.loads(ln) for ln in ledger_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, "append_decision must write a JSONL line"
    assert lines[-1].get("fingerprint_version") == "v1", (
        "the persisted JSONL line must carry \"fingerprint_version\": \"v1\""
    )


# -- T5 (A7 + R4) -- historical literals UNCHANGED; mixed-chain verify; new entry is v1 -------

# The REAL pre-regen v0 entry, frozen as a LITERAL (A7). Provenance: this is
# tests/fixtures/demo-artifacts/decision-ledger.json exactly as committed at 082703d,
# BEFORE the Terry-directed E regen reseeded the fixture under v1 (commit 89ee218).
# The on-disk fixture is now a v1 chain, so the historical v0 entry lives here as the
# unchanged-literal witness. A hand-copied hash cannot silently drift: verify() below
# RECOMPUTES the chain from these very fields and must reproduce entry_hash.
_HISTORICAL_V0_ENTRY = {
    "disposition": "KNOWN_ACCEPTED",
    "entry_hash": "sha256:3c4ff0c15286ffe0794bda49e1ac6d4c394a03878e390c2f670c367a23cd631d",
    "entry_id": "b986d57f-57ac-46fa-bed7-eeed032111f3",
    "fingerprint": "sha256:3d87ffc03f96938b1dbf236e133515595b514b099397deabae8e8ec1d15ed715",
    "period": "2024Q2",
    "prev_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    "reason": "Standing treatment: supplier confirmed not GST-registered; input tax correctly not claimed.",
    "reviewer": "Prior-Period Reviewer",
    "timestamp": "2024-06-30T00:00:00+00:00",
}


def test_t5_historical_entry_hash_frozen_and_mixed_chain(tmp_path):
    """The historical v0 entry keeps its entry_hash LITERAL; a new v1 entry chains cleanly.

    The v0 witness is the EMBEDDED literal above (the frozen fixture entry as it stood
    before the R3-sequence regen): the regenerated on-disk fixture is now a v1 chain, so
    the literal here carries the A7 unchanged-history assertion. verify() recomputes the
    chain from the literal's own fields, so no algorithm change can hide behind it.

    R4 absence-aware hashing must keep the OLD entry_hash byte-identical (a version-less
    entry hashes over the historical field-set WITHOUT the version key) while a NEWLY
    appended entry hashes over its version-bearing field-set, and verify() must pass over
    the MIXED chain.
    """
    ledger = DecisionLedger.from_entries([dict(_HISTORICAL_V0_ENTRY)])
    ledger.verify()  # absence-aware: the v0 chain still verifies under v1 code
    assert ledger.entries[0].entry_hash == _HISTORICAL_V0_ENTRY["entry_hash"], (
        "the historical v0 entry_hash must be byte-identical to the frozen literal (A7)"
    )
    assert getattr(ledger.entries[0], "fingerprint_version", "__ABSENT__") is None, (
        "a v0 (pre-version) entry must expose fingerprint_version is None"
    )

    new = ledger.append(
        fingerprint="sha256:cafef00d", disposition=KNOWN_ACCEPTED,
        reviewer="Current Reviewer", period="2026Q2",
    )
    ledger.verify()  # MIXED v0+v1 chain must still verify (R4 absence-aware)
    assert getattr(new, "fingerprint_version", "__ABSENT__") == "v1", (
        "a newly appended entry must be stamped v1"
    )
    # The historical literal is STILL unchanged after the append -- widening never rewrites history.
    assert ledger.entries[0].entry_hash == _HISTORICAL_V0_ENTRY["entry_hash"], (
        "appending a v1 entry must not mutate the historical v0 entry_hash"
    )

    # And the ON-DISK fixture has pivoted: the regenerated frozen ledger is a v1 chain now.
    frozen = json.loads(_FROZEN_LEDGER.read_text(encoding="utf-8"))
    assert frozen and frozen[0].get("fingerprint_version") == "v1", (
        "the regenerated frozen fixture must carry fingerprint_version 'v1'"
    )


# -- T6 (R1 inert) -- a stored v0 entry does NOT apply to a v1 finding ------------------------

def test_t6_v0_entry_inert_against_v1_finding():
    """A stored v0 entry keyed on the 2-key GOLDEN literal is INERT against the recomputed v1 key.

    FAILS TODAY (the perfect failing-first): under the 2-key algorithm the recomputed fingerprint
    of the E4/"OldRate Supplies"/BILL-3002 finding EQUALS _GOLDEN_V0_E4, so the stored
    KNOWN_ACCEPTED entry MATCHES and the finding is DEMOTED -- the `demoted is False` assertion is
    red (the sweep-collision applies today). After v1 the recomputed key includes doc_num and no
    longer equals the stored v0 key, so the entry is inert and the finding is un-demoted; and
    count_superseded_entries counts the version-less stored entry (== 1).
    """
    v0_stored = {
        "disposition": KNOWN_ACCEPTED,
        "entry_hash": "sha256:" + "0" * 64,   # placeholder -- annotate_and_demote never verifies
        "entry_id": "legacy-v0-1",
        "fingerprint": _GOLDEN_V0_E4,           # the OLD 2-key hash (no fingerprint_version key)
        "period": "2024Q2",
        "prev_hash": "sha256:" + "0" * 64,
        "reason": "legacy standing treatment",
        "reviewer": "Prior-Period Reviewer",
        "timestamp": "2024-06-30T00:00:00+00:00",
    }
    ledger = DecisionLedger.from_entries([dict(v0_stored)])

    annotated = annotate_and_demote([dict(_E4_FINDING)], ledger)
    assert len(annotated) == 1, "cardinality preserved -- exactly one annotated finding"
    assert annotated[0].demoted is False, (
        "a v0-keyed stored entry must NOT demote a v1 finding (inert rule R1): under the 2-key "
        "algorithm this is red because the recomputed key still equals the stored v0 key"
    )
    assert annotated[0].prior_dispositions == (), "an inert v0 entry contributes no prior dispositions"

    assert _count_superseded([dict(v0_stored)]) == 1, (
        "the version-less stored entry counts as one superseded (pre-current) decision"
    )


# -- T7 -- GET /review-session gains an additive superseded_decisions map --------------------

def test_t7_review_session_superseded_decisions_view_key(client, hermetic):
    """GET /review-session/{id} surfaces superseded_decisions:{client_id:count}; existing keys hold.

    FAILS TODAY: there is no "superseded_decisions" key on the merged view (the merged_view/endpoint
    predate this build) -- the `in view` assertion is red. A LEGACY v0 entry is written DIRECTLY to
    the tmp decisions store (NOT via append_decision, which post-build stamps v1) to simulate a
    pre-migration store; the F5 slice's client_id (xero_demo) is the distinct client_id counted.
    """
    rid = _new_review()
    _post_upload(client, _F5_FIXTURE.read_bytes(), _F5_NAME, review_id=rid)

    # Seed a legacy v0 entry (NO fingerprint_version) straight into the tmp store -- a simulated
    # pre-migration line that append_decision would (post-build) instead stamp with "v1".
    legacy = {
        "disposition": KNOWN_ACCEPTED,
        "entry_hash": "sha256:" + "0" * 64,
        "entry_id": "legacy-v0-store-1",
        "fingerprint": _GOLDEN_V0_E4,
        "period": "2024Q2",
        "prev_hash": "sha256:" + "0" * 64,
        "reason": "legacy standing treatment",
        "reviewer": "Prior-Period Reviewer",
        "timestamp": "2024-06-30T00:00:00+00:00",
    }
    store_dir = hermetic / "decisions" / "xero_demo"
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "ledger.jsonl").write_text(
        json.dumps(legacy, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )

    resp = client.get(f"/review-session/{rid}")
    assert resp.status_code == 200, resp.text
    view = resp.json()

    assert "superseded_decisions" in view, (
        "GET /review-session/{id} must gain an additive 'superseded_decisions' key"
    )
    assert view["superseded_decisions"] == {"xero_demo": 1}, (
        "superseded_decisions counts the legacy version-less entry under the slice's client_id"
    )
    for key in ("slices", "superseded", "coverage_matrix", "signed"):
        assert key in view, f"existing merged-view key {key!r} must remain present"


# -- T8 (A3 crux regression) -- a stored decision key is recomputable from the sealed detect set

def test_t8_stored_decision_key_recomputable_from_detect(client, hermetic):
    """A stored decision fingerprint is IN the set recomputed from the sealed compile-output detect
    issues. GUARD (passes TODAY and after): this is the A3 crux -- an adjudication a reviewer stored
    must map back onto a detect finding. Under v0 the row fingerprint and the recomputed detect
    fingerprint both drop doc_num and match; under v1 both include doc_num and still match -- so the
    intersection stays >= 1 across the widening. It is a regression PIN, not a failing-first test.

    Flow: plain F5 upload -> take the E4 row's fingerprint -> POST /decision (Mark known) ->
    upload F5 into a session -> accumulated sign -> read the bundle's compile-output.json ->
    recompute fingerprints of detect.issues -> assert the stored key is present.
    """
    f5 = _F5_FIXTURE.read_bytes()
    base = _post_upload(client, f5, _F5_NAME)  # stateless upload -> exposes row fingerprints
    target = next(r for r in base["queue"] if r["error_code"] == "E4")
    fp = target["fingerprint"]
    assert isinstance(fp, str) and fp.startswith("sha256:")

    decided = client.post("/decision", json={
        "client_id": "xero_demo",
        "finding_id": target["finding_id"],
        "fingerprint": fp,
        "action": "Mark known",
        "note": "Standing accepted treatment for this supplier.",
        "reviewer_name": "Collin",
    })
    assert decided.status_code == 200, decided.text

    rid = _new_review()
    _post_upload(client, f5, _F5_NAME, review_id=rid)

    _bump_audit()
    signed = client.post(f"/review-session/{rid}/sign", json={"reviewer_name": "Collin"})
    assert signed.status_code == 200, signed.text
    bundle_dir = Path(signed.json()["bundle_dir"])

    compile_output = json.loads((bundle_dir / "compile-output.json").read_text(encoding="utf-8"))
    issues = compile_output["detect"]["issues"]
    recomputed = {compute_finding_fingerprint(issue) for issue in issues}
    assert fp in recomputed, (
        "the stored decision fingerprint must be recomputable from the sealed detect issues "
        "(A3 crux: adjudications map onto detect findings, across the v0->v1 widening)"
    )


# -- T9 (A5 runtime box-isolation) -- two review() runs are byte-identical (determinism) -----

def test_t9_runtime_determinism_boxes_and_gates(hermetic):
    """Two independent review() runs over the SAME F5 bytes yield byte-identical boxes + gate
    results. GUARD (passes TODAY and after): the fingerprint machinery is a READ-ONLY presentation
    layer over compile_output, so it never perturbs the deterministic chain. This is the RUNTIME
    determinism half of box-isolation; the offline-replay ORACLE (A6, elsewhere) covers the frozen
    byte-identity across the whole chain. Not a failing-first test -- a determinism regression pin.
    """
    from config.loader import load_client_config
    from engine.review import ReviewInputs, review
    from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period

    def _run():
        reader = XeroF5ChainReader(_F5_FIXTURE)
        period = parse_review_period(_F5_FIXTURE)
        cfg = load_client_config("xero_demo", check_connectivity=False)
        inputs = ReviewInputs(line_source=lambda: [], provider=None, reader=reader)
        result = review(cfg, period, inputs, persist_artifacts=False)
        assert result.status == "completed" and result.compile_output is not None, (
            "the F5 fixture must complete a review (no halt) for the determinism comparison"
        )
        return result

    r1 = _run()
    r2 = _run()

    assert canonical_json(r1.compile_output["calculate"]["boxes"]) == canonical_json(
        r2.compile_output["calculate"]["boxes"]
    ), "F5 boxes must be byte-identical across two independent runs (determinism)"
    assert canonical_json(r1.gate_results) == canonical_json(r2.gate_results), (
        "gate results must be byte-identical across two independent runs (determinism)"
    )


# -- T10 (R-6) -- regen-tolerant key-pin on the frozen decision-ledger fixture ----------------

def test_t10_frozen_ledger_key_pin_regen_tolerant():
    """Every frozen entry's key set is EITHER the v0 base set OR that set plus fingerprint_version.

    GUARD / documentation pin (passes TODAY): the committed fixture is v0 -- it carries exactly the
    nine v0 keys and NO fingerprint_version, documenting that the fixture stays v0 until Terry's R3
    regeneration. The pin is written REGEN-TOLERANT on purpose: `keys - {"fingerprint_version"} ==
    v0-base` accepts the current v0 fixture AND a future regenerated v1-bearing fixture without
    needing a human amendment. entry_hash + fingerprint are always required.
    """
    frozen = json.loads(_FROZEN_LEDGER.read_text(encoding="utf-8"))
    assert frozen, "the frozen decision-ledger fixture must carry at least one entry"
    for i, entry in enumerate(frozen):
        keys = set(entry.keys())
        assert keys - {"fingerprint_version"} == _V0_BASE_KEYS, (
            f"entry[{i}] key set drifted from the v0 base (regen-tolerant on fingerprint_version): "
            f"{sorted(keys)}"
        )
        assert "entry_hash" in keys and "fingerprint" in keys, (
            f"entry[{i}] must always carry entry_hash + fingerprint"
        )
    # NOTE (regen-tolerant by design): this pin does NOT assert the ABSENCE of fingerprint_version.
    # The committed fixture is v0 today (no fingerprint_version), but Terry's R3 regen will add
    # "fingerprint_version" (value null for a preserved v0 entry, entry_hash byte-identical under
    # R4 absence-aware hashing); the `keys - {"fingerprint_version"}` form accepts BOTH without a
    # human amendment. See the task report FLAG on tests/test_t55b_demo_wiring.py's exact-match pin.


# -- FINGERPRINT_KEYS shape assertion moved out of collection-time so it fails as a test, not an
# -- import error: today the tuple is 2 keys; after the widening it is the 3-key v1 tuple.

def test_fingerprint_keys_is_v1_three_tuple():
    """FINGERPRINT_KEYS is the widened v1 3-tuple ("error_code","counterparty","doc_num").

    FAILS TODAY: the constant is the 2-tuple ("error_code","counterparty"). Pinned as its own test
    (not a module-level assert) so a red here never blocks collection of the guard tests above.
    """
    assert FINGERPRINT_KEYS == ("error_code", "counterparty", "doc_num"), (
        f"FINGERPRINT_KEYS must widen to the v1 3-tuple; got {FINGERPRINT_KEYS!r}"
    )
