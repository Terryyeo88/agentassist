"""Phase 2 validation: T2.9 declared-vs-computed F5 full-pipeline run."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(".").resolve()))
from dotenv import load_dotenv
load_dotenv(Path("..") / "sap-b1-ai-agent" / ".env")

from config.loader import load_client_config
from orchestrator.chain import run_chain
from orchestrator.check_declared_f5 import load_declared_f5
from report.sections import build_declared_f5_section, build_not_examined_section
from report.render import render_declared_f5_section

PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}
FIXTURES = Path("tests/fixtures")
FAIL = []


print("=== PHASE 2: T2.9 FULL-PIPELINE VALIDATION ===\n")

cfg = load_client_config("sbodemosg", check_connectivity=True)

# Step 0: re-capture authoritative baseline (no declared-f5)
print("[0] Baseline run (no --declared-f5) ...")
base_out, base_gates = run_chain(cfg, PERIOD, declared_f5=None)
BASE_BOXES = base_out["calculate"]["boxes"]
BASE_BOXES_JSON = json.dumps(BASE_BOXES, sort_keys=True)
print("    Computed boxes:")
for k in sorted(BASE_BOXES):
    print(f"      {k}: {BASE_BOXES[k]}")
base_all_passed = base_gates["all_passed"]
print(f"    gate all_passed: {base_all_passed}")
base_decl = base_out.get("declared_f5_findings")
print(f"    declared_f5_findings: {base_decl}")
print()


class _Cfg:
    custom_vat_groups = {}


def run_fixture(label, fixture_file, expected_check_types, description):
    print(f"[{label}] {description}")
    df5 = load_declared_f5(FIXTURES / fixture_file, PERIOD)
    out, gates = run_chain(cfg, PERIOD, declared_f5=df5)

    findings = out["declared_f5_findings"]
    boxes_json = json.dumps(out["calculate"]["boxes"], sort_keys=True)

    print(f"    findings ({len(findings)}):")
    for f in findings:
        chk = f.get("check", "?")
        ftype = f.get("finding_type", "?")
        box = f.get("box", "?")
        delta = f.get("delta")
        delta_str = f"{delta:+.6g}" if isinstance(delta, (int, float)) else str(delta)
        print(f"      [{chk}] {ftype}  box={box}  delta={delta_str}")
        if f.get("description"):
            print(f"           {f['description'][:120]}")
        if f.get("note"):
            print(f"           note: {f['note'][:80]}")
        if f.get("root_cause_attribution"):
            print(f"           root_cause: {f['root_cause_attribution']}")

    # Assertion 1: correct check types present
    actual_checks = set(f["check"] for f in findings)
    if actual_checks != set(expected_check_types):
        FAIL.append(f"{label}: check types expected={set(expected_check_types)} got={actual_checks}")
        print(f"    FAIL check types: expected={set(expected_check_types)} got={actual_checks}")
    else:
        print(f"    PASS check types: {actual_checks}")

    # Assertion 2: box isolation
    if boxes_json != BASE_BOXES_JSON:
        FAIL.append(f"{label}: box isolation FAILED — computed boxes differ from baseline")
        print(f"    FAIL box isolation")
        # Show diff
        act = json.loads(boxes_json)
        base = json.loads(BASE_BOXES_JSON)
        for k in sorted(set(act) | set(base)):
            if act.get(k) != base.get(k):
                print(f"      diff {k}: baseline={base.get(k)} actual={act.get(k)}")
    else:
        print(f"    PASS box isolation (computed boxes byte-identical to baseline)")

    # Assertion 3: gate all_passed unchanged
    act_all_passed = gates["all_passed"]
    if act_all_passed != base_all_passed:
        FAIL.append(f"{label}: gate all_passed mismatch: {act_all_passed} vs baseline {base_all_passed}")
        print(f"    FAIL gate all_passed: {act_all_passed} vs baseline {base_all_passed}")
    else:
        print(f"    PASS gate all_passed: {act_all_passed}")

    # Assertion 4: render_declared_f5_section
    section = build_declared_f5_section(out)
    text = render_declared_f5_section(section)
    if expected_check_types:
        if not text:
            FAIL.append(f"{label}: render_declared_f5_section returned empty string for non-empty findings")
            print(f"    FAIL render: got empty string")
        else:
            first_line = text.splitlines()[0]
            print(f"    PASS render: {len(text)} chars, first line: {first_line}")
    else:
        if text:
            FAIL.append(f"{label}: render_declared_f5_section returned non-empty for zero findings")
            print(f"    FAIL render: expected empty, got: {text[:60]}")
        else:
            print(f"    PASS render: empty string for zero findings")

    # Assertion 5: Section 6 suppression
    ne = build_not_examined_section(out, _Cfg(), declared_f5_findings=findings)
    suppressed = not any(item.startswith("Declared-vs-computed F5 comparison") for item in ne.items)
    if expected_check_types:
        if not suppressed:
            FAIL.append(f"{label}: Section 6 NOT-examined line not suppressed despite findings")
            print(f"    FAIL Section-6 suppression: placeholder still present")
        else:
            print(f"    PASS Section-6 suppression: placeholder removed")
    else:
        if suppressed:
            FAIL.append(f"{label}: Section 6 NOT-examined line incorrectly suppressed for zero findings")
            print(f"    FAIL Section-6: placeholder missing despite zero findings")
        else:
            print(f"    PASS Section-6: placeholder retained for zero findings")

    print()
    return findings, text


# Fixture B: Check B only
findings_b, text_b = run_fixture(
    "B",
    "declared-f5-fixture-b.json",
    expected_check_types=["B"],
    description="Fixture B — Check B only (internally consistent, box_1 declared +5000 above computed)",
)

# Fixture B deep assertions
b_primary = [f for f in findings_b if f.get("finding_type") == "declared_vs_computed_divergence"]
b_derived = [f for f in findings_b if f.get("finding_type") == "declared_vs_computed_divergence_derived"]

if len(b_primary) != 1 or b_primary[0]["box"] != "box_1":
    FAIL.append(f"B: expected exactly 1 primary Check B finding on box_1, got {[(f['box'], f['finding_type']) for f in b_primary]}")
    print(f"FAIL B: wrong primary finding box")
else:
    f1 = b_primary[0]
    print(f"[B-detail] Primary: box={f1['box']} delta={f1['delta']:+.6g} direction={f1['direction']} tol={f1['tolerance_applied']}")
    if abs(f1["delta"] - 5000.03) >= 0.01:
        FAIL.append(f"B: expected box_1 delta ~+5000.03, got {f1['delta']}")
        print(f"    FAIL delta: expected ~+5000.03, got {f1['delta']}")
    else:
        print(f"    PASS box_1 delta ~+5000.03 correct")
    if f1["direction"] != "over_declared":
        FAIL.append(f"B: expected direction=over_declared, got {f1['direction']}")
        print(f"    FAIL direction: {f1['direction']}")
    else:
        print(f"    PASS direction=over_declared")

if len(b_derived) != 1 or b_derived[0]["box"] != "box_4":
    FAIL.append(f"B: expected exactly 1 derived finding on box_4, got {[(f.get('box'), f.get('finding_type')) for f in b_derived]}")
    print(f"FAIL B: wrong derived finding")
else:
    fd = b_derived[0]
    rca = fd.get("root_cause_attribution", {})
    note = fd.get("note", "")
    print(f"[B-detail] Derived: box={fd['box']} delta={fd['delta']:+.6g} root_cause_keys={list(rca.keys()) if isinstance(rca, dict) else rca}")
    if not ("box_1" in rca if isinstance(rca, dict) else "box_1" in str(rca)):
        FAIL.append("B: box_1 not in root_cause_attribution of derived box_4 finding")
        print(f"    FAIL root_cause_attribution missing box_1")
    else:
        print(f"    PASS root_cause_attribution contains box_1")
    if "informational consequence" not in note:
        FAIL.append(f"B: derived note missing 'informational consequence', got: {note[:80]}")
        print(f"    FAIL note: {note[:80]}")
    else:
        print(f"    PASS note contains 'informational consequence'")

print()

# Fixture A: Check A only
findings_a, text_a = run_fixture(
    "A",
    "declared-f5-fixture-a.json",
    expected_check_types=["A"],
    description="Fixture A — Check A only (box_4 identity violated by +100, independent boxes near computed)",
)

a_findings = [f for f in findings_a if f.get("check") == "A"]
if len(a_findings) != 1 or a_findings[0]["box"] != "box_4":
    FAIL.append(f"A: expected exactly 1 Check A finding on box_4, got {[(f.get('check'), f.get('box')) for f in findings_a]}")
    print(f"FAIL A: wrong Check A findings")
else:
    fa = a_findings[0]
    print(f"[A-detail] Check A: box={fa['box']} rule={fa['rule'][:60]}")
    print(f"           declared_box4={fa['declared_box4']} expected_box4={fa['expected_box4']} delta={fa['delta']:+.6g}")
    if abs(fa["delta"] - 100.0) >= 1e-9:
        FAIL.append(f"A: expected Check A delta=+100.0, got {fa['delta']}")
        print(f"    FAIL Check A delta: {fa['delta']}")
    else:
        print(f"    PASS Check A delta=+100.0")
    if "Box 4 must equal Box 1 + Box 2 + Box 3" not in fa["rule"]:
        FAIL.append(f"A: wrong rule text: {fa['rule']}")
        print(f"    FAIL rule text: {fa['rule']}")
    else:
        print(f"    PASS rule text correct")

b_in_a = [f for f in findings_a if f.get("check") == "B"]
if b_in_a:
    FAIL.append(f"A: unexpected Check B findings: {[(f.get('box'), f.get('delta')) for f in b_in_a]}")
    print(f"    FAIL A: unexpected Check B findings present: {[(f.get('box'), f.get('delta')) for f in b_in_a]}")
else:
    print(f"    PASS no Check B findings in Fixture A")

print()

# Fixture C: Control
findings_c, text_c = run_fixture(
    "C",
    "declared-f5-fixture-c.json",
    expected_check_types=[],
    description="Fixture C — Control (all declared within tolerance of computed)",
)

if findings_c:
    FAIL.append(f"C: expected zero findings, got {len(findings_c)}: {[(f.get('check'), f.get('box'), f.get('delta')) for f in findings_c]}")
    print(f"FAIL C: {len(findings_c)} unexpected findings")
else:
    print(f"[C-detail] PASS zero findings confirmed (false-positive check)")

print()

# Rendered section text dumps
print("=== RENDERED SECTION TEXT (Fixture A) ===")
print(text_a if text_a else "(empty)")
print()
print("=== RENDERED SECTION TEXT (Fixture B) ===")
print(text_b if text_b else "(empty)")
print()

# Summary
print("=== PHASE 2 SUMMARY ===")
if FAIL:
    print(f"FAILURES ({len(FAIL)}):")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL ASSERTIONS PASSED")
