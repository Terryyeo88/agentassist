"""Failing-first tests for the WORDING-ONLY correction of the _RC_OVR_CAVEAT
constant in orchestrator/check_partial_exemption.py (the "caveat" field of the
PARTIAL_EXEMPTION_DE_MINIMIS finding).

WHAT CHANGES (wording only — fire behaviour, boxes, gates all byte-unchanged):
  The current caveat reasons from "Boxes 14-16 not computed" and lists only the
  RC/OVR exclusions. The corrected caveat reasons FROM THE RULE and carries the
  THREE exclusions that attach to the taxable-supplies component of the 5% limb
  denominator, plus data-path notes on how each exclusion lands (or fails to land)
  in this system's coded figures.

RULINGS PINNED HERE (three-times rule — prompt/code/test):
  * RULE-AUTHOR SOURCE: the three exclusions are authored from the IRAS e-Tax
    Guide "GST: Reverse Charge" (Tenth Edition, published 30 Jan 2026), fn 12 at
    p.8. The citation carries the edition + date so staleness is VISIBLE in the
    rendered caveat.
  * fn 12 is RUNNING PROSE. The three-way enumeration of the exclusions is
    RULE-AUTHOR STRUCTURING for the reviewer, NOT an IRAS numbering — so the
    caveat must NOT fabricate "(i)"/"(ii)"/"(iii)" markers (see TestCitation).
  * THE FILENAME SLUG "2ndedition" IS WRONG: the Second Edition of that guide was
    22 Aug 2019; the rule-author source is the Tenth Edition (30 Jan 2026). The
    caveat must therefore never say "2nd edition" / "second edition".
  * SCOPE (zero creep): reg 29(3) incidental-exempt-supplies is a DIFFERENT
    exclusion from a DIFFERENT source (the Partial Exemption guide), carried in a
    SEPARATE field (caveat_incidental) that this correction does NOT touch. It is
    pinned byte-for-byte below as a change-detector.
  * SURFACES-NEVER-ASSERTS: the caveat states what THIS SYSTEM does; it never
    asserts "de minimis is satisfied" and never asserts a figure "is disallowed".

Hermetic: crafted Decimals inline (the test_check_partial_exemption precedent).
No SAP, no anthropic, no frozen-fixture edits. This file is NEW and append-only;
it modifies no existing file (test_check_partial_exemption.py stays LOCKED).
"""
from __future__ import annotations

from decimal import Decimal

from orchestrator.check_partial_exemption import check_partial_exemption


def _fire_kwargs(**over):
    """A crafted input set that FIRES the finding (mirrors the LOCKED
    test_check_partial_exemption._fire_kwargs): flag on, Box-3-heavy, both
    thresholds breached, ZERO TX-RE lines. Wording is exercised on the finding
    this returns — the caveat is data-independent, but we fire faithfully."""
    base = dict(
        actively_makes_exempt=True,
        box_1=Decimal("50000"),
        box_2=Decimal("10000"),
        box_3=Decimal("300000"),
        months=3,
        txre_lines_present=False,
    )
    base.update(over)
    return base


def _finding():
    findings = check_partial_exemption(**_fire_kwargs())
    assert len(findings) == 1
    return findings[0]


def _caveat():
    return _finding()["caveat"]


# ---------------------------------------------------------------------------
# (1) Citation with edition + date so staleness is VISIBLE in the rendered text.
#     fn 12 is running prose — no fabricated (i)/(ii)/(iii) enumeration markers.
# ---------------------------------------------------------------------------

class TestCitation:
    def test_carries_tenth_edition_citation_with_date(self):
        # RED today: the current caveat reasons from "Boxes 14-16 not computed"
        # and carries NO rule-author citation. The corrected caveat cites the
        # edition + publication date so a future reader sees the source's age.
        c = _caveat()
        assert "RC e-Tax Guide (Tenth Edition, 30 Jan 2026), fn 12" in c

    def test_carries_page_pin(self):
        # RED today. fn 12 sits at p.8 of the Tenth Edition; the page pin is part
        # of the citation.
        assert "(p.8)" in _caveat()

    def test_does_not_fabricate_iras_enumeration_markers(self):
        # HONESTY GUARD (GREEN today, must stay GREEN): fn 12 is RUNNING PROSE.
        # The three-way split of the exclusions is rule-author structuring for the
        # reviewer, not an IRAS numbering, so the caveat must not invent
        # "(i)"/"(ii)"/"(iii)" markers that would misrepresent the source.
        c = _caveat()
        assert "(i)" not in c
        assert "(ii)" not in c
        assert "(iii)" not in c

    def test_no_stale_edition_reference(self):
        # STALENESS GUARD (GREEN today, must stay GREEN): the filename slug
        # "2ndedition" is wrong — the Second Edition (22 Aug 2019) is NOT the
        # rule-author source. The caveat must never claim the 2nd/Second Edition.
        c = _caveat().lower()
        assert "2nd edition" not in c
        assert "second edition" not in c


# ---------------------------------------------------------------------------
# (2)+(3) The three exclusions, concept-framed, attaching to the taxable-supplies
#         component of the 5% limb denominator; the literal "RC/OVR" retained.
# ---------------------------------------------------------------------------

class TestThreeExclusions:
    def test_denominator_component_named(self):
        # RED today: the corrected caveat frames the exclusions as attaching to
        # "the value of taxable supplies" (the taxable-supplies component of the
        # 5% limb denominator), not to "all taxable and exempt supplies" wholesale.
        assert "the value of taxable supplies" in _caveat()

    def test_exclusion_reverse_charge(self):
        # RED today: first exclusion — imported services subject to reverse charge.
        assert "imported services subject to reverse charge" in _caveat()

    def test_exclusion_overseas_vendor_registration(self):
        # RED today: second exclusion — the overseas vendor registration (OVR)
        # regime, including its electronic-marketplace-operator limb.
        c = _caveat()
        assert "overseas vendor registration regime" in c
        assert "electronic marketplace operator" in c

    def test_exclusion_customer_accounting(self):
        # RED today: third exclusion — supplies subject to customer accounting.
        assert "subject to customer accounting" in _caveat()

    def test_retains_literal_rc_ovr_substring(self):
        # RED today (current caveat says "Reverse-charge / OVR", not "RC/OVR").
        # WHY PIN IT: the LOCKED assertion at tests/test_check_partial_exemption.py
        # line 223 is `assert "RC/OVR" in f["caveat"] or "Boxes 14" in f["caveat"]`.
        # It passes TODAY via the "Boxes 14" disjunct; the correction REMOVES box
        # reasoning (see TestNoBoxReasoning), so "RC/OVR" MUST be present to keep
        # that locked test green. This is faithful wording, not a token hack: RC
        # and OVR are two of the three exclusions, so naming them "RC/OVR" is
        # accurate — and the locked test pins the substring's presence.
        assert "RC/OVR" in _caveat()


# ---------------------------------------------------------------------------
# (4) The corrected caveat reasons FROM THE RULE, not from "Boxes 14-16".
# ---------------------------------------------------------------------------

class TestNoBoxReasoning:
    def test_no_box_14_reasoning(self):
        # RED today: the current caveat says "Boxes 14-16 ... are not computed".
        # The correction reasons from the rule (the exclusions), so the box-chain
        # reasoning is gone entirely.
        assert "Boxes 14" not in _caveat()


# ---------------------------------------------------------------------------
# (5)+(6)+(7) Data-path notes: how each exclusion lands (or fails to) in the
#             coded figures — SAP-correct-by-accident, declared/filed over-state,
#             customer-accounting latency.
# ---------------------------------------------------------------------------

class TestDataPathNotes:
    def test_sap_correct_by_accident(self):
        # RED today: on the SAP/extract path the exclusions are journal-booked and
        # thus structurally absent from the denominator — the figure is correct by
        # DATA-PATH ACCIDENT, not by design.
        c = _caveat()
        assert "journal-booked" in c
        assert "data-path accident" in c

    def test_declared_or_filed_path_overstates(self):
        # RED today: on the declared/filed-return path the excluded values may be
        # baked into the filed figure, so the taxable-supplies component is
        # over-stated.
        c = _caveat()
        assert "declared or filed figure" in c
        assert "over-stated" in c

    def test_customer_accounting_latency(self):
        # RED today: the customer-accounting exclusion is LATENT — the ordinary
        # mapping carries no code for it and no such code is mapped today, so it
        # cannot be excluded even where it should be.
        c = _caveat()
        assert "latent" in c
        assert "ordinary mapping" in c
        assert "no such code is mapped today" in c


# ---------------------------------------------------------------------------
# Scope + wording-only + never-asserts guards. These fence the correction: it is
# wording-only, it does not touch the reg 29(3) field, and it never asserts.
# ---------------------------------------------------------------------------

# Byte-exact reproduction of the CURRENT caveat_incidental field
# (orchestrator/check_partial_exemption.py lines 90-104). Reg 29(3) is a DIFFERENT
# exclusion from a DIFFERENT source (the Partial Exemption guide), out of scope for
# this correction. Any drift here means the correction leaked into a neighbour field.
_EXPECTED_INCIDENTAL_CAVEAT = (
    "Incidental exempt supplies: supplies qualifying as incidental exempt "
    "supplies under reg 29(3) (for example bank interest, realised "
    "foreign-exchange gain/loss, share issuance) are excluded from both the "
    "numerator and the denominator of the De Minimis test. This system cannot "
    "identify them — no tax code, account code or item code distinguishes an "
    "incidental exempt supply from a trade exempt supply — so Box 3 is used as "
    "coded. Where Box 3 is re-derived from sales invoice lines, journal-booked "
    "incidental supplies are structurally absent (journal entries are not read by "
    "this system). Where Box 3 derives from a declared or filed figure, or where "
    "an incidental supply has been coded ES33/ESN33 on an invoice line, the "
    "numerator may be overstated and this finding may be raised where the De "
    "Minimis Rule is in fact satisfied. The reviewer confirms the composition of "
    "Box 3 before drawing any apportionment conclusion."
)


class TestScopeGuards:
    def test_candidate_tail_retained(self):
        # GREEN today, must stay GREEN: the caveat remains a CANDIDATE, closing on
        # "not a determination of non-compliance".
        assert "not a determination of non-compliance" in _caveat()

    def test_incidental_caveat_byte_unchanged(self):
        # ZERO-SCOPE-CREEP GUARD (GREEN today, must stay GREEN): the reg 29(3)
        # incidental-exempt-supplies caveat is a SEPARATE field, a different
        # exclusion from a different source, NOT part of this correction. It must
        # be byte-identical before and after the build.
        assert _finding()["caveat_incidental"] == _EXPECTED_INCIDENTAL_CAVEAT

    def test_wording_only_caveat_not_baked_into_description(self):
        # GREEN today, must stay GREEN: the caveat is a SEPARATE field, never a
        # substring of the description — mirrors the RC/OVR caveat discipline.
        f = _finding()
        assert f["caveat"] not in f["description"]

    def test_fire_behaviour_unchanged(self):
        # GREEN today, must stay GREEN: wording-only means the finding still fires
        # exactly once with the same check id. No predicate/box/gate change.
        findings = check_partial_exemption(**_fire_kwargs())
        assert len(findings) == 1
        assert findings[0]["check"] == "PARTIAL_EXEMPTION_DE_MINIMIS"

    def test_never_asserts_in_caveat(self):
        # SURFACES-NEVER-ASSERTS GUARD (GREEN today, must stay GREEN): the caveat
        # never asserts a verdict — not that de minimis is satisfied, not that an
        # amount is disallowed.
        c = _caveat().lower()
        assert "de minimis is satisfied" not in c
        assert "is disallowed" not in c
