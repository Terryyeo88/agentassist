# AgentAssist — Documentation Map

The index of every canonical document: what it is, where it lives, who it is for, and which
doc is **authoritative** for which facts. When two docs touch the same subject, the
*Authoritative for* column says which one wins — the other should **link, not restate**.

> **Docs-sync definition-of-done.** A feature is not "done" until every docs-sync target below
> that the change touches is updated. In-repo docs are enforced in the PR flow; the out-of-repo
> pedagogical docs are synced **manually** on the same definition-of-done until they move in-repo
> (see *Pending move* at the bottom).

---

## In-repo — version-controlled, in the PR / docs-sync flow

| Doc | Path | Type | Audience | Authoritative for |
|---|---|---|---|---|
| Technical State | `AGENTASSIST_TECHNICAL_STATE.md` | Status / inventory | Terry, Collin | **Current build state, test counts, what is merged.** Every other doc defers counts here. |
| Technical Roadmap v5 | `knowledge-base/AgentAssist-Technical-Roadmap-v5.md` | Plan | Terry, Collin | **Task definitions, sequencing, dependencies, planned-vs-done.** |
| IRAS-ASK Coverage Analysis | `exploration-notes/iras-ask-coverage-analysis.md` | Reference / gap-analysis | Terry, GST specialist | **Which ASK review steps are covered, by which check, and the remaining gaps.** |
| SG Tax-Code → F5 Mappings | `knowledge-base/sg-tax-code-mappings.md` | Reference (domain) | Terry, Collin, GST specialist | **VatGroup → F5-box routing, code lists, per-box rules, IRAS paragraph citations.** The SSOT for any domain fact the code encodes. |
| System Prompt | `system-prompts/base.md` | Operational artifact | the model (+ Terry) | The model-facing encoding of the routing rules. Mirrors the mappings doc **by necessity** — keep the two in lockstep; the mappings doc is the human reference, this is the prompt. |
| Merge Gates | `docs/merge-gates.md` | Process | Terry, Collin, CI | **The enforced gates** (import-scan, flake8, cage invariants) a PR must pass. |
| Operational Backlog | `exploration-notes/operational-backlog.md` | Process / backlog | Terry | Open operational items not yet scheduled as roadmap tasks. |

## Out-of-repo — Google Docs; pedagogical; **markdown-sourced, .docx generated for reading**

| Doc | Type | Audience | Authoritative for | Defers to |
|---|---|---|---|---|
| Accounting Domain Knowledge | Explanation (domain) | Terry, Claude, future specialist | *Why* the GST rules work as they do; how to reason about edge cases. | **Domain tables/codes → `sg-tax-code-mappings.md`.** Explain and link; do not restate the tables. |
| Technical Understanding — Agentic Shell | Explanation (low-level) | Terry, Claude | How the Tier-5 agent shell is built (engine seam, cage, loop, eval, demo). | **Counts/status → Technical State. Task status → Roadmap.** |
| Technical Understanding — Non-Agentic | Explanation (low-level) | Terry, Claude | How the deterministic engine + MCP tools work. | **Counts/status → Technical State. Domain facts → mappings doc.** |

## Upstream source material — *not our documentation*

The IRAS e-Tax Guides and ASK Annual Review templates are **upstream ground truth**, not docs we
author. They are the authority *behind* our domain docs: `sg-tax-code-mappings.md` is our encoding
of them, and any domain claim ultimately traces to an IRAS paragraph. Kept for reference and
verification; never edited, never indexed as our own docs.

---

## Source-of-truth & format conventions

- **Each out-of-repo doc's source of truth is its markdown file**, not the `.docx`. The `.docx`
  is a generated, shareable *view*:
  `pandoc source.md --reference-doc=<previous>.docx -o out.docx`.
  **Never hand-edit the `.docx`** — edits there are lost on the next regenerate. Edit the markdown.
- **Working / session notes** under `exploration-notes/<task>/` are *evidence*, not canonical
  docs. They are not docs-sync targets and are not indexed here.
- **Counts are point-in-time everywhere except Technical State.** Any doc that mentions a test
  count must defer to `AGENTASSIST_TECHNICAL_STATE.md` for the authoritative number.

## Pending move (gated on the credential scrub)

The three out-of-repo pedagogical docs move **in-repo under `docs/`** once the git-history
credential scrub (`aec650f9`) lands — at which point they join *automatic* docs-sync instead of
manual. Until then they are markdown-sourced and synced by hand on the same definition-of-done.