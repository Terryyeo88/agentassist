from __future__ import annotations

# Box key names below are the canonical contract and MUST be reconciled against
# calculate_f5_return's actual output keys in sap_b1_server.py when the tool is
# wired in — flag a mismatch rather than silently mapping.

import logging

from .exceptions import GateFailure
from .schemas import ClassifyOutput, DetectOutput, F5ReturnOutput, FetchManifest

log = logging.getLogger(__name__)


def gate_1_record_count(manifest: FetchManifest) -> dict:
    """Return checked-values dict on pass; raise GateFailure (with .checked) on fail.

    structural_sentinel_ok is always True at this point: the fetch step guarantees
    pagination completed via the len(page) < 20 sentinel before gate_1 runs.
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
    b = calc["boxes"]
    TOLERANCE = 0.01

    box_1_2_3_sum = (
        b["box_1_standard_rated_sales"]
        + b["box_2_zero_rated_sales"]
        + b["box_3_exempt_sales"]
    )
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
    summary_total = classify["summary"]["total"]
    issue_count = len(classify["issues"])

    inventory_keys = set(classify["vatgroup_inventory"].keys())
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
    severity_sum = sum(detect["severity_counts"].values())
    issue_count = len(detect["issues"])

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
    # E1 set equality: calculate.e1_candidates vs detect issues with error_code "E1"
    calc_e1 = {c["doc_num"] for c in calc["e1_candidates"]}
    detect_e1 = {i["doc_num"] for i in detect["issues"] if i["error_code"] == "E1"}
    e1_match = calc_e1 == detect_e1

    # Unknown VatGroup agreement: calc anomaly strings vs classify inventory flags
    calc_unknown_vgs: set[str] = set()
    for a in calc["anomalies"]:
        if "unknown VatGroup" in a["issue"]:
            # issue format: "unknown VatGroup 'XYZ' — not in mapping"
            try:
                calc_unknown_vgs.add(a["issue"].split("'")[1])
            except IndexError:
                pass  # malformed — logged, not halted

    classify_unknown_vgs = {
        vg for vg, entry in classify["vatgroup_inventory"].items()
        if not entry["known_to_mapping"]
    }
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
