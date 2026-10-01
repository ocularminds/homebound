# FL-008 — Decionis live tenant policy prerequisite

- **Date:** 2026-10-01
- **Component:** AgentSafe → Decionis Execution Authority → managed Presence
- **Environment:** HomeBound development shell; local credentials are ignored by Git
- **Expected:** A live child disarm request reaches Decionis, opens a parent Presence approval, and remains non-executable until Decionis authorizes the exact intent.
- **Observed:** The user provisioned the Decionis API key, tenant ID, and trusted approver identity in local `agentsafe/.env`. A read-only tenant policy check found one active commerce policy and no HomeBound Ring rules. A live governed child-disarm request reached Decionis but returned `MANAGED_ESCALATION_MISSING`.
- **Error:** Decionis did not return the managed escalation object needed for a native Presence handoff. AgentSafe returned `AUTHORITY_UNAVAILABLE`; no Presence request or Ring execution occurred.
- **Impact:** Credentials are present, but they do not substitute for a tenant policy rule with a Decionis authority block. The live Presence approval path remains unverified.
- **Investigation:** The active policy is commerce-only. The AgentSafe managed mode and HomeBound resume path are configured; the current policy does not route this Ring action to the enrolled approver.
- **Workaround:** Keep the executor fail-closed. Prepare the review-only HomeBound draft in `policies/homebound-household-policy.draft.json`; do not infer a Presence principal ID from an email address.
- **Resolution:** Credentials configured. Tenant policy and live Presence handoff remain outstanding; details are tracked in FL-017.
- **Upstream/documentation gap:** The UI draft-generation service fell back to heuristics, so it did not produce an enforceable household policy. See FL-018.
- **Status:** Partially resolved; waiting for policy review and tenant validation.
