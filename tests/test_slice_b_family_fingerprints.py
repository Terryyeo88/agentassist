"""Slice B — the FAMILY -> identity-key map inside the fingerprint layer.

Terry's ruling (PROPOSED D-2026-09-20-slice-b-adjudicable-rows): one fingerprint function
dispatches on the finding family, and the E-check family's path stays byte-identical.

    | family              | identity keys                                        |
    |---------------------|------------------------------------------------------|
    | E-checks (existing) | (error_code, counterparty, doc_num)   UNCHANGED      |
    | document checks x4  | (check_id-as-error_code, counterparty, doc_num)      |
    | Signal B            | (error_code, named-empty counterparty, reference)    |
    | Signal A            | (error_code, side, period_start, period_end)         |

WHY EACH ROW IS WHAT IT IS
  * Document checks KEEP the counterparty (Terry, ruling 1): Xero bill numbers can collide
    across suppliers, so dropping it risks ONE adjudication sweeping TWO suppliers' bills —
    wrongly re-applying, which is the defect. A join that misses yields a non-re-apply, which
    is the honest failure.
  * Signal A is a per-side AGGREGATE over a whole control account, not a document, so it takes
    the PERIOD. Without it, a Q2 "known accepted" would silently demote Q3's different
    divergence — the sweep defect in another costume.
  * Signal B with a BLANK journal reference gets NO fingerprint at all (Terry, ruling 3):
    never a collapsed shared key. It stays visibly non-adjudicable instead.

NO GOLDEN LITERAL IS AUTHORED HERE. These are structural pins — equality, inequality, key
composition, amount-invariance. The computed values are printed by
`test_zz_print_values_for_hand_pinning` for Terry to hand-pin separately, per the rule that
the agent cannot move its own pins.
"""
from __future__ import annotations

import pytest

from agent.decision_ledger import (
    FINGERPRINT_KEYS,
    LEDGER_RECON_FINGERPRINT_KEYS,
    compute_family_fingerprint,
    compute_finding_fingerprint,
)

PERIOD = {"start": "2026-04-01", "end": "2026-06-30"}
PERIOD_Q3 = {"start": "2026-07-01", "end": "2026-09-30"}


# --------------------------------------------------------------------------- helpers

def doc_check(check="gst_amount_mismatch", doc="BILL-3002", card="OldRate Supplies Pte Ltd",
              **extra):
    """A document-check finding as the serializer will hand it to the fingerprint layer."""
    return {"check_id": check, "error_code": check, "card_name": card, "doc_num": doc, **extra}


def signal_a(side="output", **extra):
    """A Signal A producer dict (orchestrator/check_gst_ledger_recon.py::_make_finding)."""
    return {
        "check_id": "GST_LEDGER_RECON",
        "finding_type": "ledger_recon_divergence",
        "side": side,
        "ledger_gst": 6390.0,
        "declared_gst": 5580.0,
        "divergence": 810.0,
        **extra,
    }


def signal_b(reference="#14", **extra):
    """A Signal B producer dict (::_make_not_included_finding)."""
    return {
        "check_id": "GST_LEDGER_RECON",
        "finding_type": "not_included_gst_drop",
        "account": "820 - GST",
        "reference": reference,
        "amount": 6.3,
        **extra,
    }


def e_check(code="E4", doc="BILL-3002", card="OldRate Supplies Pte Ltd"):
    return {"check_id": code, "error_code": code, "card_name": card, "doc_num": doc}


# --------------------------------------------------------------------------- B2: E-checks frozen

class TestEChecksUnchanged:
    """Invariant (a): the existing family's path is BYTE-IDENTICAL. No version bump."""

    def test_b2_dispatch_delegates_e_checks_to_the_untouched_function(self):
        f = e_check()
        assert compute_family_fingerprint(f, period=PERIOD) == compute_finding_fingerprint(f)

    def test_b2_period_is_ignored_for_e_checks(self):
        # Passing a period must not leak into a family that does not key on it.
        f = e_check()
        assert compute_family_fingerprint(f, period=PERIOD) == compute_family_fingerprint(
            f, period=PERIOD_Q3
        )
        assert compute_family_fingerprint(f, period=None) == compute_finding_fingerprint(f)

    def test_b2_key_tuple_is_still_the_v1_triple(self):
        assert FINGERPRINT_KEYS == ("error_code", "counterparty", "doc_num")


# --------------------------------------------------------------------------- B3 + ruling 1

class TestDocumentFamily:
    def test_b3_same_check_same_document_same_counterparty_is_stable(self):
        assert compute_family_fingerprint(doc_check()) == compute_family_fingerprint(doc_check())

    def test_b3_two_checks_on_one_document_differ(self):
        a = compute_family_fingerprint(doc_check(check="gst_amount_mismatch"))
        b = compute_family_fingerprint(doc_check(check="correct_period"))
        assert a != b, "two different checks on one document must not share a key"

    def test_b3_same_check_different_documents_differ(self):
        a = compute_family_fingerprint(doc_check(doc="BILL-3002"))
        b = compute_family_fingerprint(doc_check(doc="BILL-3009"))
        assert a != b

    def test_ruling1_same_check_same_doc_num_different_counterparties_differ(self):
        """Terry ruling 1: the counterparty is KEPT precisely so this pair cannot collide.

        Xero bill numbers are per-supplier, so "BILL-3002" from two suppliers is two
        documents. Sharing a key here would let one adjudication sweep both.
        """
        a = compute_family_fingerprint(doc_check(card="OldRate Supplies Pte Ltd"))
        b = compute_family_fingerprint(doc_check(card="Serangoon Facilities Pte Ltd"))
        assert a != b

    def test_ruling1_absent_counterparty_uses_the_named_empty_canonical_form(self):
        """A join MISS must be deterministic — the same empty form every time, not a crash
        and not a fabricated name. It keys differently from a present counterparty, so a
        missed join fails to re-apply (honest) rather than re-applying wrongly (the defect).
        """
        miss = compute_family_fingerprint(doc_check(card=None))
        explicit_empty = compute_family_fingerprint(doc_check(card=""))
        assert miss == explicit_empty
        assert miss != compute_family_fingerprint(doc_check(card="OldRate Supplies Pte Ltd"))

    def test_ruling1_counterparty_uses_the_same_normaliser_as_e_checks(self):
        """Whitespace collapse + casefold, identical to the E-check family."""
        a = compute_family_fingerprint(doc_check(card="OldRate  Supplies   Pte Ltd"))
        b = compute_family_fingerprint(doc_check(card="oldrate supplies pte ltd"))
        assert a == b


# --------------------------------------------------------------------------- B4: Signal B

class TestSignalB:
    def test_b4_reference_keyed_and_stable(self):
        assert compute_family_fingerprint(signal_b()) == compute_family_fingerprint(signal_b())

    def test_b4_different_references_differ(self):
        assert compute_family_fingerprint(signal_b("#14")) != compute_family_fingerprint(
            signal_b("MJ-0007")
        )

    def test_b4_never_equals_an_e_check_fingerprint(self):
        sb = compute_family_fingerprint(signal_b())
        for code in ("E1", "E2", "E3", "E4", "NO_GST_REG", "COMPLETENESS"):
            assert sb != compute_family_fingerprint(e_check(code=code, doc="#14", card=None))

    def test_b4_doc_num_canonicalisation_is_str_strip_never_int(self):
        """#34: identifiers are strings. A numeric-looking reference keys as its string form,
        and surrounding whitespace is stripped — but it is never int()-coerced.
        """
        assert compute_family_fingerprint(signal_b("  14  ")) == compute_family_fingerprint(
            signal_b("14")
        )

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_ruling3_blank_reference_stays_unfingerprinted(self, blank):
        """Terry ruling 3: a blank journal reference must NOT collapse onto a shared key.

        A numeric/blank Xero Reference is real data (the recorded Gate-4 hazard). If every
        such row shared one key, one adjudication would sweep all of them. None keeps the row
        visibly non-adjudicable instead — the honest outcome.
        """
        assert compute_family_fingerprint(signal_b(blank)) is None


# --------------------------------------------------------------------------- B5: Signal A

class TestSignalA:
    def test_b5_same_side_same_period_is_stable(self):
        a = compute_family_fingerprint(signal_a("output"), period=PERIOD)
        b = compute_family_fingerprint(signal_a("output"), period=PERIOD)
        assert a == b

    def test_b5_output_and_input_differ(self):
        out = compute_family_fingerprint(signal_a("output"), period=PERIOD)
        inp = compute_family_fingerprint(signal_a("input"), period=PERIOD)
        assert out != inp, "the two sides are two different facts"

    def test_b5_same_side_different_period_differs(self):
        """THE NON-CARRY-FORWARD PIN. A per-side aggregate is a NEW fact each quarter, so a
        Q2 'known accepted' must never silently demote Q3's different divergence.

        Synthetic period shift — no fixture file is fabricated.
        """
        q2 = compute_family_fingerprint(signal_a("output"), period=PERIOD)
        q3 = compute_family_fingerprint(signal_a("output"), period=PERIOD_Q3)
        assert q2 != q3

    def test_b5_absent_period_yields_no_fingerprint(self):
        """Without the authoritative run period the key cannot be formed. None (visibly
        non-adjudicable) beats a period-less key that would carry forward forever.
        """
        assert compute_family_fingerprint(signal_a("output"), period=None) is None

    def test_b5_absent_side_yields_no_fingerprint(self):
        assert compute_family_fingerprint(signal_a(side=""), period=PERIOD) is None

    def test_b5_key_tuple_is_named_and_four(self):
        assert LEDGER_RECON_FINGERPRINT_KEYS == (
            "error_code",
            "side",
            "period_start",
            "period_end",
        )


# --------------------------------------------------------------------------- B6: amounts

class TestAmountInvariance:
    """Invariant (d): amounts NEVER enter a fingerprint. A divergence that grows between two
    runs is the SAME fact, so a decision on it must still re-apply.
    """

    def test_b6_document_family_ignores_amounts(self):
        base = compute_family_fingerprint(doc_check())
        assert base == compute_family_fingerprint(
            doc_check(extracted_value=999.99, listing_value=1.0, amount=42.0)
        )

    def test_b6_signal_a_ignores_amounts(self):
        base = compute_family_fingerprint(signal_a("output"), period=PERIOD)
        moved = compute_family_fingerprint(
            signal_a("output", ledger_gst=1.0, declared_gst=2.0, divergence=-1.0), period=PERIOD
        )
        assert base == moved

    def test_b6_signal_b_ignores_amounts(self):
        assert compute_family_fingerprint(signal_b()) == compute_family_fingerprint(
            signal_b(amount=99999.0)
        )


# --------------------------------------------------------------------------- cross-family

class TestNoCrossFamilyCollisions:
    def test_every_family_pair_is_disjoint(self):
        fps = {
            "e_check": compute_family_fingerprint(e_check()),
            "doc_check": compute_family_fingerprint(doc_check()),
            "signal_a_out": compute_family_fingerprint(signal_a("output"), period=PERIOD),
            "signal_a_in": compute_family_fingerprint(signal_a("input"), period=PERIOD),
            "signal_b": compute_family_fingerprint(signal_b()),
        }
        assert all(v is not None for v in fps.values()), fps
        assert len(set(fps.values())) == len(fps), f"cross-family collision: {fps}"

    def test_a_doc_check_never_collides_with_the_e_check_on_the_same_document(self):
        """Both families key on the same triple SHAPE, so disjointness rests on error codes
        being disjoint between families. BILL-3002 carries BOTH an E4 and a
        gst_amount_mismatch on the demo corpus — the realest collision candidate there is.
        """
        assert compute_family_fingerprint(
            e_check(code="E4", doc="BILL-3002")
        ) != compute_family_fingerprint(doc_check(check="gst_amount_mismatch", doc="BILL-3002"))

    def test_every_fingerprint_is_a_sha256_string(self):
        for f, kw in [
            (e_check(), {}),
            (doc_check(), {}),
            (signal_a("output"), {"period": PERIOD}),
            (signal_b(), {}),
        ]:
            fp = compute_family_fingerprint(f, **kw)
            assert isinstance(fp, str) and fp.startswith("sha256:") and len(fp) == 71


# --------------------------------------------------------------------------- values to hand-pin

def test_zz_print_values_for_hand_pinning(capsys):
    """Not an assertion — it PRINTS the computed values so Terry can hand-pin goldens.

    The agent does not author golden literals for its own build (it cannot move its own
    pins). Run with -s to read them.
    """
    rows = [
        ("E-check      E4 / BILL-3002 / OldRate Supplies Pte Ltd",
         compute_family_fingerprint(e_check())),
        ("doc-check    gst_amount_mismatch / BILL-3002 / OldRate Supplies Pte Ltd",
         compute_family_fingerprint(doc_check())),
        ("doc-check    correct_period / BILL-3009 / Bras Basah Print Pte Ltd",
         compute_family_fingerprint(doc_check(check="correct_period", doc="BILL-3009",
                                              card="Bras Basah Print Pte Ltd"))),
        ("Signal A     LEDGER_RECON / output / 2026-04-01..2026-06-30",
         compute_family_fingerprint(signal_a("output"), period=PERIOD)),
        ("Signal A     LEDGER_RECON / input  / 2026-04-01..2026-06-30",
         compute_family_fingerprint(signal_a("input"), period=PERIOD)),
        ("Signal B     NOT_INCLUDED / #14",
         compute_family_fingerprint(signal_b())),
    ]
    with capsys.disabled():
        print("\n  --- Slice B fingerprints AWAITING TERRY'S HAND-PINS ---")
        for label, fp in rows:
            print(f"    {label:<66} {fp}")
    assert all(fp for _, fp in rows)
