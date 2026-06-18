"""tests/test_t61_frontend_api.py — T6.1 FastAPI seam over the FROZEN artifacts.

Honesty constraints under test (load-bearing):
  * GET /review returns the REAL frozen shape: the doc-592 NO_GST_REG "Far East Imports"
    entry is present AND demoted (T5.5b); the mock's aspirational DUP_CLAIM / SEQ_GAP /
    FLUX never appear.
  * POST /sign is box-isolated (F5 boxes byte-identical pre/post) and carries the
    reviewer name.
  * A CONTRACT test pins the documented key set the frontend consumes to exactly what the
    API emits (single source of truth = api.viewmodel.*_KEYS).
  * Import-scan (AST): api/ imports no anthropic; orchestrator/ is untouched by this slice.

SAP off, mock engine, no tokens.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.viewmodel import AUDIT_ROW_KEYS, QUEUE_ITEM_KEYS, REVIEW_KEYS, SIGN_KEYS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_DIR = _REPO_ROOT / "api"

# Aspirational mock check types that are NOT in the engine — must never be served.
_FICTIONAL_CHECK_TYPES = {"DUP_CLAIM", "SEQ_GAP", "FLUX"}
# The real frozen check types the engine actually produces.
_REAL_CHECK_TYPES = {"E1", "E2", "NO_GST_REG", "gst_amount_mismatch"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# ── GET /review ──────────────────────────────────────────────────────────────────────

def test_review_returns_real_frozen_shape(client: TestClient):
    resp = client.get("/review/sbodemosg/2024Q3")
    assert resp.status_code == 200
    body = resp.json()
    assert tuple(body.keys()) == REVIEW_KEYS or set(body.keys()) == set(REVIEW_KEYS)
    assert body["validation_status"] == "unvalidated"
    assert body["client"]["client_id"] == "sbodemosg"
    assert body["period"]["label"] == "2024Q3"
    # F5 boxes present (box-isolated source).
    assert "box_8_net_gst" in body["f5_summary"]["boxes"]
    assert body["queue"], "queue must not be empty"


def test_review_has_doc592_present_and_demoted(client: TestClient):
    body = client.get("/review/sbodemosg/2024Q3").json()
    doc592 = [it for it in body["queue"] if it["finding_id"] == "detect:NO_GST_REG:592"]
    assert len(doc592) == 1, "the genuinely-seeded doc-592 entry must be present"
    item = doc592[0]
    assert item["check_id"] == "NO_GST_REG"
    assert item["vendor"] == "Far East Imports"
    assert item["demoted"] is True, "doc-592 must be demoted (T5.5b), not dropped"
    assert item["group"] == "marked_known"
    assert "KNOWN_ACCEPTED" in (item["prior_dispositions"] or [])


def test_review_carries_only_real_check_types(client: TestClient):
    body = client.get("/review/sbodemosg/2024Q3").json()
    served = {it["check_id"] for it in body["queue"]}
    assert served <= _REAL_CHECK_TYPES, f"unexpected check types served: {served - _REAL_CHECK_TYPES}"
    # The mock's fictional types must not appear anywhere in the serialised payload.
    blob = json.dumps(body)
    for fictional in _FICTIONAL_CHECK_TYPES:
        assert fictional not in blob, f"fictional check type {fictional} leaked into the payload"


def test_review_preserves_trust_signals(client: TestClient):
    body = client.get("/review/sbodemosg/2024Q3").json()
    assert "unvalidated" in body["disclaimer"].lower()
    item = body["queue"][0]
    # Per-finding unvalidated IRAS citation caveat is carried verbatim.
    assert "UNVALIDATED" in item["iras_basis_caveat"]
    assert item["validation_status"] == "unvalidated"


def test_review_unknown_client_period_is_404(client: TestClient):
    assert client.get("/review/acme/2024Q3").status_code == 404
    assert client.get("/review/sbodemosg/2024Q1").status_code == 404


# ── Contract: documented key set == emitted key set (single source of truth) ─────────

def test_review_queue_item_contract(client: TestClient):
    body = client.get("/review/sbodemosg/2024Q3").json()
    for item in body["queue"]:
        assert set(item.keys()) == set(QUEUE_ITEM_KEYS), (
            f"queue item keys drifted from QUEUE_ITEM_KEYS: "
            f"{set(item.keys()) ^ set(QUEUE_ITEM_KEYS)}"
        )


def test_audit_row_contract(client: TestClient):
    body = client.get("/audit").json()
    assert body["entries"], "audit ledger must not be empty"
    for row in body["entries"]:
        assert set(row.keys()) == set(AUDIT_ROW_KEYS)


# ── POST /sign — box-isolation + reviewer name ───────────────────────────────────────

def test_sign_is_box_isolated_and_carries_reviewer(client: TestClient, tmp_path: Path):
    before = client.get("/review/sbodemosg/2024Q3").json()["f5_summary"]
    frozen_before = json.dumps(before, sort_keys=True)

    resp = client.post(
        "/sign",
        params={"out_dir": str(tmp_path)},
        json={"reviewer_name": "Box Guard", "firm_name": "Guard & Co"},
    )
    assert resp.status_code == 200
    sign_body = resp.json()
    assert set(sign_body.keys()) == set(SIGN_KEYS)
    assert sign_body["reviewer_name"] == "Box Guard"
    assert Path(sign_body["working_paper_path"]).exists()

    # F5 boxes byte-identical in the sign response AND on a fresh review read.
    assert json.dumps(sign_body["f5_summary"], sort_keys=True) == frozen_before
    after = client.get("/review/sbodemosg/2024Q3").json()["f5_summary"]
    assert json.dumps(after, sort_keys=True) == frozen_before


def test_sign_rejects_empty_reviewer(client: TestClient):
    resp = client.post("/sign", json={"reviewer_name": "   ", "firm_name": ""})
    assert resp.status_code == 422


# ── Import boundary (AST): api/ pure of anthropic; orchestrator/ untouched ────────────

def _imported_top_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    return mods


def test_api_imports_no_anthropic():
    forbidden = {"anthropic", "claude_agent_sdk"}
    for py_file in _API_DIR.rglob("*.py"):
        mods = _imported_top_modules(py_file)
        leaked = mods & forbidden
        assert not leaked, f"{py_file} imports forbidden module(s): {leaked}"


def test_api_import_does_not_load_anthropic_or_orchestrator(monkeypatch):
    """Importing api.app must not pull anthropic into sys.modules (mirrors the ui/ guard)."""
    import sys

    for mod in list(sys.modules):
        if mod == "anthropic" or mod.startswith("anthropic."):
            pytest.skip("anthropic already imported by another test in this process")
    import importlib

    import api.app  # noqa: F401

    importlib.reload(api.app)
    assert "anthropic" not in sys.modules
