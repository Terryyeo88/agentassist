# IRAS ASK Documentation

Source materials for AgentAssist's ASK Annual Review compliance.

## Files

### Master methodology
- **01-annual-review-guide-16ed.pdf** — IRAS GST: Assisted Self-Help Kit (ASK) Annual Review Guide, Sixteenth Edition, published 30 Jan 2026. The 80-page master document describing IRAS's prescribed 5-step methodology, sample-size rules, certification procedures, and error taxonomy (Appendix 1). Primary reference for every substantive check AgentAssist performs.

### Declaration forms (outputs of the review process)
- **02-declaration-completing-annual-review.xlsx** — Form completed by the GST-registered business and (if applicable) ATA(GST)/ATP(GST) certifier upon ASK completion. AgentAssist's signed PDF report mirrors this structure.
- **03-declaration-voluntary-disclosure.xlsx** — Form for declaring errors found during ASK under IRAS's Voluntary Disclosure Programme. AgentAssist's "errors found" section mirrors this structure.
- **04-declaration-administrative-concessions.xlsx** — Form for declaring administrative concessions applied to common errors disclosed during ASK.

### Templates (substantive review worksheets)
The seven Templates walk reviewers through the substantive checks for each supply/purchase category. AgentAssist findings map to these template structures for PDF report design (T1.4).

- **templates/template-1-analytical-review.xlsx** — Steps 1, 2, and 4. Analytical review of GST declarations and financial-statement reconciliation.
- **templates/template-2-standard-rated.xlsx** — Step 3A. Standard-rated supplies and output tax checklist (including reverse charge, customer accounting, OVR regime).
- **templates/template-3-zero-rated.xlsx** — Step 3B. Zero-rated supplies checklist (exports, international services).
- **templates/template-4-exempt-property-financial.xlsx** — Step 3C-1. Exempt supplies checklist for businesses actively making exempt supplies (property developers, financial services, IPM, digital payment tokens).
- **templates/template-5-exempt-general.xlsx** — Step 3C-2. Exempt supplies checklist for general businesses with incidental exempt supplies.
- **templates/template-6-input-tax.xlsx** — Step 3D. Input tax and refunds claimed checklist (local purchases, imports with GST paid, TRS, Bad Debt Relief, reverse-charge refunds).
- **templates/template-7-imports-suspended-deferred.xlsx** — Step 3E. Imports with GST suspended (MES, A3PL, AISS, ACMT) or deferred (IGDS).

## How AgentAssist uses these files

These files are not loaded by the orchestrator at runtime. They serve three purposes:

1. **System-prompt and knowledge-base reference** — Claude's reasoning during chain execution cites these documents when interpreting findings.
2. **PDF report structure (T1.4)** — AgentAssist's signed PDF deliverable mirrors the IRAS Template structure so reviewers recognize the format.
3. **Developer reference** — Engineering and product decisions about which checks AgentAssist automates trace back to specific paragraphs in 01-annual-review-guide-16ed.pdf.

## Coverage analysis

See `exploration-notes/iras-ask-coverage-analysis.md` for the mapping of AgentAssist's current detection against each substantive check IRAS requires, plus the deterministic-vs-judgment matrix for the Pre-Filing Checklists.

## Update cadence

IRAS publishes new editions of the Annual Review Guide periodically; current is the Sixteenth Edition (30 Jan 2026). When IRAS publishes a new edition:
1. Replace `01-annual-review-guide-16ed.pdf` with the new edition (rename accordingly).
2. Re-download Templates 1–7 in case IRAS updated them in tandem.
3. Update the edition reference in this README.
4. Flag methodology changes in the project changelog and re-run the coverage gap analysis.

## Provenance

All files downloaded from the IRAS Section 3 Annual Review page:
https://www.iras.gov.sg/taxes/goods-services-tax-(gst)/getting-it-right/voluntary-compliance-initiatives/assisted-self-help-kit-(ask)/ask-section-3---annual-review