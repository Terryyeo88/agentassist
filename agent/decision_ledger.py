"""
agent/decision_ledger.py — Append-only decision ledger of human reviewer adjudications.

The decision ledger is the system's institutional memory of human reviewer
adjudications, keyed by a DETERMINISTIC finding fingerprint. Its only behaviours are
ANNOTATE and DEMOTE on recurrence, governed by Invariant 5: NEVER suppress, NEVER
train. Known-accepted recurring findings render annotated and demoted — never hidden.

Tier placement (registry + Invariant 5): a decision-ledger WRITE is a Tier-2 action,
so the AGENT never writes it — a human reviewer's adjudication drives a DETERMINISTIC
write (a future executor handler, NOT wired here). The agent may only READ the ledger
(Tier 0). No decision-ledger tool exists in the agent registry, so for the agent it is
Tier-3/absent (get_tier() -> Tier.THREE). This module is the PURE HERMETIC CORE only —
fingerprint + append-only hash-chained ledger + annotate-and-demote read logic — NOT
the loop/demo/executor wiring (that is a follow-on slice).

THE FINGERPRINT KEY (v0/PROVISIONAL — flag for Collin/specialist)
----------------------------------------------------------------
The roadmap's nominal key was ``(error_code, VatGroup, CardCode, amount band)``. That
list PREDATES the real finding shape: a ``compile_output.detect.issues`` entry (the
finding surface, via agent.dossier.extract_findings) carries only
``error_code`` + ``card_name`` — it does NOT carry ``vat_group``, a structured
``card_code``, or any amount (those are dropped at the detect layer; they live upstream
in ``classify.issues`` and would require the deferred classify<->detect reconciliation
noted in orchestrator/steps.py:438-440).

The v0 key was the minimal recurrence key over (error_code, counterparty) — and it
proved DEGENERATE: two documents from one supplier with the same error shared one key,
so one adjudication swept both (the modal real-world defect: a wrong tax code on a
supplier master propagating to every invoice from that supplier). v1 therefore widens
the key (D-2026-07-24-fingerprint-v1):

    FINGERPRINT_KEYS = ("error_code", "counterparty", "doc_num")

``doc_num`` now JOINS the key, canonicalized str(doc_num).strip() (absent -> "" — see
_normalize_doc_num; never int()-coerced, never casefolded). Cross-period recurrence of
the SAME document still matches (amount excluded); different documents no longer sweep
each other. v0 entries (fingerprint_version absent) are INERT under v1 — by
construction, not by gate — and the non-application is surfaced via
count_superseded_entries().

Rationale for the v0 coarse posture (historical): given never-suppress + mandatory
human adjudication, an over-broad demote (still fully visible, human still adjudicates)
was judged safer than a narrow
key (e.g. amount-in-key -> cross-band brittleness -> MISSED recurrences). Enrichment
priority for the specialist: (1) VatGroup — clean categorical discriminator, needs the
reconciliation built first; (2) CardCode replacing card_name; (3) amount_band — last and
most contested (recall-vs-magnitude-scope tradeoff; needs reconciliation + a banding
policy + a multi-line-collapse aggregation policy). NONE built here.

HONEST LIMITATION (v0): without amount in the key, a known-accepted pattern carries
forward regardless of magnitude — a sudden large instance renders DEMOTED (still
visible, never suppressed, human still adjudicates), not re-promoted. That
magnitude-scoping is exactly why amount_band is on the enrichment list.

Hash construction mirrors agent/ledger.py (same canonical-JSON + sha256 primitive):
    genesis prev_hash = "sha256:" + "0" * 64
    entry_hash[n] = sha256( canonical_json(entry_fields_without_hash) + b"|" + prev_hash )
The fingerprint reuses agent.proposals.compute_inputs_hash — the single shared
anchoring primitive (sha256 over canonical JSON).

Zero anthropic import. Zero SDK import. Stdlib only (hashlib, json, uuid, datetime).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from agent.proposals import compute_inputs_hash

# --- Disposition vocabulary (v0/PROVISIONAL — flag for Collin/specialist) ---
ACCEPTED = "ACCEPTED"            # genuine error accepted this period -> annotate-only
REJECTED = "REJECTED"           # judged false positive -> annotate-only (demote-behaviour provisional)
KNOWN_ACCEPTED = "KNOWN_ACCEPTED"  # standing accepted treatment -> DEMOTE + annotate on recurrence

#: The full controlled set of valid dispositions.
DISPOSITIONS = frozenset({ACCEPTED, REJECTED, KNOWN_ACCEPTED})

#: Disposition(s) that trigger DEMOTE on recurrence (Invariant 5). v0: KNOWN_ACCEPTED only.
DEMOTE_DISPOSITIONS = frozenset({KNOWN_ACCEPTED})

#: The fingerprint key set — v1 (D-2026-07-24-fingerprint-v1). doc_num joined the key
#: because the v0 pair (error_code, counterparty) was DEGENERATE: two documents from
#: one supplier carrying the same error shared one key, so one adjudication swept
#: both — the modal real-world defect (a wrong tax code defaulted on a supplier
#: master propagates to every invoice from that supplier). Proven at the fingerprint
#: layer 2026-07-24; the engine-path double-proof was honestly skipped.
FINGERPRINT_KEYS = ("error_code", "counterparty", "doc_num")

#: The CURRENT fingerprint algorithm version, stamped on every NEW AdjudicationEntry
#: (Terry R4: HASHED into entry_hash for new entries). Records with the field ABSENT
#: are v0 by definition — see entry_fingerprint_version(), the one place that rule
#: is named.
FINGERPRINT_VERSION = "v1"

_GENESIS_HASH = "sha256:" + "0" * 64


# ---------------------------------------------------------------------------
# Canonical primitives — mirror agent/ledger.py (same rules as audit_bundle.canonical)
# ---------------------------------------------------------------------------

def _canonical_json(obj: dict) -> bytes:
    """Deterministic JSON bytes — same rules as agent.ledger / audit_bundle.canonical."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _compute_entry_hash(entry_fields: dict, prev_hash: str) -> str:
    """Compute entry_hash = sha256( canonical_json(fields) + b"|" + prev_hash )."""
    payload = _canonical_json(entry_fields) + b"|" + prev_hash.encode("utf-8")
    return _sha256_bytes(payload)


# ---------------------------------------------------------------------------
# Fingerprint — DETERMINISTIC, not AI; a PURE function of the finding
# ---------------------------------------------------------------------------

def _normalize_counterparty(card_name: Any) -> str:
    """Normalize a counterparty name: collapse ALL whitespace runs + casefold.

    R2b (t-fingerprint-v1): v0 only strip()ed the ends, so "OldRate  Supplies"
    (two internal spaces) keyed differently from "OldRate Supplies" — same defect
    class as the doc_num degeneracy, fixed in the same key change. " ".join(split())
    collapses internal runs AND strips ends.
    """
    return " ".join(("" if card_name is None else str(card_name)).split()).casefold()


#: R2 (t-fingerprint-v1): the EXPLICIT canonical form for an ABSENT doc_num — the
#: empty string, NEVER str(None). Named so absence is a deliberate value, not an
#: accident of coercion.
_ABSENT_DOC_NUM = ""


def _normalize_doc_num(doc_num: Any) -> str:
    """Canonical doc_num for the v1 key: str(doc_num).strip(); absent -> "".

    R2 (Terry): document numbers are IDENTIFIERS — no casefold (failing-to-reapply
    is the honest failure; wrongly-reapplying is the defect) and NEVER int()-coerced
    (the #34 pattern silently changes hash inputs). str-canonical means the same
    document reached via the extract path (int 605) and a string path ("605")
    produces one key.
    """
    if doc_num is None:
        return _ABSENT_DOC_NUM
    return str(doc_num).strip()


def _fingerprint_fields(finding: Any) -> dict:
    """Extract the v0 fingerprint fields from a Finding (or a bare payload/dict).

    PURE: reads only the finding itself — NO compile_output, NO reconciliation.
    Accepts a ``agent.dossier.Finding``, a raw detect-issue payload dict, or a dict
    carrying a ``payload`` key.
    """
    if isinstance(finding, dict):
        payload = finding.get("payload", finding)
        check_id = finding.get("check_id")
    else:
        payload = getattr(finding, "payload", None)
        check_id = getattr(finding, "check_id", None)
    payload = payload or {}

    error_code = payload.get("error_code")
    if error_code is None:
        error_code = check_id
    return {
        "error_code": "" if error_code is None else str(error_code).strip(),
        "counterparty": _normalize_counterparty(payload.get("card_name")),
        "doc_num": _normalize_doc_num(payload.get("doc_num")),
    }


def compute_finding_fingerprint(finding: Any) -> str:
    """Return "sha256:..." over the canonical v1 key for *finding*.

    DETERMINISTIC, not AI. The key is exactly ``FINGERPRINT_KEYS`` — error_code +
    normalized counterparty + canonical doc_num — anchored via the shared
    ``compute_inputs_hash`` primitive (sha256 over canonical JSON). Same finding ->
    same fingerprint; two documents from one supplier with the same error now key
    SEPARATELY (the v0 degeneracy is dead). Findings differing only in amount still
    share a key (cross-period recurrence of the SAME document, by design).
    """
    fields = _fingerprint_fields(finding)
    keyed = {k: fields[k] for k in FINGERPRINT_KEYS}
    return compute_inputs_hash(keyed)


# ---------------------------------------------------------------------------
# Slice B — the FAMILY -> identity-key map (PROPOSED D-2026-09-20-slice-b-adjudicable-rows)
# ---------------------------------------------------------------------------
#
# Before Slice B, three row families reached the reviewer with ``fingerprint: None`` and so
# could not be accepted, declined or marked at all — 7 of the 16 rows on the demo corpus. The
# stated reason (#46) was "these rows carry no counterparty". That premise assumed every
# fingerprint must key on a counterparty; retiring it is what makes those rows adjudicable.
#
# The dispatch below gives each family its OWN key set. Because the hash is taken over a
# canonical-JSON dict of exactly the keys a family declares, a family with a different key set
# produces a different dict and therefore a different hash — and, decisively, the E-check
# family's dict is UNTOUCHED, so every existing fingerprint stays byte-identical.
# ``FINGERPRINT_KEYS`` is NOT widened and ``FINGERPRINT_VERSION`` is NOT bumped: the new
# families never had fingerprints, so there is nothing to migrate and no stored decision is
# orphaned.
#
# Returning None is a first-class outcome, not a failure: a row whose family cannot form its
# key stays visibly non-adjudicable rather than collapsing onto a shared key that one
# adjudication could sweep.

#: Signal A (GST_LEDGER_RECON) keys on the PERIOD as well as the side. A per-side divergence is
#: an AGGREGATE over a whole control account, not a document — a new fact every quarter. Keyed
#: without the period, a Q2 "known accepted" would silently demote Q3's different divergence.
LEDGER_RECON_FINGERPRINT_KEYS = ("error_code", "side", "period_start", "period_end")

_LEDGER_RECON_DIVERGENCE = "ledger_recon_divergence"
_NOT_INCLUDED_DROP = "not_included_gst_drop"


def _period_bounds(period: Any) -> tuple[str, str]:
    """Return (start, end) from a run period dict; ("", "") when unusable.

    The period is the AUTHORITATIVE run period (``compile_output["period"]``), never parsed
    out of a description string — prose is not a contract.
    """
    if not isinstance(period, dict):
        return "", ""
    return str(period.get("start") or "").strip(), str(period.get("end") or "").strip()


def compute_family_fingerprint(finding: Any, period: Any = None) -> str | None:
    """Return the family-keyed "sha256:..." fingerprint for *finding*, or None.

    ONE function for BOTH the write path (serialization) and the re-apply path
    (``annotate_and_demote``): a decision can only re-apply if the fingerprint recomputed at
    read time equals the one recorded at write time, so the two must never diverge.

    Dispatch:
      * Signal A (``finding_type == "ledger_recon_divergence"``) ->
        (error_code, side, period_start, period_end). None without a side or a period.
      * Signal B (``finding_type == "not_included_gst_drop"``) -> the v1 triple with the
        journal reference in the doc_num slot and the named-empty counterparty. None when the
        reference is blank (Terry, ruling 3) — a blank Xero Reference is real data, and one
        shared key across every such row is exactly the sweep defect.
      * Everything else (E-checks AND the four document checks) -> the UNCHANGED v1 triple via
        ``compute_finding_fingerprint``. Document checks keep the counterparty (Terry, ruling
        1): Xero bill numbers can collide across suppliers, so dropping it risks one decision
        sweeping two suppliers' bills. A join miss normalises to the named empty form, which
        fails to re-apply (honest) rather than re-applying wrongly (the defect).

    ``period`` is accepted for every family but consumed ONLY by Signal A, so passing it is
    always safe and never leaks into a family that does not key on it.
    """
    ftype = finding.get("finding_type") if isinstance(finding, dict) else getattr(
        finding, "finding_type", None
    )

    if ftype == _LEDGER_RECON_DIVERGENCE:
        side = str(finding.get("side") or "").strip()
        start, end = _period_bounds(period)
        if not side or not start or not end:
            return None
        code = str(finding.get("error_code") or "LEDGER_RECON").strip()
        keyed = dict(zip(
            LEDGER_RECON_FINGERPRINT_KEYS, (code, side, start, end)
        ))
        return compute_inputs_hash(keyed)

    if ftype == _NOT_INCLUDED_DROP:
        reference = str(finding.get("reference") or "").strip()
        if not reference:
            return None
        code = str(finding.get("error_code") or "NOT_INCLUDED").strip()
        # Routed through the SAME triple builder so the canonicalisation rules (str().strip()
        # on the identifier, never int(); the named empty counterparty) are shared, not
        # re-implemented.
        return compute_finding_fingerprint(
            {"error_code": code, "card_name": None, "doc_num": reference}
        )

    return compute_finding_fingerprint(finding)


# ---------------------------------------------------------------------------
# Append-only hash-chained ledger — mirrors agent/ledger.py; no edit/delete API
# ---------------------------------------------------------------------------

@dataclass
class AdjudicationEntry:
    """One human reviewer adjudication, chained into the decision ledger.

    Attributes:
        entry_id:    Stable unique id for this entry.
        fingerprint: The deterministic finding fingerprint this adjudication keys on.
        disposition: One of DISPOSITIONS (ACCEPTED / REJECTED / KNOWN_ACCEPTED).
        reviewer:    Identifier of the human reviewer who adjudicated.
        reason:      Free-text rationale (optional).
        period:      The audit period the adjudication was made in (optional).
        timestamp:   ISO-8601 timestamp of the adjudication.
        prev_hash:   entry_hash of the previous entry (genesis for the first).
        entry_hash:  sha256 over the entry fields + prev_hash (the chain link).
        fingerprint_version: The fingerprint algorithm version this entry's key was
                     computed under. None means the entry predates versioning — v0
                     BY DEFINITION (see entry_fingerprint_version()). Stamped
                     FINGERPRINT_VERSION on every new append; HASHED for versioned
                     entries (Terry R4).
    """
    entry_id: str
    fingerprint: str
    disposition: str
    reviewer: str
    reason: Optional[str]
    period: Optional[str]
    timestamp: str
    prev_hash: str
    entry_hash: str
    fingerprint_version: Optional[str] = None


def entry_fingerprint_version(entry: Any) -> str:
    """THE absent==v0 rule, named in one place (Terry R1/R4: explicit, never implicit).

    A record with no ``fingerprint_version`` field (or None) was written before
    versioning existed — its key was computed under the superseded v0 composition.
    Accepts an AdjudicationEntry or a stored record dict.
    """
    if isinstance(entry, dict):
        version = entry.get("fingerprint_version")
    else:
        version = getattr(entry, "fingerprint_version", None)
    return "v0" if version is None else str(version)


def count_superseded_entries(entries: Any) -> int:
    """Count stored adjudications whose fingerprint version is SUPERSEDED (Terry R1).

    These entries are INERT: their keys were computed under an older composition, so
    they can never match a finding keyed under FINGERPRINT_VERSION — deliberately
    (applying a v0 entry forward would re-import the very sweep-collision v1 fixes).
    The count is surfaced as DATA (nothing renders) so the non-application is never
    silent: a reviewer can see how many stored decisions no longer apply.
    """
    return sum(
        1 for e in entries
        if entry_fingerprint_version(e) != FINGERPRINT_VERSION
    )


def _entry_fields_without_hash(entry: AdjudicationEntry) -> dict:
    """Return the entry fields that are inputs to entry_hash (excludes entry_hash).

    ABSENCE-AWARE HASHING (Terry R4): a v0 entry (fingerprint_version None) hashes
    over the HISTORICAL field-set WITHOUT the version key, so historical entry_hash
    values remain UNCHANGED LITERALS. A versioned entry includes the field, making
    the version itself tamper-evident.
    """
    fields = {
        "disposition": entry.disposition,
        "entry_id": entry.entry_id,
        "fingerprint": entry.fingerprint,
        "period": entry.period,
        "prev_hash": entry.prev_hash,
        "reason": entry.reason,
        "reviewer": entry.reviewer,
        "timestamp": entry.timestamp,
    }
    if entry.fingerprint_version is not None:
        fields["fingerprint_version"] = entry.fingerprint_version
    return fields


class DecisionLedgerVerificationError(Exception):
    """Raised by DecisionLedger.verify() when the chain is broken or a hash mismatches."""


class DecisionLedger:
    """Append-only in-memory hash-chained ledger of reviewer adjudications.

    Entries are never edited, deleted, or reordered — there is intentionally NO
    edit/delete API. verify() re-derives every entry_hash and checks the chain; any
    mutation (field change or entry deletion) raises DecisionLedgerVerificationError.
    """

    def __init__(self) -> None:
        self.entries: list[AdjudicationEntry] = []

    def append(
        self,
        *,
        fingerprint: str,
        disposition: str,
        reviewer: str,
        reason: Optional[str] = None,
        period: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> AdjudicationEntry:
        """Append a new adjudication and return it.

        Raises ValueError if *disposition* is not in the controlled DISPOSITIONS set —
        the vocabulary is structural, not advisory.
        """
        if disposition not in DISPOSITIONS:
            raise ValueError(
                f"disposition {disposition!r} not in controlled set {sorted(DISPOSITIONS)}"
            )
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        prev_hash = self.entries[-1].entry_hash if self.entries else _GENESIS_HASH

        fields = {
            "disposition": disposition,
            "entry_id": str(uuid.uuid4()),
            "fingerprint": fingerprint,
            # R4: every NEW entry is stamped with the current algorithm version, and
            # the field is HASHED (tamper-evident). v0 entries hash without it —
            # see _entry_fields_without_hash's absence-aware rule.
            "fingerprint_version": FINGERPRINT_VERSION,
            "period": period,
            "prev_hash": prev_hash,
            "reason": reason,
            "reviewer": reviewer,
            "timestamp": ts,
        }
        entry_hash = _compute_entry_hash(fields, prev_hash)

        entry = AdjudicationEntry(
            entry_id=fields["entry_id"],
            fingerprint=fields["fingerprint"],
            disposition=fields["disposition"],
            reviewer=fields["reviewer"],
            reason=fields["reason"],
            period=fields["period"],
            timestamp=fields["timestamp"],
            prev_hash=fields["prev_hash"],
            entry_hash=entry_hash,
            fingerprint_version=FINGERPRINT_VERSION,
        )
        self.entries.append(entry)
        return entry

    def verify(self) -> None:
        """Re-derive every entry_hash and verify the chain.

        Raises DecisionLedgerVerificationError if any entry_hash is wrong or the
        prev_hash chain is broken (including entries deleted from the middle).
        """
        prev_hash = _GENESIS_HASH
        for i, entry in enumerate(self.entries):
            fields = _entry_fields_without_hash(entry)
            expected_hash = _compute_entry_hash(fields, prev_hash)
            if entry.entry_hash != expected_hash:
                raise DecisionLedgerVerificationError(
                    f"entry[{i}] entry_hash mismatch: "
                    f"stored={entry.entry_hash!r}, expected={expected_hash!r}"
                )
            if entry.prev_hash != prev_hash:
                raise DecisionLedgerVerificationError(
                    f"entry[{i}] prev_hash chain broken: "
                    f"stored={entry.prev_hash!r}, expected={prev_hash!r}"
                )
            prev_hash = entry.entry_hash

    def lookup(self, fingerprint: str) -> list[AdjudicationEntry]:
        """Return all prior entries for *fingerprint*, oldest first.

        A PURE READ — returns a fresh list; mutating it does not affect the ledger.
        """
        return [e for e in self.entries if e.fingerprint == fingerprint]

    @classmethod
    def from_entries(cls, entries: list[dict]) -> "DecisionLedger":
        """Reconstruct a DecisionLedger from serialised entry dicts (for verify())."""
        ledger = cls()
        for d in entries:
            ledger.entries.append(AdjudicationEntry(
                entry_id=d["entry_id"],
                fingerprint=d["fingerprint"],
                disposition=d["disposition"],
                reviewer=d["reviewer"],
                reason=d["reason"],
                period=d["period"],
                timestamp=d["timestamp"],
                prev_hash=d["prev_hash"],
                entry_hash=d["entry_hash"],
                # ABSENCE PRESERVED (R4): a legacy line without the key stays None
                # (== v0), so its historical entry_hash re-derives unchanged.
                fingerprint_version=d.get("fingerprint_version"),
            ))
        return ledger


# ---------------------------------------------------------------------------
# Annotate-and-demote — PRESENTATION metadata only; cardinality-preserving
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnnotatedFinding:
    """A finding decorated with decision-ledger context — PRESENTATION metadata only.

    The original ``finding`` is referenced unchanged (never copied or mutated): this is
    how box-isolation is kept structural. ``demoted`` lowers render prominence; the
    finding is NEVER dropped (never-suppress).

    Attributes:
        finding:            The original finding object, byte-unchanged.
        fingerprint:        The finding's deterministic fingerprint, or None when its family
                            cannot form a key (Slice B: a blank Signal B journal reference, or
                            Signal A without a run period). None means "not adjudicable",
                            never "collapse onto a shared key".
        demoted:            True iff a prior KNOWN_ACCEPTED adjudication exists.
        annotation:         Reviewer-context text, or None if no prior adjudication.
        prior_dispositions: Tuple of prior dispositions (oldest first), () if none.
    """
    finding: Any
    fingerprint: Optional[str]
    demoted: bool
    annotation: Optional[str]
    prior_dispositions: tuple


def _build_annotation(priors: list[AdjudicationEntry]) -> str:
    """Build human-readable annotation text from prior adjudications."""
    last = priors[-1]
    period = f" ({last.period})" if last.period else ""
    return (
        f"Previously adjudicated {len(priors)} time(s); "
        f"most recent: {last.disposition} by {last.reviewer}{period}."
    )


def annotate_and_demote(
    findings: list, ledger: DecisionLedger, period: Any = None
) -> list[AnnotatedFinding]:
    """Decorate each finding with decision-ledger context — a PURE READ.

    CARDINALITY-PRESERVING: returns exactly one AnnotatedFinding per input finding, in
    order. This is how "never suppress" is made STRUCTURAL — no code path drops a
    finding. A finding with a prior KNOWN_ACCEPTED adjudication is annotated and
    ``demoted=True`` but STILL PRESENT; every finding renders.

    Never-train: this mutates no state — neither the findings, nor *ledger*, nor any
    model/weight path. Same input -> same output.
    """
    out: list[AnnotatedFinding] = []
    for finding in findings:
        # Slice B: family dispatch. For an E-check or document finding this IS
        # compute_finding_fingerprint(finding) — byte-identical to before — so every existing
        # caller is unaffected by the widening. `period` is consumed only by Signal A.
        fp = compute_family_fingerprint(finding, period=period)
        if fp is None:
            # A family that cannot form its key (a blank Signal B reference; Signal A without
            # a run period) stays UN-adjudicable rather than collapsing onto a shared key that
            # one decision could sweep. Cardinality is still preserved: the row is annotated
            # with nothing, never dropped.
            out.append(AnnotatedFinding(
                finding=finding,
                fingerprint=None,
                demoted=False,
                annotation=None,
                prior_dispositions=(),
            ))
            continue
        # THE INERT RULE (Terry R1, explicit — never an implicit fallthrough): the
        # lookup joins the CURRENT-version recomputed key against stored keys. A v0
        # entry's stored key was computed under the superseded 2-field composition,
        # so it can never equal a v1 key — v0 entries are INERT BY DESIGN. Applying
        # them forward would re-import the sweep-collision v1 exists to kill. The
        # non-application is surfaced as data via count_superseded_entries(), never
        # silently swallowed. History is untouched — the entries remain in the chain.
        priors = ledger.lookup(fp)
        dispositions = tuple(e.disposition for e in priors)
        demoted = any(d in DEMOTE_DISPOSITIONS for d in dispositions)
        annotation = _build_annotation(priors) if priors else None
        out.append(AnnotatedFinding(
            finding=finding,
            fingerprint=fp,
            demoted=demoted,
            annotation=annotation,
            prior_dispositions=dispositions,
        ))
    return out
