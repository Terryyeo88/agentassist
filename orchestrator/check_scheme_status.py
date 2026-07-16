"""orchestrator/check_scheme_status.py — deterministic scheme-status contradiction check.

A CONFIG-vs-DATA contradiction check (D+), mirroring check_partial_exemption.py's
shape: the client's DECLARED scheme participation (ClientConfig.participates_in_mes /
participates_in_igds) disagrees with the scheme codes actually present on their
coded lines (an "ME" / "IGDS" row in classify.vatgroup_inventory).

THE FINDING-DESIGN INVARIANT (load-bearing — read before editing any wording):
Every existing E-code is a DATA-INTERNAL contradiction (currency vs code, tax vs
rate) — the data refutes itself, so the finding can name the error. THIS check is
a CONFIG-vs-DATA contradiction and CANNOT know which side is in error. Either the
config flag is stale (the client IS in the scheme and nobody updated the YAML), or
the lines are coded to a scheme the client does not participate in. Every finding
MUST surface both hypotheses and assert neither; it must NEVER state that the
lines are wrongly coded. The phrasing surfaces a question, not a verdict — the
reviewer, who can ask the client whether they are in the scheme, adjudicates.

BASIS (v2 ruling, 2026-07-16): IRAS-prescribed at ASK Annual Review Guide Step
3D.1.1(b) — the NON-participant's Input Tax check: scan the listings for import
permit numbers beginning 'ME' or 'MC'. This system proxies that check via the
VatGroup code because permit numbers are not ingested (SAP: permit-adjacent
fields unpopulated and unprojected; Xero F5: no permit column). The proxy rests
on the client's own coding rather than Singapore Customs' record and is
therefore weaker evidence than the prescribed signal — which is why findings
surface both hypotheses (see the invariant above) rather than naming the error.
This module performs a proxy for 3D.1.1(b), never 3D.1.1(b) itself.

Invariants (mirror check_partial_exemption.py):
- No ``anthropic`` import. Pure Python; safe from orchestrator/.
- check_scheme_status() and run_scheme_status_check() are READ-ONLY over
  compile_output — no box is recomputed, no gate is touched, nothing halts.
- Findings are candidates for review; never verdicts (see the invariant above).
- No Decimal is needed here: the check reads doc_count (int) and two bools —
  no monetary value crosses a float boundary and no division occurs.

INVENTORY CONTRACT (recon-proven, 2026-07-15): a VatGroup with zero documents in
the period is ABSENT from classify.vatgroup_inventory — it is never present with
doc_count == 0 (the classify tool inserts a code only when a line carries it).
The data signal is therefore KEY PRESENCE, read defensively via
``inventory.get("ME") or {}``.

OUT OF SCOPE (human-ruled, 2026-07-15):
- The INVERSE direction (flag ON, zero scheme-coded lines) — a client in MES
  with no imports this period is normal, not a contradiction. Returns [].
- Any CHECK_REGISTRY entry — this check is self-gated by data presence; the
  mirror (PARTIAL_EXEMPTION_DE_MINIMIS) is likewise unregistered.
- Any NOT_EXAMINED change — this check ALWAYS runs (its flags are a predicate
  input, not a gate), so there is nothing to suppress. The standing 3E item
  (MES/IGDS scheme approval status and import-permit verification NOT
  performed) remains TRUE after this build: both sides of this comparison are
  the client's own assertions — a YAML boolean vs the client's own line coding.
  Nothing is verified against an IRAS scheme approval letter; no permit is
  read. This is a CONSISTENCY check, not verification.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# TERRY-AUTHORED CONSTANTS + WORDING (tax semantics — rule-author owns this block).
#
# RULE-AUTHOR-SUPPLIED 2026-07-15 (do not re-derive; no model-inferred tax
# meaning may be added to this block):
#   (1) ME = Major Exporter Scheme. Import GST is SUSPENDED at the border — not
#       paid, so nothing to claim. Routes value to Box 5; NO Box 7.
#   (2) IGDS = Import GST Deferment Scheme. Import GST is DEFERRED into the
#       return — declared and simultaneously claimed. Touches Box 5 + Box 7
#       (and Boxes 18-21, which this system does not compute).
#   (3) A business NOT in MES cannot have import GST suspended. A business NOT
#       in IGDS cannot defer import GST.
#   (4) The two directions are NOT symmetric in consequence:
#       - ME-coded + not-in-MES: the client paid GST at the border and coded it
#         as suspended, so no Box 7 claim was made. This UNDER-CLAIMS the
#         client's own input tax — the client's loss, not IRAS exposure.
#         Severity MEDIUM.
#       - IGDS-coded + not-in-IGDS: GST deferred that was not deferrable — this
#         direction carries IRAS exposure. Severity HIGH.
# ---------------------------------------------------------------------------

# BASIS RULING v2 (rule-author, 2026-07-16), correcting the same-day v1 ruling,
# which was FALSE. v1 concluded no IRAS provision or ASK cell prescribes a
# config-vs-codes comparison. ASK Annual Review Guide Step 3D.1.1(b) (printed
# p.36) DOES prescribe this check — for NON-participants, in Input Tax, the
# step every business performs. v1 reasoned correctly that the check is not
# Step 3E (3E presupposes scheme participation, which is precisely why IRAS put
# the non-participant's check in 3D) and then wrongly inferred it was nowhere:
# both rulings were made without either party searching the guide for where the
# check IS. The honesty point that survives v1: IRAS's signal is the import
# permit number prefix (ME/MC — Singapore Customs' record, third-party
# evidence); ours is the VatGroup code (the client's own bookkeeping). We
# perform a PROXY on weaker evidence, not 3D.1.1(b) itself, and the basis must
# say so.
_BASIS = (
    "IRAS-prescribed check, proxied. The prescribing cell is ASK Annual Review "
    "Guide Step 3D.1.1(b) (Input Tax): a business not approved under the MES, "
    "IGDS or any other GST scheme to import goods with GST suspended or "
    "deferred is to run through its listings for any import permit number that "
    "begins with 'ME' or 'MC'. IRAS's signal is the import-permit-number "
    "prefix — Singapore Customs' record, third-party evidence. Permit numbers "
    "are not ingested by this system, so the check proxies that signal via the "
    "VatGroup code — the client's own bookkeeping: a ME-prefixed permit means "
    "someone actually used MES status at the border, while a ME VatGroup means "
    "someone typed ME into a field. The proxy rests on the client's own coding "
    "rather than Customs' record and is therefore a proxy on weaker evidence "
    "for an IRAS-prescribed check; the finding surfaces both hypotheses rather "
    "than naming the error not because the check is unprescribed, but because "
    "this signal is weaker than the prescribed one. This check performs a "
    "proxy for 3D.1.1(b), not 3D.1.1(b) itself. Grounded in the code "
    "treatments (rule-author-supplied 2026-07-15): ME = import GST suspended "
    "under the Major Exporter Scheme; IGDS = import GST deferred under the "
    "Import GST Deferment Scheme."
)

# Mirrors the mirror's discipline: note and severity_note are SEPARATE fields,
# never baked into the description.
_NOTE = (
    "candidate for review — the reviewer confirms the client's scheme "
    "participation directly with the client; this system cannot determine "
    "whether the configuration or the line coding is the side in error."
)

# Consequence wording is CONDITIONAL by construction ("if these lines were...")
# — the check asserts neither hypothesis (see the module-top invariant).
_ME_SEVERITY_NOTE = (
    "Severity MEDIUM: if these lines were coded to a scheme the client does "
    "not participate in, GST paid at the border was recorded as suspended and "
    "no Box 7 input-tax claim was made — the client under-claims its own "
    "input tax. The consequence falls on the client, not on IRAS."
)
_IGDS_SEVERITY_NOTE = (
    "Severity HIGH: if these lines were coded to a scheme the client does not "
    "participate in, import GST was deferred without entitlement — this "
    "direction carries IRAS exposure."
)


def check_scheme_status(
    *,
    participates_in_mes: bool,
    participates_in_igds: bool,
    me_doc_count: int,
    igds_doc_count: int,
) -> list[dict]:
    """Evaluate the scheme-status contradiction predicate. Pure/read-only.

    An arm fires iff the client's config flag is OFF yet the classify inventory
    carries documents coded to that scheme:
      - IGDS arm: (not participates_in_igds) AND igds_doc_count > 0 -> HIGH.
      - ME arm:   (not participates_in_mes)  AND me_doc_count  > 0 -> MEDIUM.
    When both fire, the IGDS finding is surfaced FIRST (HIGH before MEDIUM).

    Every other corner returns []:
      - flag True + code present = consistent (declared participation matches
        the coding) — nothing to contradict;
      - flag False + code absent = consistent (no scheme coding present);
      - flag True + code absent = the INVERSE direction, ruled OUT of this
        slice (a client in a scheme with no imports this period is normal).

    The finding wording carries BOTH hypotheses (stale configuration vs lines
    coded to a scheme the client does not participate in) and asserts neither —
    see the module-top FINDING-DESIGN INVARIANT.
    """
    findings: list[dict] = []

    # IGDS arm first: HIGH surfaces before MEDIUM when both arms fire.
    if not participates_in_igds and igds_doc_count > 0:
        description = (
            f"The client configuration records no Import GST Deferment Scheme "
            f"(IGDS) participation (participates_in_igds is false), yet "
            f"{igds_doc_count} purchase document(s) in this period carry the "
            f"IGDS VatGroup code, under which import GST is deferred into the "
            f"return (declared and simultaneously claimed). Two hypotheses are "
            f"consistent with this contradiction and this system cannot "
            f"distinguish them: (a) the configuration is stale — the client "
            f"does participate in IGDS and the flag was not updated; or (b) "
            f"the lines are coded to a scheme the client does not participate "
            f"in. The reviewer confirms the client's IGDS status directly with "
            f"the client; this finding asserts neither hypothesis."
        )
        findings.append({
            "check": "SCHEME_STATUS_CONTRADICTION",
            "finding_type": "scheme_status",
            "scheme": "IGDS",
            "vat_group": "IGDS",
            "config_flag": "participates_in_igds",
            "doc_count": igds_doc_count,
            "severity": "HIGH",
            "severity_note": _IGDS_SEVERITY_NOTE,
            "basis": _BASIS,
            "description": description,
            "note": _NOTE,
        })

    if not participates_in_mes and me_doc_count > 0:
        description = (
            f"The client configuration records no Major Exporter Scheme (MES) "
            f"participation (participates_in_mes is false), yet "
            f"{me_doc_count} purchase document(s) in this period carry the ME "
            f"VatGroup code, which records import GST as suspended at the "
            f"border. Two hypotheses are consistent with this contradiction "
            f"and this system cannot distinguish them: (a) the configuration "
            f"is stale — the client does participate in MES and the flag was "
            f"not updated; or (b) the lines are coded to a scheme the client "
            f"does not participate in. The reviewer confirms the client's MES "
            f"status directly with the client; this finding asserts neither "
            f"hypothesis."
        )
        findings.append({
            "check": "SCHEME_STATUS_CONTRADICTION",
            "finding_type": "scheme_status",
            "scheme": "MES",
            "vat_group": "ME",
            "config_flag": "participates_in_mes",
            "doc_count": me_doc_count,
            "severity": "MEDIUM",
            "severity_note": _ME_SEVERITY_NOTE,
            "basis": _BASIS,
            "description": description,
            "note": _NOTE,
        })

    return findings


def run_scheme_status_check(client_config, compile_output: dict) -> list[dict]:
    """Run the check over a completed chain's compile_output. READ-ONLY.

    Reads (never recomputes) ONLY classify.vatgroup_inventory. The scheme rows
    are read defensively — a VatGroup with zero documents is ABSENT from the
    inventory (the recon-proven contract), so ``inventory.get("ME") or {}``
    followed by ``.get("doc_count", 0)`` treats absence as zero.

    The config flags are read with the same getattr forward-compat pattern the
    mirror uses for actively_makes_exempt_supplies. Unlike the mirror there is
    no cheap-out on the flags: the flags are a PREDICATE INPUT, not a gate —
    this check runs on every review, and a flag that is ON simply makes its arm
    consistent (returns no finding).
    """
    mes = bool(getattr(client_config, "participates_in_mes", False))
    igds = bool(getattr(client_config, "participates_in_igds", False))

    inventory = (compile_output.get("classify") or {}).get("vatgroup_inventory") or {}
    me_row = inventory.get("ME") or {}
    igds_row = inventory.get("IGDS") or {}

    return check_scheme_status(
        participates_in_mes=mes,
        participates_in_igds=igds,
        me_doc_count=int(me_row.get("doc_count", 0)),
        igds_doc_count=int(igds_row.get("doc_count", 0)),
    )
