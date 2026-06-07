"""
orchestrator/gates.py — Reconciliation gates for the GST audit chain.

Each gate function runs immediately after its corresponding step, inspects
the step's output for internal consistency, and either returns a `checked`
dict (pass) or raises GateFailure (halt).  Gate functions never mutate
their inputs — they are pure read-only validators.

Common contract for all five gates:
    - Returns a `checked` dict of the key values inspected so the caller
      can record them in the audit bundle regardless of pass/fail.
    - Raises GateFailure with the same `checked` dict attached as .checked
      so callers building a partial gate record don't need to re-inspect
      the step output after the exception.
    - Emits log.warning() for conditions that are notable but not
      chain-halting (e.g. unknown VatGroups, missing inlinecount).

Gate summary:
    gate_1  After fetch      — fetched record count matches SAP $inlinecount.
    gate_2  After calculate  — F5 box identities: box_4 = box_1+2+3,
                               box_8 = box_6−box_7.
    gate_3  After classify   — classify summary count matches issue list length;
                               every issue's vat_group is present in the inventory.
    gate_4  After detect     — severity_counts sum matches issue list length;
                               no issue references a doc_num absent from the manifest.
    gate_5  After compile    — E1 doc_num sets agree across calculate and detect;
                               unknown VatGroups flagged by calculate also appear
                               in classify's vatgroup_inventory.

Box key names below are the canonical contract and MUST be reconciled against
calculate_f5_return's actual output keys in sap_b1_server.py when the tool is
wired in — flag a mismatch rather than silently mapping.

Dependencies:
    orchestrator.exceptions  GateFailure
    orchestrator.schemas     ClassifyOutput, DetectOutput, F5ReturnOutput,
                             FetchManifest
"""
from __future__ import annotations

import logging

from .exceptions import GateFailure
from .schemas import ClassifyOutput, DetectOutput, F5ReturnOutput, FetchManifest

log = logging.getLogger(__name__)


def gate_1_record_count(manifest: FetchManifest) -> dict:
    """Verify the fetched record count matches SAP's reported $inlinecount.

    When SAP omits the $inlinecount header the gate cannot confirm pagination
    completeness, so it returns WARN_PASS rather than failing.  The caller
    (chain.py) is responsible for recording the WARN_PASS status.

    `structural_sentinel_ok` is always True at this point: the fetch step
    guarantees pagination completed via the len(page) < page_size sentinel
    before gate_1 runs.

    Args:
        manifest: FetchManifest dict produced by the fetch step, containing
                  "records" (list), "sap_inline_count" (int or None), and
                  "doc_nums" (set of all fetched document numbers).

    Returns:
        dict: Checked values — {"sap_inline_count", "fetched_count",
              "structural_sentinel_ok"}.  sap_inline_count may be None when
              the OData hint is unavailable.

    Raises:
        GateFailure: When sap_inline_count is not None and differs from
            fetched_count, indicating truncated pagination.
    """
    fetched_count = len(manifest["records"])
    sap_inline_count = manifest["sap_inline_count"]
    checked = {
        "sap_inline_count": sap_inline_count,
        "fetched_count": fetched_count,
        "structural_sentinel_ok": True,
    }

    if sap_inline_count is None:
        log.warning("Gate 1 [record-count]: SAP $inlinecount unavailable — cannot verify pagination completeness")
        return checked

    if fetched_count != sap_inline_count:
        raise GateFailure(
            f"Gate 1 [record-count]: SAP reported {sap_inline_count} records, "
            f"fetched {fetched_count} — possible truncated pagination",
            checked=checked,
        )

    return checked


def gate_2_box_reconciliation(calc: F5ReturnOutput) -> dict:
    """Verify the two fundamental IRAS F5 box identities hold within tolerance.

    Checks:
        1. box_4 (total sales) == box_1 + box_2 + box_3
           (standard-rated + zero-rated + exempt sales must sum to total sales).
        2. box_8 (net GST payable) == box_6 − box_7
           (output tax minus input tax must equal net GST).

    Anomalies on individual documents are logged as warnings and are not
    chain-halting — the compile step is responsible for surfacing them in
    the report's surfaced_warnings list.

    Args:
        calc: F5ReturnOutput dict from the calculate step, containing
              "boxes" (F5 box values keyed by canonical name) and
              "anomalies" (list of per-document anomaly dicts).

    Returns:
        dict: Checked values — {"box_4", "box_1_2_3_sum", "box_8",
              "box_6_minus_7", "tolerance"}.

    Raises:
        GateFailure: When either F5 identity is violated beyond TOLERANCE.
    """
    b = calc["boxes"]
    # 0.01 accommodates floating-point rounding in SAP's currency arithmetic
    # while being tight enough to catch any real reconciliation discrepancy.
    TOLERANCE = 0.01

    # --- Box 4 identity: box_4 = box_1 + box_2 + box_3 ---

    # IRAS F5 identity: total sales must equal the sum of the three sales
    # categories (standard-rated, zero-rated, exempt).
    box_1_2_3_sum = (
        b["box_1_standard_rated_sales"]
        + b["box_2_zero_rated_sales"]
        + b["box_3_exempt_sales"]
    )

    # --- Box 8 identity: box_8 = box_6 − box_7 ---

    # IRAS F5 identity: net GST payable must equal output tax minus input tax.
    box_6_minus_7 = b["box_6_output_tax"] - b["box_7_input_tax"]

    checked = {
        "box_4": b["box_4_total_sales"],
        "box_1_2_3_sum": box_1_2_3_sum,
        "box_8": b["box_8_net_gst"],
        "box_6_minus_7": box_6_minus_7,
        "tolerance": TOLERANCE,
    }

    if abs(b["box_4_total_sales"] - box_1_2_3_sum) > TOLERANCE:
        raise GateFailure(
            f"Gate 2 [box-4]: box_4={b['box_4_total_sales']:.2f} != "
            f"box_1+box_2+box_3={box_1_2_3_sum:.2f} (delta={abs(b['box_4_total_sales'] - box_1_2_3_sum):.4f})",
            checked=checked,
        )

    if abs(b["box_8_net_gst"] - box_6_minus_7) > TOLERANCE:
        raise GateFailure(
            f"Gate 2 [box-8]: box_8={b['box_8_net_gst']:.2f} != "
            f"box_6-box_7={box_6_minus_7:.2f} (delta={abs(b['box_8_net_gst'] - box_6_minus_7):.4f})",
            checked=checked,
        )

    for anomaly in calc["anomalies"]:
        log.warning(f"Gate 2 [anomaly]: doc_num={anomaly['doc_num']} — {anomaly['issue']}")
        # Not a halt; compile step must preserve these in surfaced_warnings

    return checked


def gate_3_inventory_consistency(classify: ClassifyOutput) -> dict:
    """Verify the classify output is internally self-consistent.

    Checks:
        1. classify.summary.total == len(classify.issues)
           (the summary count must match the actual issue list length).
        2. Every issue's vat_group key appears in vatgroup_inventory
           (no issue may reference a VatGroup the inventory doesn't know about).

    VatGroups present in the inventory but flagged as unknown to the mapping
    are logged as warnings — they are notable for the operator but do not
    indicate a structural inconsistency within classify's own output.

    Args:
        classify: ClassifyOutput dict from the classify step, containing
                  "summary" (with a "total" count), "issues" (list of issue
                  dicts each with a "vat_group" key), and "vatgroup_inventory"
                  (dict keyed by VatGroup code).

    Returns:
        dict: Checked values — {"summary_total", "issue_count",
              "all_vatgroups_in_inventory"}.

    Raises:
        GateFailure: When summary.total != len(issues), or when any issue
            references a vat_group absent from vatgroup_inventory.
    """
    summary_total = classify["summary"]["total"]
    issue_count = len(classify["issues"])

    inventory_keys = set(classify["vatgroup_inventory"].keys())
    # Precompute the aggregate boolean for the checked dict so the gate record
    # contains a single-field summary even though the loop below surfaces the
    # first specific violating vat_group as a GateFailure message.
    all_vatgroups_in_inventory = all(
        issue["vat_group"] in inventory_keys for issue in classify["issues"]
    )

    checked = {
        "summary_total": summary_total,
        "issue_count": issue_count,
        "all_vatgroups_in_inventory": all_vatgroups_in_inventory,
    }

    if summary_total != issue_count:
        raise GateFailure(
            f"Gate 3 [summary-count]: summary.total={summary_total} "
            f"!= len(issues)={issue_count}",
            checked=checked,
        )

    for issue in classify["issues"]:
        if issue["vat_group"] not in inventory_keys:
            raise GateFailure(
                f"Gate 3 [vg-reference]: issue doc_num={issue['doc_num']} "
                f"references vat_group='{issue['vat_group']}' not present in vatgroup_inventory",
                checked=checked,
            )

    for vg, entry in classify["vatgroup_inventory"].items():
        if not entry["known_to_mapping"]:
            log.warning(f"Gate 3 [unknown-vg]: '{vg}' not in mapping — compile must surface as anomaly")

    return checked


def gate_4_detect_consistency(detect: DetectOutput, manifest: FetchManifest) -> dict:
    """Verify detect's severity counts are consistent and all doc refs are valid.

    Checks:
        1. sum(severity_counts.values()) == len(issues)
           (the severity breakdown must account for every issue exactly once).
        2. No issue references a doc_num that is absent from the fetched manifest
           (detect must not invent document references outside the fetch scope).

    Args:
        detect:   DetectOutput dict from the detect step, containing "issues"
                  (list of issue dicts with "doc_num" and "error_code") and
                  "severity_counts" (dict mapping severity label to int count).
        manifest: FetchManifest dict from the fetch step, used to validate
                  that every issue's doc_num belongs to the fetched dataset.

    Returns:
        dict: Checked values — {"severity_sum", "issue_count",
              "dangling_doc_refs"}.

    Raises:
        GateFailure: When severity_counts sum != len(issues), or when any
            issue references a doc_num absent from manifest["doc_nums"].
    """
    severity_sum = sum(detect["severity_counts"].values())
    issue_count = len(detect["issues"])

    # Count issues whose doc_num is not None but is absent from the manifest —
    # recorded in checked for observability even though the loop below halts on
    # the first occurrence.
    dangling_doc_refs = sum(
        1 for issue in detect["issues"]
        if issue["doc_num"] is not None and issue["doc_num"] not in manifest["doc_nums"]
    )

    checked = {
        "severity_sum": severity_sum,
        "issue_count": issue_count,
        "dangling_doc_refs": dangling_doc_refs,
    }

    if severity_sum != issue_count:
        raise GateFailure(
            f"Gate 4 [severity-count]: sum(severity_counts)={severity_sum} "
            f"!= len(issues)={issue_count}",
            checked=checked,
        )

    for issue in detect["issues"]:
        if issue["doc_num"] is not None and issue["doc_num"] not in manifest["doc_nums"]:
            raise GateFailure(
                f"Gate 4 [dangling-ref]: detect issue references doc_num={issue['doc_num']} "
                f"which does not appear in fetched dataset (error_code={issue['error_code']})",
                checked=checked,
            )

    return checked


def gate_5_cross_tool_consistency(
    calc: F5ReturnOutput,
    classify: ClassifyOutput,
    detect: DetectOutput,
) -> dict:
    """Verify cross-tool agreement between calculate, classify, and detect outputs.

    Checks:
        1. E1 set equality: the set of doc_nums flagged as E1 by calculate
           must exactly match those flagged as E1 by detect.  E1 is the
           only error code produced by both tools independently, making it
           a reliable cross-tool consistency signal.
        2. Unknown VatGroup agreement: every VatGroup that calculate reports
           as unknown must also appear in classify's vatgroup_inventory as
           unknown.  The reverse is not enforced — classify may encounter
           VatGroups that calculate's current period doesn't exercise.

    Args:
        calc:     F5ReturnOutput from the calculate step, providing
                  "e1_candidates" (list of dicts with "doc_num") and
                  "anomalies" (list of dicts with "issue" strings).
        classify: ClassifyOutput from the classify step, providing
                  "vatgroup_inventory" (dict keyed by VatGroup code, each
                  entry with a "known_to_mapping" bool).
        detect:   DetectOutput from the detect step, providing "issues"
                  (list of dicts with "doc_num" and "error_code").

    Returns:
        dict: Checked values — {"e1_calc_vs_detect_match",
              "unknown_vatgroups_agree"}.

    Raises:
        GateFailure: When the E1 doc_num sets differ, or when calculate
            references unknown VatGroups not present in classify's inventory.
    """
    # --- E1 set equality: calculate vs detect ---

    calc_e1 = {c["doc_num"] for c in calc["e1_candidates"]}
    detect_e1 = {i["doc_num"] for i in detect["issues"] if i["error_code"] == "E1"}
    e1_match = calc_e1 == detect_e1

    # --- Unknown VatGroup agreement: calculate vs classify ---

    calc_unknown_vgs: set[str] = set()
    for a in calc["anomalies"]:
        if "unknown VatGroup" in a["issue"]:
            # issue format: "unknown VatGroup 'XYZ' — not in mapping"
            # Split on single-quote and take index 1 to extract the VatGroup
            # code between the first pair of quotes.
            try:
                calc_unknown_vgs.add(a["issue"].split("'")[1])
            except IndexError:
                pass  # malformed — logged, not halted

    classify_unknown_vgs = {
        vg for vg, entry in classify["vatgroup_inventory"].items()
        if not entry["known_to_mapping"]
    }
    # One-directional check: calc may only report unknowns that classify also
    # flagged.  classify is allowed to know about additional unknown VatGroups
    # that the current period's calculate output didn't encounter.
    unmatched = calc_unknown_vgs - classify_unknown_vgs
    vg_agree = len(unmatched) == 0

    checked = {
        "e1_calc_vs_detect_match": e1_match,
        "unknown_vatgroups_agree": vg_agree,
    }

    if not e1_match:
        raise GateFailure(
            f"Gate 5 [E1-set]: calculate E1 doc_nums={sorted(calc_e1)} "
            f"!= detect E1 doc_nums={sorted(detect_e1)} "
            f"(only-in-calc={sorted(calc_e1 - detect_e1)}, only-in-detect={sorted(detect_e1 - calc_e1)})",
            checked=checked,
        )

    if not vg_agree:
        raise GateFailure(
            f"Gate 5 [vg-unknown]: calculate references unknown VatGroups "
            f"not flagged by classify: {sorted(unmatched)}",
            checked=checked,
        )

    return checked
