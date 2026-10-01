# FL-017 — Live tenant does not route HomeBound to managed Presence

- **Date:** 2026-10-01
- **Component:** Decionis tenant policy → AgentSafe managed escalation → Presence
- **Environment:** User's provisioned Decionis production workspace; no physical Ring device used
- **Expected:** A child request to disarm `home_security` matches a tenant ESCALATE rule with a Decionis authority block, and Decionis opens the parent's native Presence ceremony.
- **Observed:** The tenant's active policy bundle contains commerce rules only. The live HomeBound request reached Decionis after the AgentSafe action-name mapping was corrected, but Decionis omitted a managed escalation object.
- **Error:** HomeBound received `AUTHORITY_UNAVAILABLE` with reason code `MANAGED_ESCALATION_MISSING`.
- **Impact:** The Presence ceremony did not start, there is no approval to resume, and no Ring simulator or hardware execution occurred.
- **Investigation:** Compared the live bundle with the Commerce `PresenceManagedAuthority` implementation. A managed Presence handoff requires a matching ESCALATE policy rule with an authority block; HomeBound does not directly call Presence.
- **Workaround:** Keep the request fail-closed. Added `policies/homebound-household-policy.draft.json` as a local review artifact; it has not been submitted or activated. The user-provided camera-specific actions are not current MCP tools, so the draft uses vendor-neutral `home.security.disarm` and `home.entry.unlock` capabilities. The demo courier rules compare the local-time value to a provisional 14:00–15:00 window.
- **Resolution:** No tenant change made. A live Presence outcome requires review of the exact rule fields, authenticated signal provenance, and enrolled parent principal, followed by tenant dry-run validation.
- **Upstream/documentation gap:** Published examples show several policy shapes, and the workspace draft generator returned heuristic prose rather than an enforceable rule set when its LLM was unavailable. See FL-018.
- **Status:** Open; no authorization was granted and no device action ran.
