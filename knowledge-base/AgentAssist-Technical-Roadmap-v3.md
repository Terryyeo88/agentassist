AgentAssist Technical Roadmap v3 — Tier 1 Work Allocation
Revised from v1 to reflect three decisions made after v1 was written: (1) the orchestration layer is an explicit prompt-chaining workflow with deterministic gates, not an implicit side-effect of the launcher; (2) the knowledge base is modular per chain-step, not one monolithic file; (3) the V0→V3 process is correctly understood as a failure-driven development loop for discovering what to build, which recurs only for genuinely new reasoning workflows — not for pure infrastructure or for deriving deterministic tool internals (those come from the IRAS spec).
This version also splits Tier 1 work between Terry (Claude Max — takes the token-heavy, multi-file, agentic-coding-intensive tasks) and Collin (Claude Pro — takes contained, well-specified tasks). The split is at the end of each task and summarized in the allocation table.

What changed from v1, in one place
Read this before the tasks if you read v1.
New task T1.6 — Orchestration chain with inter-step gates. v1 folded orchestration implicitly into T1.3's launcher and T1.4's "run analysis then run report" flow. Per Anthropic's Building Effective Agents, the GST workflow is a prompt-chaining workflow: fetch → classify → calculate → detect → report, each step's output feeding the next, with programmatic gates between steps that halt on reconciliation failure. This is now explicit because the gates are a defensibility feature (they are where "fail loud, not silent" lives) and the chain is the backbone the report sits on. It is NOT a multi-agent system — subtasks are fixed and predictable, so a predefined code path is correct, simpler, cheaper, and more auditable than autonomous agents.


New architectural guardrail — knowledge base is modular per step. Per Anthropic's Effective Context Engineering, context is a finite resource and each chain step should receive only the regulatory slice relevant to its deliverable (classification step gets VatGroup→category rules; F5 step gets box-routing + FX rules; future F7 step gets disclosure thresholds). Do NOT build one massive KB fed to every step — it makes each call harder, degrades attention, and costs more tokens. Cross-step information flows forward as data (the prior step's structured output), not as merged knowledge bases.


V0→V3 reframed. v1's Final Reminder #1 implied V0→V3 is about maintaining layer separation. That's true but incomplete. V0→V3 was a failure-driven development loop: run base Claude, capture where it failed, use those failures to decide which tools to build and which guardrails to write. Two consequences: (a) deterministic tool internal logic comes from the IRAS spec, not from the loop — you encode what IRAS specifies, you don't iterate to discover it; (b) the loop recurs for genuinely new reasoning workflows (reverse charge, F7, partial exemption), because base Claude will fail on those in new ways you need to capture, but it does NOT recur for pure infrastructure (config, audit, report-gen) or for extending tools whose architecture is already validated.



Tier 1 — Required Before First Paying Customer
Revised critical path: ~6–7 weeks, up from v1's 5–6, because T1.6 (orchestration chain) is now explicit and gates T1.4 (the report consumes the chain's structured output through the gates). Sequencing:
T1.1 (credit notes), T1.2 (done), T1.3 (config) can run in parallel at the start.
T1.6 (orchestration chain) can begin once T1.1 lands (it sequences the tools, so the tools must be credit-note-correct first) and runs in parallel with T1.3.
T1.4 (report) starts when T1.1, T1.3, and T1.6 are all done — the report is a projection of the chain's gated output.
T1.5 (audit trail) follows T1.4.

T1.1 — Add credit note support to all three custom MCP tools
[Task internals unchanged from v1 — see v1 for full OData detail, output-field spec, fixture requirements, and architectural guardrails. Summary below.]
Extend calculate_f5_return, validate_invoice_tax_codes, and detect_gst_errors to fetch and net CreditNotes / PurchaseCreditNotes from box totals and apply the same E1–E4 classification. Credit-note logic comes from the IRAS spec (IRAS says deduct them; encode that) — this is not a case needing a V0→V3 loop. The one reasoning-surface check: after the tool returns net figures, confirm Claude correctly narrates that credit notes were handled and correctly flags credit-note-level errors. That is a single focused check, not a four-version cycle.
KB modularity note (new): the credit-note handling rules go into the GST-F5 knowledge-base slice (the current sg-tax-code-mappings.md or its successor), not into a new global file.
Effort: ~1 week. Blocks: T1.6, T1.4. Blocked by: nothing.
OWNER: COLLIN. Well-bounded, follows existing _fetch_*_paginated patterns, clear definition of done, contained to the three tools + reference script. Good first substantive task on Pro. Sequence it first for him because it gates the chain and the report.

T1.2 — Resolve the NR VatGroup compliance inconsistency
STATUS: DONE (Collin, prior to roadmap v2). Needs pull + verification.
Pull from the repo and verify the fix closed all four artefacts: the DoD requires F5_BOX_MAPPING (code), PURCHASE_BOX5 (reference script), the base.md routing table, AND the knowledge base to all agree on NR treatment, plus an nr-vatgroup-resolution.md citing the IRAS paragraph. "Done" is only true if all four agree and the resolution note exists. If any artefact is still out of sync, it is not done.
OWNER: TERRY (verification only). Quick check during the codebase-state review (see the Claude Code prompt accompanying this roadmap).

T1.3 — Per-client configuration model
[Task internals unchanged from v1 — YAML schema, loader validation, launcher, custom-VatGroup merge logic, definition of done all as specified in v1.]
One addition for v2: the launcher (run_agent.py) is also the natural home for invoking the orchestration chain (T1.6). Design the launcher so that "load config → validate → run chain" is one entry point. The config and the chain are separate concerns but share the launcher as their seam.
Effort: 1.5–2 weeks. Blocks: T1.4, T1.5, T1.6 (the chain needs config to know which client/SAP instance). Blocked by: nothing.
OWNER: TERRY. Token-heavy, multi-file refactor (server, reference script, system prompt, new loader, new launcher, validation logic). Exactly the kind of agentic multi-file work that benefits from Max headroom. Also on the critical path twice with T1.4 — see allocation note.

T1.6 — Orchestration chain with inter-step gates (NEW)
One-line summary: Implement the GST workflow as an explicit prompt-chaining pipeline — fetch → classify → calculate → detect → compile — where each step's structured output feeds the next, with deterministic programmatic gates between steps that halt the chain on reconciliation failure rather than producing a confident wrong result.
Estimated effort: 1.5–2 weeks.
Business reason: Right now the "orchestration" is Claude deciding conversationally which tools to call in which order. That is fine for a demo but not defensible for an engagement: you cannot easily audit "Claude chose to do X," but you can trivially audit "the chain ran steps 1–5 in this fixed order, here are each step's inputs, outputs, and gate results." The chain IS the defensibility architecture, and it is the backbone the report (T1.4) projects from. The gates are where the "fail loud, not silent" requirement lives — without them, a silent error (credit notes missed, a box that doesn't reconcile) flows straight into a signed report.
Detailed technical scope:
Pattern: prompt chaining (Anthropic, Building Effective Agents). Fixed, predictable steps → predefined code path, NOT a multi-agent system. The chain lives in code (likely orchestrator.py, invoked by the T1.3 launcher), not in Claude's conversational discretion.
Steps and dependencies:
Fetch — pull invoices, purchase invoices, credit notes, purchase credit notes for the period (once; shared input downstream).
Classify (validate_invoice_tax_codes) and Detect (detect_gst_errors) — these do not depend on each other; both depend only on fetched data, so they may run in parallel (parallelization within the chain where dependencies allow).
Calculate (calculate_f5_return) — depends on fetched data; may parallelize with step 2.
Compile — aggregate the three tool outputs into the structured object the report generator (T1.4) consumes.
Gates (the critical part): deterministic Python checks between steps. At minimum:
After Calculate: Box 4 == Box 1 + Box 2 + Box 3; Box 8 == Box 6 − Box 7 (within rounding tolerance). Halt if not.
After Fetch: record-count sanity (e.g., $inlinecount vs. fetched length — catches truncated pagination). Halt if mismatch.
After Compile: every finding references a real DocNum present in the fetched data. Halt on dangling reference.
A gate failure produces a clear, human-readable halt message naming the gate and the values that failed it — never a silent pass-through.
Where Claude sits: Claude is invoked at the reasoning step (over the already-computed deterministic outputs) to apply edge-case judgment and produce the narrative findings — once, on aggregated tool output, not as multiple agents. Each Claude invocation in the chain receives only the modular KB slice relevant to its step (per the context-engineering guardrail).
Dependencies:
Blocked by: T1.1 (the chain sequences the tools; tools must be credit-note-correct first), T1.3 (the chain needs config to resolve the client/SAP instance).
Blocks: T1.4 (the report projects the chain's gated output).
Can run in parallel with: T1.3 after T1.1 lands.
Definition of done:
Running the launcher for a client+period executes the full chain and produces a single aggregated structured output.
Each gate is tested: induce a reconciliation failure (e.g., a fixture where boxes don't sum) and confirm the chain halts with a clear message rather than emitting a result.
The parallel branch (classify/detect alongside calculate) produces identical output to a serial run (correctness must not depend on ordering of independent steps).
Each Claude invocation in the chain receives only its step's KB slice, verified by inspecting the assembled context.
The chain's step inputs/outputs and gate results are captured in a form the audit trail (T1.5) can consume.
Out of scope:
Dynamic subtask selection (orchestrator-workers). The steps are fixed; do not build runtime task decomposition. That is the Tier 2/Platform pattern for when multiple agents must be combined unpredictably.
Retry/backoff inside the chain — that is T2.4 (hardened error handling). The chain halts cleanly on failure for now; resilience comes later.
Multi-agent message passing. There are no agents talking to agents here.
Architectural guardrails:
The chain is a predefined code path. If you find yourself wanting Claude to decide the order of steps at runtime, stop — that is a different (agent) architecture and not what this is.


Gates are deterministic Python, never LLM calls. A gate that asks Claude "does this look right?" is not a gate.


The chain carries prior-step output forward as data; it does NOT carry prior-step knowledge bases forward. Data flows; regulatory context stays sliced per step.


OWNER: TERRY. New architecture, token-heavy to develop and test (lots of chain-and-gate iteration), and it is the backbone everything else sits on — you want your hands on it. Benefits from Max.



T1.4 — Minimal report generation (PDF deliverable)
[Task internals unchanged from v1 — design-phase questions, section structure, tool-confirmed vs judgment-required distinction, HTML+WeasyPrint/Playwright approach, form-field sign-off, versioning metadata, definition of done all as specified in v1.]
One change for v2: the report's data source is now the orchestration chain's aggregated output (T1.6), not three separate tool-call results the user pastes together. This makes the report generator's input contract cleaner — it consumes one structured object with the gate results included, so the "items not examined" and methodology sections can be populated from the chain's own record of what it did and what gates passed.
Effort: 2.5–3 weeks (design 1 week + implementation 1.5–2). Blocked by: T1.1, T1.3, T1.6 (new). Blocks: T2 scaling.
OWNER: TERRY. Biggest task, it IS the product, design phase needs your product judgment, heavy HTML/CSS/PDF iteration. The design doc (report-design.md) is reviewed by you anyway since you own the product. Take it.

T1.5 — Audit trail and input immutability
[Task internals unchanged from v1 — per-engagement directory structure, per-run artefacts, SHA-256 versioning, sealing, verify script, definition of done all as specified in v1.]
One addition for v2: the audit trail now also captures the chain's gate results (which gates ran, which passed, any halt). This strengthens the defensibility story — the trail shows not just what was computed but that the reconciliation checks passed before the report was produced.
Effort: 1.5–2 weeks. Blocked by: T1.3, T1.4. Blocks: nothing in Tier 1.
OWNER: COLLIN. Contained to the logging layer, clear artefact spec, doesn't need deep product judgment. He picks this up after T1.1, once T1.4 is far enough along.

Tier 1 — Allocation Summary
Task
Effort
Owner
Why this owner
Critical path?
T1.1 Credit notes
~1 wk
Collin
Bounded, pattern-following, contained
Yes — gates T1.6, T1.4
T1.2 NR resolution
done
Terry (verify)
Pull + 4-artefact check
No
T1.3 Per-client config
1.5–2 wk
Terry
Token-heavy multi-file refactor
Yes — gates T1.4/5/6
T1.6 Orchestration chain
1.5–2 wk
Terry
New architecture, backbone, token-heavy
Yes — gates T1.4
T1.4 Report generation
2.5–3 wk
Terry
The product; design + heavy iteration
Yes — deliverable
T1.5 Audit trail
1.5–2 wk
Collin
Contained logging layer
No (but defensibility)

Load check (read this — it's a real risk): This puts Terry on the critical path three times in sequence (T1.3 → T1.6 → T1.4) and loads Terry far heavier than Collin (≈5.5–7 weeks of Terry work vs. ≈2.5–3 of Collin). You asked for the heavy work because of Max, and this delivers that — but it means if you get pulled into pitch prep, BIG application, or investor conversations, the whole critical path slips, because the gating tasks are all yours.
Two mitigations if that becomes real:
Swap T1.3 to Collin. Config is contained enough for Pro (clear schema, clear validation spec). That frees you to run T1.6 → T1.4 without also carrying config, and parallelizes the load. The cost: config touches many files, so it's more token-hungry than ideal for Pro — but it's specified well enough to manage.
Sequence T1.6 before T1.3. The chain technically needs config only at the client-resolution seam; you could build and test the chain against the hardcoded SBODEMOSG path first, then wire in config when T1.3 lands. Decouples your two gating tasks somewhat.
Decide based on how much non-engineering load lands on you in the next 7 weeks.

Collin's First Two Weeks (revised)
The v1 plan had Collin do T1.2 first as an architecture-learning task. T1.2 is now done, so:
Days 1–2: Environment + codebase orientation. SAP CAL connection, Claude Desktop config, run the reference script against SBODEMOSG and confirm matching figures. Read AGENTASSIST_TECHNICAL_STATE.md and this roadmap. Crucially, walk the T1.2 NR fix he already did and confirm with Terry it closed all four artefacts — this re-grounds him in the four-artefact-consistency principle.
Days 3–5 and Week 2 days 1–3: T1.1 (credit notes). Largest correctness gap, additive, exercises the three-tool symmetry and the audit-not-partner principle (he implements credit-note logic twice — once in the tool, once in the reference script). Concrete win to show Terry. Gates the chain, so it must land first.
Week 2 days 4–5: Begin T1.5 (audit trail) design — sketch the per-engagement directory structure and the metadata schema, review with Terry. Don't implement yet (it's blocked by T1.3/T1.4); just get the design settled so it's ready when its dependencies clear.

Final Architectural Reminders (revised)
Carried from v1, with two additions (6 and 7):
Three-layer separation is non-negotiable. Deterministic tools do arithmetic. Knowledge base is reference content. System prompt orchestrates.
The reference script is the audit, not the partner. Independent implementation; no shared code; divergence flags bugs.
Claude does not assert compliance positions unilaterally. Never assert a compliance issue without tool-confirmed evidence. Preserve the "candidate for review" vs "confirmed error" distinction.
The reviewer signs off on every finding before submission. This is the product. No automatic filing, no automatic IRAS contact, at any tier.
Don't add skill abstraction until the product expands beyond one workflow.
(NEW) The knowledge base is modular per chain-step. Each step receives only its regulatory slice. Context is finite; one giant KB on every step makes each call harder and costs more. Cross-step information flows forward as data (prior step's structured output), never as merged knowledge bases.
(NEW) Orchestration is a predefined code path, not autonomous agents. The GST workflow is a prompt chain with deterministic gates. Subtasks are fixed and predictable, so a chain is correct — simpler, cheaper, more auditable than a multi-agent system. Gates are deterministic Python, never LLM calls. Reserve orchestrator-workers / multi-agent patterns for the Platform tier where subtask selection becomes genuinely unpredictable (combining multiple agents for a client whose needs vary at runtime).

Note on Tier 2 and Tier 3
Unchanged from v1, with one re-tagging: T2.3 (automated evaluation harness) gains importance because it's the mechanism that protects the reliability story over time. Once you've run the definitive reliability battery (20 runs × 3 tests on the report-producing workflow), T2.3 is what re-runs that battery automatically on every model upgrade or prompt edit, so the 30/30 doesn't silently regress. Still Tier 2 (not gating first revenue), but it's the durability mechanism for the single most important claim in your pitch. Flag it to whoever owns regression discipline.
Tier 2 — Required Before Scaling Beyond Initial Pilot
These are non-blocking for the first 1–2 friendly pilots but become real problems at 5+ clients or formal contracts.

T2.1 — Manual journal entry support
Effort: 1–1.5 weeks.
Business reason: Clients with active accounting practices post GST-relevant journals — VAT adjustments, year-end reclassifications, accruals. Currently invisible to the system. For a friendly pilot you can document this as "manual journals not examined" and the reviewer applies judgment; at scale, that becomes a competitive weakness.
Scope: Add JournalEntries queries to the three custom tools. Filter for entries touching GST-relevant accounts (config-specified per client, since chart-of-accounts varies). Apply per-line classification where the account context is GST-input or GST-output.
Hardest part: Identifying which journal lines are GST-relevant. SAP B1 doesn't tag this; it's inferred from the GL account. Per-client config will need a gst_accounts list.
Out of scope: Adjusting journals (where the journal creates GST that should be re-classified into a different box). That's a partial-exemption-class problem.

T2.2 — Custom VatGroup discovery and reporting
Effort: 1 week.
Business reason: When a client has non-standard VatGroups, the current system buckets them as "anomalies" and excludes from totals. That's safe (doesn't produce wrong numbers) but unhelpful — the reviewer needs to know which custom codes exist and what they should map to. At scale, this discovery becomes the first 2–3 hours of every new engagement.
Scope: Add a discover_vat_groups tool that runs once at engagement start, fetches all VatGroups present in the period, and produces a report of which are standard (mapped) versus custom (unmapped). For custom codes, surface sample DocNums and counterparties so the reviewer can determine the intended treatment. Update the per-client config to capture custom VatGroup decisions for re-use across future quarters.

T2.3 — Automated evaluation harness
Effort: 2–3 weeks.
Business reason: Right now, regression testing is "Terry remembers what V3 looked like and checks the new output by eye." That doesn't scale across model upgrades, prompt edits, or knowledge base revisions. An automated harness that runs the V0–V3 prompts against the current system and compares outputs to stored references is what protects the 30/30 result over time.
Scope: A harness that, given a stored prompt and a stored reference output, invokes the Claude API directly (not Claude Desktop) with the current system prompt/knowledge base/tools, captures the response, and computes a scoring vector against the reference. Run as a CI step on every meaningful change.
Hardest part: Scoring non-deterministic LLM output. Use structural checks (did the response include all required boxes? are the numbers within tolerance?) rather than text comparison. Numeric tolerance is fine for F5; structural tolerance for error findings.

T2.4 — Hardened error handling and retry logic
Effort: 1–2 weeks.
Business reason: SAP CAL instances are reliable; client SAP installations vary. Production engagements will hit transient 503s, session expirations mid-pagination, slow Service Layer responses. Currently the code raises on first failure beyond the one 401 retry. At scale, that produces "the system broke" reports during engagements.
Scope: Exponential backoff on 503/timeout (max 3 retries). Pagination resumption from $skip on transient failures. Session re-authentication on 401 mid-pagination. Partial-data detection via $inlinecount comparison. User-facing error messages that name the SAP entity and the failure mode.

T2.5 — FX conversion (Box-level SGD equivalent computation)
Effort: 1.5–2 weeks.
Business reason: Currently FX invoices are excluded and listed for manual conversion. Per IRAS rules, FX must be converted to SGD at the prevailing rate for F5 reporting. A real engagement either does this manually (slow, error-prone) or the system does it. Doing it in the system requires (a) a source of exchange rates, (b) the right rate concept (transaction date? IRAS-published rate? client's banking rate?), and (c) clear methodology disclosure.
Scope: Add convert_fx_to_sgd tool that takes the list of FX invoices and either (a) reads exchange rates from SAP B1's own rate table (which clients maintain), or (b) fetches from a configured rate source. Add converted values to F5 box totals. Disclose the rate source explicitly in the report.
Hardest part: The methodology choice. IRAS accepts the rate prevailing on the supply date; clients often use month-end rates. The config needs to capture the client's IRAS-accepted methodology.

T2.6 — Multi-quarter / rolling-period analysis
Effort: 1 week.
Business reason: Clients sometimes need year-end summaries or rolling 12-month views, not just single quarters. The current tools are quarter-scoped. At scale this becomes a request.
Scope: Tools accept arbitrary date ranges, not just quarters. Reports adapt to show period summary appropriately.

T2.7 — Client business-context profile (reasoning-layer surfacing aid)
Effort: 1.5–2 weeks (builds on the T1.3 config seam and the T2.2 discovery mechanism; not greenfield).
Business reason: The judgment band (the J/J+ ASK checks — "is this really an exempt supply? is this expense really blocked?") cannot be automated, because the deciding fact lives in the source document, not the invoice line. But the quality of the candidates the reasoning layer surfaces into that band can be improved with standing facts about the client. A profile capturing what kind of business this is (industry, whether it actively makes exempt supplies, scheme participation, related-party counterparties, GL-account semantics, the meaning of its custom VatGroups) lets Layer 2 raise better-informed candidates and suppress noise — fewer false positives on legitimately-exempt clients, sharper "worth-a-look" flags on counterparties whose nature contradicts the coding. At scale this also amortises the first-engagement onboarding cost (the reviewer's mapping decisions get captured once and reused each quarter). It does not shrink the judgment band; it makes the human's pass over it faster and the surfaced set more relevant.
Scope: Extend the per-client ClientConfig (T1.3) with a structured business_context block — industry/activity descriptors, actively_makes_exempt_supplies (already present), scheme flags (MES/IGDS), a related-party counterparty list, GL-account → GST-treatment hints, and custom-VatGroup intended-treatment decisions (populated from T2.2's discovery output). The reasoning step in the chain (T1.6) receives only the relevant slice of this profile (per the modular-KB-per-step guardrail) and uses it to weight and annotate candidates — never to compute box figures. The profile feeds Layer 2 only; Layer 1 (deterministic tools) and the reconciliation gates are untouched.
Hardest part — and it is a design problem, not a coding one: building the profile so it informs candidate-raising without creating blind spots. A profile that encodes expectations ("this client always zero-rates exports") can suppress detection of the exact deviations the engagement exists to catch, if a genuinely miscoded export now "matches the expectation." The profile must bias attention toward review, never auto-bless a pattern out of scrutiny.
Design constraints (non-negotiable, carried from the architectural invariants):
Inform, never auto-bless. Context may raise or annotate a candidate; it may never remove a transaction from review or mark it correct. No context entry can downgrade a finding to "no issue."
Surfaces, never asserts — even with context. The more the agent "knows" about a client, the stronger the pull to assert a verdict. Output must still cap at J+ / "candidate for review." A context-informed candidate is still a candidate, adjudicated by the human who signs.
Profile is reference data, not arithmetic. It lives in the config/KB layer and feeds only the reasoning step. It must never enter the deterministic tools, the box calculations, or the gates. orchestrator/ stays pure-Python and context-free.
Profile provenance is auditable. Each context entry records who asserted it and when (reviewer-supplied, discovery-derived, or carried-forward), so the audit trail (T1.5) can show what standing assumptions shaped the surfaced set.
Methodology note: Because this changes Layer 2 reasoning behaviour, it is a genuinely new reasoning workflow and therefore re-triggers the V0→V3 failure-driven loop — run base behaviour with and without the profile, capture where context inflates confidence or creates a blind spot, and write the guardrails from those captured failures. (This is unlike pure infrastructure, which does not recur the loop.)
Definition of done:
A client profile populates from T1.3 config plus T2.2 discovery output, and the reasoning step receives only its relevant slice (verified by inspecting assembled context).
A deliberate blind-spot test passes: seed a miscoded transaction that matches a profile expectation, and confirm the system still surfaces it as a candidate rather than suppressing it.
A confidence-inflation test passes: confirm no output asserts a verdict ("correctly exempt") regardless of how strongly the profile supports it; all judgment-band output remains "candidate for review."
The deterministic box figures and gate results are byte-identical with and without the profile loaded (proving the profile never touched Layer 1).
Profile-entry provenance is captured in the audit bundle.
Out of scope:
Closing or automating the judgment band. The human still adjudicates every J/J+ finding.
The Anthropic Skill packaging abstraction (Reminder #5 — single workflow; not earned yet). This is a config/KB extension, not a Skill.
Any path by which context computes, adjusts, or overrides an F5 box value.
Owner: Terry. Touches the reasoning layer and the surfaces-never-asserts invariant directly — needs the architect's hands. Not on the Tier 1 critical path; first pilots ship with the human owning the full judgment band.

Tier 3 — Required Before Specific External Milestones
These are gated by external review processes, not by customer demand.

T3.1 — SOC 2 readiness documentation
External trigger: Enterprise procurement (any client whose IT/legal review requires a vendor risk assessment).
Effort: 4–6 weeks for documentation; SOC 2 Type 1 audit is a separate 3–6 month engagement.
Business reason: Mid-market in-house finance teams often don't require SOC 2; advisory firms procurement processes might. The US references in your customer research (Black Ore, Kintsugi) treat SOC 2 as table stakes. Singapore-equivalent is DPTM (Data Protection Trustmark, SS 714:2025), which you've already tagged as a year-2 goal.
Scope: Documented security policies, access control documentation, vendor management, data handling procedures, incident response. Most of this is documentation of existing practices once T1.5 (audit trail) is in place.
Out of scope at this tier: Actual SOC 2 audit engagement. That's a different budget conversation.

T3.2 — PDPA compliance framework
External trigger: First paid engagement accessing real client data, OR Anthropic Partner Network application (depending on AP requirements).
Effort: 2–3 weeks with legal input.
Business reason: Singapore PDPA applies to any handling of personal data. Most invoice/GL data is B2B (not personal data), but counterparty contact fields (CardName for sole proprietors, contact persons) can be personal data. The system needs documented purpose limitation, data minimization, retention policy, and a Data Processing Agreement with Anthropic for the API path. The audit document already tags this.
Scope: Data handling policy document, client-facing DPA template, Anthropic data processing agreement evaluation, retention/destruction procedures (probably 7-year retention for tax workpapers per IRAS, then destruction).

T3.3 — BIG application technical exhibit
External trigger: BIG (Singapore government grant) application submission.
Effort: 2 weeks for application-specific artefacts.
Business reason: Terry mentioned this in the handover prompt. Without knowing BIG's specific requirements, I can only sketch. Generally these programs want: a technical architecture document (you have this), a demonstration of innovation (V0→V3 trajectory captures this), measurable outcomes (the 30/30 scoring on validated tests captures this), and a commercial roadmap (this document captures this).
Scope: Tailored exhibit assembling existing artefacts. Likely needs a video walk-through of a demo, formal architecture diagrams (the audit's data flow diagram is a starting point), and a written innovation statement.

T3.4 — Anthropic Partner Network application artefacts
External trigger: Anthropic AP application.
Effort: 1–2 weeks for application-specific artefacts.
Business reason: AP wants evidence that you use Claude well (the architectural sophistication is the story), have a real customer use case (Singapore GST is concrete), and have a path to scale.
Scope: Case study (V0→V3), technical write-up, sample deliverable (sanitized SBODEMOSG report).

T3.5 — Singapore SAP B1 reseller channel materials
External trigger: Conversations with named SAP B1 resellers (when they happen).
Effort: 2 weeks.
Business reason: The US playbook (Vertex/Kintsugi/CPA.com) routes through channel. Resellers need materials they can put in front of their clients — co-branded one-pager, pricing structure, engagement template, training material for their consultants.

Collin's First Two Weeks — The Three Highest-Leverage Tasks
If Collin starts Monday, here are the three things he should do in his first two weeks and why:
Week 1, days 1–3: T1.2 (NR VatGroup resolution). Rationale: This is a 1-day task that surfaces deep familiarity with the codebase, the knowledge base, the IRAS source material, and the four-artefact consistency requirement. By doing this task first, Collin learns the architecture by exercising it on a low-risk, high-clarity change. If he tries to fix it without understanding why all four artefacts exist, he'll learn the architectural principle through doing. The other 2 days of the first half-week are for environment setup (SAP CAL connection, Claude Desktop configuration, running the reference script against SBODEMOSG to confirm he gets matching figures).
Week 1, days 4–5 and Week 2, days 1–3: T1.1 (credit notes). Rationale: Largest correctness gap, additive change (low blast radius), exercises the three-tool symmetry, and produces a visible improvement to the test scores. Completing this gives Collin a concrete win to show Terry. Most importantly, it forces him to think about how the reference script and the MCP tools stay in sync — the audit-not-partner principle becomes tangible when he has to implement the same logic twice.
Week 2, days 4–5: Start T1.3 (per-client config) design phase. Not implementation yet — the design phase. The config schema is a decision with downstream consequences; getting it wrong costs weeks later. Have Collin draft config/clients/example.yaml and the loader interface, and review with Terry before he writes the substantive code. This sets up week 3 for the actual implementation.
The reason for this ordering: T1.2 teaches the architecture cheaply, T1.1 produces value while reinforcing the lessons, T1.3 is the gating task for T1.4 and T1.5 so we need its design settled by end of week 2. T1.4 (report) is intentionally not in the first two weeks because its design phase deserves more than a week and Terry needs to be heavily involved in the product design.

Final Architectural Reminders for Collin
I want to close the roadmap with the architectural principles in one place, because they're scattered through the task descriptions and that's not durable enough for a multi-week reference document.
1. Three-layer separation is non-negotiable. Deterministic tools do arithmetic. Knowledge base is reference content for Claude's reasoning. System prompt orchestrates. When you find yourself wanting to put arithmetic in the system prompt, or routing logic in the knowledge base, or domain knowledge in the tool code, stop and reconsider. The V0→V3 trajectory exists because this separation was maintained; violating it regresses to V0.
2. The reference script is the audit, not the partner. run_baseline_tests.py independently implements the same logic as the MCP tools. They do not share code. When you change the MCP tool, you change the reference script separately, and the test for "did you do it right" is that both produce the same numbers on the same data. This independence is what lets you defend a number to a sophisticated reviewer. If you import functions across the boundary, you destroy the audit value.
3. Claude does not assert compliance positions unilaterally. The system prompt's compliance assertion rule ("never assert a compliance issue without tool-confirmed evidence") is the architectural constraint that prevents V0/V1 fabrications. When you write new system prompt content, preserve this. When you add new tool output formats, preserve the distinction between "candidate for review" and "confirmed error."
4. The reviewer signs off on every finding before submission. This is the product, not just a marketing line. Architectural decisions that imply the system can produce un-reviewed compliance assertions (e.g., automatic filing, automatic email to IRAS) are out of scope at any tier of this roadmap.
5. Don't add skill abstraction until product expands beyond single workflow. Anthropic's skill packaging exists for a reason; it isn't that reason yet. The current product is one workflow (GST F5 review for Singapore SAP B1). When the product becomes "GST F5 + IGDS + Malaysia SST," the skill abstraction earns its place. Until then, the system prompt is fine as a single document.
