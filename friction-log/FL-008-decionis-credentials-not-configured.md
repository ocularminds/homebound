# FL-008 — Decionis live credentials are not configured

- **Date:** 2026-10-01
- **Component:** AgentSafe → Decionis Execution Authority → managed Presence
- **Environment:** HomeBound development shell
- **Expected:** Verify a live household decision and managed Presence escalation against a Decionis tenant.
- **Observed:** The user provisioned the Decionis API key in the ignored `agentsafe/.env`. The demo's safe preflight now reports only the tenant UUID and trusted household approver identity as missing.
- **Error:** No Decionis request attempted; preflight stopped before starting services because `EXECUTOR_TENANT_ID` and `PRESENCE_APPROVER_ID` are unset.
- **Impact:** The production adapter path is implemented against the published AgentSafe HTTP contract, but live policy, signed dossier, and Presence results cannot be claimed or verified until the tenant and approver are configured.
- **Investigation:** The official executor requires `DECIONIS_API_URL`, `DECIONIS_API_KEY`, `EXECUTOR_TENANT_ID`, and a managed-mode `PRESENCE_APPROVER_ID`. The Python MCP client stores only its local AgentSafe caller token.
- **Workaround:** Keep the action path fail-closed until the actual tenant UUID and approver identity are set in the ignored `agentsafe/.env`; never use a synthetic key or represent an offline test as a real decision.
- **Resolution:** The user provisioned the real API key locally. Required config names and safe preflight behavior are documented; tenant and approver configuration remain an onboarding step.
- **Upstream/documentation gap:** None for credentials; the live integration requires a provisioned tenant and approver identity.
- **Status:** Partially configured; requires `EXECUTOR_TENANT_ID` and `PRESENCE_APPROVER_ID` before a live authority or Presence demo.
