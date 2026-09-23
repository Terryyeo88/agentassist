"""
tests/test_xero_purchase_reasoning.py — Slice E: the Reg 26/27 pass runs on the Xero F5
purchase side.

D-2026-09-23-xero-purchase-lines (PROPOSED).

THE GAP. The reasoning layer's one shipped skill — Reg 26/27 disallowed input tax — has
been dark on the primary go-to-market source since the Xero path existed. Not broken:
DARK. Every Xero upload handed the pass a line source that yields nothing, so it
short-circuited to a clean `ok` with zero candidates and made no model call. A capability
reported as healthy while receiving no data is worse than one reported as unavailable,
because nothing on the paper distinguishes "examined and found nothing" from "never looked".

WHAT THIS FILE PROVES, AND WHAT IT DOES NOT. It proves the MECHANISM end to end on STUBS:
that descriptions survive the reader, that the adapter shapes them like the sales
precedent, that the pass receives them, that the artefact seals, and that boxes/gates/
coverage/the oracle do not move. It proves NOTHING about whether the model's judgements are
correct — no test here makes a model call, and a single observed run is not a measurement.
T2.11 remains the only gate that moves the accuracy story.

NO MODEL CALLS. Every test injects a stub `llm_call`. No test sets ANTHROPIC_API_KEY, and
none may: the key lives only in the developer's own shell for the one authorised
observation run, never in CI.

APPEND-ONLY BOUNDARY: NEW file. Terry's hand-amendment (930e064) widened REG2627_SPEC in
two EXISTING files; this file adds nothing to them.

Hermetic: no network, no anthropic import, no live SAP/Xero. SAP off, dummy creds only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

_XERO_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-demo-2026Q2"
_F5 = _XERO_DIR / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_F5_NAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

#: R7 baseline, measured on the branch base (954f906) BEFORE any Slice E line was written:
#: the canonical-JSON sha256 of POST /review/upload over the demo F5 with no documents.
#: E-T3's box-isolation tripwire — if the reasoning wiring reaches the response, this moves.
_UPLOAD_DIGEST_NO_DOCS = "3ae353f1fd4f04d1c1432358d5640dc92678aa43a98a674104baa37458967104"

#: The two controls named in the brief. BILL-3007 is a Reg 27 motor-car candidate;
#: BILL-3006 is entertainment, which is NOT on the Reg 26/27 disallowed list and must not
#: be flagged. Both are TX purchase lines, so BOTH reach the pass — the negative control is
#: TAKEN rather than silent-by-absence, which is the point of wiring this at all.
_MOTOR_CAR = "BILL-3007"
_ENTERTAINMENT = "BILL-3006"

_SEQ = itertools.count()


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stub_llm(candidates: list[dict]):
    """A stub llm_call. NEVER a live call — the whole suite runs without a key."""

    def _call(model, system, messages, max_tokens):
        return {
            "content": json.dumps(candidates),
            "input_tokens": 11,
            "output_tokens": 22,
        }

    return _call


def _raw_candidate(doc_num, *, category="motor_car_s_plate", phrasing=None, vat_group="TX"):
    """One well-formed candidate echo in the 13-field artefact shape."""
    return {
        "doc_num": doc_num,
        "doc_type": "purchase_invoice",
        "doc_date": "2026-06-03",
        "card_name": "AutoCare SG Pte Ltd",
        "line_index": 0,
        "vat_group": vat_group,
        "line_description": "Private passenger car (S-plate) servicing",
        "line_total": 1200.0,
        "tax_total": 108.0,
        "suspected_category": category,
        "reasoning": "S-plate servicing reads as a private passenger car expense.",
        "phrasing": phrasing if phrasing is not None else (
            "Consider reviewing whether the input tax on this line is disallowed."
        ),
        "confidence": "low",
    }


# ══ E-T1 — the adapter yields the demo purchase lines ════════════════════════════════


class TestET1Adapter:

    @pytest.fixture(scope="class")
    def lines(self):
        from feeders.xero_f5_purchase_lines import xero_f5_purchase_lines
        from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period

        reader = XeroF5ChainReader(_F5)
        period = parse_review_period(_F5)
        return xero_f5_purchase_lines(reader, period["start"], period["end"])

    def test_it_yields_the_measured_purchase_line_count(self, lines):
        """21 TX purchase lines, measured in Phase R over the committed fixture. Pinned as
        a COUNT plus membership, not as a hand-copied list of figures."""
        assert len(lines) == 21
        assert {ln["doc_num"] for ln in lines} >= {_MOTOR_CAR, _ENTERTAINMENT}

    def test_doc_num_is_type_preserving_never_int_coerced(self, lines):
        """The standing ruling. 'BILL-3007' must arrive VERBATIM as a str — an int() here
        is what open item #34 is about, and it raises rather than degrades."""
        by_doc = {ln["doc_num"]: ln for ln in lines}
        assert _MOTOR_CAR in by_doc
        assert isinstance(by_doc[_MOTOR_CAR]["doc_num"], str)
        assert by_doc[_MOTOR_CAR]["doc_num"] == "BILL-3007"

    def test_descriptions_arrive_verbatim(self, lines):
        by_doc = {ln["doc_num"]: ln for ln in lines}
        assert by_doc[_MOTOR_CAR]["line_description"] == "Private passenger car (S-plate) servicing"
        assert by_doc[_ENTERTAINMENT]["line_description"] == "Client dinner & entertainment - 12 pax"

    def test_the_shape_mirrors_the_sales_adapter_exactly(self, lines):
        """No second line shape is invented: the 9 keys are the sales adapter's 9 keys."""
        expected = {
            "doc_num", "doc_type", "doc_date", "card_name", "line_index",
            "vat_group", "line_description", "line_total", "tax_total",
        }
        for ln in lines:
            assert set(ln) == expected
        assert {ln["doc_type"] for ln in lines} == {"purchase_invoice"}

    def test_only_canonical_tx_purchase_lines_are_yielded(self, lines):
        assert {ln["vat_group"] for ln in lines} == {"TX"}


# ══ E-T10 — one line per ROW, not per document (Terry's addition) ════════════════════


class TestET10RowGranularity:
    """Phase R proved the export is one row per LINE using reference `#14` — but `#14`
    lives in the `Transactions not included` trailer, which the reader skips, and every
    Box 5 bill in the committed corpus happens to be single-line. So the per-line
    assumption is load-bearing and UNEXERCISED on the purchase path. This constructs the
    missing case: if a real multi-line bill ever appears and the reader or the adapter
    collapses it, the reasoning pass would silently see one line where there were several,
    dropping real purchase lines from the Reg 26/27 review with no signal at all."""

    def test_a_multi_row_reference_yields_one_line_per_row(self, tmp_path):
        from feeders.xero_f5_purchase_lines import xero_f5_purchase_lines
        from feeders.xero_f5_reader import XeroF5ChainReader

        book = _build_f5_with_multirow_bill(tmp_path)
        reader = XeroF5ChainReader(book)
        lines = xero_f5_purchase_lines(reader, "2026-04-01", "2026-06-30")

        same_ref = [ln for ln in lines if ln["doc_num"] == "BILL-9001"]
        assert len(same_ref) == 2, "a two-row bill must yield TWO lines, never one merged"
        assert {ln["line_description"] for ln in same_ref} == {
            "Staff medical insurance premium",
            "Office stationery",
        }
        assert sorted(ln["line_total"] for ln in same_ref) == [400.0, 1000.0]


def _build_f5_with_multirow_bill(tmp_path: Path) -> Path:
    """A minimal real-shaped F5 workbook whose Box 5 carries ONE reference on TWO rows."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions by box number"
    ws.append(["Transactions by box number"])
    ws.append(["AgentAssist"])
    ws.append(["For the period Apr 1, 2026 to Jun 30, 2026"])
    ws.append([])
    ws.append([
        "Date", "Account", "Reference", "Contact", "Description", "Tax rate",
        "Source gross", "Source net", "Source tax", "Source currency",
        "Gross", "Net", "Tax",
    ])
    ws.append(["Box 5 - Total value of taxable purchases (excluding GST)"])
    for desc, net, tax in (
        ("Staff medical insurance premium", 1000.0, 90.0),
        ("Office stationery", 400.0, 36.0),
    ):
        ws.append([
            "2026-05-02", "400 - Expenses", "BILL-9001", "Meridian Systems Inc", desc,
            "Standard-Rated Purchases (9%)", net + tax, net, tax, "SGD",
            net + tax, net, tax,
        ])
    out = tmp_path / "multirow.xlsx"
    wb.save(out)
    return out


# ══ E-T2 — the pass runs end to end on a stub and seals ═════════════════════════════


class TestET2PassRuns:

    def test_stub_candidates_reach_the_artefact_with_provenance(self):
        from reasoning.reg2627 import _PINNED_MODEL, run_reg2627_pass
        from feeders.xero_f5_purchase_lines import xero_f5_purchase_lines
        from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period

        reader = XeroF5ChainReader(_F5)
        period = parse_review_period(_F5)
        art = run_reg2627_pass(
            period,
            line_source=lambda: xero_f5_purchase_lines(reader, period["start"], period["end"]),
            llm_call=_stub_llm([_raw_candidate(_MOTOR_CAR)]),
        )
        assert art["status"] == "ok"
        # 21 lines against _BATCH_SIZE=20 is TWO batches, so the stub is called TWICE and
        # returns its candidate each time. Pinned rather than smoothed over, because the
        # batch count IS the call count and therefore the cost of a review (E5): a client
        # export with hundreds of Box-5 rows multiplies this linearly.
        assert art["candidate_count"] == 2
        assert {c["doc_num"] for c in art["candidates"]} == {"BILL-3007"}   # verbatim str
        assert all(isinstance(c["doc_num"], str) for c in art["candidates"])
        prov = art["provenance"]
        assert prov["in_run_path"] is True
        assert prov["model_id"] == _PINNED_MODEL
        assert prov["prompt_version"] == "t2.7-reg2627-v1"
        assert prov["kb_slice_hash"].startswith("sha256:")
        assert prov["validation_status"] == "unvalidated"

    def test_the_artefact_candidate_carries_all_thirteen_fields(self):
        from reasoning.reg2627 import run_reg2627_pass

        art = run_reg2627_pass(
            {"start": "2026-04-01", "end": "2026-06-30"},
            line_source=lambda: [_line_for(_MOTOR_CAR)],
            llm_call=_stub_llm([_raw_candidate(_MOTOR_CAR)]),
        )
        assert set(art["candidates"][0]) == {
            "doc_num", "doc_type", "doc_date", "card_name", "line_index", "vat_group",
            "line_description", "line_total", "tax_total", "suspected_category",
            "reasoning", "phrasing", "confidence",
        }


def _line_for(doc_num: str, vat_group: str = "TX") -> dict:
    return {
        "doc_num": doc_num, "doc_type": "purchase_invoice", "doc_date": "2026-06-03",
        "card_name": "AutoCare SG Pte Ltd", "line_index": 0, "vat_group": vat_group,
        "line_description": "Private passenger car (S-plate) servicing",
        "line_total": 1200.0, "tax_total": 108.0,
    }


# ══ B1 — BOTH codes select (Terry's ruling) ═════════════════════════════════════════


class TestB1BothCodesSelect:
    """The widening is a BRIDGE: "SI" is the raw pre-Annex-E SAP code, "TX" the canonical
    one. The SAP reasoning feeder still emits raw codes while the chain emits canonical
    ones — a tolerated asymmetry in the frozen fixtures. Once those fixtures are
    re-captured canonically the spec should reduce to TX alone (filed open item)."""

    @pytest.mark.parametrize("code", ["SI", "TX"])
    def test_each_code_reaches_the_pass(self, code):
        from reasoning.reg2627 import run_reg2627_pass

        art = run_reg2627_pass(
            {"start": "2026-04-01", "end": "2026-06-30"},
            line_source=lambda: [_line_for("BILL-1", vat_group=code)],
            llm_call=_stub_llm([_raw_candidate("BILL-1", vat_group=code)]),
        )
        assert art["status"] == "ok"
        assert art["candidate_count"] == 1, f"{code} lines must reach the pass"
        assert art["candidates"][0]["vat_group"] == code   # per-line code kept, not flattened

    def test_an_out_of_scope_code_still_does_not_reach_the_pass(self):
        """The widening must not become 'everything selects'."""
        from reasoning.reg2627 import run_reg2627_pass

        art = run_reg2627_pass(
            {"start": "2026-04-01", "end": "2026-06-30"},
            line_source=lambda: [_line_for("BILL-2", vat_group="ZR")],
            llm_call=_stub_llm([_raw_candidate("BILL-2")]),
        )
        assert art["status"] == "ok"
        assert art["candidate_count"] == 0


# ══ E-T5 / B3 — no model configured ═════════════════════════════════════════════════


class TestET5NoModel:

    def test_lines_but_no_model_is_not_examined_with_a_reason(self, monkeypatch):
        """NEVER a silent clean: once there ARE lines to examine, an `ok`/0 artefact would
        be a lie, and `errored` would blame a failure that did not happen."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from reasoning.reg2627 import run_reg2627_pass

        art = run_reg2627_pass(
            {"start": "2026-04-01", "end": "2026-06-30"},
            line_source=lambda: [_line_for(_MOTOR_CAR)],
        )
        assert art["status"] == "not_examined"
        assert "no model configured" in (art["error"] or "").lower()
        assert art["candidates"] == []

    def test_zero_lines_and_no_model_stays_ok(self, monkeypatch):
        """Terry's B3 rule: not_examined ONLY when lines exist AND no model is configured.
        With nothing to examine, today's clean ok/0 is honest and must not move — that is
        what keeps every SAP/extract/sales path byte-identical."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from reasoning.reg2627 import run_reg2627_pass

        art = run_reg2627_pass(
            {"start": "2026-04-01", "end": "2026-06-30"}, line_source=lambda: []
        )
        assert art["status"] == "ok"
        assert art["candidate_count"] == 0

    def test_a_stub_model_examines(self):
        """The other direction (Terry's B3 addition): with an llm_call PRESENT the pass
        RUNS and the run reads as examined."""
        from reasoning.reg2627 import run_reg2627_pass

        art = run_reg2627_pass(
            {"start": "2026-04-01", "end": "2026-06-30"},
            line_source=lambda: [_line_for(_MOTOR_CAR)],
            llm_call=_stub_llm([_raw_candidate(_MOTOR_CAR)]),
        )
        assert art["status"] == "ok"
        assert art["input_summary"]["si_purchase_lines_examined"] == 1


# ══ E-T6 (REWRITTEN per Terry) — the phrasing invariant REPAIRS, it does not reject ══


class TestET6PhrasingRepair:
    """The brief said a candidate not beginning "Consider reviewing whether" is REJECTED.
    It is not: reasoning_pass.py REPAIRS it by prefixing. This pins the CHARACTERISED
    behaviour rather than the assumed one. Whether silent repair is right — a model that
    omitted the framing may have misread the task, and repairing hides that — is a filed
    OPEN ITEM, deliberately not changed in this slice."""

    def test_a_candidate_missing_the_framing_is_repaired_not_dropped(self):
        from reasoning.reg2627 import run_reg2627_pass

        art = run_reg2627_pass(
            {"start": "2026-04-01", "end": "2026-06-30"},
            line_source=lambda: [_line_for(_MOTOR_CAR)],
            llm_call=_stub_llm([_raw_candidate(_MOTOR_CAR, phrasing="this is disallowed")]),
        )
        assert art["candidate_count"] == 1, "repaired, NOT dropped"
        assert art["candidates"][0]["phrasing"].startswith("Consider reviewing whether")
        assert "this is disallowed" in art["candidates"][0]["phrasing"]

    def test_a_well_formed_candidate_is_left_alone(self):
        from reasoning.reg2627 import run_reg2627_pass

        good = "Consider reviewing whether the input tax on this line is disallowed."
        art = run_reg2627_pass(
            {"start": "2026-04-01", "end": "2026-06-30"},
            line_source=lambda: [_line_for(_MOTOR_CAR)],
            llm_call=_stub_llm([_raw_candidate(_MOTOR_CAR, phrasing=good)]),
        )
        assert art["candidates"][0]["phrasing"] == good


# ══ E-T7 — open item #34, BOTH sites ════════════════════════════════════════════════


class TestET7Item34:
    """Slice E is what makes #34 reachable: it creates the second of its three conditions
    (a reg2627 artefact that is `ok` WITH candidates). Before this slice the Xero line
    source was empty, so the crash could not fire. Hence #34 closes in the same PR."""

    def _artefact(self, doc_num):
        return {
            "status": "ok",
            "candidates": [_raw_candidate(doc_num)],
            "disclaimer": "",
            "check": "reg-26-27-disallowed-input-tax",
        }

    def test_unified_candidates_section_survives_a_string_doc_num(self):
        """THE HARD SITE. int("BILL-3007") raised ValueError straight out of build_report."""
        from report.sections import build_unified_candidates_section

        sec = build_unified_candidates_section(self._artefact(_MOTOR_CAR), None, show=True)
        rows = [r for r in sec.candidates if r.basis == "description analysis"]
        assert rows and rows[0].doc_num == "BILL-3007"

    def test_ai_candidates_section_survives_a_string_doc_num(self):
        """THE TOLERANT SITE — pinned too, so a future edit cannot quietly un-fix it."""
        from report.sections import build_ai_candidates_section

        sec = build_ai_candidates_section(self._artefact(_MOTOR_CAR), show=True)
        assert sec.candidates[0].doc_num == "BILL-3007"

    def test_a_numeric_doc_num_is_still_an_int_on_both_sites(self):
        from report.sections import build_ai_candidates_section, build_unified_candidates_section

        uni = build_unified_candidates_section(self._artefact(3007), None, show=True)
        ai = build_ai_candidates_section(self._artefact(3007), show=True)
        assert [r for r in uni.candidates if r.basis == "description analysis"][0].doc_num == 3007
        assert ai.candidates[0].doc_num == 3007


# ══ E-T8 — the gate holds: nothing AI-derived escapes while the flag is False ═══════


class TestET8Gate:

    def test_show_ai_candidates_false_yields_no_rows(self):
        from report.sections import build_unified_candidates_section

        art = {"status": "ok", "candidates": [_raw_candidate(_MOTOR_CAR)], "disclaimer": ""}
        sec = build_unified_candidates_section(art, None, show=False)
        assert sec.show is False
        assert sec.candidates == []

    def test_the_flag_is_still_false_on_the_xero_demo_config(self):
        """Invariant 5. This slice makes the pass RUN; it does not make its output visible."""
        from config.loader import load_client_config

        cfg = load_client_config("xero_demo", check_connectivity=False)
        assert getattr(cfg, "show_ai_candidates", False) is False
        assert cfg.validation_status == "unvalidated" if hasattr(cfg, "validation_status") else True
