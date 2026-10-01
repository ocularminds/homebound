# FL-008 — Decionis live credentials are not configured

- **Date:** 2026-10-01
- **Component:** AgentSafe → Decionis Execution Authority → managed Presence
- **Environment:** HomeBound development shell
- **Expected:** Verify a live household decision and managed Presence escalation against a Decionis tenant.
- **Observed:** No Decionis API key, tenant UUID, or household approver identity is configured in the current environment.
- **Error:** No live request attempted; the credentials were not available.
- **Impact:** The production adapter path is implemented against the published AgentSafe HTTP contract, but live policy, dossier, and Presence results cannot be claimed or verified in this workspace yet.
- **Investigation:** The official executor requires `DECIONIS_API_URL`, `DECIONIS_API_KEY`, `EXECUTOR_TENANT_ID`, and a managed-mode `PRESENCE_APPROVER_ID`. The Python MCP client stores only its local AgentSafe caller token.
- **Workaround:** Keep the action path fail-closed until actual values are set in the ignored `agentsafe/.env`; never use a synthetic key or represent an offline test as a real decision.
- **Resolution:** Added the required variables to the local environment template and documented setup. Real API and Presence validation remains an onboarding step.
- **Upstream/documentation gap:** None for credentials; the live integration requires a provisioned tenant and approver identity.
- **Status:** Open; requires Decionis tenant configuration before a live escalation demo.
