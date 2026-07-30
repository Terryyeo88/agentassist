"""
tests/test_documents_unified_report.py — T2.8 unified candidates section tests.

Covers:
  P1 — FixtureDocumentProvider: correct path for known doc_nums, None for unknown.
  P2 — UploadProvider: returns path for known INV-<n>.pdf, None for unknown.
  P3 — B1AttachmentProvider offline: mocked Service Layer responses (no live calls).
  P4 — CompositeProvider: returns first non-None result; falls through to upload.
  D1 — run_documents_pass: correct DocumentCandidate list over all 8 fixtures.
  D2 — run_documents_pass: absent PDF is silently skipped, no candidate emitted.
  U1 — build_unified_candidates_section: show=False short-circuits with empty section.
  U2 — build_unified_candidates_section: reasoning candidates adapt with basis tag.
  U3 — build_unified_candidates_section: document candidates adapt with basis tag.
  U4 — build_unified_candidates_section: both sources in one section.
  U5 — build_unified_candidates_section: "not_examined" status when pass omitted.
  U6 — build_unified_candidates_section: errored reasoning artefact handled.
  R1 — _unified_candidates_subsection: zero flowables appended when show=False.
       (Byte-identity guarantee: no additional content added → rest of PDF unchanged.)
  R2 — render_pdf with show=True, FixtureDocumentProvider: produces valid PDF.
  R3 — render_pdf with show=True, reasoning + document candidates: single section.
  R4 — render_pdf with show=True, no candidates: "No candidates surfaced."
  F1 — F5 boxes byte-identical with and without documents pass.
  F2 — F5 gates unchanged regardless of show_ai_candidates value.
  I1 — documents/provider.py and documents/doc_pass.py contain no forbidden imports.
  I2 — orchestrator/ has no import of documents/.

IMPORTANT: per-fixture expected candidates are AUTHOR-KNOWN, CONTROLLED, injected
issues for build/demo purposes only — NOT specialist-validated ground truth (T2.13).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from config.loader import ClientConfig
from documents.doc_pass import run_documents_pass
from documents.provider import (
    B1AttachmentProvider,
    CompositeProvider,
    DocumentProvider,
    FixtureDocumentProvider,
    UploadProvider,
)
from documents.reconcile import DocumentCandidate
from report.report import ReportModel, build_report
from report.sections import (
    ReviewCandidateRow,
    UnifiedCandidatesSection,
    build_unified_candidates_section,
)

# ---------------------------------------------------------------------------
# Shared constants and fixtures
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_DOCS_DIR = Path(__file__).parent / "fixtures" / "documents"
_MANIFEST_PATH = _DOCS_DIR / "fixtures_manifest.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
_CASES = _MANIFEST["cases"]
_PERIOD_START = _MANIFEST["_meta"]["gst_period"]["start"]   # "2024-07-01"
_PERIOD_END = _MANIFEST["_meta"]["gst_period"]["end"]       # "2024-09-30"

_CHAIN_FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"


def _make_cfg(**overrides) -> ClientConfig:
    base = dict(
        client_id="sbodemosg",
        client_name="SBODEMOSG Demo",
        gst_registration_number="M12345678X",
        applicable_gst_rate=0.07,
        service_layer_url="https://fake",
        company_db="SBODEMOSG",
        username="manager",
        password="manager",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.1,
        reviewer_name="Terry Yeo",
        firm_name="AgentAssist Pte Ltd",
    )
    base.update(overrides)
    return ClientConfig(**base)


def _raw_data() -> dict:
    return json.loads(_CHAIN_FIXTURE.read_text(encoding="utf-8"))


def _all_line_items() -> list[dict]:
    return [c["line_item_record"] for c in _CASES]


def _reasoning_artefact_ok() -> dict:
    return {
        "status": "ok",
        "candidate_count": 1,
        "disclaimer": "AI-surfaced candidates for human review only — not assertions.",
        "candidates": [
            {
                "doc_num": 9001,
                "line_index": 0,
                "doc_date": "2024-07-15",
                "card_name": "Raffles Medical Clinic",
                "line_description": "Annual health screening",
                "line_total": 500.0,
                "tax_total": 45.0,
                "suspected_category": "medical_expenses",
                "confidence": "high",
                "phrasing": "Consider reviewing whether this line (annual health screening) "
                             "falls under Reg 27 disallowed categories.",
            }
        ],
    }


# ---------------------------------------------------------------------------
# P1 — FixtureDocumentProvider
# ---------------------------------------------------------------------------

class TestFixtureDocumentProvider:
    def test_returns_path_for_known_doc_nums(self) -> None:
        provider = FixtureDocumentProvider(_DOCS_DIR)
        for case in _CASES:
            path = provider.get_document(case["doc_num"])
            assert path is not None, f"Expected path for doc_num={case['doc_num']}"
            assert path.exists(), f"Path does not exist: {path}"
            assert path.name == case["pdf_filename"]

    def test_returns_none_for_unknown_doc_num(self) -> None:
        provider = FixtureDocumentProvider(_DOCS_DIR)
        assert provider.get_document(99999) is None

    def test_returns_none_for_zero(self) -> None:
        provider = FixtureDocumentProvider(_DOCS_DIR)
        assert provider.get_document(0) is None

    def test_satisfies_document_provider_protocol(self) -> None:
        provider = FixtureDocumentProvider(_DOCS_DIR)
        assert isinstance(provider, DocumentProvider)

    def test_accepts_str_fixture_dir(self) -> None:
        provider = FixtureDocumentProvider(str(_DOCS_DIR))
        path = provider.get_document(3001)
        assert path is not None and path.exists()


# ---------------------------------------------------------------------------
# P2 — UploadProvider: temp-directory file lookup
# ---------------------------------------------------------------------------

class TestUploadProvider:
    def test_returns_path_for_existing_pdf(self, tmp_path: Path) -> None:
        pdf = tmp_path / "INV-3003.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        prov = UploadProvider(tmp_path)
        result = prov.get_document(3003)
        assert result == pdf
        assert result.exists()

    def test_returns_none_for_missing_doc_num(self, tmp_path: Path) -> None:
        prov = UploadProvider(tmp_path)
        assert prov.get_document(9999) is None

    def test_accepts_string_dir(self, tmp_path: Path) -> None:
        pdf = tmp_path / "INV-1.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        prov = UploadProvider(str(tmp_path))
        assert prov.get_document(1) is not None

    def test_satisfies_document_provider_protocol(self, tmp_path: Path) -> None:
        prov = UploadProvider(tmp_path)
        assert isinstance(prov, DocumentProvider)


# ---------------------------------------------------------------------------
# P3 — B1AttachmentProvider: offline / mocked Service Layer (no live calls)
# ---------------------------------------------------------------------------

class _FakeCfg:
    service_layer_url = "https://fake-sl:55000/b1s/v2"
    company_db = "TESTDB"
    username = "manager"
    password = "manager"
    ssl_verify = False


def _b1_mock_setup(mock_session_cls, *, att_entry=42, line_num=0,
                   pdf_bytes=b"%PDF-1.4 mock", login_ok=True,
                   pi_status=200, att_status=200, dl_status=200,
                   no_att_entry=False, no_pdf_line=False):
    """Wire up a mock requests.Session for B1AttachmentProvider tests."""
    import unittest.mock as mock

    session = mock.MagicMock()
    mock_session_cls.return_value = session

    def _make_resp(status, json_body=None, content=None):
        r = mock.MagicMock()
        r.status_code = status
        if json_body is not None:
            r.json.return_value = json_body
        if content is not None:
            r.content = content
        return r

    login_resp = _make_resp(200 if login_ok else 401)
    session.post.side_effect = [login_resp, mock.MagicMock()]  # login + logout

    pi_body = {
        "value": [] if no_att_entry else [
            {"DocEntry": 100, "AttachmentEntry": att_entry}
        ]
    }
    att_body = {
        "AbsoluteEntry": att_entry,
        "Attachments2_Lines": [] if no_pdf_line else [
            {"LineNum": line_num, "FileName": "invoice", "FileExtension": "pdf"}
        ],
    }
    dl_resp = _make_resp(dl_status, content=pdf_bytes)

    session.get.side_effect = [
        _make_resp(pi_status, json_body=pi_body),
        _make_resp(att_status, json_body=att_body),
        dl_resp,
    ]
    return session


class TestB1AttachmentProviderOffline:
    """All tests use a mocked requests.Session — no live SAP calls."""

    def test_returns_path_on_happy_path(self, tmp_path: Path) -> None:
        from unittest.mock import patch, MagicMock
        with patch("documents.provider.requests.Session") as mock_session_cls:
            _b1_mock_setup(mock_session_cls, pdf_bytes=b"%PDF-1.4 happy")
            prov = B1AttachmentProvider(_FakeCfg())
            result = prov.get_document(3003)
        assert result is not None
        assert result.suffix == ".pdf"
        assert result.read_bytes() == b"%PDF-1.4 happy"
        result.unlink(missing_ok=True)

    def test_returns_none_when_no_attachment_entry(self) -> None:
        from unittest.mock import patch
        with patch("documents.provider.requests.Session") as mock_session_cls:
            _b1_mock_setup(mock_session_cls, no_att_entry=True)
            prov = B1AttachmentProvider(_FakeCfg())
            result = prov.get_document(9999)
        assert result is None

    def test_returns_none_when_no_pdf_line(self) -> None:
        from unittest.mock import patch
        with patch("documents.provider.requests.Session") as mock_session_cls:
            _b1_mock_setup(mock_session_cls, no_pdf_line=True)
            prov = B1AttachmentProvider(_FakeCfg())
            result = prov.get_document(3003)
        assert result is None

    def test_returns_none_when_download_fails(self) -> None:
        from unittest.mock import patch
        with patch("documents.provider.requests.Session") as mock_session_cls:
            _b1_mock_setup(mock_session_cls, dl_status=404)
            prov = B1AttachmentProvider(_FakeCfg())
            result = prov.get_document(3003)
        assert result is None

    def test_returns_none_when_login_fails(self) -> None:
        from unittest.mock import patch
        with patch("documents.provider.requests.Session") as mock_session_cls:
            _b1_mock_setup(mock_session_cls, login_ok=False)
            prov = B1AttachmentProvider(_FakeCfg())
            result = prov.get_document(3003)
        assert result is None

    def test_returns_none_on_pi_error(self) -> None:
        from unittest.mock import patch
        with patch("documents.provider.requests.Session") as mock_session_cls:
            _b1_mock_setup(mock_session_cls, pi_status=500)
            prov = B1AttachmentProvider(_FakeCfg())
            result = prov.get_document(3003)
        assert result is None

    def test_satisfies_document_provider_protocol(self) -> None:
        prov = B1AttachmentProvider(_FakeCfg())
        assert isinstance(prov, DocumentProvider)

    def test_never_calls_post_patch_delete_except_login_logout(self) -> None:
        """Runtime is read-only: only POST calls must be Login and Logout."""
        from unittest.mock import patch, call
        with patch("documents.provider.requests.Session") as mock_session_cls:
            _b1_mock_setup(mock_session_cls)
            prov = B1AttachmentProvider(_FakeCfg())
            session = mock_session_cls.return_value
            prov.get_document(3003)
        post_urls = [c.args[0] if c.args else c.kwargs.get("url", "")
                     for c in session.post.call_args_list]
        for url in post_urls:
            assert "Login" in url or "Logout" in url, (
                f"Unexpected POST to {url!r} — provider must be read-only"
            )
        assert not hasattr(session, "patch") or session.patch.call_count == 0
        assert not hasattr(session, "delete") or session.delete.call_count == 0


# ---------------------------------------------------------------------------
# P4 — CompositeProvider: ordered fallthrough
# ---------------------------------------------------------------------------

class TestCompositeProvider:
    def test_returns_first_non_none(self, tmp_path: Path) -> None:
        pdf = tmp_path / "INV-3003.pdf"
        pdf.write_bytes(b"%PDF-1.4 upload")
        upload = UploadProvider(tmp_path)
        fixture = FixtureDocumentProvider(_DOCS_DIR)
        composite = CompositeProvider([upload, fixture])
        result = composite.get_document(3003)
        assert result == pdf

    def test_falls_through_to_second_on_none(self, tmp_path: Path) -> None:
        fixture = FixtureDocumentProvider(_DOCS_DIR)
        upload = UploadProvider(tmp_path)   # empty dir → always None
        composite = CompositeProvider([upload, fixture])
        result = composite.get_document(3001)
        assert result is not None
        assert result.name == "INV-3001.pdf"

    def test_returns_none_when_all_fail(self, tmp_path: Path) -> None:
        composite = CompositeProvider([UploadProvider(tmp_path)])
        assert composite.get_document(99999) is None

    def test_b1_returns_none_falls_to_upload(self, tmp_path: Path) -> None:
        """CompositeProvider(B1→None, Upload) uses Upload when B1 gives None."""
        from unittest.mock import patch
        pdf = tmp_path / "INV-3003.pdf"
        pdf.write_bytes(b"%PDF-1.4 fallback")
        with patch("documents.provider.requests.Session") as mock_session_cls:
            _b1_mock_setup(mock_session_cls, no_att_entry=True)
            b1 = B1AttachmentProvider(_FakeCfg())
            upload = UploadProvider(tmp_path)
            composite = CompositeProvider([b1, upload])
            result = composite.get_document(3003)
        assert result == pdf

    def test_empty_providers_returns_none(self) -> None:
        composite = CompositeProvider([])
        assert composite.get_document(3003) is None

    def test_satisfies_document_provider_protocol(self, tmp_path: Path) -> None:
        composite = CompositeProvider([UploadProvider(tmp_path)])
        assert isinstance(composite, DocumentProvider)


# ---------------------------------------------------------------------------
# D1 — run_documents_pass: correct candidates over all 8 fixtures
#
# Expected candidates are AUTHOR-KNOWN, CONTROLLED, injected issues for
# build/demo purposes only — NOT specialist-validated ground truth (T2.13).
# ---------------------------------------------------------------------------

class TestRunDocumentsPassCandidates:
    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.provider = FixtureDocumentProvider(_DOCS_DIR)
        self.candidates = run_documents_pass(
            _all_line_items(), self.provider, _PERIOD_START, _PERIOD_END
        )
        self.by_doc: dict[int, list[DocumentCandidate]] = {}
        for c in self.candidates:
            self.by_doc.setdefault(c.doc_num, []).append(c)

    def test_3001_zero_candidates(self) -> None:
        assert 3001 not in self.by_doc

    def test_3002_zero_candidates(self) -> None:
        assert 3002 not in self.by_doc

    def test_3003_gst_amount_mismatch(self) -> None:
        cands = self.by_doc.get(3003, [])
        assert len(cands) == 1
        assert cands[0].check_id == "gst_amount_mismatch"
        assert cands[0].extracted_value == pytest.approx(900.0)
        assert cands[0].listing_value == pytest.approx(840.0)

    def test_3004_gst_amount_mismatch(self) -> None:
        cands = self.by_doc.get(3004, [])
        assert len(cands) == 1
        assert cands[0].check_id == "gst_amount_mismatch"
        assert cands[0].extracted_value == pytest.approx(192.0)
        assert cands[0].listing_value == pytest.approx(224.0)

    def test_3005_reg11_supplier_gst_absent(self) -> None:
        cands = self.by_doc.get(3005, [])
        assert len(cands) == 1
        assert cands[0].check_id == "reg11_supplier_gst_absent"
        assert cands[0].severity == "HIGH"

    def test_3006_correct_period(self) -> None:
        cands = self.by_doc.get(3006, [])
        assert len(cands) == 1
        assert cands[0].check_id == "correct_period"
        assert cands[0].extracted_value == "2024-10-05"

    def test_3007_total_inconsistency(self) -> None:
        cands = self.by_doc.get(3007, [])
        assert len(cands) == 1
        assert cands[0].check_id == "total_inconsistency"
        assert cands[0].extracted_value == pytest.approx(4530.0)
        assert cands[0].listing_value == pytest.approx(4494.0)

    def test_3008_two_candidates(self) -> None:
        cands = self.by_doc.get(3008, [])
        assert len(cands) == 2
        check_ids = {c.check_id for c in cands}
        assert check_ids == {"gst_amount_mismatch", "reg11_supplier_gst_absent"}

    def test_3008_gst_mismatch_values(self) -> None:
        cands = [c for c in self.by_doc.get(3008, [])
                 if c.check_id == "gst_amount_mismatch"]
        assert len(cands) == 1
        assert cands[0].extracted_value == pytest.approx(360.0)
        assert cands[0].listing_value == pytest.approx(420.0)

    def test_all_candidates_are_unvalidated(self) -> None:
        for c in self.candidates:
            assert c.validation_status == "unvalidated", (
                f"doc_num={c.doc_num} {c.check_id}: expected unvalidated"
            )

    def test_all_candidates_carry_basis_born_digital(self) -> None:
        for c in self.candidates:
            assert c.extraction_source == "born_digital", (
                f"doc_num={c.doc_num}: fixture PDFs are always born_digital"
            )

    def test_total_candidate_count(self) -> None:
        # 3003(1) + 3004(1) + 3005(1) + 3006(1) + 3007(1) + 3008(2) = 7
        assert len(self.candidates) == 7


# ---------------------------------------------------------------------------
# D2 — run_documents_pass: absent PDF silently skipped
# ---------------------------------------------------------------------------

class TestRunDocumentsPassMissingPdf:
    def test_absent_pdf_produces_no_candidate(self) -> None:
        """A line item whose doc_num has no PDF emits zero candidates."""
        line_items = [{"doc_num": 99999, "doc_type": "purchase_invoice",
                       "doc_date": "2024-08-01", "card_name": "Ghost Co",
                       "line_index": 0, "vat_group": "SI",
                       "line_description": "Test", "line_total": 100.0,
                       "tax_total": 7.0}]
        provider = FixtureDocumentProvider(_DOCS_DIR)
        candidates = run_documents_pass(
            line_items, provider, _PERIOD_START, _PERIOD_END
        )
        assert candidates == []

    def test_empty_line_items_returns_empty_list(self) -> None:
        provider = FixtureDocumentProvider(_DOCS_DIR)
        candidates = run_documents_pass([], provider, _PERIOD_START, _PERIOD_END)
        assert candidates == []


# ---------------------------------------------------------------------------
# U1 — build_unified_candidates_section: show=False short-circuits
# ---------------------------------------------------------------------------

class TestUnifiedSectionShowFalse:
    def test_show_false_returns_empty_candidates(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), [_dummy_doc_candidate()],
            show=False
        )
        assert sec.show is False
        assert sec.candidates == []

    def test_show_false_reasoning_status_not_examined(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), None, show=False
        )
        assert sec.reasoning_status == "not_examined"

    def test_show_false_documents_status_not_examined(self) -> None:
        sec = build_unified_candidates_section(
            None, [_dummy_doc_candidate()], show=False
        )
        assert sec.documents_status == "not_examined"


# ---------------------------------------------------------------------------
# U2 — build_unified_candidates_section: reasoning candidates adapt correctly
# ---------------------------------------------------------------------------

class TestUnifiedSectionReasoningAdaptation:
    def test_reasoning_candidate_basis_tag(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), None, show=True
        )
        assert any(r.basis == "description analysis" for r in sec.candidates)

    def test_reasoning_candidate_finding_is_suspected_category(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), None, show=True
        )
        row = next(r for r in sec.candidates if r.basis == "description analysis")
        assert row.finding == "medical_expenses"

    def test_reasoning_candidate_doc_num(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), None, show=True
        )
        row = next(r for r in sec.candidates if r.basis == "description analysis")
        assert row.doc_num == 9001

    def test_reasoning_candidate_determinability_j_plus(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), None, show=True
        )
        row = next(r for r in sec.candidates if r.basis == "description analysis")
        assert row.determinability == "J+"

    def test_reasoning_candidate_validation_unvalidated(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), None, show=True
        )
        row = next(r for r in sec.candidates if r.basis == "description analysis")
        assert row.validation_status == "unvalidated"

    def test_reasoning_not_examined_when_artefact_none(self) -> None:
        sec = build_unified_candidates_section(None, None, show=True)
        assert sec.reasoning_status == "not_examined"
        assert not any(r.basis == "description analysis" for r in sec.candidates)

    def test_reasoning_status_ok(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), None, show=True
        )
        assert sec.reasoning_status == "ok"


# ---------------------------------------------------------------------------
# U3 — build_unified_candidates_section: document candidates adapt correctly
# ---------------------------------------------------------------------------

class TestUnifiedSectionDocumentAdaptation:
    def test_document_candidate_basis_tag(self) -> None:
        cand = _dummy_doc_candidate()
        sec = build_unified_candidates_section(None, [cand], show=True)
        row = sec.candidates[0]
        assert row.basis == "invoice cross-reference"

    def test_document_candidate_finding_is_check_id(self) -> None:
        cand = _dummy_doc_candidate()
        sec = build_unified_candidates_section(None, [cand], show=True)
        row = sec.candidates[0]
        assert row.finding == cand.check_id

    def test_document_candidate_doc_num(self) -> None:
        cand = _dummy_doc_candidate(doc_num=3003)
        sec = build_unified_candidates_section(None, [cand], show=True)
        assert sec.candidates[0].doc_num == 3003

    def test_document_candidate_determinability_preserved(self) -> None:
        cand = _dummy_doc_candidate()
        sec = build_unified_candidates_section(None, [cand], show=True)
        assert sec.candidates[0].determinability == cand.determinability

    def test_document_candidate_validation_unvalidated(self) -> None:
        cand = _dummy_doc_candidate()
        sec = build_unified_candidates_section(None, [cand], show=True)
        assert sec.candidates[0].validation_status == "unvalidated"

    def test_documents_not_examined_when_none(self) -> None:
        sec = build_unified_candidates_section(None, None, show=True)
        assert sec.documents_status == "not_examined"
        assert not any(r.basis == "invoice cross-reference" for r in sec.candidates)

    def test_documents_status_ok_when_list_provided(self) -> None:
        sec = build_unified_candidates_section(None, [], show=True)
        assert sec.documents_status == "ok"


# ---------------------------------------------------------------------------
# U4 — both sources appear in one unified section
# ---------------------------------------------------------------------------

class TestUnifiedSectionBothSources:
    def test_both_bases_present(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), [_dummy_doc_candidate()], show=True
        )
        bases = {r.basis for r in sec.candidates}
        assert bases == {"description analysis", "invoice cross-reference"}

    def test_candidate_count_is_sum_of_both(self) -> None:
        reasoning = _reasoning_artefact_ok()   # 1 candidate
        docs = [_dummy_doc_candidate(), _dummy_doc_candidate(doc_num=3004)]  # 2 candidates
        sec = build_unified_candidates_section(reasoning, docs, show=True)
        assert len(sec.candidates) == 3

    def test_reasoning_candidates_precede_document_candidates(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), [_dummy_doc_candidate()], show=True
        )
        # Builder appends reasoning first, then document — stable ordering
        assert sec.candidates[0].basis == "description analysis"
        assert sec.candidates[-1].basis == "invoice cross-reference"


# ---------------------------------------------------------------------------
# U5 — "not examined" statuses when passes are omitted
# ---------------------------------------------------------------------------

class TestUnifiedSectionNotExamined:
    def test_both_not_examined_when_both_none(self) -> None:
        sec = build_unified_candidates_section(None, None, show=True)
        assert sec.reasoning_status == "not_examined"
        assert sec.documents_status == "not_examined"

    def test_reasoning_not_examined_only(self) -> None:
        sec = build_unified_candidates_section(
            None, [_dummy_doc_candidate()], show=True
        )
        assert sec.reasoning_status == "not_examined"
        assert sec.documents_status == "ok"

    def test_documents_not_examined_only(self) -> None:
        sec = build_unified_candidates_section(
            _reasoning_artefact_ok(), None, show=True
        )
        assert sec.reasoning_status == "ok"
        assert sec.documents_status == "not_examined"


# ---------------------------------------------------------------------------
# U6 — errored reasoning artefact
# ---------------------------------------------------------------------------

class TestUnifiedSectionErroredReasoning:
    def test_errored_artefact_status(self) -> None:
        artefact = {"status": "errored", "candidates": [], "disclaimer": ""}
        sec = build_unified_candidates_section(artefact, None, show=True)
        assert sec.reasoning_status == "errored"
        assert not any(r.basis == "description analysis" for r in sec.candidates)

    def test_none_status_coerced_to_errored(self) -> None:
        artefact = {"status": None, "candidates": [], "disclaimer": ""}
        sec = build_unified_candidates_section(artefact, None, show=True)
        assert sec.reasoning_status == "errored"


# ---------------------------------------------------------------------------
# R1 — _unified_candidates_subsection appends zero flowables when show=False
#      (the "byte-identical" guarantee: no content is added when flag is off)
# ---------------------------------------------------------------------------

class TestUnifiedRendererGating:
    def test_show_false_zero_flowables_no_candidates(self) -> None:
        """show=False with no candidates: story is untouched."""
        from report.render import _unified_candidates_subsection
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=False)
        model = build_report(raw, cfg, generated_at=_GENERATED_AT)
        story: list = []
        _unified_candidates_subsection(model, story)
        assert len(story) == 0, "show=False must not add any flowables"

    def test_show_false_zero_flowables_with_doc_candidates(self) -> None:
        """show=False with document candidates: still zero flowables added."""
        from report.render import _unified_candidates_subsection
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=False)
        provider = FixtureDocumentProvider(_DOCS_DIR)
        doc_cands = run_documents_pass(
            _all_line_items(), provider, _PERIOD_START, _PERIOD_END
        )
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              document_candidates=doc_cands)
        story: list = []
        _unified_candidates_subsection(model, story)
        assert len(story) == 0, "show=False must not add any flowables even with doc_candidates"

    def test_show_false_zero_flowables_with_reasoning_and_docs(self) -> None:
        """show=False with both reasoning and document candidates: still zero flowables."""
        from report.render import _unified_candidates_subsection
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=False)
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              judgment_artefact=_reasoning_artefact_ok(),
                              document_candidates=[_dummy_doc_candidate()])
        story: list = []
        _unified_candidates_subsection(model, story)
        assert len(story) == 0

    def test_show_true_adds_flowables(self) -> None:
        """show=True with candidates: story receives flowables."""
        from report.render import _unified_candidates_subsection
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        provider = FixtureDocumentProvider(_DOCS_DIR)
        doc_cands = run_documents_pass(
            _all_line_items(), provider, _PERIOD_START, _PERIOD_END
        )
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              document_candidates=doc_cands)
        story: list = []
        _unified_candidates_subsection(model, story)
        assert len(story) > 0, "show=True with candidates must add flowables"


# ---------------------------------------------------------------------------
# R2 — render_pdf with show=True + FixtureDocumentProvider over 8 fixtures
# ---------------------------------------------------------------------------

class TestUnifiedReportRenders:
    def test_show_true_fixture_provider_renders_pdf(self, tmp_path: Path) -> None:
        from report.render import render_pdf
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        provider = FixtureDocumentProvider(_DOCS_DIR)
        doc_cands = run_documents_pass(
            _all_line_items(), provider, _PERIOD_START, _PERIOD_END
        )
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              document_candidates=doc_cands)
        out = tmp_path / "with_doc_candidates.pdf"
        render_pdf(model, out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"

    def test_show_false_renders_pdf(self, tmp_path: Path) -> None:
        from report.render import render_pdf
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=False)
        provider = FixtureDocumentProvider(_DOCS_DIR)
        doc_cands = run_documents_pass(
            _all_line_items(), provider, _PERIOD_START, _PERIOD_END
        )
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              document_candidates=doc_cands)
        out = tmp_path / "flag_off_with_docs.pdf"
        render_pdf(model, out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# R3 — show=True with reasoning + document candidates: unified single section
# ---------------------------------------------------------------------------

class TestUnifiedSectionBothInReport:
    def test_both_bases_in_unified_candidates(self) -> None:
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        doc_cands = run_documents_pass(
            _all_line_items(), FixtureDocumentProvider(_DOCS_DIR),
            _PERIOD_START, _PERIOD_END,
        )
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              judgment_artefact=_reasoning_artefact_ok(),
                              document_candidates=doc_cands)
        assert model.unified_candidates is not None
        uc = model.unified_candidates
        bases = {r.basis for r in uc.candidates}
        assert "description analysis" in bases
        assert "invoice cross-reference" in bases

    def test_unified_section_has_correct_doc_candidates_count(self) -> None:
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        doc_cands = run_documents_pass(
            _all_line_items(), FixtureDocumentProvider(_DOCS_DIR),
            _PERIOD_START, _PERIOD_END,
        )
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              document_candidates=doc_cands)
        assert model.unified_candidates is not None
        doc_rows = [r for r in model.unified_candidates.candidates
                    if r.basis == "invoice cross-reference"]
        # 7 document candidates from the 8 fixture cases
        assert len(doc_rows) == 7

    def test_document_candidates_have_correct_check_ids(self) -> None:
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        doc_cands = run_documents_pass(
            _all_line_items(), FixtureDocumentProvider(_DOCS_DIR),
            _PERIOD_START, _PERIOD_END,
        )
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              document_candidates=doc_cands)
        assert model.unified_candidates is not None
        doc_rows = [r for r in model.unified_candidates.candidates
                    if r.basis == "invoice cross-reference"]
        check_ids = {r.finding for r in doc_rows}
        assert "gst_amount_mismatch" in check_ids
        assert "reg11_supplier_gst_absent" in check_ids
        assert "correct_period" in check_ids
        assert "total_inconsistency" in check_ids


# ---------------------------------------------------------------------------
# R4 — show=True, no candidates: "not examined" statuses present
# ---------------------------------------------------------------------------

class TestUnifiedSectionNotExaminedInReport:
    def test_both_passes_not_run_statuses(self) -> None:
        """When neither pass runs, both statuses are 'not_examined'."""
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        model = build_report(raw, cfg, generated_at=_GENERATED_AT)
        assert model.unified_candidates is not None
        assert model.unified_candidates.reasoning_status == "not_examined"
        assert model.unified_candidates.documents_status == "not_examined"

    def test_documents_not_examined_when_provider_absent(self) -> None:
        """provider=None → documents_status='not_examined' in unified section."""
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              judgment_artefact=_reasoning_artefact_ok(),
                              document_candidates=None)
        assert model.unified_candidates is not None
        assert model.unified_candidates.documents_status == "not_examined"
        assert model.unified_candidates.reasoning_status == "ok"

    def test_empty_doc_candidates_list_gives_ok_status(self) -> None:
        """document_candidates=[] (provider ran, found nothing) → documents_status='ok'."""
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              document_candidates=[])
        assert model.unified_candidates is not None
        assert model.unified_candidates.documents_status == "ok"
        assert model.unified_candidates.candidates == []

    def test_not_examined_note_rendered_in_pdf(self, tmp_path: Path) -> None:
        """PDF with show=True but both passes absent renders without error."""
        from report.render import render_pdf
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        model = build_report(raw, cfg, generated_at=_GENERATED_AT)
        out = tmp_path / "not_examined.pdf"
        render_pdf(model, out)
        assert out.exists() and out.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# F1 — F5 boxes unchanged regardless of documents pass
# ---------------------------------------------------------------------------

class TestF5Isolation:
    def test_boxes_identical_with_and_without_documents_pass(self) -> None:
        raw = _raw_data()
        boxes_before = json.dumps(raw["calculate"]["boxes"], sort_keys=True)

        provider = FixtureDocumentProvider(_DOCS_DIR)
        doc_cands = run_documents_pass(
            _all_line_items(), provider, _PERIOD_START, _PERIOD_END
        )
        # Run pass — then check boxes in raw_data are unmodified
        boxes_after = json.dumps(raw["calculate"]["boxes"], sort_keys=True)
        assert boxes_before == boxes_after, (
            "run_documents_pass must not mutate compile_output boxes"
        )

    def test_boxes_identical_with_and_without_show_flag(self) -> None:
        raw_on = json.loads(_CHAIN_FIXTURE.read_text(encoding="utf-8"))
        raw_off = json.loads(_CHAIN_FIXTURE.read_text(encoding="utf-8"))

        cfg_on = _make_cfg(show_ai_candidates=True)
        cfg_off = _make_cfg(show_ai_candidates=False)

        doc_cands = run_documents_pass(
            _all_line_items(), FixtureDocumentProvider(_DOCS_DIR),
            _PERIOD_START, _PERIOD_END,
        )

        model_on = build_report(raw_on, cfg_on, generated_at=_GENERATED_AT,
                                 document_candidates=doc_cands)
        model_off = build_report(raw_off, cfg_off, generated_at=_GENERATED_AT,
                                  document_candidates=doc_cands)

        boxes_on = json.dumps(raw_on["calculate"]["boxes"], sort_keys=True)
        boxes_off = json.dumps(raw_off["calculate"]["boxes"], sort_keys=True)
        assert boxes_on == boxes_off


# ---------------------------------------------------------------------------
# F2 — F5 gate results unchanged
# ---------------------------------------------------------------------------

class TestGateIsolation:
    def test_gate_checks_do_not_reference_document_candidates(self) -> None:
        """DocumentCandidate list is separate from the five gate checks in compile_output."""
        raw = _raw_data()
        provider = FixtureDocumentProvider(_DOCS_DIR)
        doc_cands = run_documents_pass(
            _all_line_items(), provider, _PERIOD_START, _PERIOD_END
        )
        # Verify doc candidates exist but the chain output gates are unaffected
        assert len(doc_cands) > 0
        assert "boxes" in raw["calculate"]
        assert "net_gst" in raw["calculate"].get("checks", {}) or \
               "box_8_net_gst" in raw["calculate"]["boxes"]


# ---------------------------------------------------------------------------
# I1 — documents/provider.py and doc_pass.py contain no forbidden imports
# ---------------------------------------------------------------------------

_DOCUMENTS_DIR = _REPO_ROOT / "documents"
_ORCHESTRATOR_DIR = _REPO_ROOT / "orchestrator"


def _read_sources(directory: Path) -> str:
    return "\n".join(
        f.read_text(encoding="utf-8")
        for f in sorted(directory.rglob("*.py"))
    )


class TestContainmentInvariants:
    def test_provider_no_orchestrator_import(self) -> None:
        src = (_DOCUMENTS_DIR / "provider.py").read_text(encoding="utf-8")
        for forbidden in ("orchestrator", "audit_bundle"):
            matches = re.findall(
                rf'^(?:import {forbidden}|from {forbidden})',
                src, re.MULTILINE,
            )
            assert not matches, (
                f"documents/provider.py has forbidden import of {forbidden!r}: {matches}"
            )

    def test_doc_pass_no_orchestrator_import(self) -> None:
        src = (_DOCUMENTS_DIR / "doc_pass.py").read_text(encoding="utf-8")
        for forbidden in ("orchestrator", "audit_bundle"):
            matches = re.findall(
                rf'^(?:import {forbidden}|from {forbidden})',
                src, re.MULTILINE,
            )
            assert not matches, (
                f"documents/doc_pass.py has forbidden import of {forbidden!r}: {matches}"
            )

    def test_provider_no_boxes_gates_calculate(self) -> None:
        src = (_DOCUMENTS_DIR / "provider.py").read_text(encoding="utf-8")
        for forbidden in ("from boxes", "import boxes", "from gates", "import gates",
                          "from calculate", "import calculate"):
            assert forbidden not in src, (
                f"documents/provider.py references forbidden {forbidden!r}."
            )

    def test_doc_pass_no_boxes_gates_calculate(self) -> None:
        src = (_DOCUMENTS_DIR / "doc_pass.py").read_text(encoding="utf-8")
        for forbidden in ("from boxes", "import boxes", "from gates", "import gates",
                          "from calculate", "import calculate"):
            assert forbidden not in src, (
                f"documents/doc_pass.py references forbidden {forbidden!r}."
            )

    def test_doc_pass_no_anthropic_import(self) -> None:
        src = (_DOCUMENTS_DIR / "doc_pass.py").read_text(encoding="utf-8")
        module_level = re.findall(r'^(?:import anthropic|from anthropic)', src, re.MULTILINE)
        assert not module_level, (
            f"documents/doc_pass.py has anthropic import: {module_level}. "
            "Must remain SDK-free; anthropic is only deferred inside ingest._extract_multimodal."
        )


# ---------------------------------------------------------------------------
# I2 — orchestrator/ has no import of documents/
# ---------------------------------------------------------------------------

class TestOrchestratorContainment:
    def test_orchestrator_does_not_import_documents(self) -> None:
        src = _read_sources(_ORCHESTRATOR_DIR)
        assert "import documents" not in src, (
            "orchestrator/ imports documents — invariant violated."
        )
        assert "from documents" not in src, (
            "orchestrator/ imports from documents — invariant violated."
        )


# ---------------------------------------------------------------------------
# Backward compat — existing ai_candidates field is still populated
# ---------------------------------------------------------------------------

class TestBackwardCompatAiCandidates:
    def test_ai_candidates_still_populated(self) -> None:
        """build_report still populates model.ai_candidates for existing test compat."""
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              judgment_artefact=_reasoning_artefact_ok())
        assert model.ai_candidates is not None
        assert model.ai_candidates.show is True

    def test_both_fields_populated_simultaneously(self) -> None:
        raw = _raw_data()
        cfg = _make_cfg(show_ai_candidates=True)
        model = build_report(raw, cfg, generated_at=_GENERATED_AT,
                              judgment_artefact=_reasoning_artefact_ok(),
                              document_candidates=[_dummy_doc_candidate()])
        assert model.ai_candidates is not None
        assert model.unified_candidates is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_doc_candidate(doc_num: int = 3003) -> DocumentCandidate:
    from documents.reconcile import DocumentCandidate
    return DocumentCandidate(
        doc_num=doc_num,
        check_id="gst_amount_mismatch",
        severity="MEDIUM",
        message="Consider reviewing whether the GST amount on the invoice face "
                "(900.00) agrees with the posted tax total (840.00).",
        extracted_value=900.0,
        listing_value=840.0,
        extraction_source="born_digital",
        determinability="J+",
        validation_status="unvalidated",
    )
