"""
tests/test_xero_purchase_reasoning_wiring.py — Slice E: E-T3, E-T4, E-T9.

D-2026-09-23-xero-purchase-lines (PROPOSED). The isolation half of the slice.

Slice E hands the Reg 26/27 pass real purchase lines for the first time. The whole value of
that depends on it changing NOTHING else: if wiring a reasoning pass could move an F5 box, a
gate, a coverage row or the replay oracle, the deterministic chain would no longer be the
thing the signed paper rests on. These tests are the proof, taken ON THE WIRE rather than by
reading the code.

  E-T3  the upload response digest, the F5 boxes, the gate results and every coverage row
        are byte-identical with the reasoning wiring in place;
  E-T4  the SAP reg2627 artefact is unchanged — same candidates, same provenance, same
        bundle key — because the SAP path passes no purchase_line_source and must therefore
        take the identical code path it always did;
  E-T9  the adapter cannot reach the box loop: the isolation is STRUCTURAL, and this pins
        the structure rather than trusting a docstring.

NO MODEL CALLS. Stubs only; no ANTHROPIC_API_KEY is set or read anywhere.

APPEND-ONLY BOUNDARY: NEW file.
Hermetic: no network, no anthropic, no live SAP/Xero. SAP off, dummy creds only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import itertools
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

import audit_bundle.seal as _seal  # noqa: E402
from api.app import app  # noqa: E402
from audit_bundle.canonical import canonical_json  # noqa: E402
from config.loader import load_client_config  # noqa: E402
from orchestrator.chain import run_chain  # noqa: E402

_XERO_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-demo-2026Q2"
_F5 = _XERO_DIR / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_F5_NAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_FROZEN = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
_ORACLE = _FROZEN / "_replay-oracle.compiled.json"

#: Measured on the branch base (954f906) in Phase R, BEFORE any Slice E line existed.
_DIGEST_NO_DOCS = "3ae353f1fd4f04d1c1432358d5640dc92678aa43a98a674104baa37458967104"
_DIGEST_WITH_DOCS = "b3b70d53e7981e27e2aaaecd192fc489e20710fb070d9d379574da6597ca49cb"

_SEQ = itertools.count()


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
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
    # Belt and braces: no key reaches any test, so no pass can make a live call.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def _bump() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_SEQ)}"


def _digest(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ══ E-T3 — box isolation, on the wire ═══════════════════════════════════════════════


class TestET3BoxIsolation:

    def test_upload_response_digest_is_unchanged(self, client, hermetic):
        """The strongest available statement: the ENTIRE response body, byte for byte,
        against a digest measured before Slice E existed. The reasoning artefact is not in
        the response — and this is what proves it stayed out."""
        _bump()
        r = client.post(
            "/review/upload",
            files={"file": (_F5_NAME, _F5.read_bytes())},
            data={"source": "xero"},
        )
        assert r.status_code == 200, r.text
        assert _digest(r.json()) == _DIGEST_NO_DOCS

    def test_upload_with_documents_is_unchanged_too(self, client, hermetic):
        """The document path is the one B2 protected by refusing to overload line_source.
        If purchase_line_source had displaced the document-context rows, this digest would
        move even though the boxes did not."""
        docs = sorted((_XERO_DIR / "source_documents").glob("*.pdf"))
        assert docs, "the committed document corpus is missing"
        rid = client.post("/review-session").json()["review_id"]
        _bump()
        files = [("file", (_F5_NAME, _F5.read_bytes()))]
        files += [("documents", (d.name, d.read_bytes())) for d in docs]
        r = client.post("/review/upload", files=files, data={"source": "xero", "review_id": rid})
        assert r.status_code == 200, r.text
        assert _digest(r.json()) == _DIGEST_WITH_DOCS

    def test_boxes_gates_and_coverage_do_not_move_with_the_pass_wired(self, hermetic):
        """Chain level: the reasoning pass runs BESIDE the chain, never inside it. run_chain
        takes no line source at all, so this compares the chain's own output across two
        constructions of the same reader."""
        from feeders.xero_f5_reader import XeroF5ChainReader, parse_review_period

        cfg = load_client_config("xero_demo", check_connectivity=False)
        period = parse_review_period(_F5)
        a_out, a_gates = run_chain(cfg, period, reader=XeroF5ChainReader(_F5))
        b_out, b_gates = run_chain(cfg, period, reader=XeroF5ChainReader(_F5))
        assert canonical_json(a_out["calculate"]["boxes"]) == canonical_json(b_out["calculate"]["boxes"])
        assert canonical_json(a_gates) == canonical_json(b_gates)
        assert canonical_json(a_out.get("check_coverage")) == canonical_json(b_out.get("check_coverage"))
        # And the description the reader now retains must not have reached the boxes.
        assert "line_description" not in canonical_json(a_out["calculate"]["boxes"]).decode()

    def test_the_replay_oracle_is_byte_identical(self, monkeypatch):
        """Invariant 4. A reasoning change must never require an oracle re-freeze."""
        shim = _load("slice_e_shim", "tests/replay_shim.py")
        contact = shim.install_replay_patches(monkeypatch, _FROZEN)
        period = shim.period_from_manifest(_FROZEN)
        out, gates = run_chain(
            load_client_config("sbodemosg", check_connectivity=False),
            period,
            reader=shim.build_frozen_reader(_FROZEN),
        )
        blob = canonical_json({"period": period, "compile_output": out, "gate_results": gates})
        assert blob == _ORACLE.read_bytes(), "the oracle moved — NO re-freeze is allowed"
        assert contact == {"login": 0, "request": 0}


# ══ E-T4 — the SAP reg2627 artefact is untouched ════════════════════════════════════


class TestET4SapArtefactUnchanged:

    def _artefact(self, *, purchase_source=None):
        """Run the pass exactly as the SAP CLI does: lines via `line_source`, no
        purchase_line_source. The stub keeps it hermetic."""
        from reasoning.reg2627 import run_reg2627_pass

        si_line = {
            "doc_num": 3007, "doc_type": "purchase_invoice", "doc_date": "2024-08-01",
            "card_name": "ACME", "line_index": 0, "vat_group": "SI",
            "line_description": "Company car servicing", "line_total": 1000.0,
            "tax_total": 70.0,
        }
        raw = dict(si_line)
        raw.update({
            "suspected_category": "motor_car_s_plate",
            "reasoning": "car",
            "phrasing": "Consider reviewing whether this is disallowed.",
            "confidence": "low",
        })

        def _stub(model, system, messages, max_tokens):
            return {"content": json.dumps([raw]), "input_tokens": 1, "output_tokens": 1}

        return run_reg2627_pass(
            {"start": "2024-07-01", "end": "2024-09-30"},
            line_source=lambda: [si_line],
            llm_call=_stub,
        )

    def test_the_sap_si_path_still_produces_its_candidate(self):
        art = self._artefact()
        assert art["status"] == "ok"
        assert art["candidate_count"] == 1
        c = art["candidates"][0]
        assert c["doc_num"] == 3007 and isinstance(c["doc_num"], int)   # int stays int
        assert c["vat_group"] == "SI"

    def test_provenance_and_bundle_key_are_unchanged(self):
        from reasoning.reg2627 import REG2627_SPEC, _PINNED_MODEL

        art = self._artefact()
        assert art["check"] == "reg-26-27-disallowed-input-tax"
        assert art["artefact_type"] == "judgment-candidates"
        assert REG2627_SPEC.skill_id == "reg2627"          # bundle key: steps/judgment-*.json
        prov = art["provenance"]
        assert prov["model_id"] == _PINNED_MODEL
        assert prov["prompt_version"] == "t2.7-reg2627-v1"
        assert prov["validation_status"] == "unvalidated"
        assert prov["in_run_path"] is True

    def test_the_default_dispatch_is_unchanged_when_no_purchase_source_is_given(self):
        """B2's byte-identity property, pinned at the seam: with purchase_line_source
        defaulted to None the reg2627 pass reads `line_source`, exactly as before."""
        from engine.review import ReviewInputs

        inputs = ReviewInputs(line_source=lambda: [])
        assert inputs.purchase_line_source is None
        # Read the source from disk rather than re-importing the module: importing
        # engine/review.py under a synthetic name re-executes its @dataclass decorators
        # against a module object that is not in sys.modules, which raises.
        src = (_REPO_ROOT / "engine" / "review.py").read_text(encoding="utf-8")
        assert "inputs.purchase_line_source or inputs.line_source" in src


# ══ E-T9 — the adapter cannot reach the box loop ════════════════════════════════════


class TestET9StructuralIsolation:
    """The sales precedent carries no runtime assertion — the isolation is STRUCTURAL, and
    a docstring is not a guard. So this pins the structure itself: the only thing that can
    make the claim false is run_chain growing a line-source parameter, or the box loop
    importing the adapter. Both are checked here."""

    def test_run_chain_takes_no_line_source_parameter(self):
        params = set(inspect.signature(run_chain).parameters)
        assert "line_source" not in params
        assert "purchase_line_source" not in params
        assert "sales_line_source" not in params

    def test_no_box_side_module_imports_the_adapter(self):
        offenders = []
        for rel in ("orchestrator", "mcp-servers/custom", "feeders"):
            for path in (_REPO_ROOT / rel).rglob("*.py"):
                if path.name == "xero_f5_purchase_lines.py":
                    continue
                if "xero_f5_purchase_lines" in path.read_text(encoding="utf-8", errors="replace"):
                    offenders.append(str(path.relative_to(_REPO_ROOT)))
        assert offenders == [], f"the box side must not reach the adapter: {offenders}"

    def test_the_adapter_is_a_pure_leaf(self):
        """feeders/ stays importable with nothing above it — no reasoning, no engine, no
        anthropic. If that ever changes, the isolation argument changes with it."""
        src = (_REPO_ROOT / "feeders" / "xero_f5_purchase_lines.py").read_text(encoding="utf-8")
        for banned in ("import anthropic", "from anthropic", "import reasoning", "from reasoning",
                       "import engine", "from engine", "import orchestrator", "from orchestrator"):
            assert banned not in src, f"adapter must not {banned!r}"
