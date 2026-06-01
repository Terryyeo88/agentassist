from __future__ import annotations

# Box key names below are the canonical contract and MUST be reconciled against
# calculate_f5_return's actual output keys in sap_b1_server.py when the tool is
# wired in — flag a mismatch rather than silently mapping.

import logging

from .exceptions import GateFailure
from .schemas import ClassifyOutput, DetectOutput, F5ReturnOutput, FetchManifest

log = logging.getLogger(__name__)


def gate_1_record_count(manifest: FetchManifest) -> None:
    if manifest["sap_inline_count"] is None:
        log.warning("Gate 1 [record-count]: SAP $inlinecount unavailable — cannot verify pagination completeness")
        return
    actual = len(manifest["records"])
    if actual != manifest["sap_inline_count"]:
        raise GateFailure(
            f"Gate 1 [record-count]: SAP reported {manifest['sap_inline_count']} records, "
            f"fetched {actual} — possible truncated pagination"
        )


def gate_2_box_reconciliation(calc: F5ReturnOutput) -> None:
    b = calc["boxes"]
    TOLERANCE = 0.01

    box4_expected = b["box_1_standard_rated_sales"] + b["box_2_zero_rated_sales"] + b["box_3_exempt_sales"]
    if abs(b["box_4_total_sales"] - box4_expected) > TOLERANCE:
        raise GateFailure(
            f"Gate 2 [box-4]: box_4={b['box_4_total_sales']:.2f} != "
            f"box_1+box_2+box_3={box4_expected:.2f} (delta={abs(b['box_4_total_sales'] - box4_expected):.4f})"
        )

    box8_expected = b["box_6_output_tax"] - b["box_7_input_tax"]
    if abs(b["box_8_net_gst"] - box8_expected) > TOLERANCE:
        raise GateFailure(
            f"Gate 2 [box-8]: box_8={b['box_8_net_gst']:.2f} != "
            f"box_6-box_7={box8_expected:.2f} (delta={abs(b['box_8_net_gst'] - box8_expected):.4f})"
        )

    for anomaly in calc["anomalies"]:
        log.warning(f"Gate 2 [anomaly]: doc_num={anomaly['doc_num']} — {anomaly['issue']}")
        # Not a halt; compile step must preserve these in surfaced_warnings


def gate_3_inventory_consistency(classify: ClassifyOutput) -> None:
    if classify["summary"]["total"] != len(classify["issues"]):
        raise GateFailure(
            f"Gate 3 [summary-count]: summary.total={classify['summary']['total']} "
            f"!= len(issues)={len(classify['issues'])}"
        )

    inventory_keys = set(classify["vatgroup_inventory"].keys())
    for issue in classify["issues"]:
        if issue["vat_group"] not in inventory_keys:
            raise GateFailure(
                f"Gate 3 [vg-reference]: issue doc_num={issue['doc_num']} "
                f"references vat_group='{issue['vat_group']}' not present in vatgroup_inventory"
            )

    for vg, entry in classify["vatgroup_inventory"].items():
        if not entry["known_to_mapping"]:
            log.warning(f"Gate 3 [unknown-vg]: '{vg}' not in mapping — compile must surface as anomaly")


def gate_4_detect_consistency(detect: DetectOutput, manifest: FetchManifest) -> None:
    count_sum = sum(detect["severity_counts"].values())
    if count_sum != len(detect["issues"]):
        raise GateFailure(
            f"Gate 4 [severity-count]: sum(severity_counts)={count_sum} "
            f"!= len(issues)={len(detect['issues'])}"
        )

    for issue in detect["issues"]:
        if issue["doc_num"] is not None and issue["doc_num"] not in manifest["doc_nums"]:
            raise GateFailure(
                f"Gate 4 [dangling-ref]: detect issue references doc_num={issue['doc_num']} "
                f"which does not appear in fetched dataset (error_code={issue['error_code']})"
            )


def gate_5_cross_tool_consistency(
    calc: F5ReturnOutput,
    classify: ClassifyOutput,
    detect: DetectOutput,
) -> None:
    # E1 set equality: calculate.e1_candidates vs detect issues with error_code "E1"
    calc_e1 = {c["doc_num"] for c in calc["e1_candidates"]}
    detect_e1 = {i["doc_num"] for i in detect["issues"] if i["error_code"] == "E1"}
    if calc_e1 != detect_e1:
        raise GateFailure(
            f"Gate 5 [E1-set]: calculate E1 doc_nums={sorted(calc_e1)} "
            f"!= detect E1 doc_nums={sorted(detect_e1)} "
            f"(only-in-calc={sorted(calc_e1 - detect_e1)}, only-in-detect={sorted(detect_e1 - calc_e1)})"
        )

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
    if unmatched:
        raise GateFailure(
            f"Gate 5 [vg-unknown]: calculate references unknown VatGroups "
            f"not flagged by classify: {sorted(unmatched)}"
        )
