# FL-017 — Live tenant does not route HomeBound to managed Presence

- **Date:** 2026-10-01
- **Component:** Decionis tenant policy → AgentSafe managed escalation → Presence
- **Environment:** User's provisioned Decionis production workspace; no physical Ring device used
- **Expected:** A child request to disarm `home_security` matches a tenant ESCALATE rule with a Decionis authority block, and Decionis opens the parent's native Presence ceremony.
- **Observed:** The tenant's active policy bundle contains commerce rules only. The live HomeBound request reached Decionis after the AgentSafe action-name mapping was corrected, but Decionis omitted a managed escalation object.
- **Error:** HomeBound received `AUTHORITY_UNAVAILABLE` with reason code `MANAGED_ESCALATION_MISSING`.
- **Impact:** The Presence ceremony did not start, there is no approval to resume, and no Ring simulator or hardware execution occurred.
- **Investigation:** Compared the live bundle with the Commerce `PresenceManagedAuthority` implementation. A managed Presence handoff requires a matching ESCALATE policy rule with an authority block; HomeBound does not directly call Presence.
- **Workaround:** At the time, kept the request fail-closed and prepared a review artifact. The user-provided camera-specific actions are not current MCP tools, so HomeBound uses vendor-neutral `home.security.disarm` and `home.entry.unlock` capabilities.
- **Resolution:** Superseded on 2026-10-02 by publication of `homebound-household-v1` through Decionis Protocol. The publication added an enabled managed ESCALATE rule and its `APPROVER` authority block; the publishing script validates and verifies the stored version. Presence approval still requires a real parent to complete its ceremony. Trusted signal provenance remains a production-device prerequisite.
- **Upstream/documentation gap:** Published examples show several policy shapes, and the workspace draft generator returned heuristic prose rather than an enforceable rule set when its LLM was unavailable. See FL-018.
- **Status:** The missing-policy blocker is resolved. The original request did not open Presence; a fresh request against the published rule is required to exercise the real Presence flow.
