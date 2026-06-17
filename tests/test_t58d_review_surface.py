"""
tests/test_t58d_review_surface.py — T5.8d task-oriented review-surface acceptance.

The review surface is a PRESENTATION-LAYER rebuild over the UNCHANGED artifacts.py
view-models + UNCHANGED sign.py. These tests pin the two new PURE accessors and the
review.py queue assembly, plus the hermetic guards the new view must not break.

Covered (failing-first):
  (a) flatten_finding_card surfaces vendor/severity/description/recommendation as flat
      fields — for a deterministic E1, a NO_GST_REG (primary slot, NOT the supplier_catalog
      decoy), and a probabilistic finding (message→description fallback; absent
      card_name/recommendation tolerated);
  (b) check_reference joins check_id -> {display_name, iras_basis} from the registry, with
      a safe fallback for an unknown check_id;
  (c) review.py queue assembly groups items needs-review / marked-known / decided and the
      T5.5b-demoted item is PRESENT-but-demoted (cardinality preserved);
  (d) the accessors are PURE — importing ui.artifacts pulls no Streamlit/engine/anthropic
      (clean-subprocess headless import test);
  (e) box-isolation — signing renders from the frozen compile_output, never recomputing
      F5 boxes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ui.artifacts import (
    annotated_adjudication_items,
    check_reference,
    flatten_finding_card,
    load_demo_artifacts,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _item_by_finding_id(items: list[dict], finding_id: str) -> dict:
    for it in items:
        if it.get("finding_id") == finding_id:
            return it
    raise AssertionError(f"finding_id not found: {finding_id}")


# ── (a) flatten_finding_card ─────────────────────────────────────────────────────────

def test_flatten_deterministic_e1():
    items = annotated_adjudication_items(load_demo_artifacts())
    flat = flatten_finding_card(_item_by_finding_id(items, "detect:E1:958"))
    assert flat["vendor"] == "SG Electronics"
    assert flat["severity"] == "HIGH"
    assert "ZR" in flat["description"]
    assert flat["recommendation"].startswith("Reclassify")
    assert flat["doc_num"] == 958
    assert flat["error_code"] == "E1"


def test_flatten_no_gst_reg_picks_primary_slot_not_supplier_catalog_decoy():
    # NO_GST_REG evidence carries BOTH a primary purchase_invoices payload (description +
    # error_code) and a supplier_catalog decoy (card_name but NO description/error_code).
    # The predicate must prefer the payload bearing description/error_code.
    items = annotated_adjudication_items(load_demo_artifacts())
    flat = flatten_finding_card(_item_by_finding_id(items, "detect:NO_GST_REG:605"))
    assert flat["vendor"] == "Acme Associates"
    assert flat["severity"] == "HIGH"
    assert flat["error_code"] == "NO_GST_REG"
    # The decoy slot has gst_registered=false but no description — must NOT be chosen.
    assert "GST registration number" in flat["description"]
    assert flat["recommendation"].startswith("Obtain a valid tax invoice")


def test_flatten_probabilistic_message_fallback_and_absent_fields():
    items = annotated_adjudication_items(load_demo_artifacts())
    flat = flatten_finding_card(_item_by_finding_id(items, "doc:gst_amount_mismatch:958"))
    # sap_listing carries `message` not `description`; flattener falls back to message.
    assert flat["description"].startswith("Invoice PDF GST")
    assert flat["severity"] == "MEDIUM"
    assert flat["doc_num"] == 958
    # No card_name / recommendation on a probabilistic sap_listing payload — tolerated.
    assert flat["vendor"] is None
    assert flat["recommendation"] is None


# ── (b) check_reference ──────────────────────────────────────────────────────────────

def test_check_reference_known():
    ref = check_reference("E1")
    assert ref["check_id"] == "E1"
    assert ref["display_name"] == "Standard-rated sales on likely export/overseas supply"
    assert ref["iras_basis"].startswith("IRAS GST Act s21(3)")


def test_check_reference_no_gst_reg_known():
    ref = check_reference("NO_GST_REG")
    assert "input tax" in ref["display_name"].lower()
    assert "s19(1)" in ref["iras_basis"]


def test_check_reference_unknown_fallback():
    ref = check_reference("NOT_A_REAL_CHECK")
    assert ref["check_id"] == "NOT_A_REAL_CHECK"
    assert ref["display_name"] == "NOT_A_REAL_CHECK"  # safe fallback to the id
    assert ref["iras_basis"] == "—"


# ── (c) review.py queue assembly ─────────────────────────────────────────────────────

def test_review_queue_groups_and_preserves_demoted_item():
    from ui.views.review import build_queue

    artifacts = load_demo_artifacts()
    items = annotated_adjudication_items(artifacts)
    total = len(items)

    # No session decisions: everything is needs-review or marked-known (none decided).
    queue = build_queue(items, decisions={})
    assert set(queue) == {"needs_review", "marked_known", "decided"}

    # Cardinality preserved across the three buckets (never suppress).
    assert sum(len(queue[k]) for k in queue) == total

    # The seeded prior-period KNOWN_ACCEPTED (doc 592, Far East Imports) is demoted →
    # it lands in marked_known, PRESENT not dropped.
    marked_ids = {it["finding_id"] for it in queue["marked_known"]}
    assert "detect:NO_GST_REG:592" in marked_ids
    assert queue["needs_review"], "expected non-demoted findings to need review"

    # A recorded session decision moves an item into `decided` (still total-preserving).
    target = queue["needs_review"][0]["finding_id"]
    queue2 = build_queue(items, decisions={target: {"action": "Accept", "note": ""}})
    assert target in {it["finding_id"] for it in queue2["decided"]}
    assert sum(len(queue2[k]) for k in queue2) == total


# ── (d) headless import purity ───────────────────────────────────────────────────────

_HEADLESS_SNIPPET = """
import sys
import ui.artifacts  # noqa: F401  (the two new accessors live here)
banned = [m for m in ("streamlit", "anthropic", "claude_agent_sdk",
                      "engine.review", "agent.loop") if m in sys.modules]
print("BANNED:" + ",".join(banned))
"""


def test_artifacts_import_is_headless():
    proc = subprocess.run(
        [sys.executable, "-c", _HEADLESS_SNIPPET],
        cwd=str(_REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"headless import failed: {proc.stderr}"
    out = proc.stdout.strip().splitlines()[-1]
    assert out == "BANNED:", f"ui.artifacts pulled banned modules: {out}"


# ── (e) box-isolation ────────────────────────────────────────────────────────────────

def test_sign_renders_from_frozen_compile_output(tmp_path):
    """Signing renders from the frozen compile_output; it never recomputes F5 boxes."""
    import json as _json

    from ui.sign import sign_working_paper

    artifacts = load_demo_artifacts()
    # Deep snapshot of the entire compile_output (the frozen F5 box source).
    frozen = _json.dumps(artifacts.review_result["compile_output"], sort_keys=True)

    pdf = sign_working_paper(
        artifacts.review_result, reviewer_name="Box Guard", out_dir=tmp_path
    )
    assert pdf.exists() and pdf.stat().st_size > 0
    # The frozen compile_output is unchanged by the render (no recompute, no mutation).
    assert _json.dumps(artifacts.review_result["compile_output"], sort_keys=True) == frozen
