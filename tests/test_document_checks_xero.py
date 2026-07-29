"""tests/test_document_checks_xero.py — T-E(2): the four document checks on Xero.

D-40: coverage becomes three-state through the EXISTING LEVELS vocabulary — no documents
-> unavailable with today's reason BYTE-IDENTICAL (T1 pins it BY REFERENCE, never a
hand-copy); partial -> degraded with a COMPUTED n-of-m (T4 is the enforcement: a
hardcoded count passes T2 and fails T4); complete -> full.

D-45: /sign/upload accepts review_id and threads the review's documents, so the sealed
paper carries what the screen showed. The sign RESPONSE has no queue key (7 keys,
measured), so findings parity is asserted from the SEALED PAPER's text (T11), per
Terry's test-shape correction.

D-46: document cross-reference candidates render on the paper UNGATED — they are
deterministic comparisons over extracted values and share only a RENDERER with the
AI-Surfaced (reasoning/LLM) section, which stays flag-gated (T15). Each candidate
renders its extraction provenance (T16): born-digital extraction is deterministic end
to end; a multimodal (scanned) extraction says so on its face.

Hermetic: every store root under tmp_path; committed 2026Q2 corpus fixtures only.
"""
import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agent.review_store as review_store
import api.app as app_module
import audit_bundle.seal as seal_mod
import engine.review as engine_review
import feeders.coverage_status as coverage_status
import ui.sign as ui_sign
from documents.reconcile import coerce_doc_num
from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period

client = TestClient(app_module.app)

_REPO = Path(__file__).resolve().parent.parent
_F5 = _REPO / "tests" / "fixtures" / "xero-demo-2026Q2" / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_DOCS = _REPO / "tests" / "fixtures" / "xero-demo-2026Q2" / "source_documents"
_MANIFEST = _REPO / "tests" / "fixtures" / "xero-demo-2026Q2" / "fixture_manifest.csv"

_FOUR = ("gst_amount_mismatch", "correct_period", "total_inconsistency", "reg11_supplier_gst_absent")

_ALL_REFS = None  # populated lazily from the reader (the review's own document population)


def _all_refs():
    global _ALL_REFS
    if _ALL_REFS is None:
        reader = XeroF5ChainReader(_F5)
        period = parse_review_period(_F5)
        refs = set()
        for entity in ("Invoices", "PurchaseInvoices", "CreditNotes", "PurchaseCreditNotes"):
            for d in reader.fetch_invoices(entity, period["start"], period["end"]):
                refs.add(str(d["DocNum"]))
        _ALL_REFS = sorted(refs)
    return _ALL_REFS


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(review_store, "_REVIEWS_ROOT", tmp_path / "reviews")
    monkeypatch.setattr(seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr(engine_review, "_REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(ui_sign, "DEFAULT_OUTPUT_DIR", tmp_path / "sign-out")
    return tmp_path


@pytest.fixture
def rid(roots):
    return client.post("/review-session", json={"label": "te2"}).json()["review_id"]


def _corpus_docs():
    return [(p.name, p.read_bytes()) for p in sorted(_DOCS.glob("*.pdf"))]


def _pdf_bytes(ref: str) -> bytes:
    """A minimal legible invoice PDF for reference *ref* (reportlab, in-memory)."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for ln in [
            "Synth Supplier Pte Ltd",
            "GST Reg No: 200600000Z",
            f"Invoice No: {ref}",
            "Invoice Date: 2026-05-15",
            "Subtotal (excl. GST): 100.00",
            "GST @ 9%: 9.00",
            "TOTAL (incl. GST): 109.00",
    ]:
        c.drawString(50, y, ln)
        y -= 20
    c.save()
    return buf.getvalue()


def _upload(rid_or_none, docs):
    files = [("file", (_F5.name, _F5.read_bytes()))]
    for name, body in docs:
        files.append(("documents", (name, body)))
    data = {"review_id": rid_or_none} if rid_or_none else {}
    return client.post("/review/upload", files=files, data=data)


def _sign(rid_or_none):
    data = {"reviewer_name": "TE2 Probe", "firm_name": "T"}
    if rid_or_none:
        data["review_id"] = rid_or_none
    return client.post("/sign/upload", files={"file": (_F5.name, _F5.read_bytes())}, data=data)


def _paper_text(sign_body) -> str:
    import pdfplumber
    with pdfplumber.open(sign_body["working_paper_path"]) as d:
        return "\n".join(pg.extract_text() or "" for pg in d.pages)


def _four_rows(body):
    return {r["check"]: r for r in body["coverage_status"] if r["check"] in _FOUR}


def _doc_queue_rows(body):
    return [i for i in body["queue"] if i["error_code"] in _FOUR]


# ── T1: no documents -> unavailable, byte-identical BY REFERENCE ─────────────────────

def test_t1_no_documents_is_byte_identical_unavailable(roots):
    body = _upload(None, []).json()
    rows = _four_rows(body)
    assert set(rows) == set(_FOUR)
    for check, row in rows.items():
        assert row["level"] == "unavailable"
        assert row["reason"] == coverage_status._doc_unavailable_reason(check)


# ── T2/T3: partial -> degraded n of m; complete -> full ──────────────────────────────

def test_t2_partial_set_is_degraded_with_the_computed_numbers(rid):
    body = _upload(rid, _corpus_docs()).json()
    matched = sorted(set(_all_refs()) & {Path(n).stem for n, _ in _corpus_docs()})
    n, m = len(matched), len(_all_refs())
    assert 0 < n < m
    for check, row in _four_rows(body).items():
        assert row["level"] == "degraded", (check, row)
        assert f"{n} of {m}" in row["reason"], row["reason"]


def test_t3_complete_set_is_full(rid):
    docs = [(f"{ref}.pdf", _pdf_bytes(ref)) for ref in _all_refs()]
    body = _upload(rid, docs).json()
    for check, row in _four_rows(body).items():
        assert row["level"] == "full", (check, row)


# ── T4: THE COUNT IS COMPUTED — different set sizes move the numbers ─────────────────

def test_t4_the_count_is_computed_not_asserted(roots):
    m = len(_all_refs())
    for take in (3, 5):
        rid = client.post("/review-session", json={"label": f"t4-{take}"}).json()["review_id"]
        docs = [(f"{ref}.pdf", _pdf_bytes(ref)) for ref in _all_refs()[:take]]
        body = _upload(rid, docs).json()
        for check, row in _four_rows(body).items():
            assert row["level"] == "degraded"
            assert f"{take} of {m}" in row["reason"], (take, row["reason"])


# ── T5: all four fire on their baits ─────────────────────────────────────────────────

def test_t5_all_four_fire_on_their_baits(rid):
    body = _upload(rid, _corpus_docs()).json()
    fired = {(i["error_code"], str(i["doc_num"])) for i in _doc_queue_rows(body)}
    assert ("gst_amount_mismatch", "BILL-3002") in fired
    assert ("reg11_supplier_gst_absent", "BILL-3003") in fired
    assert ("correct_period", "BILL-3009") in fired
    assert ("total_inconsistency", "BILL-3010") in fired
    amounts = next(i for i in _doc_queue_rows(body)
                   if i["error_code"] == "gst_amount_mismatch")
    assert "360.00" in amounts["description"] and "320.00" in amounts["description"]


# ── T6: every clean control stays silent, by name ────────────────────────────────────

def test_t6_clean_controls_stay_silent(rid):
    controls = [r["doc_num"] for r in csv.DictReader(open(_MANIFEST, encoding="utf-8-sig"))
                if "(clean control)" in json.dumps(r)]
    assert controls, "manifest must carry clean controls"
    body = _upload(rid, _corpus_docs()).json()
    fired_refs = {str(i["doc_num"]) for i in _doc_queue_rows(body)}
    offenders = sorted(fired_refs & set(controls))
    assert offenders == [], f"document checks fired on clean controls: {offenders}"


# ── T7: response key set unchanged either way ────────────────────────────────────────

def test_t7_response_key_set_unchanged(rid):
    with_docs = _upload(rid, _corpus_docs()).json()
    without = _upload(None, []).json()
    assert set(with_docs) == set(app_module.XERO_F5_UPLOAD_KEYS) == set(without)


# ── T8: boxes and gate verdicts byte-identical with and without documents ────────────

def test_t8_boxes_and_gates_move_nothing(roots):
    rid = client.post("/review-session", json={"label": "t8"}).json()["review_id"]
    plain = _upload(None, []).json()
    with_docs = _upload(rid, _corpus_docs()).json()
    assert plain["recomputed_client_coded_f5_boxes"] == with_docs["recomputed_client_coded_f5_boxes"]

    signed_plain = _sign(None).json()
    signed_docs = _sign(rid).json()
    g1 = json.loads((Path(signed_plain["bundle_dir"]) / "gates.json").read_text(encoding="utf-8"))
    g2 = json.loads((Path(signed_docs["bundle_dir"]) / "gates.json").read_text(encoding="utf-8"))
    assert g1 == g2


# ── T9: a document matching NO item is honest — no candidate, denominator arithmetic ──

def test_t9_unjoined_document_is_honest(rid):
    m = len(_all_refs())
    docs = [("BILL-3002.pdf", (_DOCS / "BILL-3002.pdf").read_bytes()),
            ("ZZZ-9999.pdf", _pdf_bytes("ZZZ-9999"))]
    body = _upload(rid, docs).json()
    for check, row in _four_rows(body).items():
        assert row["level"] == "degraded"
        assert f"1 of {m}" in row["reason"], row["reason"]   # ZZZ-9999 joins nothing
    fired_refs = {str(i["doc_num"]) for i in _doc_queue_rows(body)}
    assert "ZZZ-9999" not in fired_refs


# ── T10: the coercion is byte-identical for int inputs ───────────────────────────────

def test_t10_coercion_unit_pin():
    assert coerce_doc_num(605) == 605 and type(coerce_doc_num(605)) is int
    assert coerce_doc_num("605") == 605
    assert coerce_doc_num("BILL-3002") == "BILL-3002"
    assert coerce_doc_num(True) is True or coerce_doc_num(True) == 1  # bools never arrive; either is safe


# ── T11/T12: D-45 — the sealed paper carries what the screen showed ──────────────────

def test_t11_sign_with_rid_matches_the_screen(rid):
    screen = _upload(rid, _corpus_docs()).json()
    screen_pairs = {(i["error_code"], str(i["doc_num"])) for i in _doc_queue_rows(screen)}
    signed = _sign(rid).json()
    text = _paper_text(signed)
    assert "Source-Document Cross-Reference" in text
    for check, ref in screen_pairs:
        assert ref in text, f"paper omits {ref}"
        assert check.replace("_", " ") in text or check in text, f"paper omits {check}"
    n, m = len({Path(x).stem for x, _ in _corpus_docs()} & set(_all_refs())), len(_all_refs())
    for check, row in _four_rows(screen).items():
        assert row["level"] == "degraded"
    assert f"{n} of {m}" in text, "paper's coverage rows must carry the same computed count"


def test_t12_sign_without_rid_is_todays_behaviour(roots):
    signed = _sign(None).json()
    assert set(signed.keys()) == {"bundle_dir", "disclaimer", "firm_name",
                                  "reviewer_name", "source_kind", "validation_status",
                                  "working_paper_path"}
    text = _paper_text(signed)
    assert "Source-Document Cross-Reference" not in text
    assert coverage_status._doc_unavailable_reason("gst_amount_mismatch").split(" — ")[0] in text


# ── T13: the degraded reason is coverage FACT only ───────────────────────────────────

def test_t13_degraded_reason_is_fact_only(rid):
    body = _upload(rid, _corpus_docs()).json()
    for check, row in _four_rows(body).items():
        reason = row["reason"]
        assert "IRAS" not in reason
        assert "Reg" not in reason and "reg " not in reason
        assert "Section" not in reason and "ASK" not in reason


# ── T14–T17: D-46 — the ungated document section ─────────────────────────────────────

def test_t14_document_section_renders_with_flag_false(rid):
    _upload(rid, _corpus_docs())
    text = _paper_text(_sign(rid).json())
    assert "Source-Document Cross-Reference" in text
    for ref in ("BILL-3002", "BILL-3003", "BILL-3009", "BILL-3010"):
        assert ref in text


def test_t15_ai_surfaced_section_stays_gated(rid):
    _upload(rid, _corpus_docs())
    text = _paper_text(_sign(rid).json())
    assert "AI-Surfaced" not in text


def test_t16_extraction_provenance_renders_per_candidate(rid):
    _upload(rid, _corpus_docs())
    text = _paper_text(_sign(rid).json())
    assert "born-digital" in text


def test_t17_flag_true_renders_both_and_suppresses_signature(tmp_path):
    from config.loader import load_client_config
    from report.report import build_report
    from report.render import render_pdf
    from documents.reconcile import DocumentCandidate
    import pdfplumber

    cfg = load_client_config("xero_demo", check_connectivity=False)
    cfg.show_ai_candidates = True
    cand = DocumentCandidate(
        doc_num="BILL-3002", check_id="gst_amount_mismatch", severity="MEDIUM",
        message="Consider reviewing whether the GST amount on the invoice face (360.00) "
                "agrees with the SAP-posted tax total (320.00); the difference of 40.00 "
                "may indicate an input or coding error.",
        extracted_value=360.0, listing_value=320.0,
        extraction_source="born_digital", determinability="J+",
    )
    art = {"status": "ok", "candidates": [
        {"doc_num": 3006, "suspected_category": "entertainment",  # int: the reasoning branch keeps its int() (out of T-E(2) scope)
         "phrasing": "Consider reviewing this line."}]}
    sample = json.loads(
        (_REPO / "tests" / "fixtures" / "chain-run-sample.json").read_text(encoding="utf-8")
    )
    compile_output = sample.get("compile_output", sample)
    model = build_report(compile_output, cfg, generated_at="2026-07-29T00:00:00+00:00",
                         judgment_artefact=art, document_candidates=[cand])
    out = tmp_path / "t17.pdf"
    render_pdf(model, out)
    with pdfplumber.open(out) as d:
        text = "\n".join(pg.extract_text() or "" for pg in d.pages)
    assert "Source-Document Cross-Reference" in text
    assert "AI-Surfaced" in text
    assert "Signature suppressed" in text
