# Business-Context Assumption — Reg 26/27 Labelling and Reasoning Pass

<!-- PROVENANCE
     Created by   : AgentAssist T2.7, 2026-06-03
     Purpose      : States the generic-SME assumption that underlies the Reg 26/27
                    labelling pass (L) and the reasoning pass (T2.7).  Inject this
                    file verbatim into the labelling-pass prompt so that the assumption
                    is explicit and auditable.
     Do NOT edit  : This file is hashed into the labelling-pass artefact.  Any
                    change invalidates all prior labels and requires a full re-label.
-->

## Assumed Business Type: Generic General-Trading / Services SME

All fixture labels and all reasoning-pass inferences assume the client is a
**generic, general-trading or professional-services SME** operating in Singapore
and registered for GST.

In concrete terms this means:

- The business buys goods and services as **operating overhead or staff expenditure**,
  not as trading stock or inputs to its primary commercial activity.
- A club membership, a motor-car running expense, or a staff medical bill is
  presumed to be an **overhead purchase** — the kind a Reg 26/27 disallowance
  is designed to target.
- The business does **not** trade in the categories that appear in the §6.1.6
  disallowance list as its primary commercial activity (see caveat below).

---

## Why This Assumption Matters

Reg 26/27 targets overhead expenditure.  When a business's **primary trade**
is in a category that overlaps with the disallowance list, the disallowance
rule may not apply — those purchases are trading inputs, not overhead:

| Business type | Line that looks disallowed | Actual GST treatment |
|---|---|---|
| Car dealer | Vehicle purchase / running cost | **Claimable** — trading stock or demonstrator vehicle used in the business of selling cars |
| Medical clinic | Medical supplies, staff medical costs | **Claimable** — direct inputs to the medical service being sold |
| Insurance broker | Staff medical & accident premium | May be **claimable** if the premium is itself the product being sold or a mandatory input to it |
| Sports/recreational club | Its own membership & subscription income | Complex — seek specialist advice on the specific facts |

**The fixture labels are NOT valid for businesses in these categories.**
Applying the scoring harness to a car dealer's or clinic's data would produce
materially wrong recall and FP-rate figures.

---

## Production Implication (Roadmap Item T2.7.x)

The production reasoning pass must receive the client's business nature as an
explicit input — see the `ClientConfig` roadmap item in
`knowledge-base/AgentAssist-Technical-Roadmap-v3.md` — so that context-claimable
lines (a car dealer's vehicles, a clinic's medical supplies) are not surfaced
as Reg 26/27 candidates.

Until that field exists, the pass is limited to generic SME clients and
**must not be enabled** for clients whose primary trade overlaps with any
§6.1.6 disallowed category without a manual KB customisation.

---

## Scope of the Assumption

This assumption applies to:

1. **Fixture labelling (pass L)** — all 110 DRAFT lines are labelled on the
   generic-SME premise.  Labels are not portable to specialist businesses.
2. **Reg 26/27 reasoning pass (T2.7)** — the KB slice (`reg2627.md`) and
   system prompt are written for a generic SME.
3. **Gate measurement** — recall and FP-rate figures are valid only for
   generic-SME data.  Measured on a car dealer's data, the same model would
   produce artificially high FP rates (vehicles flagged that are trading stock).

---

## What This Assumption Does NOT Cover

- Partial exemption: a business that makes both taxable and exempt supplies
  must apportion input tax separately.  This pass does not address partial
  exemption.
- Import GST / non-resident suppliers: this pass is scoped to domestic
  Singapore standard-rated purchases.
- Rate-transition lines (9 % vs 8 % vs 7 %): rate correctness is handled
  by the deterministic chain, not this pass.
