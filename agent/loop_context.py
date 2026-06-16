"""
agent/loop_context.py — build a REAL LoopContext for the case-file loop from the
frozen SBODEMOSG extract (T5.3h).

The T5.3-V machinery runs drove ``run_casefile_loop`` over a HAND-CRAFTED ReviewResult
plus a fixture ctx (a fixture PDF + a tiny vendor catalog) — machinery only, not real
data. This module closes that gap: it assembles the ctx the loop's gather step consumes
from the frozen ground truth, so the loop runs over REAL findings rather than crafted
ones.

Division of labour (A1 — see the T5.3h prompt):

  * The REAL ``ReviewResult`` is produced OFFLINE by the caller (e.g.
    ``tests/replay_shim.replay_review`` — the deterministic chain off the frozen extract,
    SAP unreachable) and INJECTED into ``build_loop_context``. This module never runs the
    chain, never touches SAP, never monkeypatches anything, and imports no SDK — it stays
    a pure assembler so it can serialise cleanly for the T5.8 RealEngine path to consume.
  * From the injected ReviewResult this module extracts the real findings
    (``agent.dossier.extract_findings``).
  * The vendor/supplier catalog is built from the S3 ``business-partners`` surface of the
    frozen extract (keyed by CardName, surfacing only the GST-registration fields the
    Tier-0 ``read_vendor_gst_status`` needs — no other BP fields, no secrets).
  * The source-document provider is an ``AbsentDocumentProvider`` and the prior-period
    store is empty: SBODEMOSG ships no invoice attachments and we hold no prior-period
    record, so both reads honestly return ABSENT (the degraded case) rather than
    fabricating evidence.

``LoopContext`` (agent/loop.py) carries only the three read sources; the loop receives
the ReviewResult separately via its ``invoke_review`` argument. ``build_loop_context``
therefore returns a small ``BuiltLoopContext`` bundle pairing the two (plus the extracted
findings) so a caller can wire the loop directly.

Surfaces, never asserts: this builder assembles evidence context; it asserts no
compliance position and never recomputes or mutates the deterministic findings — it reads
``review()``'s output as-is.

Zero anthropic import. Zero SDK import. Stdlib only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from agent.dossier import Finding, extract_findings
from agent.loop import LoopContext

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: The frozen SBODEMOSG extract directory (same ground truth the T2.12a offline-replay
#: gate runs against). The vendor catalog is read from its business-partners surface.
FROZEN_EXTRACT: Path = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"


class AbsentDocumentProvider:
    """A DocumentProvider that has NO source documents (honest SBODEMOSG degraded case).

    SBODEMOSG ships no invoice attachments, so ``get_source_document`` over this provider
    always returns ``None`` — the loop records source-doc evidence as ABSENT rather than
    fabricating it. Read-only; mutates nothing; the model never supplies the source.
    """

    def get_document(self, doc_num: int) -> Optional[str]:
        return None


def build_vendor_catalog(extract_dir: Path = FROZEN_EXTRACT) -> dict:
    """Build the vendor/supplier catalog from the S3 ``business-partners`` surface.

    The frozen ``business-partners.raw.json`` is keyed by CardCode; the catalog
    ``read_vendor_gst_status`` consumes is keyed by CardName. For each business partner
    this surfaces ONLY the two GST-registration fields the read needs:

      * ``gst_registered`` — derived from the presence of a ``FederalTaxID`` (the SG
        GST-registration-number field on a BusinessPartner);
      * ``gst_reg_no``     — the ``FederalTaxID`` itself (``None`` when absent).

    No other BP fields are surfaced (minimal, no secrets). A record without a CardName is
    skipped.
    """
    raw = json.loads((extract_dir / "business-partners.raw.json").read_text(encoding="utf-8"))
    catalog: dict[str, dict] = {}
    for record in raw.values():
        card_name = record.get("CardName")
        if not card_name:
            continue
        federal_tax_id = record.get("FederalTaxID")
        catalog[card_name] = {
            "gst_registered": federal_tax_id is not None,
            "gst_reg_no": federal_tax_id,
        }
    return catalog


@dataclass
class BuiltLoopContext:
    """The real case-file-loop inputs assembled from the frozen extract.

    ``LoopContext`` itself carries only the three Tier-0 read sources; the loop receives
    the ReviewResult separately via its ``invoke_review`` argument. This bundle pairs the
    two (plus the extracted findings, for convenience) so a caller can wire the loop:

        built = build_loop_context(period, review_result=rr)
        run_casefile_loop(
            invoke_review=lambda: built.review_result,
            transport=ScriptedLoopTransport(scripts, built.ctx, ledger),
            ctx=built.ctx, ledger=ledger, budget=budget, store=store,
        )

    Attributes:
        review_result: The injected (offline-replayed) ReviewResult — real findings.
        ctx:           LoopContext(provider, vendor_catalog, prior_period_store).
        findings:      ``extract_findings(review_result)`` — the real normalised findings.
    """
    review_result: Any
    ctx: LoopContext
    findings: list[Finding]


def build_loop_context(
    period: dict,
    *,
    review_result: Any,
    extract_dir: Path = FROZEN_EXTRACT,
) -> BuiltLoopContext:
    """Assemble the real LoopContext for the case-file loop from the frozen extract.

    Args:
        period:        The audit period ``{"start", "end"}`` the review covers. Carried
                       for the caller / forward-compatibility; the findings on
                       ``review_result`` already reflect it.
        review_result: A ReviewResult produced OFFLINE (e.g.
                       ``tests/replay_shim.replay_review``) and INJECTED here, so this
                       module stays pure — no SAP, no monkeypatch, no SDK. Its findings
                       are real.
        extract_dir:   Frozen extract dir; the vendor catalog is read from its
                       ``business-partners`` surface.

    Returns:
        ``BuiltLoopContext(review_result, ctx, findings)``. ``ctx.provider`` is an
        ``AbsentDocumentProvider`` (source docs absent) and ``ctx.prior_period_store`` is
        empty (no prior-period record) — both honest SBODEMOSG degraded cases.
    """
    findings = extract_findings(review_result)
    ctx = LoopContext(
        provider=AbsentDocumentProvider(),
        vendor_catalog=build_vendor_catalog(extract_dir),
        prior_period_store={},
    )
    return BuiltLoopContext(review_result=review_result, ctx=ctx, findings=findings)
