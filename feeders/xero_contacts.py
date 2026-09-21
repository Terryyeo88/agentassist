"""
feeders/xero_contacts.py — the Xero Contacts export as a SUPPLIER-MASTER surface.

D-2026-09-20-slice-c-contacts-no-gst-reg. A Xero IRAS-F5 export carries no supplier
master, so ``NO_GST_REG`` (input tax claimed from a supplier with no GST registration
number) has never been able to run on the Xero path — ``coverage_status`` has reported it
``unavailable`` and asked for the supplier master at onboarding. In Xero that master is the
CONTACTS export, and its ``TaxNumber`` column is the GST registration number.

WHAT THIS MODULE IS. A loader + an index. It parses the real Xero Contacts CSV (73-field
header, data rows of 53 fields, CRLF, with or without a UTF-8 BOM) and answers ONE
question per transaction counterparty: does exactly one contact of that name exist, and
what is its ``TaxNumber``?

PRESENCE ONLY (ruling R1). A non-blank ``TaxNumber`` makes the supplier "registered on
record" and nothing more. The number is NEVER format-validated, never inferred, never
looked up against IRAS, and never compared between contacts — two contacts sharing one
number is not a finding here (it is deliberate bait for a future shared-registration
check). A blank one is a CANDIDATE for the reviewer, never a verdict.

NEVER A FINDING (ruling R2). A name that matches no contact, a name that matches two or
more, and a transaction with no supplier name at all are all NOT EXAMINED. They are
COUNTED (see ``ContactsJoin``) and reported as a coverage degrade — never silently
dropped, and never guessed at by picking the first match.

IMPORT POSTURE. ``feeders/`` is a pure-stdlib leaf: it imports no ``agent``, no
``engine``, no ``orchestrator``, no ``anthropic`` (docs/merge-gates.md Gate a). That is
why ``normalize_contact_name`` below is a LOCAL re-implementation of the E-check
counterparty normaliser rather than an import of ``agent.decision_ledger``; the two
definitions are pinned equal by test (``test_xero_contacts_join.py``
``test_normaliser_matches_the_e_check_counterparty_normaliser``) so the copy cannot drift.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

#: The Xero Contacts export's own column names. The name column is the export's first
#: field and carries Xero's required-field marker.
_CONTACT_NAME_COLUMN = "*ContactName"
_TAX_NUMBER_COLUMN = "TaxNumber"

#: Join outcomes. ``unique`` is the only state that EXAMINES a line; every other state is
#: counted as not-examined and can never produce a finding (R2).
UNIQUE = "unique"
MISSING = "missing"
AMBIGUOUS = "ambiguous"
NAMELESS = "nameless"


def normalize_contact_name(name: Any) -> str:
    """Collapse ALL whitespace runs + casefold — the E-check counterparty normaliser.

    Mirrors ``agent.decision_ledger._normalize_counterparty`` EXACTLY (and is pinned equal
    to it by test). ``" ".join(split())`` collapses internal runs AND strips the ends, so
    "OldRate  Supplies" and " oldrate supplies " are one supplier, not three.
    """
    return " ".join(("" if name is None else str(name)).split()).casefold()


@dataclass(frozen=True)
class ContactsJoin:
    """How many input-tax purchase lines were EXAMINED, and why the rest were not.

    Counts are per LINE, not per supplier: the denominator is every input-tax purchase
    line in the period, so a supplier missing from the Contacts export costs as many
    un-examined lines as it has transactions. Ruling R3 — a nameless line is COUNTED in
    the denominator, never excluded from it.

    Exposed on the reader as ``contacts_join`` and handed to
    ``coverage_status.derive_coverage_statuses`` the way ``document_join`` is handed over
    (the D-40 precedent): the numbers are COMPUTED from the data and carried as DATA. The
    coverage reason is BUILT from them; nothing ever parses counts back out of prose.
    """

    examined: int = 0
    missing: int = 0
    ambiguous: int = 0
    nameless: int = 0

    @property
    def total(self) -> int:
        """Every input-tax purchase line — the denominator."""
        return self.examined + self.missing + self.ambiguous + self.nameless

    @property
    def fully_examined(self) -> bool:
        """True only when EVERY input-tax purchase line was examined (R3's `full` leg)."""
        return self.total == self.examined


@dataclass(frozen=True)
class ContactsIndex:
    """A name-keyed view of one Contacts export.

    ``by_name`` maps the NORMALISED contact name to the tuple of ``TaxNumber`` values
    carried by the contacts of that name — a tuple, not a single value, so a duplicate
    name is AMBIGUOUS by construction rather than by a first-wins accident.
    ``display_by_name`` keeps the contact's name AS THE EXPORT SPELLS IT, so a joined
    transaction can be keyed by the supplier's canonical name rather than by whatever
    spelling that one transaction happened to carry.
    """

    by_name: dict
    contact_count: int
    display_by_name: dict

    def match(self, name: Any) -> tuple:
        """Resolve a transaction's counterparty name to ``(state, tax_number)``.

        ``(UNIQUE, "<TaxNumber>")`` — exactly one contact of that name; the number may be
        the empty string, which is precisely what makes NO_GST_REG fire.
        ``(MISSING, None)`` / ``(AMBIGUOUS, None)`` / ``(NAMELESS, None)`` — not examined.
        """
        key = normalize_contact_name(name)
        if not key:
            return (NAMELESS, None)
        values = self.by_name.get(key)
        if values is None:
            return (MISSING, None)
        if len(values) > 1:
            return (AMBIGUOUS, None)
        return (UNIQUE, values[0])

    def canonical_name(self, name: Any) -> str:
        """The contact's name as the EXPORT spells it, for a name that resolves UNIQUE.

        Keying a joined document by this (rather than by the transaction's own spelling)
        means two spellings of one supplier dedupe to ONE finding — the check emits one
        issue per SUPPLIER (R4), and the supplier is the contact, not the keystroke.
        """
        return self.display_by_name.get(normalize_contact_name(name), "")

    def has_tax_number_population(self) -> bool:
        """Whether the TaxNumber column carried at least one NON-EMPTY value.

        The OBSERVED-population predicate (D-2026-07-27-xero-coverage-derived), applied to
        this surface: a present-but-0%-populated column is NOT covered, so an export whose
        TaxNumber column is entirely empty leaves NO_GST_REG ``unavailable`` rather than
        flagging every supplier off an empty column.
        """
        return any(value.strip() for values in self.by_name.values() for value in values)


def load_contacts(source) -> ContactsIndex:
    """Parse a Xero Contacts CSV export into a ``ContactsIndex``.

    TOLERANT BY DESIGN, because this is a CLIENT'S file:
      * ``utf-8-sig`` — a real export may or may not carry a UTF-8 BOM (neither committed
        fixture does; the recon claim that they did was wrong). Both parse identically.
      * RAGGED ROWS — a real export's data rows carry 53 fields against a 73-field header.
        A row shorter than the TaxNumber column reads as a blank TaxNumber, never an
        IndexError.
      * The columns are located BY HEADER NAME, never by a hard-coded index, so a Xero
        column-order change degrades to "no TaxNumber column" rather than reading some
        other field as a GST registration number.

    A file with no recognisable header yields an EMPTY index: every supplier then reads
    MISSING and nothing is flagged (R2). Never a fabricated finding.
    """
    raw = Path(source).read_bytes() if not isinstance(source, (bytes, bytearray)) else bytes(source)
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))))
    if not rows:
        return ContactsIndex(by_name={}, contact_count=0, display_by_name={})

    header = [str(cell).strip() for cell in rows[0]]
    name_index = header.index(_CONTACT_NAME_COLUMN) if _CONTACT_NAME_COLUMN in header else 0
    tax_index: Optional[int] = (
        header.index(_TAX_NUMBER_COLUMN) if _TAX_NUMBER_COLUMN in header else None
    )

    by_name: dict = {}
    display_by_name: dict = {}
    count = 0
    for row in rows[1:]:
        if not any(str(cell).strip() for cell in row):
            continue  # a blank line, not a contact
        name = row[name_index] if name_index < len(row) else ""
        key = normalize_contact_name(name)
        if not key:
            continue  # a contact with no name cannot be joined to anything
        tax_number = ""
        if tax_index is not None and tax_index < len(row):
            tax_number = str(row[tax_index]).strip()
        by_name.setdefault(key, []).append(tax_number)
        display_by_name.setdefault(key, str(name).strip())
        count += 1

    return ContactsIndex(
        by_name={key: tuple(values) for key, values in by_name.items()},
        contact_count=count,
        display_by_name=display_by_name,
    )
