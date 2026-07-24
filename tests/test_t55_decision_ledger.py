"""
tests/test_t55_decision_ledger.py — T5.5 decision-ledger PURE CORE.

Proves the four Invariant-5 properties STRUCTURALLY (not by convention):
  (a) Append-only / tamper-evident   — verify() clean; any mutation breaks it; no edit/delete API.
  (b) Never-suppress (cardinality)   — annotate_and_demote output length == input length, always.
  (c) Never-train (pure read)        — same input -> same output; ledger untouched during read.
  (d) Deterministic fingerprint      — same finding -> same fp; v1 key is
                                       (error_code, counterparty, doc_num); amount still excluded.
PLUS agent-cannot-write (Tier-3/absent) and box-isolation (presentation metadata only).

RULE-AUTHOR AMENDMENT (t-fingerprint-v1, hand-authored — separation of duties).
The v0 key was (error_code, counterparty) ONLY, which was DEGENERATE: two documents from
one supplier carrying the same error hashed identically, so one adjudication swept both.
That is the modal real-world defect (a wrong tax code defaulted on a supplier master
propagates to every invoice from that supplier). doc_num joined the key under
D-2026-07-24-fingerprint-v1. The former defect-asserting test below is INVERTED, not
retired — it is now the fix-witness.

No SDK, no SAP, no network. Fully hermetic.
"""
from __future__ import annotations

import copy

import pytest

from agent.decision_ledger import (
    ACCEPTED,
    DEMOTE_DISPOSITIONS,
    FINGERPRINT_KEYS,
    KNOWN_ACCEPTED,
    REJECTED,
    AdjudicationEntry,
    AnnotatedFinding,
    DecisionLedger,
    DecisionLedgerVerificationError,
    annotate_and_demote,
    compute_finding_fingerprint,
)
from agent.dossier import Finding, extract_findings


def _finding(error_code: str, card_name: str, doc_num: int = 1, **extra) -> Finding:
    payload = {"error_code": error_code, "card_name": card_name, "doc_num": doc_num}
    payload.update(extra)
    return Finding(
        finding_id=f"detect:{error_code}:{doc_num}",
        check_id=error_code,
        finding_type="deterministic",
        source="compile_output.detect",
        payload=payload,
    )


def _adjudicate(ledger: DecisionLedger, finding: Finding, disposition: str,
                reviewer: str = "collin", reason: str = "reviewed", period: str = "2024Q3"):
    return ledger.append(
        fingerprint=compute_finding_fingerprint(finding),
        disposition=disposition,
        reviewer=reviewer,
        reason=reason,
        period=period,
    )


# ---------------------------------------------------------------------------
# (d) Deterministic fingerprint
# ---------------------------------------------------------------------------

class TestFingerprintDeterminism:
    def test_same_finding_same_fp(self):
        f = _finding("E1", "SG Electronics", 974)
        assert compute_finding_fingerprint(f) == compute_finding_fingerprint(f)

    def test_fp_is_sha256_prefixed(self):
        assert compute_finding_fingerprint(_finding("E1", "SG Electronics")).startswith("sha256:")

    def test_doc_num_included_documents_key_separately(self):
        # t-fingerprint-v1 (INVERTED from test_doc_num_excluded_recurrence_matches).
        # Different doc_num, same (error_code, counterparty) -> DIFFERENT fp. Under v0
        # these collided, so a single adjudication on one document silently swept the
        # other — the defect this build exists to kill. Cross-period recurrence of the
        # SAME document still matches (same doc_num -> same key).
        a = _finding("E1", "SG Electronics", 974)
        b = _finding("E1", "SG Electronics", 958)
        assert compute_finding_fingerprint(a) != compute_finding_fingerprint(b)

    def test_same_doc_num_recurrence_still_matches(self):
        # The property v0 was reaching for, correctly scoped: the SAME document seen
        # again (e.g. next period's export) keys identically, so a standing
        # adjudication on that document still re-applies.
        a = _finding("E1", "SG Electronics", 974)
        b = _finding("E1", "SG Electronics", 974, line_total=99.0)
        assert compute_finding_fingerprint(a) == compute_finding_fingerprint(b)

    def test_amount_excluded_same_fp(self):
        # v1 key still excludes amount: two different magnitudes -> SAME fp (by design).
        a = _finding("E1", "SG Electronics", 974, line_total=35310.0)
        b = _finding("E1", "SG Electronics", 974, line_total=8.03)
        assert compute_finding_fingerprint(a) == compute_finding_fingerprint(b)

    def test_counterparty_normalized(self):
        a = _finding("E1", "SG Electronics")
        b = _finding("E1", "  sg electronics  ")
        assert compute_finding_fingerprint(a) == compute_finding_fingerprint(b)
        # R2b (t-fingerprint-v1): INTERNAL whitespace runs collapse too, not just the
        # ends. Under v0 "SG   Electronics" keyed differently from "SG Electronics",
        # so one stray space in next quarter's export orphaned every standing
        # adjudication for that supplier.
        c = _finding("E1", "SG   Electronics")
        assert compute_finding_fingerprint(a) == compute_finding_fingerprint(c)

    def test_different_error_code_different_fp(self):
        a = _finding("E1", "SG Electronics")
        b = _finding("E2", "SG Electronics")
        assert compute_finding_fingerprint(a) != compute_finding_fingerprint(b)

    def test_different_counterparty_different_fp(self):
        a = _finding("E1", "SG Electronics")
        b = _finding("E1", "Aquent Systems")
        assert compute_finding_fingerprint(a) != compute_finding_fingerprint(b)

    def test_fp_keys_are_the_documented_constant(self):
        assert FINGERPRINT_KEYS == ("error_code", "counterparty", "doc_num")

    def test_fp_accepts_plain_payload_dict(self):
        f = _finding("E1", "SG Electronics", 974)
        # A bare payload dict fingerprints identically to the Finding it came from.
        assert compute_finding_fingerprint(f.payload) == compute_finding_fingerprint(f)


# ---------------------------------------------------------------------------
# (a) Append-only / tamper-evident
# ---------------------------------------------------------------------------

class TestAppendOnlyTamperEvident:
    def test_empty_verifies(self):
        DecisionLedger().verify()

    def test_chain_verifies(self):
        led = DecisionLedger()
        for d in (ACCEPTED, REJECTED, KNOWN_ACCEPTED, ACCEPTED):
            _adjudicate(led, _finding("E1", "SG Electronics"), d)
        led.verify()

    def test_mutate_disposition_breaks_verify(self):
        led = DecisionLedger()
        _adjudicate(led, _finding("E1", "SG Electronics"), ACCEPTED)
        _adjudicate(led, _finding("E2", "Acme Associates"), REJECTED)
        led.entries[0].disposition = KNOWN_ACCEPTED
        with pytest.raises(DecisionLedgerVerificationError):
            led.verify()

    def test_mutate_fingerprint_breaks_verify(self):
        led = DecisionLedger()
        _adjudicate(led, _finding("E1", "SG Electronics"), ACCEPTED)
        led.entries[0].fingerprint = "sha256:" + "f" * 64
        with pytest.raises(DecisionLedgerVerificationError):
            led.verify()

    def test_delete_middle_entry_breaks_verify(self):
        led = DecisionLedger()
        for d in (ACCEPTED, REJECTED, KNOWN_ACCEPTED):
            _adjudicate(led, _finding("E1", "SG Electronics"), d)
        del led.entries[1]
        with pytest.raises(DecisionLedgerVerificationError):
            led.verify()

    def test_no_edit_or_delete_api(self):
        # STRUCTURAL: the ledger exposes append/verify/lookup/from_entries only — no mutators.
        public = {n for n in dir(DecisionLedger) if not n.startswith("_")}
        assert not (public & {"edit", "update", "delete", "remove", "pop", "set"})

    def test_unknown_disposition_rejected(self):
        led = DecisionLedger()
        with pytest.raises(ValueError):
            led.append(fingerprint="sha256:" + "0" * 64, disposition="MAYBE", reviewer="x")

    def test_from_entries_roundtrip_verifies(self):
        led = DecisionLedger()
        for d in (ACCEPTED, KNOWN_ACCEPTED):
            _adjudicate(led, _finding("E1", "SG Electronics"), d)
        dumped = [vars(e) for e in led.entries]
        DecisionLedger.from_entries(dumped).verify()


# ---------------------------------------------------------------------------
# (b) Never-suppress — cardinality-preserving (STRUCTURAL)
# ---------------------------------------------------------------------------

class TestNeverSuppress:
    def test_output_length_equals_input_no_priors(self):
        findings = [_finding("E1", "A"), _finding("E2", "B"), _finding("NO_GST_REG", "C")]
        out = annotate_and_demote(findings, DecisionLedger())
        assert len(out) == len(findings)

    def test_every_finding_known_accepted_still_all_present(self):
        findings = [_finding("E1", "A", 1), _finding("E1", "A", 2), _finding("E2", "B", 3)]
        led = DecisionLedger()
        for f in findings:
            _adjudicate(led, f, KNOWN_ACCEPTED)
        out = annotate_and_demote(findings, led)
        # Cardinality preserved AND every output is demoted but still present.
        # Note (t-fingerprint-v1): under v1 the first two findings key SEPARATELY, so
        # all three demote because all three were individually adjudicated — not
        # because one adjudication swept two documents.
        assert len(out) == len(findings)
        assert all(a.demoted for a in out)
        assert all(isinstance(a, AnnotatedFinding) for a in out)

    def test_demoted_finding_carries_original(self):
        f = _finding("E1", "SG Electronics", 974)
        led = DecisionLedger()
        _adjudicate(led, f, KNOWN_ACCEPTED)
        [a] = annotate_and_demote([f], led)
        assert a.finding is f
        assert a.demoted is True
        assert a.annotation  # non-empty annotation text

    def test_empty_findings_empty_output(self):
        assert annotate_and_demote([], DecisionLedger()) == []


# ---------------------------------------------------------------------------
# annotate/demote semantics by disposition (v0 vocab)
# ---------------------------------------------------------------------------

class TestDispositionSemantics:
    def test_known_accepted_demotes(self):
        f = _finding("E1", "A")
        led = DecisionLedger()
        _adjudicate(led, f, KNOWN_ACCEPTED)
        assert annotate_and_demote([f], led)[0].demoted is True

    def test_accepted_annotates_only(self):
        f = _finding("E1", "A")
        led = DecisionLedger()
        _adjudicate(led, f, ACCEPTED)
        a = annotate_and_demote([f], led)[0]
        assert a.demoted is False
        assert a.annotation  # annotated, not demoted

    def test_rejected_annotates_only(self):
        f = _finding("E1", "A")
        led = DecisionLedger()
        _adjudicate(led, f, REJECTED)
        a = annotate_and_demote([f], led)[0]
        assert a.demoted is False
        assert a.annotation

    def test_no_prior_no_annotation_no_demote(self):
        a = annotate_and_demote([_finding("E1", "A")], DecisionLedger())[0]
        assert a.demoted is False
        assert a.annotation is None
        assert a.prior_dispositions == ()

    def test_demote_trigger_set_is_known_accepted_only(self):
        assert DEMOTE_DISPOSITIONS == frozenset({KNOWN_ACCEPTED})


# ---------------------------------------------------------------------------
# (c) Never-train — pure read, no mutation
# ---------------------------------------------------------------------------

class TestNeverTrain:
    def test_same_input_same_output(self):
        findings = [_finding("E1", "A"), _finding("E2", "B")]
        led = DecisionLedger()
        _adjudicate(led, findings[0], KNOWN_ACCEPTED)
        r1 = annotate_and_demote(findings, led)
        r2 = annotate_and_demote(findings, led)
        assert [(a.fingerprint, a.demoted, a.annotation) for a in r1] == \
               [(a.fingerprint, a.demoted, a.annotation) for a in r2]

    def test_ledger_untouched_during_read(self):
        led = DecisionLedger()
        _adjudicate(led, _finding("E1", "A"), KNOWN_ACCEPTED)
        before = copy.deepcopy(led.entries)
        annotate_and_demote([_finding("E1", "A"), _finding("E2", "B")], led)
        assert led.entries == before
        led.verify()  # chain still intact after a read

    def test_lookup_returns_fresh_list(self):
        led = DecisionLedger()
        f = _finding("E1", "A")
        _adjudicate(led, f, ACCEPTED)
        got = led.lookup(compute_finding_fingerprint(f))
        got.clear()  # mutating the returned list must not affect the ledger
        led.verify()
        assert len(led.entries) == 1


# ---------------------------------------------------------------------------
# Box-isolation — presentation metadata only
# ---------------------------------------------------------------------------

class TestBoxIsolation:
    def _compile_output(self) -> dict:
        return {
            "calculate": {"boxes": {"box_1_standard_rated_sales": 369589.97, "box_8_net_gst": 12663.87}},
            "detect": {"issues": [
                {"severity": "HIGH", "error_code": "E1", "doc_num": 974,
                 "doc_date": "2024-07-11", "card_name": "SG Electronics",
                 "description": "...", "recommendation": "..."},
                {"severity": "MEDIUM", "error_code": "E2", "doc_num": 605,
                 "doc_date": "2024-07-15", "card_name": "Acme Associates",
                 "description": "...", "recommendation": "..."},
            ]},
        }

    def test_findings_and_compile_output_byte_unchanged(self):
        compile_output = self._compile_output()
        findings = extract_findings({"compile_output": compile_output})
        co_snapshot = copy.deepcopy(compile_output)
        findings_snapshot = copy.deepcopy(findings)

        led = DecisionLedger()
        _adjudicate(led, findings[0], KNOWN_ACCEPTED)
        out = annotate_and_demote(findings, led)

        # F5 boxes + detect issues untouched; findings untouched.
        assert compile_output == co_snapshot
        assert findings == findings_snapshot
        # The annotated wrappers reference the SAME finding objects (no copy/mutate).
        assert all(out[i].finding is findings[i] for i in range(len(findings)))


# ---------------------------------------------------------------------------
# Agent-cannot-write (Tier-3 / absent) ; read helper, if any, is Tier-0
# ---------------------------------------------------------------------------

class TestAgentCannotWrite:
    def test_no_decision_ledger_write_tool_in_registry(self):
        from agent.registry import REGISTRY, get_tier
        from agent.schemas import Tier
        names = set(REGISTRY)
        # A decision-ledger WRITE is Tier-2 — the agent never writes it, so no
        # adjudication-write tool may exist in the agent registry.
        assert not any("adjudicat" in n for n in names)
        # A decision-ledger READ helper IS permitted, but only at Tier-0 (the
        # section invariant: "read helper, if any, is Tier-0"). T5.9a1 added the
        # Tier-0 read_decision_ledger; assert any decision_ledger-named tool is a
        # read at Tier-0, never a write.
        for n in names:
            if "decision_ledger" in n:
                assert n.startswith("read_"), (
                    f"{n!r}: only a Tier-0 READ of the decision ledger is allowed"
                )
                assert get_tier(n) is Tier.ZERO

    def test_write_tool_is_tier_three_for_agent(self):
        from agent.registry import get_tier
        from agent.schemas import Tier
        assert get_tier("record_adjudication") == Tier.THREE
