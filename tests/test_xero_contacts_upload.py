"""
tests/test_xero_contacts_upload.py — Slice C: the contacts part, end to end.

D-2026-09-20-slice-c-contacts-no-gst-reg. Covers the RULED test set at the WIRING layer:
C2 (no contacts → the response is byte-identical to the recorded baseline), C5 (the SAP
path and the offline-replay oracle are untouched), C6 (a contacts part on a non-F5 path is
ignored), C7 (the NO_GST_REG row is adjudicable and its decision re-applies), and C10 (the
signed paper carries the finding and the Xero wording, on BOTH the per-upload sign and the
accumulated sign — ruling 4: the screen and every paper agree).

WHAT THIS PROVES AND WHAT IT DOES NOT. It proves the WIRING — that a supplied Contacts
export reaches every reader construction site, and that supplying none changes nothing. It
proves NOTHING about accuracy: real Xero FORMAT over SYNTHETIC content (DEBT-3),
presence-only (R1), candidates not verdicts, `validation_status` still "unvalidated".

APPEND-ONLY BOUNDARY: this is a NEW test file. No existing test file is modified; no
existing fixture is modified or re-pointed.

Hermetic: no network, no anthropic import, no live SAP/Xero. SAP off, dummy creds only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import sys
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from api.app import app

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

from audit_bundle.canonical import canonical_json  # noqa: E402
from config.loader import load_client_config  # noqa: E402
from orchestrator.chain import run_chain  # noqa: E402

_shim_spec = importlib.util.spec_from_file_location(
    "slice_c_replay_shim", _REPO_ROOT / "tests" / "replay_shim.py"
)
replay_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(replay_shim)

_EXTRACT_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
_ORACLE_PATH = _EXTRACT_FIXTURE_DIR / "_replay-oracle.compiled.json"

_DEMO_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-demo-2026Q2"
_DEMO_F5 = _DEMO_DIR / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_DEMO_F5_NAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_DEMO_CONTACTS = _DEMO_DIR / "Contacts.csv"

_SALES_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
    / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
)
_SALES_NAME = "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"

#: C2 — the canonical-JSON sha256 of ``POST /review/upload`` over the demo F5 with NO
#: contacts part, MEASURED on the branch base (ef5d0b8) BEFORE any line of this slice was
#: written, and re-measured twice to prove the response is deterministic. This is the
#: byte-identity tripwire for D2: if anything in this slice reaches the no-contacts path,
#: this digest moves. Re-measure with:
#:   POST /review/upload {file: demo F5} → sha256(json.dumps(body, sort_keys=True,
#:   separators=(",", ":")).encode())
_NO_CONTACTS_BASELINE_SHA = (
    "3ae353f1fd4f04d1c1432358d5640dc92678aa43a98a674104baa37458967104"
)

_UPLOAD_SEQ = itertools.count()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Engine PDF dir + audit root + decision store + review store redirected to tmp.

    The three stores are patched through IMPORTED MODULE OBJECTS, not through dotted
    strings: ``monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", ...)`` resolves
    the submodule as an attribute of the ``agent`` package, which only exists once
    something has imported it. Standalone this file passes either way; inside the full
    suite the import order differs and the string form raised at SETUP. Importing here
    makes the fixture independent of whatever ran before it.
    """
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


def _bump_audit() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"


def _upload(
    client: TestClient,
    *,
    contacts: Optional[bytes] = None,
    contacts_name: str = "Contacts.csv",
    file_bytes: Optional[bytes] = None,
    name: str = _DEMO_F5_NAME,
    review_id: Optional[str] = None,
):
    _bump_audit()
    files = {"file": (name, file_bytes if file_bytes is not None else _DEMO_F5.read_bytes())}
    if contacts is not None:
        files["contacts"] = (contacts_name, contacts)
    data = {"review_id": review_id} if review_id is not None else None
    return client.post("/review/upload", files=files, data=data)


def _sign(
    client: TestClient,
    *,
    contacts: Optional[bytes] = None,
    reviewer_name: str = "Collin Tan",
    review_id: Optional[str] = None,
):
    _bump_audit()
    files = {"file": (_DEMO_F5_NAME, _DEMO_F5.read_bytes())}
    if contacts is not None:
        files["contacts"] = ("Contacts.csv", contacts)
    data = {"reviewer_name": reviewer_name}
    if review_id is not None:
        data["review_id"] = review_id
    return client.post("/sign/upload", data=data, files=files)


def _digest(body: dict) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _cov(body: dict, check: str) -> dict:
    return next(r for r in body["coverage_status"] if r["check"] == check)


def _pdf_text(pdf_path: Path) -> str:
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return " ".join(
            " ".join((page.extract_text() or "").split()) for page in pdf.pages
        )


# ══ C2 — no contacts: byte-identical to the recorded baseline ════════════════════════


class TestNoContactsUnchanged:

    def test_no_contacts_response_is_byte_identical_to_the_baseline(self, client, hermetic):
        resp = _upload(client)
        assert resp.status_code == 200, resp.text
        assert _digest(resp.json()) == _NO_CONTACTS_BASELINE_SHA

    def test_no_contacts_keeps_no_gst_reg_unavailable_with_the_same_reason(self, client, hermetic):
        from feeders import coverage_status as cov_status

        body = _upload(client).json()
        row = _cov(body, "NO_GST_REG")
        assert row["level"] == "unavailable"
        assert row["reason"] == cov_status._NO_GST_REG_UNAVAILABLE
        assert [r for r in body["queue"] if r["error_code"] == "NO_GST_REG"] == []

    def test_an_empty_contacts_part_is_treated_as_no_contacts(self, client, hermetic):
        """A present-but-empty part is 'no contacts' — the ledger precedent, so a browser
        that always appends the field cannot flip the review into a different mode."""
        resp = _upload(client, contacts=b"", contacts_name="")
        assert resp.status_code == 200, resp.text
        assert _digest(resp.json()) == _NO_CONTACTS_BASELINE_SHA


# ══ The contacts part itself ═════════════════════════════════════════════════════════


class TestContactsPart:

    def test_contacts_makes_no_gst_reg_run_and_degrade_with_counts(self, client, hermetic):
        body = _upload(client, contacts=_DEMO_CONTACTS.read_bytes()).json()
        row = _cov(body, "NO_GST_REG")
        assert row["level"] == "degraded"
        assert "19 of 20" in row["reason"]
        assert "1 with no supplier on the transaction" in row["reason"]
        findings = [r for r in body["queue"] if r["error_code"] == "NO_GST_REG"]
        assert [r["doc_num"] for r in findings] == ["BILL-3003"]

    def test_a_non_csv_contacts_part_is_an_honest_422(self, client, hermetic):
        resp = _upload(client, contacts=b"not,a,csv", contacts_name="Contacts.xlsx")
        assert resp.status_code == 422
        assert "csv" in resp.json()["detail"].lower()

    def test_an_unreadable_contacts_file_is_a_422_never_a_500(self, client, hermetic):
        resp = _upload(client, contacts=b"\x00\x01\x02 not a csv at all")
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            # Tolerated as a 0-contact export: every supplier then reads "missing" and
            # NOTHING is flagged (R2). What must never happen is a fabricated finding.
            body = resp.json()
            assert [r for r in body["queue"] if r["error_code"] == "NO_GST_REG"] == []


# ══ Box-isolation — the join adds a FINDING and moves nothing else ══════════════════


class TestBoxIsolation:

    def test_boxes_are_byte_identical_with_and_without_contacts(self, client, hermetic):
        """Invariant 3, pinned rather than reviewed. The contacts join sets CardCode on
        purchase documents; CardCode feeds the NO_GST_REG loop and nothing else on this
        reader (its listing surface is empty). The F5 boxes are therefore untouched — and
        this asserts it on the wire instead of trusting that reading.

        The queue must differ by EXACTLY one added row, the NO_GST_REG finding: no other
        finding may appear, move or vanish because a supplier master was supplied.
        """
        without = _upload(client).json()
        with_contacts = _upload(client, contacts=_DEMO_CONTACTS.read_bytes()).json()

        assert json.dumps(
            with_contacts["recomputed_client_coded_f5_boxes"], sort_keys=True
        ) == json.dumps(without["recomputed_client_coded_f5_boxes"], sort_keys=True)
        assert with_contacts["validation_status"] == without["validation_status"]

        def _ids(body: dict) -> list:
            return sorted(r["finding_id"] for r in body["queue"])

        added = set(_ids(with_contacts)) - set(_ids(without))
        assert set(_ids(without)) - set(_ids(with_contacts)) == set()
        assert len(added) == 1
        new_row = next(r for r in with_contacts["queue"] if r["finding_id"] in added)
        assert (new_row["error_code"], new_row["doc_num"]) == ("NO_GST_REG", "BILL-3003")


# ══ C6 — a contacts part on a non-F5 path is IGNORED ═════════════════════════════════


class TestIgnoredElsewhere:

    def test_sales_upload_ignores_a_contacts_part(self, client, hermetic):
        without = _upload(
            client, file_bytes=_SALES_FIXTURE.read_bytes(), name=_SALES_NAME
        )
        with_contacts = _upload(
            client,
            file_bytes=_SALES_FIXTURE.read_bytes(),
            name=_SALES_NAME,
            contacts=_DEMO_CONTACTS.read_bytes(),
        )
        assert without.status_code == with_contacts.status_code == 200
        assert _digest(with_contacts.json()) == _digest(without.json())


# ══ C7 — the row is adjudicable, and the decision re-applies ═════════════════════════


class TestAdjudicable:

    def test_no_gst_reg_row_carries_a_fingerprint_and_reapplies(self, client, hermetic):
        contacts = _DEMO_CONTACTS.read_bytes()
        body = _upload(client, contacts=contacts).json()
        row = next(r for r in body["queue"] if r["error_code"] == "NO_GST_REG")
        assert row["fingerprint"].startswith("sha256:")
        assert row["demoted"] is False

        posted = client.post(
            "/decision",
            json={
                "client_id": "xero_demo",
                "finding_id": row["finding_id"],
                "fingerprint": row["fingerprint"],
                "action": "Mark known",
                "note": "Supplier confirmed unregistered; input tax not claimed.",
                "reviewer_name": "Collin Tan",
            },
        )
        assert posted.status_code == 200, posted.text

        again = _upload(client, contacts=contacts).json()
        same = next(r for r in again["queue"] if r["error_code"] == "NO_GST_REG")
        assert same["fingerprint"] == row["fingerprint"]
        # Cardinality-preserving: demoted and STILL PRESENT, never deleted from the queue.
        assert same["demoted"] is True


# ══ C10 — the signed papers ══════════════════════════════════════════════════════════


class TestSignedPaper:

    def test_per_upload_sign_carries_the_finding_and_the_xero_wording(self, client, hermetic):
        resp = _sign(client, contacts=_DEMO_CONTACTS.read_bytes())
        assert resp.status_code == 200, resp.text
        text = _pdf_text(Path(resp.json()["working_paper_path"]))
        assert "NO_GST_REG" in text
        assert "NoReg Trading" in text
        # R8 — the Xero branch of the supplier-registration judgment question.
        assert "TaxNumber" in text
        assert "Contacts export" in text
        assert "FederalTaxID" not in text
        assert "User Defined Field" not in text

    def test_section6_line_is_suppressed_when_the_check_ran(self, client, hermetic):
        with_contacts = _pdf_text(
            Path(_sign(client, contacts=_DEMO_CONTACTS.read_bytes()).json()["working_paper_path"])
        )
        without = _pdf_text(Path(_sign(client).json()["working_paper_path"]))
        from report.constants import SUPPLIER_REG_UNAVAILABLE_ITEM

        probe = " ".join(SUPPLIER_REG_UNAVAILABLE_ITEM.split())[:60]
        assert probe in " ".join(without.split())
        assert probe not in " ".join(with_contacts.split())

    def test_accumulated_sign_reads_the_retained_contacts(self, client, hermetic):
        """Ruling 4: the accumulated paper re-runs the PRIMARY over its RETAINED bytes —
        including the retained .contacts.csv, or the accumulated paper would silently drop
        a finding the screen showed."""
        import agent.review_store as rs

        rid = rs.create_review("slice-c")["review_id"]
        body = _upload(client, contacts=_DEMO_CONTACTS.read_bytes(), review_id=rid).json()
        assert [r["doc_num"] for r in body["queue"] if r["error_code"] == "NO_GST_REG"] == [
            "BILL-3003"
        ]

        _bump_audit()
        signed = client.post(
            f"/review-session/{rid}/sign", json={"reviewer_name": "Collin Tan"}
        )
        assert signed.status_code == 200, signed.text
        text = _pdf_text(Path(signed.json()["working_paper_path"]))
        assert "NO_GST_REG" in text
        assert "NoReg Trading" in text


# ══ C5 — the SAP path and the offline-replay oracle are untouched ════════════════════


class TestSapPathUntouched:

    def test_offline_replay_stays_byte_identical_to_the_oracle(self, monkeypatch):
        contact = replay_shim.install_replay_patches(monkeypatch, _EXTRACT_FIXTURE_DIR)
        cfg = load_client_config("sbodemosg", check_connectivity=False)
        period = replay_shim.period_from_manifest(_EXTRACT_FIXTURE_DIR)
        compile_output, gate_results = run_chain(
            cfg, period, reader=replay_shim.build_frozen_reader(_EXTRACT_FIXTURE_DIR)
        )
        replayed = canonical_json({
            "period": period,
            "compile_output": compile_output,
            "gate_results": gate_results,
        })
        assert replayed == _ORACLE_PATH.read_bytes()
        assert contact == {"login": 0, "request": 0}

    def test_sap_judgment_wording_keeps_its_mechanism_nouns(self):
        """The SAP branch of R8 is byte-identical: the SAP paper still names the UDF and
        FederalTaxID mechanism, because on SAP those nouns are the truth."""
        from types import SimpleNamespace

        from report.sections import build_judgment_section

        findings = [
            SimpleNamespace(error_code="NO_GST_REG", doc_num="BILL-3003", vat_group="NR")
        ]
        # `source_system` is the attribute `_source_label` / the R8 branch actually read;
        # a SimpleNamespace carrying `source` instead would silently exercise the
        # missing-attribute DEFAULT and prove nothing about a SAP-configured run.
        section = build_judgment_section(
            {}, findings, client_config=SimpleNamespace(source_system="sap_b1")
        )
        group = next(g for g in section.groups if g.group_id == "supplier-registration")
        assert "FederalTaxID" in group.judgment_question
        assert "User Defined Field" in group.judgment_question

    def test_sap_section6_never_gains_the_supplier_registration_line(self):
        """A reader with NO coverage seam (live SAP / frozen replay) emits no
        check_coverage, and absence must mean 'the check ran' — otherwise every SAP paper
        would gain a new Section 6 line and the oracle would need re-freezing."""
        from report.sections import build_not_examined_section

        from report.constants import NOT_EXAMINED_ITEMS, SUPPLIER_REG_UNAVAILABLE_ITEM

        section = build_not_examined_section({}, None)
        assert SUPPLIER_REG_UNAVAILABLE_ITEM not in section.items
        # And it is not a member of the static list either, so no paper anywhere gains a
        # line just by this constant existing (the locked Section 6 count pins hold).
        assert SUPPLIER_REG_UNAVAILABLE_ITEM not in NOT_EXAMINED_ITEMS
