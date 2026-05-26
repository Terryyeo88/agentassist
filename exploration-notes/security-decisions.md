# Security Decisions Log

## 2026-05-26: Credential exposure in git history (DEFERRED)

### Finding
During security review, credential files were found committed in the initial
commit (aec650f9, "Initial project structure - SAP B1 AI Agent POC"):
- keys/sap_credentials.json (SAP B1 demo credentials)
- keys/sap-b1-poc-sg.pem (SSH PEM for SAP CAL VM)

The file `gitignore` (missing leading dot) was non-functional, so `.gitignore`
protection did not apply at the time of the initial commit.

### Exposure assessment
- Remote: private GitHub repository
- Collaborators: one trusted collaborator (Collin), no further sharing
- CI/CD: none
- Third-party integrations: none
- Credentials in question: SAP B1 demo instance (manager/manager default),
  SAP CAL trial deployment at 35.186.145.230, SSH key for the CAL VM
- Practical risk at present: LOW (private repo, single trusted collaborator,
  demo-tier credentials, no production data accessible)

### Decision
Defer git history scrubbing. Do not rotate credentials at this time.

Rationale: pre-customer POC phase, no production data, no untrusted access
to the remote. Cost of scrubbing now (rewriting all commit SHAs, force-push,
re-syncing with collaborator) exceeds current risk reduction.

### Triggers that REVERSE this decision and require immediate action
Action required BEFORE any of the following events:
1. Making the GitHub repo public
2. Adding a non-trusted collaborator or any CI/CD service
3. Accepting payment, signed engagement, or LOI from any customer
4. Connecting the system to any non-demo SAP B1 instance
5. Storing any real client data in the repo or in connected systems
6. Applying to Anthropic Partner Network, BIG, or any program that may
   review security posture
7. Redeploying the SAP CAL instance (use this as a natural clean-slate
   opportunity — do not commit new credentials)

### Required actions when triggered
1. Rotate SAP B1 manager password
2. Regenerate or tear down the SAP CAL SSH key
3. Scrub history: `git filter-repo --path keys/ --invert-paths`, then
   force-push. Notify Collin to re-clone.
4. Verify with `git log --all --full-history -- keys/` returns empty
5. Update this log with the resolution date

### Owner
Terry Yeo. Review this decision monthly or at the next milestone, whichever
comes first.
