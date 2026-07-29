"""tests/test_dup_window_paper.py -- D-2026-07-27-dup-window FAILING-FIRST (paper layer).

BUILD ID: t-dup-window. End-to-end pins over the SIGNED xero_demo paper and the
response/oracle contracts:

  P1  xero_demo now DECLARES dup_window_enabled: true + dup_window_days: 92 (one
      GST filing period -- D-2026-07-29, superseding the G4b fixture-fitted 7,
      which was reverse-derived from BILL-3004/3005's 7-day gap; no IRAS source
      prescribes any window; the loader still refuses to guess).
  P2  (A2) the signed xero_demo F5 paper renders the Windowed Duplicate-Purchase
      Review with the BILL-3004/3005 pair: both doc_nums, both dates, the delta,
      the supplier.
  P3  (A4) the locked DUP_SAME_DAY caveat is REPLACED on the enabled paper (the
      "pending a worksheet-derived window" claim would be false there) and stays
      BYTE-IDENTICAL on a no-position paper -- the locked pin in
      tests/test_document_dup_section.py passes UNAMENDED.
  P4  (A5 pin) an undeclared-position config builds NO section (model field None) --
      the SAP paper's byte-identity is carried by construction.
  P6  (A6) BOX-ISOLATION at runtime: calculate.boxes + gate results canonical_json
      byte-identical with the window check enabled and disabled.
  P7  (A7) the six-key F5 upload response is untouched: exact key set, and no
      dup_window content anywhere in the serialized response body.
  P8  (A8) the enabled paper clears every negative pin under BOTH pdfplumber and
      pdfminer, including the "SAP" bare-substring ban on Xero-config papers and
      the empty-store "adjudication" pin.

HERMETIC: committed fixtures; tmp dirs; dummy SAP creds (file-import config, never
dialled); fresh audit subdir per sign (seal run_ts collision sidestep). No anthropic.
DOES NOT edit any existing test file.
"""
from __future__ import annotations

import dataclasses
import itertools
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from audit_bundle.canonical import canonical_json
from api.app import app
from config.loader import load_client_config

_UPLOAD_SEQ = itertools.count()
_REPO_ROOT = Path(__file__).resolve().parents[1]

_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_F5_NAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_CHAIN_SAMPLE = _REPO_ROOT / "tests" / "fixtures" / "chain-run-sample.json"

_LOCKED_SAMEDAY_CAVEAT = "same-day only pending a worksheet-derived window"

# A8 -- the negative pins, enumerated with their locked homes:
#   Severity/HIGH/MEDIUM/LOW      -> test_report_redesign_severity_removed.py (pdfminer)
#   AI-Surfaced Candidates (x2),
#   Signature suppressed,
#   Do not sign                   -> the four unamendable literals (decision-render R5c)
#   Not an issue / Mark known     -> UI verbs (test_decision_render.py)
#   adjudication                  -> empty-store silent-paper pin (test_decision_render.py
#                                    case-insensitive; test_sales_paper_box_pin.py exact)
#   SAP / SBODEMOSG               -> test_source_provenance.py:221-222 bare-substring ban
#                                    on Xero-config papers
_NEGATIVE_PINS = (
    "Severity", "HIGH", "MEDIUM", "LOW",
    "AI-Surfaced Candidates", "AI-surfaced candidates",
    "Signature suppressed", "Do not sign",
    "Not an issue", "Mark known",
    "adjudication", "Adjudication",
    "SAP", "SBODEMOSG",
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    return tmp_path


def _bump_audit() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"


def _sign_f5(client: TestClient) -> dict:
    _bump_audit()
    resp = client.post(
        "/sign/upload",
        data={"reviewer_name": "Collin Tan", "firm_name": ""},
        files={"file": (_F5_NAME, _F5_FIXTURE.read_bytes())},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _plumber_text(pdf_path) -> str:
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(pdf_path) as pdf:
        raw = " ".join((page.extract_text() or "") for page in pdf.pages)
    return " ".join(raw.split())


def _miner_text(pdf_path) -> str:
    high_level = pytest.importorskip("pdfminer.high_level")
    return " ".join(high_level.extract_text(str(pdf_path)).split())


# -- P1 -- the committed config declares the demo window ------------------------------


def test_p1_xero_demo_declares_the_demo_window():
    """xero_demo.yaml declares the window; the value is one GST filing period (D-2026-07-29)."""
    cfg = load_client_config("xero_demo", check_connectivity=False)
    assert cfg.dup_window_enabled is True
    assert cfg.dup_window_days == 92, (
        "one GST filing period. Supersedes the fixture-fitted 7 (D-2026-07-29): the "
        "prior value was reverse-derived from the BILL-3004/3005 bait gap. Still a "
        "NON-REGULATORY TUNING PARAMETER, OURS -- no IRAS source prescribes a window, "
        "key, or tolerance; ASK 3D.1.1(d) prescribes the QUESTION only."
    )


# -- P2 (A2) -- the pair renders on the signed xero_demo paper ------------------------


def test_p2_pair_renders_on_signed_paper(client, hermetic):
    body = _sign_f5(client)
    text = _plumber_text(body["working_paper_path"])

    assert "Windowed Duplicate-Purchase Review" in text
    assert "BILL-3004" in text and "BILL-3005" in text
    assert "2026-05-12" in text and "2026-05-19" in text
    assert "DupSupplier Pte Ltd" in text
    assert "7 days apart" in text, "the delta must be on the page"
    # G2: cite + OURS label present (same-paragraph coupling is unit-pinned in
    # tests/test_dup_window_section.py U8).
    assert "3D.1.1(d)" in text
    assert "non-regulatory tuning parameter" in text
    # G7 vacuity + G8 non-actionability caveats reach the page.
    assert "UNTESTED, not absent" in text
    assert "cannot be keyed by the decision ledger" in text
    # The sealed bundle carries the findings the paper renders (gloss, not filter).
    sealed = json.loads(
        (Path(body["bundle_dir"]) / "compile-output.json").read_text(encoding="utf-8")
    )
    finds = sealed["document_dup_window_findings"]
    assert len(finds) == 1 and finds[0]["doc_nums"] == ["BILL-3004", "BILL-3005"]


# -- P3 (A4) -- the conditional caveat, both directions -------------------------------


def test_p3_sameday_caveat_replaced_on_enabled_paper(client, hermetic):
    body = _sign_f5(client)
    text = _plumber_text(body["working_paper_path"])
    assert _LOCKED_SAMEDAY_CAVEAT not in text, (
        "on a paper where the window check ran, 'pending a worksheet-derived window' "
        "is a false statement and must not render"
    )
    assert "same-day pairs only in this section" in text


def test_p3b_sameday_caveat_byte_identical_on_no_position_paper(tmp_path):
    """A config with NO dup_window position renders the locked caveat verbatim --
    the locked pin (tests/test_document_dup_section.py) passes UNAMENDED."""
    from report.contract import load_compile_output
    from report.report import build_report
    from report.render import render_pdf
    from config.loader import ClientConfig

    cfg = ClientConfig(
        client_id="sbodemosg", client_name="Plain Demo",
        gst_registration_number="M12345678X", applicable_gst_rate=0.07,
        service_layer_url="https://fake", company_db="SBODEMOSG",
        username="manager", password="manager", ssl_verify=False,
        fiscal_year_start_month=1, custom_vat_groups={}, completeness_threshold=0.1,
        reviewer_name="Terry Yeo", firm_name="AgentAssist Pte Ltd",
    )
    assert cfg.dup_window_enabled is False and cfg.dup_window_days is None
    # chain-run-sample predates DUP_SAME_DAY (no key -> not_examined -> that section
    # never renders, caveats included). Give the same-day check an examined-clean
    # state so its caveat block is ON the page for the byte-identity assertion.
    import copy as _copy

    co = _copy.deepcopy(load_compile_output(_CHAIN_SAMPLE))
    co["document_dup_findings"] = []
    model = build_report(
        co, cfg,
        generated_at="2026-06-01T09:11:28+00:00",
    )
    assert model.document_dup_window is None, (
        "no declared position -> no section -> the SAP paper stays byte-identical (A5)"
    )
    out = tmp_path / "plain.pdf"
    render_pdf(model, out)
    text = _plumber_text(out)
    assert _LOCKED_SAMEDAY_CAVEAT in text
    assert "Windowed Duplicate-Purchase Review" not in text


# -- P6 (A6) -- BOX-ISOLATION at runtime ----------------------------------------------


def test_p6_boxes_and_gates_byte_identical_enabled_vs_disabled(monkeypatch):
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    from feeders.xero_f5_reader import XeroF5ChainReader
    from orchestrator.chain import run_chain

    period = {"start": "2026-04-01", "end": "2026-06-30"}
    cfg_on = load_client_config("xero_demo", check_connectivity=False)
    assert cfg_on.dup_window_enabled is True
    cfg_off = dataclasses.replace(cfg_on, dup_window_enabled=False)

    co_on, gates_on = run_chain(cfg_on, period, reader=XeroF5ChainReader(_F5_FIXTURE))
    co_off, gates_off = run_chain(cfg_off, period, reader=XeroF5ChainReader(_F5_FIXTURE))

    assert "document_dup_window_findings" in co_on
    assert "document_dup_window_findings" not in co_off
    assert canonical_json(co_on["calculate"]["boxes"]) == canonical_json(
        co_off["calculate"]["boxes"]
    )
    assert canonical_json(gates_on) == canonical_json(gates_off)


# -- P7 (A7) -- the six-key F5 upload response is untouched ---------------------------


def test_p7_f5_upload_response_contract_untouched(client, hermetic):
    _bump_audit()
    resp = client.post(
        "/review/upload",
        files={"file": (_F5_NAME, _F5_FIXTURE.read_bytes())},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "source_kind", "validation_status", "disclaimer", "coverage_status",
        "queue", "recomputed_client_coded_f5_boxes",
    }, "the six-key contract that cost seven hand-amended files must not move"
    assert "dup_window" not in json.dumps(body), (
        "no DUP_WINDOW content may leak into the response body"
    )


# -- P8 (A8) -- negative pins under BOTH extractors on the ENABLED paper --------------


def test_p8_enabled_paper_clears_negative_pins_both_extractors(client, hermetic):
    body = _sign_f5(client)
    for extract in (_plumber_text, _miner_text):
        text = extract(body["working_paper_path"])
        for banned in _NEGATIVE_PINS:
            assert banned not in text, (
                f"enabled paper must not carry {banned!r} ({extract.__name__})"
            )
