# Knowledge-base slice: exempt-supply misclassification (sales)

<!-- skill_id: exempt-supply    kb_slice_name: exempt-supply -->
<!-- Rule-author: Terry. Every rule below traces to a NAMED IRAS source (see §9).
     This slice is a Terry-authored READING of IRAS sources, cross-verified against
     the cited guides/pages, not IRAS text reproduced. -->
<!-- Injected verbatim into the reasoning prompt. The pass SURFACES candidates
     for a human reviewer; it NEVER asserts a classification. -->

## 1. Purpose

Help a reviewer catch **sales** lines whose exempt-vs-taxable classification may
be wrong. Exempt supplies (the Fourth Schedule set) are reported in **F5 Box 3**;
taxable supplies are standard-rated (Box 1) or zero-rated (Box 2). Two error
directions:

1. **Coded exempt but cannot qualify** — a line routed to Box 3 that is not
   actually a Fourth Schedule supply, and should be standard-rated (or
   zero-rated). This **understates output tax** — the costly direction for IRAS
   exposure. *This is v1's primary target.*
2. **Coded taxable but actually exempt** — over-declares output tax; noisier and
   less costly. *Deferred to v2.*

*(Source: ASK Annual Review Guide, Step 3C — Check your Exempt Supplies, 3C-1
actively-making / 3C-2 general-business.)*

## 2. Scope of v1 (read before tuning)

- **Classification only, NOT valuation.** Financial-services exempt supplies have
  ~9 transaction-type valuation rules (interest, realised forex gain, etc.). Value
  correctness is out of scope. *(How-do-I-prepare 11th ed §6.3.1–6.3.2.)*
- **Exempt-vs-taxable, NOT the ES33-vs-ESN33 sub-split.** Whether an exempt supply
  is a Reg 33 supply (ES33) or another exempt supply (ESN33) is an **input-tax
  apportionment** distinction (Reg 28/29/33), not a Box 3 *value* question — both
  land in Box 3. Out of v1 scope. *(How-do-I-prepare 11th ed §5.9(b), which names
  Reg 28/29/33 verbatim.)*
- **Primary signal:** an exempt-coded line whose description does not read as a
  Fourth Schedule supply, or reads as one of the §4 traps.

## 3. What IS exempt (Fourth Schedule to the GST Act) → Box 3

Only these categories are exempt:
- **(a) Provision of financial services** (Fourth Schedule Part I — the Act
  provides the list).
- **(b) Supply of digital payment tokens** (from 1 Jan 2020) — specifically the
  exchange of DPT for fiat / other DPT, and the provision of DPT loans.
- **(c) Sale and lease of RESIDENTIAL properties** — vacant residential-zoned
  land, or a residential building/flat/tenement.
- **(d) Import and local supply of investment precious metals (IPM)** — qualifying
  gold (≥99.5%), silver (≥99.9%), platinum (≥99%) in investment bar/ingot/wafer/
  coin form (Fourth Schedule Part I, para 1A).

*(Source: IRAS "Supplies Exempt from GST" (all four categories); GST General Guide
§4.3 (three) + para-1A IPM ref; How-do-I-prepare 11th ed §5.9.)*

## 4. The traps — where "looks exempt" is actually TAXABLE (the misclassification meat)

- **Financial INTERMEDIARY fees are taxable, not exempt.** Advising on,
  **arranging, broking, or underwriting** financial activities is standard-rated
  to local customers (may be zero-rated to overseas). An insurance broker's
  commission is taxable even though the underlying policy premium is exempt. A
  line coded exempt described as "brokerage / arrangement / advisory / commission"
  is a candidate.
- **Commercial property is NOT exempt.** Only **residential** property is exempt.
  Office / retail / industrial / warehouse lease or sale coded exempt is a
  candidate.
- **Real-estate agent / property-agent services are taxable** — regardless of
  whether the property is residential or commercial. "Agent commission" coded
  exempt is a candidate.
- **Furnished residential — the MOVABLE component is taxable.** The bare unit
  rental/sale is exempt, and built-in **fixtures** (cabinets, wardrobes, kitchen/
  sanitary wares, permanently-attached aircon) stay exempt with the property; but
  **movable furniture and fittings are taxable**. A single fully-exempt "furnished
  apartment" line may under-tax the movable-furniture component.
- **Mixed-use / shophouse:** the residential portion is exempt, the
  non-residential portion is taxable — a single exempt code over a mixed line may
  under-tax the non-residential portion. (Inference from the residential-only
  rule; reviewer confirms apportionment.)
- **Financial service to an OVERSEAS customer may be ZERO-RATED, not exempt.**
  A prescribed financial service supplied under contract with, and benefiting, a
  person belonging outside Singapore may be a zero-rated international service
  (Box 2, s21(3)); the same service to a local person is exempt (Box 3). A
  Box-3-coded financial-service line to an overseas counterparty is a candidate.
- **Digital-payment-token INTERMEDIARY and voucher-like tokens are taxable.**
  The DPT exemption covers the token exchange/loan itself — it does **not** extend
  to intermediary services (exchange, wallet, broker), to mining services provided
  for a consideration, or to utility tokens that cease to function as a medium of
  exchange (treated like vouchers). A "crypto exchange fee / wallet service /
  token brokerage" line coded exempt is a candidate. **NOTE (false-positive
  guard):** stablecoins and security tokens are typically still EXEMPT under the
  financial-services heads (currency; shares/debt), so an exempt-coded stablecoin
  or security-token line is NOT a candidate on that basis alone.

*(Source: IRAS "Supplies Exempt from GST" (intermediary fees, real-estate agent,
furnished-fixtures-vs-furniture, DPT intermediaries/mining); GST: Digital Payment
Tokens e-Tax Guide §§5.7–5.14 (token boundaries; stablecoins/security tokens
excluded-but-still-exempt); List of International Services extract, s21(3).)*

## 5. The data-readable signal

Raise a candidate **only** on a **description-vs-tax-code mismatch**: a line coded
**ES33 or ESN33** (exempt, Box 3) whose `line_description` either
- does not read as a Fourth Schedule supply (§3), or
- reads as one of the §4 traps (brokerage/arrangement/agent commission, commercial
  property, movable furniture, overseas financial-service counterparty, DPT
  intermediary/exchange/wallet/broker fee).

If the description is silent or generic (e.g. "SUNDRY", "SERVICE FEE") with no
Fourth-Schedule indicator, treat as **indeterminate** — surface with low
confidence, do not assert. No exempt code, no signal → no candidate in v1.

## 6. Surfacing discipline (hard limits)

- Every candidate's `phrasing` must begin `Consider reviewing whether`. Never
  state or imply a verdict. The reviewer decides; the system surfaces.
- Surface **only** on the §5 signal.
- **NEVER reason about, infer, or assert:** whether a property is residential vs
  commercial; whether a financial service is a Fourth-Schedule supply vs a taxable
  intermediary fee; whether a token is a qualifying DPT vs a stablecoin/security/
  utility token; the belonging/benefit of an overseas financial service. These
  depend on facts outside the transaction data and require client verification.
- Do not reclassify, correct, or compute Box 3. Read and surface only.

## 7. Worked examples (reworded from IRAS positions)

- **"INSURANCE BROKERAGE COMMISSION" coded exempt → candidate.** Arranging/broking
  a policy is a taxable service; only the underlying premium is exempt.
- **"OFFICE UNIT LEASE Q3" coded exempt → candidate.** Commercial property is not
  exempt; residential only.
- **"RESIDENTIAL APT 12-B MONTHLY RENTAL" coded exempt → no candidate** (bare
  residential lease is correctly exempt) — unless the description signals movable
  furniture/fittings, which are taxable.
- **"CRYPTO EXCHANGE TRADING FEE" coded exempt → candidate.** DPT intermediary
  services are taxable even though the token exchange itself is exempt.
- **"LOAN INTEREST — [overseas counterparty]" coded exempt (Box 3) → candidate.**
  A prescribed financial service to an overseas person may be zero-rated (Box 2);
  the reviewer checks belonging.

## 8. What you must NOT do

- Do not decide residential vs commercial, DPT-vs-stablecoin/security/utility, or
  belonging, from the line.
- Do not touch Box 3 or any other box.

## 9. Sources (cross-verified; owner-check remaining where noted)

1. **GST: General Guide for Businesses** — §4.3 (exempt supply), §6.3.3 (Reg 33 vs
   non-Reg-33), IPM para-1A ref. [project files]
2. **IRAS "Supplies Exempt from GST"** — four categories; intermediary-fee,
   commercial-property, real-estate-agent, furnished-fixtures-vs-furniture, DPT
   intermediary/mining positions. [verified 2026 against the live page]
3. **GST: Digital Payment Tokens e-Tax Guide** — DPT criteria; stablecoin/security/
   utility boundaries (§§5.7–5.14). [project files]
4. **How do I prepare my GST return? (11th ed)** — Box 3 (§5.9(a)–(c), §5.9(b)
   Reg 28/29/33); exempt-supply valuation table (§6.3.1–6.3.2, out of v1 scope).
   [project files]
5. **List of International Services extract** — s21(3); First Schedule prescribed
   financial services + belonging test (overseas-financial-service → ZR). [project files]
6. **GST: ASK Annual Review Guide** — Step 3C (3C-1 actively-making / 3C-2 general).
   [project files]
7. **Statutory-reference note (documentation-only; ruled non-blocking).** The exact
   Fourth Schedule paragraph for RESIDENTIAL property and the precise DPT exemption
   paragraph, plus the exact Reg 33 enumeration, are statutory and were not closed
   from the guides above. To be confirmed with an accredited consultant at
   onboarding (or on Singapore Statutes Online: sso.agc.gov.sg/Act/GSTA1993, Fourth
   Schedule; GST (General) Regulations reg 33). The v1 skill surfaces on
   description-vs-code only and does not depend on these paragraph numbers.

<!-- END exempt-supply slice. -->
