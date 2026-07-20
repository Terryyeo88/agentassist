# sources.md — citation manifest for the knowledge-base corpus

Rule-author: Terry Yeo. This manifest is the authoritative record of WHO checked,
FROM WHICH COPY, WHEN — not merely "what edition". It exists because three merged
basis strings were found citing sources that were absent, mis-editioned, or
contradicted by a sibling artefact, and because a true edition attached to a false
provenance is exactly the failure a row carrying only edition+date cannot catch.
Agent-generated mechanics (SHA-256, paths, page counts, publication-history
extractions) are admitted per ruling γ; every edition/date/provenance value traces
to a rule-author ruling (β/γ/δ/α1, 2026-07-16..2026-07-19) or to a
publication-history page read. Nothing in this file is inferred from a filename.

## Source-admissibility invariant (rule-author ruling, 2026-07-19)

Only IRAS-hosted e-Tax Guides and SSO/AGC-hosted primary legislation
(the GST Act and GST (General) Regulations, version-pinned to their SSO
'in force as at' stamp) count as authority for tax semantics. Third-party
summaries and mirrors (e.g. plco.com.sg) never do. Primary legislation is
admissible for its own text only, never for annotation or commentary.

Decisive reason on record (α1): the List of International Services extract is an
excerpt of the GST Act, is already in knowledge-base/, and is already cited by the
merged exempt-supply slice for s21(3) — the prior "IRAS-hosted only" phrasing
conflated SOURCE TYPE with HOST; it was written to exclude third-party summaries,
not primary law.

## Reading rules

- The publication-history page (p.2 in every guide in this corpus) is the ONLY
  admissible evidence of an edition. Cover pages are structurally unreliable:
  three confirmed layering artifacts in this corpus alone (ruling γ).
- An edition is NEVER inferred from a filename or a citation string (ruling δ).
  An unknown edition reads UNVERIFIED.
- local_path means CLONED: bytes in the git tree, present in every checkout.
  "In the repo" has three meanings — on disk, tracked, present in a clone — and
  this column means the third. ABSENT means cited-but-not-held.
- One row per FILE, not per instrument. Two files of one instrument get two rows;
  status + superseded_by express which one a citation should resolve to.
- verified_by: rule-author (Terry attestation) or agent-history-page (γ-blessed
  extraction citing the page). A row whose verified_from is not a repo path may
  not read VERIFIED without an explicit rule-author attestation naming where the
  copy lived.
- Filename convention for newly named files: instrument-ordinal-pubdate; names
  are hints, rows are authoritative. Only names that LIE get renamed (ruling:
  a lying name sends you to a wrong answer that looks right; a silent name sends
  you to the manifest).

## Manifest

| local_path | instrument | class | edition | pub_date | pages | sha256 | status | superseded_by | verified_by | verified_from | verified_on | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| knowledge-base/gst-reverse-charge-10th-2026-01-30.pdf | IRAS e-Tax Guide: GST: Reverse Charge | e-Tax Guide | Tenth Edition | 30 Jan 2026 | 88 | 06b14a6da63b06416e69e4b9ca5fe497c2ea56f536e4bef27839e0eb8fbde1e2 | CURRENT | — | agent-history-page | knowledge-base/gst-reverse-charge-10th-2026-01-30.pdf | 2026-07-17 | p.2 publication history (chain ends Ninth Edition 1 Jul 2025). Carries De Minimis fn 12 (p.8) with the three denominator exclusions the merged D52 caveat encodes. Also rule-author-attested 2026-07-16 against an EXTERNAL-COPY, pre-repo (see D52 provenance annotation). Former slug said "2nd-edition" — a lie; renamed per convention 2026-07-19. |
| knowledge-base/gst-reverse-charge-02nd-2019-08-22-SUPERSEDED.pdf | IRAS e-Tax Guide: GST: Reverse Charge | e-Tax Guide | Second Edition | 22 Aug 2019 | 60 | 46d1d1e29f12a64b6aa2b91a8149c9cc50080267c7d1b75dab675381fcb7feba | SUPERSEDED | knowledge-base/gst-reverse-charge-10th-2026-01-30.pdf | agent-history-page | knowledge-base/gst-reverse-charge-02nd-2019-08-22-SUPERSEDED.pdf | 2026-07-17 | p.2 publication history (chain: First Edition 4 Feb 2019). KEPT, not deleted — the teaching artefact that justifies this manifest: its former slug was indistinguishable from the Tenth Edition's ("2nd-edition" in both). In this edition the De Minimis footnote is fn 9, not fn 12, and carries NO denominator exclusions — the sentence ends at the 5% limb; "low-value goods" appears zero times in the document. A reader following the merged caveat's citation ("RC e-Tax Guide, fn 12") into this file gets a coherent-looking wrong answer rather than an error: the fn 9 to fn 12 renumbering makes the wrong copy look internally consistent. |
| knowledge-base/gst-attribution-of-input-tax-10th-2026-01-30.pdf | GST Guide on Attribution of Input Tax | e-Tax Guide | Tenth Edition | 30 Jan 2026 | 25 | 3d8649b304747d3212124bce411ac7be69475c5c3f41865759fee094c01d5ec0 | CURRENT | — | agent-history-page | knowledge-base/gst-attribution-of-input-tax-10th-2026-01-30.pdf | 2026-07-17 | p.2 publication history (chain ends Ninth Edition 31 Oct 2025). Former slug said "7th-edition" — a lie; renamed per convention 2026-07-19. Not yet cited by any code artefact. |
| knowledge-base/e-tax-guide_gst_digital-payment-tokens.pdf | IRAS e-Tax Guide: GST: Digital Payment Tokens | e-Tax Guide | Third Edition | 30 Jan 2026 | 23 | abc2247bc6415d1dd1a859fa348c4a3bdc0f73470a32ed5c5d29be3741ea343f | CURRENT | — | agent-history-page | knowledge-base/e-tax-guide_gst_digital-payment-tokens.pdf | 2026-07-17 | p.2 publication history (chain: First edition 19 Nov 2019, Second edition 3 Aug 2022). Cited by the merged exempt-supply slice. Silent filename kept (no edition token; the row is authoritative). |
| knowledge-base/list-of-international-services-extract.pdf | List of International Services | STATUTORY EXTRACT of the GST Act — NOT an e-Tax Guide | Not editioned (statutory extract, in force from 1 Jan 2020) | 17 Feb 2020 (LAST-UPDATED date, not a publication date — different semantic, same slot) | 13 | d8f012ab286951eb2cf4c0e433bcba6b26477289c015f4fe2feb408a41afeba2 | CURRENT | — | rule-author | knowledge-base/list-of-international-services-extract.pdf | 2026-07-19 | No publication-history page exists (cover-only class) — rule-author attestation per ruling β. OLDEST instrument in this corpus by ~6 years; the merged exempt-supply slice depends on it for s21(3). Admissible as primary-legislation extract per α1. |
| knowledge-base/etaxguide_gst_gst-general-guide-for-businesses(1).pdf | IRAS GST: General Guide for Businesses | e-Tax Guide | Seventeenth Edition | 30 Jan 2026 | 49 | 19734b2d66505c763adc389889d7e78540656a08e95b3d1b2db77e15ee4e9656 | CURRENT | — | agent-history-page | knowledge-base/etaxguide_gst_gst-general-guide-for-businesses(1).pdf | 2026-07-17 | p.2 publication history (chain ends Sixteenth Edition 1 Sep 2025). "(1)" in the name is a download-dedupe suffix, not an edition token — silent, kept. |
| knowledge-base/etaxguide_gst_how-do-i-prepare-my-gst-return.pdf | IRAS e-Tax Guide: How do I prepare my GST return? | e-Tax Guide | Eleventh Edition | 30 Jan 2026 | 33 | d9df3df65f40764c010f33ba3744bb294286da2c7f9b2cde6346a8c7e483fe5f | CURRENT | — | agent-history-page | knowledge-base/etaxguide_gst_how-do-i-prepare-my-gst-return.pdf | 2026-07-17 | p.2 publication history (chain ends Tenth Edition 01 Jan 2024). One of TWO byte-different files of the SAME edition (see next row) — a duplicate, not a collision. |
| knowledge-base/how-do-i-prepare-my-gst-return-eleventh-edition.pdf | IRAS e-Tax Guide: How do I prepare my GST return? | e-Tax Guide | Eleventh Edition | 30 Jan 2026 | 33 | bac09e81d725a1e1047c2b59eb9d96c849659d3ffc30a4ed92f58d434584b221 | CURRENT | — | agent-history-page | knowledge-base/how-do-i-prepare-my-gst-return-eleventh-edition.pdf | 2026-07-17 | p.2 publication history (identical chain to the row above). Byte-different duplicate of the same Eleventh Edition — hashes differ, edition and history agree; which copy is read does not change what is read. The filename's edition token is TRUE — left unrenamed per the rename-what-lies ruling. |
| knowledge-base/etaxguide_gst_invoicenow_requirement.pdf | IRAS e-Tax Guide: Adopting GST InvoiceNow Requirement | e-Tax Guide | Second Edition | 9 Mar 2026 | 85 | c87bb82577d3a2107a350856b116bd260e029479cfeebaf9ab9686a26abbcdfb | CURRENT | — | agent-history-page | knowledge-base/etaxguide_gst_invoicenow_requirement.pdf | 2026-07-17 | p.2 publication history (chain: First edition 7 Mar 2025). The only guide in the corpus not dated 30 Jan 2026. Present but uncited by any repo artefact. |
| knowledge-base/etaxguides_gst_exchange-rates-for-gst-purpose.pdf | IRAS e-Tax Guide: GST: Exchange Rates for GST Purpose | e-Tax Guide | Fourth Edition | 30 Jan 2026 | 7 | 81cec0ff85cc2cfb0ed286c54c6289fc0aa714dc9a42ee63b9a7d998594b12dd | CURRENT | — | agent-history-page | knowledge-base/etaxguides_gst_exchange-rates-for-gst-purpose.pdf | 2026-07-17 | p.2 publication history (chain: First 30 Sep 2013, Second 13 Jun 2017, Third 26 Nov 2021). Cover p.1 carries a leftover "GST: General Guide for Businesses" text layer — one of the three confirmed cover layering artifacts (γ). Present but uncited by any repo artefact. |
| knowledge-base/iras-ask/gst_ask-annual-review-guide.pdf | IRAS ASK Annual Review Guide | e-Tax Guide (ASK) | Sixteenth Edition | 30 Jan 2026 | 83 | d590767a0c299239a080729205839747fd1b6d71601c51fc5afb4037e2d912cd | CURRENT | — | agent-history-page | knowledge-base/iras-ask/gst_ask-annual-review-guide.pdf | 2026-07-17 | p.2 publication history (chain ends Fifteenth edition 1 Jul 2024). Cover p.1 text layer mis-extracts as "Do I need to register? (Third Edition)" — a layering artifact; the history page is authoritative (γ). The heaviest-cited instrument in the codebase; report/constants.py Appendix-1 block pins 16th Edition (30 Jan 2026) — consistent. |
| ABSENT | IRAS e-Tax Guide: GST: Partial Exemption and Input Tax Recovery | e-Tax Guide | UNVERIFIED | UNVERIFIED | — | — | UNVERIFIED | — | UNVERIFIED | ABSENT | — | Cited by the merged partial-exemption banner as "(6th edition)" — per ruling δ that token may NOT be back-filled here: three of three slugs in this corpus were caught wrong, and an edition asserted only by a citation string is exactly the class this manifest distrusts. Rule-author does not hold the guide. |
| ABSENT | GST Act | PRIMARY LEGISLATION (SSO/AGC-hosted) | UNVERIFIED | UNVERIFIED | — | — | UNVERIFIED | — | UNVERIFIED | ABSENT | — | Admissible per α1 (version-pinned to SSO's 'in force as at' stamp) but no SSO-stamped copy supplied. Cited by registry basis strings (s10, s19(1), s20, s21(3)) and report/sections.py (4th Schedule). The s21(3) List of International Services excerpt IS held — see its own row. |
| ABSENT | GST (General) Regulations | PRIMARY LEGISLATION (SSO/AGC-hosted) | UNVERIFIED | UNVERIFIED | — | — | UNVERIFIED | — | UNVERIFIED | ABSENT | — | Admissible per α1 but no SSO-stamped copy supplied. Cited by registry (regs 11, 26/27), check_partial_exemption (reg 28, reg 29(3)), report/constants (regs 26/27). reg 26/27 content is currently held only second-hand via the reg2627 slice's guide citations. |
| ABSENT | IRAS GST F5 Return form | Form | UNVERIFIED | UNVERIFIED | — | — | UNVERIFIED | — | UNVERIFIED | ABSENT | — | Cited by the registry F5 arithmetic-consistency basis; no form artefact is held (the iras-ask/ xlsx templates are ASK working templates, not the F5 form). |
| ABSENT | IRAS Supplies Exempt from GST | IRAS web page / guide | UNVERIFIED | UNVERIFIED | — | — | UNVERIFIED | — | UNVERIFIED | ABSENT | — | Cited by the merged exempt-supply slice (internal-only). Not held. |
| ABSENT | IRAS Annex E (Xero TaxType to VatGroup) | IRAS web artefact | UNVERIFIED | UNVERIFIED | — | — | UNVERIFIED | — | UNVERIFIED | ABSENT | — | The feeders' _PROPOSED_VAT_GROUP_MAP is a rule-author-authored PROPOSED mapping (DEBT-1, UNVALIDATED); no Annex E artefact is held. Internal-only. |
