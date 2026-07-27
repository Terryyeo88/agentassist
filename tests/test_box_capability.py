"""tests/test_box_capability.py -- D-2026-07-26-box-capability FAILING-FIRST.

BUILD ID: t-box-capability. Written BEFORE the implementation; these MUST fail today
for the RIGHT reason (missing seam / missing projection / 0.0 fabrication), then pass.

THE INVARIANT (three-times rule: prompt + code + THIS file): a signed working paper
never states a figure for an F5 box the SOURCE could not have populated. Readers
declare which SIDES ("sales"/"purchase") their FORMAT can carry via a duck-typed
``populatable_sides()`` seam beside ``coverage_status()``; ``orchestrator.chain``
projects sides -> per-box status using the EXISTING ``side`` field in
``sap_b1_server.F5_BOX_MAPPING`` (no new side->box table) and emits
``compile_output["box_capability"]``; ``report/`` renders an unavailable box as a
MARKER (no figure) and a derived box with an unavailable input as its figure PLUS a
sub-line naming the unavailable term, claiming no bound or direction (R4).

CAPABILITY, NOT EMPTINESS, drives the marker (R-4 of the recon): a legitimately
one-sided F5 export (a format that CAN carry purchases but had none in the period)
renders Box 5/7 as genuine 0.00 FIGURES, never as unavailable -- pinned here by a
constructed no-purchase F5 workbook (T10).

BOX-ISOLATION AT RUNTIME (A6): calculate.boxes and gate results are canonical_json
byte-identical with and without the capability seam (T7). The seal GLOSSES, never
diverges: sealed boxes keep their computed zeros; only the paper's presentation
changes (the ADDITIVE shape from D-2026-07-24-decision-render, not the DEAD filter).

R7: an ABSENT box key must never render as a fabricated 0.00 (sections.py boxes.get
default) -- pinned in T8.

HERMETIC: committed fixtures + tmp_path workbooks; no network, no anthropic, no live
SAP (dummy env creds only, never dialled). DOES NOT edit any existing test file.
"""
from __future__ import annotations

import copy
import itertools
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

from audit_bundle.canonical import canonical_json  # noqa: E402
from config.loader import load_client_config  # noqa: E402
from feeders.extract_reader import ExtractChainReader  # noqa: E402
from feeders.xero_f5_reader import XeroF5ChainReader  # noqa: E402
from feeders.xero_sales_reader import XeroSalesInvoiceChainReader  # noqa: E402
from orchestrator.chain import (  # noqa: E402
    run_chain,
    _emit_box_capability,
    project_box_capability,
)
import sap_b1_server  # noqa: E402

_SALES_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
    / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
)
_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_EXTRACT_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "extract-export-sbodemosg"
_CHAIN_SAMPLE = _REPO_ROOT / "tests" / "fixtures" / "chain-run-sample.json"

_ALL_BOXES = (
    "box_1_standard_rated_sales",
    "box_2_zero_rated_sales",
    "box_3_exempt_sales",
    "box_4_total_sales",
    "box_5_taxable_purchases",
    "box_6_output_tax",
    "box_7_input_tax",
    "box_8_net_gst",
)

_UPLOAD_SEQ = itertools.count()


@pytest.fixture()
def dummy_creds(monkeypatch):
    """Dummy SAP env creds (file-import configs never dial; mirrors the sign fixtures)."""
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")


def _sales_reader() -> XeroSalesInvoiceChainReader:
    cfg = load_client_config("xero_sales_demo", check_connectivity=False)
    return XeroSalesInvoiceChainReader(
        _SALES_FIXTURE,
        tax_code_mappings=cfg.effective_tax_code_mappings,
        out_of_scope_codes=cfg.out_of_scope_codes,
    )


def _statuses(cap: dict) -> dict:
    return {b: cap["boxes"][b]["status"] for b in cap["boxes"]}


# -- T1/T2/T3 -- projection: sides -> per-box status via F5_BOX_MAPPING's side field --


def test_t1_projection_sales_only():
    """A sales-only source: purchase boxes unavailable; Box 8 derived_incomplete naming box_7.

    FAILS TODAY: project_box_capability does not exist.
    """
    cap = project_box_capability({"sales"})
    assert cap["declared_sides"] == ["sales"]
    assert tuple(cap["boxes"].keys()) == _ALL_BOXES, "all 8 boxes, F5 form order"

    st = _statuses(cap)
    assert st["box_1_standard_rated_sales"] == "available"
    assert st["box_2_zero_rated_sales"] == "available"
    assert st["box_3_exempt_sales"] == "available"
    # Box 4 = 1+2+3: every input is sales-side -> available (NOT contaminated).
    assert st["box_4_total_sales"] == "available"
    assert st["box_5_taxable_purchases"] == "unavailable"
    assert st["box_6_output_tax"] == "available"
    assert st["box_7_input_tax"] == "unavailable"
    # Box 8 = 6 - 7: box_6 real, box_7 unavailable -> derived from an incomplete input.
    assert st["box_8_net_gst"] == "derived_incomplete"
    assert cap["boxes"]["box_8_net_gst"]["unavailable_inputs"] == ["box_7_input_tax"]
    # Non-derived rows carry an EMPTY inputs list (uniform shape, canonical-JSON friendly).
    assert cap["boxes"]["box_5_taxable_purchases"]["unavailable_inputs"] == []


def test_t2_projection_purchase_only():
    """A purchase-only source: sales boxes unavailable; Box 4 all-inputs-unavailable ->
    unavailable (NOT derived_incomplete); Box 8 derived_incomplete naming box_6."""
    cap = project_box_capability({"purchase"})
    st = _statuses(cap)
    assert st["box_1_standard_rated_sales"] == "unavailable"
    assert st["box_2_zero_rated_sales"] == "unavailable"
    assert st["box_3_exempt_sales"] == "unavailable"
    assert st["box_4_total_sales"] == "unavailable", (
        "a derived box whose EVERY input is unavailable is itself unavailable"
    )
    assert st["box_5_taxable_purchases"] == "available"
    assert st["box_6_output_tax"] == "unavailable"
    assert st["box_7_input_tax"] == "available"
    assert st["box_8_net_gst"] == "derived_incomplete"
    assert cap["boxes"]["box_8_net_gst"]["unavailable_inputs"] == ["box_6_output_tax"]


def test_t3_projection_both_sides_all_available():
    cap = project_box_capability({"sales", "purchase"})
    assert cap["declared_sides"] == ["purchase", "sales"]
    assert set(_statuses(cap).values()) == {"available"}


def test_t3b_projection_reads_mapping_side_field():
    """The projection derives box->sides from F5_BOX_MAPPING's OWN side field (R6 --
    no authored side->box table): every direct box's side set here must match a fresh
    recomputation over the mapping."""
    recomputed: dict = {}
    for spec in sap_b1_server.F5_BOX_MAPPING.values():
        for key in ("lt_box", "tt_box"):
            box = spec.get(key)
            if box:
                recomputed.setdefault(box, set()).add(spec["side"])
    sales_cap = _statuses(project_box_capability({"sales"}))
    for box, sides in recomputed.items():
        expected = "available" if "sales" in sides else "unavailable"
        assert sales_cap[box] == expected, f"{box}: mapping says sides={sides}"


# -- T4 -- reader declarations: capability is a property of the FORMAT ----------------


def test_t4_reader_side_declarations(dummy_creds):
    """FAILS TODAY: no reader carries populatable_sides."""
    assert _sales_reader().populatable_sides() == frozenset({"sales"})
    assert XeroF5ChainReader(_F5_FIXTURE).populatable_sides() == frozenset(
        {"sales", "purchase"}
    )
    assert ExtractChainReader(_EXTRACT_FIXTURE_DIR).populatable_sides() == frozenset(
        {"sales", "purchase"}
    )


def test_t4b_live_sap_reader_has_no_seam():
    """The live-SAP reader declares nothing -> the chain emits nothing -> the SAP path
    (and the frozen-replay oracle, which uses no seam-carrying reader) stays byte-identical."""
    assert not hasattr(sap_b1_server.SapChainReader, "populatable_sides")


# -- T5 -- emission unit: duck-typed, non-fatal, never fabricated ---------------------


class _StubReader:
    def __init__(self, sides=None, raises=False):
        self._sides = sides
        self._raises = raises
        if sides is None and not raises:
            return
        self.populatable_sides = self._probe  # instance attr = the seam

    def _probe(self):
        if self._raises:
            raise RuntimeError("boom")
        return self._sides


def test_t5_emission_ducktyped_and_nonfatal():
    out: dict = {}
    _emit_box_capability(out, _StubReader(sides={"sales"}))
    assert out["box_capability"]["declared_sides"] == ["sales"]

    no_seam: dict = {}
    _emit_box_capability(no_seam, _StubReader())
    assert "box_capability" not in no_seam, "no seam -> no key (never fabricated)"

    raising: dict = {}
    _emit_box_capability(raising, _StubReader(raises=True))
    assert "box_capability" not in raising, "a failing probe is non-fatal and emits nothing"

    junk: dict = {}
    _emit_box_capability(junk, _StubReader(sides={"weird_side"}))
    assert "box_capability" not in junk, "undeclarable sides -> no emission, never a guess"

    empty: dict = {}
    _emit_box_capability(empty, _StubReader(sides=set()))
    assert "box_capability" not in empty, "an empty declaration is meaningless -> no emission"


# -- T6 -- chain end-to-end over the committed sales fixture --------------------------


def test_t6_chain_emits_capability_on_sales_reader(dummy_creds):
    """run_chain over the sales reader carries box_capability in compile_output.

    FAILS TODAY: the chain emits no such key.
    """
    cfg = load_client_config("xero_sales_demo", check_connectivity=False)
    period = {"start": "2026-04-05", "end": "2026-05-01"}
    compile_output, _gates = run_chain(cfg, period, reader=_sales_reader())

    cap = compile_output["box_capability"]
    assert cap["declared_sides"] == ["sales"]
    st = _statuses(cap)
    assert st["box_5_taxable_purchases"] == "unavailable"
    assert st["box_7_input_tax"] == "unavailable"
    assert st["box_8_net_gst"] == "derived_incomplete"
    assert cap["boxes"]["box_8_net_gst"]["unavailable_inputs"] == ["box_7_input_tax"]


# -- T7 (A6) -- BOX-ISOLATION at runtime: boxes + gates byte-identical ----------------


class _SeamStripped:
    """Delegates every reader surface EXCEPT populatable_sides (absent by construction)."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name == "populatable_sides":
            raise AttributeError(name)
        return getattr(self._inner, name)


def test_t7_box_isolation_with_and_without_signal(dummy_creds):
    """calculate.boxes and gate results are canonical_json byte-identical with and
    without the capability seam; the key itself is the ONLY compile-output delta class."""
    cfg = load_client_config("xero_sales_demo", check_connectivity=False)
    period = {"start": "2026-04-05", "end": "2026-05-01"}

    with_seam, gates_with = run_chain(cfg, period, reader=_sales_reader())
    without_seam, gates_without = run_chain(
        cfg, period, reader=_SeamStripped(_sales_reader())
    )

    assert "box_capability" in with_seam
    assert "box_capability" not in without_seam
    assert canonical_json(with_seam["calculate"]["boxes"]) == canonical_json(
        without_seam["calculate"]["boxes"]
    ), "BOX-ISOLATION: the capability signal must not move a single box byte"
    assert canonical_json(gates_with) == canonical_json(gates_without), (
        "gate results byte-identical with and without the signal"
    )


# -- T8 (R7) -- an ABSENT box key must not render as a fabricated 0.00 ----------------


def test_t8_absent_box_key_is_not_fabricated_as_zero():
    """build_f5_box_section: a boxes dict MISSING a key yields box_value None (not 0.0),
    and the renderer shows an em-dash, never '0.00'.

    FAILS TODAY: sections.py's boxes.get(box_name, 0.0) fabricates 0.0.
    """
    from report.contract import load_compile_output
    from report.sections import build_f5_box_section
    import report.render as R

    doctored = copy.deepcopy(load_compile_output(_CHAIN_SAMPLE))
    del doctored["calculate"]["boxes"]["box_5_taxable_purchases"]

    section = build_f5_box_section(doctored)
    row = next(
        a for a in section.attribution if a.box_name == "box_5_taxable_purchases"
    )
    assert row.box_value is None, "absent key -> None, never a fabricated 0.0"

    texts: list = []
    for flowable in R._box_value_flowables(row):
        texts.append(flowable.getPlainText())
    joined = " ".join(texts)
    assert "0.00" not in joined
    assert joined.strip() == "—", "absent value renders as an em-dash, no figure"


# -- T9 -- section threading: statuses flow from compile_output into the section ------


def test_t9_section_threads_capability_statuses():
    """build_f5_box_section reads box_capability; absent key -> all rows 'available'
    (the byte-identical SAP/legacy default).

    FAILS TODAY: F5BoxAttribution has no status field.
    """
    from report.contract import load_compile_output
    from report.sections import build_f5_box_section

    plain = load_compile_output(_CHAIN_SAMPLE)
    for row in build_f5_box_section(plain).attribution:
        assert row.status == "available"
        assert list(row.unavailable_inputs) == []

    with_cap = copy.deepcopy(plain)
    with_cap["box_capability"] = project_box_capability({"sales"})
    rows = {a.box_name: a for a in build_f5_box_section(with_cap).attribution}
    assert rows["box_5_taxable_purchases"].status == "unavailable"
    assert rows["box_7_input_tax"].status == "unavailable"
    assert rows["box_8_net_gst"].status == "derived_incomplete"
    assert list(rows["box_8_net_gst"].unavailable_inputs) == ["box_7_input_tax"]
    assert rows["box_1_standard_rated_sales"].status == "available"
    assert len(build_f5_box_section(with_cap).attribution) == 8, (
        "the marker approach keeps ALL 8 rows -- suppression is the DEAD shape"
    )


# -- T10 (A4) -- capability, NOT emptiness, drives the marker -------------------------


def _one_sided_f5_workbook(tmp_path: Path) -> Path:
    """A LEGITIMATELY one-sided Xero F5 workbook: the format carries the purchase
    value-box section, but the period had no purchase transactions. Mirrors the real
    export's structure (title block, row-5 header, labelled box sections)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions by box number"
    ws.append(["AgentAssist One-Sided Demo Pte Ltd"])
    ws.append(["Transactions by box number"])
    ws.append(["For the period Apr 1, 2026 to Jun 30, 2026"])
    ws.append([])
    ws.append([
        "Date", "Reference", "Contact", "Description", "Tax rate",
        "Source currency", "Gross", "Net", "Tax", "Account",
    ])
    ws.append(["Box 1 - Total value of standard-rated supplies"])
    ws.append([
        "2026-04-08", "INV-7001", "Alpha Pte Ltd", "Consulting",
        "Standard-Rated Supplies (9%)", "SGD", 10900.0, 10000.0, 900.0, "200",
    ])
    ws.append(["Total", "", "", "", "", "", 10900.0, 10000.0, 900.0, ""])
    ws.append([])
    # The purchase value box IS part of the format -- present, with no rows in period.
    ws.append(["Box 5 - Total value of taxable purchases and imports"])
    ws.append([])
    ws.append(["Box 6 - Output tax due"])  # restatement box (re-lists; reader skips)
    out = tmp_path / "one_sided_f5.xlsx"
    wb.save(out)
    return out


def test_t10_one_sided_f5_renders_zero_figures_not_markers(tmp_path, monkeypatch):
    """An F5 export with NO purchases in the period: Box 5/7 render as 0.00 FIGURES
    (category b -- knowable and genuinely zero), never as unavailable. This is the
    proof that CAPABILITY, not emptiness, drives the marker.

    FAILS TODAY for the paper half trivially (no marker exists anywhere yet), so the
    LOAD-BEARING red is the capability half: compile_output carries box_capability
    with ALL 8 boxes available.
    """
    import dataclasses

    import engine.review as _er
    import audit_bundle.seal as _seal
    from engine.review import ReviewInputs, review
    from feeders.xero_f5_reader import parse_review_period

    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(
        "audit_bundle.seal._AUDIT_ROOT", tmp_path / f"audit-{next(_UPLOAD_SEQ)}"
    )
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    assert _er is not None and _seal is not None  # imported for the monkeypatch targets

    wb_path = _one_sided_f5_workbook(tmp_path)
    reader = XeroF5ChainReader(wb_path)
    assert reader.populatable_sides() == frozenset({"sales", "purchase"})
    assert reader.count("PurchaseInvoices", "2026-04-01", "2026-06-30") == 0

    cfg = dataclasses.replace(
        load_client_config("xero_demo", check_connectivity=False),
        reviewer_name="Recon Runner",
        firm_name="",
    )
    period = parse_review_period(wb_path)
    result = review(
        cfg, period,
        ReviewInputs(line_source=lambda: [], provider=None, reader=XeroF5ChainReader(wb_path)),
    )
    assert result.status == "completed"

    cap = result.compile_output["box_capability"]
    assert set(s["status"] for s in cap["boxes"].values()) == {"available"}, (
        "an F5 export CAN carry both sides -- emptiness must not flip capability"
    )
    boxes = result.compile_output["calculate"]["boxes"]
    assert boxes["box_5_taxable_purchases"] == 0.0
    assert boxes["box_7_input_tax"] == 0.0

    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(result.report_pdf_path) as pdf:
        text = " ".join(
            " ".join((page.extract_text() or "").split()) for page in pdf.pages
        )
    assert "Not available from this source" not in text, (
        "a genuinely-zero box on a capable source renders its 0.00 FIGURE, no marker"
    )
    assert "Taxable purchases 0.00" in text
    assert "Input tax and refunds claimed 0.00" in text


# -- T11 -- the seal is GLOSSED, never diverged ---------------------------------------


def test_t11_sealed_boxes_keep_computed_zeros_under_markers(dummy_creds, tmp_path, monkeypatch):
    """On the sales path the PAPER marks Box 5/7 unavailable while the SEALED
    compile-output keeps the raw computed zeros -- every sealed figure stays accounted
    for (the ADDITIVE gloss shape, never the DEAD filter)."""
    import dataclasses

    import audit_bundle.seal as _seal
    from engine.review import ReviewInputs, review
    from feeders.xero_sales_lines import xero_sales_lines

    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(
        "audit_bundle.seal._AUDIT_ROOT", tmp_path / f"audit-{next(_UPLOAD_SEQ)}"
    )
    assert _seal is not None

    reader = _sales_reader()
    cfg = dataclasses.replace(
        load_client_config("xero_sales_demo", check_connectivity=False),
        reviewer_name="Recon Runner",
        firm_name="",
    )
    period = {"start": "2026-04-05", "end": "2026-05-01"}
    inner = _sales_reader()
    result = review(
        cfg, period,
        ReviewInputs(
            line_source=lambda: [], provider=None, reader=reader,
            sales_line_source=lambda: xero_sales_lines(inner, period["start"], period["end"]),
        ),
    )
    assert result.status == "completed"

    sealed = json.loads(
        (Path(result.bundle_dir) / "compile-output.json").read_text(encoding="utf-8")
    )
    assert sealed["calculate"]["boxes"]["box_5_taxable_purchases"] == 0.0
    assert sealed["calculate"]["boxes"]["box_7_input_tax"] == 0.0
    assert sealed["box_capability"]["declared_sides"] == ["sales"], (
        "the capability that JUSTIFIES the paper's marker is itself sealed"
    )


# -- T12 (F3) -- STRUCTURAL: every feeders/ ChainReader declares its sides ------------

# Readers that DELIBERATELY do not declare populatable_sides (Terry ruling F3 --
# an explicit named allowlist, never a silent default):
#   * sap_b1_server.SapChainReader -- the live SAP feeder. SAP B1 carries both
#     document sides by construction, so the "available" render default is correct,
#     and emitting nothing keeps the live-SAP chain output byte-identical.
#   * tests/replay_shim.FrozenExtractReader -- the offline-replay reader. It must
#     add NO compile-output key, or the frozen replay oracle's byte-identical
#     comparison (Invariant 4) breaks; the frozen SBODEMOSG capture is two-sided,
#     so the "available" default is correct there too.
# WHY THIS PIN EXISTS (F3 reasoning): the "available" default is correct today ONLY
# because both non-declaring readers are two-sided. A future ONE-SIDED reader that
# forgets to declare would resurrect the #48 fabrication through this exact gap --
# vigilance is not a control; this pin is.
_SIDES_EXEMPT_READERS = frozenset({"SapChainReader", "FrozenExtractReader"})


def _feeders_chain_reader_classes() -> list:
    """Every class defined under feeders/ that satisfies the ChainReader surface
    (duck-typed on the same probes the chain uses: fetch_invoices + fetch_listing)."""
    import importlib
    import inspect
    import pkgutil

    import feeders

    classes = []
    for mod_info in pkgutil.iter_modules(feeders.__path__):
        module = importlib.import_module(f"feeders.{mod_info.name}")
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if not cls.__module__.startswith("feeders."):
                continue  # re-exported import, not a feeders-defined class
            if callable(getattr(cls, "fetch_invoices", None)) and callable(
                getattr(cls, "fetch_listing", None)
            ):
                classes.append(cls)
    return classes


def test_t12_every_feeders_reader_declares_sides():
    """F3: every ChainReader in feeders/ declares populatable_sides; the deliberate
    non-declarers are the EXPLICIT allowlist above, nowhere else."""
    readers = _feeders_chain_reader_classes()
    assert readers, "the scan must find the feeders readers (sweep broke, not the repo)"
    seen = {cls.__name__ for cls in readers}
    assert {"ExtractChainReader", "XeroF5ChainReader", "XeroSalesInvoiceChainReader"} <= seen

    for cls in readers:
        assert cls.__name__ not in _SIDES_EXEMPT_READERS, (
            f"{cls.__name__} is feeders-defined -- the allowlist is for the live-SAP "
            "and replay readers only; a feeders reader must declare"
        )
        assert callable(getattr(cls, "populatable_sides", None)), (
            f"{cls.__name__} declares no populatable_sides: if it is one-sided, the "
            "'available' render default FABRICATES figures on its signed papers (#48). "
            "Declare its sides, or add it to _SIDES_EXEMPT_READERS with a stated reason."
        )


def test_t12b_exempt_readers_exist_and_lack_the_seam():
    """The allowlist stays honest: both named exemptions exist and genuinely lack
    the seam (a stale allowlist entry would mask a missing declaration)."""
    import importlib.util

    assert not hasattr(sap_b1_server.SapChainReader, "populatable_sides")

    shim_spec = importlib.util.spec_from_file_location(
        "boxcap_replay_shim", Path(__file__).resolve().parent / "replay_shim.py"
    )
    shim = importlib.util.module_from_spec(shim_spec)
    shim_spec.loader.exec_module(shim)
    assert not hasattr(shim.FrozenExtractReader, "populatable_sides"), (
        "the replay reader must emit nothing -- the frozen oracle comparison is "
        "byte-identical only while replay adds no compile-output key"
    )


# -- T13 (F4) -- DERIVED-IDENTITY BINDING: _DERIVED_BOX_INPUTS matches reality --------


def test_t13_derived_inputs_table_bound_to_observed_arithmetic(dummy_creds):
    """F4: _DERIVED_BOX_INPUTS is a THIRD statement of identities held in calculate
    (sap_b1_server box_4/box_8 derivation) and Gate 2 (gates.py). An unbound
    restatement can drift -- and the failure mode is a paper naming the WRONG
    unavailable input, inside the feature built to prevent exactly that. This test
    binds the table to the OBSERVED arithmetic of a real chain run whose derived
    boxes have non-zero, distinct terms (the committed F5 fixture: box_8 =
    900.00 - 1,265.00 = -365.00; box_4 = 15,000 + 3,000 + 0 = 18,000).
    """
    from orchestrator.chain import _DERIVED_BOX_INPUTS

    # The table claims EXACTLY these relationships -- membership and order.
    assert _DERIVED_BOX_INPUTS == {
        "box_4_total_sales": (
            "box_1_standard_rated_sales",
            "box_2_zero_rated_sales",
            "box_3_exempt_sales",
        ),
        "box_8_net_gst": ("box_6_output_tax", "box_7_input_tax"),
    }

    cfg = load_client_config("xero_demo", check_connectivity=False)
    period = {"start": "2026-04-01", "end": "2026-06-30"}
    compile_output, _gates = run_chain(
        cfg, period, reader=XeroF5ChainReader(_F5_FIXTURE)
    )
    b = compile_output["calculate"]["boxes"]

    # Non-trivial terms: a 0-heavy run would let a drifted table pass by accident.
    assert b["box_6_output_tax"] != 0.0 and b["box_7_input_tax"] != 0.0
    assert b["box_6_output_tax"] != b["box_7_input_tax"]

    box_4_inputs = _DERIVED_BOX_INPUTS["box_4_total_sales"]
    assert round(sum(b[k] for k in box_4_inputs), 2) == b["box_4_total_sales"], (
        "box_4 must equal the SUM of exactly the inputs the table claims"
    )
    minuend, subtrahend = _DERIVED_BOX_INPUTS["box_8_net_gst"]
    assert round(b[minuend] - b[subtrahend], 2) == b["box_8_net_gst"], (
        "box_8 must equal box_6 - box_7 in the table's own input order"
    )
