"""tests/test_source_provenance.py — failing-first guard for build
D-2026-07-20-source-provenance.

WHAT THIS BUILD DOES (not yet implemented — these tests MUST fail today for the RIGHT
reason, i.e. the feature is absent, not a typo):

  1. NEW ``config/source_labels.py`` — a source_system → display-name mapping
     (``SOURCE_DISPLAY_NAMES`` / ``SOURCE_DISPLAY_NAMES_LONG``) + a ``source_display_name``
     helper with None/empty → "sap_b1" fallback and unknown-string passthrough.
  2. ``api/viewmodel.upload_disclaimer(source_kind)`` — Xero-worded / uploaded-extract-worded /
     fallback-to-``viewmodel.DISCLAIMER`` text, every value carrying the unvalidated token.
  3. ``api/app.py`` upload endpoints emit the source-aware disclaimer; the b1 GET /review path
     keeps the OLD SBODEMOSG wording.
  4. ``report.report.ReportModel`` gains ``source_label``; ``build_report`` sets it from
     ``client_config.source_system``.
  5. ``report.sections`` — signature / not-examined / judgment builders become source-aware
     (byte-identical for sap/missing/None; Xero wording for xero configs).
  6. ``report.render`` F5 caption becomes source-aware ("Computed from Xero …" vs
     "Computed from SAP B1 …").

FAILING-FIRST: written BEFORE the implementation exists. Everything that touches
``config.source_labels``, ``upload_disclaimer``, ``source_label``, and the new source-aware
wordings is expected to be RED now. Tests that merely assert CURRENT behaviour (the b1
SBODEMOSG retention, the byte-identity of the existing DISCLAIMER_TEXT / SAP caption for a
plain sap config, the 2-arg judgment back-compat) may already be GREEN — that is the
three-times invariant expressed as a lock on the unchanged path.

APPEND-ONLY BOUNDARY: this is a NEW test file. No existing test file is modified or deleted
(CLAUDE.md "never edit an existing test" boundary). ``config.source_labels`` is imported
INSIDE the test bodies so a missing module raises ImportError as a genuine FAILURE — it is
deliberately NOT skipped.

DELIBERATE #44 RESIDUE: the supplier-registration mechanism nouns "FederalTaxID" and
"User Defined Field" stay SAP-worded on ALL sources this build (open item #44). The tests
LOCK that they are NOT relabelled even on the Xero path.

Hermetic: no network, no anthropic import, no live SAP/Xero. SAP off, dummy creds only.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api import viewmodel
from report.constants import DISCLAIMER_TEXT
from report.contract import load_compile_output
from report.enrich import EnrichedFinding
from report.render import render_pdf
from report.report import build_report
from report.sections import (
    build_judgment_section,
    build_not_examined_section,
    build_signature_section,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"

# The committed real-FORMAT Xero IRAS-F5 export fixture (synthetic transactions), mirroring
# tests/test_xero_engine_upload.py.
_XERO_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_XERO_FILENAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

# The token every disclaimer value must carry (T2.11 is the binding validation gate).
_UNVALIDATED_TOKEN = "validation_status=unvalidated (T2.11 is the binding gate)"


# ── Shared duck-typed config + finding builders ───────────────────────────────────────

def _ns_cfg(source_system: str | None = "sap_b1", *, omit_source: bool = False):
    """A duck-typed ClientConfig-lookalike. The report section builders read every field
    via getattr, so a SimpleNamespace exercises the real code paths without a ClientConfig
    schema dependency (and lets us build the source_system-absent and source_system=None
    variants the fallback semantics require)."""
    kwargs = dict(
        client_name="Demo Co",
        gst_registration_number="M12345678X",
        reviewer_name="Terry Yeo",
        firm_name="AgentAssist Pte Ltd",
        custom_vat_groups={},
    )
    if not omit_source:
        kwargs["source_system"] = source_system
    return SimpleNamespace(**kwargs)


def _finding(error_code: str, vat_group: str | None, doc_num: int) -> EnrichedFinding:
    """Mirror the EnrichedFinding constructor for the judgment-section grouping keys
    (error_code + vat_group); template_ref/appendix1 are inert for build_judgment_section."""
    return EnrichedFinding(
        doc_num=doc_num,
        error_code=error_code,
        severity="MEDIUM",
        vat_group=vat_group,
        doc_currency="SGD",
        card_name="Test Co",
        doc_date="2024-07-15",
        line_total=1000.0,
        tax_total=90.0,
        line_count=1,
        description=f"{error_code} finding on doc {doc_num}",
        recommendation="Review.",
        template_ref={"number": 6, "label": "Template 6"},
        appendix1_category="Input tax to be disallowed",
        doc_total=1090.0,
    )


def _group(section, group_id: str):
    return next((g for g in section.groups if g.group_id == group_id), None)


@pytest.fixture(scope="module")
def compile_output() -> dict:
    return load_compile_output(_FIXTURE)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# ══ TestSourceLabels — config/source_labels.py mapping + fallbacks ═════════════════════

class TestSourceLabels:
    """The NEW config/source_labels.py. Imported INSIDE each test so its absence raises
    ImportError as a real FAILURE (never a skip)."""

    def test_short_mapping_values(self):
        from config.source_labels import SOURCE_DISPLAY_NAMES

        assert SOURCE_DISPLAY_NAMES["sap_b1"] == "SAP B1"
        assert SOURCE_DISPLAY_NAMES["xero"] == "Xero"
        assert SOURCE_DISPLAY_NAMES["xero_sales"] == "Xero"
        assert SOURCE_DISPLAY_NAMES["extract"] == "uploaded extract"

    def test_long_mapping_differs_only_for_sap(self):
        from config.source_labels import SOURCE_DISPLAY_NAMES, SOURCE_DISPLAY_NAMES_LONG

        assert SOURCE_DISPLAY_NAMES_LONG["sap_b1"] == "SAP Business One"
        # Every non-sap key is identical between the short and long maps.
        for key in ("xero", "xero_sales", "extract"):
            assert SOURCE_DISPLAY_NAMES_LONG[key] == SOURCE_DISPLAY_NAMES[key]

    def test_display_name_known(self):
        from config.source_labels import source_display_name

        assert source_display_name("sap_b1") == "SAP B1"
        assert source_display_name("xero") == "Xero"
        assert source_display_name("xero_sales") == "Xero"
        assert source_display_name("extract") == "uploaded extract"

    def test_display_name_long(self):
        from config.source_labels import source_display_name

        assert source_display_name("sap_b1", long=True) == "SAP Business One"
        assert source_display_name("xero", long=True) == "Xero"

    def test_none_and_empty_fall_back_to_sap(self):
        from config.source_labels import source_display_name

        assert source_display_name(None) == "SAP B1"
        assert source_display_name("") == "SAP B1"
        assert source_display_name(None, long=True) == "SAP Business One"
        assert source_display_name("", long=True) == "SAP Business One"

    def test_unknown_string_returns_raw(self):
        from config.source_labels import source_display_name

        # An unrecognised (but genuinely non-empty) system name passes through verbatim —
        # we never silently coerce a real non-SAP system into "SAP B1".
        assert source_display_name("myob") == "myob"
        assert source_display_name("quickbooks", long=True) == "quickbooks"


# ══ TestUploadDisclaimer — api.viewmodel.upload_disclaimer, both directions ════════════

class TestUploadDisclaimer:
    """upload_disclaimer(source_kind) — new function on the existing api.viewmodel module.
    It does not exist yet, so every call raises AttributeError (a genuine failure)."""

    def test_xero_kinds_share_one_xero_text(self):
        f5 = viewmodel.upload_disclaimer("xero_f5_upload")
        sales = viewmodel.upload_disclaimer("xero_sales_upload")
        assert f5 == sales, "both Xero upload kinds must return the SAME Xero-worded text"
        assert "Xero" in f5
        assert "SBODEMOSG" not in f5
        assert "SAP" not in f5

    def test_extract_kinds_share_one_extract_text(self):
        review = viewmodel.upload_disclaimer("extract_review")
        upload = viewmodel.upload_disclaimer("extract_upload")
        assert review == upload, "both extract kinds must return the SAME extract-worded text"
        assert "SBODEMOSG" not in review
        assert "SAP" not in review

    def test_xero_and_extract_texts_differ(self):
        assert viewmodel.upload_disclaimer("xero_f5_upload") != viewmodel.upload_disclaimer(
            "extract_review"
        )

    def test_unknown_kind_falls_back_to_module_disclaimer(self):
        # Any other/unknown kind is the existing viewmodel.DISCLAIMER constant, byte-identical.
        assert viewmodel.upload_disclaimer("something_else") == viewmodel.DISCLAIMER
        assert viewmodel.upload_disclaimer("") == viewmodel.DISCLAIMER

    def test_every_value_carries_the_trust_tokens(self):
        for kind in (
            "xero_f5_upload",
            "xero_sales_upload",
            "extract_review",
            "extract_upload",
            "unknown_kind",
        ):
            text = viewmodel.upload_disclaimer(kind)
            assert _UNVALIDATED_TOKEN in text, f"{kind}: missing unvalidated token"
            assert "not a compliance verdict" in text, f"{kind}: missing verdict caveat"


# ══ TestApiBothDirections — TestClient: xero upload Xero-worded; b1 review SBODEMOSG ═══

class TestApiBothDirections:

    @pytest.fixture()
    def hermetic_engine(self, tmp_path, monkeypatch):
        """Redirect the engine PDF dir + audit root to tmp and set dummy SAP creds (DEBT-9);
        mirrors tests/test_xero_engine_upload.py. No SAP call is made on the Xero path."""
        monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
        monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
        monkeypatch.setenv("SAP_USERNAME", "dummy")
        monkeypatch.setenv("SAP_PASSWORD", "dummy")

    def test_xero_upload_disclaimer_is_xero_worded(self, client, hermetic_engine):
        assert _XERO_FIXTURE.is_file(), f"committed Xero fixture missing: {_XERO_FIXTURE}"
        resp = client.post(
            "/review/upload",
            files={"file": (_XERO_FILENAME, _XERO_FIXTURE.read_bytes())},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_kind"] == "xero_f5_upload"
        disclaimer = body["disclaimer"]
        assert "Xero" in disclaimer
        assert "SBODEMOSG" not in disclaimer
        assert "SAP" not in disclaimer

    def test_b1_review_retains_sbodemosg_wording(self, client):
        body = client.get("/review/sbodemosg/2024Q3").json()
        assert "SBODEMOSG" in body["disclaimer"], (
            "the b1 demo review disclaimer must keep the OLD SBODEMOSG wording (unchanged path)"
        )


# ══ TestSignatureDisclaimer — build_signature_section byte-identity vs Xero wording ════

class TestSignatureDisclaimer:

    def test_sap_is_byte_identical_to_disclaimer_text(self):
        sig = build_signature_section(_ns_cfg("sap_b1"))
        assert sig.disclaimer == DISCLAIMER_TEXT

    def test_missing_source_attr_defaults_to_sap(self):
        sig = build_signature_section(_ns_cfg(omit_source=True))
        assert sig.disclaimer == DISCLAIMER_TEXT

    def test_none_source_defaults_to_sap(self):
        sig = build_signature_section(_ns_cfg(None))
        assert sig.disclaimer == DISCLAIMER_TEXT

    def test_xero_disclaimer_is_reworded(self):
        sig = build_signature_section(_ns_cfg("xero"))
        assert "Xero transaction data" in sig.disclaimer
        assert "SAP Business One" not in sig.disclaimer


# ══ TestNotExamined — source-aware labels, no leaked placeholder, count invariance ════

class TestNotExamined:

    def test_sap_has_no_placeholder_and_labels_sap(self, compile_output):
        sec = build_not_examined_section(compile_output, _ns_cfg("sap_b1"))
        for item in sec.items:
            assert "{source_label}" not in item, f"leaked placeholder: {item!r}"
        assert any("in SAP B1" in item for item in sec.items), (
            "at least one not-examined item must be SAP-labelled on the sap path"
        )

    def test_xero_labels_xero_and_never_sap(self, compile_output):
        sec = build_not_examined_section(compile_output, _ns_cfg("xero"))
        assert any("in Xero" in item for item in sec.items), (
            "at least one not-examined item must be Xero-labelled on the xero path"
        )
        for item in sec.items:
            assert "{source_label}" not in item, f"leaked placeholder: {item!r}"
            assert "SAP B1" not in item, f"SAP label leaked onto the xero path: {item!r}"

    def test_item_count_is_source_invariant(self, compile_output):
        sap = build_not_examined_section(compile_output, _ns_cfg("sap_b1"))
        xero = build_not_examined_section(compile_output, _ns_cfg("xero"))
        missing = build_not_examined_section(compile_output, _ns_cfg(omit_source=True))
        assert len(sap.items) == len(xero.items) == len(missing.items), (
            "source labelling must not change the number of not-examined items"
        )


# ══ TestJudgment — optional client_config kwarg + both directions + #44 residue ═══════

class TestJudgment:

    def _findings(self):
        return [
            _finding("E2", "BL", 605),        # business-purpose / Reg 26-27 group
            _finding("NO_GST_REG", None, 592),  # supplier-registration group
        ]

    def test_two_arg_backcompat_defaults_to_sap(self, compile_output):
        # The original (compile_output, findings) call must still work — SAP wording.
        sec = build_judgment_section(compile_output, self._findings())
        bp = _group(sec, "business-purpose-reg26-27")
        assert bp is not None
        assert bp.judgment_question.endswith("claimed against it in SAP B1.")

    def test_client_config_none_defaults_to_sap(self, compile_output):
        sec = build_judgment_section(compile_output, self._findings(), client_config=None)
        bp = _group(sec, "business-purpose-reg26-27")
        assert bp.judgment_question.endswith("claimed against it in SAP B1.")

    def test_sap_cfg_business_purpose_wording(self, compile_output):
        sec = build_judgment_section(
            compile_output, self._findings(), client_config=_ns_cfg("sap_b1")
        )
        bp = _group(sec, "business-purpose-reg26-27")
        assert bp.judgment_question.endswith("claimed against it in SAP B1.")

    def test_xero_cfg_business_purpose_wording(self, compile_output):
        sec = build_judgment_section(
            compile_output, self._findings(), client_config=_ns_cfg("xero")
        )
        bp = _group(sec, "business-purpose-reg26-27")
        assert bp.judgment_question.endswith("claimed against it in Xero.")

    def test_supplier_registration_both_directions_keep_mechanism_nouns(self, compile_output):
        sap = _group(
            build_judgment_section(
                compile_output, self._findings(), client_config=_ns_cfg("sap_b1")
            ),
            "supplier-registration",
        )
        xero = _group(
            build_judgment_section(
                compile_output, self._findings(), client_config=_ns_cfg("xero")
            ),
            "supplier-registration",
        )
        assert "your SAP B1 instance" in sap.judgment_question
        assert "your Xero instance" in xero.judgment_question
        assert "your SAP B1 instance" not in xero.judgment_question
        # #44 residue: the mechanism nouns stay SAP-worded on BOTH sources this build.
        for q in (sap.judgment_question, xero.judgment_question):
            assert "FederalTaxID" in q
            assert "User Defined Field" in q


# ══ TestRenderedCaption — PDF F5 caption both directions (2 renders max) ═══════════════

class TestRenderedCaption:

    @staticmethod
    def _pdf_text(pdf_path: Path) -> str:
        pdfplumber = pytest.importorskip(
            "pdfplumber", reason="pdfplumber not installed — run: pip install pdfplumber"
        )
        with pdfplumber.open(pdf_path) as pdf:
            raw = " ".join(p.extract_text() or "" for p in pdf.pages)
        # Collapse whitespace so a phrase that wrapped across PDF lines still matches.
        return " ".join(raw.split())

    def test_sap_caption(self, compile_output, tmp_path):
        model = build_report(compile_output, _ns_cfg("sap_b1"), generated_at=_GENERATED_AT)
        out = tmp_path / "sap.pdf"
        render_pdf(model, out)
        text = self._pdf_text(out)
        assert "Computed from SAP B1 invoice and credit note lines" in text

    def test_xero_caption(self, compile_output, tmp_path):
        model = build_report(compile_output, _ns_cfg("xero"), generated_at=_GENERATED_AT)
        out = tmp_path / "xero.pdf"
        render_pdf(model, out)
        text = self._pdf_text(out)
        assert "Computed from Xero invoice and credit note lines" in text
